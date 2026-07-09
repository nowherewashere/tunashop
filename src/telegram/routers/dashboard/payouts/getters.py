from typing import Any, Optional

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common.dao import ReferralLedgerDao, UserDao
from src.application.dto import UserDto
from src.application.use_cases.referral.commands.operator import (
    GetPayoutQueue,
    GetPayoutQueueDto,
)
from src.core.utils.money import kop_to_rub
from src.infrastructure.database.models.referral_ledger import (
    PAYOUT_PROCESSING,
    PAYOUT_REQUESTED,
)


def _user_label(user: Optional[UserDto]) -> str:
    if user is None:
        return "—"
    if user.username:
        return f"@{user.username}"
    if user.telegram_id:
        return str(user.telegram_id)
    if user.email:
        return user.email
    return str(user.id)


@inject
async def payout_queue_getter(
    dialog_manager: DialogManager,
    get_payout_queue: FromDishka[GetPayoutQueue],
    **kwargs: Any,
) -> dict[str, Any]:
    # Show both open states so the operator can drive requested → processing → paid
    # without leaving the queue (requested first, then in-flight).
    requested = await get_payout_queue.system(GetPayoutQueueDto(status=PAYOUT_REQUESTED))
    processing = await get_payout_queue.system(GetPayoutQueueDto(status=PAYOUT_PROCESSING))

    items: list[dict[str, Any]] = []
    for item in list(requested) + list(processing):
        payout = item.payout
        mark = "🆕" if payout.status == PAYOUT_REQUESTED else "⏳"
        items.append(
            {
                "id": payout.id,
                "label": f"{mark} {kop_to_rub(payout.amount_kop)} ₽ · {_user_label(item.user)}",
            }
        )

    return {
        "payout_items": items,
        "has_items": bool(items),
        "count": len(items),
    }


@inject
async def payout_detail_getter(
    dialog_manager: DialogManager,
    referral_ledger_dao: FromDishka[ReferralLedgerDao],
    user_dao: FromDishka[UserDao],
    **kwargs: Any,
) -> dict[str, Any]:
    payout_id = dialog_manager.dialog_data.get("payout_id")
    payout = await referral_ledger_dao.get_payout(int(payout_id)) if payout_id else None
    if not payout:
        return {"found": False, "is_requested": False, "is_open": False}

    user = await user_dao.get_by_id(payout.user_id)
    return {
        "found": True,
        "payout_id": payout.id,
        "status": payout.status,
        "is_requested": payout.status == PAYOUT_REQUESTED,
        "is_open": payout.status in (PAYOUT_REQUESTED, PAYOUT_PROCESSING),
        "amount": kop_to_rub(payout.amount_kop),
        "user_label": _user_label(user),
        "email": (user.email if user else None) or "—",
        "wallet": payout.crypto_wallet or "—",
        "asset": payout.crypto_asset or "—",
        "network": payout.crypto_network or "—",
        "tx_hash": payout.tx_hash or "—",
    }
