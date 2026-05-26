from dishka import FromDishka
from dishka.integrations.fastapi import inject
from fastapi import APIRouter, Request, Response, status
from loguru import logger

from src.application.common import EventPublisher
from src.application.events import ErrorEvent
from src.application.use_cases.gateways.queries.providers import GetPaymentGatewayInstance
from src.core.config import AppConfig
from src.core.constants import API_V1, PAYMENTS_WEBHOOK_PATH
from src.core.enums import PaymentGatewayType
from src.core.exceptions import GatewayNotConfiguredError
from src.infrastructure.taskiq.tasks.payments import handle_payment_transaction_task

router = APIRouter(prefix=API_V1 + PAYMENTS_WEBHOOK_PATH, include_in_schema=False)


@router.post("/{gateway_type}")
@inject
async def payments_webhook(
    gateway_type: str,
    request: Request,
    config: FromDishka[AppConfig],
    event_publisher: FromDishka[EventPublisher],
    get_payment_gateway_instance: FromDishka[GetPaymentGatewayInstance],
) -> Response:
    try:
        gateway_enum = PaymentGatewayType(gateway_type.upper())
    except ValueError:
        logger.exception(f"Invalid gateway type received: '{gateway_type}'")
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    gateway = None
    try:
        gateway = await get_payment_gateway_instance.system(gateway_enum)
        result = await gateway.handle_webhook(request)
        if result is not None:
            payment_id, payment_status = result
            await handle_payment_transaction_task.kiq(payment_id, payment_status)  # type: ignore[call-overload]

    except GatewayNotConfiguredError:
        logger.warning(f"Webhook received for inactive/unconfigured gateway '{gateway_enum}'")
        return Response(status_code=status.HTTP_404_NOT_FOUND)
    except PermissionError:
        logger.warning(f"Webhook signature verification failed for '{gateway_enum}'")
        return Response(status_code=status.HTTP_403_FORBIDDEN)
    except Exception as e:
        logger.exception(f"Error processing webhook for '{gateway_type}': {e}")
        error_event = ErrorEvent(**config.build.data, exception=e)
        await event_publisher.publish(error_event)

    if gateway is not None:
        try:
            return await gateway.build_webhook_response(request)
        except Exception:
            logger.exception(f"Failed to build webhook response for '{gateway_type}'")
    return Response(status_code=status.HTTP_200_OK)
