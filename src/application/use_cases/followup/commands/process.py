from datetime import timedelta

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger

from src.application.common import Interactor, Notifier
from src.application.common.dao import LifecycleFollowupDao, SubscriptionDao, UserDao
from src.application.common.uow import UnitOfWork
from src.application.dto import MessagePayloadDto, SubscriptionDto, UserDto
from src.core.constants import GOTO_PREFIX
from src.core.utils.time import datetime_now
from src.infrastructure.database.models.lifecycle_followup import (
    CHAIN_HABIT,
    CHAIN_TRIAL_ENDING,
    CHAIN_WINBACK,
)

# Global-ish frequency cap (spec §9), matching the onboarding chain's defaults.
_MIN_GAP = timedelta(minutes=180)
_DAILY_CAP = 4

# gt_<Dialog:STATE> targets resolved by routers/extra/goto.py::on_goto.
_GT_PLANS = f"{GOTO_PREFIX}Subscription:PLANS"
_GT_INVITE = f"{GOTO_PREFIX}MainMenu:INVITE"

# Per-chain message copy key.
_COPY: dict[str, str] = {
    CHAIN_HABIT: "event-followup-habit",
    CHAIN_TRIAL_ENDING: "event-followup-trial-ending",
    CHAIN_WINBACK: "event-followup-winback",
}


def _keyboard(chain: str) -> InlineKeyboardMarkup:
    # Button text is the i18n key — the notifier localizes it per recipient
    # (see NotificationService._translate_keyboard_text), like the onboarding chain.
    if chain == CHAIN_HABIT:
        rows = [[InlineKeyboardButton(text="btn-followup.add-device", callback_data=_GT_PLANS)]]
    elif chain == CHAIN_TRIAL_ENDING:
        rows = [
            [
                InlineKeyboardButton(text="btn-followup.subscribe", callback_data=_GT_PLANS),
                InlineKeyboardButton(text="btn-followup.invite", callback_data=_GT_INVITE),
            ]
        ]
    else:  # CHAIN_WINBACK
        rows = [[InlineKeyboardButton(text="btn-followup.return", callback_data=_GT_PLANS)]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def _should_send(chain: str, subscription: SubscriptionDto | None) -> bool:
    """Re-validate live state at send time so we never need per-chain cancel events."""
    active_trial = bool(subscription and subscription.is_trial and subscription.is_active)
    has_access = bool(subscription and subscription.is_active)
    if chain in (CHAIN_HABIT, CHAIN_TRIAL_ENDING):
        return active_trial  # only nudge users still inside an active trial
    if chain == CHAIN_WINBACK:
        return not has_access  # only win back users who are actually churned
    return False


class ProcessDueLifecycleFollowups(Interactor[None, None]):
    """Sweep due lifecycle followups (chains B/C/E) and deliver them.

    Runs from a cron task. Each row is re-validated against the user's current
    subscription state before sending; a stale row (e.g. trial converted, or a
    churned user who returned) is cancelled instead of sent.
    """

    required_permission = None

    def __init__(
        self,
        uow: UnitOfWork,
        followup_dao: LifecycleFollowupDao,
        user_dao: UserDao,
        subscription_dao: SubscriptionDao,
        notifier: Notifier,
    ) -> None:
        self.uow = uow
        self.followup_dao = followup_dao
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
        self.notifier = notifier

    async def _execute(self, actor: UserDto, data: None) -> None:
        now = datetime_now()
        due = await self.followup_dao.get_due(now)
        if not due:
            return

        sent = 0
        async with self.uow:
            for followup in due:
                user = await self.user_dao.get_by_telegram_id(followup.telegram_id)
                if not user:
                    await self.followup_dao.mark_cancelled(followup.id)
                    continue

                # Frequency cap — leave the row pending so it retries later.
                if await self.followup_dao.sent_in_window(followup.telegram_id, now - _MIN_GAP) > 0:
                    continue
                day_count = await self.followup_dao.sent_in_window(
                    followup.telegram_id, now - timedelta(hours=24)
                )
                if day_count >= _DAILY_CAP:
                    continue

                subscription = await self.subscription_dao.get_current(user.id)
                if not _should_send(followup.chain, subscription):
                    await self.followup_dao.mark_cancelled(followup.id)
                    continue

                payload = MessagePayloadDto(
                    i18n_key=_COPY[followup.chain],
                    reply_markup=_keyboard(followup.chain),
                    disable_default_markup=True,
                    delete_after=None,
                )

                try:
                    message = await self.notifier.notify_user(user=user, payload=payload)
                except Exception:  # noqa: BLE001 — one bad row must not abort the sweep
                    logger.exception(
                        f"Lifecycle followup send failed (chain={followup.chain}, "
                        f"step={followup.step}, uid={followup.telegram_id})"
                    )
                    continue

                if message is None:
                    # Undeliverable (blocked bot) — stop every chain for this user.
                    await self.followup_dao.cancel_all_pending(followup.telegram_id)
                    continue

                await self.followup_dao.mark_sent(followup.id, now)
                sent += 1

            await self.uow.commit()

        logger.info(f"Lifecycle followup sweep: due={len(due)} sent={sent}")
