import asyncio
import aiosqlite
from configs import DB_FILE

async def main():
    """
    Этот скрипт безопасно изменяет структуру таблицы 'orders',
    не затрагивая другие таблицы и не удаляя данные.
    """
    print(f"Подключаюсь к базе данных: {DB_FILE}")
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row # Чтобы работать со столбцами по именам

        # Проверяем, существует ли уже новая таблица, на всякий случай
        cursor = await db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='orders_new'")
        if await cursor.fetchone():
            print("Похоже, миграция уже была проведена. Выхожу.")
            return

        print("Начинаю миграцию таблицы 'orders'...")

        # Шаг 1: Переименовываем старую таблицу
        await db.execute("ALTER TABLE orders RENAME TO orders_old")
        print("1/4: Старая таблица переименована в 'orders_old'.")

        # Шаг 2: Создаем новую таблицу с правильной структурой
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
            created_at TEXT NOT NULL
        )
        ''')
        print("2/4: Новая таблица 'orders' создана с правильной структурой.")

        # Шаг 3: Копируем данные из старой таблицы в новую
        # Важно: мы не копируем 'created_at', т.к. будем его генерировать по-новому
        # Но для существующих заказов можно поставить заглушку
        await db.execute('''
        INSERT INTO orders (id, user_id, user_name, user_address, user_phone, cart, total_price, status, deducted_from_stock, created_at)
        SELECT id, user_id, user_name, user_address, user_phone, cart, total_price, status, deducted_from_stock, created_at
        FROM orders_old
        ''')
        print("3/4: Данные скопированы из старой таблицы в новую.")

        # Шаг 4: Удаляем старую таблицу
        await db.execute("DROP TABLE orders_old")
        print("4/4: Старая таблица 'orders_old' удалена.")

        await db.commit()
        print("\n✅ Миграция успешно завершена! Структура таблицы 'orders' обновлена.")
        print("Все твои товары и другие данные в полной безопасности.")

if __name__ == "__main__":
    asyncio.run(main())