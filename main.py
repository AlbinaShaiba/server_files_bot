import asyncio
import logging
import os
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from config import BOT_TOKEN, FILES_ROOT
from models import init_db
from handlers import get_handlers_router
from middleware import DatabaseMiddleware
from file_watcher import FileWatcher

# Настройка логирования
logging.basicConfig(level=logging.INFO)

async def main():
    try:
        # Создаем директорию для файлов если её нет
        os.makedirs(FILES_ROOT, exist_ok=True)
        print(f"📂 Рабочая директория: {FILES_ROOT}")
        
        # Инициализация базы данных SQLite
        await init_db()
        
        # Создание бота и диспетчера
        bot = Bot(
            token=BOT_TOKEN,
            default=DefaultBotProperties(parse_mode=ParseMode.HTML)
        )
        dp = Dispatcher()
        
        # Регистрация middleware
        dp.update.middleware(DatabaseMiddleware())
        
        # Регистрация роутеров
        dp.include_router(get_handlers_router())
        
        # Создание file watcher
        file_watcher = FileWatcher(BOT_TOKEN)
        
        # Запуск мониторинга в отдельной задаче
        watcher_task = asyncio.create_task(file_watcher.start_monitoring())
        
        print("🤖 Бот запущен")
        print("🔍 Мониторинг файлов активен")
        
        # Запуск бота
        await dp.start_polling(bot)
        
    except Exception as e:
        print(f"❌ Ошибка при запуске бота: {e}")
        logging.error(f"Ошибка при запуске бота: {e}")
    finally:
        # Остановка мониторинга
        if 'watcher_task' in locals():
            watcher_task.cancel()
            try:
                await watcher_task
            except asyncio.CancelledError:
                pass
        
        # Закрытие соединений
        if 'file_watcher' in locals():
            await file_watcher.close()
        if 'bot' in locals():
            await bot.session.close()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("🛑 Бот остановлен")