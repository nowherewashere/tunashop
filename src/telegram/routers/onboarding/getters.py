import base64
from typing import Any, Final

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import BotService, TranslatorRunner
from src.application.common.dao import SubscriptionDao
from src.application.dto import TelegramUserDto
from src.core.config import AppConfig
from src.core.constants import API_V1

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
# Fallback "how to refresh in Happ" clip when ONBOARDING_REFRESH_VIDEO_URL is unset
# (the tips screen always renders the link, so it must resolve to something).
_REFRESH_VIDEO_DEFAULT: Final[str] = "https://t.me/tuna_vpn"


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


@inject
async def connect_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: TelegramUserDto,
    subscription_dao: FromDishka[SubscriptionDao],
    **kwargs: Any,
) -> dict[str, Any]:
    current_subscription = await subscription_dao.get_current(user.id)
    sub_url = current_subscription.url if current_subscription else ""

    platform = str(dialog_manager.dialog_data.get("platform", "ios"))
    open_url = _happ_open_url(config.domain.get_secret_value(), sub_url)

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
    **kwargs: Any,
) -> dict[str, Any]:
    current_subscription = await subscription_dao.get_current(user.id)
    sub_url = current_subscription.url if current_subscription else ""

    platform = str(dialog_manager.dialog_data.get("platform", "apple_tv"))

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
    **kwargs: Any,
) -> dict[str, Any]:
    video_url = config.onboarding.refresh_video_url or _REFRESH_VIDEO_DEFAULT
    return {"refresh_video_url": video_url}


@inject
async def not_working_getter(
    dialog_manager: DialogManager,
    bot_service: FromDishka[BotService],
    i18n: FromDishka[TranslatorRunner],
    **kwargs: Any,
) -> dict[str, Any]:
    # Entered from the menu Support button (start_data={"from_menu": True}) vs.
    # reached inside the funnel — drives which Back target the screen shows.
    start_data = dialog_manager.start_data
    from_menu = bool(isinstance(start_data, dict) and start_data.get("from_menu"))
    return {
        "support_url": bot_service.get_support_url(text=i18n.get("message.help")),
        "from_menu": from_menu,
    }
