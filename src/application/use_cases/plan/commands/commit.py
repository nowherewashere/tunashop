from dataclasses import dataclass
from typing import Optional
from uuid import UUID

from loguru import logger

from src.application.common import Cryptographer, Interactor
from src.application.common.dao import PlanDao, TrafficPoolDao
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import PlanDto, UserDto
from src.core.enums import PlanAvailability, PlanType
from src.core.exceptions import PlanNameAlreadyExistsError, SquadsEmptyError, TrialDurationError


@dataclass(frozen=True)
class CommitPlanResultDto:
    plan: Optional[PlanDto] = None
    is_created: bool = False
    is_updated: bool = False


def _validate_and_prepare_plan(
    actor: UserDto,
    plan: PlanDto,
    pool_squads: Optional[dict[int, UUID]] = None,
) -> None:
    if not plan.internal_squads:
        logger.warning(f"{actor.log} Commit failed: squads list is empty")
        raise SquadsEmptyError()

    _prune_pool_quotas(actor, plan, pool_squads or {})

    if plan.is_trial and len(plan.durations) > 1:
        logger.warning(
            f"{actor.log} Commit failed: trial plan has '{len(plan.durations)}' durations"
        )
        raise TrialDurationError()

    if plan.type == PlanType.DEVICES:
        plan.traffic_limit = 0
    elif plan.type == PlanType.TRAFFIC:
        plan.device_limit = 0
    elif plan.type == PlanType.UNLIMITED:
        plan.traffic_limit = 0
        plan.device_limit = 0

    if plan.availability != PlanAvailability.ALLOWED:
        plan.allowed_telegram_ids = []
        plan.allowed_emails = []


def _prune_pool_quotas(actor: UserDto, plan: PlanDto, pool_squads: dict[int, UUID]) -> None:
    """Drop pool quotas the plan cannot actually enforce.

    A quota only means anything when the plan grants the pool's squad in the first
    place: the quota is enforced by *taking that squad away*, so on a plan that never
    granted it there is nothing to meter and nothing to withdraw — the number would
    only mislead whoever reads the plan card. Same for a quota of zero, and for a pool
    that has since been deleted.
    """
    kept = []
    for quota in plan.pool_quotas:
        squad = pool_squads.get(quota.pool_id)
        if squad is None:
            logger.warning(
                f"{actor.log} Dropped quota on unknown pool '{quota.pool_id}' from "
                f"plan '{plan.name}'"
            )
            continue
        if quota.quota_gb <= 0:
            continue
        if squad not in plan.internal_squads:
            logger.warning(
                f"{actor.log} Dropped quota on pool '{quota.pool_id}' from plan "
                f"'{plan.name}': its squad is not among the plan's internal squads"
            )
            continue
        kept.append(quota)

    plan.pool_quotas = kept


async def _pool_squads(traffic_pool_dao: TrafficPoolDao) -> dict[int, UUID]:
    return {pool.id: pool.internal_squad_uuid for pool in await traffic_pool_dao.get_all()}


class CommitPlan(Interactor[PlanDto, CommitPlanResultDto]):
    required_permission = Permission.REMNASHOP_PLAN_EDITOR

    def __init__(
        self,
        uow: UnitOfWork,
        plan_dao: PlanDao,
        traffic_pool_dao: TrafficPoolDao,
        cryptographer: Cryptographer,
    ) -> None:
        self.uow = uow
        self.plan_dao = plan_dao
        self.traffic_pool_dao = traffic_pool_dao
        self.cryptographer = cryptographer

    async def _execute(self, actor: UserDto, plan: PlanDto) -> CommitPlanResultDto:
        _validate_and_prepare_plan(actor, plan, await _pool_squads(self.traffic_pool_dao))

        async with self.uow:
            if plan.id:
                await self.plan_dao.update(plan.as_fully_changed())
                logger.info(f"{actor.log} Updated existing plan '{plan.name}' with ID '{plan.id}'")
                await self.uow.commit()
                return CommitPlanResultDto(plan, is_updated=True)

            existing = await self.plan_dao.get_by_name(plan.name)
            if existing:
                logger.warning(f"{actor.log} Plan name '{plan.name}' already exists")
                raise PlanNameAlreadyExistsError()

            async def persist(code: str) -> PlanDto:
                plan.public_code = code
                return await self.plan_dao.create(plan)

            new_plan = await self.uow.persist_with_unique_code(
                generate=lambda: self.cryptographer.generate_unique_code(
                    self.plan_dao.get_by_public_code, length=8
                ),
                persist=persist,
                column="public_code",
            )
            await self.uow.commit()

        logger.info(f"{actor.log} Created new plan '{new_plan.name}'")
        return CommitPlanResultDto(new_plan, is_created=True)


class CommitPlansBatch(Interactor[list[PlanDto], list[CommitPlanResultDto]]):
    required_permission = Permission.REMNASHOP_PLAN_EDITOR

    def __init__(
        self,
        uow: UnitOfWork,
        plan_dao: PlanDao,
        traffic_pool_dao: TrafficPoolDao,
        cryptographer: Cryptographer,
    ) -> None:
        self.uow = uow
        self.plan_dao = plan_dao
        self.traffic_pool_dao = traffic_pool_dao
        self.cryptographer = cryptographer

    async def _execute(self, actor: UserDto, plans: list[PlanDto]) -> list[CommitPlanResultDto]:
        results: list[CommitPlanResultDto] = []
        pool_squads = await _pool_squads(self.traffic_pool_dao)
        async with self.uow:
            for plan in plans:
                _validate_and_prepare_plan(actor, plan, pool_squads)

                existing = await self.plan_dao.get_by_name(plan.name)
                if existing:
                    logger.warning(f"{actor.log} Plan name '{plan.name}' already exists")
                    raise PlanNameAlreadyExistsError()

                async def persist(code: str, plan: PlanDto = plan) -> PlanDto:
                    plan.public_code = code
                    return await self.plan_dao.create(plan)

                created = await self.uow.persist_with_unique_code(
                    generate=lambda: self.cryptographer.generate_unique_code(
                        self.plan_dao.get_by_public_code, length=8
                    ),
                    persist=persist,
                    column="public_code",
                )
                results.append(CommitPlanResultDto(created, is_created=True))

            await self.uow.commit()

        logger.info(f"{actor.log} Imported '{len(results)}' plans atomically")
        return results
