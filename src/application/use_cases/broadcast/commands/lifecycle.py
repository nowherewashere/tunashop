from dataclasses import dataclass
from typing import Optional
from uuid import UUID, uuid4

from aiogram.types import InlineKeyboardMarkup
from loguru import logger

from src.application.common import BroadcastDispatcher, Interactor
from src.application.common.dao import BroadcastDao
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import BroadcastDto, MessagePayloadDto, UserDto
from src.application.use_cases.broadcast.queries.audience import (
    GetBroadcastAudienceCount,
    GetBroadcastAudienceCountDto,
)
from src.core.constants import TRIAL_BONUS_CB
from src.core.enums import BroadcastAudience, BroadcastStatus


def _bind_bonus_button(payload: MessagePayloadDto, task_id: UUID) -> None:
    """Point the "+1 trial day" button at the broadcast that is about to carry it.

    The keyboard is picked in the dialog, before a task_id exists, so the button leaves
    the editor with a bare prefix. Stamping the id here is what lets a press find its own
    broadcast_messages row — the per-person claim ledger — instead of any other campaign's.
    """
    markup = payload.reply_markup
    if not isinstance(markup, InlineKeyboardMarkup):
        return

    for row in markup.inline_keyboard:
        for button in row:
            if button.callback_data == TRIAL_BONUS_CB:
                button.callback_data = f"{TRIAL_BONUS_CB}{task_id}"


@dataclass(frozen=True)
class StartBroadcastDto:
    audience: BroadcastAudience
    payload: MessagePayloadDto
    plan_id: Optional[int] = None


class StartBroadcast(Interactor[StartBroadcastDto, UUID]):
    required_permission = Permission.BROADCAST

    def __init__(
        self,
        uow: UnitOfWork,
        broadcast_dao: BroadcastDao,
        get_broadcast_audience_count: GetBroadcastAudienceCount,
        broadcast_dispatcher: BroadcastDispatcher,
    ) -> None:
        self.uow = uow
        self.broadcast_dao = broadcast_dao
        self.get_broadcast_audience_count = get_broadcast_audience_count
        self.broadcast_dispatcher = broadcast_dispatcher

    async def _execute(self, actor: UserDto, data: StartBroadcastDto) -> UUID:
        total_count = await self.get_broadcast_audience_count.system(
            GetBroadcastAudienceCountDto(data.audience, data.plan_id)
        )

        async with self.uow:
            task_id = uuid4()
            _bind_bonus_button(data.payload, task_id)
            broadcast = BroadcastDto(
                task_id=task_id,
                status=BroadcastStatus.PROCESSING,
                total_count=total_count,
                audience=data.audience,
                payload=data.payload,
            )
            await self.broadcast_dao.create(broadcast)
            await self.uow.commit()

        await self.broadcast_dispatcher.start(broadcast, data.plan_id)

        logger.info(f"{actor.log} Scheduled broadcast initialization '{task_id}'")
        return task_id


class DeleteBroadcast(Interactor[UUID, None]):
    required_permission = Permission.BROADCAST

    def __init__(
        self,
        broadcast_dao: BroadcastDao,
        broadcast_dispatcher: BroadcastDispatcher,
    ) -> None:
        self.broadcast_dao = broadcast_dao
        self.broadcast_dispatcher = broadcast_dispatcher

    async def _execute(self, actor: UserDto, data: UUID) -> None:
        broadcast = await self.broadcast_dao.get_by_task_id(data)

        if not broadcast:
            logger.error(f"{actor.log} Failed to find broadcast '{data}' for deletion")
            raise ValueError(f"Broadcast '{data}' not found")

        if broadcast.status == BroadcastStatus.DELETED:
            logger.warning(f"{actor.log} Broadcast '{data}' is already deleted")
            raise ValueError("Broadcast already deleted")

        # Deletion runs in the background; the task sets DELETED on completion. Do NOT
        # mark DELETED here — a failed/timed-out task must stay retryable and must not
        # falsely claim the Telegram messages were removed.
        await self.broadcast_dispatcher.delete(broadcast)

        logger.info(f"{actor.log} Scheduled background deletion for broadcast '{data}'")


class CancelBroadcast(Interactor[UUID, None]):
    required_permission = Permission.BROADCAST

    def __init__(self, uow: UnitOfWork, broadcast_dao: BroadcastDao) -> None:
        self.uow = uow
        self.broadcast_dao = broadcast_dao

    async def _execute(self, actor: UserDto, data: UUID) -> None:
        async with self.uow:
            broadcast = await self.broadcast_dao.get_by_task_id(data)

            if not broadcast:
                logger.error(f"{actor.log} Attempted to cancel non-existent broadcast '{data}'")
                raise ValueError(f"Broadcast '{data}' not found")

            if broadcast.status != BroadcastStatus.PROCESSING:
                logger.warning(
                    f"{actor.log} Failed to cancel broadcast '{data}' "
                    f"with status '{broadcast.status}'"
                )
                raise ValueError("Broadcast is not cancelable")

            await self.broadcast_dao.update_status(data, BroadcastStatus.CANCELED)
            await self.uow.commit()

        logger.info(f"{actor.log} Canceled broadcast '{data}'")


@dataclass(frozen=True)
class FinishBroadcastDto:
    task_id: UUID
    status: BroadcastStatus


class FinishBroadcast(Interactor[FinishBroadcastDto, None]):
    required_permission = None

    def __init__(self, uow: UnitOfWork, broadcast_dao: BroadcastDao) -> None:
        self.uow = uow
        self.broadcast_dao = broadcast_dao

    async def _execute(self, actor: UserDto, data: FinishBroadcastDto) -> None:
        async with self.uow:
            await self.broadcast_dao.update_status(data.task_id, data.status)
            await self.uow.commit()

        logger.info(f"Finished broadcast '{data.task_id}' with status '{data.status}'")
