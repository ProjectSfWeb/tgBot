import asyncio
import io
import os
from datetime import datetime

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile, Document
from dotenv import load_dotenv

from app.processing.parser import parse_telegram_export_streams
from app.processing.extractor import extract_entities
from app.processing.excel import build_excel_workbook
from app.utils.temp import SessionAccumulator, InMemoryFile

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
MAX_FILES_HINT = int(os.getenv("MAX_FILES_HINT", "10"))

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()
dp.include_router(router)

# В памяти храним по user_id: список файлов, пока не вызовут /process
sessions = {}

HELP_TEXT = (
    "Этот бот принимает экспорт истории чата из Telegram (JSON/HTML/ZIP) и извлекает участников.\n\n"
    "Как пользоваться:\n"
    "1) Выгрузите историю чата в Telegram Desktop (Настройки -> Advanced -> Export Telegram data).\n"
    "2) Отправьте файл(ы) экспорта сюда (рекомендуем не более {max_files} за одну отправку).\n"
    "3) После загрузки отправьте команду /process.\n\n"
    "Результат:\n"
    "- Если < 50 участников: получите список @username в чате.\n"
    "- Если ≥ 51: получите Excel с вкладками: Участники, Упоминания, Каналы.\n\n"
    "Конфиденциальность: файлы не сохраняются на сервере, обработка происходит в оперативной памяти."
).format(max_files=MAX_FILES_HINT)


@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(
        "Привет! Я помогу извлечь список участников из экспорта истории чата Telegram.\n\n" + HELP_TEXT
    )


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP_TEXT)


@router.message(F.document)
async def handle_document(message: Message):
    doc: Document = message.document
    file_name = doc.file_name or "unknown"
    mime_type = doc.mime_type or ""

    # Разрешённые форматы: .json, .html, .zip
    lower = file_name.lower()
    if not (lower.endswith(".json") or lower.endswith(".html") or lower.endswith(".zip")):
        await message.answer("Пожалуйста, отправьте файл экспорта Telegram: .json, .html или .zip")
        return

    # Скачиваем файл в память
    file = await bot.get_file(doc.file_id)
    file_bytes = await bot.download_file(file.file_path)
    data = await file_bytes.read()

    user_id = message.from_user.id if message.from_user else message.chat.id

    acc: SessionAccumulator = sessions.get(user_id) or SessionAccumulator()
    acc.add_file(InMemoryFile(name=file_name, mime=mime_type, data=data))
    sessions[user_id] = acc

    await message.answer(
        f"Файл '{file_name}' принят. Всего загружено: {acc.count()}.\n"
        f"Отправьте /process для обработки. Рекомендуем загружать не более {MAX_FILES_HINT} файлов за раз."
    )


@router.message(Command("process"))
async def cmd_process(message: Message):
    user_id = message.from_user.id if message.from_user else message.chat.id
    acc: SessionAccumulator = sessions.get(user_id)
    if not acc or acc.count() == 0:
        await message.answer("Нет загруженных файлов. Сначала отправьте экспорт истории чата.")
        return

    await message.answer("Обработка начата, пожалуйста, подождите...")

    # Парсинг экспортов
    try:
        parsed_items = parse_telegram_export_streams(acc.files)
    except Exception as e:
        await message.answer(f"Ошибка при разборе файлов: {e}")
        acc.clear()
        return

    # Извлечение сущностей
    entities = extract_entities(parsed_items)

    # Фильтрация дублей и удалённых
    participants = entities["participants"]
    mentions = entities["mentions"]
    channels = entities["channels"]

    # Решение по отправке
    if len(participants) < 50:
        # Список в чат
        usernames = sorted({p.get("username") for p in participants if p.get("username")})
        if not usernames:
            await message.answer("Не удалось извлечь ни одного username из участников.")
        else:
            # Отправляем компактный список
            chunk = "\n".join(f"@{u}" if not u.startswith("@") else u for u in usernames)
            await message.answer("Участники (<50):\n" + chunk)
    else:
        # Excel
        try:
            buf = io.BytesIO()
            export_date = datetime.utcnow()
            wb = build_excel_workbook(
                participants=participants,
                mentions=mentions,
                channels=channels,
                export_date=export_date,
            )
            wb.save(buf)
            buf.seek(0)
            input_file = FSInputFile(buf, filename=f"chat_members_{export_date.date()}.xlsx")
            await message.answer_document(input_file, caption="Excel с участниками, упоминаниями и каналами.")
        except Exception as e:
            await message.answer(f"Ошибка при формировании Excel: {e}")

    # Очистка сессии
    acc.clear()
    sessions.pop(user_id, None)


async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())