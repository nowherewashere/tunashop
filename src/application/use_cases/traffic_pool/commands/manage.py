from dataclasses import dataclass
from uuid import UUID

from loguru import logger

from src.application.common import Interactor, Remnawave
from src.application.common.dao import TrafficPoolDao
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import TrafficPoolDto, UserDto
from src.core.exceptions import (
    PoolInUseError,
    PoolNameAlreadyExistsError,
    PoolSquadAlreadyUsedError,
    PoolSquadNotFoundError,
)

# Both screens sit inside the plans area of the dashboard: a pool exists only to be
# priced by a plan, and the same admin manages both. Reusing the plan permissions keeps
# the role matrix as it is instead of inventing a second, near-identical one.
_VIEW = Permission.VIEW_PLANS
_EDIT = Permission.REMNASHOP_PLAN_EDITOR

_MAX_NAME_LENGTH = 64


class GetTrafficPools(Interactor[None, list[TrafficPoolDto]]):
    required_permission = _VIEW

    def __init__(self, traffic_pool_dao: TrafficPoolDao) -> None:
        self.traffic_pool_dao = traffic_pool_dao

    async def _execute(self, actor: UserDto, data: None) -> list[TrafficPoolDto]:
        return await self.traffic_pool_dao.get_all()


class CommitTrafficPool(Interactor[TrafficPoolDto, TrafficPoolDto]):
    """Create or update a pool, after checking the squad really exists in the panel.

    The squad is the pool's identity: it is both what gets metered and what gets
    withdrawn. A typo'd or deleted squad would silently meter nothing and cut nothing,
    so it is validated against the live panel list rather than trusted.
    """

    required_permission = _EDIT

    def __init__(
        self,
        uow: UnitOfWork,
        traffic_pool_dao: TrafficPoolDao,
        remnawave: Remnawave,
    ) -> None:
        self.uow = uow
        self.traffic_pool_dao = traffic_pool_dao
        self.remnawave = remnawave

    async def _execute(self, actor: UserDto, pool: TrafficPoolDto) -> TrafficPoolDto:
        name = (pool.name or "").strip()
        if not name or len(name) > _MAX_NAME_LENGTH:
            raise ValueError(f"Pool name must be 1..{_MAX_NAME_LENGTH} characters")
        pool.name = name

        squads = {squad.uuid for squad in await self.remnawave.get_internal_squads()}
        if pool.internal_squad_uuid not in squads:
            logger.warning(
                f"{actor.log} Pool commit failed: squad '{pool.internal_squad_uuid}' "
                f"is not present in the panel"
            )
            raise PoolSquadNotFoundError()

        existing = await self.traffic_pool_dao.get_all()
        for other in existing:
            if other.id == pool.id:
                continue
            if other.name == pool.name:
                raise PoolNameAlreadyExistsError()
            if other.internal_squad_uuid == pool.internal_squad_uuid:
                # Two pools on one squad would meter the same bytes twice and fight
                # over the same squad on the user.
                raise PoolSquadAlreadyUsedError()

        async with self.uow:
            if pool.id:
                updated = await self.traffic_pool_dao.update(pool)
                if not updated:
                    raise ValueError(f"Traffic pool '{pool.id}' not found")
                await self.uow.commit()
                logger.info(f"{actor.log} Updated traffic pool '{updated.name}'")
                return updated

            pool.order_index = max((p.order_index for p in existing), default=-1) + 1
            created = await self.traffic_pool_dao.create(pool)
            await self.uow.commit()

        logger.info(
            f"{actor.log} Created traffic pool '{created.name}' "
            f"on squad '{created.internal_squad_uuid}'"
        )
        return created


class DeleteTrafficPool(Interactor[int, None]):
    required_permission = _EDIT

    def __init__(self, uow: UnitOfWork, traffic_pool_dao: TrafficPoolDao) -> None:
        self.uow = uow
        self.traffic_pool_dao = traffic_pool_dao

    async def _execute(self, actor: UserDto, pool_id: int) -> None:
        # Deleting cascades into plan quotas and accounting windows. Live plans must be
        # unwired first, deliberately: an admin should see which plans lose their quota
        # rather than have them silently become unmetered.
        in_use = await self.traffic_pool_dao.count_plans_using(pool_id)
        if in_use:
            logger.warning(
                f"{actor.log} Refused to delete traffic pool '{pool_id}': "
                f"still priced by '{in_use}' plan(s)"
            )
            raise PoolInUseError()

        async with self.uow:
            if not await self.traffic_pool_dao.delete(pool_id):
                raise ValueError(f"Traffic pool '{pool_id}' not found")
            await self.uow.commit()

        logger.warning(f"{actor.log} Deleted traffic pool '{pool_id}'")


@dataclass(frozen=True)
class GetPoolNodesDto:
    squad_uuid: UUID


class GetPoolNodes(Interactor[GetPoolNodesDto, list[str]]):
    """Names of the nodes a pool's squad reaches — what the quota will actually meter.

    Usage can only be split per node, so this is the admin's only way to confirm that
    the squad covers the premium locations and nothing else.
    """

    required_permission = _VIEW

    def __init__(self, remnawave: Remnawave) -> None:
        self.remnawave = remnawave

    async def _execute(self, actor: UserDto, data: GetPoolNodesDto) -> list[str]:
        # Ask what squads exist before asking about one of them, exactly as
        # CommitTrafficPool does. A saved pool's squad can be deleted on the panel
        # afterwards, and `get_accessible_nodes` answers that with a 404 -> NotFoundError.
        # Raised out of a dialog getter that becomes "cannot get window data" and the
        # screen will not render at all, so the miss is turned into the domain error the
        # dashboard already knows how to say out loud.
        squads = {squad.uuid for squad in await self.remnawave.get_internal_squads()}
        if data.squad_uuid not in squads:
            logger.warning(
                f"{actor.log} Pool squad '{data.squad_uuid}' is not present in the panel"
            )
            raise PoolSquadNotFoundError()

        nodes = await self.remnawave.get_squad_nodes(data.squad_uuid)
        return [f"{node.country_code} {node.name}".strip() for node in nodes]
