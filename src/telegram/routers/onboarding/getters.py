from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import BotService, TranslatorRunner
from src.application.common.dao import SettingsDao, SubscriptionDao
from src.application.dto import TelegramUserDto
from src.core.config import AppConfig

# Fixed set of platforms the funnel offers. The order here is the on-screen order.
PLATFORMS: tuple[str, ...] = ("ios", "android", "windows", "mac")


@inject
async def onboarding_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    user: TelegramUserDto,
    bot_service: FromDishka[BotService],
    i18n: FromDishka[TranslatorRunner],
    subscription_dao: FromDishka[SubscriptionDao],
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    current_subscription = await subscription_dao.get_current(user.id)
    subscription_url = current_subscription.url if current_subscription else ""

    settings = await settings_dao.get()
    onboarding = config.onboarding

    platform = str(dialog_manager.dialog_data.get("platform", PLATFORMS[0]))
    store_link = onboarding.store_link(platform)
    import_url = onboarding.happ_import_template.format(sub_url=subscription_url)
    support_url = bot_service.get_support_url(text=i18n.get("message.help"))

    return {
        "platform": platform,
        "store_link": store_link,
        "import_url": import_url,
        "support_url": support_url,
        "refresh_video_url": onboarding.refresh_video_url,
        "has_refresh_video": bool(onboarding.refresh_video_url),
        # Shared keys reused by the embedded *connect_buttons on the SUCCESS window
        # (kept identical to getter_connect so the widget renders the same way).
        "is_mini_app": config.bot.is_mini_app,
        "is_mini_app_reserve": config.bot.is_mini_app and settings.extra.mini_app_reserve,
        "connection_url": config.bot.mini_app_url or subscription_url,
        "subscription_url": subscription_url,
        "connectable": bool(current_subscription),
        # Inside the funnel we always want the real *connect_buttons (SUCCESS window)
        # and never the funnel-entry button, so report the flag as off here. See the
        # `~F["onboarding_enabled"]` guard added to connect_buttons in keyboards.py.
        "onboarding_enabled": False,
    }
