from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, HTTPException, status

from src.application.common import BotService
from src.application.common.dao import ReferralLedgerDao, SettingsDao, SubscriptionDao
from src.application.dto import UserDto
from src.application.use_cases.referral.commands.balance import PayWithBalance, PayWithBalanceDto
from src.application.use_cases.referral.commands.payout import (
    RequestCryptoPayout,
    RequestCryptoPayoutDto,
)
from src.application.use_cases.referral.queries.summary import (
    GetReferralSummary,
    GetReferralSummaryDto,
)
from src.core.config import AppConfig
from src.core.enums import SubscriptionStatus
from src.core.exceptions import (
    BalanceNegativeError,
    InsufficientBalanceError,
    PayoutBelowMinimumError,
    PayoutLockedError,
    PlanError,
    PurchaseError,
    ReferralError,
)
from src.core.utils.money import mask_wallet
from src.web.schemas import (
    CryptoPayoutRequest,
    PayoutResponse,
    PayWithBalanceRequest,
    PayWithBalanceResponse,
    ReferralProgramResponse,
    ReferralRewardLevelResponse,
)

from ._common import CurrentUser

router = APIRouter(prefix="/referral", tags=["Public - Referral"])


def _require_referral_enabled(user: UserDto, enabled: bool) -> None:
    if not user.is_email_verified:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Referral program is available only for users with verified email",
        )
    if not enabled:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Referral program is disabled",
        )


@router.get("/program", response_model=ReferralProgramResponse)
@inject
async def get_referral_program(
    user: CurrentUser,
    config: FromDishka[AppConfig],
    bot_service: FromDishka[BotService],
    settings_dao: FromDishka[SettingsDao],
    referral_ledger_dao: FromDishka[ReferralLedgerDao],
    subscription_dao: FromDishka[SubscriptionDao],
    get_referral_summary: FromDishka[GetReferralSummary],
) -> ReferralProgramResponse:
    settings = await settings_dao.get()
    _require_referral_enabled(user, settings.referral.enable)

    current_subscription = await subscription_dao.get_current(user.id)
    if not current_subscription or current_subscription.current_status != SubscriptionStatus.ACTIVE:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Referral program is available only for users with active subscription",
        )

    summary = await get_referral_summary.system(GetReferralSummaryDto(user.id))
    last_wallet_payout = await referral_ledger_dao.get_last_crypto_wallet(user.id)

    reward_levels = [
        ReferralRewardLevelResponse(level=level.value, value=value)
        for level, value in sorted(
            settings.referral.reward.config.items(),
            key=lambda item: item[0].value,
        )
        if level.value <= settings.referral.level.value
    ]

    bot_referral_url = await bot_service.get_referral_url(user.referral_code)
    site_base = config.referral_site_url.rstrip("/")
    site_referral_url = f"{site_base}/r/{user.referral_code}" if site_base else None

    return ReferralProgramResponse(
        enabled=settings.referral.enable,
        referral_code=user.referral_code,
        bot_referral_url=bot_referral_url,
        site_referral_url=site_referral_url,
        invited_count=summary.invited,
        invited_with_payment_count=summary.paying,
        #
        balance_kop=summary.balance_kop,
        withdrawn_kop=summary.withdrawn_kop,
        spent_kop=summary.spent_kop,
        lifetime_kop=summary.lifetime_kop,
        payout_min_kop=config.referral.payout_min_kop,
        has_open_payout=summary.has_open_payout,
        crypto_asset=config.payout.crypto_asset,
        crypto_network=config.payout.crypto_network,
        last_wallet=(
            mask_wallet(last_wallet_payout.crypto_wallet)
            if last_wallet_payout and last_wallet_payout.crypto_wallet
            else None
        ),
        #
        reward_type=settings.referral.reward.type.value,
        reward_strategy=settings.referral.reward.strategy.value,
        accrual_strategy=settings.referral.accrual_strategy.value,
        max_level=settings.referral.level.value,
        reward_levels=reward_levels,
    )


@router.post("/payout/crypto", response_model=PayoutResponse)
@inject
async def request_crypto_payout(
    body: CryptoPayoutRequest,
    user: CurrentUser,
    settings_dao: FromDishka[SettingsDao],
    request_payout: FromDishka[RequestCryptoPayout],
) -> PayoutResponse:
    settings = await settings_dao.get()
    _require_referral_enabled(user, settings.referral.enable)

    try:
        payout = await request_payout.system(
            RequestCryptoPayoutDto(user=user, wallet=body.wallet)
        )
    except PayoutBelowMinimumError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except PayoutLockedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except BalanceNegativeError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except ReferralError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    return PayoutResponse(
        id=payout.id,
        status=payout.status,
        amount_kop=payout.amount_kop,
        method=payout.method,
        crypto_asset=payout.crypto_asset,
        crypto_network=payout.crypto_network,
    )


@router.post("/pay-with-balance", response_model=PayWithBalanceResponse)
@inject
async def pay_with_balance(
    body: PayWithBalanceRequest,
    user: CurrentUser,
    settings_dao: FromDishka[SettingsDao],
    pay: FromDishka[PayWithBalance],
) -> PayWithBalanceResponse:
    settings = await settings_dao.get()
    _require_referral_enabled(user, settings.referral.enable)

    try:
        result = await pay.system(
            PayWithBalanceDto(user=user, plan_id=body.plan_id, duration_days=body.duration_days)
        )
    except InsufficientBalanceError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except PayoutLockedError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except BalanceNegativeError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except PurchaseError as e:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(e)) from e
    except PlanError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e)) from e

    return PayWithBalanceResponse(
        ok=True,
        amount_kop=result.amount_kop,
        new_expire_at=result.new_expire_at.isoformat(),
        balance_kop=result.balance_kop,
    )
