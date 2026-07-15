import base64
from pathlib import Path
from typing import Any, Final, Optional

from aiogram.types import ContentType
from aiogram_dialog import DialogManager
from aiogram_dialog.api.entities import MediaAttachment
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import BotService, EventPublisher, TranslatorRunner
from src.application.common.dao import SubscriptionDao
from src.application.dto import TelegramUserDto
from src.core.config import AppConfig
from src.core.constants import API_V1
from src.core.enums import BannerName
from src.core.metrics import FunnelStep
from src.telegram.widgets.banner import get_banner

from .metrics import emit_funnel_step

# dialog_data flag: emit the connect-screen funnel steps once per dialog, not on
# every re-render (Back navigation), so counts stay one-per-step (spec §5).
_FUNNEL_CONNECT_FLAG = "funnel_connect_emitted"

# Human-readable platform names used inside "Скачать Happ для …" (iOS/macOS share
# the App Store listing, so they are merged into one "ios" option).
PLATFORM_TITLES: Final[dict[str, str]] = {
    "ios": "iPhone / Mac",
    "android": "Android",
    "windows": "Windows",
    "linux": "Linux",
}
_PLATFORM_TITLE_DEFAULT: Final[str] = "устройства"

# TV platforms set up via phone/web import (no direct subscription deep link), so
# they get their own instruction screen. The web-import URL and per-platform FAQ
# links live in OnboardingConfig (single source shared with the web API).
TV_PLATFORMS: Final[tuple[str, ...]] = ("apple_tv", "android_tv")

# Local "how to refresh in Happ" clip shown on the tips screen. Dropped into
# assets/videos/ as refresh_video.<ext>; absent ⇒ the video button is hidden and the
# screen keeps the success banner.
_REFRESH_VIDEO_NAME: Final[str] = "refresh_video"
_REFRESH_VIDEO_EXTS: Final[tuple[str, ...]] = ("mp4", "mov", "webm")


def resolve_refresh_video(config: AppConfig) -> Optional[Path]:
    for directory in (config.videos_dir, config.default_videos_dir):
        for ext in _REFRESH_VIDEO_EXTS:
            candidate = directory / f"{_REFRESH_VIDEO_NAME}.{ext}"
            if candidate.exists():
                return candidate
    return None


def is_tv_platform(platform: str) -> bool:
    return platform in TV_PLATFORMS


def platform_title(platform: str) -> str:
    return PLATFORM_TITLES.get(platform, _PLATFORM_TITLE_DEFAULT)


def _happ_open_url(domain: str, sub_url: str) -> str:
    """HTTPS bouncer URL that redirects to the ``happ://add/<url>`` deep link.

    Telegram rejects custom-scheme URLs in inline buttons, so a real "Открыть в
    Happ" button must point at an https page that redirects — served by the
    ``/connect/happ/{payload}`` endpoint. Empty ⇒ the button is hidden.
    """
    if not domain or not sub_url:
        return ""
    payload = base64.urlsafe_b64encode(sub_url.encode()).decode()
    # Must match connect_router's mount (API_V1 prefix) — see connect.py.
    return f"https://{domain}{API_V1}/connect/happ/{payload}"


async def _emit_connect_funnel(
    dialog_manager: DialogManager,
    publisher: EventPublisher,
    telegram_id: Optional[int],
    platform: str,
    has_config: bool,
) -> None:
    """Emit the connect-screen funnel steps once per dialog (spec §5).

    On the bot the install instructions and the config link live on one screen, so
    ``app_install_shown`` and ``config_issued`` fire together — an honest reflection
    of a single-screen flow (the site can space them across screens)."""
    if dialog_manager.dialog_data.get(_FUNNEL_CONNECT_FLAG):
        return
    dialog_manager.dialog_data[_FUNNEL_CONNECT_FLAG] = True

    await emit_funnel_step(
        publisher, FunnelStep.APP_INSTALL_SHOWN, telegram_id=telegram_id, platform=platform
    )
    if has_config:
        await emit_funnel_step(
            publisher, FunnelStep.CONFIG_ISSUED, telegram_id=telegram_id, platform=platform
        )


@inject
async def connect_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: TelegramUserDto,
    subscription_dao: FromDishka[SubscriptionDao],
    event_publisher: FromDishka[EventPublisher],
    **kwargs: Any,
) -> dict[str, Any]:
    current_subscription = await subscription_dao.get_current(user.id)
    sub_url = current_subscription.url if current_subscription else ""

    platform = str(dialog_manager.dialog_data.get("platform", "ios"))
    open_url = _happ_open_url(config.domain.get_secret_value(), sub_url)

    await _emit_connect_funnel(
        dialog_manager, event_publisher, user.telegram_id, platform, bool(sub_url)
    )

    return {
        "platform": platform,
        "platform_title": platform_title(platform),
        "store_link": config.onboarding.store_link(platform),
        "store_link_ru": config.onboarding.happ_link_ios_ru,
        "is_apple": platform == "ios",
        "open_url": open_url,
        "subscription_url": sub_url,
        "has_open_url": bool(open_url),
    }


@inject
async def tv_connect_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: TelegramUserDto,
    subscription_dao: FromDishka[SubscriptionDao],
    event_publisher: FromDishka[EventPublisher],
    **kwargs: Any,
) -> dict[str, Any]:
    current_subscription = await subscription_dao.get_current(user.id)
    sub_url = current_subscription.url if current_subscription else ""

    platform = str(dialog_manager.dialog_data.get("platform", "apple_tv"))

    await _emit_connect_funnel(
        dialog_manager, event_publisher, user.telegram_id, platform, bool(sub_url)
    )

    return {
        "platform": platform,
        "faq_url": config.onboarding.tv_faq_link(platform),
        "web_import_url": config.onboarding.tv_web_import_url,
        "subscription_url": sub_url,
        "has_sub": bool(sub_url),
    }


@inject
async def tips_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: TelegramUserDto,
    **kwargs: Any,
) -> dict[str, Any]:
    show_video = bool(dialog_manager.dialog_data.get("show_video"))
    video_path = resolve_refresh_video(config)

    # Screen media: the local «how to refresh» clip once the user taps the video
    # button, otherwise the success banner (both honour use_banners).
    media: Optional[MediaAttachment] = None
    if show_video and video_path is not None:
        media = MediaAttachment(type=ContentType.VIDEO, path=video_path)
    elif config.bot.use_banners:
        try:
            banner_path, banner_content_type = get_banner(
                banners_dir=config.banners_dir,
                default_banners_dir=config.default_banners_dir,
                name=BannerName.ONBOARDING_SUCCESS,
                locale=user.language,
                default_locale=config.default_locale,
            )
            media = MediaAttachment(type=banner_content_type, path=banner_path)
        except FileNotFoundError:
            media = None

    return {
        "show_video": show_video,
        "has_video": video_path is not None,
        "tips_media": media,
    }


@inject
async def not_working_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    bot_service: FromDishka[BotService],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    # Entered from the menu Support button (start_data={"from_menu": True}) vs.
    # reached inside the funnel — drives which Back target the screen shows.
    start_data = dialog_manager.start_data
    from_menu = bool(isinstance(start_data, dict) and start_data.get("from_menu"))
    # Legal links point at the public site's /oferta and /privacy pages (same base as
    # the cabinet link). Shown only when the site URL is configured, so we never render
    # a Url button with an empty href.
    site_base = config.web_cabinet_url.strip().rstrip("/")
    return {
        "support_url": bot_service.get_support_url(text=i18n.get("message.help")),
        "from_menu": from_menu,
        "has_legal": bool(site_base),
        "oferta_url": f"{site_base}/oferta" if site_base else "",
        "privacy_url": f"{site_base}/privacy" if site_base else "",
    }
