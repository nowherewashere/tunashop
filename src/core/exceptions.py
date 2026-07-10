from datetime import datetime
from typing import Union


class MenuRenderError(Exception): ...


class PermissionDeniedError(Exception): ...


class UserNotFoundError(Exception):
    def __init__(self, user_id: Union[int, str, None] = None) -> None:
        self.user_id = user_id
        super().__init__(f"User with id '{user_id}' not found" if user_id else "User not found")


class FileNotFoundError(Exception): ...


class LogsToFileDisabledError(Exception):
    def __init__(self) -> None:
        super().__init__("Logging to file is disabled in configuration")


class PlanError(Exception): ...


class SquadsEmptyError(PlanError): ...


class TrialDurationError(PlanError): ...


class PlanNameAlreadyExistsError(PlanError): ...


class UserAlreadyAllowedError(PlanError): ...


class DurationAlreadyExistsError(PlanError): ...


class PriceNotFoundError(PlanError): ...


class GatewayNotConfiguredError(Exception): ...


class PurchaseError(Exception): ...


class TrialNotAvailableError(Exception): ...


class MenuEditorInvalidPayloadError(Exception): ...


class BlacklistSourceAlreadyExistsError(Exception): ...


class CooldownError(Exception):
    def __init__(self, available_at: datetime) -> None:
        self.available_at = available_at
        super().__init__(f"Cooldown active until {available_at}")


class PromocodeError(Exception): ...


class PromocodeNotFoundError(PromocodeError): ...


class PromocodeNotAvailableError(PromocodeError): ...


class PromocodeExpiredError(PromocodeNotAvailableError): ...


class PromocodeAlreadyActivatedError(PromocodeError): ...


class EmailDeliveryError(Exception): ...


class EmailDeliveryDisabledError(Exception): ...


class ReferralError(Exception): ...


class InsufficientBalanceError(ReferralError):
    """Balance is below the amount required to pay for the chosen plan (full-cover)."""


class BalanceNegativeError(ReferralError):
    """Balance is below zero (a chargeback landed): block payouts + pay-with-balance."""


class PayoutLockedError(ReferralError):
    """An open payout (requested/processing) already exists: single-open-payout lock."""


class PayoutBelowMinimumError(ReferralError):
    """Balance is below the payout minimum (REFERRAL_PAYOUT_MIN_KOP / STARS_MIN_KOP)."""


class PayoutNoTelegramError(ReferralError):
    """A Stars payout was requested for a user with no linked telegram_id."""


class PayoutMethodUnavailableError(ReferralError):
    """The chosen payout method is disabled or not configured (e.g. Stars off)."""
