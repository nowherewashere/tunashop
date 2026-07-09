from dataclasses import dataclass

from src.application.common import Interactor
from src.application.common.dao import ReferralDao, ReferralLedgerDao
from src.application.dto import ReferralSummaryDto, UserDto


@dataclass(frozen=True)
class GetReferralSummaryDto:
    user_id: int


class GetReferralSummary(Interactor[GetReferralSummaryDto, ReferralSummaryDto]):
    """Derive the six displayed referral stats (referral spec §2).

    Pure DB sums — no cached balance column. ``Баланс`` is computed on the DTO as
    ``EARNED − SPENT − WITHDRAWN``; the identity
    ``Доход = Баланс + Выведено + Потрачено`` holds by construction.
    """

    required_permission = None

    def __init__(
        self,
        referral_dao: ReferralDao,
        referral_ledger_dao: ReferralLedgerDao,
    ) -> None:
        self.referral_dao = referral_dao
        self.referral_ledger_dao = referral_ledger_dao

    async def _execute(self, actor: UserDto, data: GetReferralSummaryDto) -> ReferralSummaryDto:
        user_id = data.user_id
        # Attribution is always first-level (single-tier), so this counts invited friends.
        invited = await self.referral_dao.get_referrals_count(user_id)
        paying = await self.referral_ledger_dao.get_paying_count(user_id)
        earned = await self.referral_ledger_dao.get_earned_kop(user_id)
        spent = await self.referral_ledger_dao.get_spent_kop(user_id)
        withdrawn = await self.referral_ledger_dao.get_withdrawn_kop(user_id)
        has_open_payout = await self.referral_ledger_dao.get_open_payout(user_id) is not None

        return ReferralSummaryDto(
            invited=invited,
            paying=paying,
            earned_kop=earned,
            spent_kop=spent,
            withdrawn_kop=withdrawn,
            has_open_payout=has_open_payout,
        )
