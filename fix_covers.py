import asyncio
import aiosqlite
import logging
from configs import DB_FILE
# Настройка логирования, чтобы видеть процесс
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')


async def fix_old_products():
    """
    Этот скрипт находит все товары, у которых нет обложки (cover_url IS NULL),
    и устанавливает им в качестве обложки первую фотографию первого варианта.
    """
    updated_count = 0
    not_found_count = 0

    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row  # Чтобы можно было обращаться к колонкам по имени

        # 1. Находим все товары, у которых НЕТ обложки
        async with db.execute("SELECT id, name FROM products WHERE cover_url IS NULL OR cover_url = ''") as cursor:
            products_to_fix = await cursor.fetchall()

        if not products_to_fix:
            logging.info("Отлично! Все товары уже имеют обложки. Исправлять нечего.")
            return

        logging.info(f"Найдено {len(products_to_fix)} товаров без обложки. Начинаем исправление...")

        # 2. Проходим по каждому такому товару в цикле
        for product in products_to_fix:
            product_id = product['id']
            product_name = product['name']

            # 3. Ищем для него подходящую фотографию (первое фото первого варианта)
            find_photo_sql = """
                SELECT pm.url
                FROM product_media pm
                JOIN product_variants pv ON pm.variant_id = pv.id
                WHERE pv.product_id = ? AND pm.is_video = 0 AND pm.url IS NOT NULL
                ORDER BY pv.id ASC, pm."order" ASC
                LIMIT 1
            """
            async with db.execute(find_photo_sql, (product_id,)) as photo_cursor:
                photo_row = await photo_cursor.fetchone()

            if photo_row and photo_row['url']:
                cover_url = photo_row['url']
                
                # 4. Обновляем товар, прописывая ему найденную обложку
                await db.execute(
                    "UPDATE products SET cover_url = ? WHERE id = ?",
                    (cover_url, product_id)
                )
                await db.commit()
                logging.info(f"✅ Обложка для товара '{product_name}' (ID: {product_id}) успешно установлена.")
                updated_count += 1
            else:
                logging.warning(f"⚠️ Для товара '{product_name}' (ID: {product_id}) не найдено ни одного фото в вариантах. Пропущено.")
                not_found_count += 1
    
    logging.info("======================================")
    logging.info("Готово!")
    logging.info(f"Всего обновлено товаров: {updated_count}")
    logging.info(f"Товаров без фото пропущено: {not_found_count}")


if __name__ == "__main__":
    asyncio.run(fix_old_products())