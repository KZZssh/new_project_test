import logging
import os
import asyncio
from telegram import Update
from telegram.ext import (
    Application, ContextTypes, PicklePersistence, CommandHandler, 
    CallbackQueryHandler, InlineQueryHandler, MessageHandler, filters, 
    ConversationHandler
)

# --- Веб-сервер ---
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route

# --- Сіздің импорттарыңыз ---
from configs import BOT_TOKEN
from admin_handlers_newupdate import (
     add_product_conv , finish_media,
     report_handler, admin_decision_handler, cancel_dialog, cat_manage_handler,
    subcat_manage_handler, subcat_rename_conv, brand_manage_handler, brand_rename_conv,
    orders_report_handler, orders_report_period_handler, admin_conv, 
    get_name, get_new_category_name, get_new_subcategory_name, get_new_brand_name, get_description,
    get_new_size_name, get_new_color_name, get_variant_price, get_variant_quantity,
     update_order_status_admin, order_history_handler, order_filter_handler,
    cancel_from_history_handler, confirm_cancel_from_history, back_to_order_history,
    pagination_handler , cleanup_handler
)
from client_handlers_org import (
    start_handler, catalog_handler, reply_cart_handler, subcategories_handler, brands_handler,
    brand_slider_handler, all_slider_handler, brand_slider_nav_handler, all_slider_nav_handler,
    details_handler, choose_color_handler, choose_size_handler, back_to_slider_handler,
    add_to_cart_handler, cart_back_handler, cart_handler, cart_plus_handler, cart_minus_handler, clear_cart_handler,
    payment_confirmation_handler, checkout_handler, back_to_brands_handler, back_to_main_cat_handler,
    color_photo_pagination, inlinequery, help_handler, reply_main_menu_handler,
    cancel_by_client, confirm_cancel, back_to_payment, back_to_main_menu_handler, d , noop_handler 
)

# Логгингті баптау
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

async def debug_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query:
        logging.info(f"⚠️ [DEBUG CALLBACK GLOBAL]: {query.data}")


async def main() -> None:
    """Ботты баптап, іске қосатын негізгі асинхронды функция."""
    
    persistence = PicklePersistence(filepath="bot_data.pkl")
    application = (
        Application.builder().token(BOT_TOKEN).persistence(persistence).build()
    )

    # === ГРУППА -1: ОТЛАДКА (Ловит всё, но не мешает) ===
    # Этот хендлер просто логгирует ВСЕ нажатия на кнопки. Очень полезно для дебага.
    # block=False означает, что после него обработка пойдет дальше.
    #application.add_handler(MessageHandler(filters.COMMAND, cleanup_handler), group=-1)
    application.add_handler(
        CallbackQueryHandler(debug_all_callback, pattern=".*", block=False), 
        group=-1
    )

    # === ГРУППА 0: ГЛОБАЛЬНЫЕ ОБРАБОТЧИКИ (Работают всегда и везде) ===
    # Эти команды и коллбэки должны срабатывать, даже если админ находится внутри диалога.
    
    # Самый важный - обработчик кнопок подтверждения/отклонения заказа
    application.add_handler(admin_decision_handler, group=0)
    
    # Глобальные команды, которые должны быть доступны всегда
    application.add_handler(start_handler, group=0)
    application.add_handler(help_handler, group=0)
    
    # Глобальный обработчик для выхода из любого диалога
    application.add_handler(MessageHandler(filters.COMMAND, cancel_dialog), group=0)


    # === ГРУППА 1: ОСНОВНЫЕ ОБРАБОТЧИКИ И ДИАЛОГИ ===
    # Сюда идет вся основная логика твоего бота.
    
    # --- ДИАЛОГИ (ConversationHandlers) ---
    application.add_handler(add_product_conv, group=1)
    application.add_handler(brand_rename_conv, group=1)
    application.add_handler(admin_conv, group=1)
    application.add_handler(subcat_rename_conv, group=1)
    
    # --- ОБРАБОТЧИКИ АДМИН-ПАНЕЛИ (не в диалогах) ---
    application.add_handler(report_handler, group=1)
    application.add_handler(cat_manage_handler, group=1)
    application.add_handler(subcat_manage_handler, group=1)
    application.add_handler(brand_manage_handler, group=1)
    application.add_handler(orders_report_handler, group=1)
    application.add_handler(orders_report_period_handler, group=1)
    application.add_handler(CallbackQueryHandler(update_order_status_admin, pattern=r"^status_(preparing|shipped|delivered)_\d+$"), group=1)
    application.add_handler(CallbackQueryHandler(order_history_handler, pattern="^order_history$"), group=1)
    application.add_handler(CallbackQueryHandler(order_filter_handler, pattern="^order_filter_"), group=1)
    application.add_handler(CallbackQueryHandler(pagination_handler, pattern="^page_"), group=1)
    application.add_handler(CallbackQueryHandler(cancel_from_history_handler, pattern="^cancel_from_history_"), group=1)
    application.add_handler(CallbackQueryHandler(confirm_cancel_from_history, pattern="^confirm_cancel_from_history_"), group=1)
    application.add_handler(CallbackQueryHandler(back_to_order_history, pattern="^back_to_order_history$"), group=1)
    application.add_handler(CallbackQueryHandler(noop_handler, pattern="^noop$"), group=1) # Пустышка, чтобы кнопка не "залипала"
    
    # --- ОБРАБОТЧИКИ КЛИЕНТСКОЙ ЧАСТИ ---
    application.add_handler(CommandHandler("d", d), group=1) # Твоя команда для дебага
    application.add_handler(catalog_handler, group=1)
    application.add_handler(reply_cart_handler, group=1)
    application.add_handler(subcategories_handler, group=1)
    application.add_handler(brands_handler, group=1)
    application.add_handler(brand_slider_handler, group=1)
    application.add_handler(all_slider_handler, group=1)
    application.add_handler(brand_slider_nav_handler, group=1)
    application.add_handler(all_slider_nav_handler, group=1)
    application.add_handler(details_handler, group=1)
    application.add_handler(choose_color_handler, group=1)
    application.add_handler(choose_size_handler, group=1)
    application.add_handler(back_to_slider_handler, group=1)
    application.add_handler(back_to_brands_handler, group=1)
    application.add_handler(back_to_main_cat_handler, group=1)
    application.add_handler(add_to_cart_handler, group=1)
    application.add_handler(cart_handler, group=1)
    application.add_handler(cart_back_handler, group=1)
    application.add_handler(cart_plus_handler, group=1)
    application.add_handler(cart_minus_handler, group=1)
    application.add_handler(clear_cart_handler, group=1)
    application.add_handler(payment_confirmation_handler, group=1)
    application.add_handler(checkout_handler, group=1)
    application.add_handler(CallbackQueryHandler(color_photo_pagination, pattern=r"^colorphoto_\d+_\d+_\d+$"), group=1)
    application.add_handler(InlineQueryHandler(inlinequery), group=1)
    application.add_handler(CallbackQueryHandler(cancel_by_client, pattern=r"^cancel_by_client_\d+$"), group=1)
    application.add_handler(CallbackQueryHandler(confirm_cancel, pattern=r"^confirm_cancel_\d+$"), group=1)
    application.add_handler(CallbackQueryHandler(back_to_payment, pattern=r"^back_to_payment_\d+$"), group=1)
    application.add_handler(reply_main_menu_handler, group=1)
    application.add_handler(back_to_main_menu_handler, group=1)


    
    
    # --- Тіркеудің соңы ---

    # --- Веб-серверді баптау ---
    async def health(_: Request) -> PlainTextResponse:
        return PlainTextResponse(content="The bot is running...")

    async def telegram(request: Request) -> Response:
        update_data = await request.json()
        await application.update_queue.put(
            Update.de_json(data=update_data, bot=application.bot)
        )
        return Response(status_code=200)

    webhook_path = "/telegram"
    routes = [
        Route(webhook_path, endpoint=telegram, methods=["POST"]),
        Route("/health", endpoint=health, methods=["GET"]),
    ]

    starlette_app = Starlette(routes=routes)
    web_server = uvicorn.Server(
        config=uvicorn.Config(
            app=starlette_app,
            port=int(os.environ.get("PORT", 8080)),
            host="0.0.0.0",
        )
    )

    # --- Бәрін бірге іске қосу ---
    await application.initialize()
    await application.bot.set_webhook(url=f"https://new-project-test.fly.dev{webhook_path}")
    await asyncio.sleep(2)  # ← дам немного времени, чтобы всё успело подняться
    
    # Боттың "конвейерін" және веб-серверді қатар іске қосамыз
    async with application:
        await application.start()
        await web_server.serve()
        await application.stop()


if __name__ == "__main__":
    asyncio.run(main())
