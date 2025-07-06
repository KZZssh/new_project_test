import sqlite3
import pathlib

DB_FILE = pathlib.Path(__file__).parent.joinpath("shop.db")
connection = sqlite3.connect(DB_FILE)
cursor = connection.cursor()

cursor.execute('''
CREATE TABLE IF NOT EXISTS product_media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER,
    variant_id INTEGER,
    file_id TEXT NOT NULL,
    is_video BOOLEAN DEFAULT 0,
    "order" INTEGER DEFAULT 0,
    FOREIGN KEY (product_id) REFERENCES products (id),
    FOREIGN KEY (variant_id) REFERENCES product_variants (id)
)
''')
print("Таблица 'product_media' создана (или уже существовала).")




connection.commit()
connection.close()
print(f"\n✅ Миграция базы данных '{DB_FILE}' завершена!")