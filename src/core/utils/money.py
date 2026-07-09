def kop_to_rub(kop: int) -> str:
    """Format kopecks as a human ₽ amount string (no currency symbol).

    Whole rubles render without decimals; fractional amounts keep two places.
    Thousands are grouped with a thin space (Russian convention): ``1 340``.
    """
    if kop % 100 == 0:
        return f"{kop // 100:,}".replace(",", " ")
    return f"{kop / 100:,.2f}".replace(",", " ")


def mask_wallet(wallet: str) -> str:
    """Mask a crypto wallet for display: ``TABCDE…WXYZ``."""
    wallet = wallet.strip()
    if len(wallet) <= 12:
        return wallet
    return f"{wallet[:6]}…{wallet[-4:]}"
