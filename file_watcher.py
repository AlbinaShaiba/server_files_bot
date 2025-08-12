# file_watcher.py
import asyncio
import os
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy import select
from models import FolderSubscription, User
from aiogram import Bot
from config import FILES_ROOT, CHECK_INTERVAL
from datetime import datetime
import logging
from models import async_session 

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger(__name__)


class FileWatcher:
    def __init__(self, bot_token: str):
        self.bot_token = bot_token
        self.bot = Bot(token=bot_token)

    def get_full_path(self, relative_path: str) -> str:
        """Преобразует относительный путь в абсолютный на основе FILES_ROOT"""
        return os.path.join(FILES_ROOT, relative_path)

    def get_folder_mtime_recursive(self, folder_path: str) -> float:
        """
        Возвращает самое свежее время изменения в папке (рекурсивно)
        Если папки нет — возвращает 0.0
        """
        if not os.path.exists(folder_path):
            return 0.0

        latest = 0.0
        try:
            for root, _, files in os.walk(folder_path):
                # Время изменения самой папки
                try:
                    mtime = os.path.getmtime(root)
                    if mtime > latest:
                        latest = mtime
                except OSError:
                    pass

                # Время изменения файлов
                for file in files:
                    file_path = os.path.join(root, file)
                    try:
                        mtime = os.path.getmtime(file_path)
                        if mtime > latest:
                            latest = mtime
                    except OSError:
                        continue
        except Exception as e:
            logger.warning(f"Ошибка при рекурсивной проверке {folder_path}: {e}")
        return latest
    
    async def notify_subscribers(self, sub: FolderSubscription, full_path: str, current_mtime: datetime):
        try:
            async with async_session() as session:
                result = await session.execute(select(User).where(User.id == sub.user_id))
                user = result.scalar_one_or_none()
                if not user:
                    logger.warning(f"Пользователь с ID {sub.user_id} не найден")
                    return

            # Получаем путь относительно FILES_ROOT для отображения
            try:
                rel_path = os.path.relpath(full_path, FILES_ROOT)
                parts = rel_path.split(os.sep)
                project = parts[0] if len(parts) >= 1 else "—"
                stage = parts[1] if len(parts) >= 2 else "—"
                task = os.path.basename(full_path)
            except Exception:
                project = stage = "—"
                task = os.path.basename(full_path)

            message = (
            "🔄 <b>Обнаружено изменение в папке!</b>\n\n"
            f"📌 <code>{task}</code>\n"
            f"📦 Проект: <b>{project}</b>\n"
            f"🔧 Стадия: {stage}\n\n"
            f"🕒 Время изменения: {current_mtime.strftime('%d.%m.%Y %H:%M')}\n"
            f"💬 Вы подписаны на эту папку."
            )

            await self.bot.send_message(
                chat_id=user.tg_id,
                text=message,
                parse_mode="HTML"
            )
            logger.info(f"✅ Уведомление отправлено пользователю {user.tg_id} по папке: {task}")

        except Exception as e:
            logger.error(f"❌ Ошибка при отправке уведомления: {e}")

    async def check_folder_updates(self, session):
        """Проверяет все подписанные папки на изменения"""
        try:
            result = await session.execute(select(FolderSubscription))
            subscriptions = result.scalars().all()

            for sub in subscriptions:
                full_path = self.get_full_path(sub.folder_path)

                # Проверяем, существует ли папка
                if not os.path.exists(full_path):
                    logger.warning(f"Папка не найдена (возможно удалена): {full_path}")
                    continue

                # Получаем самое свежее время изменения
                current_mtime_ts = self.get_folder_mtime_recursive(full_path)
                if current_mtime_ts == 0.0:
                    continue

                current_mtime = datetime.fromtimestamp(current_mtime_ts)

                # Первый запуск — просто сохраняем время
                if sub.last_modified is None:
                    sub.last_modified = current_mtime
                    session.add(sub)
                    await session.commit()
                    logger.info(f"📌 Инициализировано время для: {sub.folder_path}")
                    continue

                # Сравниваем с последним сохранённым временем
                if current_mtime_ts > sub.last_modified.timestamp():
                    logger.info(f"🔥 Изменение обнаружено: {sub.folder_path}")
                    sub.last_modified = current_mtime
                    session.add(sub)
                    await session.commit()
                    await self.notify_subscribers(sub, full_path, current_mtime)

        except Exception as e:
            logger.error(f"❌ Ошибка при проверке обновлений: {e}")

    async def start_monitoring(self):
        """Запуск постоянного мониторинга подписанных папок"""
        from models import async_session  # Импортируем сессию из models
        logger.info("🚀 Мониторинг подписанных папок запущен...")

        while True:
            try:
                async with async_session() as session:
                    await self.check_folder_updates(session)
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
        logger.info("🔌 Сессия бота закрыта")