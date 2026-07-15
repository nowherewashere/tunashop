import base64
from datetime import timedelta
from pathlib import Path
from typing import Optional

from aiogram.enums import ButtonStyle
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
from loguru import logger

from src.application.common import BotService, Interactor, Notifier
from src.application.common.dao import (
    OnboardingNudgeDao,
    SettingsDao,
    SubscriptionDao,
    UserDao,
)
from src.application.common.uow import UnitOfWork
from src.application.dto import MediaDescriptorDto, MessagePayloadDto, UserDto
from src.core.config import AppConfig
from src.core.constants import API_V1, GOTO_PREFIX, ONBOARDING_GOTO_HELP, ONBOARDING_GOTO_TARGET
from src.core.enums import BannerFormat, BannerName, MediaType
from src.core.utils.time import datetime_now

# Reuse the existing goto pipeline (see routers/extra/goto.py) to open the funnel
# from a plain notification button — no dialog context needed at send time.
_GOTO_ENTRY = f"{GOTO_PREFIX}{ONBOARDING_GOTO_TARGET}"  # funnel start (O0)
_GOTO_HELP = f"{GOTO_PREFIX}{ONBOARDING_GOTO_HELP}"  # fail branch

# Per-step nudge copy ported 1:1 from the source A-chain (30m / 3h / 24h). Button
# text is the i18n key — the notifier resolves it per recipient locale (see
# NotificationService._translate_keyboard_text).
_MAX_NUDGE_STEP = 3

# The card banner (spec fix #11) rides on the first nudge. Step 2 swaps its primary
# button to a direct "Подключиться" deep link into Happ.
_BANNER_STEP = 1
_FOLLOWUP_A_STEP = 2


def _nudge_step_index(step: str) -> int:
    """`nudge_{N}` -> N (1-based), clamped to the defined steps."""
    try:
        index = int(step.rsplit("_", 1)[-1])
    except ValueError:
        return 1
    return min(max(index, 1), _MAX_NUDGE_STEP)


def _happ_open_url(domain: str, sub_url: str) -> str:
    """HTTPS bouncer URL that redirects to ``happ://add/<url>`` (see connect.py).

    Fork-local copy of the onboarding getter helper so the application layer stays
    free of any presentation-layer import. Empty ⇒ no direct-connect button.
    """
    if not domain or not sub_url:
        return ""
    payload = base64.urlsafe_b64encode(sub_url.encode()).decode()
    return f"https://{domain}{API_V1}/connect/happ/{payload}"


def _resolve_banner_path(config: AppConfig, name: BannerName) -> Optional[Path]:
    """Locate a banner image for `name`, falling back to the global default.

    Self-contained (fork-local) to keep the application layer independent of the
    telegram Banner widget; mirrors its lookup order for the dirs we ship.
    """
    locale = config.default_locale
    targets: list[tuple[Path, BannerName]] = []
    for directory in (config.banners_dir, config.default_banners_dir):
        targets.append((directory / locale, name))
        targets.append((directory / locale, BannerName.DEFAULT))
        targets.append((directory, BannerName.DEFAULT))
    for directory, banner_name in targets:
        if not directory.exists():
            continue
        for banner_format in BannerFormat:
            candidate = directory / f"{banner_name}.{banner_format}"
            if candidate.exists():
                return candidate
    return None


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
        subscription_dao: SubscriptionDao,
        settings_dao: SettingsDao,
        notifier: Notifier,
        bot_service: BotService,
        config: AppConfig,
    ) -> None:
        self.uow = uow
        self.nudge_dao = nudge_dao
        self.user_dao = user_dao
        self.subscription_dao = subscription_dao
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

                # Step 1 carries the card banner (spec fix #11); step 2 carries a direct
                # "Подключиться" deep link into Happ. Other steps keep the funnel entry.
                open_url, media, media_type = await self._connect_extras(user, index)

                payload = MessagePayloadDto(
                    i18n_key=f"event-onboarding-nudge-{index}",
                    media=media,
                    media_type=media_type,
                    reply_markup=self._build_keyboard(index, support_url, open_url),
                    # No stock "❌ Закрыть" button — the CTA buttons are the only actions.
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

    async def _connect_extras(
        self, user: UserDto, index: int
    ) -> tuple[str, Optional[MediaDescriptorDto], Optional[MediaType]]:
        """Per-step extras: card banner on step 1, direct-connect Happ URL on step 2."""
        if index == _BANNER_STEP:
            media: Optional[MediaDescriptorDto] = None
            media_type: Optional[MediaType] = None
            if self.config.bot.use_banners:
                banner_path = _resolve_banner_path(self.config, BannerName.FOLLOWUP_CONNECT)
                if banner_path:
                    media = MediaDescriptorDto(kind="fs", value=str(banner_path))
                    media_type = MediaType.PHOTO
            return "", media, media_type

        if index == _FOLLOWUP_A_STEP:
            subscription = await self.subscription_dao.get_current(user.id)
            sub_url = subscription.url if subscription else ""
            open_url = _happ_open_url(self.config.domain.get_secret_value(), sub_url)
            return open_url, None, None

        return "", None, None

    def _build_keyboard(
        self, index: int, support_url: str, open_url: str = ""
    ) -> InlineKeyboardMarkup:
        # Buttons mirror the source A-chain per step. Text is the i18n key (the
        # notifier localizes it, preserving `style`); connect actions are blue
        # (PRIMARY), the support/fail branch is red (DANGER).
        if index <= 1:
            row = [
                InlineKeyboardButton(
                    text="btn-onboarding.nudge-continue",
                    callback_data=_GOTO_ENTRY,
                    style=ButtonStyle.PRIMARY,
                ),
                InlineKeyboardButton(
                    text="btn-onboarding.nudge-fail",
                    callback_data=_GOTO_HELP,
                    style=ButtonStyle.DANGER,
                ),
            ]
        elif index == 2:
            # "Подключиться" opens Happ directly via the bouncer URL (same action as
            # the onboarding "Открыть в Happ" button); falls back to the funnel entry
            # if the user has no subscription URL. "Помощь" is the support page.
            connect_button = (
                InlineKeyboardButton(
                    text="btn-onboarding.nudge-connect",
                    url=open_url,
                    style=ButtonStyle.PRIMARY,
                )
                if open_url
                else InlineKeyboardButton(
                    text="btn-onboarding.nudge-connect",
                    callback_data=_GOTO_ENTRY,
                    style=ButtonStyle.PRIMARY,
                )
            )
            row = [
                connect_button,
                InlineKeyboardButton(
                    text="btn-onboarding.nudge-help",
                    url=support_url,
                    style=ButtonStyle.DANGER,
                ),
            ]
        else:
            row = [
                InlineKeyboardButton(
                    text="btn-onboarding.connect",
                    callback_data=_GOTO_ENTRY,
                    style=ButtonStyle.PRIMARY,
                ),
            ]
        return InlineKeyboardMarkup(inline_keyboard=[row])
