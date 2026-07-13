from aiogram.filters import BaseFilter
from aiogram.types import Message

from src.core.config import AppConfig


class SupportGroupFilter(BaseFilter):
    """Allow messages from the configured support operator supergroup.

    The global message filter otherwise permits only private chats (PrivateFilter),
    which would silently drop every operator reply sent inside a forum topic. This
    opens exactly one exception — the configured support group — so those messages
    reach the support router. A no-op when support is disabled.
    """

    async def __call__(self, event: Message, config: AppConfig) -> bool:
        support = config.support
        return support.is_active and event.chat.id == support.group_id
