from datetime import timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger

from src.application.common import BotService, Interactor, Notifier
from src.application.common.dao import OnboardingNudgeDao, SettingsDao, UserDao
from src.application.common.uow import UnitOfWork
from src.application.dto import MessagePayloadDto, UserDto
from src.core.config import AppConfig
from src.core.constants import GOTO_PREFIX, ONBOARDING_GOTO_HELP, ONBOARDING_GOTO_TARGET
from src.core.utils.time import datetime_now

# Reuse the existing goto pipeline (see routers/extra/goto.py) to open the funnel
# from a plain notification button — no dialog context needed at send time.
_GOTO_ENTRY = f"{GOTO_PREFIX}{ONBOARDING_GOTO_TARGET}"  # funnel start (O0)
_GOTO_HELP = f"{GOTO_PREFIX}{ONBOARDING_GOTO_HELP}"  # fail branch

# Per-step nudge copy ported 1:1 from the source A-chain (30m / 3h / 24h). Button
# text is the i18n key — the notifier resolves it per recipient locale (see
# NotificationService._translate_keyboard_text).
_MAX_NUDGE_STEP = 3


def _nudge_step_index(step: str) -> int:
    """`nudge_{N}` -> N (1-based), clamped to the defined steps."""
    try:
        index = int(step.rsplit("_", 1)[-1])
    except ValueError:
        return 1
    return min(max(index, 1), _MAX_NUDGE_STEP)


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
        bot_service: BotService,
        config: AppConfig,
    ) -> None:
        self.uow = uow
        self.nudge_dao = nudge_dao
        self.user_dao = user_dao
        self.settings_dao = settings_dao
        self.notifier = notifier
        self.bot_service = bot_service
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
        support_url = self.bot_service.get_support_url()
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

                index = _nudge_step_index(nudge.step)
                payload = MessagePayloadDto(
                    i18n_key=f"event-onboarding-nudge-{index}",
                    reply_markup=self._build_keyboard(index, support_url),
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

    def _build_keyboard(self, index: int, support_url: str) -> InlineKeyboardMarkup:
        # Buttons mirror the source A-chain per step. Text is the i18n key (the
        # notifier localizes it); "Помощь" is a support URL, the rest reopen the
        # funnel via the goto pipeline (entry or the fail branch).
        if index <= 1:
            row = [
                InlineKeyboardButton(
                    text="btn-onboarding.nudge-continue", callback_data=_GOTO_ENTRY
                ),
                InlineKeyboardButton(
                    text="btn-onboarding.nudge-fail", callback_data=_GOTO_HELP
                ),
            ]
        elif index == 2:
            row = [
                InlineKeyboardButton(
                    text="btn-onboarding.nudge-open-happ", callback_data=_GOTO_ENTRY
                ),
                InlineKeyboardButton(text="btn-onboarding.nudge-help", url=support_url),
            ]
        else:
            row = [
                InlineKeyboardButton(
                    text="btn-onboarding.connect", callback_data=_GOTO_ENTRY
                ),
            ]
        return InlineKeyboardMarkup(inline_keyboard=[row])
