from datetime import datetime, timedelta
from decimal import Decimal
from typing import Callable, Final, Iterable, Mapping, Optional, Sequence, Union

from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.common.when import Whenable

from src.application.common import TranslatorRunner
from src.application.common.policy import Permission, PermissionPolicy
from src.application.dto import (
    PlanPoolQuotaDto,
    PoolQuotaSnapshotDto,
    PoolUsageViewDto,
    TelegramUserDto,
    TrafficPoolDto,
)
from src.core.constants import USER_KEY
from src.core.enums import Role
from src.core.utils.i18n_keys import ByteUnitKey
from src.core.utils.time import datetime_now

_GB: Final[Decimal] = Decimal(1024**3)


def _gb(value: int) -> float:
    """Bytes as gigabytes, two decimals — the unit pool quotas are authored in.

    Pools are always stated in GB and never promoted to TB. An admin types «500» and a
    3-month term multiplies it to 1500; rendering that as «1,46 ТБ» would both lose the
    number they chose and disagree with every other surface that repeats it.
    """
    return float(Decimal(value) / _GB) if value else 0.0


def _amount(i18n: TranslatorRunner, value: int) -> str:
    """A pool figure with no unit — «495», «1500»."""
    return i18n.get("frg-pool-amount", value=_gb(value))


def _quota(i18n: TranslatorRunner, value: int) -> str:
    """A pool figure with its unit — «500 ГБ»."""
    return i18n.get(ByteUnitKey.GIGABYTE, value=_gb(value))


def _pair(i18n: TranslatorRunner, part: int, whole: int) -> tuple[str, str]:
    """``(part, whole)`` for a «495 / 500 ГБ» pair — one unit, stated once at the end.

    Both halves go through fluent so they are formatted by the same rules; building one
    of them in Python instead produced «0.49 / 5,86 ТБ», mixing decimal separators
    inside a single line.
    """
    return _amount(i18n, max(0, part)), _quota(i18n, whole)


def plan_pool_lines(
    i18n: TranslatorRunner,
    quotas: Iterable[Union[PlanPoolQuotaDto, PoolQuotaSnapshotDto]],
    pools_by_id: Mapping[int, TrafficPoolDto],
    *,
    months: int = 1,
    per_month: bool = False,
) -> str:
    """Pre-render the pool lines of a plan being *offered*, or '' when it meters none.

    Nobody holds this plan yet, so no accounting window exists and there is no
    remainder to state — that is what ``subscription_pool_lines`` is for.

    The quota is priced per month, which leaves two honest ways to state it and the
    caller picks by what it knows. A shelf that has not asked for a term yet says
    ``per_month`` («500 ГБ/мес»); once a duration is on the screen the caller passes
    the matching ``months`` and the line states the total that term actually buys
    («1500 ГБ»). Never both — «1500 ГБ/мес» would be a lie either way round.

    A quota whose pool row is gone is skipped rather than rendered unnamed, the same
    rule ``_plan_pool_offers`` applies in the web cabinet. Assembled here rather than
    in fluent because a plan can meter several pools and an FTL pattern cannot loop.
    """
    return "".join(
        i18n.get(
            "frg-plan-pool",
            name=pools_by_id[quota.pool_id].name,
            quota=_quota(i18n, quota.quota_bytes * months),
            per_month=int(per_month),
        )
        for quota in quotas
        if quota.pool_id in pools_by_id and quota.quota_gb > 0
    )


def subscription_pool_lines(
    i18n: TranslatorRunner,
    views: Sequence[PoolUsageViewDto],
) -> str:
    """Pre-render the pool lines of a plan the user *holds*, or '' when it meters none.

    Shows what is left in the window the metering pass is actually judging, so the
    figure here and the verdict that withdraws the squad can never disagree.
    ``used_bytes is None`` means the panel could not be reached: that renders as
    "unknown", never as a full quota the user does not really have.

    No reset date: the quota is bought for the whole term and does not come back
    inside it, so there is no date to promise.
    """
    lines = []
    for view in views:
        remaining = view.remaining_bytes
        if view.is_exhausted:
            state = "EXHAUSTED"
        elif remaining is None:
            state = "UNKNOWN"
        else:
            state = "LEFT"

        left, quota = _pair(i18n, remaining or 0, view.quota_bytes)
        lines.append(
            i18n.get(
                "frg-plan-pool-usage",
                name=view.name,
                state=state,
                quota=quota,
                remaining=left,
            )
        )
    return "".join(lines)


def translate_or_literal(i18n: TranslatorRunner, value: str) -> str:
    """Resolve a plan name/description that may be a translation key or a literal.

    Admin-entered plan labels (e.g. "Pro") are not translation keys, so translating
    them would only log a spurious "key not found" warning. Return the translation
    when the key exists, otherwise the value itself — silently.
    """
    return i18n.get_optional(value) or value


def is_double_click(dialog_manager: DialogManager, key: str, cooldown: int = 10) -> bool:
    now = datetime_now()
    last_click_str: Optional[str] = dialog_manager.dialog_data.get(key)
    if last_click_str:
        last_click = datetime.fromisoformat(last_click_str.replace("Z", "+00:00"))
        if now - last_click < timedelta(seconds=cooldown):
            return True

    dialog_manager.dialog_data[key] = now.isoformat()
    return False


def require_permission(permission: Permission) -> Callable:
    def checker(
        data: dict,
        widget: Whenable,
        manager: DialogManager,
    ) -> bool:
        user: TelegramUserDto = manager.middleware_data[USER_KEY]
        return PermissionPolicy.has_permission(user, permission)

    return checker


def require_role(role: Role) -> Callable:
    def checker(
        data: dict,
        widget: Whenable,
        manager: DialogManager,
    ) -> bool:
        user: TelegramUserDto = manager.middleware_data[USER_KEY]
        return user.role >= role

    return checker
