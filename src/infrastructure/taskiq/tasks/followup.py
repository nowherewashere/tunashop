from dishka.integrations.taskiq import FromDishka, inject

from src.application.use_cases.followup.commands.process import (
    ProcessDueLifecycleFollowups,
)
from src.infrastructure.taskiq.broker import broker


@broker.task(schedule=[{"cron": "*/10 * * * *"}])
@inject(patch_module=True)
async def process_lifecycle_followups_task(
    process_due_followups: FromDishka[ProcessDueLifecycleFollowups],
) -> None:
    await process_due_followups.system()
