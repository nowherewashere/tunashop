import re
from datetime import timezone
from decimal import Decimal
from pathlib import Path
from re import Pattern
from typing import Final

from packaging.version import Version

from src.core.enums import Currency, UserNotificationType

BASE_DIR: Final[Path] = Path(__file__).resolve().parents[2]
ASSETS_DIR: Final[Path] = BASE_DIR / "assets"
ASSETS_DEFAULT_DIR: Final[Path] = BASE_DIR / "assets.default"
BACKUP_DIR: Final[Path] = BASE_DIR / "backups"
LOG_DIR: Final[Path] = BASE_DIR / "logs"

# Per-currency default price for a freshly added plan duration (mirrors the
# configurator's 30-day tier). Avoids the absurd USD=100 shared default.
DEFAULT_DURATION_PRICES: Final[dict[Currency, Decimal]] = {
    Currency.USD: Decimal("1"),
    Currency.XTR: Decimal("60"),
    Currency.RUB: Decimal("100"),
}

DOMAIN_REGEX: Pattern[str] = re.compile(r"^(?:[a-zA-Z0-9-]+\.)+[a-zA-Z]{2,}$")
TAG_REGEX: Pattern[str] = re.compile(r"^[A-Z0-9_]{1,16}$")
URL_PATTERN: Pattern[str] = re.compile(r"^https://\S+$")
USERNAME_PATTERN: Pattern[str] = re.compile(r"^@[a-zA-Z0-9_]{5,32}$")
INVITE_LINK_PATTERN: Pattern[str] = re.compile(r"^https://t\.me/(\+|joinchat/)[A-Za-z0-9_\-]+")

# MIN is a hard gate (`try_connection` refuses to start below it); MAX only raises an
# admin warning. 3.0.0 is the floor because the bot speaks the post-UUID API and cannot
# talk to a 2.x panel at all.
REMNAWAVE_MIN_VERSION: Final[Version] = Version("3.0.0")
REMNAWAVE_MAX_VERSION: Final[Version] = Version("3.3.0")

# Panel 2.8 collapsed expires_in_72/48/24_hours and expired_24_hours_ago into one
# user.expiration event. `meta.expiration` is the EXPIRATION_NOTIFICATIONS entry that
# fired, in hours relative to expireAt and signed: negative = expires in N hours,
# positive = expired N hours ago. Thresholds are the admin's to choose, so the bot
# buckets them into whole days and clamps to what its copy is written for.
MAX_EXPIRING_NOTICE_DAYS: Final[int] = 3

# Day bucket -> the admin toggle the notice answers to. Both families must cover
# 1..MAX_EXPIRING_NOTICE_DAYS, which is the range `day` is clamped to. Publishing
# without one pins every notice to the 1-day toggle: the 2- and 3-day switches go
# dead and the 1-day switch silences all three.
EXPIRING_NOTICE_TYPES: Final[dict[int, UserNotificationType]] = {
    1: UserNotificationType.EXPIRES_IN_1_DAY,
    2: UserNotificationType.EXPIRES_IN_2_DAYS,
    3: UserNotificationType.EXPIRES_IN_3_DAYS,
}
EXPIRED_AGO_NOTICE_TYPES: Final[dict[int, UserNotificationType]] = {
    1: UserNotificationType.EXPIRED_1_DAY_AGO,
    2: UserNotificationType.EXPIRED_2_DAYS_AGO,
    3: UserNotificationType.EXPIRED_3_DAYS_AGO,
}

# Page size for /users/stream, which since panel 3.0.0 replaces the removed
# by-telegram-id / by-email / by-tag lookups. Panel caps it at 1000.
USERS_STREAM_PAGE_SIZE: Final[int] = 500
# Cursor-walk backstop for /users/stream, same reasoning as SQUAD_USAGE_MAX_PAGES
# below: every caller filters down to a handful of users, so 100k rows means the
# cursor is not converging and a partial list would be worse than an exception.
USERS_STREAM_MAX_PAGES: Final[int] = 200

# The bandwidth-stats endpoints take plain calendar dates, not timestamps.
PANEL_DATE_FORMAT: Final[str] = "%Y-%m-%d"
# Reset date as shown to the user in pool notifications.
POOL_RESET_DATE_FORMAT: Final[str] = "%d.%m.%Y"
# Cursor-walk backstop for squad usage. At 500 users a page this covers 100k users
# over a single pool's quota; hitting it means something is wrong, and continuing
# would mean acting on a partial set.
SQUAD_USAGE_MAX_PAGES: Final[int] = 200

REPOSITORY: Final[str] = "https://github.com/snoups/remnashop"
DOCS: Final[str] = "https://remnashop.mintlify.app"
T_ME: Final[str] = "https://t.me/"
API_V1: Final[str] = "/api/v1"
BOT_WEBHOOK_PATH: Final[str] = "/telegram"
PAYMENTS_WEBHOOK_PATH: Final[str] = "/payments"
REMNAWAVE_WEBHOOK_PATH: Final[str] = "/remnawave"

IMPORTED_TAG: Final[str] = "IMPORTED"
INLINE_QUERY_INVITE: Final[str] = "invite"
# Parked panel id for a subscription whose panel user was already gone at the 3.x
# cutover — an account merge or a delete removed it, so migration 0056 had nothing to
# resolve and stamped this instead of blocking the rollout. Panel ids are a positive
# sequence (`z.coerce.number().positive()` on every path param), so nothing can ever
# resolve onto it — but for the same reason nothing may be *sent* to the panel either:
# id 0 is a 400, not a 404. Callers that sweep a user's whole subscription history have
# to skip it. Migration 0056 repeats the literal on purpose; a migration must not import
# a constant that can drift under it.
NO_PANEL_USER: Final[int] = 0

REMNASHOP_PREFIX: Final[str] = "rs_"
WEB_PREFIX: Final[str] = "web_"
PAYMENT_PREFIX: Final[str] = "payment_"
GOTO_PREFIX: Final[str] = "gt_"
ENCRYPTED_PREFIX: Final[str] = "enc_"

# Support operator-topic inline button (callback data). Devices are rendered inline in
# the card and «🗂 Карточка» is a URL deep link, so «🔒 Закрыть» is the only callback.
SUPPORT_CB_CLOSE: Final[str] = "support:close"
# User-side inline button in the in-bot support chat: leave the chat (clears the FSM),
# a visible alternative to typing /stop.
SUPPORT_CB_LEAVE: Final[str] = "support:leave"
# Website sign-in confirmation, asked inside the bot. The one-time token is appended to
# the prefix, so both fit Telegram's 64-byte callback_data budget (prefix 9 + token 32).
WEB_LOGIN_CB_APPROVE: Final[str] = "wlogin:y:"
WEB_LOGIN_CB_DECLINE: Final[str] = "wlogin:n:"
# How long a deep link a gate (rules / channel) swallowed stays resumable. Long enough
# to read the rules and join a channel, short enough that a confirmation pressed much
# later is not answered with a flow the person has forgotten starting.
PENDING_DEEPLINK_TTL_SECONDS: Final[int] = 600
# The in-bot support FSM state string (== telegram.states.Support.CHAT.state). Duplicated
# here as a plain string so the infrastructure support service can drop a client's chat on
# operator /close without importing the telegram layer; states.py asserts they stay in sync.
SUPPORT_FSM_STATE: Final[str] = "Support:CHAT"

# Broadcast "+1 free trial day" button. StartBroadcast appends the broadcast task_id to
# the prefix so a press can be matched back to exactly one broadcast_messages row — that
# row is the claim ledger, which is what makes the bonus one-per-person-per-broadcast.
# Budget: prefix 4 + uuid 36 = 40 of Telegram's 64 callback_data bytes.
TRIAL_BONUS_CB: Final[str] = "tbn:"
TRIAL_BONUS_DAYS: Final[int] = 1
# The claim keeps its ledger row locked across the panel round trip (deliberately — a
# panel failure must roll the claim back), and a broadcast is exactly when presses arrive
# in bulk. Both halves of that wait are therefore capped, and capped low: the pool is 30
# connections app-wide, and Telegram refuses a callback answer that arrives more than
# ~15s late. Waiting side — a rival press for the same row gives up instead of queueing
# behind the panel.
TRIAL_BONUS_LOCK_WAIT_SECONDS: Final[float] = 3.0
# Holding side — a hung panel cannot pin the row (and the connection under it) for the
# httpx client's own 25s read timeout.
TRIAL_BONUS_PANEL_WAIT_SECONDS: Final[float] = 8.0

# goto targets (see routers/extra/goto.py) that open the onboarding funnel from a
# plain notification button; must match the Onboarding state strings in
# telegram/states.py. ENTRY is the funnel start (O0); HELP is the fail branch.
ONBOARDING_GOTO_TARGET: Final[str] = "Onboarding:DEVICE_CHOICE"
ONBOARDING_GOTO_HELP: Final[str] = "Onboarding:NOT_WORKING"

MIDDLEWARE_DATA_KEY: Final[str] = "middleware_data"
CONTAINER_KEY: Final[str] = "dishka_container"
CONFIG_KEY: Final[str] = "config"
USER_KEY: Final[str] = "user"
TARGET_TELEGRAM_ID: Final[str] = "target_telegram_id"
TARGET_USER_ID: Final[str] = "target_user_id"
FROM_REFERRAL_USER_ID: Final[str] = "from_referral_user_id"
USER_LIST_ORIGIN: Final[str] = "user_list_origin"
USER_LIST_PAYLOAD: Final[str] = "user_list_payload"

INT32_MAX: Final[int] = 2_147_483_647

TIMEZONE: Final[timezone] = timezone.utc
DATETIME_VIEW_FORMAT: Final[str] = "%d.%m.%y %H:%M:%S"
DATETIME_FILE_FORMAT: Final[str] = "%Y-%m-%d_%H-%M-%S"

TIME_1M: Final[int] = 60
TIME_1H: Final[int] = TIME_1M * 60
TIME_1D: Final[int] = TIME_1H * 24

TTL_5M: Final[int] = TIME_1M * 5
TTL_10M: Final[int] = TIME_1M * 10
TTL_30M: Final[int] = TIME_1M * 30
TTL_1H: Final[int] = TIME_1H
TTL_6H: Final[int] = TIME_1H * 6
TTL_12H: Final[int] = TIME_1H * 12
TTL_1D: Final[int] = TIME_1D
TTL_7D: Final[int] = TIME_1D * 7

RECENT_REGISTERED_MAX_COUNT: Final[int] = 50
RECENT_ACTIVITY_MAX_COUNT: Final[int] = 50
RECENT_ACTIVITY_STORE_CAP: Final[int] = 200

UNLIMITED_EXPIRE_YEAR: Final[int] = 2099

BATCH_SIZE_10: Final[int] = 10
BATCH_SIZE_20: Final[int] = 20
BATCH_DELAY: Final[int] = 1

TEXT_MAX_LENGTH: Final[int] = 4096
TEXT_MEDIA_MAX_LENGTH: Final[int] = 1024

PASSWORD_SCRYPT_N: Final[int] = 2**14
PASSWORD_SCRYPT_R: Final[int] = 8
PASSWORD_SCRYPT_P: Final[int] = 1
PASSWORD_SCRYPT_DKLEN: Final[int] = 64
ACCESS_TOKEN_TTL_SECONDS: Final[int] = 900  # 15 minutes
REFRESH_TOKEN_TTL_SECONDS: Final[int] = 60 * 60 * 24 * 30  # 30 days
TELEGRAM_AUTH_MAX_AGE_SECONDS: Final[int] = 600  # 10 minutes
PUBLIC_LANDING_PLANS_CACHE_TTL_SECONDS: Final[int] = 21600
PUBLIC_LANDING_PLANS_CACHE_KEY: Final[str] = "cache:public_landing_plans"
EMAIL_VERIFICATION_CODE_LENGTH: Final[int] = 6
EMAIL_VERIFICATION_RESEND_COOLDOWN_SECONDS: Final[int] = 60
WEB_PASSWORD_LEN: Final[int] = 8
WEB_PASSWORD_ALPHABET: Final[str] = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

# Unified support bridge (support spec). One conversation per user, bridged to a
# Telegram forum topic; the DB is the source of truth for history.

# support_conversations.status
CONVERSATION_OPEN: Final[str] = "open"
CONVERSATION_CLOSED: Final[str] = "closed"

# support_conversations.last_user_channel & support_messages.source
CHANNEL_SITE: Final[str] = "site"
CHANNEL_TELEGRAM: Final[str] = "telegram"

# support_messages.direction
DIRECTION_INBOUND: Final[str] = "inbound"  # user -> operator
DIRECTION_OUTBOUND: Final[str] = "outbound"  # operator -> user

# support_messages.sender
SENDER_USER: Final[str] = "user"
SENDER_OPERATOR: Final[str] = "operator"
SENDER_SYSTEM: Final[str] = "system"

# lifecycle_followups.status
FOLLOWUP_PENDING: Final[str] = "pending"
FOLLOWUP_SENT: Final[str] = "sent"
FOLLOWUP_CANCELLED: Final[str] = "cancelled"

# lifecycle_followups.chain
CHAIN_TRIAL_ENDING: Final[str] = "C"  # −3h before trial end — convert
CHAIN_WINBACK: Final[str] = "E"  # +3d / +2w after churn — win-back

# Money referral ledger (referral spec §2/§4). Statuses / kinds are plain strings, not
# PG enums, to keep the whole feature a set of additive tables with no changes to the
# shared enum registry — mirroring `lifecycle_followups` / `onboarding_nudges`. They
# live here rather than beside the SQLAlchemy models because the DTOs, use cases and
# bot getters that compare against them all sit above the infrastructure layer.

# referral_events.kind
EVENT_KIND_COMMISSION: Final[str] = "commission"
EVENT_KIND_ADJUSTMENT: Final[str] = "adjustment"  # chargeback reversal (external workstream)

# payouts.method
PAYOUT_METHOD_CRYPTO: Final[str] = "crypto"
PAYOUT_METHOD_STARS: Final[str] = "stars"  # buy-and-gift Telegram Stars (spec §7.2)

# payouts.status
PAYOUT_REQUESTED: Final[str] = "requested"
PAYOUT_PROCESSING: Final[str] = "processing"
PAYOUT_PAID: Final[str] = "paid"
PAYOUT_REJECTED: Final[str] = "rejected"

# A payout is "open" (locks further payouts + pay-with-balance) while in either
# of these states.
PAYOUT_OPEN_STATUSES: Final[tuple[str, ...]] = (PAYOUT_REQUESTED, PAYOUT_PROCESSING)

# Reason stamped on the payout an account merge had to close, and read back to its owner
# through `event-payout.rejected` ("Вывод { $amount } ₽ отклонён: { $reason }."). Free
# text and lowercase for that sentence position — exactly like the reason an operator
# types when rejecting by hand, and in the same language, since the bot ships only `ru`.
MERGE_SUPERSEDED_PAYOUT_REASON: Final[str] = "аккаунты объединены"
