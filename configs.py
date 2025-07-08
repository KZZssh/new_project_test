import pathlib
import os

FLASK_UPLOAD_URL = os.getenv("FLASK_UPLOAD_URL", "https://flask-media-server.fly.dev/upload")

BOT_TOKEN = "7014521370:AAHgMni3jXKU4n0hz7l-hFXigTTvseK8yiE"



ADMIN_IDS = [7955438947]           # Список id админов
DB_FILE = pathlib.Path(__file__).parent.joinpath("shop.db")
ITEMS_PER_PAGE = 5