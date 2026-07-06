from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert

from src.application.common.dao import UserConnectionStateDao
from src.infrastructure.database.models.user_connection_state import UserConnectionState

from .base import BaseDaoImpl


class UserConnectionStateDaoImpl(BaseDaoImpl, UserConnectionStateDao):
    async def is_connected_once(self, telegram_id: int) -> bool:
        result = await self.session.execute(
            select(UserConnectionState.connected_once).where(
                UserConnectionState.telegram_id == telegram_id
            )
        )
        return bool(result.scalar_one_or_none())

    async def mark_connected(self, telegram_id: int, at: datetime) -> None:
        stmt = (
            insert(UserConnectionState)
            .values(
                telegram_id=telegram_id,
                connected_once=True,
                first_connected_at=at,
            )
            # Already connected before → keep the original first_connected_at,
            # just make sure the flag stays on.
            .on_conflict_do_update(
                index_elements=[UserConnectionState.telegram_id],
                set_={"connected_once": True},
            )
        )
        await self.session.execute(stmt)

    async def try_mark_trial_restarted(self, telegram_id: int, at: datetime) -> bool:
        result = await self.session.execute(
            update(UserConnectionState)
            .where(
                UserConnectionState.telegram_id == telegram_id,
                UserConnectionState.trial_restarted_at.is_(None),
            )
            .values(trial_restarted_at=at)
        )
        return bool(result.rowcount)  # type: ignore[attr-defined]
