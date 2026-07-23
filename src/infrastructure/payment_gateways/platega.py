import hmac
from decimal import Decimal
from typing import Any, Final, Optional, Union, cast
from uuid import UUID

import orjson
from aiogram import Bot
from fastapi import Request
from httpx import AsyncClient, HTTPStatusError
from loguru import logger

from src.application.dto import PaymentGatewayDto, PaymentResultDto
from src.application.dto.payment_gateway import PlategaGatewaySettingsDto
from src.core.config import AppConfig
from src.core.enums import TransactionStatus

from .base import BasePaymentGateway


# https://docs.platega.io/
class PlategaGateway(BasePaymentGateway):
    _client: AsyncClient

    API_BASE: Final[str] = "https://app.platega.io"
    DEFAULT_MULTI_METHOD_ENDPOINT: Final[str] = "v2/transaction/process"
    DEFAULT_SINGLE_METHOD_ENDPOINT: Final[str] = "transaction/process"

    def __init__(self, gateway: PaymentGatewayDto, bot: Bot, config: AppConfig) -> None:
        super().__init__(gateway, bot, config)

        if not isinstance(self.data.settings, PlategaGatewaySettingsDto):
            raise TypeError(
                f"Invalid settings type: expected {PlategaGatewaySettingsDto.__name__}, "
                f"got {type(self.data.settings).__name__}"
            )

        self.settings = cast(PlategaGatewaySettingsDto, self.data.settings)
        if self.settings.merchant_id is None or self.settings.api_key is None:
            raise ValueError("Platega gateway is not configured")

        self.merchant_id = self.settings.merchant_id
        self.api_key = self.settings.api_key.get_secret_value()

        self._client = self._make_client(
            base_url=self.API_BASE,
            headers={
                "X-MerchantId": self.merchant_id,
                "X-Secret": self.api_key,
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        self.selected_payment_method: Optional[str] = None

    async def handle_create_payment(
        self, amount: Decimal, details: str, payment_method: int | None = None
    ) -> PaymentResultDto:
        # A user-selected method (from the in-bot picker) takes precedence over the
        # admin hard-pin. When either is set we hit the single-method endpoint and pass
        # the code; otherwise Platega renders its own multi-method page.
        effective_method = (
            payment_method if payment_method is not None else self.settings.payment_method
        )
        payload = await self._create_payment_payload(amount, details, effective_method)
        logger.debug(f"Creating payment payload: {payload}")
        endpoint = (
            self.DEFAULT_SINGLE_METHOD_ENDPOINT
            if effective_method is not None
            else self.DEFAULT_MULTI_METHOD_ENDPOINT
        )

        try:
            response = await self._client.post(endpoint, json=payload)
            response.raise_for_status()
            data = orjson.loads(response.content)
            return self._get_payment_data(data)

        except HTTPStatusError as e:
            logger.error(
                f"HTTP error creating payment. "
                f"Status: '{e.response.status_code}', Body: {e.response.text}"
            )
            raise
        except (KeyError, orjson.JSONDecodeError) as e:
            logger.error(f"Failed to parse response. Error: {e}")
            raise
        except Exception as e:
            logger.exception(f"An unexpected error occurred while creating payment: {e}")
            raise

    async def handle_webhook(self, request: Request) -> Union[tuple[UUID, TransactionStatus], None]:
        logger.debug(f"Received {self.__class__.__name__} webhook request")

        raw_body = await request.body()
        webhook_data = orjson.loads(raw_body)

        if not self._verify_webhook(request):
            raise PermissionError("Webhook verification failed")

        payment_id_str = webhook_data.get("id")
        if not payment_id_str:
            raise ValueError("Required field 'id' is missing")

        status = webhook_data.get("status")
        payment_id = UUID(payment_id_str)
        self.selected_payment_method = self._normalize_payment_method(
            webhook_data.get("paymentMethod")
        )

        match status:
            case "CONFIRMED":
                transaction_status = TransactionStatus.COMPLETED
            case "CANCELED":
                transaction_status = TransactionStatus.CANCELED
            case "CHARGEBACKED":
                transaction_status = TransactionStatus.REFUNDED
            case _:
                raise ValueError(f"Unsupported status: {status}")

        return payment_id, transaction_status

    async def _create_payment_payload(
        self, amount: Decimal, details: str, payment_method: int | None
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "paymentDetails": {
                "amount": float(amount),
                "currency": self.data.currency.value,
            },
            "description": details,
            "return": await self._get_bot_redirect_url(),
            "failedUrl": await self._get_bot_redirect_url(),
        }
        if payment_method is not None:
            payload["paymentMethod"] = payment_method

        return payload

    def _get_payment_data(self, data: dict[str, Any]) -> PaymentResultDto:
        transaction_id_str = data.get("transactionId")
        if not transaction_id_str:
            raise KeyError("Invalid response from API: missing 'transactionId'")

        payment_url = data.get("redirect") or data.get("url")
        if not payment_url:
            raise KeyError("Invalid response from API: missing 'redirect' or 'url'")

        return PaymentResultDto(id=UUID(transaction_id_str), url=str(payment_url))

    @staticmethod
    def _normalize_payment_method(value: Any) -> str | None:
        if value is None:
            return None

        payment_method = str(value).strip()
        return payment_method or None

    def _verify_webhook(self, request: Request) -> bool:
        """Authenticate a Platega callback by its static credential headers.

        Weaker than the other gateways by the provider's design: Cryptomus, CryptoPay
        and Remnawave sign the request *body*, so a tampered payload fails. Platega
        sends a fixed X-Secret instead, which proves only that the caller knows the
        shared secret — there is no body integrity and nothing binds a callback to a
        single delivery, so anyone holding that secret can forge or replay any
        payment. Consequences: the secret must never reach logs or error reports, and
        rotating it invalidates every forged copy at once.

        Platega publishes no source IP ranges, so NETWORKS is empty for this gateway
        and the edge deliberately does not allowlist /api/v1/payments/ either — doing
        so would reject every real callback (see deploy/nginx/nginx.conf). If the
        provider ever documents its egress, pin it in both places.
        """
        merchant_id = request.headers.get("X-MerchantId")
        secret = request.headers.get("X-Secret")

        if not merchant_id or not secret:
            self._log_rejection(
                "missing-headers", "Webhook is missing X-MerchantId or X-Secret headers"
            )
            return False

        merchant_id_ok = hmac.compare_digest(merchant_id, self.merchant_id)
        secret_ok = hmac.compare_digest(secret, self.api_key)

        if not merchant_id_ok or not secret_ok:
            self._log_rejection("bad-credentials", "Invalid Platega webhook credentials")
            return False

        return True
