from typing import Any

from aiogram_dialog import DialogManager
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject

from src.application.common.dao import PaymentGatewayDao, SettingsDao
from src.application.dto import PaymentGatewayDto
from src.application.dto.payment_gateway import PlategaGatewaySettingsDto
from src.core.config import AppConfig
from src.core.enums import Currency, PaymentGatewayType, PlategaPaymentMethod

# Settings fields that must never appear in the generic text-field editor (edited via a
# dedicated screen instead).
_NON_EDITABLE_SETTINGS: frozenset[str] = frozenset({"display_name", "methods"})


@inject
async def gateways_getter(
    dialog_manager: DialogManager,
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    **kwargs: Any,
) -> dict[str, Any]:
    gateways: list[PaymentGatewayDto] = await payment_gateway_dao.get_all(sorted=False)

    formatted_gateways = [
        {
            "id": gateway.id,
            "gateway_type": gateway.type,
            "is_active": gateway.is_active,
        }
        for gateway in gateways
    ]

    return {
        "gateways": formatted_gateways,
    }


@inject
async def gateway_getter(
    dialog_manager: DialogManager,
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    **kwargs: Any,
) -> dict[str, Any]:
    config: AppConfig = kwargs["config"]
    gateway_id = dialog_manager.dialog_data["gateway_id"]
    gateway = await payment_gateway_dao.get_by_id(gateway_id)

    if not gateway:
        raise ValueError(f"Gateway '{gateway_id}' not found")

    if not gateway.settings:
        raise ValueError(f"Gateway '{gateway_id}' has not settings")

    settings = gateway.settings.as_list
    display_name_field = [s for s in settings if s["field"] == "display_name"]
    other_settings = [s for s in settings if s["field"] not in _NON_EDITABLE_SETTINGS]

    return {
        "id": gateway.id,
        "gateway_type": gateway.type,
        "is_active": gateway.is_active,
        "display_name_field": display_name_field,
        "settings": other_settings,
        "webhook": config.get_webhook(gateway.type),
        "requires_webhook": gateway.requires_webhook,
        # Platega exposes an extra "payment methods" screen (СБП / карта / крипта …).
        "is_platega": gateway.type == PaymentGatewayType.PLATEGA,
    }


def _method_label(method: PlategaPaymentMethod, custom: Any) -> str:
    if isinstance(custom, str) and custom.strip():
        return custom
    return method.default_label


@inject
async def platega_methods_getter(
    dialog_manager: DialogManager,
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    **kwargs: Any,
) -> dict[str, Any]:
    gateway_id = dialog_manager.dialog_data["gateway_id"]
    gateway = await payment_gateway_dao.get_by_id(gateway_id)

    if not gateway or not isinstance(gateway.settings, PlategaGatewaySettingsDto):
        raise ValueError(f"Gateway '{gateway_id}' is not a Platega gateway")

    configs = {m.id: m for m in (gateway.settings.methods or [])}
    methods = [
        {
            "id": method.value,
            "enabled": 1 if (configs.get(method.value) and configs[method.value].enabled) else 0,
            "label": _method_label(
                method, configs[method.value].label if method.value in configs else None
            ),
        }
        for method in PlategaPaymentMethod
    ]

    return {
        "gateway_type": gateway.type,
        "methods": methods,
    }


@inject
async def platega_method_label_getter(
    dialog_manager: DialogManager,
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    **kwargs: Any,
) -> dict[str, Any]:
    gateway_id = dialog_manager.dialog_data["gateway_id"]
    method_id = dialog_manager.dialog_data["selected_method_id"]
    gateway = await payment_gateway_dao.get_by_id(gateway_id)

    if not gateway or not isinstance(gateway.settings, PlategaGatewaySettingsDto):
        raise ValueError(f"Gateway '{gateway_id}' is not a Platega gateway")

    method = PlategaPaymentMethod(method_id)
    config = next((m for m in (gateway.settings.methods or []) if m.id == method_id), None)

    return {
        "gateway_type": gateway.type,
        "method_label": _method_label(method, config.label if config else None),
        "is_custom": bool(config and config.label),
    }


@inject
async def field_getter(
    dialog_manager: DialogManager,
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    **kwargs: Any,
) -> dict[str, Any]:
    gateway_id = dialog_manager.dialog_data["gateway_id"]
    selected_field = dialog_manager.dialog_data["selected_field"]

    gateway = await payment_gateway_dao.get_by_id(gateway_id)

    if not gateway:
        raise ValueError(f"Gateway '{gateway_id}' not found")

    if not gateway.settings:
        raise ValueError(f"Gateway '{gateway_id}' has not settings")

    return {
        "gateway_type": gateway.type,
        "field": selected_field,
        "is_empty": getattr(gateway.settings, selected_field, None) is None,
    }


@inject
async def currency_getter(
    dialog_manager: DialogManager,
    settings_dao: FromDishka[SettingsDao],
    **kwargs: Any,
) -> dict[str, Any]:
    settings = await settings_dao.get()
    return {
        "currency_list": [
            {
                "symbol": currency.symbol,
                "currency": currency.value,
                "enabled": currency == settings.default_currency,
            }
            for currency in Currency
        ]
    }


@inject
async def placement_getter(
    dialog_manager: DialogManager,
    payment_gateway_dao: FromDishka[PaymentGatewayDao],
    **kwargs: Any,
) -> dict[str, Any]:
    gateways: list[PaymentGatewayDto] = await payment_gateway_dao.get_all()

    formatted_gateways = [
        {
            "id": gateway.id,
            "gateway_type": gateway.type,
            "is_active": gateway.is_active,
        }
        for gateway in gateways
    ]

    return {
        "gateways": formatted_gateways,
    }
