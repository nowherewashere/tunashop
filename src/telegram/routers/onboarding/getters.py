from html import escape
from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import BotService, TranslatorRunner
from src.application.common.dao import SubscriptionDao
from src.application.dto import TelegramUserDto
from src.core.config import AppConfig

# Fixed set of platforms the funnel offers. The order here is the on-screen order.
PLATFORMS: tuple[str, ...] = ("ios", "android", "windows", "mac")

# Per-platform title used inside "Скачать Happ для …" (mirrors the source bot's
# PLATFORM_TITLES; the default matches the source fallback).
_PLATFORM_TITLES: dict[str, str] = {
    "ios": "iPhone",
    "android": "Android",
    "windows": "Windows",
    "mac": "Mac",
}
_PLATFORM_TITLE_DEFAULT = "устройства"

# The video line is inlined into the tip screens (O3 / refresh) exactly as the
# source bot renders it, and omitted entirely when no video URL is configured.
_VIDEO_LABEL = "Видео: как обновить за 5 секунд"


@inject
async def onboarding_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: TelegramUserDto,
    bot_service: FromDishka[BotService],
    i18n: FromDishka[TranslatorRunner],
    subscription_dao: FromDishka[SubscriptionDao],
    **kwargs: Any,
) -> dict[str, Any]:
    current_subscription = await subscription_dao.get_current(user.id)
    subscription_url = current_subscription.url if current_subscription else ""

    onboarding = config.onboarding
    platform = str(dialog_manager.dialog_data.get("platform", PLATFORMS[0]))

    video_url = onboarding.refresh_video_url
    video_block = (
        f'\n\n→ <a href="{escape(video_url)}">{_VIDEO_LABEL}</a>' if video_url else ""
    )

    return {
        "platform_title": _PLATFORM_TITLES.get(platform, _PLATFORM_TITLE_DEFAULT),
        "store_link": onboarding.store_link(platform),
        "import_url": onboarding.happ_import_template.format(sub_url=subscription_url),
        "video_block": video_block,
        "support_url": bot_service.get_support_url(text=i18n.get("message.help")),
    }
