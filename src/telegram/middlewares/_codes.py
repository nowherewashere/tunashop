from typing import Optional

from aiogram.types import Message, TelegramObject
from loguru import logger

from src.core.enums import Deeplink


def _parse_deeplink_code(event: TelegramObject, deeplink: Deeplink) -> Optional[str]:
    if not isinstance(event, Message) or not event.text:
        return None

    parts = event.text.split()
    if len(parts) <= 1:
        return None

    code = parts[1]
    prefix = deeplink.with_underscore
    if code.startswith(prefix):
        raw = code[len(prefix) :]
        logger.debug(f"Parsed '{deeplink.value}' code '{raw}' from deeplink")
        return raw

    return None


def parse_deeplink_payload(event: TelegramObject) -> Optional[str]:
    """The raw ``/start`` argument, whatever deep link it belongs to.

    Used by the gates to park a deep link they are about to swallow — they have no
    business knowing which flow the payload opens, only that one was interrupted.
    """
    if not isinstance(event, Message) or not event.text:
        return None

    parts = event.text.split()
    if len(parts) <= 1 or not parts[0].lower().startswith("/start"):
        return None

    return parts[1]


def parse_referral_code(event: TelegramObject) -> Optional[str]:
    return _parse_deeplink_code(event, Deeplink.REFERRAL)


def parse_ad_link_code(event: TelegramObject) -> Optional[str]:
    return _parse_deeplink_code(event, Deeplink.ADVERTISING)
