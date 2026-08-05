from dishka import AnyOf, Provider, Scope, alias, provide

from src.application.common import (
    BotService,
    BroadcastDispatcher,
    Cryptographer,
    EmailSender,
    EventPublisher,
    EventSubscriber,
    FileDownloader,
    HttpClient,
    Notifier,
    OAuthClientRegistry,
    PasswordHasher,
    PaymentNotificationDispatcher,
    Redirect,
    Remnawave,
    SupportService,
    TrafficPoolAccess,
    TurnstileVerifier,
    XuiDbReader,
)
from src.application.services import (
    AccountMergeService,
    PricingService,
    RemnaWebhookService,
    SubscriptionProrationService,
    TrafficPoolAccessService,
    TrafficPoolMeteringService,
)
from src.core.config import AppConfig
from src.infrastructure.services import (
    AiogramFileDownloader,
    AiohttpClient,
    BotServiceImpl,
    BroadcastDispatcherImpl,
    CommandService,
    ConsoleEmailSender,
    CryptographerImpl,
    EventBusImpl,
    HealthService,
    LifecycleFollowupHandler,
    MetricsEventListener,
    NotificationQueue,
    NotificationService,
    NotificationWorker,
    OAuthClientRegistryImpl,
    PasswordHasherImpl,
    PaymentNotificationDispatcherImpl,
    RedirectImpl,
    RemnawaveImpl,
    SmtpEmailSender,
    SupportServiceImpl,
    TrialConnectionHandler,
    TurnstileVerifierImpl,
    WebhookService,
    XuiDbReaderImpl,
)


class ServicesProvider(Provider):
    scope = Scope.APP

    bot = provide(source=BotServiceImpl, provides=BotService)
    health = provide(source=HealthService)
    cryptographer = provide(source=CryptographerImpl, provides=Cryptographer)
    password_hasher = provide(source=PasswordHasherImpl, provides=PasswordHasher)

    @provide(scope=Scope.APP)
    def email_sender(self, config: AppConfig) -> EmailSender:
        # Dev/local: console backend logs the code (no SMTP). Prod: real SMTP.
        if config.email.console:
            return ConsoleEmailSender()
        return SmtpEmailSender(config)

    @provide(scope=Scope.APP)
    def oauth_clients(self, config: AppConfig) -> OAuthClientRegistry:
        # Built from config at startup: only providers that are both enabled and
        # implemented get a client, so a misconfiguration shows up in the boot log
        # rather than mid-redirect on a user's first click.
        return OAuthClientRegistryImpl(config)

    http_client = provide(source=AiohttpClient, provides=HttpClient)
    turnstile = provide(source=TurnstileVerifierImpl, provides=TurnstileVerifier)
    redirect = provide(source=RedirectImpl, provides=Redirect)
    pricing = provide(source=PricingService)
    proration = provide(source=SubscriptionProrationService)
    event_bus = provide(EventBusImpl)
    publisher = alias(source=EventBusImpl, provides=EventPublisher)
    subscriber = alias(source=EventBusImpl, provides=EventSubscriber)
    file_downloader = provide(source=AiogramFileDownloader, provides=FileDownloader)

    command = provide(source=CommandService)
    webhook = provide(source=WebhookService)

    remnawave = provide(source=RemnawaveImpl, provides=Remnawave)
    remna_webhook = provide(source=RemnaWebhookService, scope=Scope.REQUEST)
    # Shared core of both merge directions. REQUEST scope: it composes onto the
    # request-scoped uow + DAOs so the whole merge lands in one transaction.
    account_merge_service = provide(source=AccountMergeService, scope=Scope.REQUEST)
    # Traffic pools. Both REQUEST-scoped: they compose onto the request-scoped uow +
    # DAOs, exactly like the merge service. The access service is pulled in by the
    # squad-assignment use cases; the metering service only by the cron task.
    # Provided under both names, one instance either way: use cases ask for the
    # `TrafficPoolAccess` port (they cannot import this package — see the port's
    # docstring), while the metering service and the web layer take the class.
    traffic_pool_access = provide(
        source=TrafficPoolAccessService,
        scope=Scope.REQUEST,
        provides=AnyOf[TrafficPoolAccessService, TrafficPoolAccess],
    )
    traffic_pool_metering = provide(source=TrafficPoolMeteringService, scope=Scope.REQUEST)
    # Unified support bridge (site + bot -> operator forum topics). REQUEST scope: it
    # composes onto the request-scoped uow + DAOs, like the other stateful services.
    support_service = provide(
        source=SupportServiceImpl, scope=Scope.REQUEST, provides=SupportService
    )
    # First-connection listener (connected_once + on-connect trial-timer restart).
    # REQUEST scope: it uses the request-scoped uow + DAOs, and the event bus
    # resolves listeners from a fresh request container.
    trial_connection = provide(source=TrialConnectionHandler, scope=Scope.REQUEST)
    # Win-back arming listener (chain E on subscription expiry).
    lifecycle_followup = provide(source=LifecycleFollowupHandler, scope=Scope.REQUEST)
    # Metrics/analytics listener — maps domain events to the append-only `events`
    # table (metrics spec §4–§6). REQUEST scope: fresh uow + DAOs per event, like the
    # other listeners. Auto-subscribes via its @on_event methods (no extra wiring).
    metrics_listener = provide(source=MetricsEventListener, scope=Scope.REQUEST)

    notification_queue = provide(source=NotificationQueue)
    notification_worker = provide(source=NotificationWorker)
    notification = provide(
        NotificationService,
        scope=Scope.REQUEST,
        provides=AnyOf[Notifier, NotificationService],
    )

    payment_dispatcher = provide(
        source=PaymentNotificationDispatcherImpl,
        provides=PaymentNotificationDispatcher,
        scope=Scope.APP,
    )
    broadcast_dispatcher = provide(
        source=BroadcastDispatcherImpl,
        provides=BroadcastDispatcher,
        scope=Scope.APP,
    )
    xui_reader = provide(source=XuiDbReaderImpl, provides=XuiDbReader, scope=Scope.APP)
