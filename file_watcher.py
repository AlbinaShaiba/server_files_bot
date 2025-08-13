import asyncio
import os
from sqlalchemy import select
from models import FolderSubscription, User, async_session
from aiogram import Bot
from config import FILES_ROOT, CHECK_INTERVAL
from datetime import datetime, timedelta
import logging


DISPLAY_TIME_OFFSET_MINUTES = 60

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
        """Конструирует абсолютный путь из относительного (относительно FILES_ROOT)."""
        return os.path.join(FILES_ROOT, relative_path)

    def get_folder_mtime_recursive(self, folder_path: str) -> float:
        """
        Рекурсивно возвращает самое свежее время изменения в папке.
        Если папки нет — возвращает 0.0.
        """
        if not os.path.exists(folder_path):
            return 0.0
        latest = 0.0
        try:
            for root, _, files in os.walk(folder_path):
                try:
                    mtime = os.path.getmtime(root)
                    if mtime > latest:
                        latest = mtime
                except OSError:
                    pass
                for file in files:
                    try:
                        mtime = os.path.getmtime(os.path.join(root, file))
                        if mtime > latest:
                            latest = mtime
                    except OSError:
                        pass
        except Exception as e:
            logger.warning(f"Ошибка при сканировании {folder_path}: {e}")
        return latest

    async def notify_subscribers(self, sub: FolderSubscription, changed_data_path: str, current_mtime: datetime):
        """
        Отправляет уведомление подписчику о изменении в конкретной папке Data.
        """
        try:
            async with async_session() as session:
                result = await session.execute(select(User).where(User.id == sub.user_id))
                user = result.scalar_one_or_none()
                if not user:
                    logger.warning(f"Пользователь с ID {sub.user_id} не найден")
                    return

            # Папка "Задание", на которую подписан пользователь (относительно FILES_ROOT)
            task_relative = sub.folder_path                          # например: "355/РД/Задание от КЖ"
            task_name = os.path.basename(task_relative)              # например: "Задание от КЖ"

            # Путь до изменившейся .rvt-папки БЕЗ "Data"
            rel_path = os.path.relpath(changed_data_path, FILES_ROOT)  # ".../.rvt/Data"
            rvt_path = os.path.dirname(rel_path)                        # убираем "Data": ".../.rvt"

            # Время для отображения (со сдвигом), в БД/логах остаётся исходное
            display_time = current_mtime + timedelta(minutes=DISPLAY_TIME_OFFSET_MINUTES)

            message = (
                "🔄 <b>Обнаружено изменение в подписанной папке!</b>\n\n"
                f"📂 Подписка: <b>{task_name}</b>\n"
                f"📌 Путь: <code>{rvt_path}</code>\n"
                f"🕒 Время изменения: {display_time.strftime('%d.%m.%Y %H:%M')}\n"
                f"💬 Вы подписаны на это задание."
            )

            await self.bot.send_message(
                chat_id=user.tg_id,
                text=message,
                parse_mode="HTML"
            )
            logger.info(f"✅ Уведомление отправлено {user.tg_id} ({task_relative})")

        except Exception as e:
            logger.error(f"Ошибка при отправке уведомления: {e}")


    async def check_folder_updates(self, session):
        """
        Для каждой подписанной папки 'Задание' проверяет все подпапки (например 1.rvt, 2.rvt, ...)
        и ищет в них папку 'Data'. Если в какой-то Data есть изменения — уведомляет подписчика.
        """
        try:
            result = await session.execute(select(FolderSubscription))
            subscriptions = result.scalars().all()

            for sub in subscriptions:
                task_full_path = self.get_full_path(sub.folder_path)  # Путь до папки Задание

                if not os.path.exists(task_full_path):
                    logger.warning(f"Папка задания не найдена: {task_full_path}")
                    continue

                subfolders = [name for name in os.listdir(task_full_path)
                              if os.path.isdir(os.path.join(task_full_path, name))]

                latest_mtime_ts = 0.0
                changed_data_folder = None

                for subfolder in subfolders:
                    data_folder_path = os.path.join(task_full_path, subfolder, "Data")
                    if not os.path.exists(data_folder_path) or not os.path.isdir(data_folder_path):
                        continue

                    current_mtime_ts = self.get_folder_mtime_recursive(data_folder_path)
                    if current_mtime_ts > latest_mtime_ts:
                        latest_mtime_ts = current_mtime_ts
                        changed_data_folder = data_folder_path

                if latest_mtime_ts == 0.0:
                    continue

                current_mtime = datetime.fromtimestamp(latest_mtime_ts)

                if sub.last_modified is None:
                    sub.last_modified = current_mtime
                    session.add(sub)
                    await session.commit()
                    logger.info(f"📌 Инициализация времени изменения для {sub.folder_path}")
                    continue

                # Сравнение с точностью до секунды
                if int(latest_mtime_ts) > int(sub.last_modified.timestamp()):
                    logger.info(f"🔥 Обнаружено изменение в Data: {changed_data_folder}")
                    sub.last_modified = current_mtime
                    session.add(sub)
                    await session.commit()
                    await self.notify_subscribers(sub, changed_data_folder, current_mtime)

        except Exception as e:
            logger.error(f"Ошибка при проверке обновлений Data: {e}")

    async def start_monitoring(self):
        """Периодически проверяет все подписки."""
        logger.info("🚀 Мониторинг подписок запущен...")
        while True:
            try:
                async with async_session() as session:
                    await self.check_folder_updates(session)
                await asyncio.sleep(CHECK_INTERVAL)
            except asyncio.CancelledError:
                logger.info("🛑 Мониторинг остановлен.")
                break
            except Exception as e:
                logger.error(f"Ошибка в цикле мониторинга: {e}")
                await asyncio.sleep(CHECK_INTERVAL)

    async def close(self):
        """Закрывает ресурсы."""
        await self.bot.session.close()
        logger.info("🔌 Сессия бота закрыта")
