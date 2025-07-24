import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select
from models import FileInfo, Subscription, User
from aiogram import Bot
from config import DATABASE_URL, CHECK_INTERVAL
from datetime import datetime
import logging

# Настройка логирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FileWatcher:
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.engine = create_async_engine(DATABASE_URL)
        self.async_session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.bot = Bot(token=bot_token)
        
    async def check_file_updates(self):
        """Проверяет обновления файлов и отправляет уведомления"""
        try:
            async with self.async_session() as session:
                # Получаем все файлы из БД
                stmt = select(FileInfo)
                result = await session.execute(stmt)
                db_files = result.scalars().all()
                
                # Проверяем каждый файл
                for db_file in db_files:
                    if os.path.exists(db_file.path):
                        try:
                            # Получаем текущую информацию о файле
                            stat = os.stat(db_file.path)
                            current_modified = datetime.fromtimestamp(stat.st_mtime)
                            current_size = stat.st_size
                            
                            # Проверяем, изменился ли файл
                            if (db_file.last_modified != current_modified or 
                                db_file.size != current_size):
                                
                                # Сохраняем старую дату для уведомления
                                old_modified = db_file.last_modified
                                
                                # Обновляем информацию в БД
                                db_file.last_modified = current_modified
                                db_file.size = current_size
                                
                                # Отправляем уведомления подписчикам
                                await self.notify_subscribers(session, db_file, old_modified)
                                
                        except OSError as e:
                            logger.warning(f"Ошибка при проверке файла {db_file.path}: {e}")
                
                # Сохраняем изменения
                await session.commit()
                
        except Exception as e:
            logger.error(f"Ошибка при проверке обновлений файлов: {e}")
    
    async def notify_subscribers(self, session, file_info: FileInfo, old_modified: datetime):
        """Отправляет уведомления подписчикам об изменении файла"""
        try:
            # Получаем подписчиков файла
            stmt = select(Subscription).where(Subscription.file_path == file_info.path)
            result = await session.execute(stmt)
            subscriptions = result.scalars().all()
            
            # Получаем информацию о пользователях
            user_ids = [sub.user_id for sub in subscriptions]
            if not user_ids:
                return
                
            stmt = select(User).where(User.id.in_(user_ids))
            result = await session.execute(stmt)
            users = result.scalars().all()
            users_dict = {user.id: user.tg_id for user in users}
            
            # Отправляем уведомления
            for subscription in subscriptions:
                tg_user_id = users_dict.get(subscription.user_id)
                if tg_user_id:
                    try:
                        message = (
                            f"🔔 Обновление файла!\n\n"
                            f"📁 Файл: <code>{file_info.filename}</code>\n"
                            f"🔢 Заказ: {file_info.order}\n"
                            f"🏗 Стадия: {file_info.stage}\n"
                            f"📝 Задание: {file_info.task}\n\n"
                            f"🕒 Время изменения: {file_info.last_modified.strftime('%d.%m.%Y %H:%M')}"
                        )
                        await self.bot.send_message(chat_id=tg_user_id, text=message)
                    except Exception as e:
                        logger.error(f"Ошибка отправки сообщения пользователю {tg_user_id}: {e}")
                        
        except Exception as e:
            logger.error(f"Ошибка при отправке уведомлений: {e}")
    
    async def start_monitoring(self):
        """Запускает мониторинг файлов"""
        logger.info("🚀 Запуск мониторинга файлов...")
        while True:
            try:
                await self.check_file_updates()
                await asyncio.sleep(CHECK_INTERVAL)
            except asyncio.CancelledError:
                logger.info("🛑 Мониторинг файлов остановлен")
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле мониторинга: {e}")
                await asyncio.sleep(CHECK_INTERVAL)
    
    async def close(self):
        """Закрывает соединения"""
        await self.bot.session.close()
        await self.engine.dispose()