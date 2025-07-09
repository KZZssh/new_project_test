import sqlite3
import pathlib
import os

# --- ИСПРАВЛЕНО: Путь к базе данных на постоянном диске ---
# Убеждаемся, что папка /data существует (на сервере Fly.io она будет)
os.makedirs("/data", exist_ok=True) 
DB_FILE = "/data/shop.db"

connection = sqlite3.connect(DB_FILE)
cursor = connection.cursor()
print("Начинаю полную перестройку базы данных...")

# --- 0. Удаляем старые таблицы, чтобы избежать конфликтов ---
cursor.execute("DROP TABLE IF EXISTS product_media")  
cursor.execute("DROP TABLE IF EXISTS product_variants")
cursor.execute("DROP TABLE IF EXISTS products")
cursor.execute("DROP TABLE IF EXISTS orders")
cursor.execute("DROP TABLE IF EXISTS sub_categories")
cursor.execute("DROP TABLE IF EXISTS categories")
cursor.execute("DROP TABLE IF EXISTS brands")
cursor.execute("DROP TABLE IF EXISTS sizes")
cursor.execute("DROP TABLE IF EXISTS colors")
print("Старые таблицы удалены.")

# --- 1. Таблицы-справочники ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
)
''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS sub_categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    category_id INTEGER NOT NULL,
    FOREIGN KEY (category_id) REFERENCES categories (id)
)
''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS brands (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
)
''')
print("Таблицы-справочники созданы (categories, sub_categories, brands).")

cursor.execute('''
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT,
    category_id INTEGER,
    sub_category_id INTEGER,
    brand_id INTEGER,
    FOREIGN KEY (category_id) REFERENCES categories (id),
    FOREIGN KEY (sub_category_id) REFERENCES sub_categories (id),
    FOREIGN KEY (brand_id) REFERENCES brands (id)
)
''')
print("Таблица 'products' создана.")

cursor.execute('''
CREATE TABLE IF NOT EXISTS sizes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
)
''')
cursor.execute('''
CREATE TABLE IF NOT EXISTS colors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE
)
''')
print("Таблицы 'sizes' и 'colors' созданы.")

# --- 2. Таблица с вариантами товаров (добавлен photo_id и photo_url) ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS product_variants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL,
    size_id INTEGER,
    color_id INTEGER,
    price REAL NOT NULL,
    quantity INTEGER NOT NULL DEFAULT 0,
    photo_id TEXT,
    photo_url TEXT,
    FOREIGN KEY (product_id) REFERENCES products (id),
    FOREIGN KEY (size_id) REFERENCES sizes (id),
    FOREIGN KEY (color_id) REFERENCES colors (id)
)
''')
print("Таблица 'product_variants' создана с photo_id и photo_url.")

# --- 3. Таблица с медиафайлами (добавлен url) ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS product_media (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER,
    variant_id INTEGER,
    file_id TEXT NOT NULL,
    is_video BOOLEAN DEFAULT 0,
    "order" INTEGER DEFAULT 0,
    url TEXT,
    FOREIGN KEY (product_id) REFERENCES products (id),
    FOREIGN KEY (variant_id) REFERENCES product_variants (id)
)
''')
print("Таблица 'product_media' создана с url.")

# --- 4. Таблица заказов ---
cursor.execute('''
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    user_name TEXT NOT NULL,
    user_address TEXT NOT NULL,
    user_phone TEXT NOT NULL,
    cart TEXT NOT NULL,
    total_price REAL NOT NULL,
    status TEXT,
    deducted_from_stock INTEGER DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
''')
print("Таблица 'orders' создана.")

# --- Завершаем ---
connection.commit()
connection.close()
print(f"\n✅ База данных '{DB_FILE}' успешно пересоздана с полной структурой!")
