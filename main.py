# main.py
import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from config import BOT_TOKEN, FILES_ROOT
from models import init_db, async_session
from handlers import router
from middleware import DatabaseMiddleware
from file_watcher import FileWatcher

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


async def main():
    # Объявляем переменные заранее
    watcher_task = None
    file_watcher = None
    bot = None
    dp = None

    try:
        # Создаём рабочую директорию
        os.makedirs(FILES_ROOT, exist_ok=True)
        logger.info(f"📂 Рабочая директория: {FILES_ROOT}")

        # Инициализация базы данных
        await init_db()

        # Инициализация бота
        bot = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        dp = Dispatcher()

        # Подключаем middleware и роутеры
        dp.update.middleware(DatabaseMiddleware())
        dp.include_router(router)

        # Запуск мониторинга изменений в папках
        file_watcher = FileWatcher(BOT_TOKEN)
        watcher_task = asyncio.create_task(file_watcher.start_monitoring())

        logger.info("🤖 Бот запущен")
        logger.info("🔍 Мониторинг файлов активен")

        # Запуск polling
        await dp.start_polling(bot)

    except KeyboardInterrupt:
        logger.info("🛑 Получен сигнал остановки (Ctrl+C)")
    except Exception as e:
        logger.exception(f"❌ Критическая ошибка при запуске бота: {e}")
    finally:
        logger.info("🛑 Начинается корректное завершение работы...")

        # Останавливаем polling
        if dp is not None and bot is not None:
            await dp.stop_polling()

        # Отменяем задачу мониторинга
        if watcher_task is not None:
            watcher_task.cancel()
            try:
                await watcher_task
            except asyncio.CancelledError:
                logger.info("✅ Задача мониторинга отменена")

        # Закрываем ресурсы file_watcher
        if file_watcher is not None:
            await file_watcher.close()

        # Закрываем сессию бота
        if bot is not None:
            await bot.session.close()
            logger.info("🔌 Сессия бота закрыта")

        # Опционально: закрыть движок SQLAlchemy (если нужно)
        # from models import engine
        # await engine.dispose()
        # logger.info("💾 Движок SQLAlchemy остановлен")

        logger.info("👋 Бот остановлен. До новых встреч!")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен вручную")