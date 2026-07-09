from typing import Final

from .base import BaseConfig

# PAYOUT_MODE values.
PAYOUT_MODE_OPERATOR: Final[str] = "operator"  # beta: a human settles from the queue
PAYOUT_MODE_AUTO: Final[str] = "auto"  # future: automated treasury (behind the provider seam)


class PayoutConfig(BaseConfig, env_prefix="PAYOUT_"):
    """Payout execution config (referral spec §5.5/§10).

    Beta runs ``mode=operator``: ``requestPayout*`` just enqueues ``requested`` and a
    human operator settles from the bot admin queue. ``auto`` is a future drop-in.
    """

    mode: str = PAYOUT_MODE_OPERATOR  # operator | auto
    crypto_asset: str = "USDT"
    crypto_network: str = "TRC20"
    # Weekly Monday 09:00 crypto batch (runCryptoBatch).
    batch_cron: str = "0 9 * * 1"
