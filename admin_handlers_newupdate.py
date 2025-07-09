import json
import logging
import os
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup , CallbackQuery
from telegram.ext import ContextTypes, ConversationHandler, CommandHandler, MessageHandler, CallbackQueryHandler, filters
from telegram.constants import ParseMode
import asyncio
from configs import ADMIN_IDS, FLASK_UPLOAD_URL
from db import fetchall, fetchone, execute

def get_effective_message(update):
    # Вернёт message для обычного сообщения или callback_query.message для кнопки
    if getattr(update, "message", None):
        return update.message
    elif getattr(update, "callback_query", None):
        return update.callback_query.message
    return None
# --- СОСТОЯНИЯ FSM (Finite State Machine) ---

# Определяем уникальные, пронумерованные шаги для всего диалога
(
    # === Состояния для ДОБАВЛЕНИЯ товара ===
    ADD_GET_NAME, ADD_GET_CATEGORY, ADD_GET_SUBCATEGORY, ADD_GET_BRAND, ADD_GET_DESCRIPTION,
    ADD_GET_NEW_CATEGORY_NAME, ADD_GET_NEW_SUBCATEGORY_NAME, ADD_GET_NEW_BRAND_NAME,
    ADD_GET_VARIANT_SIZE, ADD_GET_VARIANT_COLOR, ADD_GET_VARIANT_PRICE, ADD_GET_VARIANT_QUANTITY, ADD_GET_VARIANT_MEDIA,
    ADD_GET_NEW_SIZE_NAME, ADD_GET_NEW_COLOR_NAME,
    ADD_ASK_ADD_MORE_VARIANTS,

    # === Состояния для ЕДИНОГО АДМИНСКОГО ХЕНДЛЕРА ===
    ADMIN_MENU_AWAIT,           # Ожидание выбора в главном админ-меню
    ADMIN_AWAIT_EDIT_ID,        # Ожидание ввода ID товара для редактирования
    ADMIN_AWAIT_SUBCAT_ID,     # Ожидание ввода ID категории для подкатегорий
    
    # === Состояния для РЕДАКТИРОВАНИЯ товара ===
    EDIT_AWAIT_ACTION, 
    EDIT_CONFIRM_DELETE_VARIANT, EDIT_CONFIRM_DELETE_FULL_PRODUCT,
    EDIT_SELECT_VARIANT_FIELD, EDIT_GET_NEW_VARIANT_VALUE,
    EDIT_ADD_VARIANT_SIZE, EDIT_ADD_VARIANT_COLOR, EDIT_ADD_VARIANT_PRICE, EDIT_ADD_VARIANT_QUANTITY, EDIT_ADD_VARIANT_MEDIA,
    EDIT_GET_NEW_SIZE_NAME, EDIT_GET_NEW_COLOR_NAME,
    EDIT_ASK_ADD_MORE,

    # === Состояния для Админ-панели ===
    ADMIN_MENU_AWAIT, ADMIN_EDIT_AWAIT_ID, ADMIN_SUBCAT_AWAIT_ID,
    
    # === Состояния для переименования (остаются как есть) ===
    RENAME_SUBCAT, RENAME_BRAND

) = range(500, 537)

# --- Вспомогательные функции (без изменений) ---

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def cancel_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Прерывает диалог в любом месте."""
    context.user_data.clear()
    message = "Действие отменено."
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text=message)
    else:
        await update.message.reply_text(message)
    return ConversationHandler.END

async def create_new_entity(name: str, table_name: str, category_id: int = None) -> int:
    """Создает новую сущность (категорию, бренд и т.д.)."""
    params = (name,)
    query = f"INSERT INTO {table_name} (name) VALUES (?)"
    if table_name == 'sub_categories' and category_id:
        params = (name, category_id)
        query = "INSERT INTO sub_categories (name, category_id) VALUES (?, ?)"
    
    try:
        await execute(query, params)
        entity_row = await fetchone(f"SELECT id FROM {table_name} WHERE name = ? {'AND category_id = ?' if category_id else ''}", params)
        return entity_row['id']
    except Exception: # Если сущность с таким именем уже существует
        entity_row = await fetchone(f"SELECT id FROM {table_name} WHERE name = ? {'AND category_id = ?' if category_id else ''}", params)
        return entity_row['id']

# =================================================================
# === ПРОЦЕСС ДОБАВЛЕНИЯ ТОВАРА (ЕДИНЫЙ CONVERSATIONHANDLER) ===
# =================================================================

# 1. Начало (Entry Point)
async def start_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает диалог добавления товара."""
    query = update.callback_query
    await query.answer()
    context.user_data.clear() # Очищаем старые данные
    await query.edit_message_text("Добавляем новый товар. Введите его общее название.\n\n/cancel - отмена.")
    return ADD_GET_NAME

# 2. Получение названия
async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['product_name'] = update.message.text.strip()
    categories = await fetchall("SELECT * FROM categories")
    keyboard = [[InlineKeyboardButton(cat['name'], callback_data=f"cat_{cat['id']}")] for cat in categories]
    keyboard.append([InlineKeyboardButton("➕ Новая категория", callback_data="cat_new")])
    await update.message.reply_text("Шаг 1: Выберите основную категорию:", reply_markup=InlineKeyboardMarkup(keyboard))
    return ADD_GET_CATEGORY

# 3. Получение категории
async def get_category(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "cat_new":
        await query.edit_message_text("Введите название новой категории:")
        return ADD_GET_NEW_CATEGORY_NAME
    context.user_data['category_id'] = int(query.data.split('_')[1])
    await ask_for_subcategory(update, context)
    return ADD_GET_SUBCATEGORY

async def get_new_category_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    category_id = await create_new_entity(update.message.text, 'categories')
    context.user_data['category_id'] = category_id
    await update.message.reply_text(f"Категория '{update.message.text}' создана.")
    await ask_for_subcategory(update, context)
    return ADD_GET_SUBCATEGORY

# 4. Запрос подкатегории (вспомогательная функция)
async def ask_for_subcategory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    category_id = context.user_data.get('category_id')
    sub_categories = await fetchall("SELECT * FROM sub_categories WHERE category_id = ?", (category_id,))
    keyboard = [[InlineKeyboardButton(scat['name'], callback_data=f"subcat_{scat['id']}")] for scat in sub_categories]
    keyboard.append([InlineKeyboardButton("➕ Новая подкатегория", callback_data="subcat_new")])
    message_text = "Шаг 2: Выберите подкатегорию:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text=message_text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text=message_text, reply_markup=InlineKeyboardMarkup(keyboard))

# 5. Получение подкатегории
async def get_subcategory(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "subcat_new":
        await query.edit_message_text("Введите название новой подкатегории:")
        return ADD_GET_NEW_SUBCATEGORY_NAME
    context.user_data['sub_category_id'] = int(query.data.split('_')[1])
    await ask_for_brand(update, context)
    return ADD_GET_BRAND

async def get_new_subcategory_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    category_id = context.user_data.get('category_id')
    subcat_id = await create_new_entity(update.message.text, 'sub_categories', category_id=category_id)
    context.user_data['sub_category_id'] = subcat_id
    await update.message.reply_text(f"Подкатегория '{update.message.text}' создана.")
    await ask_for_brand(update, context)
    return ADD_GET_BRAND

# 6. Запрос бренда (вспомогательная функция)
async def ask_for_brand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    brands = await fetchall("SELECT * FROM brands")
    keyboard = [[InlineKeyboardButton(b['name'], callback_data=f"brand_{b['id']}")] for b in brands]
    keyboard.append([InlineKeyboardButton("➕ Новый бренд", callback_data="brand_new")])
    message_text = "Шаг 3: Выберите бренд:"
    if update.callback_query:
        await update.callback_query.edit_message_text(text=message_text, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(text=message_text, reply_markup=InlineKeyboardMarkup(keyboard))

# 7. Получение бренда
async def get_brand(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "brand_new":
        await query.edit_message_text("Введите название нового бренда:")
        return ADD_GET_NEW_BRAND_NAME
    context.user_data['brand_id'] = int(query.data.split('_')[1])
    await query.edit_message_text("Шаг 4: Введите общее описание товара:")
    return ADD_GET_DESCRIPTION

async def get_new_brand_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    brand_id = await create_new_entity(update.message.text, 'brands')
    context.user_data['brand_id'] = brand_id
    await update.message.reply_text(f"Бренд '{update.message.text}' создан.\n\nШаг 4: Введите общее описание товара.")
    return ADD_GET_DESCRIPTION

# 8. Получение описания и сохранение основного товара
async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data['description'] = update.message.text
    data = context.user_data
    # Сохраняем основной товар в БД
    await execute(
        "INSERT INTO products (name, description, category_id, sub_category_id, brand_id) VALUES (?, ?, ?, ?, ?)",
        (data['product_name'], data['description'], data['category_id'], data['sub_category_id'], data['brand_id'])
    )
    product_row = await fetchone("SELECT id FROM products WHERE name = ? ORDER BY id DESC LIMIT 1", (data['product_name'],))
    context.user_data['product_id'] = product_row['id']
    await update.message.reply_text(f"✅ Основной товар '{data['product_name']}' создан.\n\nТеперь добавим первый вариант.")
    await ask_for_variant_size(update, context)
    return ADD_GET_VARIANT_SIZE

# --- Функции для добавления вариантов ---
async def ask_for_variant_size(update, context):
    sizes = await fetchall("SELECT * FROM sizes")
    keyboard = [[InlineKeyboardButton(s['name'], callback_data=f"size_{s['id']}")] for s in sizes]
    keyboard.append([InlineKeyboardButton("➕ Новый размер", callback_data="size_new")])
    msg = "Добавление варианта. Шаг 1: Выберите размер:"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def get_variant_size(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "size_new":
        await query.edit_message_text("Введите новое значение размера:")
        return ADD_GET_NEW_SIZE_NAME
    context.user_data['variant_size_id'] = int(query.data.split('_')[1])
    await ask_for_variant_color(update, context)
    return ADD_GET_VARIANT_COLOR

async def get_new_size_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    size_id = await create_new_entity(update.message.text, 'sizes')
    context.user_data['variant_size_id'] = size_id
    await update.message.reply_text(f"Размер '{update.message.text}' создан.")
    await ask_for_variant_color(update, context)
    return ADD_GET_VARIANT_COLOR

async def ask_for_variant_color(update, context):
    colors = await fetchall("SELECT * FROM colors")
    keyboard = [[InlineKeyboardButton(c['name'], callback_data=f"color_{c['id']}")] for c in colors]
    keyboard.append([InlineKeyboardButton("➕ Новый цвет", callback_data="color_new")])
    msg = "Шаг 2: Выберите цвет:"
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard))

async def get_variant_color(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "color_new":
        await query.edit_message_text("Введите название нового цвета:")
        return ADD_GET_NEW_COLOR_NAME
    context.user_data['variant_color_id'] = int(query.data.split('_')[1])
    await query.edit_message_text("Шаг 3: Введите цену этого варианта (только число):")
    return ADD_GET_VARIANT_PRICE

async def get_new_color_name(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    color_id = await create_new_entity(update.message.text, 'colors')
    context.user_data['variant_color_id'] = color_id
    await update.message.reply_text(f"Цвет '{update.message.text}' создан.\n\nШаг 3: Введите цену этого варианта:")
    return ADD_GET_VARIANT_PRICE

async def get_variant_price(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data['variant_price'] = float(update.message.text)
        await update.message.reply_text("Шаг 4: Введите количество на складе:")
        return ADD_GET_VARIANT_QUANTITY
    except ValueError:
        await update.message.reply_text("Неверный формат. Введите цену числом.")
        return ADD_GET_VARIANT_PRICE

async def get_variant_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        context.user_data['variant_quantity'] = int(update.message.text)
        data = context.user_data
        # Сохраняем вариант в БД
        await execute(
            "INSERT INTO product_variants (product_id, size_id, color_id, price, quantity) VALUES (?, ?, ?, ?, ?)",
            (data['product_id'], data['variant_size_id'], data['variant_color_id'], data['variant_price'], data['variant_quantity'])
        )
        variant_row = await fetchone(
            "SELECT id FROM product_variants WHERE product_id=? AND size_id=? AND color_id=? ORDER BY id DESC LIMIT 1",
            (data['product_id'], data['variant_size_id'], data['variant_color_id'])
        )
        context.user_data['current_variant_id'] = variant_row['id']
        context.user_data['media_order'] = 0
        await update.message.reply_text("Вариант сохранен. Теперь отправьте от 1 до 5 фото/видео для этого варианта. Когда закончите, напишите /done.")
        return ADD_GET_VARIANT_MEDIA
    except ValueError:
        await update.message.reply_text("Неверный формат. Введите количество как целое число.")
        return ADD_GET_VARIANT_QUANTITY

# ВАША ФУНКЦИЯ add_media БЕЗ ИЗМЕНЕНИЙ
async def add_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    variant_id = context.user_data.get('current_variant_id')
    order = context.user_data.get('media_order', 0)

    if order >= 5:
        await update.message.reply_text("Максимум 5 медиафайлов для одного варианта. Напишите /done.")
        return ADD_GET_VARIANT_MEDIA

    file_id = None
    is_video = False
    file_obj = None

    if update.message.photo:
        file = update.message.photo[-1]
        file_id = file.file_id
        file_obj = await file.get_file()
        is_video = False
    elif update.message.video:
        file = update.message.video
        file_id = file.file_id
        file_obj = await file.get_file()
        is_video = True
    
    if file_id and file_obj:
        # Логика загрузки на Flask сервер
        async with aiohttp.ClientSession() as session:
            async with session.get(file_obj.file_path) as resp:
                if resp.status == 200:
                    photo_bytes = await resp.read()
                    form = aiohttp.FormData()
                    form.add_field(
                        "photo",
                        photo_bytes,
                        filename=os.path.basename(file_obj.file_path),
                        content_type="image/jpeg" if not is_video else "video/mp4"
                    )
                    async with session.post(FLASK_UPLOAD_URL, data=form) as upload_resp:
                        if upload_resp.status == 200:
                            result = await upload_resp.json()
                            photo_url = result["url"]
                            logging.info(f"✅ Загружено на Flask: {photo_url}")
                            # Сохраняем в БД
                            await execute(
                                "INSERT INTO product_media (variant_id, file_id, url, is_video, \"order\") VALUES (?, ?, ?, ?, ?)",
                                (variant_id, file_id, photo_url, is_video, order)
                            )
                            context.user_data['media_order'] += 1
                            if order == 0:
                                await execute(
                                    "UPDATE product_variants SET photo_id = ?, photo_url = ? WHERE id = ?",
                                    (file_id, photo_url, variant_id)
                                )
                            await update.message.reply_text(f"Медиафайл #{order + 1} добавлен. Отправьте еще или напишите /done.")
                        else:
                            error_text = await upload_resp.text()
                            logging.error(f"❌ Ошибка от Flask сервера: {error_text}")
                            await update.message.reply_text("❌ Сервер не принял файл.")
                else:
                    logging.error(f"❌ Не удалось скачать с Telegram: {resp.status}")
                    await update.message.reply_text("❌ Не удалось скачать файл из Telegram.")
    else:
        await update.message.reply_text("Отправьте только фото или видео.")
        
    return ADD_GET_VARIANT_MEDIA

async def finish_media(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = [
        [InlineKeyboardButton("➕ Да, добавить еще", callback_data="add_more_variants")],
        [InlineKeyboardButton("✅ Нет, завершить", callback_data="finish_add_product")]
    ]
    await update.message.reply_text(
        "✅ Вариант успешно добавлен. Хотите добавить еще один?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    return ADD_ASK_ADD_MORE_VARIANTS

async def ask_add_more_variants(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == 'add_more_variants':
        await query.edit_message_text("Добавление нового варианта...")
        await ask_for_variant_size(update, context)
        return ADD_GET_VARIANT_SIZE
    elif query.data == 'finish_add_product':
        product_name = context.user_data.get('product_name', 'товар')
        await query.edit_message_text(f"✅ Отлично! Все варианты для товара '{product_name}' сохранены.")
        context.user_data.clear()
        return ConversationHandler.END

# =================================================================
# === ПРОЦЕСС РЕДАКТИРОВАНИЯ ТОВАРА (НОВЫЙ CONVERSATIONHANDLER) ===
# =================================================================

async def start_edit_product(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Начинает диалог редактирования товара."""
    query = update.callback_query
    await query.answer()
    
    # ID товара должен быть уже в user_data из admin_menu_handler
    product_id = context.user_data.get('product_to_edit_id')
    if not product_id:
        await query.edit_message_text("Ошибка: ID товара не найден. Начните заново из /admin.")
        return ConversationHandler.END

    await show_edit_menu(update, context)
    return EDIT_AWAIT_ACTION

async def show_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показывает главное меню редактирования с вариантами."""
    product_id = context.user_data.get('product_to_edit_id')
    product = await fetchone("SELECT * FROM products WHERE id = ?", (product_id,))
    if not product:
        # Используем update.effective_message, чтобы работать и с кнопками, и с сообщениями
        await update.effective_message.reply_text(f"❌ Товар с ID {product_id} не найден.")
        return

    variants = await fetchall("""
        SELECT pv.id, pv.price, pv.quantity, s.name as size_name, c.name as color_name
        FROM product_variants pv
        LEFT JOIN sizes s ON pv.size_id = s.id
        LEFT JOIN colors c ON pv.color_id = c.id
        WHERE pv.product_id = ?
    """, (product_id,))

    message_text = f"⚙️ Редактирование <b>{product['name']}</b> (ID: {product_id})\n\nВыберите действие:"
    keyboard = [[InlineKeyboardButton("✏️ Общая информация", callback_data=f"edit_general_{product_id}")]]
    
    if variants:
        keyboard.append([InlineKeyboardButton("--- Варианты товара ---", callback_data="noop")])
        for v in variants:
            v_text = f"{v['size_name']}, {v['color_name']} | {v['price']}₸ ({v['quantity']} шт.)"
            keyboard.append([
                InlineKeyboardButton(v_text, callback_data=f"edit_variant_menu_{v['id']}"),
                InlineKeyboardButton("🗑️", callback_data=f"delete_variant_{v['id']}")
            ])

    keyboard.append([InlineKeyboardButton("➕ Добавить новый вариант", callback_data=f"add_variant_to_{product_id}")])
    keyboard.append([InlineKeyboardButton("❌ Удалить товар ПОЛНОСТЬЮ", callback_data=f"delete_product_full_{product_id}")])
    keyboard.append([InlineKeyboardButton("⬅️ Завершить", callback_data="edit_cancel")])

    if update.callback_query:
        await update.callback_query.edit_message_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    else:
        await update.message.reply_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML)
    

async def handle_edit_action(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает нажатия в главном меню редактирования."""
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "back_to_admin_menu":
        await query.edit_message_text("Возврат в главное меню...")
        await admin_menu_entry(query, context) # Переиспользуем функцию входа
        return ADMIN_MENU_AWAIT

    if data.startswith("delete_variant_"):
        context.user_data['variant_to_delete'] = int(data.split('_')[2])
        keyboard = [[InlineKeyboardButton("✅ Да, удалить вариант", callback_data="confirm_delete_variant"), InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete")]]
        await query.edit_message_text("Вы уверены?", reply_markup=InlineKeyboardMarkup(keyboard))
        return EDIT_CONFIRM_DELETE_VARIANT

    elif data.startswith("delete_product_full_"):
        context.user_data['product_to_delete'] = int(data.split('_')[3])
        keyboard = [[InlineKeyboardButton("✅ Да, удалить ВСЁ", callback_data="confirm_delete_full"), InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete")]]
        await query.edit_message_text("Вы уверены, что хотите удалить товар и ВСЕ его варианты?", reply_markup=InlineKeyboardMarkup(keyboard))
        return EDIT_CONFIRM_DELETE_FULL_PRODUCT

    elif data.startswith("add_variant_to_"):
        context.user_data['product_id'] = int(data.split('_')[3])
        await query.edit_message_text("Добавление нового варианта к существующему товару...")
        await ask_for_variant_size(update, context) # Переиспользуем функцию, но она вернет правильное состояние
        return EDIT_ADD_VARIANT_SIZE

    elif data.startswith("edit_variant_menu_"):
        context.user_data['variant_to_edit_id'] = int(data.split('_')[3])
        keyboard = [
            [InlineKeyboardButton("Цену", callback_data="edit_field_price")],
            [InlineKeyboardButton("Количество", callback_data="edit_field_quantity")],
            [InlineKeyboardButton("Фото", callback_data="edit_field_photo")],
            [InlineKeyboardButton("⬅️ Назад", callback_data="back_to_edit_menu")]
        ]
        await query.edit_message_text("Что изменить в этом варианте?", reply_markup=InlineKeyboardMarkup(keyboard))
        return EDIT_SELECT_VARIANT_FIELD

    elif data == "edit_cancel":
        context.user_data.clear()
        await query.edit_message_text("Редактирование завершено.")
        return ConversationHandler.END
    
    return EDIT_AWAIT_ACTION # Остаемся в том же состоянии

async def confirm_variant_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "confirm_delete_variant":
        variant_id = context.user_data.get('variant_to_delete')
        await execute("DELETE FROM product_variants WHERE id = ?", (variant_id,))
        await query.edit_message_text("✅ Вариант удален. Обновляю меню...")
    else: # cancel_delete
        await query.edit_message_text("Удаление отменено.")
        
    await show_edit_menu(update, context)
    return EDIT_AWAIT_ACTION

async def confirm_full_product_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    if query.data == "confirm_delete_full":
        product_id = context.user_data.get('product_to_delete')
        await execute("DELETE FROM product_variants WHERE product_id = ?", (product_id,))
        await execute("DELETE FROM products WHERE id = ?", (product_id,))
        await query.edit_message_text(f"✅ Товар с ID {product_id} и все его варианты были полностью удалены.")
        context.user_data.clear()
        return ConversationHandler.END
    else: # cancel_delete
        await query.edit_message_text("Удаление отменено.")
        await show_edit_menu(update, context)
        return EDIT_AWAIT_ACTION

async def select_variant_field_to_edit(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "back_to_edit_menu":
        await show_edit_menu(update, context)
        return EDIT_AWAIT_ACTION

    field_to_edit = data.split('_')[2] # edit_field_price -> price
    context.user_data['field_to_edit'] = field_to_edit
    
    if field_to_edit == "photo":
        # Для редактирования фото мы можем переиспользовать логику добавления
        context.user_data['current_variant_id'] = context.user_data.get('variant_to_edit_id')
        context.user_data['media_order'] = 0
        await query.edit_message_text("Пришлите новые фото или видео для этого варианта. Когда закончите — напишите /done.")
        return EDIT_ADD_VARIANT_MEDIA 
        
    prompt = f"Введите новое значение для поля '{field_to_edit}':"
    await query.edit_message_text(prompt)
    return EDIT_GET_NEW_VARIANT_VALUE

async def get_new_variant_value(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    field = context.user_data.get('field_to_edit')
    variant_id = context.user_data.get('variant_to_edit_id')
    new_value_text = update.message.text
    
    try:
        new_value = float(new_value_text) if field == 'price' else int(new_value_text)
    except ValueError:
        await update.message.reply_text("Неверный формат. Введите число.")
        return EDIT_GET_NEW_VARIANT_VALUE

    await execute(f"UPDATE product_variants SET {field} = ? WHERE id = ?", (new_value, variant_id))
    await update.message.reply_text(f"✅ Поле '{field}' для варианта успешно обновлено.")
    
    await show_edit_menu(update, context)
    return EDIT_AWAIT_ACTION


# --- Отчёты ---
async def get_sales_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        return
    report_data = await fetchone("SELECT COUNT(id) AS c, SUM(total_price) AS s FROM orders WHERE status = 'confirmed' AND created_at >= date('now', '-7 days')")
    all_carts_data = await fetchall("SELECT cart FROM orders WHERE status = 'confirmed' AND created_at >= date('now', '-7 days')")
    product_popularity = {}
    for row in all_carts_data:
        cart = json.loads(row['cart'])
        for item_details in cart.values():
            product_popularity[item_details['name']] = product_popularity.get(item_details['name'], 0) + item_details['quantity']
    most_popular_product_text = "Нет проданных товаров"
    if product_popularity:
        most_popular_item = max(product_popularity, key=product_popularity.get)
        most_popular_product_text = f"{most_popular_item} (продано {product_popularity[most_popular_item]} шт.)"
    orders_count, total_revenue = (report_data['c'] or 0), (report_data['s'] or 0)
    report_message = (
        f"📊 <b>Отчет за 7 дней:</b>\n\n"
        f"• <b>Заказов:</b> {orders_count}\n"
        f"• <b>Выручка:</b> {int(total_revenue)} ₸\n"
        f"• <b>Хит продаж:</b> {most_popular_product_text}"
    )
    msg = get_effective_message(update)
    if msg:
        await msg.reply_text(report_message, parse_mode=ParseMode.HTML)
    

from bee import fetch_products_detailed, export_to_gsheet, download_xlsx, GOOGLE_SHEET_URL
# --- Отчёт по товарам ---
async def send_products_report(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # 1. Получаем актуальные данные и обновляем Google Sheet
    data = fetch_products_detailed()
    export_to_gsheet(data)
    # 2. Скачиваем .xlsx-файл
    xlsx_file = download_xlsx()
    # 3. Отправляем ссылку на Google Таблицу
    msg = get_effective_message(update)
    if msg:
        await msg.reply_text("Генерирую отчёт по товарам...")
        await msg.reply_text(f"Ссылка на Google Таблицу:\n{GOOGLE_SHEET_URL}")
    # 4. Отправляем .xlsx файл (если скачался)
    if xlsx_file:
        with open(xlsx_file, "rb") as f:
            msg = get_effective_message(update)
            if msg:
                await msg.reply_text("Отправляю .xlsx-файл с отчётом по товарам...")
            await msg.reply_document(document=f, filename="products_report.xlsx", caption="Отчёт по товарам (.xlsx)")
    else:
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text("Не удалось скачать .xlsx-файл. Проверьте права доступа.")


from bee import fetch_orders_report, make_orders_report_text

PERIODS = {
    "today": "сегодня",
    "3days": "последние 3 дня",
    "7days": "последние 7 дней",
    "30days": "последние 30 дней"
}

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

async def ask_orders_report_period(update, context):
    keyboard = [
        [InlineKeyboardButton("Сегодня", callback_data="orders_report_today")],
        [InlineKeyboardButton("Последние 3 дня", callback_data="orders_report_3days")],
        [InlineKeyboardButton("Последние 7 дней", callback_data="orders_report_7days")],
        [InlineKeyboardButton("Последние 30 дней", callback_data="orders_report_30days")],
    ]
    msg = get_effective_message(update)
    if msg:
        
        await msg.reply_text(
            "Выберите период для отчёта по заказам:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

async def handle_orders_report_period(update, context):
    query = update.callback_query
    await query.answer()
    period_key = query.data.split("_")[-1]
    period_map = {
        "today": "today",
        "3days": "3days",
        "7days": "7days",
        "30days": "30days"
    }
    period = period_map.get(period_key)
    if not period:
        await query.edit_message_text("Некорректный период.")
        return
    orders = fetch_orders_report(period)
    text = make_orders_report_text(orders, PERIODS[period])
    await query.edit_message_text(text)


async def report_combined(update, context):
    await get_sales_report(update, context)
    await send_products_report(update, context)


# --- Подтверждение заказа админом ---
async def handle_admin_decision(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split('_')
    # Проверка что parts[2] — это число
    if len(parts) < 3 or not parts[2].isdigit():
        await query.edit_message_text("Ошибка: некорректный формат callback data.", parse_mode=ParseMode.HTML)
        return
    action, order_id_str = query.data.split('_')[1], query.data.split('_')[2]
    order_id = int(order_id_str)
    order = await fetchone("SELECT * FROM orders WHERE id = ?", (order_id,))
    if order["status"] == "cancelled_by_client":
        await query.edit_message_text(
            f"⚠️ Невозможно изменить статус — заказ №{order_id} отменён клиентом.",
            parse_mode=ParseMode.HTML
        )
        return

    if not order:
        await query.edit_message_text("Заказ не найден.", parse_mode=ParseMode.HTML)
        return
    customer_user_id = order['user_id']
    if action == "confirm":
        try:
            cart = json.loads(order['cart'])

            # 💥 Ключевая проверка: избежать двойного списания
            if str(order["deducted_from_stock"]) != "1":
                for variant_id_str, item in cart.items():
                    await execute(
                        "UPDATE product_variants SET quantity = quantity - ? WHERE id = ?",
                        (item['quantity'], int(variant_id_str))
                    )

                await execute("UPDATE orders SET deducted_from_stock = 1 WHERE id = ?", (order_id,))

            await execute("UPDATE orders SET status = ? WHERE id = ?", ('confirmed', order_id))
            kb = [[InlineKeyboardButton("История заказов 🗒" , callback_data="order_history")]]
            await context.bot.send_message(
                chat_id=customer_user_id,
                text= f"<b>✅ Ваш заказ №{order_id} подтвержден! \n\nВы можете отслеживать заказ :\nГлавное меню ➡ История заказов ➡ 🟡Активные</b>",

                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(kb)
            )

            status_buttons = [
                [InlineKeyboardButton("🔄 Готовится к доставке", callback_data=f"status_preparing_{order_id}")],
                [InlineKeyboardButton("🚚 Отправлен", callback_data=f"status_shipped_{order_id}")],
                [InlineKeyboardButton("📦 Доставлен", callback_data=f"status_delivered_{order_id}")],
                [InlineKeyboardButton("❌ Отклонить заказ", callback_data=f"admin_reject_after_confirm_{order_id}")]
            ]

            await query.edit_message_text(
                f"Заказ №{order_id} подтверждён.\n\nВыберите следующий статус:",
                parse_mode=ParseMode.HTML,
                reply_markup=InlineKeyboardMarkup(status_buttons)
            )
        except Exception:
            await query.edit_message_text("Ошибка при подтверждении заказа.", parse_mode=ParseMode.HTML)




# --- Обновление статуса заказа админом с пошаговой логикой ---
async def update_order_status_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    parts = query.data.split('_')  # status_preparing_123
    if len(parts) != 3 or not parts[2].isdigit():
        await query.edit_message_text("Ошибка: некорректные данные.", parse_mode="HTML")
        return

    new_status = parts[1]
    order_id = int(parts[2])

    order = await fetchone("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not order:
        await query.edit_message_text("Заказ не найден.", parse_mode="HTML")
        return

    if order["status"] == "cancelled_by_client":
        await query.edit_message_text(
            f"⚠️ Невозможно изменить статус — заказ №{order_id} отменён клиентом.",
            parse_mode="HTML"
        )
        return

    await execute("UPDATE orders SET status = ? WHERE id = ?", (new_status, order_id))

    support_user = "candyy_sh0p"
    admin_link = f'<a href="https://t.me/{support_user}">@{support_user}</a>'

    try:
        user_obj = await context.bot.get_chat(order["user_id"])
        username = user_obj.username
    except Exception:
        username = None

    user_link = f'<a href="https://t.me/{username}">@{username}</a>' if username else "нет username"

    try:
        cart = json.loads(order['cart'])
        cart_text = "\n".join([f"• {item['name']} (x{item['quantity']})" for item in cart.values()])
    except Exception:
        cart_text = "Ошибка при разборе состава заказа"

    user_check = (
        f"📦 <b>Информация о заказе №{order_id}</b>\n\n"
        f"Сумма: {order['total_price']} ₸\n"
        f"Клиент: {order['user_name']}\n"
        f"Телефон: {order['user_phone']}\n"
        f"Адрес: {order['user_address']}\n\n"
        f"<b>Состав заказа:</b>\n{cart_text}\n"
        f"\n\nКонтакты админа{admin_link}"
    )

    status_texts = {
        "preparing": "Ваш заказ готовится к доставке 🚕",
        "shipped": f"<b>🚚 Ваш заказ был отправлен на адрес:</b> {order['user_address']}",
        "delivered": f"Ваш заказ доставлен, спасибо за покупку!\n\n{user_check}"
    }

    notify_text = status_texts.get(new_status, "📢 Обновление по вашему заказу.")

    await context.bot.send_message(
        chat_id=order["user_id"],
        text=f"{notify_text} (Заказ №{order_id})",
        parse_mode="HTML"
    )

    admin_info = (
        f"📦 <b>Информация о заказе №{order_id}</b>\n\n"
        f"Сумма: {order['total_price']} ₸\n"
        f"Клиент: {order['user_name']}\n"
        f"Username: {user_link}\n"
        f"Телефон: {order['user_phone']}\n"
        f"Адрес: {order['user_address']}\n\n"
        f"<b>Состав заказа:</b>\n{cart_text}\n"
    )

    next_buttons = []
    if new_status == "preparing":
        next_buttons = [
            [InlineKeyboardButton("🚚 Отправлен", callback_data=f"status_shipped_{order_id}")],
            [InlineKeyboardButton("📦 Доставлен", callback_data=f"status_delivered_{order_id}")],
            [InlineKeyboardButton("❌ Отклонить заказ", callback_data=f"admin_reject_after_confirm_{order_id}")]
        ]
        admin_text = f"Статус заказа №{order_id} изменён на: Готовится к доставке"
    elif new_status == "shipped":
        next_buttons = [
            [InlineKeyboardButton("📦 Доставлен", callback_data=f"status_delivered_{order_id}")],
            [InlineKeyboardButton("❌ Отклонить заказ", callback_data=f"admin_reject_after_confirm_{order_id}")]
        ]
        admin_text = f"Статус заказа №{order_id} изменён на: Отправлен"
    elif new_status == "delivered":
        await query.edit_message_text(
            f"✅ Заказ №{order_id} был завершён.",
            parse_mode="HTML"
        )
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=admin_info,
            parse_mode="HTML"
        )
        return

    await query.edit_message_text(
        f"{admin_text}\n\n{admin_info}",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(next_buttons) if next_buttons else None
    )










async def handle_admin_rejection_after_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    order_id = int(query.data.split('_')[-1])
    order = await fetchone("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not order:
        await query.edit_message_text("❌ Заказ не найден.")
        return

    # 🔐 Защита от повторного отклонения
    if order["status"] in ("delivered", "cancelled_by_client", "rejected"):
        await query.edit_message_text("⚠️ Заказ уже завершён или отменён.")
        return

    if str(order["deducted_from_stock"]) == "1":

        try:
            cart = json.loads(order["cart"])
            for variant_id_str, item in cart.items():
                await execute(
                    "UPDATE product_variants SET quantity = quantity + ? WHERE id = ?",
                    (item['quantity'], int(variant_id_str))
                )
            await execute("UPDATE orders SET deducted_from_stock = 0 WHERE id = ?", (order_id,))

        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка при возврате товаров: {e}")
            return
    else:
        cart = json.loads(order['cart'])

    # 🧾 Формируем состав заказа
    cart_text = "\n".join([
        f"• {item['name']} x{item['quantity']}" for item in cart.values()
    ])

    # 👤 Получаем username (если есть)
    username = None
    try:
        user_obj = await context.bot.get_chat(order["user_id"])
        username = user_obj.username
    except Exception:
        pass

    user_link = (
        f'<a href="https://t.me/{username}">@{username}</a>' if username else "нет username"
    )

    support_user = "candyy_sh0p"
    admin_link = f'<a href="https://t.me/{support_user}">@{support_user}</a>'

    # 📦 Информация для админа
    order_info_admin = (
        f"<b>📦 Информация о заказе №{order_id}</b>\n\n"
        f"<b>Сумма:</b> {order['total_price']} ₸\n"
        f"<b>Клиент:</b> {order['user_name']}\n"
        f"<b>Username:</b> {user_link}\n"
        f"<b>Телефон:</b> {order['user_phone']}\n"
        f"<b>Адрес:</b> {order['user_address']}\n\n"
        f"<b>Состав заказа:</b>\n{cart_text}"
    )

    # 📩 Информация для клиента
    order_info_user = (
        f"<b>📦 Информация о заказе №{order_id}</b>\n\n"
        f"<b>Сумма:</b> {order['total_price']} ₸\n"
        f"<b>Клиент:</b> {order['user_name']}\n"
        f"<b>Телефон:</b> {order['user_phone']}\n"
        f"<b>Адрес:</b> {order['user_address']}\n\n"
        f"<b>Состав заказа:</b>\n{cart_text}\n\n"
        f"Админ: {admin_link}"
    )

    # ❌ Обновляем статус
    await execute("UPDATE orders SET status = ? WHERE id = ?", ("rejected", order_id))

    # 🛑 Уведомляем админа
    await query.edit_message_text(
        f"❌ Заказ №{order_id} отклонён админом.\n\n{order_info_admin}",
        parse_mode=ParseMode.HTML
    )

    # 📩 Уведомляем клиента
    await context.bot.send_message(
        chat_id=order["user_id"],
        text=f"❌ Ваш заказ №{order_id} был отклонен администратором.\n\n{order_info_user}",
        parse_mode=ParseMode.HTML
    )




# --- Статусы ---
def is_active(status: str) -> bool:
    return status in ("pending_payment", "confirmed", "preparing", "shipped")


def is_finished(status):
    return status in ("delivered", "cancelled_by_client", "rejected")

# --- История заказов клиента ---
async def order_history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await asyncio.sleep(0.5)

    context.user_data["order_history_started"] = True

    filter_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Все", callback_data="order_filter_all"),
            InlineKeyboardButton("🟡 Активные", callback_data="order_filter_active"),
            InlineKeyboardButton("✅ Завершённые", callback_data="order_filter_finished") , 
            InlineKeyboardButton("◀ назад " , callback_data="back_to_main_menu" )
        ]
    ])

    await query.edit_message_text(
        text="📋 Выберите, какие заказы хотите посмотреть:",
        parse_mode=ParseMode.HTML,
        reply_markup=filter_keyboard
    )


async def order_filter_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await asyncio.sleep(0.5)

    

    filter_type = query.data.replace("order_filter_", "")
    context.user_data["order_filter"] = filter_type

    user_id = update.effective_user.id
    orders = await fetchall("SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC", (user_id,))

    if filter_type == "active":
        orders = [o for o in orders if is_active(o["status"])]
    elif filter_type == "finished":
        orders = [o for o in orders if is_finished(o["status"])]

    if not orders:
        back_btn = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Назад к истории заказов", callback_data="back_to_order_history")]
        ])
        await query.edit_message_text(
            "❗ У вас пока нет заказов по выбранному фильтру.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_btn
        )
        return

    context.user_data["order_list"] = orders
    await show_orders_text(update, context, orders, filter_type, 0)


async def pagination_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    _, filter_type, page_str = query.data.split("_")
    page = int(page_str)
    orders = context.user_data.get("order_list", [])

    await show_orders_text(update, context, orders, filter_type, page)


async def show_orders_text(update, context, orders, filter_type, page):
    query = update.callback_query
    ORDERS_PER_PAGE = 1
    start = page * ORDERS_PER_PAGE
    end = start + ORDERS_PER_PAGE
    total_pages = (len(orders) - 1) // ORDERS_PER_PAGE + 1
    sliced_orders = orders[start:end]

    status_names = {
        "pending_payment": "Ожидает оплату",
        "confirmed": "Подтверждён",
        "preparing": "Готовится к доставке",
        "shipped": "Отправлен",
        "delivered": "Доставлен",
        "cancelled_by_client": "Отменён клиентом",
        "rejected": "Отклонён"
    }

    order = sliced_orders[0]
    order_id = f"{order['id']}"
    raw_status = order["status"]
    status = f"{status_names.get(raw_status, raw_status)}"
    total = f"{order['total_price']}"
    cart = json.loads(order["cart"])
    cart_text = "\n".join([
        f"• {item['name']} (x{item['quantity']})" for item in cart.values()
    ])
    msg = (
        f"🧾 <b>Чек №{order_id}</b>\n\n"
        f"<b>Клиент:</b> {order['user_name']}\n"
        f"<b>Тел:</b> {order['user_phone']}\n"
        f"<b>Адрес:</b> {order['user_address']}\n\n"
        f"<b>Сумма:</b> {total} ₸\n\n"
        f"<b>Статус:</b> <i>{status}</i>\n\n"
        f"<b>Состав:</b>\n{cart_text}\n\n"
        f"<b>Дата:</b> {order['created_at']}"
    )

    buttons = []
    if is_active(raw_status):
        buttons.append([InlineKeyboardButton("❌ Отменить заказ", callback_data=f"cancel_from_history_{order['id']}")])

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️ Назад", callback_data=f"page_{filter_type}_{page - 1}"))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton("▶️ Далее", callback_data=f"page_{filter_type}_{page + 1}"))
    if nav:
        buttons.append(nav)

    buttons.append([InlineKeyboardButton("🔙 Назад к истории заказов", callback_data="back_to_order_history")])

    await query.edit_message_text(
        text=msg,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(buttons)
    )


async def cancel_from_history_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split('_')[-1])

    order = await fetchone("SELECT status FROM orders WHERE id = ?", (order_id,))
    if not order or order["status"] in ("delivered", "cancelled_by_client", "rejected"):
        await query.edit_message_text("⚠️ Этот заказ уже завершён или отменён. Отмена невозможна.")
        return

       
    keyboard = [
        [
            InlineKeyboardButton("✅ Да, отменить", callback_data=f"confirm_cancel_from_history_{order_id}"),
            InlineKeyboardButton("🔙 Назад", callback_data=f"order_filter_{context.user_data.get('order_filter', 'all')}")
        ]
    ]
    await query.edit_message_text(
        text="❗ Вы уверены, что хотите отменить этот заказ?",
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def confirm_cancel_from_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split('_')[-1])

    # Сразу получаем всё, что нужно
    order = await fetchone("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not order:
        await query.edit_message_text("⚠️ Заказ не найден.")
        return

    if order["status"] in ("delivered", "cancelled_by_client", "rejected"):
        await query.edit_message_text("⚠️ Этот заказ уже завершён или отменён. Отмена невозможна.")
        return

    # 🔄 Возвращаем товар на склад, если был списан
    if str(order["deducted_from_stock"]) == "1":
        try:
            cart = json.loads(order["cart"])
            for variant_id_str, item in cart.items():
                await execute(
                    "UPDATE product_variants SET quantity = quantity + ? WHERE id = ?",
                    (item['quantity'], int(variant_id_str))
                )
            await execute("UPDATE orders SET deducted_from_stock = 0 WHERE id = ?", (order_id,))
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка при возврате товара на склад: {e}")
            return

    # 🛑 Меняем статус заказа
    await execute("UPDATE orders SET status = ? WHERE id = ?", ("cancelled_by_client", order_id))
    await query.edit_message_text("❌ Заказ был отменён.")

    # 👤 Получаем username
    username = None
    try:
        user_obj = await context.bot.get_chat(order["user_id"])
        username = user_obj.username
    except Exception:
        pass

    user_link = f'<a href="https://t.me/{username}">@{username}</a>' if username else "нет username"

    # 🧾 Формируем состав заказа
    cart = json.loads(order['cart'])
    cart_text = "\n".join([
        f"• {item['name']} x{item['quantity']}" for item in cart.values()
    ])

    # 📦 Информация для админа
    order_info_admin = (
        f"<b>📦 Информация о заказе №{order_id}</b>\n\n"
        f"<b>Сумма:</b> {order['total_price']} ₸\n"
        f"<b>Клиент:</b> {order['user_name']}\n"
        f"<b>Username:</b> {user_link}\n"
        f"<b>Телефон:</b> {order['user_phone']}\n"
        f"<b>Адрес:</b> {order['user_address']}\n\n"
        f"<b>Состав заказа:</b>\n{cart_text}"
    )

    for admin_id in ADMIN_IDS:
        await context.bot.send_message(
            admin_id,
            f"⚠️ Клиент отменил заказ №{order_id}\n\n*Изменение статуса отключено* — заказ отменён клиентом\n\n{order_info_admin}",
            parse_mode=ParseMode.HTML
        )



async def back_to_order_history(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data["order_history_started"] = True

    filter_keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📋 Все", callback_data="order_filter_all"),
            InlineKeyboardButton("🟡 Активные", callback_data="order_filter_active"),
            InlineKeyboardButton("✅ Завершённые", callback_data="order_filter_finished"),
            InlineKeyboardButton("◀ Назад" , callback_data="back_to_main_menu")
        ]
    ])

    await query.edit_message_text(
        text="📋 Выберите, какие заказы хотите посмотреть:",
        parse_mode=ParseMode.HTML,
        reply_markup=filter_keyboard
    )










from telegram import InlineKeyboardButton, InlineKeyboardMarkup

# ----- Управление категориями -----
# Команда для админа — показать список категорий с кнопками
async def manage_categories(update, context):
    categories = await fetchall("SELECT * FROM categories")
    keyboard = []
    for cat in categories:
        keyboard.append([
            InlineKeyboardButton(f"{cat['name']}", callback_data=f"cat_manage_{cat['id']}"),
            InlineKeyboardButton("🗑️", callback_data=f"cat_delete_{cat['id']}")
        ])
    msg = get_effective_message(update)
    if msg:
        await msg.reply_text("Категории:", reply_markup=InlineKeyboardMarkup(keyboard))

# Обработчик ВСЕХ callback_data по категориям
async def handle_cat_manage(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data

    print("DEBUG: data =", data)  # Для дебага

    if data.startswith("cat_delete_confirm_"):
        parts = data.split("_")
        print("DEBUG: parts =", parts)
        if len(parts) == 4 and parts[3].isdigit():
            cat_id = int(parts[3])
            await execute("DELETE FROM categories WHERE id = ?", (cat_id,))
            await execute("DELETE FROM sub_categories WHERE category_id = ?", (cat_id,))
            await query.edit_message_text(f"Категория {cat_id} и все её разделы удалены.")
        else:
            await query.edit_message_text("Ошибка: не удалось определить категорию для удаления.")
    elif data.startswith("cat_delete_"):
        parts = data.split("_")
        print("DEBUG: parts =", parts)
        if len(parts) == 3 and parts[2].isdigit():
            cat_id = int(parts[2])
            keyboard = [
                [InlineKeyboardButton("✅ Да, удалить", callback_data=f"cat_delete_confirm_{cat_id}")],
                [InlineKeyboardButton("❌ Нет, отмена", callback_data="cat_delete_cancel")]
            ]
            await query.edit_message_text(
                f"Удалить категорию {cat_id}?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text("Ошибка: не удалось определить категорию для удаления.")
    elif data == "cat_delete_cancel":
        await query.edit_message_text("Удаление отменено.")
    else:
        await query.edit_message_text("Неизвестное действие.")


async def category_rename_text(update, context):
    if context.user_data.get('await_rename_category'):
        cat_id = context.user_data['rename_cat_id']
        new_name = update.message.text
        await execute("UPDATE categories SET name = ? WHERE id = ?", (new_name, cat_id))
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text(f"Категория переименована в {new_name}.")
        context.user_data['await_rename_category'] = False

# ----- Управление подкатегориями -----
async def manage_subcategories(update, context):
    cat_id = context.user_data.get('category_id_for_subcat')
    if not cat_id:
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text("ID категории не определён. Повторите попытку через меню.")
        return
    subcats = await fetchall("SELECT * FROM sub_categories WHERE category_id = ?", (cat_id,))

    if not subcats:
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text("В этой категории нет подкатегорий.")
        return

    keyboard = []
    for sub in subcats:
        keyboard.append([
            InlineKeyboardButton(f"{sub['name']}", callback_data=f"subcat_manage_{sub['id']}"),
            InlineKeyboardButton("✏️", callback_data=f"subcat_rename_{sub['id']}"),
            InlineKeyboardButton("🗑️", callback_data=f"subcat_delete_{sub['id']}")
        ])
    msg = get_effective_message(update)
    if msg:
        await msg.reply_text("Разделы:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_subcat_manage(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("subcat_rename_"):
        parts = data.split("_")
        if parts[-1].isdigit():
            subcat_id = int(parts[-1])
            context.user_data['rename_subcat_id'] = subcat_id
            await query.edit_message_text("Введите новое название для раздела:")
            context.user_data['await_rename_subcat'] = True
            return  RENAME_SUBCAT
        else:
            await query.edit_message_text("Ошибка: не удалось определить раздел.")

    elif data.startswith("subcat_delete_confirm_"):
        parts = data.split("_")
        if parts[-1].isdigit():
            subcat_id = int(parts[-1])
            await execute("DELETE FROM sub_categories WHERE id = ?", (subcat_id,))
            await query.edit_message_text(f"Раздел {subcat_id} удален.")
        else:
            await query.edit_message_text("Ошибка: не удалось определить раздел для удаления.")

    elif data.startswith("subcat_delete_"):
        parts = data.split("_")
        if parts[-1].isdigit():
            subcat_id = int(parts[-1])
            keyboard = [
                [InlineKeyboardButton("✅ Да, удалить", callback_data=f"subcat_delete_confirm_{subcat_id}")],
                [InlineKeyboardButton("❌ Нет, отмена", callback_data="subcat_delete_cancel")]
            ]
            await query.edit_message_text(
                f"Удалить раздел {subcat_id} и все его товары?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text("Ошибка: не удалось определить раздел для удаления.")

    elif data == "subcat_delete_cancel":
        await query.edit_message_text("Удаление отменено.")

    else:
        await query.answer("Неизвестное действие.", show_alert=True)








RENAME_SUBCAT = 2002

async def start_rename_subcat(update, context):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if parts[-1].isdigit():
        subcat_id = int(parts[-1])
        context.user_data['rename_subcat_id'] = subcat_id
        await query.edit_message_text("Введите новое название для раздела:")
        return RENAME_SUBCAT
    else:
        await query.edit_message_text("Ошибка: не удалось определить раздел.")
        return ConversationHandler.END

async def finish_rename_subcat(update, context):
    subcat_id = context.user_data.get('rename_subcat_id')
    new_name = update.message.text
    msg = get_effective_message(update)
    if not subcat_id or not new_name:
        if msg:
            await msg.reply_text("Ошибка: не удалось переименовать раздел.")
        return ConversationHandler.END
    await execute("UPDATE sub_categories SET name = ? WHERE id = ?", (new_name, subcat_id))
    if msg:
        await msg.reply_text(f"Раздел переименован в {new_name}.")
    context.user_data.pop('rename_subcat_id', None)
    return ConversationHandler.END

async def cancel_rename_subcat(update, context):
    msg = get_effective_message(update)
    if msg:
        await msg.reply_text("Переименование отменено.")
    context.user_data.pop('rename_subcat_id', None)
    return ConversationHandler.END



# ----- Управление брендами -----
async def manage_brands(update, context):
    brands = await fetchall("SELECT * FROM brands")
    if not brands:
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text("Бренды пока не созданы.")
        return

    keyboard = []
    for b in brands:
        keyboard.append([
            InlineKeyboardButton(f"{b['name']}", callback_data=f"brand_manage_{b['id']}"),
            InlineKeyboardButton("✏️", callback_data=f"brand_rename_{b['id']}"),
            InlineKeyboardButton("🗑️", callback_data=f"brand_delete_{b['id']}")
        ])
    msg = get_effective_message(update)
    if msg:
        await msg.reply_text("Бренды:", reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_brand_manage(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data.startswith("brand_rename_"):
        parts = data.split("_")
        if parts[-1].isdigit():
            brand_id = int(parts[-1])
            context.user_data['rename_brand_id'] = brand_id
            await query.edit_message_text("Введите новое название для бренда:")
            context.user_data['await_rename_brand'] = True
            return RENAME_BRAND
        else:
            await query.edit_message_text("Ошибка: не удалось определить бренд.")

    elif data.startswith("brand_delete_confirm_"):
        parts = data.split("_")
        if parts[-1].isdigit():
            brand_id = int(parts[-1])
            await execute("DELETE FROM brands WHERE id = ?", (brand_id,))
            await query.edit_message_text(f"Бренд {brand_id} удален.")
        else:
            await query.edit_message_text("Ошибка: не удалось определить бренд для удаления.")

    elif data.startswith("brand_delete_"):
        parts = data.split("_")
        if parts[-1].isdigit():
            brand_id = int(parts[-1])
            keyboard = [
                [InlineKeyboardButton("✅ Да, удалить", callback_data=f"brand_delete_confirm_{brand_id}")],
                [InlineKeyboardButton("❌ Нет, отмена", callback_data="brand_delete_cancel")]
            ]
            await query.edit_message_text(
                f"Удалить бренд {brand_id}?",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.edit_message_text("Ошибка: не удалось определить бренд для удаления.")

    elif data == "brand_delete_cancel":
        await query.edit_message_text("Удаление отменено.")

    else:
        await query.answer("Неизвестное действие.", show_alert=True)

from telegram.ext import ConversationHandler, CallbackQueryHandler, MessageHandler, CommandHandler, filters

RENAME_BRAND = 2001

async def start_rename_brand(update, context):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    if parts[-1].isdigit():
        brand_id = int(parts[-1])
        context.user_data['rename_brand_id'] = brand_id
        await query.edit_message_text("Введите новое название для бренда:")
        return RENAME_BRAND
    else:
        await query.edit_message_text("Ошибка: не удалось определить бренд.")
        return ConversationHandler.END

async def finish_rename_brand(update, context):
    brand_id = context.user_data.get('rename_brand_id')
    new_name = update.message.text
    if not brand_id or not new_name:
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text("Ошибка: не удалось переименовать бренд.")
        return ConversationHandler.END
    await execute("UPDATE brands SET name = ? WHERE id = ?", (new_name, brand_id))
    msg = get_effective_message(update)
    if msg:
        await msg.reply_text(f"Бренд переименован в {new_name}.")
    context.user_data.pop('rename_brand_id', None)
    return ConversationHandler.END

async def cancel_rename_brand(update, context):
    msg = get_effective_message(update)
    if msg:
        await msg.reply_text("Переименование отменено.")
    context.user_data.pop('rename_brand_id', None)
    return ConversationHandler.END



# --- Регистрация хендлеров ---

(
    ADMIN_MENU_AWAIT,
    ADMIN_EDIT_AWAIT_ID,
    ADMIN_SUBCAT_AWAIT_ID,
    
    
) = range(500, 503)

def admin_menu_keyboard():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Добавить товар", callback_data="admin_add_new_product")],
        [InlineKeyboardButton("✏️ Редактировать товар", callback_data="admin_edit_product")],
        [InlineKeyboardButton("📂 Категории", callback_data="admin_manage_categories")],
        [InlineKeyboardButton("📁 Подкатегории", callback_data="admin_manage_subcategories")],
        [InlineKeyboardButton("🏷️ Бренды", callback_data="admin_manage_brands")],
        [InlineKeyboardButton("📊 Отчёт", callback_data="admin_report")],
        [InlineKeyboardButton("📦 Отчёт по заказам", callback_data="admin_orders_report")],
    ])



async def admin_menu_entry(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Входная точка для всей админ-панели."""
    if not is_admin(update.effective_user.id):
        await update.message.reply_text("Нет доступа.")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "⚙️ <b>Админ-панель. Выберите действие:</b>",
        reply_markup=admin_menu_keyboard(),
        parse_mode=ParseMode.HTML
    )
    return ADMIN_MENU_AWAIT

async def admin_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обрабатывает нажатия в главном меню админки."""
    query = update.callback_query
    await query.answer()
    data = query.data

    # Эти команды не меняют состояние, а просто выполняют действие и выходят из диалога
    if data in ["admin_manage_categories", "admin_manage_brands", "admin_report", "admin_orders_report"]:
        if data == "admin_manage_categories":
            await query.edit_message_text("Управление категориями:")
            await manage_categories(update, context) # Предполагается, что эта функция существует
        # ... (здесь другие elif для брендов, отчетов) ...
        elif data == "admin_manage_subcategories":
            await query.edit_message_text("Введите ID категории для управления подкатегориями:")
            return ADMIN_SUBCAT_AWAIT_ID

        elif data == "admin_manage_brands":
            await query.edit_message_text("Управление брендами:")
            await manage_brands(update, context)
            return ConversationHandler.END  # <----- обязательно!

        elif data == "admin_report":
            await query.edit_message_text(f"Формирую отчёт... \nПожалуйста подождите 10-20 секунд.")
            await report_combined(update, context)
            return ConversationHandler.END  # <----- обязательно!

        elif data == "admin_orders_report":
            await query.edit_message_text("Формирую отчёт по заказам...")
            await ask_orders_report_period(update, context)
            return ConversationHandler.END  # <----- обязательно!

        return ConversationHandler.END

    # Эти команды переводят диалог в новое состояние
    elif data == "admin_edit_product":
        await query.edit_message_text("Введите ID товара для редактирования:")
        return ADMIN_AWAIT_EDIT_ID
        
    elif data == "admin_manage_subcategories":
        await query.edit_message_text("Введите ID категории для управления подкатегориями:")
        return ADMIN_AWAIT_SUBCAT_ID

    return ADMIN_MENU_AWAIT

async def admin_await_edit_id(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Получает ID товара и переходит в меню редактирования."""
    product_id = update.message.text.strip()
    if not product_id.isdigit():
        await update.message.reply_text("Некорректный ID. Попробуйте ещё раз.")
        return ADMIN_AWAIT_EDIT_ID
    
    context.user_data['product_to_edit_id'] = int(product_id)
    await show_edit_menu(update, context)
    return EDIT_AWAIT_ACTION

async def admin_subcat_await_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    category_id = update.message.text.strip()
    if not category_id.isdigit():
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text("Некорректный ID категории, попробуйте ещё раз или /cancel для отмены.")
        return ADMIN_SUBCAT_AWAIT_ID
    context.user_data['category_id_for_subcat'] = int(category_id)
    await manage_subcategories(update, context)
    return ConversationHandler.END


# =================================================================
# === СОЗДАНИЕ HANDLERS ===
# =================================================================

add_product_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_add_product, pattern="^admin_add_new_product$")],
    states={
        ADD_GET_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_name)],
        ADD_GET_CATEGORY: [CallbackQueryHandler(get_category, pattern="^cat_")],
        ADD_GET_NEW_CATEGORY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_category_name)],
        ADD_GET_SUBCATEGORY: [CallbackQueryHandler(get_subcategory, pattern="^subcat_")],
        ADD_GET_NEW_SUBCATEGORY_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_subcategory_name)],
        ADD_GET_BRAND: [CallbackQueryHandler(get_brand, pattern="^brand_")],
        ADD_GET_NEW_BRAND_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_brand_name)],
        ADD_GET_DESCRIPTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_description)],
        ADD_GET_VARIANT_SIZE: [CallbackQueryHandler(get_variant_size, pattern="^size_")],
        ADD_GET_NEW_SIZE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_size_name)],
        ADD_GET_VARIANT_COLOR: [CallbackQueryHandler(get_variant_color, pattern="^color_")],
        ADD_GET_NEW_COLOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_color_name)],
        ADD_GET_VARIANT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_variant_price)],
        ADD_GET_VARIANT_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_variant_quantity)],
        ADD_GET_VARIANT_MEDIA: [
            MessageHandler(filters.PHOTO | filters.VIDEO, add_media),
            CommandHandler('done', finish_media)
        ],
        ADD_ASK_ADD_MORE_VARIANTS: [CallbackQueryHandler(ask_add_more_variants, pattern="^add_more_variants$|^finish_add_product$")]
    },
    fallbacks=[CommandHandler("cancel", cancel_dialog)],
    per_user=True,
    per_chat=True,
    persistent=True, 
    name="add_product_conversation"
)


edit_product_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_edit_product, pattern=r"^admin_edit_product$")],
    states={
        EDIT_AWAIT_ACTION: [
            CallbackQueryHandler(handle_edit_action, pattern=r"^(delete_variant_|delete_product_full_|edit_variant_menu_|edit_cancel|back_to_edit_menu|add_variant_to_)")
        ],
        EDIT_CONFIRM_DELETE_VARIANT: [
            CallbackQueryHandler(confirm_variant_delete, pattern=r"^confirm_delete_variant$|^cancel_delete$"),
        ],
        EDIT_CONFIRM_DELETE_FULL_PRODUCT: [
            CallbackQueryHandler(confirm_full_product_delete, pattern=r"^confirm_delete_full$|^cancel_delete$"),
        ],
        EDIT_SELECT_VARIANT_FIELD: [
            CallbackQueryHandler(select_variant_field_to_edit, pattern=r"^edit_field_|^back_to_edit_menu$")
        ],
        EDIT_GET_NEW_VARIANT_VALUE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_variant_value)
        ],
        # Состояния для добавления медиа во время редактирования
        EDIT_ADD_VARIANT_MEDIA: [
            MessageHandler(filters.PHOTO | filters.VIDEO, add_media),
            CommandHandler('done', show_edit_menu) # После /done возвращаемся в меню
        ],
        # Состояния для добавления нового варианта ВНУТРИ редактирования
        EDIT_ADD_VARIANT_SIZE: [CallbackQueryHandler(get_variant_size, pattern="^size_")],
        EDIT_GET_NEW_SIZE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_size_name)],
        EDIT_ADD_VARIANT_COLOR: [CallbackQueryHandler(get_variant_color, pattern="^color_")],
        EDIT_GET_NEW_COLOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_color_name)],
        EDIT_ADD_VARIANT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_variant_price)],
        EDIT_ADD_VARIANT_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_variant_quantity)],
    },
    fallbacks=[CommandHandler("cancel", cancel_dialog)],
    per_user=True,
    per_chat=True,
    persistent=True,
    name="edit_product_conversation"
)


# ЕДИНЫЙ обработчик для всей админ-панели и редактирования
admin_conv = ConversationHandler(
    entry_points=[CommandHandler("admin", admin_menu_entry)],
    states={
        ADMIN_MENU_AWAIT: [
            CallbackQueryHandler(admin_menu_callback, pattern=r"^admin_")
        ],
        ADMIN_AWAIT_EDIT_ID: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_await_edit_id)
        ],
        EDIT_AWAIT_ACTION: [
            CallbackQueryHandler(handle_edit_action)
        ],
        EDIT_CONFIRM_DELETE_VARIANT: [
            CallbackQueryHandler(confirm_variant_delete, pattern=r"^confirm_delete_variant$|^cancel_delete$"),
        ],

        EDIT_CONFIRM_DELETE_VARIANT: [
            CallbackQueryHandler(confirm_variant_delete, pattern=r"^confirm_delete_variant$|^cancel_delete$"),
        ],
        EDIT_CONFIRM_DELETE_FULL_PRODUCT: [
            CallbackQueryHandler(confirm_full_product_delete, pattern=r"^confirm_delete_full$|^cancel_delete$"),
        ],
        EDIT_SELECT_VARIANT_FIELD: [
            CallbackQueryHandler(select_variant_field_to_edit, pattern=r"^edit_field_|^back_to_edit_menu$")
        ],
        EDIT_GET_NEW_VARIANT_VALUE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_variant_value)
        ],
        # Состояния для добавления медиа во время редактирования
        EDIT_ADD_VARIANT_MEDIA: [
            MessageHandler(filters.PHOTO | filters.VIDEO, add_media),
            CommandHandler('done', show_edit_menu) # После /done возвращаемся в меню
        ],
        # Состояния для добавления нового варианта ВНУТРИ редактирования
        EDIT_ADD_VARIANT_SIZE: [CallbackQueryHandler(get_variant_size, pattern="^size_")],
        EDIT_GET_NEW_SIZE_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_size_name)],
        EDIT_ADD_VARIANT_COLOR: [CallbackQueryHandler(get_variant_color, pattern="^color_")],
        EDIT_GET_NEW_COLOR_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_color_name)],
        EDIT_ADD_VARIANT_PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_variant_price)],
        EDIT_ADD_VARIANT_QUANTITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, get_variant_quantity)],
    
        ADMIN_AWAIT_SUBCAT_ID: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_subcat_await_id)
        ],
    },
    fallbacks=[CommandHandler("cancel", cancel_dialog)],
    persistent=True, name="admin_panel_conversation"
)


subcat_rename_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_rename_subcat, pattern=r"^subcat_rename_\d+$")],
    states={
        RENAME_SUBCAT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, finish_rename_subcat),
        ],
    },
    fallbacks=[MessageHandler(filters.COMMAND, cancel_rename_subcat)],
    per_user=True,
    per_chat=True
)

brand_rename_conv = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_rename_brand, pattern=r"^brand_rename_\d+$")],
    states={
        RENAME_BRAND: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, finish_rename_brand),
        ],
    },
    fallbacks=[MessageHandler(filters.COMMAND, cancel_rename_brand)],
    per_user=True,
    per_chat=True,
)

# === Одиночные CallbackHandlers ===
cat_manage_handler = CallbackQueryHandler(
    handle_cat_manage,
    pattern=r"^cat_delete_\d+$|^cat_delete_confirm_\d+$|^cat_delete_cancel$"
)
subcat_manage_handler = CallbackQueryHandler(
    handle_subcat_manage,
    pattern=r"^subcat_(delete|manage)_\d+$|^subcat_delete_confirm_\d+$|^subcat_delete_cancel$"
)
brand_manage_handler = CallbackQueryHandler(
    handle_brand_manage,
    pattern=r"^brand_(delete|manage)_\d+$|^brand_delete_confirm_\d+$|^brand_delete_cancel$"
)
cat_rename_text_handler = MessageHandler(filters.TEXT & ~filters.COMMAND, category_rename_text)
# === Админские действия ===
report_handler = CallbackQueryHandler(report_combined, pattern=r"^admin_report$")
orders_report_handler = CallbackQueryHandler(ask_orders_report_period, pattern=r"^admin_orders_report$")
orders_report_period_handler = CallbackQueryHandler(handle_orders_report_period, pattern=r"^orders_report_(today|3days|7days|30days)$")
admin_decision_handler = CallbackQueryHandler(handle_admin_decision, pattern=r"^admin_(confirm|reject)_\d+$")