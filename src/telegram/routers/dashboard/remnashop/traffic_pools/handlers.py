from uuid import UUID

from adaptix import Retort
from aiogram.types import CallbackQuery, Message
from aiogram_dialog import DialogManager, ShowMode, StartMode
from aiogram_dialog.widgets.input import MessageInput
from aiogram_dialog.widgets.kbd import Button, Select
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import Notifier
from src.application.dto import TelegramUserDto, TrafficPoolDto
from src.application.use_cases.traffic_pool import (
    CommitTrafficPool,
    DeleteTrafficPool,
    GetTrafficPools,
)
from src.core.constants import UNASSIGNED_SQUAD, USER_KEY
from src.core.exceptions import (
    PoolInUseError,
    PoolNameAlreadyExistsError,
    PoolSquadAlreadyUsedError,
    PoolSquadNotFoundError,
    TrafficPoolError,
)
from src.telegram.states import RemnashopTrafficPools
from src.telegram.utils import is_double_click

_ERRORS: dict[type[Exception], str] = {
    PoolNameAlreadyExistsError: "ntf-pool.name-already-exists",
    PoolSquadAlreadyUsedError: "ntf-pool.squad-already-used",
    PoolSquadNotFoundError: "ntf-pool.squad-not-found",
    PoolInUseError: "ntf-pool.in-use",
}


def _load(dialog_manager: DialogManager, retort: Retort) -> TrafficPoolDto:
    return retort.load(dialog_manager.dialog_data[TrafficPoolDto.__name__], TrafficPoolDto)


def _store(dialog_manager: DialogManager, retort: Retort, pool: TrafficPoolDto) -> None:
    dialog_manager.dialog_data[TrafficPoolDto.__name__] = retort.dump(pool)


@inject
async def on_pool_create(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
) -> None:
    # A pool is meaningless without a squad, so the draft starts with a nil UUID and
    # the configurator refuses to save until one is picked.
    _store(
        dialog_manager,
        retort,
        TrafficPoolDto(name="", internal_squad_uuid=UNASSIGNED_SQUAD),
    )
    await dialog_manager.switch_to(RemnashopTrafficPools.CONFIGURATOR)


@inject
async def on_pool_select(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    get_pools: FromDishka[GetTrafficPools],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    pool_id = int(dialog_manager.item_id)  # type: ignore[attr-defined]

    pool = next((p for p in await get_pools(user) if p.id == pool_id), None)
    if not pool:
        raise ValueError(f"Attempted to select non-existent traffic pool '{pool_id}'")

    _store(dialog_manager, retort, pool)
    logger.info(f"{user.log} Selected traffic pool '{pool_id}'")
    await dialog_manager.switch_to(RemnashopTrafficPools.CONFIGURATOR)


@inject
async def on_name_input(
    message: Message,
    widget: MessageInput,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
) -> None:
    dialog_manager.show_mode = ShowMode.EDIT
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    name = (message.text or "").strip()
    if not name or len(name) > 64:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    pool = _load(dialog_manager, retort)
    pool.name = name
    _store(dialog_manager, retort, pool)
    await dialog_manager.switch_to(RemnashopTrafficPools.CONFIGURATOR)


@inject
async def on_squad_select(
    callback: CallbackQuery,
    widget: Select,
    dialog_manager: DialogManager,
    selected_squad: UUID,
    retort: FromDishka[Retort],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]

    pool = _load(dialog_manager, retort)
    pool.internal_squad_uuid = selected_squad
    _store(dialog_manager, retort, pool)

    logger.info(f"{user.log} Set traffic pool squad to '{selected_squad}'")
    await dialog_manager.switch_to(RemnashopTrafficPools.CONFIGURATOR)


@inject
async def on_active_toggle(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
) -> None:
    pool = _load(dialog_manager, retort)
    pool.is_active = not pool.is_active
    _store(dialog_manager, retort, pool)


@inject
async def on_pool_confirm(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    commit_pool: FromDishka[CommitTrafficPool],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    pool = _load(dialog_manager, retort)

    if pool.internal_squad_uuid == UNASSIGNED_SQUAD:
        await notifier.notify_user(user, i18n_key="ntf-pool.squad-required")
        return

    try:
        await commit_pool(user, pool)
    except TrafficPoolError as e:
        await notifier.notify_user(user, i18n_key=_ERRORS.get(type(e), "ntf-error.unknown"))
        return
    except ValueError:
        await notifier.notify_user(user, i18n_key="ntf-common.invalid-value")
        return

    await notifier.notify_user(user, i18n_key="ntf-pool.saved")
    await dialog_manager.switch_to(RemnashopTrafficPools.MAIN)


@inject
async def on_pool_delete(
    callback: CallbackQuery,
    widget: Button,
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    notifier: FromDishka[Notifier],
    delete_pool: FromDishka[DeleteTrafficPool],
) -> None:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    pool = _load(dialog_manager, retort)

    if not is_double_click(dialog_manager, key=f"pool_delete_{pool.id}", cooldown=10):
        await notifier.notify_user(user, i18n_key="ntf-common.double-click-confirm")
        return

    try:
        await delete_pool(user, pool.id)
    except TrafficPoolError as e:
        await notifier.notify_user(user, i18n_key=_ERRORS.get(type(e), "ntf-error.unknown"))
        return

    await notifier.notify_user(user, i18n_key="ntf-pool.deleted")
    await dialog_manager.start(state=RemnashopTrafficPools.MAIN, mode=StartMode.RESET_STACK)
