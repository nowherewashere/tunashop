from typing import Optional

from pydantic import model_validator

from .base import BaseConfig


class SupportConfig(BaseConfig, env_prefix="SUPPORT_"):
    """Unified support bridge config.

    When enabled, website and bot users chat with an operator through Telegram
    forum topics in a single supergroup: one topic per user. Shipped OFF by default
    (like Stars payouts); until enabled the bot keeps its old ``BOT_SUPPORT_USERNAME``
    contact link and the site widget shows the same fallback.

    Prerequisites when enabling: create a supergroup with Topics on, add the bot as
    admin with "Manage Topics", and disable the bot's group privacy in BotFather so
    it receives operators' messages inside topics.
    """

    enabled: bool = False
    # The forum-enabled operator supergroup (a negative -100... chat id). Required
    # when enabled.
    group_id: Optional[int] = None

    @property
    def is_active(self) -> bool:
        return self.enabled and self.group_id is not None

    @model_validator(mode="after")
    def _validate(self) -> "SupportConfig":
        if self.enabled and self.group_id is None:
            raise ValueError("SUPPORT_GROUP_ID must be set when SUPPORT_ENABLED=true")
        return self
