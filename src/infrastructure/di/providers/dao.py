from dishka import Provider, Scope, provide

from src.application.common.dao import (
    AccountMergeDao,
    AdLinkDao,
    AuthSessionDao,
    BotLoginDao,
    BroadcastDao,
    EmailLoginLinkDao,
    EventsDao,
    LifecycleFollowupDao,
    OAuthStateDao,
    OnboardingNudgeDao,
    PaymentGatewayDao,
    PlanDao,
    PromocodeDao,
    RateLimiter,
    RecentActivityDao,
    ReferralDao,
    ReferralLedgerDao,
    SettingsDao,
    SubscriptionDao,
    SupportDao,
    TransactionDao,
    UserConnectionStateDao,
    UserDao,
    UserOAuthProviderDao,
    WaitlistDao,
    WebhookDao,
)
from src.infrastructure.database.dao import (
    AccountMergeDaoImpl,
    AdLinkDaoImpl,
    BroadcastDaoImpl,
    EventsDaoImpl,
    LifecycleFollowupDaoImpl,
    OnboardingNudgeDaoImpl,
    PaymentGatewayDaoImpl,
    PlanDaoImpl,
    PromocodeDaoImpl,
    ReferralDaoImpl,
    ReferralLedgerDaoImpl,
    SettingsDaoImpl,
    SubscriptionDaoImpl,
    SupportDaoImpl,
    TransactionDaoImpl,
    UserConnectionStateDaoImpl,
    UserDaoImpl,
    UserOAuthProviderDaoImpl,
    WaitlistDaoImpl,
    WebhookDaoImpl,
)
from src.infrastructure.redis.activity import RedisActivityRepository
from src.infrastructure.redis.auth import RedisAuthRepository
from src.infrastructure.redis.bot_login import RedisBotLoginRepository
from src.infrastructure.redis.email_login_link import RedisEmailLoginLinkRepository
from src.infrastructure.redis.oauth_state import RedisOAuthStateRepository
from src.infrastructure.redis.rate_limit import RedisRateLimiter


class DaoProvider(Provider):
    scope = Scope.REQUEST

    account_merge = provide(source=AccountMergeDaoImpl, provides=AccountMergeDao)
    ad_link = provide(source=AdLinkDaoImpl, provides=AdLinkDao)
    broadcast = provide(source=BroadcastDaoImpl, provides=BroadcastDao)
    events = provide(source=EventsDaoImpl, provides=EventsDao)
    onboarding_nudge = provide(source=OnboardingNudgeDaoImpl, provides=OnboardingNudgeDao)
    lifecycle_followup = provide(
        source=LifecycleFollowupDaoImpl, provides=LifecycleFollowupDao
    )
    user_connection_state = provide(
        source=UserConnectionStateDaoImpl, provides=UserConnectionStateDao
    )
    payment_gateway = provide(source=PaymentGatewayDaoImpl, provides=PaymentGatewayDao)
    plan = provide(source=PlanDaoImpl, provides=PlanDao)
    promocode = provide(source=PromocodeDaoImpl, provides=PromocodeDao)
    referral = provide(source=ReferralDaoImpl, provides=ReferralDao)
    referral_ledger = provide(source=ReferralLedgerDaoImpl, provides=ReferralLedgerDao)
    settings = provide(source=SettingsDaoImpl, provides=SettingsDao)
    subscription = provide(source=SubscriptionDaoImpl, provides=SubscriptionDao)
    support = provide(source=SupportDaoImpl, provides=SupportDao)
    transaction = provide(source=TransactionDaoImpl, provides=TransactionDao)
    user = provide(source=UserDaoImpl, provides=UserDao)
    oauth_provider = provide(source=UserOAuthProviderDaoImpl, provides=UserOAuthProviderDao)

    webhook = provide(source=WebhookDaoImpl, provides=WebhookDao, scope=Scope.APP)
    waitlist = provide(source=WaitlistDaoImpl, provides=WaitlistDao, scope=Scope.APP)
    auth_session = provide(source=RedisAuthRepository, provides=AuthSessionDao, scope=Scope.APP)
    oauth_state = provide(source=RedisOAuthStateRepository, provides=OAuthStateDao, scope=Scope.APP)
    bot_login = provide(source=RedisBotLoginRepository, provides=BotLoginDao, scope=Scope.APP)
    email_login_link = provide(
        source=RedisEmailLoginLinkRepository, provides=EmailLoginLinkDao, scope=Scope.APP
    )
    rate_limiter = provide(source=RedisRateLimiter, provides=RateLimiter, scope=Scope.APP)
    recent_activity = provide(
        source=RedisActivityRepository, provides=RecentActivityDao, scope=Scope.APP
    )
