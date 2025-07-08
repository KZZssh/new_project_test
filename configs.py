import pathlib
import os

FLASK_UPLOAD_URL = os.getenv("FLASK_UPLOAD_URL", "https://flask-media-server.fly.dev/upload")


# Берем токен из "секретов" Fly.io (переменных окружения)
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Проверка, что токен существует. Если нет, приложение упадет с понятной ошибкой.
if not BOT_TOKEN:
    raise ValueError("Секрет BOT_TOKEN не найден! Установите его командой: fly secrets set BOT_TOKEN=...")






ADMIN_IDS = [7955438947]           # Список id админов
DB_FILE = pathlib.Path(__file__).parent.joinpath("shop.db")
ITEMS_PER_PAGE = 5