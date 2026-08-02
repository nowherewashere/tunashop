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


class OAuthExchangeError(Exception):
    """A provider exchange failed (network, HTTP error, bad token, bad claims).

    Always fails the sign-in. Unlike the captcha, this path must never fail open:
    an unreachable token endpoint is not evidence that anyone is who they claim.
    """


class SupportUnavailableError(Exception):
    """Support is disabled (SUPPORT_ENABLED=false) or its operator group is unset."""


class UserDeletionError(Exception):
    """A user delete was refused before anything was touched."""


class UserDeletionSelfError(UserDeletionError):
    """The operator aimed the delete at their own account."""


class UserDeletionPrivilegedError(UserDeletionError):
    """The target holds a staff role: demote first, so it is never a slip of the thumb."""


class UserDeletionReferralLedgerError(UserDeletionError):
    """The target's payments earned commission for whoever invited them.

    Those rows cascade off ``referral_events.referred_id``, so deleting this account
    would quietly shrink a *different*, living user's balance.
    """


class UserDeletionPanelError(UserDeletionError):
    """The Remnawave user could not be removed, so nothing local was deleted.

    Deliberately fatal: a panel user left behind keeps the username
    (``remnashop_<telegram_id>``) taken, and the person's next trial would fail to
    create — the exact opposite of a clean slate.
    """


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
