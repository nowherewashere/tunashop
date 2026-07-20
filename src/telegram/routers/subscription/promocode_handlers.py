from typing import Any

from aiogram.fsm.state import State
from aiogram.types import Message
from aiogram_dialog import DialogManager, ShowMode
from aiogram_dialog.widgets.input import MessageInput
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import EventPublisher
from src.application.dto import TelegramUserDto
from src.application.events import ErrorEvent
from src.application.use_cases.promocode.commands.activate import (
    ActivatePromocode,
    ActivatePromocodeDto,
)
from src.core.config import AppConfig
from src.core.constants import USER_KEY
from src.core.exceptions import (
    PromocodeAlreadyActivatedError,
    PromocodeExpiredError,
    PromocodeNotAvailableError,
    PromocodeNotFoundError,
)
from src.telegram.states import Subscription

# Keys under which the success screen's reward wording is passed (dialog_data for the
# in-dialog input flow, start_data for the deeplink flow — see getter_promocode_success).
REWARD_TYPE_KEY = "reward_type"
REWARD_KEY = "reward"


async def activate_and_resolve(
    user: TelegramUserDto,
    code: str,
    *,
    activate_promocode: ActivatePromocode,
    event_publisher: EventPublisher,
    config: AppConfig,
) -> tuple[State, dict[str, Any]]:
    """Activate `code` and resolve which result window to show plus its render data.

    Shared by the in-dialog message input and the `promo_<CODE>` deeplink so both drive
    the same one-step flow (send code → «принят» / «не сработал»). Every validation
    failure collapses to the single failed window; unexpected errors are reported via
    an ErrorEvent (as before) and also land on the failed window.
    """
    try:
        promo = await activate_promocode(user, ActivatePromocodeDto(code=code, user=user))
    except (
        PromocodeNotFoundError,
        PromocodeExpiredError,
        PromocodeAlreadyActivatedError,
        PromocodeNotAvailableError,
    ):
        return Subscription.PROMOCODE_FAILED, {}
    except Exception as exc:
        logger.exception(f"{user.log} Promocode '{code}' activation failed unexpectedly")
        await event_publisher.publish(
            ErrorEvent(
                **config.build.data,
                telegram_id=user.telegram_id,
                username=user.username,
                name=user.name,
                exception=exc,
            )
        )
        return Subscription.PROMOCODE_FAILED, {}

    logger.info(f"{user.log} Activated promocode '{promo.code}'")
    return Subscription.PROMOCODE_SUCCESS, {
        REWARD_TYPE_KEY: promo.reward_type.value,
        # reward is None for SUBSCRIPTION-type codes; that branch ignores it, and 0 is a
        # legitimate value elsewhere (DURATION 0 = «бессрочно»).
        REWARD_KEY: promo.reward if promo.reward is not None else 0,
    }


@inject
async def on_promocode_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    activate_promocode: FromDishka[ActivatePromocode],
    event_publisher: FromDishka[EventPublisher],
    config: FromDishka[AppConfig],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    code = (message.text or "").strip().upper()

    if not code:
        return

    target, data = await activate_and_resolve(
        user,
        code,
        activate_promocode=activate_promocode,
        event_publisher=event_publisher,
        config=config,
    )
    dialog_manager.dialog_data.update(data)
    await dialog_manager.switch_to(target)


async def getter_promocode_success(dialog_manager: DialogManager, **kwargs: Any) -> dict[str, Any]:
    start_data = dialog_manager.start_data if isinstance(dialog_manager.start_data, dict) else {}
    reward_type = (
        dialog_manager.dialog_data.get(REWARD_TYPE_KEY) or start_data.get(REWARD_TYPE_KEY) or ""
    )
    reward = dialog_manager.dialog_data.get(REWARD_KEY)
    if reward is None:
        reward = start_data.get(REWARD_KEY, 0)
    return {"reward_type": reward_type, "reward": reward or 0}
