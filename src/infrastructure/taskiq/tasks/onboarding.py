from dishka.integrations.taskiq import FromDishka, inject

from src.application.use_cases.onboarding.commands.process import ProcessDueOnboardingNudges
from src.infrastructure.taskiq.broker import broker


@broker.task(schedule=[{"cron": "*/10 * * * *"}])
@inject(patch_module=True)
async def process_onboarding_nudges_task(
    process_due_nudges: FromDishka[ProcessDueOnboardingNudges],
) -> None:
    await process_due_nudges.system()
