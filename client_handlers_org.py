import json
import re
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton,
    InputMediaPhoto, CallbackQuery , InlineQueryResultPhoto , InputTextMessageContent , InlineQueryResultArticle , InputMediaVideo 
)
import asyncio
from telegram.ext import (
    CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters , InlineQueryHandler
)
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown
from configs import ADMIN_IDS, ITEMS_PER_PAGE
from db import fetchall, fetchone, execute
from datetime import datetime
import time
ASK_NAME, ASK_ADDRESS, ASK_PHONE = range(3)
import telegram.error
import logging

def md2(text):
    """
    Экспортирует спецсимволы для MarkdownV2, но не трогает обычный текст.
    """
    if text is None:
        return ''
    # Список спецсимволов для MarkdownV2
    chars = r"_*[]()~`>#+-=|{}.!"
    return re.sub(f'([{re.escape(chars)}])', r'\\\1', str(text))




async def safe_edit_or_send(
    source, 
    text, 
    context, 
    reply_markup=None, 
    parse_mode="MarkdownV2"
):
    """
    Универсальная функция для отправки текста с инлайн-кнопками.
    Работает и с CallbackQuery, и с Message.
    1. Пробует отредактировать сообщение (edit_text/edit_caption).
    2. Если не удалось — просто отправляет новое сообщение.
    """
    try:
        # Если это callback_query (есть .message)
        if getattr(source, "message", None):
            msg = source.message
            # Если это фото/видео с caption
            if getattr(msg, "photo", None) or getattr(msg, "video", None):
                await msg.edit_caption(caption=text, reply_markup=reply_markup, parse_mode=parse_mode)
            else:
                await msg.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        # Если это обычное сообщение (например, MessageHandler)
        elif getattr(source, "chat", None):
            await source.edit_text(text, reply_markup=reply_markup, parse_mode=parse_mode)
        else:
            raise Exception("No message to edit")
    except Exception:
        # Если редактирование не удалось — просто отправим новое
        chat_id = None
        if getattr(source, "message", None) and getattr(source.message, "chat", None):
            chat_id = source.message.chat.id
        elif getattr(source, "chat", None):
            chat_id = source.chat.id
        elif getattr(source, "from_user", None):
            chat_id = source.from_user.id
        if chat_id:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )

async def safe_delete_and_send(query, text, context, reply_markup=None, parse_mode="MarkdownV2"):
    try:
        await query.message.delete()
    except Exception:
        pass
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text=text,
        reply_markup=reply_markup,
        parse_mode=parse_mode
    )
# ======= КАТАЛОГ, РАЗДЕЛЫ, БРЕНДЫ =======

async def show_catalog(update: Update, context: ContextTypes.DEFAULT_TYPE):
    categories = await fetchall("SELECT * FROM categories")
    keyboard = [[InlineKeyboardButton(md2(cat['name']), callback_data=f"cat_{cat['id']}")] for cat in categories]
    # Кнопка "Назад в главное меню"
    keyboard.append([InlineKeyboardButton(md2("◀ Главное меню"), callback_data="back_to_main_menu")])

    text = md2("Выберите категорию:")

    # Универсально: поддерживает и CallbackQuery, и Message
    source = update.callback_query if update.callback_query else update.message
    if update.callback_query:
        await update.callback_query.answer()
    await safe_edit_or_send(
        source, text, context, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2"
    )

async def show_subcategories(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    category_id = int(query.data.split('_')[1])
    context.user_data['current_category_id'] = category_id
    sub_categories = await fetchall("SELECT * FROM sub_categories WHERE category_id = ?", (category_id,))
    keyboard = [[InlineKeyboardButton(md2(scat['name']), callback_data=f"subcat_{scat['id']}")] for scat in sub_categories]
    keyboard.append([InlineKeyboardButton(md2("◀️ Назад к категориям"), callback_data="back_to_main_cat")])
    try:
        if query.message.photo:
            await query.message.delete()
            await query.message.chat.send_message(
                md2("Выберите раздел:"), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2"
            )
            return
    except Exception:
        pass
    await query.message.edit_text(md2("Выберите раздел:"), reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")


async def show_brand_or_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split('_')
    # Проверяем, что id действительно число (универсально для любого callback_data)
    if len(parts) >= 2 and parts[1].isdigit():
        subcat_id = int(parts[1])
    elif parts[-1].isdigit():
        subcat_id = int(parts[-1])
    else:
        await query.edit_message_text("Ошибка: не удалось определить id раздела.")
        return
    context.user_data['current_subcat_id'] = subcat_id
    brands = await fetchall("""
        SELECT DISTINCT b.id, b.name
        FROM products p
        JOIN brands b ON p.brand_id = b.id
        WHERE p.sub_category_id = ?
    """, (subcat_id,))
    keyboard = [
        [InlineKeyboardButton(md2(b['name']), callback_data=f"brand_{subcat_id}_{b['id']}")] for b in brands
    ]
    keyboard.append([InlineKeyboardButton(md2("Показать все товары"), callback_data=f"showall_{subcat_id}_page_0")])
    keyboard.append([InlineKeyboardButton(md2("◀️ К разделам"), callback_data=f"cat_{context.user_data.get('current_category_id', 1)}")])
    try:
        if query.message.photo:
            await query.message.delete()
            await query.message.chat.send_message(
                md2("Выберите бренд или посмотрите все товары:"),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2"
            )
            return
    except Exception:
        pass
    await query.message.edit_text(
        md2("Выберите бренд или посмотрите все товары:"),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="MarkdownV2"
    )

async def back_to_brands(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    subcat_id = int(query.data.split('_')[1])
    context.user_data['current_subcat_id'] = subcat_id
    try:
        if query.message.photo:
            await query.message.delete()
    except Exception:
        pass
    brands = await fetchall("""
        SELECT DISTINCT b.id, b.name
        FROM products p
        JOIN brands b ON p.brand_id = b.id
        WHERE p.sub_category_id = ?
    """, (subcat_id,))
    keyboard = [
        [InlineKeyboardButton(md2(b['name']), callback_data=f"brand_{subcat_id}_{b['id']}")] for b in brands
    ]
    keyboard.append([InlineKeyboardButton(md2("Показать все товары"), callback_data=f"showall_{subcat_id}_page_0")])
    keyboard.append([InlineKeyboardButton(md2("◀️ К разделам"), callback_data=f"cat_{context.user_data.get('current_category_id', 1)}")])
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.message.chat.send_message(
        md2("Выберите бренд или посмотрите все товары:"),
        reply_markup=reply_markup,
        parse_mode="MarkdownV2"
    )

async def back_to_main_cat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    categories = await fetchall("SELECT * FROM categories")
    keyboard = [[InlineKeyboardButton(md2(cat['name']), callback_data=f"cat_{cat['id']}")] for cat in categories]
    keyboard.append([InlineKeyboardButton(md2("◀ Главное меню"), callback_data="back_to_main_menu")])
    try:
        if query.message.photo:
            await query.message.delete()
            await query.message.chat.send_message(
                md2("Выберите категорию:"),
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="MarkdownV2"
            )
            return
    except Exception:
        pass
    await query.message.edit_text(
        md2("Выберите категорию:"),
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="MarkdownV2"
    )



def generate_pagination_buttons(current_page, total_pages, prefix):
    buttons = []

    max_buttons = 4  # максимум числовых кнопок на экране
    current_block = current_page // max_buttons
    start_page = current_block * max_buttons
    end_page = min(start_page + max_buttons, total_pages)

    # ⏮ назад на предыдущий блок
    if start_page > 0:
        buttons.append(InlineKeyboardButton("⏮", callback_data=f"{prefix}{start_page - 1}"))

    # Числовые кнопки
    for i in range(start_page, end_page):
        if i == current_page:
            buttons.append(InlineKeyboardButton(f"{i + 1}", callback_data="noop"))
        else:
            buttons.append(InlineKeyboardButton(f"{i + 1}", callback_data=f"{prefix}{i}"))

    # ⏭ вперёд на следующий блок
    if end_page < total_pages:
        buttons.append(InlineKeyboardButton("⏭", callback_data=f"{prefix}{end_page}"))

    return buttons




async def noop_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()


async def show_product_slider(update: Update, context: ContextTypes.DEFAULT_TYPE, brand_id=None, subcat_id=None, all_mode=False):
    query = update.callback_query
    await query.answer()

    user_data = context.user_data
    subcat_id = subcat_id or user_data.get('current_subcat_id')
    brand_id = brand_id or user_data.get('current_brand_id') if not all_mode else None

    if not subcat_id:
        await safe_delete_and_send(query, md2("Ошибка: не определён раздел. Попробуйте заново."), context)
        return

    if 'current_category_id' not in user_data:
        result = await fetchone("SELECT category_id FROM sub_categories WHERE id = ?", (subcat_id,))
        if result:
            user_data['current_category_id'] = result['category_id']

    page = int(user_data.get('product_slider_page', 0))
    await asyncio.sleep(0.5)

    # Получение товаров
    if all_mode:
        products = await fetchall("""
            SELECT p.id, p.name, MIN(pv.price) as min_price, b.name as brand
            FROM products p
            JOIN product_variants pv ON p.id = pv.product_id
            JOIN brands b ON p.brand_id = b.id
            WHERE p.sub_category_id = ? AND pv.quantity > 0
            GROUP BY p.id
            ORDER BY min_price
        """, (subcat_id,))
    else:
        if not brand_id:
            await safe_delete_and_send(query, "Ошибка: не определён бренд.", context)
            return
        products = await fetchall("""
            SELECT p.id, p.name, MIN(pv.price) as min_price, b.name as brand
            FROM products p
            JOIN product_variants pv ON p.id = pv.product_id
            JOIN brands b ON p.brand_id = b.id
            WHERE p.sub_category_id = ? AND p.brand_id = ? AND pv.quantity > 0
            GROUP BY p.id
            ORDER BY min_price
        """, (subcat_id, brand_id))

    if not products:
        await safe_delete_and_send(query, md2("Нет товаров!"), context)
        return

    total = len(products)
    page = max(0, min(page, total - 1))
    user_data['product_slider_page'] = page
    user_data['all_mode'] = all_mode

    product = products[page]
    product_id = product['id']
    user_data['current_product_id'] = product_id

    # Установка недостающих данных
    if 'current_subcat_id' not in user_data or 'current_brand_id' not in user_data:
        info = await fetchone("SELECT sub_category_id, brand_id FROM products WHERE id = ?", (product_id,))
        if info:
            user_data['current_subcat_id'] = info['sub_category_id']
            user_data['current_brand_id'] = info['brand_id']
            result = await fetchone("SELECT category_id FROM sub_categories WHERE id = ?", (info['sub_category_id'],))
            if result:
                user_data['current_category_id'] = result['category_id']

    # Медиа
    media_row = await fetchone("""
        SELECT file_id, is_video FROM product_media
        WHERE variant_id = (SELECT id FROM product_variants WHERE product_id = ? LIMIT 1)
        ORDER BY "order" LIMIT 1
    """, (product_id,))
    file_id = media_row['file_id'] if media_row else None
    is_video = bool(media_row['is_video']) if media_row else False

    # Текст карточки
    caption = (
        f"*{md2(product['name'])}*\n"
        f"{md2('Бренд')}: {md2(product['brand'])}\n"
        f"{md2('Цена')}: {md2(product['min_price'])}₸\n"
        f"_{md2('Страница')} {md2(page + 1)}/{md2(total)}_"
    )

    
    prefix = f"{'all_' if all_mode else 'brand_'}slider_{subcat_id}_{brand_id or ''}_"
    page_buttons = generate_pagination_buttons(page, total, prefix)

    # Вторая строка — подробнее
    second_row = [
        InlineKeyboardButton(md2("📦 Подробнее"), callback_data=f"details_{product_id}")
    ]

    keyboard = [
        page_buttons,
        second_row,
        [InlineKeyboardButton(
            md2("◀ Назад к разделу") if all_mode else md2("◀ Назад к брендам"),
            callback_data=f"cat_{user_data['current_category_id']}" if all_mode else f"brands_{subcat_id}"
        )],
        [InlineKeyboardButton(md2("⏪ Категории"), callback_data="back_to_main_cat")],
        [InlineKeyboardButton(md2("🏚 Главное меню"), callback_data="back_to_main_menu")]
    ]


    chat_id = query.message.chat_id if query.message else update.effective_chat.id
    context.user_data['return_to_slider'] = {
    'product_slider_page': context.user_data.get('product_slider_page', 0),
    'all_mode': context.user_data.get('all_mode', True),
    'current_subcat_id': subcat_id,
    'current_brand_id': brand_id
}


    if not file_id:
        await context.bot.send_message(chat_id=chat_id, text=caption, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="MarkdownV2")
        return

    try:
        if is_video:
            await query.message.edit_media(
                media=InputMediaVideo(file_id, caption=caption, parse_mode="MarkdownV2"),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            if query.message.photo:
                await query.edit_message_media(
                    media=InputMediaPhoto(file_id, caption=caption, parse_mode="MarkdownV2"),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            else:
                await query.message.edit_caption(
                    caption=caption,
                    parse_mode="MarkdownV2",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
    except Exception:
        try:
            await query.message.delete()
        except:
            pass
        if is_video:
            await context.bot.send_video(chat_id=chat_id, video=file_id, caption=caption, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard))
        else:
            await context.bot.send_photo(chat_id=chat_id, photo=file_id, caption=caption, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard))

async def set_slider_context(context, product_id=None, subcat_id=None, brand_id=None):
    if product_id:
        product_info = await fetchone(
            "SELECT p.sub_category_id, p.brand_id, sc.category_id FROM products p JOIN sub_categories sc ON p.sub_category_id = sc.id WHERE p.id = ?",
            (product_id,)
        )
        if product_info:
            context.user_data['current_subcat_id'] = product_info['sub_category_id']
            context.user_data['current_brand_id'] = product_info['brand_id']
            context.user_data['current_category_id'] = product_info['category_id']

    if subcat_id and 'current_subcat_id' not in context.user_data:
        context.user_data['current_subcat_id'] = subcat_id
    if brand_id and 'current_brand_id' not in context.user_data:
        context.user_data['current_brand_id'] = brand_id

    # Подставь category_id если надо
    if 'current_category_id' not in context.user_data and 'current_subcat_id' in context.user_data:
        result = await fetchone("SELECT category_id FROM sub_categories WHERE id = ?", (context.user_data['current_subcat_id'],))
        if result:
            context.user_data['current_category_id'] = result['category_id']


async def handle_brand_slider(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split('_')
    subcat_id, brand_id, page = int(data[2]), int(data[3]), int(data[4])
    context.user_data['all_mode'] = False

    context.user_data['current_subcat_id'] = subcat_id
    context.user_data['current_brand_id'] = brand_id
    context.user_data['product_slider_page'] = page
    await show_product_slider(update, context, brand_id=brand_id, all_mode=False)

async def handle_all_slider(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split('_')
    subcat_id, page = int(data[2]), int(data[4])
    

    context.user_data['current_subcat_id'] = subcat_id
    context.user_data['product_slider_page'] = page
    await show_product_slider(update, context, all_mode=True)

async def start_brand_slider(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data.split('_')
    subcat_id, brand_id = int(data[1]), int(data[2])
    context.user_data['all_mode'] = False

    context.user_data['current_subcat_id'] = subcat_id
    context.user_data['current_brand_id'] = brand_id
    
    await show_product_slider(update, context, brand_id=brand_id, all_mode=False)

async def start_all_slider(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    subcat_id = int(query.data.split('_')[1])
    

    context.user_data['current_subcat_id'] = subcat_id
    
    await show_product_slider(update, context, all_mode=True)

# ...далее идут функции для деталей товара, корзины, оформления заказа и т.д...

from telegram import InputMediaPhoto

async def show_product_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = getattr(update, "callback_query", None)
    await query.answer() if query else None

    try:
        if query and query.data.startswith("details_"):
            parts = query.data.split('_')
            product_id = int(parts[1])
            if len(parts) == 4:
                context.user_data['current_subcat_id'] = int(parts[2])
                context.user_data['current_brand_id'] = int(parts[3])
        else:
            product_id = context.user_data.get("current_product_id")
    except Exception:
        product_id = context.user_data.get("current_product_id")

    if not product_id:
        await update.message.reply_text("❌ Не удалось определить товар.")
        return

    context.user_data['current_product_id'] = product_id

    # Получаем недостающие данные subcat/brand/category
    if 'current_subcat_id' not in context.user_data or 'current_brand_id' not in context.user_data:
        info = await fetchone("SELECT sub_category_id, brand_id FROM products WHERE id = ?", (product_id,))
        if info:
            context.user_data['current_subcat_id'] = info['sub_category_id']
            context.user_data['current_brand_id'] = info['brand_id']
            result = await fetchone("SELECT category_id FROM sub_categories WHERE id = ?", (info['sub_category_id'],))
            if result:
                context.user_data['current_category_id'] = result['category_id']

    if 'all_mode' not in context.user_data:
    # Если зашли из inline (нет истории), включаем all_mode
        context.user_data['all_mode'] = True
    else:
        context.user_data['all_mode'] = context.user_data.get('all_mode', False)

    
    # 🧠 Вычисляем product_slider_page если его ещё нет
    if 'product_slider_page' not in context.user_data or context.user_data['product_slider_page'] == 0:
        subcat_id = context.user_data.get('current_subcat_id')
        brand_id = context.user_data.get('current_brand_id')
        all_mode = context.user_data['all_mode']

        if subcat_id:
            if all_mode:
                product_list = await fetchall("""
                    SELECT p.id FROM products p
                    JOIN product_variants pv ON p.id = pv.product_id
                    WHERE p.sub_category_id = ? AND pv.quantity > 0
                    GROUP BY p.id
                    ORDER BY MIN(pv.price)
                """, (subcat_id,))
            else:
                product_list = await fetchall("""
                    SELECT p.id FROM products p
                    JOIN product_variants pv ON p.id = pv.product_id
                    WHERE p.sub_category_id = ? AND p.brand_id = ? AND pv.quantity > 0
                    GROUP BY p.id
                    ORDER BY MIN(pv.price)
                """, (subcat_id, brand_id))

            for i, item in enumerate(product_list):
                if item['id'] == product_id:
                    context.user_data['product_slider_page'] = i
                    break

        # 💾 Контекст слайдера
        subcat_id = context.user_data.get('current_subcat_id')
        brand_id = context.user_data.get('current_brand_id')
        all_mode = context.user_data.get('all_mode', False)
        slider_page = None

        if subcat_id:
            if all_mode:
                product_list = await fetchall("""
                    SELECT p.id FROM products p
                    JOIN product_variants pv ON p.id = pv.product_id
                    WHERE p.sub_category_id = ? AND pv.quantity > 0
                    GROUP BY p.id
                    ORDER BY MIN(pv.price)
                """, (subcat_id,))
            else:
                product_list = await fetchall("""
                    SELECT p.id FROM products p
                    JOIN product_variants pv ON p.id = pv.product_id
                    WHERE p.sub_category_id = ? AND p.brand_id = ? AND pv.quantity > 0
                    GROUP BY p.id
                    ORDER BY MIN(pv.price)
                """, (subcat_id, brand_id))

            for i, item in enumerate(product_list):
                if item['id'] == product_id:
                    slider_page = i
                    context.user_data['product_slider_page'] = i
                    break

            # 💾 Сохраняем return_to_slider только если нашли товар в списке
            if slider_page is not None:
                context.user_data['return_to_slider'] = {
                    'product_slider_page': slider_page,
                    'all_mode': all_mode,
                    'current_subcat_id': subcat_id,
                    'current_brand_id': brand_id
                }


    # Получаем товар
    product = await fetchone("SELECT * FROM products WHERE id = ?", (product_id,))
    if not product:
        await update.message.reply_text("❌ Товар не найден.")
        return

    # Достаём доступные цвета
    colors = await fetchall("""
        SELECT DISTINCT c.id, c.name
        FROM product_variants pv
        JOIN colors c ON pv.color_id = c.id
        WHERE pv.product_id = ? AND pv.quantity > 0
    """, (product_id,))

    if not colors:
        await safe_edit_or_send(update, md2("Нет доступных цветов для этого товара."), context=context)
        return

    text = f"<b>{product['name']}</b>\n\n<blockquote><i>{product['description']}</i></blockquote>\n\nВыберите цвет:"
    keyboard = [[InlineKeyboardButton(f"{c['name']}", callback_data=f"color_{product_id}_{c['id']}")] for c in colors]
    keyboard.append([InlineKeyboardButton("◀️ К товарам", callback_data="back_to_slider")])

    await safe_edit_or_send(query or update, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML, context=context)

async def get_color_media(product_id, color_id):
    # Получаем все variant_id для этого товара и цвета
    variant_ids = await fetchall(
        "SELECT id FROM product_variants WHERE product_id = ? AND color_id = ?",
        (product_id, color_id)
    )
    variant_ids = [str(row['id']) for row in variant_ids]
    if not variant_ids:
        return []
    ids_str = ",".join(variant_ids)
    query = f"SELECT file_id, is_video FROM product_media WHERE variant_id IN ({ids_str}) ORDER BY \"order\""
    return await fetchall(query)


async def choose_color(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    # --- Определяем параметры страницы ---
    parts = query.data.split('_')
    if parts[0] == "colorphoto":
        _, product_id, color_id, page = parts
        page = int(page)
    else:
        _, product_id, color_id = parts
        page = 0
    product_id = int(product_id)
    color_id = int(color_id)
    context.user_data['current_product_id'] = product_id
    context.user_data['chosen_color_id'] = color_id
    context.user_data['color_photo_page'] = page

    # --- Получаем все медиа (фото и видео) для этого цвета ---
    variant_ids = await fetchall(
        "SELECT id FROM product_variants WHERE product_id = ? AND color_id = ?",
        (product_id, color_id)
    )
    variant_ids = [str(row['id']) for row in variant_ids]
    if not variant_ids:
        media_rows = []
    else:
        ids_str = ",".join(variant_ids)
        media_rows = await fetchall(
            f"SELECT file_id, is_video FROM product_media WHERE variant_id IN ({ids_str}) ORDER BY \"order\""
        )
    total_media = len(media_rows)

    # --- Выбираем нужное медиа для страницы ---
    if total_media == 0:
        file_id = None
        is_video = False
    else:
        if page < 0:
            page = 0
        if page >= total_media:
            page = total_media - 1
        file_id = media_rows[page]['file_id']
        is_video = bool(media_rows[page]['is_video'])

    # --- Получаем размеры ---
    sizes = await fetchall("""
        SELECT DISTINCT s.id, s.name
        FROM product_variants pv
        JOIN sizes s ON pv.size_id = s.id
        WHERE pv.product_id = ? AND pv.color_id = ? AND pv.quantity > 0
    """, (product_id, color_id))
    size_keyboard = [
        [InlineKeyboardButton(s['name'], callback_data=f"size_{product_id}_{color_id}_{s['id']}")] for s in sizes
    ]
    size_keyboard.append([InlineKeyboardButton("◀️ К цветам", callback_data=f"details_{product_id}")])

    # --- Кнопки пагинации медиа ---
    nav_buttons = []
    if total_media > 1:
        if page > 0:
            nav_buttons.append(InlineKeyboardButton("⬅️", callback_data=f"colorphoto_{product_id}_{color_id}_{page-1}"))
        nav_buttons.append(InlineKeyboardButton(f"{page+1}/{total_media}", callback_data="noop"))
        if page < total_media - 1:
            nav_buttons.append(InlineKeyboardButton("➡️", callback_data=f"colorphoto_{product_id}_{color_id}_{page+1}"))
    keyboard = [nav_buttons] if nav_buttons else []
    keyboard += size_keyboard

    text = f"<b>Фото {page+1} из {total_media}</b>" if total_media > 0 else "*Нет медиа для выбранного цвета*"
    text += "\n\n" + "Выберите размер:"

    # --- Отправляем медиа или просто текст с кнопками ---
    if not file_id:
        await safe_edit_or_send(query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="HTML", context=context)
        context.user_data['color_photo_page'] = page
        return

    # Если есть медиа (фото или видео)
    try:
        if is_video:
            await query.message.edit_media(
                media=InputMediaVideo(file_id, caption=text, parse_mode="HTML"),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            await query.message.edit_media(
                media=InputMediaPhoto(file_id, caption=text, parse_mode="HTML"),
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    except Exception:
        # Только если edit_media не сработал — удаляем и отправляем новое
        try:
            await query.message.delete()
        except Exception:
            pass
        if is_video:
            await query.message.chat.send_video(
                video=file_id,
                caption=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        else:
            try:
                await query.message.edit_media(
                    media=InputMediaPhoto(file_id, caption=text, parse_mode="HTML"),
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
            except Exception:
                try:
                    await query.message.delete()
                except Exception:
                    pass
            await query.message.chat.send_photo(
                photo=file_id,
                caption=text,
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
    context.user_data['color_photo_page'] = page

async def color_photo_pagination(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, product_id, color_id, page = query.data.split('_')
    product_id, color_id, page = int(product_id), int(color_id), int(page)
    context.user_data['color_photo_page'] = page
    # Просто вызываем choose_color с нужной страницей
    await choose_color(update, context)

async def choose_size(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    _, product_id, color_id, size_id = query.data.split('_')
    product_id, color_id, size_id = int(product_id), int(color_id), int(size_id)
    context.user_data['current_product_id'] = product_id
    context.user_data['chosen_color_id'] = color_id
    context.user_data['chosen_size_id'] = size_id
    context.user_data['all_mode'] = context.user_data.get('all_mode', False)  #  безопасно



    if 'current_subcat_id' not in context.user_data or 'current_brand_id' not in context.user_data:
        product = await fetchone("SELECT sub_category_id, brand_id FROM products WHERE id = ?", (product_id,))
        if product:
            context.user_data['current_subcat_id'] = product['sub_category_id']
            context.user_data['current_brand_id'] = product['brand_id']

    variant = await fetchone("""
        SELECT pv.*, s.name as size, c.name as color
        FROM product_variants pv
        JOIN sizes s ON pv.size_id = s.id
        JOIN colors c ON pv.color_id = c.id
        WHERE pv.product_id = ? AND pv.color_id = ? AND pv.size_id = ? AND pv.quantity > 0
        LIMIT 1
    """, (product_id, color_id, size_id))
    if not variant:
        await safe_edit_or_send(query, md2("Нет такого варианта в наличии.") , parse_mode="MarkdownV2", context=context)
        return
    product = await fetchone("SELECT name FROM products WHERE id = ?", (product_id,))
    text = (
        f"<b>{product['name']}</b>\n \n<i>Цвет:</i> <b><i>{variant['color']}</i></b>\n<i>Размер:</i> <b><i>{variant['size']}</i></b>\n<i>Цена:</i> <b><i>{variant['price']}₸</i></b>\n<i>В наличии:</i> <b><i>{variant['quantity']} шт.</i></b>\n\n"
    )
    keyboard = [
        [InlineKeyboardButton(md2("✅ Добавить в корзину"), callback_data=f"add_{variant['id']}")],
        [InlineKeyboardButton(md2("◀️ К размерам"), callback_data=f"color_{product_id}_{color_id}")],
        [InlineKeyboardButton(md2("⏪ К товарам "), callback_data="back_to_slider")],
        [InlineKeyboardButton(md2("🏚 Главное меню ") , callback_data="back_to_main_menu")]
    ]
    await safe_edit_or_send(query, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode=ParseMode.HTML, context=context)

async def back_to_slider(update: Update, context: ContextTypes.DEFAULT_TYPE, subcat_id=None, brand_id=None):
    query = update.callback_query
    await query.answer()

    slider_ctx = context.user_data.get('return_to_slider', {})
    context.user_data['product_slider_page'] = slider_ctx.get('product_slider_page', 0)
    context.user_data['all_mode'] = slider_ctx.get('all_mode', False)
    context.user_data['current_subcat_id'] = slider_ctx.get('current_subcat_id')
    context.user_data['current_brand_id'] = slider_ctx.get('current_brand_id')

    all_mode = context.user_data['all_mode']
    subcat_id = context.user_data['current_subcat_id']
    brand_id = context.user_data['current_brand_id']

    await asyncio.sleep(0.1)

    if all_mode:
        await show_product_slider(update, context, subcat_id=subcat_id, all_mode=True)
    elif brand_id is not None:
        products = await fetchall(
            """
            SELECT p.id FROM products p
            JOIN product_variants pv ON p.id = pv.product_id
            WHERE p.sub_category_id = ? AND p.brand_id = ? AND pv.quantity > 0
            GROUP BY p.id
            """,
            (subcat_id, brand_id)
        )
        if products:
            await show_product_slider(update, context, brand_id=brand_id, all_mode=False)
        else:
            await show_product_slider(update, context, subcat_id=subcat_id, all_mode=False)
    elif subcat_id is not None:
        await show_product_slider(update, context, subcat_id=subcat_id, all_mode=False)
    else:
        await show_product_slider(update, context, all_mode=False)

async def add_item_to_cart(context : ContextTypes.DEFAULT_TYPE, product_variant_id, chat_id, query=None ):
    variant = await fetchone("""
        SELECT pv.id, pv.quantity, p.name, pv.price, s.name as size, c.name as color
        FROM product_variants pv
        JOIN products p ON pv.product_id = p.id
        JOIN sizes s ON pv.size_id = s.id
        JOIN colors c ON pv.color_id = c.id
        WHERE pv.id = ?
    """, (product_variant_id,))
    if not variant or variant['quantity'] <= 0:
        msg = ("❌ Этот вариант товара закончился на складе.")
        if query:
            await query.answer(msg, show_alert=True)
        else:
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
        return False
    cart = context.user_data.setdefault('cart', {})
    
    variant_id_str = str(product_variant_id)
    current_quantity = cart.get(variant_id_str, {}).get('quantity', 0)
    if current_quantity >= variant['quantity']:
        msg = ("Вы уже добавили в корзину всё, что есть в наличии!")
        if query:
            await query.answer(msg, show_alert=True)
        else:
            await context.bot.send_message(chat_id=chat_id, text=msg, parse_mode="HTML")
        return False
    full_name = f"{variant['name']} ({variant['size']}, {variant['color']})"
    if variant_id_str in cart:
        cart[variant_id_str]['quantity'] += 1
    else:
        cart[variant_id_str] = {'name': full_name, 'price': variant['price'], 'quantity': 1}
    return True



async def show_cart(update: Update, context: ContextTypes.DEFAULT_TYPE , edit=True):
    cart = context.user_data.setdefault('cart', {})
    chat_id = update.effective_chat.id
    


    if update.callback_query:
        await update.callback_query.answer()
    data = update.callback_query.data if update.callback_query else None
    if data and data.startswith("add_"):
        if context.user_data.get('cart_return_source') is None:
            context.user_data['cart_return_source'] = "slider"



    kb_back = [[InlineKeyboardButton("◀ Назад", callback_data="back_from_cart")]]    
    if not cart:
        text = "🛒 Ваша корзина пуста."
        reply_markup = InlineKeyboardMarkup(kb_back)
    else:
        text_raw = "🛒 Ваша корзина:\n\n"
        text = f"<i>{text_raw}</i>"

        total_price = 0
        keyboard = []

        for variant_id_str, item in cart.items():
            item_total = item['price'] * item['quantity']
            total_price += item_total

            text += f" <b>{item['name']} (x{item['quantity']}) - {item_total}₸</b>\n\n"

            keyboard.append([
                InlineKeyboardButton("➖", callback_data=f"cart_minus_{variant_id_str}"),
                InlineKeyboardButton(str(item['quantity']), callback_data="noop"),
                InlineKeyboardButton("➕", callback_data=f"cart_plus_{variant_id_str}")
            ])

        text += f"\n<i>Итого:</i> <b>{total_price}₸</b>"
        keyboard.append([InlineKeyboardButton("🧾 Оформить заказ", callback_data="by_all")])
        keyboard.append([InlineKeyboardButton("🗑️ Очистить корзину", callback_data="clear_cart")])
        keyboard.append([InlineKeyboardButton("◀ Назад", callback_data="back_from_cart")])
        reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        elif update.message:
            await update.message.reply_text(
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
        else:
            await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                parse_mode=ParseMode.HTML,
                reply_markup=reply_markup
            )
    except telegram.error.BadRequest:
        await context.bot.send_message(
            chat_id=chat_id,
            text=text,
            parse_mode=ParseMode.HTML,
            reply_markup=reply_markup
        )
async def back_from_cart_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    source = context.user_data.get("cart_return_source")

    if source == "slider":
                slider_ctx = context.user_data.get('return_to_slider')
                if slider_ctx:
                    context.user_data['product_slider_page'] = slider_ctx.get('product_slider_page', 0)
                    context.user_data['all_mode'] = slider_ctx.get('all_mode', True)
                    context.user_data['current_subcat_id'] = slider_ctx.get('current_subcat_id')
                    context.user_data['current_brand_id'] = slider_ctx.get('current_brand_id')

                    if context.user_data['all_mode']:
                        await show_product_slider(update, context, subcat_id=context.user_data['current_subcat_id'], all_mode=True)
                    else:
                        await show_product_slider(update, context, brand_id=context.user_data['current_brand_id'], subcat_id=context.user_data['current_subcat_id'])
                    return  # ← обязательно!

    

            

            # Любой другой случай — главное меню
    await show_reply_main_menu(update, context )


async def reply_cart_button(update: Update, context: ContextTypes.DEFAULT_TYPE):

    await show_cart(update, context, edit=False)

async def clear_cart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['cart'] = {}  # безопаснее, чем pop()
    kb = [[InlineKeyboardButton("◀ Назад", callback_data="back_from_cart")]]
    await safe_edit_or_send(query, md2("🛒 Ваша корзина очищена."), context , reply_markup=InlineKeyboardMarkup(kb))


async def cart_plus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    variant_id = query.data.split('_')[2]
    cart = context.user_data.setdefault('cart', {})
    item = cart.get(variant_id)
    
    if not item:
        await query.answer("❌ Товар не найден в корзине.", show_alert=True)
        return

    try:
        variant = await fetchone("SELECT quantity FROM product_variants WHERE id = ?", (variant_id,))
    except Exception as e:
        await query.answer("⚠️ Ошибка при проверке наличия.", show_alert=True)
        return

    if not variant:
        await query.answer("❌ Товар больше недоступен.", show_alert=True)
        return

    if item['quantity'] >= variant['quantity']:
        await query.answer("📦 Больше нет в наличии!", show_alert=True)
        return

    item['quantity'] += 1

    try:
        await show_cart(update, context , edit= True)
    except Exception as e:
        print("⚠️ Ошибка при отображении корзины после +:", e)


async def cart_minus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    variant_id = query.data.split('_')[2]
    cart = context.user_data.setdefault('cart', {})

    if variant_id not in cart:
        await query.answer("❌ Товар не найден.", show_alert=True)
        return

    cart[variant_id]['quantity'] -= 1

    if cart[variant_id]['quantity'] <= 0:
        del cart[variant_id]

    try:
        await show_cart(update, context, edit=True)
    except Exception as e:
        print("⚠️ Ошибка при отображении корзины после -:", e)

async def add_to_cart_handler_func(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = update.effective_chat.id
    product_variant_id = int(query.data.split("_")[1])

    subcat_id = context.user_data.get('current_subcat_id')
    brand_id = context.user_data.get('current_brand_id')

    if not subcat_id or not brand_id:
        product_info = await fetchone(
            "SELECT p.sub_category_id, p.brand_id, sc.category_id "
            "FROM product_variants pv "
            "JOIN products p ON pv.product_id = p.id "
            "JOIN sub_categories sc ON p.sub_category_id = sc.id "
            "WHERE pv.id = ?",
            (product_variant_id,)
        )
        if product_info:
            subcat_id = product_info['sub_category_id']
            brand_id = product_info['brand_id']
            context.user_data['current_subcat_id'] = subcat_id
            context.user_data['current_brand_id'] = brand_id
            context.user_data['current_category_id'] = product_info['category_id']

    context.user_data['current_subcat_id'] = subcat_id or 1
    context.user_data['current_brand_id'] = brand_id or 1
    context.user_data['current_category_id'] = context.user_data.get('current_category_id', 1)


    slider_ctx = context.user_data.get('return_to_slider', {})
    context.user_data['product_slider_page'] = slider_ctx.get('product_slider_page', 0)
    context.user_data['all_mode'] = slider_ctx.get('all_mode', True)
    context.user_data['current_subcat_id'] = slider_ctx.get('current_subcat_id', subcat_id)
    context.user_data['current_brand_id'] = slider_ctx.get('current_brand_id', brand_id)
    context.user_data['cart_return_source'] = "slider"

    result = await add_item_to_cart(context, product_variant_id, chat_id, query)
    kb = [[InlineKeyboardButton("🛒 Посмотреть корзину", callback_data="cart")],
          [InlineKeyboardButton("◀ Назад", callback_data="back_to_slider")]]

    if result:
        try:
            await query.message.delete()
        except Exception as e:
            print("❌ Не удалось удалить сообщение:", e)
        await context.bot.send_message(chat_id=chat_id, text="✅ Добавлено в корзину!" , reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")

        await asyncio.sleep(0.1)  # Небольшая задержка перед возвратом к слайдеру

        


        #await show_product_slider(update, context,
            #subcat_id=context.user_data['current_subcat_id'],
            #brand_id=context.user_data['current_brand_id'],
            #all_mode=context.user_data['all_mode']
        #)




async def start_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data.split('_')[0] if query.data else None
    cart = context.user_data.get("cart", {})
    if not isinstance(cart, dict) or not cart:
        await safe_edit_or_send(query, md2("🛒 Ваша корзина пуста.") , parse_mode="MarkdownV2")
        return ConversationHandler.END
    kb = [[InlineKeyboardButton(md2("❌ Отменить"), callback_data="cancel_checkout")],]
    
    context.user_data['checkout_cart'] = cart  # Сохраняем корзину для дальнейшего использования
   
    await safe_edit_or_send(query, md2("Для оформления заказа, пожалуйста, введите ваше имя"), parse_mode="MarkdownV2", context=context , reply_markup=InlineKeyboardMarkup(kb))
    return ASK_NAME

async def ask_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["checkout_name"] = update.message.text
    await update.message.reply_text(md2("Отлично! Теперь адрес для доставки"), parse_mode="MarkdownV2")
    return ASK_ADDRESS

async def ask_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["checkout_address"] = update.message.text
    await update.message.reply_text(md2("Спасибо! И последнее, ваш контактный номер"), parse_mode="MarkdownV2")
    return ASK_PHONE

async def ask_phone(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["checkout_phone"] = update.message.text
    user_id = update.effective_user.id
    name = context.user_data["checkout_name"]
    address = context.user_data["checkout_address"]
    phone = context.user_data["checkout_phone"]
    cart = context.user_data.get("cart", {})
    if not isinstance(cart, dict):
        cart = {}
    cart_json = json.dumps(cart, ensure_ascii=False)
    total_price = sum(item['price'] * item['quantity'] for item in cart.values())
    try:
        order_id = await execute(
    "INSERT INTO orders (user_id, user_name, user_address, user_phone, cart, total_price, status) VALUES (?, ?, ?, ?, ?, ?, ?)",
    (user_id, name, address, phone, cart_json, total_price, 'pending_payment')
                                )

    except Exception as e:
        print(f"Ошибка при сохранении заказа в БД: {e}")
        await update.message.reply_text(md2("Произошла ошибка."), parse_mode="MarkdownV2")
        return ConversationHandler.END
    
     # --- Формируем чек ---
    cart_lines = []
    for item in cart.values():
        cart_lines.append(f"{item['name']} x{item['quantity']} = {item['price']*item['quantity']}₸")
    cart_text = "\n".join(cart_lines)
    receipt_text = (
        f"🧾 <b>Ваш чек №{order_id}</b>\n\n"
        f"<b>Имя:</b> {name}\n"
        f"<b>Телефон:</b> {phone}\n"
        f"<b>Адрес:</b> {address}\n\n"
        f"<b>Товары:</b>\n{cart_text}\n\n"
        f"<b>Итого:</b> {total_price}₸"
    )

    await update.message.reply_text(receipt_text, parse_mode="HTML")

    
    kaspi_link = "https://pay.kaspi.kz/pay/f9ja8t7g"
    message_text = (
        f"{md2('✅ Ваш заказ')} *№{md2(order_id)}* {md2('почти готов')}\\!\n\n"
        f"{md2('Сумма к оплате')}: *{md2(total_price)} ₸*\n\n"
        f"{md2('Пожалуйста, оплатите заказ по ссылке в Kaspi')}:\n👉 [Оплатить через Kaspi]({kaspi_link})\n\n"
        f"*{md2('ВАЖНО')}:* {md2('В комментарии к платежу укажите номер заказа')}: `{md2(order_id)}`\n\n"
        f"{md2('После оплаты вернитесь и нажмите кнопку ниже')}\\."
    )
    keyboard = [[InlineKeyboardButton(f"{md2('✅ Оплатил')}", callback_data=f"paid_{order_id}")],
                [InlineKeyboardButton(md2("❌ Отменить заказ"), callback_data=f"cancel_by_client_{order_id}")]
                ]
    await update.message.reply_text(
        message_text, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True
    )
    context.user_data.pop('cart', None)
    return ConversationHandler.END


async def cancel_by_client(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split('_')[-1])

    keyboard = [
        [
            InlineKeyboardButton("✅ Да, отменить", callback_data=f"confirm_cancel_{order_id}"),
            InlineKeyboardButton("🔙 Назад", callback_data=f"back_to_payment_{order_id}")
        ]
    ]
    await query.edit_message_text(
        text="❗ Вы уверены, что хотите отменить заказ?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def confirm_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split('_')[-1])

    

    await query.edit_message_text(f"❌ Ваш заказ {md2(order_id)} был отменён.")
    order = await fetchone("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not order or order["status"] in ("delivered", "cancelled_by_client", "rejected"):
        await query.edit_message_text("⚠️ Заказ уже не может быть отменён.")
        return
    
    # Если товар уже списан — вернём его обратно на склад
    if order["deducted_from_stock"] == 1:

        try:
            cart = json.loads(order["cart"])
            for variant_id_str, item in cart.items():
                await execute(
                    "UPDATE product_variants SET quantity = quantity + ? WHERE id = ?",
                    (item['quantity'], int(variant_id_str))
                )
            await execute("UPDATE orders SET deducted_from_stock = 0 WHERE id = ?", (order_id,))
        except Exception as e:
            await query.edit_message_text(f"❌ Ошибка при возврате товаров на склад: {e}")
            return

    # Обновляем статус
    await execute("UPDATE orders SET status = ? WHERE id = ?", ("cancelled_by_client", order_id))

    # Информация о заказе для админа
    cart = json.loads(order['cart'])
    cart_text = "\n".join([f"• {md2(item['name'])} \(x{md2(item['quantity'])}\)" for item in cart.values()])

    user_link = f"[@{md2(update.effective_user.username)}](https://t.me/{md2(update.effective_user.username)})" if update.effective_user.username else md2("нет username")

    admin_info = (
        f"📦 *Информация о заказе №{md2(order_id)}*\n\n"
        f"{md2('Сумма')}: {md2(order['total_price'])} ₸\n"
        f"{md2('Клиент')}: {md2(order['user_name'])}\n"
        f"{md2('Username')}: {user_link}\n"
        f"{md2('Телефон')}: {md2(order['user_phone'])}\n"
        f"{md2('Адрес')}: {md2(order['user_address'])}\n\n"
        f"*{md2('Состав заказа')}*:\n{cart_text}\n"
    )

    for admin_id in ADMIN_IDS:
        await context.bot.send_message(admin_id, f"⚠️ Клиент отменил заказ №{order_id} \n\n {admin_info}")



async def back_to_payment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split('_')[-1])

    order = await fetchone("SELECT * FROM orders WHERE id = ?", (order_id,))
    if not order:
        await query.edit_message_text("⚠️ Заказ не найден.")
        return

    if order["status"] != "pending_payment":
        await query.edit_message_text("⚠️ Заказ уже неактивен.")
        return


    cart = json.loads(order['cart'])
    cart_text = "\n".join([f"• {item['name']} x{item['quantity']} = {item['price'] * item['quantity']}₸" for item in cart.values()])
    
    kaspi_link = "https://pay.kaspi.kz/pay/f9ja8t7g"
    message_text = (
        f"{md2('✅ Ваш заказ')} *№{md2(order_id)}* {md2('почти готов')}\\!\n\n"
        f"{md2('Сумма к оплате')}: *{md2(order['total_price'])} ₸*\n\n"
        f"{md2('Пожалуйста, оплатите заказ по ссылке в Kaspi')}:\n👉 [Оплатить через Kaspi]({kaspi_link})\n\n"
        f"*{md2('ВАЖНО')}:* {md2('В комментарии к платежу укажите номер заказа')}: `{md2(order_id)}`\n\n"
        f"{md2('После оплаты вернитесь и нажмите кнопку ниже')}\\."
    )
    keyboard = [
        [InlineKeyboardButton("✅ Оплатил", callback_data=f"paid_{order_id}")],
        [InlineKeyboardButton("❌ Отменить заказ", callback_data=f"cancel_by_client_{order_id}")]
    ]

    await query.edit_message_text(
        message_text, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard), disable_web_page_preview=True
    )



async def payment_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    order_id = int(query.data.split('_')[1])
    order = await fetchone("SELECT * FROM orders WHERE id = ?", (order_id,))
    if order and order['status'] == 'pending_payment':
        await execute("UPDATE orders SET status = ? WHERE id = ?", ('pending_verification', order_id))
        cart = json.loads(order['cart'])
        cart_text = "\n".join([f"• {md2(item['name'])} \\(x{md2(item['quantity'])}\\)" for item in cart.values()])

        user_id = order['user_id']
        user_name = order['user_name']
        user_username = None
        try:
            user_obj = await context.bot.get_chat(user_id)
            user_username = user_obj.username
        except Exception:
            user_username = None

        if user_username:
            username_link = f"[@{md2(user_username)}](https://t.me/{md2(user_username)})"
        else:
            username_link = md2("нет username")

        admin_message = (
            f"🔔 *{md2('Клиент')}* \\(id: {md2(user_id)}\\) *{md2('подтвердил оплату заказа')} №{md2(order_id)}* 🔔\n\n"
            f"{md2('Сумма')}: {md2(order['total_price'])} ₸\n"
            f"{md2('Клиент')}: {md2(user_name)}\n"
            f"{md2('Username')}: {username_link}\n"
            f"{md2('Телефон')}: {md2(order['user_phone'])}\n"
            f"{md2('Адрес')}: {md2(order['user_address'])}\n\n"
            f"*{md2('Состав заказа')}*:\n{cart_text}\n\n"
            f"*{md2('ПРОВЕРЬТЕ поступление в Kaspi Pay и подтвердите заказ')}\\.*"
        )
        keyboard = [
            [
                InlineKeyboardButton(md2("✅ Подтвердить"), callback_data=f"admin_confirm_{order_id}"),
                InlineKeyboardButton(md2("❌ Отклонить"), callback_data=f"admin_reject_{order_id}")
            ]
        ]
        for admin_id in ADMIN_IDS:
            await context.bot.send_message(chat_id=admin_id, text=admin_message, parse_mode="MarkdownV2", reply_markup=InlineKeyboardMarkup(keyboard))
    await safe_edit_or_send(query, md2("Спасибо! Ваш заказ принят в обработку! Ожидайте подтверждения от менеджера"), parse_mode="MarkdownV2", context=context)

async def cancel_checkout(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    
    await asyncio.sleep(0.1) 
    await back_from_cart_handler(update, context)
    return ConversationHandler.END




def escape_html(text: str) -> str:
    if not text:
        return "-"
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
    )

from telegram import InlineQueryResultArticle, InputTextMessageContent, InlineKeyboardMarkup, InlineKeyboardButton

async def inlinequery(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query_text = update.inline_query.query.strip()

    if not query_text:
        query_sql = """
            SELECT p.id, p.name, p.description,
                   p.sub_category_id, p.brand_id,
                   c.name AS category,
                   sc.name AS subcategory,
                   b.name AS brand,
                   MIN(pv.price) AS min_price,
                   MAX(pv.photo_url) AS photo_url
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN sub_categories sc ON p.sub_category_id = sc.id
            LEFT JOIN brands b ON p.brand_id = b.id
            LEFT JOIN product_variants pv ON p.id = pv.product_id
            GROUP BY p.id
            LIMIT 10
        """
        params = ()
    else:
        query_sql = """
            SELECT p.id, p.name, p.description,
                   p.sub_category_id, p.brand_id,
                   c.name AS category,
                   sc.name AS subcategory,
                   b.name AS brand,
                   MIN(pv.price) AS min_price,
                   (
                       SELECT photo_url
                       FROM product_variants pv2
                       WHERE pv2.product_id = p.id AND pv2.photo_url IS NOT NULL
                       ORDER BY pv2.id ASC LIMIT 1
                   ) AS photo_url
            FROM products p
            LEFT JOIN categories c ON p.category_id = c.id
            LEFT JOIN sub_categories sc ON p.sub_category_id = sc.id
            LEFT JOIN brands b ON p.brand_id = b.id
            LEFT JOIN product_variants pv ON p.id = pv.product_id
            WHERE p.name LIKE ? OR p.description LIKE ? OR
                  c.name LIKE ? OR sc.name LIKE ? OR b.name LIKE ?
            GROUP BY p.id
            LIMIT 10
        """
        params = (f"%{query_text}%",) * 5

    products = await fetchall(query_sql, params)

    results = []
    for p in products:
        name = p["name"]
        desc = p["description"] or "—"
        category = p["category"] or "—"
        subcat = p["subcategory"] or "—"
        brand = p["brand"] or "—"
        price = int(p["min_price"]) if p["min_price"] else 0
        thumb_url = p["photo_url"]

        subcat_id = p['sub_category_id'] or 0
        brand_id = p['brand_id'] or 0   

        message = (
            f"<b>{name}</b>\n\n"
            f"{desc}\n\n"
            f"<b>Категория:</b> {category}\n"
            f"<b>Раздел:</b> {subcat}\n"
            f"<b>Бренд:</b> {brand}\n"
            f"<b>Цена от:</b> {price} ₸"
        )

        result = InlineQueryResultArticle(
            id=f"prod_{p['id']}",
            title=name,
            description=f"{brand} · от {price} ₸",
            input_message_content=InputTextMessageContent(
                message,
                parse_mode="HTML"
            ),
            thumbnail_url=thumb_url if thumb_url else None,
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📦 Подробнее", callback_data=f"details_{p['id']}_{subcat_id}_{brand_id}")]
            ])
        )
        results.append(result)

    await update.inline_query.answer(results, cache_time=1)







async def help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "Контакты поддержки: @candyy_sh0p\n\n"
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("◀ Назад", callback_data="back_to_main_menu")]
    ])

    try:
        if getattr(update, "callback_query", None):
            await update.callback_query.answer()
            try:
                await update.callback_query.message.edit_text(
                    text, reply_markup=keyboard
                )
                return
            except:
                pass
            try:
                await update.callback_query.message.delete()
            except:
                pass
            await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                reply_markup=keyboard
            )
        else:
            await update.message.reply_text(
                text, reply_markup=keyboard
            )
    except Exception as e:
        print("Ошибка при показе помощи:", e)


async def get_main_menu(context: ContextTypes.DEFAULT_TYPE ):
    
    if 'cart_return_source' not in context.user_data:
        context.user_data['cart_return_source'] = "main_menu"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Каталог 📦", callback_data="catalog")],
            [InlineKeyboardButton("Поиск товара 🔎", switch_inline_query_current_chat="")],
            [InlineKeyboardButton("История заказов 📒", callback_data="order_history")],
            [InlineKeyboardButton("Корзина 🛒", callback_data="cart")],
            [InlineKeyboardButton("Помощь ℹ️", callback_data="help")]
        ]
    ) 

kb = ReplyKeyboardMarkup(keyboard=
                               [
                                   ["Главное меню"]
                               ],
        resize_keyboard=True
    )

async def show_reply_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE , text="Главное меню\nвыберите действие:"):
    
    context.user_data['cart_return_source'] = "main_menu"


    """
    Универсально: вызывает главное меню как reply-клавиатуру.
    Автоматически определяет — edit, delete+send или просто send.
    """

    try:
        await update.message.delete()  # ← удаляет сообщение с /start
    except Exception as e:
        print("Не удалось удалить Главное меню:", e)
    msg = None
    try:
        # Если это callback_query (инлайн-кнопка)
        if getattr(update, "callback_query", None):
            await update.callback_query.answer()
            # 1. Пробуем отредактировать текст (если сообщение поддерживает edit)
            try:
                await update.callback_query.message.edit_text(
                    text, reply_markup=await get_main_menu(context=context),
                    parse_mode=ParseMode.HTML
                )
                return
            except Exception:
                pass
            # 2. Не получилось — удаляем старое сообщение и отправляем новое
            try:
                await update.callback_query.message.delete()
            except Exception:
                pass
            msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                reply_markup=await get_main_menu(context=context)
            )
        # Если это обычное сообщение (например, по команде /start)
        elif getattr(update, "message", None):
            msg = await update.message.reply_text(
                text, reply_markup=await get_main_menu(context=context)
            )
        # Если вдруг передали только chat_id (редко, но удобно для рассылок)
        elif getattr(update, "effective_chat", None):
            msg = await context.bot.send_message(
                chat_id=update.effective_chat.id,
                text=text,
                reply_markup=await get_main_menu(context=context)
            )
    except Exception as e:
        print("Ошибка при показе главного меню:", e)
    return msg



async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = "Добро пожаловать в наш магазин!"
    await update.message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML
    )
    args = context.args
    try:
        await update.message.delete()  # ← удаляет сообщение с /start
    except Exception as e:
        print("Не удалось удалить /start:", e)

    

    # Иначе просто показываем меню
    await show_reply_main_menu(update, context)

async def d(update:Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("."  , parse_mode=ParseMode.HTML
                                    )

    args = context.args
    try:
        await update.message.delete()  # ← удаляет сообщение с /d
    except Exception as e:
        print("Не удалось удалить /d:", e)
    # Если был передан параметр ?start=prod_123
    if args and args[0].startswith("prod_"):
        product_id = int(args[0].split("_")[1])
        context.user_data['current_product_id'] = product_id

        # Показываем детали товара
        await show_product_details(update, context)
        return
    


    # --- Регистрация обработчиков ---
start_handler = CommandHandler("start",start)

catalog_handler = CallbackQueryHandler(show_catalog, pattern="^catalog$")
reply_cart_handler = MessageHandler(filters.Regex("^🛒 Посмотреть корзину$"), reply_cart_button)
subcategories_handler = CallbackQueryHandler(show_subcategories, pattern="^cat_\\d+$")
brands_handler = CallbackQueryHandler(show_brand_or_all, pattern="^subcat_\\d+$")
brand_slider_handler = CallbackQueryHandler(start_brand_slider, pattern="^brand_\\d+_\\d+$")
all_slider_handler = CallbackQueryHandler(start_all_slider, pattern="^showall_\\d+_page_0$")
back_to_brands_handler = CallbackQueryHandler(back_to_brands, pattern="^brands_\\d+$")
back_to_main_cat_handler = CallbackQueryHandler(back_to_main_cat, pattern="^back_to_main_cat$")
help_handler = CallbackQueryHandler(help, pattern="^help$")

brand_slider_nav_handler = CallbackQueryHandler(handle_brand_slider, pattern="^brand_slider_\\d+_\\d+_\\d+$")
all_slider_nav_handler = CallbackQueryHandler(handle_all_slider, pattern="^all_slider_\\d+__\\d+$")
details_handler = CallbackQueryHandler(show_product_details, pattern=r"^details_\d+(_\d+_\d+)?$")


choose_color_handler = CallbackQueryHandler(choose_color, pattern="^color_\\d+_\\d+$")
choose_size_handler = CallbackQueryHandler(choose_size, pattern="^size_\\d+_\\d+_\\d+$")
back_to_slider_handler = CallbackQueryHandler(back_to_slider, pattern="^back_to_slider$")
add_to_cart_handler = CallbackQueryHandler(add_to_cart_handler_func, pattern="^add_\\d+$")
cart_back_handler = CallbackQueryHandler(back_from_cart_handler, pattern="^back_from_cart$")
cart_handler = CallbackQueryHandler(show_cart, pattern="^cart$")
cart_plus_handler = CallbackQueryHandler(cart_plus, pattern="^cart_plus_\\d+$")
cart_minus_handler = CallbackQueryHandler(cart_minus, pattern="^cart_minus_\\d+$")
clear_cart_handler = CallbackQueryHandler(clear_cart, pattern="^clear_cart$")
payment_confirmation_handler = CallbackQueryHandler(payment_confirmation, pattern="^paid_")
checkout_handler = ConversationHandler(
    entry_points=[CallbackQueryHandler(start_checkout, pattern="^by_all$")],
    states={
        ASK_NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_name)],
        ASK_ADDRESS: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_address)],
        ASK_PHONE: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_phone)],
    },
    fallbacks=[CommandHandler("cancel", cancel_checkout) , 
               CallbackQueryHandler(cancel_checkout, pattern="^cancel_checkout$")],
    per_user=True, per_chat=True
)


reply_main_menu_handler = MessageHandler(
    filters.TEXT & filters.Regex("^Главное меню$"),
    show_reply_main_menu 
)
back_to_main_menu_handler = CallbackQueryHandler(show_reply_main_menu , pattern= "back_to_main_menu")
