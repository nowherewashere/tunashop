def kop_to_rub(kop: int) -> str:
    """Format kopecks as a human ₽ amount string (no currency symbol).

    Whole rubles render without decimals; fractional amounts keep two places.
    Thousands are grouped with a thin space (Russian convention): ``1 340``.
    """
    if kop % 100 == 0:
        return f"{kop // 100:,}".replace(",", " ")
    return f"{kop / 100:,.2f}".replace(",", " ")


def kop_to_stars(kop: int, rate_kop_per_star: int) -> int:
    """Whole Stars for a kopeck balance at a kopecks-per-Star rate (floor).

    Single source of truth for the RUB→⭐ conversion, shared by the request use case
    and the withdraw-screen preview. A non-positive rate means Stars are unconfigured
    → 0 (callers treat that as "Stars unavailable").
    """
    if rate_kop_per_star <= 0:
        return 0
    return kop // rate_kop_per_star


def mask_wallet(wallet: str) -> str:
    """Mask a crypto wallet for display: ``TABCDE…WXYZ``."""
    wallet = wallet.strip()
    if len(wallet) <= 12:
        return wallet
    return f"{wallet[:6]}…{wallet[-4:]}"
