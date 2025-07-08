import logging
import os
import asyncio
from telegram import Update
from telegram.ext import Application, ContextTypes, CommandHandler

# --- Веб-сервер ---
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route

# --- Ваши импорты ---
from configs import BOT_TOKEN

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

# === ТЕСТОВЫЙ ОБРАБОТЧИК ПРЯМО ЗДЕСЬ ===
async def start_diagnostic(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправляет тестовое сообщение в ответ на /start."""
    logging.info("--- !!! FINAL DIAGNOSTIC: /start handler was called! Attempting to reply...")
    try:
        await update.message.reply_text("ПОБЕДА! Бот отвечает!")
        logging.info("--- !!! FINAL DIAGNOSTIC: Reply sent successfully!")
    except Exception as e:
        logging.error(f"--- !!! FINAL DIAGNOSTIC: FAILED TO SEND REPLY! Error: {e}", exc_info=True)

async def main() -> None:
    """Основная асинхронная функция для настройки и запуска бота."""
    
    # Запускаем без сохранения состояния, чтобы исключить ошибки
    application = Application.builder().token(BOT_TOKEN).build()

    # --- РЕГИСТРИРУЕМ ТОЛЬКО ОДИН ТЕСТОВЫЙ ОБРАБОТЧИК ---
    application.add_handler(CommandHandler("start", start_diagnostic))
    
    await application.initialize()

    # --- Настройка веб-сервера (без изменений) ---
    async def health(_: Request) -> PlainTextResponse:
        return PlainTextResponse(content="The bot is running in final diagnostic mode...")

    async def telegram(request: Request) -> Response:
        logging.info("Received an update from Telegram, passing to the final diagnostic handler...")
        try:
            # === ЖАҢА ЖОЛ: КЕЛГЕН ДЕРЕКТЕРДІ ЛОГҚА ШЫҒАРУ ===
            update_data = await request.json()
            logging.info(f"TELEGRAM PAYLOAD: {update_data}") # <-- ОСЫ ЖОЛ МӘСЕЛЕНІ КӨРСЕТЕДІ

            await application.process_update(update_data)
        except Exception as e:
            logging.error(f"Error processing update: {e}", exc_info=True)
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

    # --- Запускаем все вместе (без изменений) ---
    async with application:
        await application.bot.set_webhook(
            url=f"https://new-project-test.fly.dev{webhook_path}"
        )
        logging.info("Final diagnostic application started successfully!")
        await web_server.serve()


if __name__ == "__main__":
    asyncio.run(main())
