from dataclasses import replace

from src.application.common import Interactor
from src.application.common.dao import ReferralDao, ReferralLedgerDao, UserDao
from src.application.common.policy import Permission
from src.application.dto import ReferralStatisticsDto, UserDto
from src.core.constants import (
    PAYOUT_PROCESSING,
    PAYOUT_REQUESTED,
)


class GetReferralStatistics(Interactor[None, ReferralStatisticsDto]):
    required_permission = Permission.VIEW_STATISTICS

    def __init__(
        self,
        referral_dao: ReferralDao,
        referral_ledger_dao: ReferralLedgerDao,
        user_dao: UserDao,
    ) -> None:
        self.referral_dao = referral_dao
        self.referral_ledger_dao = referral_ledger_dao
        self.user_dao = user_dao

    async def _execute(self, actor: UserDto, data: None) -> ReferralStatisticsDto:
        stats = await self.referral_dao.get_stats()

        paying = await self.referral_ledger_dao.get_total_paying_count()
        earned = await self.referral_ledger_dao.get_total_commission_kop()
        spent = await self.referral_ledger_dao.get_total_spent_kop()
        withdrawn = await self.referral_ledger_dao.get_total_withdrawn_kop()
        open_kop = await self.referral_ledger_dao.get_open_payouts_kop()
        # The queue is two open statuses, counted the same way GetPayoutQueue lists them.
        requested = await self.referral_ledger_dao.count_payouts_by_status(PAYOUT_REQUESTED)
        processing = await self.referral_ledger_dao.count_payouts_by_status(PAYOUT_PROCESSING)

        stats = replace(
            stats,
            paying_referrals=paying,
            total_earned_kop=earned,
            total_spent_kop=spent,
            total_withdrawn_kop=withdrawn,
            open_payouts_count=requested + processing,
            open_payouts_kop=open_kop,
        )

        if stats.top_referrer_id:
            referrer = await self.user_dao.get_by_id(stats.top_referrer_id)

            if referrer:
                stats = replace(
                    stats,
                    top_referrer_telegram_id=referrer.telegram_id,
                    top_referrer_email=referrer.email,
                    top_referrer_username=referrer.username,
                )

        return stats
