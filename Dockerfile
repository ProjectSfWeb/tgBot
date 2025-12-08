# Используем Python 3.11 slim
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Установка системных зависимостей для корректной работы парсинга и openpyxl (шрифты, locale при необходимости)
RUN apt-get update && apt-get install -y \
    locales \
    tzdata \
    unzip \
    && rm -rf /var/lib/apt/lists/*

# Локаль (опционально)
RUN sed -i '/ru_RU.UTF-8/s/^# //g' /etc/locale.gen && locale-gen

WORKDIR /app

COPY requirements.txt /app/
RUN pip install --no-cache-dir -r requirements.txt

COPY app /app/app

# Пользователь без root (опционально)
RUN useradd -ms /bin/bash botuser
USER botuser

CMD ["python", "-m", "app.main"]