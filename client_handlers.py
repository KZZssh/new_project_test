import logging
from telegram import Update
from telegram.ext import ContextTypes, CommandHandler

# Эта функция будет единственной, которую мы тестируем
async def start_diagnostic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет тестовое сообщение в ответ на /start."""
    user = update.effective_user
    logging.info(f"--- DIAGNOSTIC: /start called by {user.id}. Attempting to reply...")
    try:
        await update.message.reply_text("Диагностика работает! Сервер отвечает.")
        logging.info("--- DIAGNOSTIC: Reply sent successfully!")
    except Exception as e:
        logging.error(f"--- DIAGNOSTIC: FAILED TO SEND REPLY! Error: {e}", exc_info=True)

# Мы создаем только один обработчик для теста
start_handler = CommandHandler("start", start_diagnostic)
