import html
import re
import unicodedata
from calendar import monthrange
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Final, Optional, Union

from src.core.constants import UNLIMITED_EXPIRE_YEAR
from src.core.enums import PlanType
from src.core.utils.time import datetime_now

_GB_FACTOR: Final[Decimal] = Decimal(1024**3)
_HTML_RE = re.compile(r"<[^>]*>")
_URL_RE = re.compile(r"(?i)\b(?:https?://|www\.|tg://|t\.me/|telegram\.me/|joinchat/)\S+")


def _round_decimal(value: Decimal) -> int:
    result = value.quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    return max(0, int(result))


def user_name_clean(name: Optional[str], telegram_id: int) -> str:
    if not name:
        return f"{telegram_id}"

    text = html.unescape(name)
    text = unicodedata.normalize("NFKC", text)

    text = _HTML_RE.sub("", text)
    text = _URL_RE.sub("", text)
    text = text.replace("<", "").replace(">", "").replace("&", "")

    allowed_prefixes = {"L", "N"}
    allowed_symbols = {"$", "_", "-", "."}

    chars: list[str] = []

    for char in text:
        cat = unicodedata.category(char)

        if cat == "Mn":
            continue

        if cat[0] in allowed_prefixes or char in allowed_symbols or cat == "Zs":
            chars.append(char)

    cleaned = " ".join("".join(chars).split())

    if not cleaned:
        return f"{telegram_id}"

    if len(cleaned) > 32:
        cleaned = cleaned[:32]

    return cleaned


def event_to_key(class_name: str) -> str:
    snake = re.sub(r"(?<!^)(?=[A-Z])", "_", class_name).lower()
    formatted_key = snake.replace("_", "-")
    return f"event-{formatted_key}"


def gb_to_bytes(value: Optional[int]) -> int:
    if not value:
        return 0

    return _round_decimal(Decimal(value) * _GB_FACTOR)


def bytes_to_gb(value: Optional[int]) -> int:
    if not value:
        return 0

    return _round_decimal(Decimal(value) / _GB_FACTOR)


def quota_months(duration_days: int) -> int:
    """How many months of pool quota a plan of ``duration_days`` grants.

    A pool quota is priced per month, so a longer term simply gets a proportionally
    larger one — spent across the whole term rather than reset every month. Only exact
    multiples of 30 scale: the catalogue is built from 30/90/180/360, and stretching an
    odd term (a 3-day trial, a 365-day leftover) into a fractional quota would produce
    numbers nobody chose. Everything else, including the open-ended ``0``, gets ×1.

    Single source of the rule — the snapshot writes it into the frozen quota, and the
    offer surfaces re-derive it to show what a given term will actually grant.
    """
    if duration_days > 0 and duration_days % 30 == 0:
        return duration_days // 30

    return 1


def percent(part: Union[int, float], whole: Union[int, float]) -> float:
    if whole == 0:
        return 0

    percent = (part / whole) * 100
    return round(percent, 2)


def country_code_to_flag(code: str) -> str:
    if not code.isalpha() or len(code) != 2:
        return "🏴‍☠️"

    return "".join(chr(ord("🇦") + ord(c.upper()) - ord("A")) for c in code)


def days_to_datetime(value: int, year: int = UNLIMITED_EXPIRE_YEAR) -> datetime:
    dt = datetime_now()

    if value == 0:  # UNLIMITED for panel
        try:
            return dt.replace(year=year)
        except ValueError:
            last_day = monthrange(year, dt.month)[1]
            return dt.replace(year=year, day=min(dt.day, last_day))

    return dt + timedelta(days=value)


def normalize_channel_id(value: Union[str, int]) -> int:
    channel_id = int(value)
    if not str(channel_id).startswith("-100"):
        channel_id = int(f"-100{abs(channel_id)}")
    return channel_id


def limits_to_plan_type(traffic: int, devices: int) -> PlanType:
    has_traffic = traffic > 0
    has_devices = devices > 0

    if has_traffic and has_devices:
        return PlanType.BOTH
    elif has_traffic:
        return PlanType.TRAFFIC
    elif has_devices:
        return PlanType.DEVICES
    else:
        return PlanType.UNLIMITED
