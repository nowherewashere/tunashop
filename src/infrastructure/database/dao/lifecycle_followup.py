from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from src.application.common.dao import LifecycleFollowupDao
from src.application.dto import LifecycleFollowupDto
from src.infrastructure.database.models.lifecycle_followup import (
    FOLLOWUP_CANCELLED,
    FOLLOWUP_PENDING,
    FOLLOWUP_SENT,
    LifecycleFollowup,
)

from .base import BaseDaoImpl


class LifecycleFollowupDaoImpl(BaseDaoImpl, LifecycleFollowupDao):
    async def schedule(
        self, telegram_id: int, chain: str, step: str, fire_at: datetime
    ) -> None:
        exists = await self.session.execute(
            select(LifecycleFollowup.id).where(
                LifecycleFollowup.telegram_id == telegram_id,
                LifecycleFollowup.chain == chain,
                LifecycleFollowup.step == step,
            )
        )
        if exists.first() is not None:
            return

        await self.session.execute(
            insert(LifecycleFollowup).values(
                telegram_id=telegram_id,
                chain=chain,
                step=step,
                fire_at=fire_at,
                status=FOLLOWUP_PENDING,
            )
        )

    async def cancel_chain(self, telegram_id: int, chain: str) -> None:
        await self.session.execute(
            update(LifecycleFollowup)
            .where(
                LifecycleFollowup.telegram_id == telegram_id,
                LifecycleFollowup.chain == chain,
                LifecycleFollowup.status == FOLLOWUP_PENDING,
            )
            .values(status=FOLLOWUP_CANCELLED)
        )

    async def cancel_all_pending(self, telegram_id: int) -> None:
        await self.session.execute(
            update(LifecycleFollowup)
            .where(
                LifecycleFollowup.telegram_id == telegram_id,
                LifecycleFollowup.status == FOLLOWUP_PENDING,
            )
            .values(status=FOLLOWUP_CANCELLED)
        )

    async def get_due(
        self, now: datetime, limit: int = 100
    ) -> list[LifecycleFollowupDto]:
        result = await self.session.execute(
            select(LifecycleFollowup)
            .where(
                LifecycleFollowup.status == FOLLOWUP_PENDING,
                LifecycleFollowup.fire_at <= now,
            )
            .order_by(LifecycleFollowup.fire_at)
            .limit(limit)
        )
        return [
            LifecycleFollowupDto(
                id=row.id,
                telegram_id=row.telegram_id,
                chain=row.chain,
                step=row.step,
            )
            for row in result.scalars().all()
        ]

    async def mark_sent(self, followup_id: int, sent_at: datetime) -> None:
        await self.session.execute(
            update(LifecycleFollowup)
            .where(LifecycleFollowup.id == followup_id)
            .values(status=FOLLOWUP_SENT, sent_at=sent_at)
        )

    async def mark_cancelled(self, followup_id: int) -> None:
        await self.session.execute(
            update(LifecycleFollowup)
            .where(LifecycleFollowup.id == followup_id)
            .values(status=FOLLOWUP_CANCELLED)
        )

    async def sent_in_window(self, telegram_id: int, since: datetime) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(LifecycleFollowup)
            .where(
                LifecycleFollowup.telegram_id == telegram_id,
                LifecycleFollowup.status == FOLLOWUP_SENT,
                LifecycleFollowup.sent_at >= since,
            )
        )
        return int(result.scalar_one())
