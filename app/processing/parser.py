import io
import json
import zipfile
from typing import List, Dict, Any
from bs4 import BeautifulSoup
import chardet

from app.utils.temp import InMemoryFile


def _decode_bytes_auto(data: bytes) -> str:
    """
    Автоопределение кодировки и декодирование.
    """
    res = chardet.detect(data)
    enc = res.get("encoding") or "utf-8"
    try:
        return data.decode(enc, errors="replace")
    except Exception:
        return data.decode("utf-8", errors="replace")


def _parse_json_text(text: str) -> Dict[str, Any]:
    """
    Ожидаемый формат Telegram Desktop: result.json с messages и profile/participants.
    """
    return json.loads(text)


def _parse_html_text(text: str) -> Dict[str, Any]:
    """
    Парсинг messages.html: извлекаем авторов, текст сообщений, упоминания и отметки каналов.
    Возвращаем унифицированную структуру:
    {
      "messages": [
         {
           "from": {"name": "...", "username": "...", "is_channel": False},
           "text": "message text",
           "mentions": ["username1", "username2"]
         },
         ...
      ]
    }
    """
    soup = BeautifulSoup(text, "html5lib")
    messages = []
    for msg_div in soup.find_all("div", class_="message"):
        # Автор
        from_name = None
        from_username = None
        is_channel = False

        from_div = msg_div.find("div", class_="from_name")
        if from_div:
            from_name = from_div.get_text(strip=True)

        # Telegram экспорт иногда содержит ссылку на профиль/канал
        # Попробуем найти username по ссылке
        link = msg_div.find("a", href=True)
        if link and link["href"].startswith("https://t.me/"):
            uname = link["href"].split("/")[-1]
            if uname:
                from_username = uname
                # Эвристика: если from_name выглядит как имя канала и нет явного пользователя
                if "channel" in msg_div.get("class", []):
                    is_channel = True

        # Текст сообщения
        text_div = msg_div.find("div", class_="text")
        text_content = text_div.get_text("\n", strip=True) if text_div else ""

        # Упоминания
        mentions = []
        for a in msg_div.find_all("a", href=True):
            href = a["href"]
            if href.startswith("https://t.me/"):
                uname = href.split("/")[-1]
                if uname and uname not in mentions:
                    mentions.append(uname)
            # Также ищем явные @username в тексте
        for t in text_content.split():
            if t.startswith("@") and len(t) > 1:
                uname = t[1:].strip().strip(",.;:!?()[]{}\"'")
                if uname and uname not in mentions:
                    mentions.append(uname)

        messages.append(
            {
                "from": {
                    "name": from_name,
                    "username": from_username,
                    "is_channel": is_channel,
                },
                "text": text_content,
                "mentions": mentions,
            }
        )

    return {"messages": messages}


def _parse_zip(data: bytes) -> Dict[str, Any]:
    """
    Распаковка ZIP: ищем result.json или messages.html. Если оба — объединяем.
    """
    result: Dict[str, Any] = {"messages": []}
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        # Попробуем стандартные имена
        json_candidates = [n for n in zf.namelist() if n.endswith("result.json")]
        html_candidates = [n for n in zf.namelist() if n.endswith("messages.html")]

        # JSON
        for name in json_candidates:
            with zf.open(name, "r") as f:
                txt = _decode_bytes_auto(f.read())
                j = _parse_json_text(txt)
                # Нормализуем из JSON
                msgs = []
                for m in j.get("messages", []):
                    from_obj = {}
                    # Telegram JSON формат может иметь поля 'from', 'from_id', 'from_user', 'forwarded_from', т.п.
                    author_name = m.get("from")
                    author_username = m.get("from_username") or m.get("author_username")
                    is_channel = m.get("type") == "channel" or m.get("from_id", "").startswith("channel")
                    from_obj = {"name": author_name, "username": author_username, "is_channel": is_channel}

                    text_content = ""
                    if isinstance(m.get("text"), str):
                        text_content = m.get("text")
                    elif isinstance(m.get("text"), list):
                        # Telegram экспорт может представлять текст как массив объектов/строк
                        parts = []
                        for t in m["text"]:
                            if isinstance(t, str):
                                parts.append(t)
                            elif isinstance(t, dict) and "text" in t:
                                parts.append(t["text"])
                        text_content = " ".join(parts)

                    mentions = []
                    # Извлекаем упоминания из entities, если есть
                    for e in m.get("entities", []):
                        if isinstance(e, dict):
                            url = e.get("url") or ""
                            if url.startswith("https://t.me/"):
                                uname = url.split("/")[-1]
                                if uname and uname not in mentions:
                                    mentions.append(uname)
                    # А также из текста напрямую
                    for token in text_content.split():
                        if token.startswith("@") and len(token) > 1:
                            uname = token[1:].strip(",.;:!?()[]{}\"'")
                            if uname and uname not in mentions:
                                mentions.append(uname)

                    msgs.append({"from": from_obj, "text": text_content, "mentions": mentions})
                result["messages"].extend(msgs)

        # HTML
        for name in html_candidates:
            with zf.open(name, "r") as f:
                txt = _decode_bytes_auto(f.read())
                parsed_html = _parse_html_text(txt)
                result["messages"].extend(parsed_html.get("messages", []))

    return result


def parse_telegram_export_streams(files: List[InMemoryFile]) -> Dict[str, Any]:
    """
    Принимает несколько файлов экспорта, возвращает объединённую структуру:
    {"messages": [...]}.

    Обработка «на лету», без записи на диск.
    """
    aggregated: Dict[str, Any] = {"messages": []}

    for f in files:
        name = (f.name or "").lower()
        if name.endswith(".json"):
            text = f.data.decode("utf-8")
            j = _parse_json_text(text)
            msgs = []
            for m in j.get("messages", []):
                author_name = m.get("from")  # имя автора
                from_id = m.get("from_id", "")

                # username НЕ существует => берем только None
                author_username = None

                # канал определяется только так:
                is_channel = from_id.startswith("channel")

                from_obj = {
                    "name": author_name,
                    "username": author_username,
                    "is_channel": is_channel
                }

                text_content = ""
                if isinstance(m.get("text"), str):
                    text_content = m.get("text")
                elif isinstance(m.get("text"), list):
                    parts = []
                    for t in m["text"]:
                        if isinstance(t, str):
                            parts.append(t)
                        elif isinstance(t, dict) and "text" in t:
                            parts.append(t["text"])
                    text_content = " ".join(parts)

                mentions = []
                for e in m.get("entities", []):
                    if isinstance(e, dict):
                        url = e.get("url") or ""
                        if url.startswith("https://t.me/"):
                            uname = url.split("/")[-1]
                            if uname and uname not in mentions:
                                mentions.append(uname)
                for token in text_content.split():
                    if token.startswith("@") and len(token) > 1:
                        uname = token[1:].strip(",.;:!?()[]{}\"'")
                        if uname and uname not in mentions:
                            mentions.append(uname)

                msgs.append({"from": from_obj, "text": text_content, "mentions": mentions})
            aggregated["messages"].extend(msgs)
        elif name.endswith(".html"):
            text = f.data.decode("utf-8")
            parsed_html = _parse_html_text(text)
            aggregated["messages"].extend(parsed_html.get("messages", []))
        elif name.endswith(".zip"):
            parsed_zip = _parse_zip(f.data)
            aggregated["messages"].extend(parsed_zip.get("messages", []))
        else:
            # Игнорируем неподдерживаемые (но сюда не попадём, фильтруется ранее)
            continue

    return aggregated