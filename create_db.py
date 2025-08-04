import asyncio
import os
import aiosqlite

# --- ВАЖНО: Импортируем путь к БД из единого источника ---
from configs import DB_FILE

async def main():
    """Асинхронно пересоздает структуру базы данных с использованием aiosqlite."""
    
    # Убеждаемся, что папка /data существует
    db_dir = os.path.dirname(DB_FILE)
    if not os.path.exists(db_dir):
        os.makedirs(db_dir)
        print(f"Создана директория: {db_dir}")

    # Удаляем старый файл БД, если он существует, для чистого старта
    if os.path.exists(DB_FILE):
        os.remove(DB_FILE)
        print(f"Старый файл базы данных '{DB_FILE}' удален.")

    async with aiosqlite.connect(DB_FILE) as db:
        print(f"Подключаюсь к базе данных по пути: {DB_FILE}")
        print("Начинаю полную перестройку базы данных...")

        # --- 1. Таблицы-справочники ---
        await db.execute('''
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
        ''')
        await db.execute('''
        CREATE TABLE sub_categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            category_id INTEGER NOT NULL,
            FOREIGN KEY (category_id) REFERENCES categories (id),
            UNIQUE(name, category_id)
        )
        ''')
        await db.execute('''
        CREATE TABLE brands (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
        ''')
        print("Таблицы-справочники созданы (categories, sub_categories, brands).")

        await db.execute('''
        CREATE TABLE products (
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
        # Дополнительно создаем уникальный индекс для sku для надежности
        await db.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS idx_products_sku ON products (sku)
        """)
        print("Таблица 'products' создана.")

        await db.execute('''
        CREATE TABLE sizes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
        ''')
        await db.execute('''
        CREATE TABLE colors (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
        ''')
        print("Таблицы 'sizes' и 'colors' созданы.")

        # --- 2. Таблица с вариантами товаров ---
        await db.execute('''
        CREATE TABLE product_variants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL,
            size_id INTEGER,
            color_id INTEGER,
            price REAL NOT NULL,
            quantity INTEGER NOT NULL DEFAULT 0,
            photo_id TEXT,
            photo_url TEXT,
            FOREIGN KEY (product_id) REFERENCES products (id) ON DELETE CASCADE,
            FOREIGN KEY (size_id) REFERENCES sizes (id),
            FOREIGN KEY (color_id) REFERENCES colors (id)
        )
        ''')
        print("Таблица 'product_variants' создана.")

        # --- 3. Таблица с медиафайлами ---
        await db.execute('''
        CREATE TABLE product_media (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            variant_id INTEGER,
            file_id TEXT NOT NULL,
            is_video BOOLEAN DEFAULT 0,
            "order" INTEGER DEFAULT 0,
            url TEXT,
            FOREIGN KEY (variant_id) REFERENCES product_variants (id) ON DELETE CASCADE
        )
        ''')
        print("Таблица 'product_media' создана.")

        # --- 4. Таблица заказов ---
        await db.execute('''
        CREATE TABLE orders (
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

        await db.commit()
        print(f"\n✅ База данных '{DB_FILE}' успешно пересоздана с полной структурой!")

if __name__ == "__main__":
    asyncio.run(main())
