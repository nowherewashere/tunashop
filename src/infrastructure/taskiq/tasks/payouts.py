from dishka.integrations.taskiq import FromDishka, inject

from src.application.use_cases.referral.commands.operator import RunCryptoBatch
from src.infrastructure.taskiq.broker import broker

# Weekly Monday 09:00 crypto payout batch (spec §5.3). The cron is hardcoded here to
# match every other scheduled task in this package; PAYOUT_BATCH_CRON documents intent
# for when a dynamic (config-driven) scheduler is introduced.


@broker.task(schedule=[{"cron": "0 9 * * 1"}])
@inject(patch_module=True)
async def run_crypto_payout_batch_task(
    run_crypto_batch: FromDishka[RunCryptoBatch],
) -> None:
    await run_crypto_batch.system()
