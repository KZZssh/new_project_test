import pathlib
import os

FLASK_UPLOAD_URL = os.getenv("FLASK_UPLOAD_URL", "https://flask-media-server.fly.dev/upload")


# Берем токен из "секретов" Fly.io (переменных окружения)
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Проверка, что токен существует. Если нет, приложение упадет с понятной ошибкой.
if not BOT_TOKEN:
    raise ValueError("Секрет BOT_TOKEN не найден! Установите его командой: fly secrets set BOT_TOKEN=...")






ADMIN_IDS = [7955438947]           # Список id админов
# Указываем путь к базе данных ВНУТРИ постоянного диска (volume)
DB_FILE = "/data/shop.db" # Путь к базе данных, которая будет храниться на постоянном диске Fly.io
ITEMS_PER_PAGE = 5