from typing import Any, Awaitable, Callable, Dict
from aiogram import BaseMiddleware
from aiogram.types import TelegramObject
from models import async_session

class DatabaseMiddleware(BaseMiddleware):
    async def __call__(
        self,
        handler: Callable[[TelegramObject, Dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: Dict[str, Any]
    ) -> Any:
        # Создаем новую сессию для каждого запроса
        async with async_session() as session:
            # Добавляем сессию в данные, доступные хендлерам
            data["session"] = session
            try:
                # Вызываем следующий обработчик
                result = await handler(event, data)
                return result
            except Exception as e:
                # Откатываем изменения при ошибке
                await session.rollback()
                raise e