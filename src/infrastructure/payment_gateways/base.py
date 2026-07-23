from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Optional, Protocol, Union
from uuid import UUID

import orjson
from aiogram import Bot
from fastapi import Request, Response
from httpx import AsyncClient, Timeout
from loguru import logger

from src.application.dto import PaymentGatewayDto, PaymentResultDto
from src.core.config import AppConfig
from src.core.constants import T_ME
from src.core.enums import TransactionStatus
from src.core.utils.log_throttle import LogThrottle, log_throttled
from src.core.utils.net import (
    CF_CONNECTING_IP_HEADER,
    FORWARDED_FOR_HEADER,
    UNKNOWN_IP,
    is_ip_in_networks,
    resolve_client_ip,
)

# Shared across gateway instances on purpose: instances are built per request, so a
# per-instance throttle would reset every time and suppress nothing.
_REJECTION_LOG = LogThrottle()


class PaymentGatewayFactory(Protocol):
    def __call__(self, gateway: "PaymentGatewayDto") -> "BasePaymentGateway": ...


class BasePaymentGateway(ABC):
    data: PaymentGatewayDto
    bot: Bot

    _bot_username: Optional[str]

    NETWORKS: list[str] = []

    def __init__(self, gateway: PaymentGatewayDto, bot: Bot, config: AppConfig) -> None:
        self.data = gateway
        self.bot = bot
        self.config = config
        self._bot_username: Optional[str] = None

        # Settled-after-fee amount for the metrics payment event (spec §4). A gateway
        # whose webhook exposes the PSP fee sets this inside ``handle_webhook``; the
        # payments endpoint then persists it onto the transaction. Left None when the
        # gateway's webhook carries no fee — net stays unknown rather than guessed.
        #
        # TODO(metrics net_rub): no gateway populates this yet — the real PSP is not
        # chosen. Once it is, set ``self.settled_amount`` from that provider's webhook
        # body. The whole downstream pipeline (persist → transactions.net_amount →
        # payment event ``net``) is already wired; this is the only missing line.
        self.settled_amount: Optional[Decimal] = None

        logger.debug(f"{self.__class__.__name__} Initialized")

    @abstractmethod
    async def handle_create_payment(
        self, amount: Decimal, details: str, payment_method: int | None = None
    ) -> PaymentResultDto: ...

    @abstractmethod
    async def handle_webhook(
        self,
        request: Request,
    ) -> Union[tuple[UUID, TransactionStatus], None]: ...

    async def build_webhook_response(self, request: Request) -> Response:
        return Response(status_code=200)

    async def _get_bot_redirect_url(self) -> str:
        if self._bot_username is None:
            self._bot_username = (await self.bot.get_me()).username
        return f"{T_ME}{self._bot_username}"

    async def _get_webhook_data(self, request: Request) -> dict:
        try:
            data = orjson.loads(await request.body())
            logger.debug(f"Webhook data: {data}")

            if not isinstance(data, dict):
                raise ValueError("Payload is not a dictionary")

            return data
        except (orjson.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse webhook payload: {e}")
            raise ValueError("Invalid webhook payload") from e

    def _make_client(
        self,
        base_url: str,
        auth: Optional[tuple[str, str]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: float = 30.0,
    ) -> AsyncClient:
        return AsyncClient(base_url=base_url, auth=auth, headers=headers, timeout=Timeout(timeout))

    def _is_test_payment(self, payment_id: str) -> bool:
        return payment_id.startswith("test:")

    def _is_ip_trusted(self, ip: str) -> bool:
        return is_ip_in_networks(ip, self.NETWORKS)

    def _log_rejection(self, kind: str, message: str, level: str = "WARNING") -> None:
        """Report a rejected webhook, at most once per interval per kind.

        Anyone can POST at these endpoints, so one line per rejection let an
        attacker drive disk writes and drown out the genuine alerts. ``kind`` must
        stay low-cardinality — never an IP or other caller-supplied value.
        """
        log_throttled(_REJECTION_LOG, f"{kind}:{self.__class__.__name__}", level, message)

    def _log_untrusted_ip(self, ip: str) -> None:
        self._log_rejection(
            "untrusted-ip", f"Webhook received from untrusted IP: '{ip}'", "CRITICAL"
        )

    def _get_ip(self, request: Request) -> str:
        """Source address of the webhook call.

        Resolved through the shared walker so the provider allowlists below key on
        a hop we can actually attribute; reading the client-settable first hop (as
        this used to) made them spoofable. They stay defence in depth regardless —
        the signature check in each gateway is the real gate.
        """
        ip = resolve_client_ip(
            peer_ip=request.client.host if request.client else None,
            forwarded_for=request.headers.get(FORWARDED_FOR_HEADER),
            trusted_proxy_cidrs=self.config.trusted_proxy_cidrs,
            proxy_header_ip=request.headers.get(CF_CONNECTING_IP_HEADER),
            trust_proxy_header=self.config.trust_cf_connecting_ip,
        )

        if ip == UNKNOWN_IP:
            raise PermissionError("Client IP could not be determined from the request")

        return ip
