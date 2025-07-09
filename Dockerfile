# Используем минимальный и стабильный образ
FROM python:3.11.9-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем зависимости (сначала requirements, чтобы использовать кэш)
COPY requirements.txt .

# Установка зависимостей
RUN pip install --no-cache-dir -r requirements.txt


RUN apt-get update && apt-get install -y sqlite3

# Копируем весь код проекта
COPY . .

# Указываем порт, который прослушивает приложение (не обязателен для бота, но нужно для Fly)
ENV PORT=8080

# Команда запуска
CMD ["python", "main.py"]
