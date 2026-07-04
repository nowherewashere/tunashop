from datetime import timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger

from src.application.common import Interactor, Notifier, TranslatorHub
from src.application.common.dao import OnboardingNudgeDao, SettingsDao, UserDao
from src.application.common.uow import UnitOfWork
from src.application.dto import MessagePayloadDto, UserDto
from src.core.config import AppConfig
from src.core.constants import GOTO_PREFIX, ONBOARDING_GOTO_TARGET
from src.core.enums import Locale
from src.core.utils.time import datetime_now

# Reuse the existing goto pipeline (see routers/extra/goto.py) to open the funnel
# from a plain notification button — no dialog context needed at send time.
_NUDGE_CALLBACK = f"{GOTO_PREFIX}{ONBOARDING_GOTO_TARGET}"

_NUDGE_MESSAGE_KEY = "event-onboarding-nudge"
_NUDGE_BUTTON_KEY = "btn-onboarding.nudge-open"


class ProcessDueOnboardingNudges(Interactor[None, None]):
    """Sweep due nudge rows and deliver them, re-validating live state per row.

    Runs from a cron task. Skipping (frequency cap) leaves a row pending to retry;
    completion or a block cancels the whole chain for the user.
    """

    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        nudge_dao: OnboardingNudgeDao,
        user_dao: UserDao,
        settings_dao: SettingsDao,
        notifier: Notifier,
        translator_hub: TranslatorHub,
        config: AppConfig,
    ) -> None:
        self.uow = uow
        self.nudge_dao = nudge_dao
        self.user_dao = user_dao
        self.settings_dao = settings_dao
        self.notifier = notifier
        self.translator_hub = translator_hub
        self.config = config

    async def _execute(self, actor: UserDto, data: None) -> None:
        settings = await self.settings_dao.get()
        if not settings.extra.onboarding_enabled:
            # Feature turned off by admin: hold the queue, don't nudge into a hidden flow.
            return

        now = datetime_now()
        due = await self.nudge_dao.get_due(now)
        if not due:
            return

        min_gap = timedelta(minutes=self.config.onboarding.nudge_min_gap_minutes)
        daily_cap = self.config.onboarding.nudge_daily_cap
        sent = 0

        async with self.uow:
            for nudge in due:
                user = await self.user_dao.get_by_telegram_id(nudge.telegram_id)
                if not user:
                    await self.nudge_dao.mark_cancelled(nudge.id)
                    continue

                # Frequency cap — leave the row pending so it retries once the window frees.
                if await self.nudge_dao.sent_in_window(nudge.telegram_id, now - min_gap) > 0:
                    continue
                day_count = await self.nudge_dao.sent_in_window(
                    nudge.telegram_id, now - timedelta(hours=24)
                )
                if day_count >= daily_cap:
                    continue

                payload = MessagePayloadDto(
                    i18n_key=_NUDGE_MESSAGE_KEY,
                    reply_markup=self._build_keyboard(user.language),
                    disable_default_markup=True,
                    delete_after=None,
                )

                try:
                    message = await self.notifier.notify_user(user=user, payload=payload)
                except Exception:  # noqa: BLE001 — one bad row must not abort the sweep
                    logger.exception(
                        f"Onboarding nudge send failed (step={nudge.step}, "
                        f"uid={nudge.telegram_id})"
                    )
                    continue

                if message is None:
                    # Undeliverable (e.g. the user blocked the bot) — stop the chain.
                    await self.nudge_dao.cancel_pending(nudge.telegram_id)
                    continue

                await self.nudge_dao.mark_sent(nudge.id, now)
                sent += 1

            await self.uow.commit()

        logger.info(f"Onboarding nudge sweep: due={len(due)} sent={sent}")

    def _build_keyboard(self, locale: Locale) -> InlineKeyboardMarkup:
        i18n = self.translator_hub.get_translator_by_locale(locale)
        button = InlineKeyboardButton(
            text=i18n.get(_NUDGE_BUTTON_KEY),
            callback_data=_NUDGE_CALLBACK,
        )
        return InlineKeyboardMarkup(inline_keyboard=[[button]])
