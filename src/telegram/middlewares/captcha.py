import random
from typing import Any, Awaitable, Callable, Final

from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    TelegramObject,
)
from cachetools import TTLCache
from dishka import AsyncContainer
from loguru import logger

from src.application.common import Notifier, TranslatorRunner
from src.application.dto import MessagePayloadDto, TelegramUserDto
from src.core.constants import CONTAINER_KEY, USER_KEY
from src.core.enums import MiddlewareEventType

from .base import EventTypedMiddleware

# Adaptive friction (spec §8): clean users pass with zero captcha; only users who
# trip the /start-burst heuristic get a one-tap "нажми тунца" challenge. Detection
# is per-user and in-memory (like ThrottlingMiddleware) — short-lived, additive,
# no new storage.
_CAPTCHA_PREFIX: Final[str] = "captcha:"
_TOKEN_OK: Final[str] = "ok"
_TOKEN_NO: Final[str] = "no"

_START_WINDOW: Final[float] = 60.0  # seconds
_START_BURST: Final[int] = 5  # /start presses in the window that trips the flag
_FLAG_TTL: Final[float] = 3600.0  # how long a flagged user stays challenged

_CORRECT_EMOJI: Final[str] = "🐟"
_DECOY_EMOJI: Final[tuple[str, ...]] = ("🦈", "🐙", "🦑", "🐳", "🦀")


class CaptchaMiddleware(EventTypedMiddleware):
    __event_types__ = [MiddlewareEventType.MESSAGE, MiddlewareEventType.CALLBACK_QUERY]

    def __init__(self) -> None:
        super().__init__()
        self._start_count: TTLCache[int, int] = TTLCache(maxsize=10_000, ttl=_START_WINDOW)
        self._flagged: TTLCache[int, bool] = TTLCache(maxsize=10_000, ttl=_FLAG_TTL)
        self._pending: TTLCache[int, bool] = TTLCache(maxsize=10_000, ttl=_FLAG_TTL)

    async def middleware_logic(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        user: TelegramUserDto = data[USER_KEY]
        container: AsyncContainer = data[CONTAINER_KEY]
        tid = user.telegram_id

        # 1) Resolve a captcha tap (verify / retry) — short-circuits the handler.
        if isinstance(event, CallbackQuery) and (event.data or "").startswith(_CAPTCHA_PREFIX):
            await self._handle_captcha_tap(event, container, tid)
            return None

        # 2) A flagged user is held behind the challenge until they pass it.
        if tid in self._flagged:
            if tid not in self._pending:
                await self._send_captcha(user, container)
            return None

        # 3) Trip the flag on a /start burst.
        if self._is_start(event):
            count = self._start_count.get(tid, 0) + 1
            self._start_count[tid] = count
            if count > _START_BURST:
                logger.warning(f"{user.log} flagged for /start burst ({count})")
                self._flagged[tid] = True
                await self._send_captcha(user, container)
                return None

        return await handler(event, data)

    @staticmethod
    def _is_start(event: TelegramObject) -> bool:
        return (
            isinstance(event, Message)
            and event.text is not None
            and event.text.startswith("/start")
        )

    async def _handle_captcha_tap(
        self, event: CallbackQuery, container: AsyncContainer, tid: int
    ) -> None:
        token = (event.data or "")[len(_CAPTCHA_PREFIX):]
        i18n = await container.get(TranslatorRunner)
        if token == _TOKEN_OK:
            self._flagged.pop(tid, None)
            self._pending.pop(tid, None)
            await event.answer(i18n.get("captcha-passed"))
            await self._delete_previous_message(event)
            logger.info(f"Captcha passed for '{tid}'")
        else:
            await event.answer(i18n.get("captcha-retry"), show_alert=True)

    async def _send_captcha(self, user: TelegramUserDto, container: AsyncContainer) -> None:
        notifier = await container.get(Notifier)
        payload = MessagePayloadDto(
            i18n_key="captcha-prompt",
            reply_markup=self._build_keyboard(),
            disable_default_markup=True,
            delete_after=None,
        )
        await notifier.notify_user(user, payload)
        self._pending[user.telegram_id] = True

    @staticmethod
    def _build_keyboard() -> InlineKeyboardMarkup:
        decoys = random.sample(_DECOY_EMOJI, 3)
        buttons = [
            InlineKeyboardButton(text=emoji, callback_data=f"{_CAPTCHA_PREFIX}{_TOKEN_NO}")
            for emoji in decoys
        ]
        buttons.append(
            InlineKeyboardButton(
                text=_CORRECT_EMOJI, callback_data=f"{_CAPTCHA_PREFIX}{_TOKEN_OK}"
            )
        )
        random.shuffle(buttons)
        return InlineKeyboardMarkup(inline_keyboard=[buttons])
