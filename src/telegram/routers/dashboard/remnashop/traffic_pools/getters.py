from typing import Any
from uuid import UUID

from adaptix import Retort
from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common import Remnawave
from src.application.dto import TelegramUserDto, TrafficPoolDto
from src.application.use_cases.traffic_pool import (
    GetPoolNodes,
    GetPoolNodesDto,
    GetTrafficPools,
)
from src.core.constants import UNASSIGNED_SQUAD, USER_KEY


def _draft(dialog_manager: DialogManager, retort: Retort) -> TrafficPoolDto:
    """The pool currently being edited, kept in dialog_data until it is committed.

    Mirrors how the plan editor holds a PlanDto draft: nothing is written until the
    admin presses save, so backing out of the dialog changes nothing.
    """
    return retort.load(dialog_manager.dialog_data[TrafficPoolDto.__name__], TrafficPoolDto)


@inject
async def pools_getter(
    dialog_manager: DialogManager,
    remnawave: FromDishka[Remnawave],
    get_pools: FromDishka[GetTrafficPools],
    **kwargs: Any,
) -> dict[str, Any]:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    pools = await get_pools(user)

    squad_names = {squad.uuid: squad.name for squad in await remnawave.get_internal_squads()}

    return {
        "has_pools": bool(pools),
        "pools": [
            {
                "id": pool.id,
                "name": pool.name,
                "is_active": pool.is_active,
                # Falls back to the raw UUID when the squad has been deleted in the
                # panel — that is exactly the case the admin needs to see.
                "squad": squad_names.get(pool.internal_squad_uuid, str(pool.internal_squad_uuid)),
            }
            for pool in pools
        ],
    }


@inject
async def configurator_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    remnawave: FromDishka[Remnawave],
    **kwargs: Any,
) -> dict[str, Any]:
    pool = _draft(dialog_manager, retort)
    squad_names = {squad.uuid: squad.name for squad in await remnawave.get_internal_squads()}

    return {
        "name": pool.name,
        "is_active": pool.is_active,
        "is_edit": bool(pool.id),
        # `internal_squad_uuid` is not Optional, so `is not None` was true even for a
        # brand-new draft — which left "🖥 Ноды пула" on screen before a squad existed
        # and sent the nil UUID to the panel. UNASSIGNED_SQUAD is the real "not chosen
        # yet" value; `on_pool_confirm` has always tested for it.
        "squad": (
            squad_names.get(pool.internal_squad_uuid, str(pool.internal_squad_uuid))
            if pool.internal_squad_uuid != UNASSIGNED_SQUAD
            else "—"
        ),
        "has_squad": pool.internal_squad_uuid != UNASSIGNED_SQUAD,
    }


@inject
async def name_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    **kwargs: Any,
) -> dict[str, Any]:
    return {"name": _draft(dialog_manager, retort).name}


@inject
async def squad_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    remnawave: FromDishka[Remnawave],
    get_pools: FromDishka[GetTrafficPools],
    **kwargs: Any,
) -> dict[str, Any]:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    pool = _draft(dialog_manager, retort)

    # One squad backs at most one pool: two pools on the same squad would meter the
    # same bytes twice and fight over the same squad on the user. Taken ones are hidden
    # rather than shown-and-rejected.
    taken: set[UUID] = {
        other.internal_squad_uuid for other in await get_pools(user) if other.id != pool.id
    }

    return {
        "squads": [
            {
                "uuid": squad.uuid,
                "name": squad.name,
                "selected": squad.uuid == pool.internal_squad_uuid,
            }
            for squad in await remnawave.get_internal_squads()
            if squad.uuid not in taken
        ],
    }


@inject
async def nodes_getter(
    dialog_manager: DialogManager,
    retort: FromDishka[Retort],
    get_pool_nodes: FromDishka[GetPoolNodes],
    **kwargs: Any,
) -> dict[str, Any]:
    user: TelegramUserDto = dialog_manager.middleware_data[USER_KEY]
    pool = _draft(dialog_manager, retort)

    # The button into this window is hidden until a squad is picked, but a stale message
    # can still deliver the callback afterwards. Asking the panel about the nil UUID is a
    # 404, and a getter that raises leaves the window unrenderable rather than merely
    # empty — so treat "no squad" as "no nodes", which the template already renders.
    nodes: list[str] = []
    if pool.internal_squad_uuid != UNASSIGNED_SQUAD:
        nodes = await get_pool_nodes(user, GetPoolNodesDto(squad_uuid=pool.internal_squad_uuid))

    return {
        "name": pool.name,
        "nodes": "\n".join(f"• {node}" for node in nodes) if nodes else False,
    }
