import logging
import os
import asyncio
from telegram.ext import Application

# --- Веб-сервер ---
import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response
from starlette.routing import Route

# --- Ваши импорты ---
from configs import BOT_TOKEN
# --- ВАЖНО: ИМПОРТИРУЕМ ТОЛЬКО ОДИН ОБРАБОТЧИК ДЛЯ ТЕСТА ---
from client_handlers import start_handler 

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)

async def main() -> None:
    """Основная асинхронная функция для настройки и запуска бота."""
    
    # Запускаем без сохранения состояния, чтобы исключить ошибки
    application = Application.builder().token(BOT_TOKEN).build()

    # --- РЕГИСТРИРУЕМ ТОЛЬКО START_HANDLER ---
    logging.info("Registering ONLY the diagnostic start_handler...")
    application.add_handler(start_handler)
    
    await application.initialize()

    # --- Настройка веб-сервера (без изменений) ---
    async def health(_: Request) -> PlainTextResponse:
        return PlainTextResponse(content="The bot is running in diagnostic mode...")

    async def telegram(request: Request) -> Response:
        logging.info("Received an update from Telegram, passing to diagnostic handler...")
        try:
            await application.process_update(await request.json())
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
        logging.info("Diagnostic application started successfully!")
        await web_server.serve()


if __name__ == "__main__":
    asyncio.run(main())
