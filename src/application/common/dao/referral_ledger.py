from typing import Optional, Protocol, runtime_checkable

from src.application.dto import BalanceSpendDto, PayoutDto, ReferralEventDto


@runtime_checkable
class ReferralLedgerDao(Protocol):
    """The money referral ledger (referral spec §2/§4).

    All amounts are kopecks. The six displayed stats are *derived*: EARNED / SPENT
    / WITHDRAWN are pure ``SUM`` queries; there is no cached balance column.
    """

    # --- earning side (referral_events) ---
    async def add_commission(self, event: ReferralEventDto) -> bool:
        """Insert a commission row, idempotent on ``payment_id``.

        Returns ``True`` if a new row was inserted, ``False`` if this
        ``payment_id`` was already recorded (duplicate webhook / retry)."""
        ...

    async def get_earned_kop(self, referrer_id: int) -> int: ...

    async def get_paying_count(self, referrer_id: int) -> int:
        """Distinct referred users with at least one commission row."""
        ...

    # --- spend side (balance_spends) ---
    async def add_balance_spend(self, spend: BalanceSpendDto) -> BalanceSpendDto: ...

    async def get_spent_kop(self, user_id: int) -> int: ...

    # --- withdrawal side (payouts) ---
    async def get_withdrawn_kop(self, user_id: int) -> int: ...

    async def get_open_payout(self, user_id: int) -> Optional[PayoutDto]:
        """The user's single open payout (``requested``/``processing``), if any."""
        ...

    async def create_payout(self, payout: PayoutDto) -> PayoutDto: ...

    async def get_payout(self, payout_id: int) -> Optional[PayoutDto]: ...

    async def list_payouts_by_status(
        self, status: str, limit: int = 50, offset: int = 0
    ) -> list[PayoutDto]: ...

    async def count_payouts_by_status(self, status: str) -> int: ...

    async def get_last_crypto_wallet(self, user_id: int) -> Optional[PayoutDto]:
        """Most recent payout carrying a crypto wallet, to prefill repeat payouts."""
        ...

    # --- operator transitions (each stamps operator_id + processed_at) ---
    async def mark_processing(self, payout_id: int, operator_id: Optional[int]) -> None: ...

    async def mark_paid(
        self,
        payout_id: int,
        operator_id: int,
        *,
        tx_hash: Optional[str] = None,
        gift_ref: Optional[str] = None,
    ) -> None:
        """Settle a payout: crypto stamps ``tx_hash``, stars stamps ``gift_ref``."""
        ...

    async def mark_rejected(self, payout_id: int, operator_id: int, reason: str) -> None: ...

    async def collect_crypto_batch(self, batch_id: str) -> list[PayoutDto]:
        """Move all ``requested`` crypto payouts to ``processing`` under ``batch_id``
        (the weekly Monday batch). Returns the collected payouts."""
        ...
