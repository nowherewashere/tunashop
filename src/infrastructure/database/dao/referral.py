from typing import Optional, cast

from adaptix import Retort
from adaptix.conversion import ConversionRetort
from loguru import logger
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.application.common.dao import ReferralDao
from src.application.dto import (
    ReferralDto,
    ReferralStatisticsDto,
    UserReferralStatsDto,
)
from src.infrastructure.database.models import Referral
from src.infrastructure.database.models.user import User


class ReferralDaoImpl(ReferralDao):
    def __init__(
        self,
        session: AsyncSession,
        retort: Retort,
        conversion_retort: ConversionRetort,
        redis: Redis,
    ) -> None:
        self.session = session
        self.retort = retort
        self.conversion_retort = conversion_retort
        self.redis = redis

        self._convert_to_referral_dto = self.conversion_retort.get_converter(Referral, ReferralDto)
        self._convert_to_referral_list = self.conversion_retort.get_converter(
            list[Referral],
            list[ReferralDto],
        )

    async def create_referral(self, referral: ReferralDto) -> ReferralDto:
        db_referral = Referral(
            referrer_id=referral.referrer.id,
            referred_id=referral.referred.id,
            level=referral.level,
        )

        self.session.add(db_referral)
        await self.session.flush()
        await self.session.refresh(db_referral, attribute_names=["referrer", "referred"])

        logger.debug(
            f"Created referral: referrer id='{referral.referrer.id}' "
            f"invited referred id='{referral.referred.id}'"
        )
        return self._convert_to_referral_dto(db_referral)

    async def get_by_referred_id(self, referred_id: int) -> Optional[ReferralDto]:
        stmt = (
            select(Referral)
            .where(Referral.referred_id == referred_id)
            .options(selectinload(Referral.referrer), selectinload(Referral.referred))
        )
        db_referral = await self.session.scalar(stmt)

        if db_referral:
            logger.debug(f"Referrer for user_id '{referred_id}' found")
            return self._convert_to_referral_dto(db_referral)

        logger.debug(f"Referrer for user_id '{referred_id}' not found")
        return None

    async def get_referrals_count(self, referrer_id: int) -> int:
        stmt = select(func.count()).select_from(Referral).where(Referral.referrer_id == referrer_id)
        count = await self.session.scalar(stmt) or 0

        logger.debug(f"User_id '{referrer_id}' has '{count}' referrals")
        return count

    async def get_referrals_list(
        self,
        referrer_id: int,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ReferralDto]:
        stmt = (
            select(Referral)
            .where(Referral.referrer_id == referrer_id)
            .options(selectinload(Referral.referred))
            .limit(limit)
            .offset(offset)
            .order_by(Referral.created_at.desc())
        )
        result = await self.session.scalars(stmt)
        db_referrals = cast(list, result.all())

        logger.debug(
            f"Retrieved '{len(db_referrals)}' referrals for user_id '{referrer_id}' "
            f"with limit '{limit}' and offset '{offset}'"
        )
        return self._convert_to_referral_list(db_referrals)

    async def get_referral_chain(
        self,
        referred_id: int,
    ) -> tuple[Optional[ReferralDto], Optional[ReferralDto]]:
        first_level = await self.get_by_referred_id(referred_id)
        if not first_level:
            return None, None

        second_level = await self.get_by_referred_id(first_level.referrer.id)

        logger.debug(
            f"Referral chain for user_id '{referred_id}': "
            f"level 1 referrer id='{first_level.referrer.id}', "
            f"level 2 referrer id='{second_level.referrer.id if second_level else 'none'}'"
        )

        return first_level, second_level

    async def get_stats(self) -> ReferralStatisticsDto:
        # No level split: attribution still writes level-2 edges, but commission is
        # single-tier, so splitting the display by level implies earnings that can
        # never happen. The money side comes from ReferralLedgerDao.
        stmt = select(
            func.count().label("total_referrals"),
            func.count(func.distinct(Referral.referrer_id)).label("unique_referrers"),
        )

        top_referrer_stmt = (
            select(
                Referral.referrer_id,
                func.count().label("referrals_count"),
            )
            .group_by(Referral.referrer_id)
            .order_by(func.count().desc())
            .limit(1)
        )

        referral_row = (await self.session.execute(stmt)).mappings().one()
        top_referrer_row = (await self.session.execute(top_referrer_stmt)).mappings().first()

        logger.debug("Referral stats fetched")
        return ReferralStatisticsDto(
            total_referrals=int(referral_row["total_referrals"] or 0),
            unique_referrers=int(referral_row["unique_referrers"] or 0),
            top_referrer_referrals_count=int(top_referrer_row["referrals_count"])
            if top_referrer_row
            else 0,
            top_referrer_id=top_referrer_row["referrer_id"] if top_referrer_row else None,
        )

    async def get_user_referral_stats(self, user_id: int) -> UserReferralStatsDto:
        # Referrer info: find the User who referred this user (referred_id = user_id).
        # Counts and money for the *inviting* side come from GetReferralSummary.
        referrer_stmt = (
            select(User.telegram_id, User.email, User.username)
            .join(Referral, Referral.referrer_id == User.id)
            .where(Referral.referred_id == user_id)
        )

        referrer_row = (await self.session.execute(referrer_stmt)).mappings().first()

        return UserReferralStatsDto(
            referrer_telegram_id=referrer_row["telegram_id"] if referrer_row else None,
            referrer_email=referrer_row["email"] if referrer_row else None,
            referrer_username=referrer_row["username"] if referrer_row else None,
        )
