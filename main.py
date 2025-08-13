import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from config import BOT_TOKEN, FILES_ROOT
from models import init_db
from handlers import router
from middleware import DatabaseMiddleware
from file_watcher import FileWatcher

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)

async def main():
    watcher_task = None
    file_watcher = None
    bot = None
    dp = None

    stop_event = asyncio.Event()

    try:
        os.makedirs(FILES_ROOT, exist_ok=True)
        logger.info(f"📂 Рабочая директория: {FILES_ROOT}")

        await init_db()

        bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
        dp = Dispatcher()

        dp.update.middleware(DatabaseMiddleware())
        dp.include_router(router)

        file_watcher = FileWatcher(BOT_TOKEN)
        watcher_task = asyncio.create_task(file_watcher.start_monitoring())

        logger.info("🤖 Бот запущен")
        logger.info("🔍 Мониторинг файлов активен")

        polling_task = asyncio.create_task(dp.start_polling(bot))

        # Instead of signal handlers, wait on event; KeyboardInterrupt handled below
        await stop_event.wait()

    except KeyboardInterrupt:
        logger.info("🛑 Получен сигнал остановки (Ctrl+C)")
        stop_event.set()

        if dp is not None and bot is not None:
            await dp.stop_polling()

        if watcher_task is not None:
            watcher_task.cancel()
            try:
                await watcher_task
            except asyncio.CancelledError:
                logger.info("✅ Задача мониторинга отменена")

    except Exception as e:
        logger.exception(f"❌ Критическая ошибка при запуске бота: {e}")

    finally:
        logger.info("🛑 Начинается корректное завершение работы...")

        if dp is not None and bot is not None:
            await dp.stop_polling()

        if watcher_task is not None:
            watcher_task.cancel()
            try:
                await watcher_task
            except asyncio.CancelledError:
                logger.info("✅ Задача мониторинга отменена")

        if file_watcher is not None:
            await file_watcher.close()

        if bot is not None:
            await bot.session.close()
            logger.info("🔌 Сессия бота закрыта")

        logger.info("👋 Бот остановлен. До новых встреч!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен вручную")
