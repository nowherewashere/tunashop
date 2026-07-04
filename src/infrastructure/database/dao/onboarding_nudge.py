from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert

from src.application.common.dao import OnboardingNudgeDao
from src.application.dto import OnboardingNudgeDto
from src.infrastructure.database.models.onboarding_nudge import (
    NUDGE_CANCELLED,
    NUDGE_PENDING,
    NUDGE_SENT,
    OnboardingNudge,
)

from .base import BaseDaoImpl


class OnboardingNudgeDaoImpl(BaseDaoImpl, OnboardingNudgeDao):
    async def schedule(self, telegram_id: int, step: str, fire_at: datetime) -> None:
        # Skip if a row for this (telegram_id, step) already exists in any status,
        # so the chain fires at most once per user even across re-entries.
        exists = await self.session.execute(
            select(OnboardingNudge.id).where(
                OnboardingNudge.telegram_id == telegram_id,
                OnboardingNudge.step == step,
            )
        )
        if exists.first() is not None:
            return

        await self.session.execute(
            insert(OnboardingNudge).values(
                telegram_id=telegram_id,
                step=step,
                fire_at=fire_at,
                status=NUDGE_PENDING,
            )
        )

    async def cancel_pending(self, telegram_id: int) -> None:
        await self.session.execute(
            update(OnboardingNudge)
            .where(
                OnboardingNudge.telegram_id == telegram_id,
                OnboardingNudge.status == NUDGE_PENDING,
            )
            .values(status=NUDGE_CANCELLED)
        )

    async def get_due(self, now: datetime, limit: int = 100) -> list[OnboardingNudgeDto]:
        result = await self.session.execute(
            select(OnboardingNudge)
            .where(
                OnboardingNudge.status == NUDGE_PENDING,
                OnboardingNudge.fire_at <= now,
            )
            .order_by(OnboardingNudge.fire_at)
            .limit(limit)
        )
        return [
            OnboardingNudgeDto(id=row.id, telegram_id=row.telegram_id, step=row.step)
            for row in result.scalars().all()
        ]

    async def mark_sent(self, nudge_id: int, sent_at: datetime) -> None:
        await self.session.execute(
            update(OnboardingNudge)
            .where(OnboardingNudge.id == nudge_id)
            .values(status=NUDGE_SENT, sent_at=sent_at)
        )

    async def mark_cancelled(self, nudge_id: int) -> None:
        await self.session.execute(
            update(OnboardingNudge)
            .where(OnboardingNudge.id == nudge_id)
            .values(status=NUDGE_CANCELLED)
        )

    async def sent_in_window(self, telegram_id: int, since: datetime) -> int:
        result = await self.session.execute(
            select(func.count())
            .select_from(OnboardingNudge)
            .where(
                OnboardingNudge.telegram_id == telegram_id,
                OnboardingNudge.status == NUDGE_SENT,
                OnboardingNudge.sent_at >= since,
            )
        )
        return int(result.scalar_one())
