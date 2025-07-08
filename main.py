import logging
import os
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, InlineQueryHandler, MessageHandler, filters, ConversationHandler
from configs import BOT_TOKEN
from telegram import Update 
from telegram.ext import ContextTypes , PicklePersistence

# --- Импорт всех твоих обработчиков --- (оставлено без изменений)
from admin_handlers import (
    add_product_text_handler, add_product_callback_handler, add_product_media_handler, finish_media,
    edit_product_handler, report_handler, admin_decision_handler, cancel_dialog, cat_manage_handler,
    subcat_manage_handler, subcat_rename_conv, brand_manage_handler, brand_rename_conv,
    orders_report_handler, orders_report_period_handler, admin_menu_convhandler, nazad_to_admin_menu_handler,
    get_name, get_new_category_name, get_new_subcategory_name, get_new_brand_name, get_description,
    get_new_size_name, get_new_color_name, get_variant_price, get_variant_quantity,
    handle_done_command, update_order_status_admin, order_history_handler, order_filter_handler,
    cancel_from_history_handler, confirm_cancel_from_history, back_to_order_history,
    pagination_handler, handle_admin_rejection_after_confirm 
)

from client_handlers import (
    start_handler, catalog_handler, reply_cart_handler, subcategories_handler, brands_handler,
    brand_slider_handler, all_slider_handler, brand_slider_nav_handler, all_slider_nav_handler,
    details_handler, choose_color_handler, choose_size_handler, back_to_slider_handler,
    add_to_cart_handler, cart_handler, cart_plus_handler, cart_minus_handler, clear_cart_handler,
    payment_confirmation_handler, checkout_handler, back_to_brands_handler, back_to_main_cat_handler,
    color_photo_pagination, inlinequery, help_handler, reply_main_menu_handler,
    cancel_by_client, confirm_cancel, back_to_payment, back_to_main_menu_handler
)

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)


async def debug_all_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("⚠️ [DEBUG CALLBACK GLOBAL]:", update.callback_query.data)


def main():
    persistence = PicklePersistence(filepath="bot_data.pkl")

    application = Application.builder().token(BOT_TOKEN).persistence(persistence).build()

    # Все  add_handler'ы без изменений:
    application.add_handler(CallbackQueryHandler(debug_all_callback), group=999)
    application.add_handler(CommandHandler("done", handle_done_command))
    application.add_handler(start_handler)
    application.add_handler(catalog_handler)
    application.add_handler(reply_cart_handler)
    application.add_handler(subcategories_handler)
    application.add_handler(brands_handler)
    application.add_handler(brand_slider_handler)
    application.add_handler(all_slider_handler)
    application.add_handler(brand_slider_nav_handler)
    application.add_handler(all_slider_nav_handler)
    application.add_handler(details_handler)
    application.add_handler(choose_color_handler)
    application.add_handler(choose_size_handler)
    application.add_handler(back_to_slider_handler)
    application.add_handler(back_to_brands_handler)
    application.add_handler(back_to_main_cat_handler)
    application.add_handler(add_to_cart_handler)
    application.add_handler(cart_handler)
    application.add_handler(cart_plus_handler)
    application.add_handler(cart_minus_handler)
    application.add_handler(clear_cart_handler)
    application.add_handler(payment_confirmation_handler)
    application.add_handler(checkout_handler)
    
    application.add_handler(CallbackQueryHandler(color_photo_pagination, pattern=r"^colorphoto_\d+_\d+_\d+$"))
    application.add_handler(InlineQueryHandler(inlinequery))
    application.add_handler(CallbackQueryHandler(cancel_by_client, pattern=r"^cancel_by_client_\d+$"))
    application.add_handler(CallbackQueryHandler(confirm_cancel, pattern=r"^confirm_cancel_\d+$"))
    application.add_handler(CallbackQueryHandler(back_to_payment, pattern=r"^back_to_payment_\d+$"))
    application.add_handler(help_handler)
    application.add_handler(reply_main_menu_handler)
    application.add_handler(back_to_main_menu_handler)

    application.add_handler(brand_manage_handler)
    application.add_handler(brand_rename_conv)
    application.add_handler(admin_menu_convhandler)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, add_product_text_handler), group=3)
    application.add_handler(CallbackQueryHandler(
        add_product_callback_handler,
        pattern=r"^(add_cat_\d+|add_cat_new|add_subcat_\d+|add_subcat_new|add_brand_\d+|add_brand_new|add_size_\d+|add_size_new|add_color_\d+|add_color_new|add_more_variants|finish_add_product)$"
    ), group=3)
    

    application.add_handler(CallbackQueryHandler(update_order_status_admin, pattern=r"^status_(preparing|shipped|delivered)_\d+$"))
    application.add_handler(CallbackQueryHandler(order_history_handler, pattern="^order_history$"))
    application.add_handler(CallbackQueryHandler(order_filter_handler, pattern="^order_filter_"))
    application.add_handler(CallbackQueryHandler(pagination_handler, pattern="^page_"))
    application.add_handler(CallbackQueryHandler(cancel_from_history_handler, pattern="^cancel_from_history_"))
    application.add_handler(CallbackQueryHandler(handle_admin_rejection_after_confirm, pattern=r"^admin_reject_after_confirm_\d+$"))
    application.add_handler(CallbackQueryHandler(confirm_cancel_from_history, pattern="^confirm_cancel_from_history_"))
    application.add_handler(CallbackQueryHandler(back_to_order_history, pattern="^back_to_order_history$"))
    application.add_handler(MessageHandler(filters.PHOTO | filters.VIDEO, add_product_media_handler), group=3)
    application.add_handler(edit_product_handler)
    application.add_handler(cat_manage_handler)
    application.add_handler(subcat_manage_handler)
    application.add_handler(subcat_rename_conv)
    application.add_handler(report_handler)
    application.add_handler(orders_report_handler)
    application.add_handler(orders_report_period_handler)
    application.add_handler(admin_decision_handler)
    application.add_handler(MessageHandler(filters.COMMAND, cancel_dialog))
    application.add_handler(nazad_to_admin_menu_handler)

    

 
    persistence = PicklePersistence(filepath="bot_data.pkl")  # ✅ сохранение состояния

    
    # --- add_handler блок оставляем без изменений ---

    logging.info("Bot started. Press Ctrl+C to stop.")

    port = int(os.environ.get("PORT", 8080))
    app_url = f"https://new-project-test.fly.dev/{BOT_TOKEN}"

    application.run_webhook(
        listen="0.0.0.0",
        port=port,
        webhook_url=app_url
    )
        



if __name__ == "__main__":
    main()
