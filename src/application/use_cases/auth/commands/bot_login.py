import hmac
import secrets
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, status
from loguru import logger

from src.application.common import BotService, Interactor
from src.application.common.dao import BotLoginDao, BotLoginRequest, UserDao
from src.application.common.policy import Permission
from src.application.dto import UserDto
from src.application.use_cases.auth.commands.oauth import hash_binding
from src.core.config import AppConfig
from src.core.utils.qr import render_qr_png_base64

# Short on purpose: the whole exchange is a person tapping a link and pressing one
# button. A stale QR left on a screen stops being useful within minutes.
BOT_LOGIN_TTL_SECONDS = 120


@dataclass
class BotLoginStarted:
    token: str
    url: str
    qr_png_base64: str
    # Raw value for the httpOnly binding cookie; only its hash is stored.
    binding: str
    expires_in: int


@dataclass
class StartBotLoginDto:
    ip: Optional[str] = None


class StartBotLogin(Interactor[StartBotLoginDto, BotLoginStarted]):
    """Open a "confirm in the bot" sign-in.

    Exists because the Telegram Login Widget is a third-party script plus an iframe
    from telegram.org — both of which are blocked often enough in the markets this
    service sells into that the login page already carries a failure branch for it.
    This path is entirely first-party: our page, our API, our bot.
    """

    required_permission = None

    def __init__(self, bot_service: BotService, bot_login_dao: BotLoginDao) -> None:
        self.bot_service = bot_service
        self.bot_login_dao = bot_login_dao

    async def _execute(self, actor: UserDto, data: StartBotLoginDto) -> BotLoginStarted:
        token = secrets.token_urlsafe(24)
        binding = secrets.token_urlsafe(32)
        url = await self.bot_service.get_web_login_url(token)

        await self.bot_login_dao.put(
            token,
            BotLoginRequest(status="pending", binding_hash=hash_binding(binding), ip=data.ip),
            ttl=BOT_LOGIN_TTL_SECONDS,
        )
        return BotLoginStarted(
            token=token,
            url=url,
            # Rendered server-side, so the SPA needs no QR library — and the desktop
            # user can confirm on their phone without Telegram Desktop installed.
            qr_png_base64=render_qr_png_base64(url),
            binding=binding,
            expires_in=BOT_LOGIN_TTL_SECONDS,
        )


@dataclass
class ResolveBotLoginDto:
    token: str
    approve: bool


class ResolveBotLogin(Interactor[ResolveBotLoginDto, bool]):
    """Record the person's decision, from inside the bot.

    Called with the Telegram user as the actor, so approval is bound to whoever
    actually pressed the button — the website never gets a say in whose account it
    receives. Returns False when the request expired or was already answered, which
    the bot turns into "ссылка устарела" rather than a silent no-op.
    """

    # PUBLIC, not None: `None` means "only ever invoked via .system()", and the base
    # Interactor refuses a real actor on that setting. This one is deliberately called
    # with the pressing user, so it needs an actual permission — same as LinkTelegram.
    required_permission = Permission.PUBLIC

    def __init__(self, bot_login_dao: BotLoginDao) -> None:
        self.bot_login_dao = bot_login_dao

    async def _execute(self, actor: UserDto, data: ResolveBotLoginDto) -> bool:
        resolved = await self.bot_login_dao.resolve(
            data.token,
            "approved" if data.approve else "declined",
            actor.id if data.approve else None,
        )
        if resolved:
            logger.info(
                f"{actor.log} {'approved' if data.approve else 'declined'} a website sign-in"
            )
        return resolved


@dataclass
class ClaimBotLoginDto:
    token: str
    binding: Optional[str]


class ClaimBotLogin(Interactor[ClaimBotLoginDto, UserDto]):
    """Turn an approved confirmation into a session, for the browser that started it.

    The binding cookie is what makes this safe against the classic QR-phishing move —
    showing a victim a code from the attacker's own screen. Even holding the token,
    an attacker's browser cannot produce the cookie, so the approval is worthless to
    them. Consumed on read, so it works exactly once.
    """

    required_permission = None

    def __init__(self, config: AppConfig, bot_login_dao: BotLoginDao, user_dao: UserDao) -> None:
        self.config = config
        self.bot_login_dao = bot_login_dao
        self.user_dao = user_dao

    async def _execute(self, actor: UserDto, data: ClaimBotLoginDto) -> UserDto:
        invalid = HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="bot_login_invalid")
        if not data.binding:
            raise invalid

        request = await self.bot_login_dao.get(data.token)
        if request is None or request.status != "approved" or request.user_id is None:
            raise invalid
        if not hmac.compare_digest(hash_binding(data.binding), request.binding_hash):
            logger.warning("Refused a bot-login claim from a browser that did not start it")
            raise invalid

        # Only now consume it: a mismatched binding must not burn the pending request,
        # or an attacker who guessed the token could grief the real user.
        await self.bot_login_dao.consume(data.token)

        user = await self.user_dao.get_by_id(request.user_id)
        if user is None:
            raise invalid
        if user.is_blocked:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is blocked")
        return user
