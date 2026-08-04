from typing import Final

from src.application.common import Interactor

from .commands.attachment import AttachReferral
from .commands.balance import PayWithBalance
from .commands.commission import RecordReferralCommission
from .commands.operator import (
    CompletePayout,
    GetPayoutQueue,
    RejectPayout,
    RunCryptoBatch,
    StartPayout,
)
from .commands.payout import (
    ChangeCryptoPayoutWallet,
    RequestCryptoPayout,
    RequestPayoutStars,
)
from .queries.code import GenerateReferralQr, ValidateReferralCode
from .queries.summary import GetReferralSummary

REFERRAL_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    AttachReferral,
    ValidateReferralCode,
    GenerateReferralQr,
    RecordReferralCommission,
    GetReferralSummary,
    PayWithBalance,
    RequestCryptoPayout,
    ChangeCryptoPayoutWallet,
    RequestPayoutStars,
    StartPayout,
    CompletePayout,
    RejectPayout,
    GetPayoutQueue,
    RunCryptoBatch,
)
