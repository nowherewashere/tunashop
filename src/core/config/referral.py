from .base import BaseConfig


class ReferralConfig(BaseConfig, env_prefix="REFERRAL_"):
    """Money referral program parameters (referral spec §10).

    Static economic parameters only. The runtime on/off toggle stays in
    ``settings.referral.enable`` (DB); the second referral link base lives on
    ``AppConfig`` (``config.referral_site_url`` ← ``REFERRAL_SITE_URL``).
    """

    # Commission rate in basis points: 5000 = 50.00%.
    rate_bp: int = 5000
    # Minimum balance to request a crypto payout (kopecks): 100000 = 1000 ₽.
    payout_min_kop: int = 100_000
    # NOTE: the referred-friend trial length is NOT configured here. It is data-driven
    # via a trial Plan with availability=INVITED (picked by GetAvailableTrial for users
    # with a referral row) — single source of truth, editable without a rebuild.
