from decimal import Decimal
from typing import Awaitable, Callable, Optional

from loguru import logger

from src.application.common.dao import EventsDao, SubscriptionDao, TransactionDao, UserDao
from src.application.common.uow import UnitOfWork
from src.application.events.metrics import (
    FunnelStepEvent,
    ReferralCommissionRecordedEvent,
)
from src.application.events.system import (
    NodeConnectionLostEvent,
    NodeConnectionRestoredEvent,
    TrialActivatedEvent,
    UserFirstConnectionEvent,
    UserPurchaseEvent,
)
from src.application.events.user import SubscriptionExpiredEvent
from src.core.enums import PurchaseType
from src.core.metrics import ConnectOutcome, MetricEvent, MetricSource, NodeStatus
from src.infrastructure.services.event_bus import on_event


class MetricsEventListener:
    """Turns domain events into rows in the append-only ``events`` table (metrics
    spec §4–§6). It is the single writer of business + node metrics — one additive
    fork listener, auto-subscribed by the event bus exactly like
    ``TrialConnectionHandler`` (zero wiring beyond the DI provider).

    **Fire-and-forget (spec §2, §7).** Every write goes through :meth:`_write`,
    whose ``try/except`` wraps the *whole* unit of work — including opening it — so
    a metrics failure never surfaces to the user and never lets an exception escape
    into the bus's ErrorEvent fan-out (which would storm the admin chat). Per-user
    events are keyed by ``remnawave_uuid`` (``Subscription.user_remna_id``), resolved
    from the current subscription, so bot + site + probe data auto-consolidate.
    """

    def __init__(
        self,
        uow: UnitOfWork,
        events_dao: EventsDao,
        subscription_dao: SubscriptionDao,
        user_dao: UserDao,
        transaction_dao: TransactionDao,
    ) -> None:
        self.uow = uow
        self.events_dao = events_dao
        self.subscription_dao = subscription_dao
        self.user_dao = user_dao
        self.transaction_dao = transaction_dao

    # --- business events (spec §4) -------------------------------------------
    @on_event(TrialActivatedEvent)
    async def on_trial_started(self, event: TrialActivatedEvent) -> None:
        async def write() -> None:
            await self.events_dao.append(
                event_type=MetricEvent.TRIAL_STARTED,
                source=MetricSource.BOT,
                user_ref=await self._user_ref_for_user_id(event.user_id),
                properties={
                    "plan_type": str(event.plan_type),
                    "is_trial_plan": event.is_trial_plan,
                },
            )

        await self._write("trial_started", write)

    @on_event(UserFirstConnectionEvent)
    async def on_first_connect(self, event: UserFirstConnectionEvent) -> None:
        # `subscription_id` already IS the remnawave_uuid (the spec keys on it
        # directly). No node/protocol here — the FIRST_CONNECTED webhook doesn't
        # carry them; the dimensioned health signal comes from probes (§6.2) and
        # node_status (§6.1). This row is the passive "activation" signal.
        async def write() -> None:
            await self.events_dao.append(
                event_type=MetricEvent.FIRST_CONNECT,
                source=MetricSource.BOT,
                user_ref=str(event.subscription_id),
                properties={"is_trial": event.is_trial, "outcome": ConnectOutcome.SUCCESS},
            )

        await self._write("first_connect", write)

    @on_event(UserPurchaseEvent)
    async def on_payment(self, event: UserPurchaseEvent) -> None:
        # Trial "purchases" and free grants are not revenue — keep them out of the
        # payment metric (mirrors the referral-commission gate).
        gross = event.final_amount
        if event.is_trial_plan or gross <= 0:
            return

        async def write() -> None:
            user_ref = await self._user_ref_for_user_id(event.user_id)
            transaction = await self.transaction_dao.get_by_payment_id(event.payment_id)
            net = transaction.net_amount if transaction else None
            method = transaction.payment_method if transaction else None
            plan_days = transaction.plan_snapshot.duration if transaction else None

            # Detect conversion + renewal BEFORE writing the payment row, so the
            # "first payment ever?" check can't see the row we're about to add.
            is_first_payment = bool(user_ref) and not await self.events_dao.has_event(
                user_ref=str(user_ref), event_type=MetricEvent.PAYMENT
            )
            had_trial = bool(user_ref) and await self.events_dao.has_event(
                user_ref=str(user_ref), event_type=MetricEvent.TRIAL_STARTED
            )

            await self.events_dao.append(
                event_type=MetricEvent.PAYMENT,
                source=MetricSource.PSP,
                user_ref=user_ref,
                properties={
                    "plan": plan_days,
                    "tier": str(event.plan_type),
                    "gross": self._decimal_str(gross),
                    "net": self._decimal_str(net),
                    "currency": event.currency,
                    "method": method,
                    "psp": str(event.gateway_type),
                },
            )

            if event.purchase_type == PurchaseType.RENEW:
                await self.events_dao.append(
                    event_type=MetricEvent.SUBSCRIPTION_RENEWED,
                    source=MetricSource.PSP,
                    user_ref=user_ref,
                    properties={
                        "plan": plan_days,
                        "gross": self._decimal_str(gross),
                        "net": self._decimal_str(net),
                    },
                )

            # trial → first paid payment = the conversion the model needs (spec §9).
            if is_first_payment and had_trial:
                await self.events_dao.append(
                    event_type=MetricEvent.TRIAL_CONVERTED,
                    source=MetricSource.BOT,
                    user_ref=user_ref,
                )

        await self._write("payment", write)

    @on_event(SubscriptionExpiredEvent)
    async def on_churned(self, event: SubscriptionExpiredEvent) -> None:
        # Expiry with no active sub = lapse; churn time = the row's `ts`. The offline
        # job pairs it with first_connect for the paying-lifetime cohort (spec §8).
        async def write() -> None:
            await self.events_dao.append(
                event_type=MetricEvent.CHURNED,
                source=MetricSource.BOT,
                user_ref=await self._user_ref_for_user_id(event.user.id),
                properties={"is_trial": event.is_trial},
            )

        await self._write("churned", write)

    @on_event(ReferralCommissionRecordedEvent)
    async def on_referral_attributed(self, event: ReferralCommissionRecordedEvent) -> None:
        async def write() -> None:
            referrer_ref = (
                str(event.referrer_remna_uuid)
                if event.referrer_remna_uuid is not None
                else await self._user_ref_for_user_id(event.referrer_id)
            )
            await self.events_dao.append(
                event_type=MetricEvent.REFERRAL_ATTRIBUTED,
                source=MetricSource.BOT,
                user_ref=await self._user_ref_for_user_id(event.referred_id),
                properties={
                    "referrer_ref": referrer_ref,
                    "payout_rub": self._kop_to_rub_str(event.commission_kop),
                    "payment_rub": self._kop_to_rub_str(event.payment_kop),
                    "payment_id": event.payment_id,
                },
            )

        await self._write("referral_attributed", write)

    # --- funnel steps (spec §5) ----------------------------------------------
    @on_event(FunnelStepEvent)
    async def on_funnel_step(self, event: FunnelStepEvent) -> None:
        async def write() -> None:
            user_ref = event.user_ref
            if user_ref is None and event.telegram_id is not None:
                user_ref = await self._user_ref_for_telegram_id(event.telegram_id)
            await self.events_dao.append(
                event_type=MetricEvent.FUNNEL_STEP,
                source=event.source,
                user_ref=user_ref,
                properties={
                    "step": str(event.step),
                    "surface": str(event.source),
                    "platform": event.platform,
                },
            )

        await self._write("funnel_step", write)

    # --- node health (spec §6.1) ---------------------------------------------
    @on_event(NodeConnectionLostEvent)
    async def on_node_down(self, event: NodeConnectionLostEvent) -> None:
        await self._record_node_status(event.name, event.address, NodeStatus.DOWN)

    @on_event(NodeConnectionRestoredEvent)
    async def on_node_up(self, event: NodeConnectionRestoredEvent) -> None:
        await self._record_node_status(event.name, event.address, NodeStatus.UP)

    async def _record_node_status(self, name: str, address: str, status: NodeStatus) -> None:
        async def write() -> None:
            await self.events_dao.append(
                event_type=MetricEvent.NODE_STATUS,
                source=MetricSource.BOT,
                user_ref=None,  # node-level, not per-user
                properties={"node_id": name, "address": address, "status": str(status)},
            )

        await self._write("node_status", write)

    # --- helpers -------------------------------------------------------------
    async def _write(self, label: str, build: Callable[[], Awaitable[None]]) -> None:
        """Run ``build`` inside a committed unit of work, swallowing any failure.

        The ``try`` wraps opening the uow too, so even a session-acquisition error
        stays invisible — the fire-and-forget guarantee (spec §7)."""
        try:
            async with self.uow:
                await build()
                await self.uow.commit()
        except Exception as error:
            logger.warning(f"metrics '{label}' write skipped: {error}")

    async def _user_ref_for_user_id(self, user_id: int) -> Optional[str]:
        subscription = await self.subscription_dao.get_current(user_id)
        return str(subscription.user_remna_id) if subscription else None

    async def _user_ref_for_telegram_id(self, telegram_id: int) -> Optional[str]:
        user = await self.user_dao.get_by_telegram_id(telegram_id)
        return await self._user_ref_for_user_id(user.id) if user else None

    @staticmethod
    def _decimal_str(value: Optional[Decimal]) -> Optional[str]:
        return format(value, "f") if value is not None else None

    @staticmethod
    def _kop_to_rub_str(kop: int) -> str:
        return format(Decimal(kop) / Decimal(100), "f")
