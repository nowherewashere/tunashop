from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common.dao import PlanDao, SettingsDao
from src.core.config import AppConfig
from src.core.utils.money import kop_to_rub


@inject
async def referral_getter(
    dialog_manager: DialogManager,
    config: AppConfig,
    settings_dao: FromDishka[SettingsDao],
    plan_dao: FromDishka[PlanDao],
    **kwargs: Any,
) -> dict[str, Any]:
    """The on/off switch is the only editable knob; everything else is env-driven.

    Showing the real numbers read-only beats an editor whose writes nothing honours —
    that was the trap the old points/extra-days screen fell into.
    """
    settings = await settings_dao.get()
    trial_days = (await plan_dao.get_invited_trial_days()) or 0

    return {
        "is_enable": settings.referral.enable,
        "rate": config.referral.rate_bp // 100,
        "trial_days": trial_days,
        "payout_min": kop_to_rub(config.referral.payout_min_kop),
        "payout_mode": config.payout.mode,
        "crypto_asset": config.payout.crypto_asset,
        "crypto_network": config.payout.crypto_network,
        "batch_cron": config.payout.batch_cron,
        "stars_enabled": int(config.stars.payout_enabled),
        "stars_rate": kop_to_rub(config.stars.rub_rate),
        "stars_min": kop_to_rub(config.stars.min_kop),
    }
