from typing import Optional

from taskiq.exceptions import TaskiqResultTimeoutError

from src.application.dto import BroadcastDto
from src.infrastructure.taskiq.tasks.notifications import notify_payments_restored


class PaymentNotificationDispatcherImpl:
    async def notify_payments_restored(self, user_ids: list[int]) -> None:
        await notify_payments_restored.kiq(user_ids)  # type: ignore[call-overload]


class BroadcastDispatcherImpl:
    async def start(self, broadcast: BroadcastDto, plan_id: Optional[int]) -> None:
        from src.infrastructure.taskiq.tasks.broadcast import send_broadcast_task  # noqa: PLC0415

        await (
            send_broadcast_task.kicker()
            .with_task_id(str(broadcast.task_id))
            .kiq(broadcast, plan_id)  # type: ignore[call-overload]
        )

    async def delete(self, broadcast: BroadcastDto) -> tuple[int, int, int]:
        from src.infrastructure.taskiq.tasks.broadcast import delete_broadcast_task  # noqa: PLC0415

        task = await delete_broadcast_task.kiq(broadcast)  # type: ignore[call-overload]
        try:
            result = await task.wait_result(timeout=600)
        except TaskiqResultTimeoutError:
            raise ValueError("Delete broadcast task timed out after 600 seconds")
        if result.is_err:
            raise ValueError("Delete broadcast task failed")
        counts = result.return_value
        return counts[0], counts[1], counts[2]
