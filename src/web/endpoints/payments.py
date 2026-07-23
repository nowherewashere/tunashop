from typing import Optional
from uuid import UUID

from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Request, Response, status
from loguru import logger

from src.application.common import EventPublisher
from src.application.common.dao import TransactionDao
from src.application.common.uow import UnitOfWork
from src.application.events import ErrorEvent
from src.application.use_cases.gateways.queries.providers import GetPaymentGatewayInstance
from src.core.config import AppConfig
from src.core.constants import API_V1, PAYMENTS_WEBHOOK_PATH
from src.core.enums import PaymentGatewayType, TransactionStatus
from src.core.exceptions import GatewayNotConfiguredError
from src.core.utils.log_throttle import LogThrottle, log_throttled
from src.infrastructure.payment_gateways import PlategaGateway
from src.infrastructure.payment_gateways.base import BasePaymentGateway
from src.infrastructure.taskiq.tasks.payments import handle_payment_transaction_task

router = APIRouter(prefix=API_V1 + PAYMENTS_WEBHOOK_PATH, include_in_schema=False)

# Unauthenticated callers reach every rejection path below, so repeats are collapsed
# into one line per interval — otherwise a junk-POST flood is a disk-write amplifier
# and drowns out real payment failures.
_REJECTION_LOG = LogThrottle()
# The gateway segment comes straight from the URL; echo only enough to diagnose.
_GATEWAY_ECHO_MAX_LEN = 32


async def _build_response(
    gateway: Optional[BasePaymentGateway], request: Request, gateway_type: str
) -> Response:
    if gateway is not None:
        try:
            return await gateway.build_webhook_response(request)
        except Exception:
            logger.exception(f"Failed to build webhook response for '{gateway_type}'")
    return Response(status_code=status.HTTP_200_OK)


async def _enqueue_payment_task(
    payment_id: UUID,
    payment_status: TransactionStatus,
    gateway_enum: PaymentGatewayType,
    gateway_type: str,
    config: AppConfig,
    event_publisher: EventPublisher,
) -> Optional[Response]:
    try:
        await handle_payment_transaction_task.kiq(payment_id, payment_status, gateway_enum)  # type: ignore[call-overload]
        return None
    except Exception as e:
        logger.exception(f"Failed to enqueue payment task for '{gateway_type}'")
        error_event = ErrorEvent(**config.build.data, exception=e)
        await event_publisher.publish(error_event)
        return Response(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)


async def _sync_platega_payment_method(
    gateway: BasePaymentGateway,
    payment_id: UUID,
    transaction_dao: TransactionDao,
    uow: UnitOfWork,
) -> None:
    if not isinstance(gateway, PlategaGateway) or gateway.selected_payment_method is None:
        return

    async with uow:
        transaction = await transaction_dao.get_by_payment_id(payment_id)
        if transaction is None:
            logger.warning(f"Transaction '{payment_id}' not found for Platega payment method sync")
            return

        transaction.payment_method = gateway.selected_payment_method
        await transaction_dao.update(transaction)
        await uow.commit()


async def _persist_settled_net(
    gateway: BasePaymentGateway,
    payment_id: UUID,
    transaction_dao: TransactionDao,
    uow: UnitOfWork,
) -> None:
    """Record the PSP-settled (after-fee) amount the gateway extracted from the raw
    webhook body (metrics spec §4). Fire-and-forget: a failure here must never
    affect the payment or the webhook response — net just stays unknown."""
    if gateway.settled_amount is None:
        return
    try:
        async with uow:
            await transaction_dao.set_net_amount(payment_id, gateway.settled_amount)
            await uow.commit()
    except Exception:
        logger.exception(f"Failed to persist settled net for payment '{payment_id}'")


async def _process_payment_webhook(
    gateway_type: str,
    request: Request,
    config: AppConfig,
    event_publisher: EventPublisher,
    get_payment_gateway_instance: GetPaymentGatewayInstance,
    transaction_dao: TransactionDao,
    uow: UnitOfWork,
) -> Response:
    try:
        gateway_enum = PaymentGatewayType(gateway_type.upper())
    except ValueError:
        # Not an error condition: anyone can POST an arbitrary path segment. It used
        # to log a full traceback per request, which is a free amplifier.
        log_throttled(
            _REJECTION_LOG,
            "unknown-gateway",
            "WARNING",
            f"Invalid gateway type received: '{gateway_type[:_GATEWAY_ECHO_MAX_LEN]}'",
        )
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    gateway: Optional[BasePaymentGateway] = None
    try:
        gateway = await get_payment_gateway_instance.system(gateway_enum)
        result = await gateway.handle_webhook(request)
    except GatewayNotConfiguredError:
        log_throttled(
            _REJECTION_LOG,
            f"not-configured:{gateway_enum}",
            "WARNING",
            f"Webhook received for inactive/unconfigured gateway '{gateway_enum}'",
        )
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    except PermissionError:
        log_throttled(
            _REJECTION_LOG,
            f"bad-signature:{gateway_enum}",
            "WARNING",
            f"Webhook signature verification failed for '{gateway_enum}'",
        )
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    except Exception as e:
        # Throttled but kept at exception level, and the ErrorEvent below is still
        # published every time: a real gateway fault must stay visible even while a
        # flood is in progress.
        log_throttled(
            _REJECTION_LOG,
            f"processing-error:{gateway_enum}",
            "ERROR",
            f"Error processing webhook for '{gateway_enum}': {e}",
            exception=True,
        )
        error_event = ErrorEvent(**config.build.data, exception=e)
        await event_publisher.publish(error_event)
        return await _build_response(gateway, request, gateway_type)

    if result is not None:
        payment_id, payment_status = result
        if gateway_enum == PaymentGatewayType.PLATEGA:
            await _sync_platega_payment_method(gateway, payment_id, transaction_dao, uow)
        if gateway is not None:
            await _persist_settled_net(gateway, payment_id, transaction_dao, uow)
        enqueue_error = await _enqueue_payment_task(
            payment_id, payment_status, gateway_enum, gateway_type, config, event_publisher
        )
        if enqueue_error is not None:
            return enqueue_error

    return await _build_response(gateway, request, gateway_type)


@router.post("/{gateway_type}")
@inject
async def payments_webhook(
    gateway_type: str,
    request: Request,
    config: FromDishka[AppConfig],
    event_publisher: FromDishka[EventPublisher],
    get_payment_gateway_instance: FromDishka[GetPaymentGatewayInstance],
    transaction_dao: FromDishka[TransactionDao],
    uow: FromDishka[UnitOfWork],
) -> Response:
    return await _process_payment_webhook(
        gateway_type=gateway_type,
        request=request,
        config=config,
        event_publisher=event_publisher,
        get_payment_gateway_instance=get_payment_gateway_instance,
        transaction_dao=transaction_dao,
        uow=uow,
    )
