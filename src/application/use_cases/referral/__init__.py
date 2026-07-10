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
from .commands.payout import RequestCryptoPayout, RequestPayoutStars
from .commands.rewards import AssignReferralRewards, GiveReferrerReward
from .queries.calculations import CalculateReferralReward
from .queries.code import GenerateReferralQr, ValidateReferralCode
from .queries.summary import GetReferralSummary

REFERRAL_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    AttachReferral,
    ValidateReferralCode,
    GenerateReferralQr,
    CalculateReferralReward,
    GiveReferrerReward,
    AssignReferralRewards,
    RecordReferralCommission,
    GetReferralSummary,
    PayWithBalance,
    RequestCryptoPayout,
    RequestPayoutStars,
    StartPayout,
    CompletePayout,
    RejectPayout,
    GetPayoutQueue,
    RunCryptoBatch,
)
