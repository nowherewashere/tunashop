from typing import Any, Awaitable, Callable, cast

from aiogram.enums import ChatType
from aiogram.types import Message, TelegramObject
from loguru import logger

from src.application.dto import TelegramUserDto
from src.core.constants import USER_KEY
from src.core.enums import Command, MiddlewareEventType
from src.telegram.states import Support

from .base import EventTypedMiddleware


class GarbageMiddleware(EventTypedMiddleware):
    __event_types__ = [MiddlewareEventType.MESSAGE]

    async def middleware_logic(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        message = cast(Message, event)
        user: TelegramUserDto = data[USER_KEY]

        # The garbage collector keeps the private-chat dialog UI to a single message.
        # It must never touch the support operator group (deleting would wipe operators'
        # replies), nor the user's messages while they are in the in-bot support chat.
        if message.chat.type != ChatType.PRIVATE or data.get("raw_state") == Support.CHAT.state:
            return await handler(event, data)

        if message.text != f"/{Command.START.value.command}":
            try:
                await message.delete()
                logger.debug(f"Message '{message.content_type}' deleted from {user.log}")
            except Exception as e:
                logger.debug(f"Failed to delete message from {user.log}: '{e}'")

        return await handler(event, data)
