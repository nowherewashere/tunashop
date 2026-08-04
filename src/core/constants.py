import re
from datetime import timezone
from decimal import Decimal
from pathlib import Path
from re import Pattern
from typing import Final

from packaging.version import Version

from src.core.enums import Currency

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

# Page size for /users/stream, which since panel 3.0.0 replaces the removed
# by-telegram-id / by-email / by-tag lookups. Panel caps it at 1000.
USERS_STREAM_PAGE_SIZE: Final[int] = 500

REPOSITORY: Final[str] = "https://github.com/snoups/remnashop"
DOCS: Final[str] = "https://remnashop.mintlify.app"
T_ME: Final[str] = "https://t.me/"
API_V1: Final[str] = "/api/v1"
BOT_WEBHOOK_PATH: Final[str] = "/telegram"
PAYMENTS_WEBHOOK_PATH: Final[str] = "/payments"
REMNAWAVE_WEBHOOK_PATH: Final[str] = "/remnawave"

IMPORTED_TAG: Final[str] = "IMPORTED"
INLINE_QUERY_INVITE: Final[str] = "invite"
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

# Reason stamped on the payout an account merge had to close, and read back to its owner
# through `event-payout.rejected` ("Вывод { $amount } ₽ отклонён: { $reason }."). Free
# text and lowercase for that sentence position — exactly like the reason an operator
# types when rejecting by hand, and in the same language, since the bot ships only `ru`.
MERGE_SUPERSEDED_PAYOUT_REASON: Final[str] = "аккаунты объединены"
