import json
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup , CallbackQuery 
from telegram.ext import (
    CommandHandler,
    ContextTypes,
    ConversationHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)
from telegram.constants import ParseMode
import logging
import asyncio
import re
import telegram.error
from telegram.helpers import escape_markdown
from configs import ADMIN_IDS
from db import fetchall, fetchone, execute

(
    GET_NAME, GET_CATEGORY, GET_SUBCATEGORY, GET_BRAND, GET_DESCRIPTION,
    GET_NEW_CATEGORY_NAME, GET_NEW_SUBCATEGORY_NAME, GET_NEW_BRAND_NAME,
    GET_NEW_SIZE_NAME, GET_NEW_COLOR_NAME,
    SELECT_VARIANT_SIZE, SELECT_VARIANT_COLOR,
    GET_VARIANT_PRICE, GET_VARIANT_QUANTITY, GET_VARIANT_PHOTO,
    ASK_ADD_MORE_VARIANTS,
    AWAIT_EDIT_ACTION,
    CONFIRM_DELETE_VARIANT, CONFIRM_DELETE_FULL_PRODUCT,
    SELECT_VARIANT_FIELD, GET_NEW_VARIANT_VALUE,
    SELECT_GENERAL_FIELD, GET_NEW_GENERAL_VALUE
) = range(23)

def get_effective_message(update):
    # Вернёт message для обычного сообщения или callback_query.message для кнопки
    if getattr(update, "message", None):
        return update.message
    elif getattr(update, "callback_query", None):
        return update.callback_query.message
    return None


def md2(text):
    if not isinstance(text, str):
        text = str(text)
    return re.sub(r'([_\*\[\]\(\)\~\`\>\#\+\-\=\|\{\}\.\!])', r'\\\1', text)

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

async def cancel_dialog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    
    logging.warning(f"FSM CANCELLED. Callback: {getattr(update.callback_query, 'data', None)}; Message: {getattr(update.message, 'text', None)}; State: {context.user_data.get('state')}")
    

    context.user_data.clear()
    message = md2("Действие отменено.")
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.edit_message_text(text=message, parse_mode="MarkdownV2")
    else:
        await update.message.reply_text(message, parse_mode="MarkdownV2")
    return ConversationHandler.END

async def create_new_entity(update, context, table_name, name, **kwargs):
    params = (name,)
    query = f"INSERT INTO {table_name} (name) VALUES (?)"
    if table_name == 'sub_categories':
        params = (name, kwargs['category_id'])
        query = "INSERT INTO sub_categories (name, category_id) VALUES (?, ?)"
    try:
        await execute(query, params)
        entity_row = await fetchone(f"SELECT id FROM {table_name} WHERE name = ? {'AND category_id = ?' if table_name == 'sub_categories' else ''}", params)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=md2(f"Сущность '{name}' успешно создана."), parse_mode="MarkdownV2")
        return entity_row['id']
    except Exception:
        entity_row = await fetchone(f"SELECT id FROM {table_name} WHERE name = ? {'AND category_id = ?' if table_name == 'sub_categories' else ''}", params)
        await context.bot.send_message(chat_id=update.effective_chat.id, text=md2(f"Сущность '{name}' уже существует. Выбираю существующую."), parse_mode="MarkdownV2")
        return entity_row['id']
        

# --- Добавление товара ---
async def start_add_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(md2("Нет доступа."), parse_mode="MarkdownV2")
        return 
    context.user_data.clear()
    context.user_data["state"] = "get_product_name"
    query = update.callback_query
    await query.answer()
    await query.edit_message_text(md2("Добавляем новый товар. Введите его общее название.\n\n/cancel для отмены."), parse_mode="MarkdownV2")
    return 

async def get_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("DEBUG: get_name called")
    print("Text received:", update.message.text)

    product_name = update.message.text.strip()
    if not product_name:
        await update.message.reply_text("Название не может быть пустым. Попробуйте ещё раз.")
        return
    
    context.user_data['new_product_name'] = product_name
    context.user_data["state"] = "choose_category"
    print("DEBUG: state changed to choose_category")

    categories = await fetchall("SELECT * FROM categories")
    keyboard = [[InlineKeyboardButton(cat['name'], callback_data=f"add_cat_{cat['id']}")] for cat in categories]
    keyboard.append([InlineKeyboardButton("➕ Создать категорию", callback_data="add_cat_new")])

    await update.message.reply_text(
        md2("Шаг 1: Выберите основную категорию:"),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="MarkdownV2"
    )


async def get_category(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "choose_category"
    query = update.callback_query
    await query.answer()
    if query.data == "add_cat_new":
        context.user_data["state"] = "get_new_category_name"
        await query.edit_message_text(md2("Введите название новой основной категории:"), parse_mode="MarkdownV2")
        return
    parts = query.data.split('_')
    if len(parts) == 3 and parts[2].isdigit():
        context.user_data['new_product_category_id'] = int(parts[2])
        context.user_data["state"] = "choose_subcategory"
        await ask_for_subcategory(update, context)
        return   
    else:
        await query.answer("Ошибка формата категории.", show_alert=True)
        return 

async def get_new_category_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    category_id = await create_new_entity(update, context, 'categories', update.message.text)
    context.user_data['new_product_category_id'] = category_id
    context.user_data["state"] = "choose_subcategory"
    await ask_for_subcategory(update, context)

async def ask_for_subcategory(update, context):
    context.user_data["state"] = "choose_subcategory"
    category_id = context.user_data['new_product_category_id']
    sub_categories = await fetchall("SELECT * FROM sub_categories WHERE category_id = ?", (category_id,))
    keyboard = [[InlineKeyboardButton(scat['name'], callback_data=f"add_subcat_{scat['id']}")] for scat in sub_categories]
    keyboard.append([InlineKeyboardButton("➕ Создать подкатегорию", callback_data="add_subcat_new")])
    message_text = md2("Шаг 2: Выберите подкатегорию:")
    if getattr(update, 'callback_query', None):
        await update.callback_query.edit_message_text(text=message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    else:
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text(
                text=message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2"
            )
    return

async def get_subcategory(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "choose_subcategory"
    query = update.callback_query
    await query.answer()
    if query.data == "add_subcat_new":
        context.user_data["state"] = "get_new_subcategory_name"
        await query.edit_message_text(md2("Введите название новой подкатегории:"), parse_mode="MarkdownV2")
        return 
    parts = query.data.split('_')
    if len(parts) == 3 and parts[2].isdigit():
        context.user_data['new_product_sub_category_id'] = int(parts[2])
        context.user_data["state"] = "choose_brand"
        await ask_for_brand(update, context)
    else:
        await query.answer("Ошибка формата подкатегории.", show_alert=True)
        return

async def get_new_subcategory_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "get_new_subcategory_name"
    category_id = context.user_data['new_product_category_id']
    subcat_id = await create_new_entity(update, context, 'sub_categories', update.message.text, category_id=category_id)
    context.user_data['new_product_sub_category_id'] = subcat_id
    context.user_data["state"] = "choose_brand"
    await ask_for_brand(update, context)

async def ask_for_brand(update, context):
    context.user_data["state"] = "choose_brand"
    brands = await fetchall("SELECT * FROM brands")
    keyboard = [[InlineKeyboardButton(b['name'], callback_data=f"add_brand_{b['id']}")] for b in brands]
    keyboard.append([InlineKeyboardButton("➕ Создать новый бренд", callback_data="add_brand_new")])
    message_text = md2("Шаг 3: Выберите бренд:")
    if getattr(update, 'callback_query', None):
        await update.callback_query.edit_message_text(text=message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    else:
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text(text=message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    return


# === Часть 2: Бренд, описание, варианты, добавление, исправления по кнопкам/состояниям ===

async def get_brand(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "choose_brand"
    query = update.callback_query
    await query.answer()
    if query.data == "add_brand_new":
        context.user_data["state"] = "get_new_brand_name"
        await query.edit_message_text(md2("Введите название нового бренда:"), parse_mode="MarkdownV2")
        return
    parts = query.data.split('_')
    if len(parts) == 3 and parts[2].isdigit():
        context.user_data['new_product_brand_id'] = int(parts[2])
        context.user_data["state"] = "get_description"
        await query.edit_message_text(md2("Бренд выбран. Шаг 4: Введите общее описание товара."), parse_mode="MarkdownV2")
        return 
    else:
        await query.answer("Ошибка формата бренда.", show_alert=True)
        return

async def get_new_brand_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "get_new_brand_name"
    brand_id = await create_new_entity(update, context, 'brands', update.message.text)
    context.user_data['new_product_brand_id'] = brand_id
    msg = get_effective_message(update)
    if msg:
        await msg.reply_text(md2("Бренд создан/выбран. Шаг 4: Введите общее описание товара."), parse_mode="MarkdownV2")
    context.user_data["state"] = "get_description"

async def get_description(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("DEBUG user_data before get_description:", context.user_data)
    context.user_data["state"] = "get_description"
    data = context.user_data
    await execute(
        "INSERT INTO products (name, description, category_id, sub_category_id, brand_id) VALUES (?, ?, ?, ?, ?)",
        (data['new_product_name'], update.message.text, data['new_product_category_id'], data['new_product_sub_category_id'], data['new_product_brand_id'])
    )
    product_row = await fetchone("SELECT id FROM products WHERE name = ? ORDER BY id DESC LIMIT 1", (data['new_product_name'],))
    context.user_data['current_product_id'] = product_row['id']
    msg = get_effective_message(update)
    if msg:
        await msg.reply_text(md2(f"✅ Основная карточка товара '{data['new_product_name']}' создана.\n\nТеперь добавим первый вариант."), parse_mode="MarkdownV2")
    context.user_data["state"] = "choose_variant_size"
    await ask_for_variant_size(update, context)

# --- Варианты товара ---
async def ask_for_variant_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "choose_variant_size"
    sizes = await fetchall("SELECT * FROM sizes")
    print("ask_for_variant_size sizes:", sizes, flush=True)
    keyboard = [[InlineKeyboardButton(s['name'], callback_data=f"add_size_{s['id']}")] for s in sizes]
    keyboard.append([InlineKeyboardButton("➕ Создать новый размер", callback_data="add_size_new")])
    msg = md2("Добавление варианта. Шаг 1: Выберите размер:")
    if getattr(update, 'callback_query', None):
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    else:
        msg_obj = get_effective_message(update)
        if msg_obj:
            await msg_obj.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    return 

async def select_variant_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "choose_variant_size"
    print("select_variant_size called", flush=True)
    query = update.callback_query
    await query.answer()
    print("callback_query data:", query.data, flush=True)
    if query.data == "add_size_new":
        context.user_data["state"] = "get_new_size_name"
        await query.edit_message_text(md2("Введите новое значение размера:"), parse_mode="MarkdownV2")
        return
    parts = query.data.split('_')
    if len(parts) == 3 and parts[2].isdigit():
        context.user_data['current_variant_size_id'] = int(parts[2])
        context.user_data["state"] = "choose_variant_color"
        await ask_for_variant_color(update, context)
        return
    else:
        await query.answer("Ошибка формата размера.", show_alert=True)
        return

async def get_new_size_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "get_new_size_name"
    size_id = await create_new_entity(update, context, 'sizes', update.message.text)
    context.user_data['current_variant_size_id'] = size_id
    context.user_data["state"] = "choose_variant_color"
    await ask_for_variant_color(update, context)

async def ask_for_variant_color(update, context):
    context.user_data["state"] = "choose_variant_color"
    colors = await fetchall("SELECT * FROM colors")
    keyboard = [[InlineKeyboardButton(c['name'], callback_data=f"add_color_{c['id']}")] for c in colors]
    keyboard.append([InlineKeyboardButton("➕ Создать новый цвет", callback_data="add_color_new")])
    msg = md2("Шаг 2: Выберите цвет:")
    if getattr(update, 'callback_query', None):
        await update.callback_query.edit_message_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    else:
        msg_obj = get_effective_message(update)
        if msg_obj:
            await msg_obj.reply_text(msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    return

async def select_variant_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "choose_variant_color"
    query = update.callback_query
    await query.answer()
    if query.data == "add_color_new":
        context.user_data["state"] = "get_new_color_name"
        await query.edit_message_text(md2("Введите название нового цвета:"), parse_mode="MarkdownV2")
        return
    parts = query.data.split('_')
    if len(parts) == 3 and parts[2].isdigit():
        context.user_data['current_variant_color_id'] = int(parts[2])
        context.user_data["state"] = "get_variant_price"  # <-- ВАЖНО!
        await query.edit_message_text(md2("Шаг 3: Укажите цену для этого варианта (число):"), parse_mode="MarkdownV2")
        return
    else:
        await query.answer("Ошибка формата цвета.", show_alert=True)
        return 

async def get_new_color_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "get_new_color_name"
    color_id = await create_new_entity(update, context, 'colors', update.message.text)
    context.user_data['current_variant_color_id'] = color_id
    msg = get_effective_message(update)
    if msg:
        await msg.reply_text(md2("Цвет создан/выбран. Шаг 3: Укажите цену."), parse_mode="MarkdownV2")
    context.user_data["state"] = "get_variant_price"
    

async def get_variant_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "get_variant_price"
    try:
        context.user_data['current_variant_price'] = float(update.message.text)
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text(md2("Цена установлена. Шаг 4: Укажите количество на складе:"), parse_mode="MarkdownV2")
        
        context.user_data["state"] = "get_variant_quantity"
    except ValueError:
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text(md2("Неверный формат. Введите цену как число."), parse_mode="MarkdownV2")
        

async def get_variant_quantity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "get_variant_quantity"
    try:
        
        context.user_data['current_variant_quantity'] = int(update.message.text)
       
        # Сразу создаём вариант в БД и переводим на этап фото:
        return await get_variant_photo(update, context)
    except ValueError:
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text(md2("Неверный формат. Введите количество как целое число."), parse_mode="MarkdownV2")
        

async def get_variant_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "add_variant_photo"
    # Эта функция вызывается только после ввода количества!
    data = context.user_data
    print("DEBUG variant data:",
      data['current_product_id'],
      data['current_variant_size_id'],
      data['current_variant_color_id'],
      data['current_variant_price'],
      data['current_variant_quantity'])
    try:
        await execute(
            "INSERT INTO product_variants (product_id, size_id, color_id, price, quantity, photo_id) VALUES (?, ?, ?, ?, ?, NULL)",
            (data['current_product_id'], data['current_variant_size_id'], data['current_variant_color_id'], data['current_variant_price'], data['current_variant_quantity'])
        )
        variant_row = await fetchone(
            "SELECT id FROM product_variants WHERE product_id=? AND size_id=? AND color_id=? ORDER BY id DESC LIMIT 1",
            (data['current_product_id'], data['current_variant_size_id'], data['current_variant_color_id'])
        )
        context.user_data['admin_variant_id'] = variant_row['id']
        context.user_data['media_order'] = 0
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text("Теперь отправьте от 1 до 5 фото или видео для этого варианта. Когда закончите — напишите /done.")
        context.user_data["state"] = "add_variant_media"
        
    except Exception as e:
        print(f"Ошибка при добавлении варианта в БД: {e}")
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text(md2("Ошибка при добавлении варианта в базу данных."), parse_mode="MarkdownV2")

        
async def add_media(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "add_variant_media"
    variant_id = context.user_data.get('admin_variant_id')
    order = context.user_data.get('media_order', 0)
    media_count = await fetchone("SELECT COUNT(*) as cnt FROM product_media WHERE variant_id = ?", (variant_id,))
    if media_count and media_count['cnt'] >= 5:
        msg = get_effective_message(update)
        await msg.reply_text("Максимум 5 фото/видео для одного варианта. Нажмите /done.")
        context.user_data["state"] = "finish_variant_media"
        return await finish_media(update, context)
    if update.message.photo:
        file_id = update.message.photo[-1].file_id
        await execute(
            "INSERT INTO product_media (variant_id, file_id, is_video, \"order\") VALUES (?, ?, 0, ?)",
            (variant_id, file_id, order)
        )
        context.user_data['media_order'] = order + 1
        # --- Исправление: обновляем photo_id, если это первое медиа ---
        if order == 0:
            await execute(
                "UPDATE product_variants SET photo_id = ? WHERE id = ?",
                (file_id, variant_id)
            )
            msg = get_effective_message(update)
            if msg:
                await msg.reply_text("Фото добавлено. Отправьте ещё или напишите /done.")
    elif update.message.video:
        file_id = update.message.video.file_id
        await execute(
            "INSERT INTO product_media (variant_id, file_id, is_video, \"order\") VALUES (?, ?, 1, ?)",
            (variant_id, file_id, order)
        )
        context.user_data['media_order'] = order + 1
        # --- Исправление: обновляем photo_id, если это первое медиа ---
        if order == 0:
            await execute(
                "UPDATE product_variants SET photo_id = ? WHERE id = ?",
                (file_id, variant_id)
            )
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text("Видео добавлено. Отправьте ещё или напишите /done.")
    else:
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text("Пожалуйста, отправьте фото или видео. Максимум 5 медиа для одного варианта.")
    context.user_data["state"] = "add_variant_media"
    

async def finish_media(update: Update, context: ContextTypes.DEFAULT_TYPE):

    print("[DEBUG] user_data keys before finish_media:", list(context.user_data.keys()))
    print("[DEBUG] /done triggered — state:", context.user_data.get("state"))


    if context.user_data.get("product_addition_finished"):
        await update.message.reply_text("✅ Все уже завершено. Спасибо!")
        return


    if context.user_data.get("state") != "add_variant_media":
        await update.message.reply_text("⚠️ Команда /done доступна только во время загрузки фото/видео для варианта.")
        return
    context.user_data["state"] = "finish_variant_media"
    # Если идет добавление варианта в add_product_handler
    if context.user_data.get("current_product_id") and context.user_data.get("admin_variant_id"):
        context.user_data.pop('media_order', None)
        context.user_data.pop('admin_variant_id', None)
        keyboard = [
            [InlineKeyboardButton("➕ Да, добавить еще", callback_data="add_more_variants")],
            [InlineKeyboardButton("✅ Нет, завершить", callback_data="finish_add_product")]
        ]
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text(
                md2("✅ Вариант успешно добавлен. Хотите добавить еще один?"),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2"
            )
        context.user_data["state"] = "ask_add_more_variants"
        return 
    # Если это режим редактирования варианта (edit_product)
    elif context.user_data.get("product_to_edit_id") and context.user_data.get("variant_to_edit_id"):
        context.user_data.pop('media_order', None)
        context.user_data.pop('admin_variant_id', None)
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text(md2("✅ Фото/видео для варианта успешно добавлены."), parse_mode="MarkdownV2")
            context.user_data["state"] = "edit_menu"
       
        await show_edit_menu(update, context)
        return
    # Если это отдельный add_media_conv (например, через /addmedia)
    else:
        context.user_data.pop('media_order', None)
        context.user_data.pop('admin_variant_id', None)
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text(md2("✅ Фото/видео успешно добавлены."), parse_mode="MarkdownV2")
        context.user_data["state"] = None
        return
        
async def add_product_media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    if state == "add_variant_media":
        return await add_media(update, context)
    else:
        # Игнорируем, если не в состоянии ожидания медиа
        return

async def handle_done_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    return await finish_media(update, context)


async def ask_add_more_variants(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["state"] = "ask_add_more_variants"
    query = update.callback_query
    await query.answer()
    if query.data == 'add_more_variants':
        context.user_data["state"] = "choose_variant_size"
        # Вместо удаления сообщения просто редактируем его, чтобы убрать кнопки
        await query.edit_message_text(
            md2("Добавление нового варианта..."),
            parse_mode="MarkdownV2",
            reply_markup=None
        )
        await ask_for_variant_size(update, context)
    elif query.data == 'finish_add_product':
        await query.edit_message_text(
            md2("✅ Отлично! Все варианты для товара сохранены."),
            parse_mode="MarkdownV2",
            reply_markup=None
        )
        # Просто ставим флаг завершения — НЕ очищаем пока user_data
        context.user_data["product_addition_finished"] = True

        
    else:
        await query.edit_message_text(
            md2("Неизвестное действие."),
            parse_mode="MarkdownV2",
            reply_markup=None
        )
        
        
    


# === Часть 3: Редактирование/удаление товаров и вариантов, отчёты, подтверждение заказов ===

# --- Редактирование и удаление товаров/вариантов ---
async def start_edit_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = get_effective_message(update)
    if not is_admin(update.effective_user.id):
        if msg:
            await msg.reply_text(md2("Нет доступа."), parse_mode="MarkdownV2")
        return ConversationHandler.END
    product_id = context.user_data.get('product_to_edit_id')
    if not product_id:
        if msg:
            await msg.reply_text("ID товара не определён. Повторите попытку через меню.", parse_mode="MarkdownV2")
        return ConversationHandler.END
    variant_photo = await fetchone("SELECT photo_id FROM product_variants WHERE product_id = ? AND photo_id IS NOT NULL LIMIT 1", (product_id,))
    if variant_photo:
        msg = get_effective_message(update)
        if msg:
            sent = await msg.reply_photo(photo=variant_photo['photo_id'])
            context.user_data['edit_photo_message_id'] = sent.message_id
    await show_edit_menu(update, context)
    return AWAIT_EDIT_ACTION
    

async def show_edit_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    product_id = context.user_data.get('product_to_edit_id')
    if not product_id:
        context.user_data.clear()
        return ConversationHandler.END
    product = await fetchone("SELECT * FROM products WHERE id = ?", (product_id,))
    variants = await fetchall("""
        SELECT pv.id, pv.price, pv.quantity, s.name as size_name, c.name as color_name
        FROM product_variants pv
        LEFT JOIN sizes s ON pv.size_id = s.id
        LEFT JOIN colors c ON pv.color_id = c.id
        WHERE pv.product_id = ?
    """, (product_id,))
    if not product:
        await update.effective_message.reply_text(md2(f"Товар с ID `{product_id}` не найден."), parse_mode="MarkdownV2")
        context.user_data.clear()
        return ConversationHandler.END
    safe_name = md2(product['name'])
    message_text = f"⚙️ Редактирование *{safe_name}* \\(ID: {md2(product_id)}\\)\n\n{md2('Выберите действие:')}"
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
    if getattr(update, 'callback_query', None):
        query = update.callback_query
        await query.answer()
        await query.edit_message_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    else:
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text(message_text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    

async def handle_edit_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    if data.startswith("delete_variant_"):
        context.user_data['variant_to_delete'] = int(data.split('_')[2])
        keyboard = [
            [InlineKeyboardButton("✅ Да, удалить вариант", callback_data="confirm_delete_variant"),
             InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete")]
        ]
        await query.edit_message_text(md2("Вы уверены?"), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
        return CONFIRM_DELETE_VARIANT
    elif data.startswith("delete_product_full_"):
        keyboard = [
            [InlineKeyboardButton("✅ Да, удалить ВСЁ", callback_data="confirm_delete_full"),
             InlineKeyboardButton("❌ Отмена", callback_data="cancel_delete")]
        ]
        await query.edit_message_text(md2("Вы уверены, что хотите удалить товар и ВСЕ его варианты?"), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
        return CONFIRM_DELETE_FULL_PRODUCT
    elif data.startswith("add_variant_to_"):
        context.user_data['current_product_id'] = int(data.split('_')[3])
        await query.edit_message_text(md2("Перехожу в режим добавления нового варианта..."), parse_mode="MarkdownV2")
        await ask_for_variant_size(update, context)
        return SELECT_VARIANT_SIZE
    elif data.startswith("edit_variant_menu_"):
        context.user_data['variant_to_edit_id'] = int(data.split('_')[3])
        keyboard = [
            [InlineKeyboardButton("Цену", callback_data=f"edit_field_price")],
            [InlineKeyboardButton("Количество", callback_data=f"edit_field_quantity")],
            [InlineKeyboardButton("Фото", callback_data=f"edit_field_photo")],
            [InlineKeyboardButton("⬅️ Назад к списку вариантов", callback_data="back_to_edit_menu_main")]
        ]
        await query.edit_message_text(md2("Что изменить в этом варианте?"), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
        return SELECT_VARIANT_FIELD
    elif data == "back_to_edit_menu_main":
        await show_edit_menu(update, context)
        return AWAIT_EDIT_ACTION
    elif data == "edit_cancel":
    # Удаляем фото, если message_id сохранён
        msg_id = context.user_data.get('edit_photo_message_id')
        if msg_id:
            try:
                await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=msg_id)
            except Exception:
                pass  # если сообщение уже удалено или слишком старое
            context.user_data.pop('edit_photo_message_id', None)
        context.user_data.clear()
        await query.edit_message_text(md2("Редактирование завершено."), parse_mode="MarkdownV2")
        return ConversationHandler.END
    else:
        await query.edit_message_text(md2("Эта функция пока в разработке."), parse_mode="MarkdownV2")
        await show_edit_menu(update, context)
        return AWAIT_EDIT_ACTION

async def confirm_variant_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel_delete":
        return await show_edit_menu(update, context)
    variant_id = context.user_data.get('variant_to_delete')
    await execute("DELETE FROM product_variants WHERE id = ?", (variant_id,))
    await query.edit_message_text(md2("✅ Вариант удален. Обновляю меню..."), parse_mode="MarkdownV2")
    await show_edit_menu(update, context)
    return AWAIT_EDIT_ACTION

async def confirm_full_product_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "cancel_delete":
        return await show_edit_menu(update, context)
    product_id = context.user_data.get('product_to_edit_id')
    await execute("DELETE FROM product_variants WHERE product_id = ?", (product_id,))
    await execute("DELETE FROM products WHERE id = ?", (product_id,))
    await query.edit_message_text(md2(f"✅ Товар с ID {product_id} и все его варианты были полностью удалены."), parse_mode="MarkdownV2")
    context.user_data.clear()
    return ConversationHandler.END

async def select_variant_field_to_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    field_to_edit = query.data.split('_')[2]
    context.user_data['field_to_edit'] = field_to_edit
    if field_to_edit == "photo":
        context.user_data['admin_variant_id'] = context.user_data['variant_to_edit_id']
        context.user_data['media_order'] = 0
        await query.edit_message_text("Пришлите новые фото или видео для этого варианта. Когда закончите — напишите /done.")
        return GET_VARIANT_PHOTO
    prompt = md2(f"Введите новое значение для поля '{field_to_edit}':")
    keyboard = [[InlineKeyboardButton("⬅️ Назад к списку вариантов", callback_data="back_to_edit_menu_main")]]
    await query.edit_message_text(prompt, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
    return GET_NEW_VARIANT_VALUE

async def get_new_variant_value(update: Update, context: ContextTypes.DEFAULT_TYPE):
    field = context.user_data.get('field_to_edit')
    variant_id = context.user_data.get('variant_to_edit_id')
    if update.message and update.message.text and update.message.text == "⬅️ Назад к списку вариантов":
        await show_edit_menu(update, context)
        return AWAIT_EDIT_ACTION
    new_value = None
    if field == 'photo':
        if update.message.photo:
            new_value = update.message.photo[-1].file_id
            field = 'photo_id'
        else:
            keyboard = [[InlineKeyboardButton("⬅️ Назад к списку вариантов", callback_data="back_to_edit_menu_main")]]
            msg = get_effective_message(update)
            if msg:
                await msg.reply_text(
                    md2("Пожалуйста, отправьте фото."),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="MarkdownV2"
                )
            return GET_NEW_VARIANT_VALUE
    else:
        new_value_text = update.message.text
        if new_value_text == "⬅️ Назад к списку вариантов":
            await show_edit_menu(update, context)
            return AWAIT_EDIT_ACTION
        try:
            new_value = float(new_value_text) if field == 'price' else int(new_value_text)
        except ValueError:
            keyboard = [[InlineKeyboardButton("⬅️ Назад к списку вариантов", callback_data="back_to_edit_menu_main")]]
            msg = get_effective_message(update)
            if msg:
                # Если не удалось преобразовать значение, сообщаем об ошибке
                await msg.reply_text(
                    md2("Неверный формат. Введите число."),
                    reply_markup=InlineKeyboardMarkup(keyboard),
                    parse_mode="MarkdownV2"
                )
            return GET_NEW_VARIANT_VALUE
    try:
        await execute(f"UPDATE product_variants SET {field} = ? WHERE id = ?", (new_value, variant_id))
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text(md2(f"✅ Поле '{field}' для варианта успешно обновлено."), parse_mode="MarkdownV2")
    except Exception as e:
        print(f"Ошибка при обновлении варианта: {e}")
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text(md2("Ошибка при обновлении базы данных."), parse_mode="MarkdownV2")
    await show_edit_menu(update, context)
    return AWAIT_EDIT_ACTION



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
        f"📊 *Отчет за 7 дней:*\n\n"
        f"• *Заказов:* {md2(orders_count)}\n"
        f"• *Выручка:* {md2(int(total_revenue))} ₸\n"
        f"• *Хит продаж:* {md2(most_popular_product_text)}"
    )
    msg = get_effective_message(update)
    if msg:
        await msg.reply_text(report_message, parse_mode="MarkdownV2")
    

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
        await query.edit_message_text(md2("Ошибка: некорректный формат callback data."), parse_mode="MarkdownV2")
        return
    action, order_id_str = query.data.split('_')[1], query.data.split('_')[2]
    order_id = int(order_id_str)
    order = await fetchone("SELECT * FROM orders WHERE id = ?", (order_id,))
    if order["status"] == "cancelled_by_client":
        await query.edit_message_text(
            md2(f"⚠️ Невозможно изменить статус — заказ №{order_id} отменён клиентом."),
            parse_mode="MarkdownV2"
        )
        return

    if not order:
        await query.edit_message_text(md2("Заказ не найден."), parse_mode="MarkdownV2")
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
                text="*" + md2(f"✅ Ваш заказ №{order_id} подтвержден! \n\nВы можете отслеживать заказ :\nГлавное меню ➡ История заказов ➡ 🟡Активные") + "*",

                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(kb)
            )

            status_buttons = [
                [InlineKeyboardButton("🔄 Готовится к доставке", callback_data=f"status_preparing_{order_id}")],
                [InlineKeyboardButton("🚚 Отправлен", callback_data=f"status_shipped_{order_id}")],
                [InlineKeyboardButton("📦 Доставлен", callback_data=f"status_delivered_{order_id}")],
                [InlineKeyboardButton("❌ Отклонить заказ", callback_data=f"admin_reject_after_confirm_{order_id}")]
            ]

            await query.edit_message_text(
                md2(f"Заказ №{order_id} подтверждён.\n\nВыберите следующий статус:"),
                parse_mode="MarkdownV2",
                reply_markup=InlineKeyboardMarkup(status_buttons)
            )
        except Exception:
            await query.edit_message_text(md2("Ошибка при подтверждении заказа."), parse_mode="MarkdownV2")




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
        text=md2("📋 Выберите, какие заказы хотите посмотреть:"),
        parse_mode="MarkdownV2",
        reply_markup=filter_keyboard
    )


async def order_filter_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await asyncio.sleep(0.5)

    if not context.user_data.get("order_history_started"):
        await query.edit_message_text(md2("Сначала откройте историю заказов."), parse_mode="MarkdownV2")
        return

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
            md2("❗ У вас пока нет заказов по выбранному фильтру."),
            parse_mode="MarkdownV2",
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
    order_id = md2(str(order["id"]))
    raw_status = order["status"]
    status = md2(status_names.get(raw_status, raw_status))
    total = md2(str(order["total_price"]))
    cart = json.loads(order["cart"])
    cart_text = "\n".join([
        f"• {md2(item['name'])} \\(x{md2(item['quantity'])}\\)" for item in cart.values()
    ])
    msg = (
        f"🧾 *Чек №{order_id}*\n"
        f"*Клиент:* {md2(order['user_name'])}\n"
        f"*Тел:* {md2(order['user_phone'])}\n"
        f"*Адрес:* {md2(order['user_address'])}\n"
        f"*Сумма:* {total} ₸\n"
        f"*Статус:* `{status}`\n"
        f"*Состав:*\n{cart_text}\n"
        f"*Дата:* {md2(order['created_at'])}"
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
        parse_mode="MarkdownV2",
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
        text=md2("❗ Вы уверены, что хотите отменить этот заказ?"),
        parse_mode="MarkdownV2",
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
        text=md2("📋 Выберите, какие заказы хотите посмотреть:"),
        parse_mode="MarkdownV2",
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

async def admin_menu_entry(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update.effective_user.id):
        await update.message.reply_text(md2("Нет доступа."), parse_mode="MarkdownV2")
        return ConversationHandler.END
    await update.message.reply_text(
        "⚙️ <b>Админ-панель. Выберите действие:</b>",
        reply_markup=admin_menu_keyboard(),
        parse_mode="HTML"
    )
    return ADMIN_MENU_AWAIT


async def admin_menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data

    if data == "admin_add_new_product":
        await query.answer("Начинаю добавление нового товара...")
        context.user_data.clear()
        
        
        
        return await start_add_product(update, context)  # <----- обязательно!
    
    elif data == "admin_manage_categories":
        await query.edit_message_text("Управление категориями:")
        await manage_categories(update, context)
        return ConversationHandler.END  # <----- обязательно!

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

    elif data == "admin_edit_product":
        await query.edit_message_text("Введите ID товара для редактирования:")
        return ADMIN_EDIT_AWAIT_ID

    else:
        await query.edit_message_text("Неизвестная команда.")
        return ConversationHandler.END

async def nazad_to_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    await query.answer()
    if data == "admin_menu":
        await query.edit_message_text(
            "⚙️ <b>Админ-панель. Выберите действие:</b>",
            reply_markup=admin_menu_keyboard(),
            parse_mode="HTML"
        )
        return ADMIN_MENU_AWAIT

async def admin_edit_await_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    product_id = update.message.text.strip()
    msg = get_effective_message(update)
    if not product_id.isdigit():
        msg = get_effective_message(update)
        if msg:
            await msg.reply_text("Некорректный ID товара, попробуйте ещё раз или /cancel для отмены.")
        return ADMIN_EDIT_AWAIT_ID
    context.user_data['product_to_edit_id'] = int(product_id)
    
    await update.message.reply_text(
    "ID товара сохранён. Нажмите кнопку ниже для перехода к редактированию.",
    reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("✏️ Редактировать товар", callback_data="admin_edit_product")]])
)
    return ConversationHandler.END

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



async def add_product_text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    user_id = update.effective_user.id
    message_text = update.message.text

    print(f"[DEBUG] User {user_id} entered text: {message_text}")
    print(f"[DEBUG] Current user_data state: {state}")

    if state == "get_product_name":
        return await get_name(update, context)

    elif state == "get_new_category_name":
        return await get_new_category_name(update, context)

    elif state == "get_new_subcategory_name":
        return await get_new_subcategory_name(update, context)

    elif state == "get_new_brand_name":
        return await get_new_brand_name(update, context)

    elif state == "get_description":
        return await get_description(update, context)

    elif state == "get_new_size_name":
        return await get_new_size_name(update, context)

    elif state == "get_new_color_name":
        return await get_new_color_name(update, context)

    elif state == "get_variant_price":
        return await get_variant_price(update, context)

    elif state == "get_variant_quantity":
        return await get_variant_quantity(update, context)

    



async def add_product_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    state = context.user_data.get("state")
    data = update.callback_query.data
    await update.callback_query.answer()

    if data.startswith("add_cat_"):
        return await get_category(update, context)

    elif data.startswith("add_subcat_"):
        return await get_subcategory(update, context)

    elif data.startswith("add_brand_"):
        return await get_brand(update, context)

    elif data.startswith("add_size_"):
        return await select_variant_size(update, context)

    elif data.startswith("add_color_"):
        return await select_variant_color(update, context)

    elif data == "add_more_variants" or data == "finish_add_product":
        return await ask_add_more_variants(update, context)

    else:
        await update.callback_query.answer("⚠️ Неизвестная команда", show_alert=True)



async def add_product_media_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("[DEBUG] add_product_media_handler triggered — state:", context.user_data.get("state"))
    state = context.user_data.get("state")
    if state == "add_variant_media":
        return await add_media(update, context)
    else:
        # Игнорируем, если не в состоянии ожидания медиа
        return






# === ConversationHandlers ===

admin_menu_convhandler = ConversationHandler(
    entry_points=[CommandHandler("admin", admin_menu_entry)],
    states={
        ADMIN_MENU_AWAIT: [
            CallbackQueryHandler(admin_menu_callback, pattern=r"^admin_"),
        ],
        ADMIN_EDIT_AWAIT_ID: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_edit_await_id),
        ],
        ADMIN_SUBCAT_AWAIT_ID: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, admin_subcat_await_id),
        ],
    },
    fallbacks=[
        MessageHandler(filters.COMMAND, cancel_dialog),
        CallbackQueryHandler(cancel_dialog, pattern="^cancel_dialog$")  # на всякий случай
    ],
    per_user=True,
    per_chat=True,
    per_message=True
)

edit_product_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_edit_product, pattern=r"^admin_edit_product$")],
    states={
        AWAIT_EDIT_ACTION: [
            CallbackQueryHandler(handle_edit_action),
        ],
        CONFIRM_DELETE_VARIANT: [
            CallbackQueryHandler(confirm_variant_delete, pattern=r"^confirm_delete_variant$|^cancel_delete$"),
        ],
        CONFIRM_DELETE_FULL_PRODUCT: [
            CallbackQueryHandler(confirm_full_product_delete, pattern=r"^confirm_delete_full$|^cancel_delete$"),
        ],
        SELECT_VARIANT_FIELD: [
            CallbackQueryHandler(select_variant_field_to_edit, pattern=r"^edit_field_"),
            CallbackQueryHandler(handle_edit_action),  # fallback на всякий
        ],
        GET_NEW_VARIANT_VALUE: [
            MessageHandler(filters.TEXT | filters.PHOTO, get_new_variant_value),
            CallbackQueryHandler(handle_edit_action)
        ],
        SELECT_VARIANT_SIZE: [
            CallbackQueryHandler(select_variant_size, pattern=r"^add_size_"),
        ],
        GET_NEW_SIZE_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_size_name),
        ],
        SELECT_VARIANT_COLOR: [
            CallbackQueryHandler(select_variant_color, pattern=r"^add_color_"),
        ],
        GET_NEW_COLOR_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_new_color_name),
        ],
        GET_VARIANT_PRICE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_variant_price),
        ],
        GET_VARIANT_QUANTITY: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, get_variant_quantity),
        ],
        GET_VARIANT_PHOTO: [
            MessageHandler(filters.PHOTO | filters.VIDEO, add_media),
            MessageHandler(filters.COMMAND, finish_media)
        ],
        ASK_ADD_MORE_VARIANTS: [
            CallbackQueryHandler(ask_add_more_variants, pattern=r"^add_more_variants$|^finish_add_product$"),
        ],
    },
    fallbacks=[
        MessageHandler(filters.COMMAND, cancel_dialog),
        CallbackQueryHandler(cancel_dialog, pattern=r"^cancel_dialog$")  # про запас
    ],
    per_user=True,
    per_chat=True,
    per_message=True
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
    per_chat=True,
    per_message=True
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
    per_message=True
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
nazad_to_admin_menu_handler = CallbackQueryHandler(nazad_to_admin_menu, pattern=r"^admin_menu$")


