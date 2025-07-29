# file_watcher.py
import asyncio
import os
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy import select
from models import FolderSubscription, User
from aiogram import Bot
from config import DATABASE_URL, CHECK_INTERVAL
from datetime import datetime
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class FileWatcher:
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.engine = create_async_engine(DATABASE_URL)
        self.async_session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.bot = Bot(token=bot_token)

    async def check_folder_updates(self):
        """Проверяет изменения в подписанных папках по last_modified"""
        try:
            async with self.async_session() as session:
                result = await session.execute(select(FolderSubscription))
                subscriptions = result.scalars().all()

                for sub in subscriptions:
                    folder_path = sub.folder_path
                    if not os.path.exists(folder_path):
                        continue

                    try:
                        stat = os.stat(folder_path)
                        current_mtime = datetime.fromtimestamp(stat.st_mtime)
                    except Exception as e:
                        logger.warning(f"Не удалось прочитать статус папки {folder_path}: {e}")
                        continue

                    # Если first check — просто сохраним время
                    if sub.last_modified is None:
                        sub.last_modified = current_mtime
                        await session.commit()
                        logger.info(f"Инициализировано last_modified для {folder_path}")
                        continue

                    # Проверяем, изменилась ли папка
                    if current_mtime > sub.last_modified:
                        logger.info(f"Обнаружено изменение в папке: {folder_path}")
                        sub.last_modified = current_mtime
                        await session.commit()  # ← ОБЯЗАТЕЛЬНО СОХРАНЯЕМ
                        await self.notify_subscribers(session, sub, folder_path, current_mtime)

        except Exception as e:
            logger.error(f"Ошибка при проверке обновлений папок: {e}")

    async def notify_subscribers(self, session, sub: FolderSubscription, folder_path: str, current_mtime: datetime):
        """Отправляет уведомление подписчику"""
        try:
            stmt = select(User).where(User.id == sub.user_id)
            result = await session.execute(stmt)
            user = result.scalar_one_or_none()
            if not user:
                return

            folder_name = os.path.basename(folder_path)
            parent_path = os.path.dirname(folder_path)
            task_name = os.path.basename(parent_path)
            stage_name = os.path.basename(os.path.dirname(parent_path))
            order_name = os.path.basename(os.path.dirname(os.path.dirname(parent_path)))

            message = (
                "🔄 <b>Обновление в папке!</b>\n\n"
                f"📁 <code>{folder_name}</code>\n"
                f"📦 Задание: <b>{task_name}</b>\n"
                f"🔧 Стадия: {stage_name}\n"
                f"📋 Заказ: {order_name}\n\n"
                f"🕒 Изменено: {current_mtime.strftime('%d.%m.%Y %H:%M')}"
            )

            await self.bot.send_message(
                chat_id=user.tg_id,
                text=message,
                parse_mode="HTML"
            )
            logger.info(f"✅ Уведомление отправлено пользователю {user.tg_id} о папке {folder_name}")

        except Exception as e:
            logger.error(f"❌ Ошибка отправки уведомления: {e}")

    async def start_monitoring(self):
        """Запуск постоянного мониторинга"""
        logger.info("🚀 Запуск мониторинга подписанных папок...")
        while True:
            try:
                await self.check_folder_updates()
                await asyncio.sleep(CHECK_INTERVAL)
            except asyncio.CancelledError:
                logger.info("🛑 Мониторинг остановлен.")
                break
            except Exception as e:
                logger.error(f"❌ Ошибка в цикле мониторинга: {e}")
                await asyncio.sleep(CHECK_INTERVAL)

    async def close(self):
        """Закрытие ресурсов"""
        await self.bot.session.close()
        await self.engine.dispose()