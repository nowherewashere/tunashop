from typing import Final

from src.application.common import Interactor

from .commands.bot_login import ClaimBotLogin, ResolveBotLogin, StartBotLogin
from .commands.email import (
    ChangeEmail,
    ConfirmEmailVerification,
    RequestEmailVerification,
)
from .commands.email_login import (
    RequestEmailLoginCode,
    VerifyEmailLoginCode,
    VerifyEmailLoginLink,
)
from .commands.login import LoginEmailUser
from .commands.oauth import (
    AuthenticateOAuth,
    LinkOAuthProvider,
    StartOAuth,
    UnlinkOAuthProvider,
)
from .commands.password import ChangePassword
from .commands.register import RegisterEmailUser
from .commands.session import RefreshSession
from .commands.telegram import AuthenticateTelegram, AuthenticateTelegramWebApp, LinkTelegram

AUTH_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    RegisterEmailUser,
    LoginEmailUser,
    RefreshSession,
    AuthenticateTelegram,
    AuthenticateTelegramWebApp,
    LinkTelegram,
    StartOAuth,
    AuthenticateOAuth,
    LinkOAuthProvider,
    UnlinkOAuthProvider,
    StartBotLogin,
    ResolveBotLogin,
    ClaimBotLogin,
    ChangePassword,
    ChangeEmail,
    RequestEmailVerification,
    ConfirmEmailVerification,
    RequestEmailLoginCode,
    VerifyEmailLoginCode,
    VerifyEmailLoginLink,
)
