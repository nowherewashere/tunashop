from dishka.integrations.taskiq import FromDishka, inject

from src.application.common import SupportService
from src.infrastructure.taskiq.broker import broker


# Auto-close idle support conversations. Runs every 10 minutes; the idle threshold
# itself is SUPPORT_IDLE_CLOSE_MINUTES, checked inside the service (0 disables it, and
# it no-ops when support is off). A new user message reopens a closed conversation.
@broker.task(schedule=[{"cron": "*/10 * * * *"}])
@inject(patch_module=True)
async def close_idle_support_conversations_task(
    support: FromDishka[SupportService],
) -> None:
    await support.close_idle()
