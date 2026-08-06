from datetime import datetime, timedelta
from typing import Callable, Iterable, Mapping, Optional, Sequence

from aiogram_dialog import DialogManager
from aiogram_dialog.widgets.common.when import Whenable

from src.application.common import TranslatorRunner
from src.application.common.policy import Permission, PermissionPolicy
from src.application.dto import (
    PlanPoolQuotaDto,
    PoolUsageViewDto,
    TelegramUserDto,
    TrafficPoolDto,
)
from src.core.constants import POOL_RESET_DATE_FORMAT, USER_KEY
from src.core.enums import Role
from src.core.utils.i18n_helpers import i18n_format_bytes_to_unit
from src.core.utils.time import datetime_now


def _bytes(i18n: TranslatorRunner, value: int) -> str:
    key, kw = i18n_format_bytes_to_unit(value)
    return i18n.get(key, **kw)


def plan_pool_lines(
    i18n: TranslatorRunner,
    quotas: Iterable[PlanPoolQuotaDto],
    pools_by_id: Mapping[int, TrafficPoolDto],
) -> str:
    """Pre-render the pool lines of a plan being *offered*, or '' when it meters none.

    Quota and period only. Nobody holds this plan yet, so no accounting window exists
    and there is no remainder to state — that is what ``subscription_pool_lines`` is
    for. A quota whose pool row is gone is skipped rather than rendered unnamed, the
    same rule ``_plan_pool_offers`` applies in the web cabinet.

    Assembled here rather than in fluent because a plan can meter several pools and
    an FTL pattern cannot loop — same arrangement as the locations line.
    """
    return "".join(
        i18n.get(
            "frg-plan-pool",
            name=pools_by_id[quota.pool_id].name,
            quota=_bytes(i18n, quota.quota_bytes),
            strategy_type=quota.reset_strategy,
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

        lines.append(
            i18n.get(
                "frg-plan-pool-usage",
                name=view.name,
                state=state,
                quota=_bytes(i18n, view.quota_bytes),
                remaining=_bytes(i18n, remaining or 0),
                # A pre-formatted string (not a datetime) so the FTL only interpolates
                # it, and 0 for "never resets" so it can drop the clause — the same
                # contract the pool notifications use.
                reset=view.reset_at.strftime(POOL_RESET_DATE_FORMAT) if view.reset_at else 0,
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
