from typing import Final

from src.application.common.interactor import Interactor

from .commands.configuration import (
    MovePaymentGatewayUp,
    ResetPaymentGatewaySettingsField,
    SetPlategaMethodLabel,
    TogglePaymentGatewayActive,
    TogglePlategaMethod,
    UpdatePaymentGatewaySettings,
)
from .commands.payment import (
    CreateDefaultPaymentGateway,
    CreatePayment,
    CreateTestPayment,
    ProcessPayment,
)
from .queries.providers import GetPaymentGatewayInstance

GATEWAYS_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    GetPaymentGatewayInstance,
    MovePaymentGatewayUp,
    TogglePaymentGatewayActive,
    UpdatePaymentGatewaySettings,
    ResetPaymentGatewaySettingsField,
    TogglePlategaMethod,
    SetPlategaMethodLabel,
    CreateDefaultPaymentGateway,
    CreatePayment,
    CreateTestPayment,
    ProcessPayment,
)
