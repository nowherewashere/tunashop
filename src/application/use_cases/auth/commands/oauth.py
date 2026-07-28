import hashlib
import secrets
from dataclasses import dataclass
from typing import Optional

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy.exc import IntegrityError

from src.application.common import Interactor, OAuthClientRegistry, OAuthIdentity
from src.application.common.dao import (
    OAuthFlowMode,
    OAuthFlowState,
    OAuthStateDao,
    UserDao,
    UserOAuthProviderDao,
)
from src.application.common.policy import Permission
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.application.dto.user import UserOAuthProviderDto
from src.application.services import AccountMergeService
from src.application.use_cases.user.commands.web_registration import (
    RegisterWebUser,
    RegisterWebUserDto,
)
from src.core.config import AppConfig
from src.core.enums import AuthType, OAuthProvider


def hash_binding(value: str) -> str:
    """Hash the browser-binding cookie value before it is stored alongside the state.

    Stored hashed for the same reason a password is: anyone who can read the Redis
    key must not be able to forge the cookie that unlocks it.
    """
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def _blocked() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="User is blocked")


def count_sign_in_methods(
    user: UserDto,
    providers: list[UserOAuthProviderDto],
    excluding: Optional[OAuthProvider] = None,
) -> int:
    """How many ways this account can still be signed into.

    An email with neither a verification nor a password is deliberately NOT counted,
    even though ``RequestEmailLoginCode`` would in fact find the user by it: that path
    also depends on EMAIL_ENABLED and a live SMTP host, so counting it could let
    someone strand themselves during a mail outage. Erring toward refusing an unlink
    is the recoverable direction.
    """
    total = 0
    if user.telegram_id is not None:
        total += 1
    if user.email is not None and (user.is_email_verified or user.password_hash is not None):
        total += 1
    total += sum(1 for p in providers if p.provider != excluding)
    return total


async def _exchange(
    registry: OAuthClientRegistry,
    config: AppConfig,
    provider: OAuthProvider,
    code: str,
    code_verifier: Optional[str],
) -> OAuthIdentity:
    client = registry.get(provider)
    if client is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Provider not enabled")
    redirect_uri = config.oauth.redirect_uri(config.oauth_public_base_url, provider)
    return await client.exchange(code=code, redirect_uri=redirect_uri, code_verifier=code_verifier)


@dataclass
class StartOAuthDto:
    provider: OAuthProvider
    # Set by the route, never by the client — login and link are separate endpoints
    # precisely so a caller cannot ask for link mode.
    mode: OAuthFlowMode
    referral_code: Optional[str] = None
    actor_user_id: Optional[int] = None


@dataclass
class OAuthFlowStarted:
    authorize_url: str
    # Raw value for the httpOnly binding cookie; only its hash is persisted.
    binding: str
    ttl_seconds: int


class StartOAuth(Interactor[StartOAuthDto, OAuthFlowStarted]):
    """Open a social sign-in: mint the state, stash what the callback must trust.

    Nothing the callback relies on travels through the browser — the user agent
    carries only an opaque state and a binding cookie.
    """

    required_permission = None

    def __init__(
        self,
        config: AppConfig,
        registry: OAuthClientRegistry,
        state_dao: OAuthStateDao,
    ) -> None:
        self.config = config
        self.registry = registry
        self.state_dao = state_dao

    async def _execute(self, actor: UserDto, data: StartOAuthDto) -> OAuthFlowStarted:
        client = self.registry.get(data.provider)
        if client is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Provider not enabled"
            )

        state = secrets.token_urlsafe(32)
        binding = secrets.token_urlsafe(32)
        redirect_uri = self.config.oauth.redirect_uri(
            self.config.oauth_public_base_url, data.provider
        )
        request = client.build_authorize_request(redirect_uri=redirect_uri, state=state)

        ttl = self.config.oauth.state_ttl_seconds
        await self.state_dao.put(
            state,
            OAuthFlowState(
                provider=data.provider,
                mode=data.mode,
                code_verifier=request.code_verifier,
                binding_hash=hash_binding(binding),
                referral_code=data.referral_code,
                actor_user_id=data.actor_user_id,
            ),
            ttl=ttl,
        )
        return OAuthFlowStarted(authorize_url=request.url, binding=binding, ttl_seconds=ttl)


@dataclass
class AuthenticateOAuthDto:
    provider: OAuthProvider
    code: str
    code_verifier: Optional[str]
    referral_code: Optional[str] = None


class AuthenticateOAuth(Interactor[AuthenticateOAuthDto, UserDto]):
    """Resolve a provider identity to an account, creating one if needed.

    The decision table, in order — this ordering is the security property, not an
    implementation detail:

    - **A1** an identity row for ``(provider, provider_id)`` exists → that user.
    - **A2** no row, the provider asserts a **verified** email, and a user holds that
      address → attach the identity to that user (and mark the address verified: the
      provider's signed claim proves ownership of the same address already on the row).
    - **A4** no row, the email is **not** verified, and a user holds that address →
      **refuse**. Auto-linking here would be a one-click account takeover for any
      provider that lets a user claim an address it never checked. The caller turns
      this into "sign in by email code, then link from the cabinet", which reaches the
      same account through a path that does prove ownership.
    - **A3/A5** nobody holds the address → create. The address is only written to
      ``users.email`` when it was verified (A3); otherwise the account is created
      without one (A5) and the unverified address is kept for display only.

    Deliberately rejected: a "trust this provider's email anyway" config flag. A
    setting whose wrong value silently enables account takeover is not worth the
    convenience.
    """

    required_permission = None

    def __init__(
        self,
        config: AppConfig,
        uow: UnitOfWork,
        registry: OAuthClientRegistry,
        user_dao: UserDao,
        oauth_dao: UserOAuthProviderDao,
        register_web_user: RegisterWebUser,
    ) -> None:
        self.config = config
        self.uow = uow
        self.registry = registry
        self.user_dao = user_dao
        self.oauth_dao = oauth_dao
        self.register_web_user = register_web_user

    async def _execute(self, actor: UserDto, data: AuthenticateOAuthDto) -> UserDto:
        identity = await _exchange(
            self.registry, self.config, data.provider, data.code, data.code_verifier
        )

        existing = await self.oauth_dao.get_by_provider(identity.provider, identity.provider_id)
        if existing is not None:  # A1
            if existing.is_blocked:
                raise _blocked()
            return existing

        if identity.email:
            by_email = await self.user_dao.get_by_email(identity.email)
            if by_email is not None:
                if not identity.email_verified:  # A4
                    logger.info(
                        f"Refused OAuth auto-link for '{identity.provider}': "
                        f"provider did not verify an email that already owns an account"
                    )
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail="oauth_email_unverified",
                    )
                if by_email.is_blocked:
                    raise _blocked()
                return await self._attach(by_email, identity)  # A2

        return await self._create(identity, data.referral_code)  # A3 / A5

    async def _attach(self, user: UserDto, identity: OAuthIdentity) -> UserDto:
        try:
            async with self.uow:
                await self.oauth_dao.create(_identity_row(user.id, identity))
                if not user.is_email_verified:
                    # The provider signed for this exact address, which is the same
                    # proof the emailed code provides.
                    user.is_email_verified = True
                    await self.user_dao.update(user)
                await self.uow.commit()
        except IntegrityError:
            # A concurrent first sign-in won the unique index; its row is authoritative.
            attached = await self.oauth_dao.get_by_provider(identity.provider, identity.provider_id)
            if attached is None:
                raise
            return attached
        return user

    async def _create(self, identity: OAuthIdentity, referral_code: Optional[str]) -> UserDto:
        verified_email = identity.email if identity.email and identity.email_verified else None

        if referral_code and not await self.user_dao.get_by_referral_code(referral_code):
            referral_code = None

        new_user = UserDto(
            telegram_id=None,
            # OAuthProvider and AuthType share member names by construction, so the
            # creation-origin marker needs no lookup table to keep in sync.
            auth_type=AuthType(identity.provider.value),
            email=verified_email,
            is_email_verified=verified_email is not None,
            password_hash=None,
            username=None,
            name=_display_name(identity),
            language=self.config.default_locale,
        )

        try:
            created = await self.register_web_user.system(
                RegisterWebUserDto(user=new_user, referral_code=referral_code)
            )
        except IntegrityError:
            # Raced with another sign-in for the same identity (or the same email).
            existing = await self.oauth_dao.get_by_provider(identity.provider, identity.provider_id)
            if existing is not None:
                return existing
            if verified_email:
                by_email = await self.user_dao.get_by_email(verified_email)
                if by_email is not None:
                    return await self._attach(by_email, identity)
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="User creation conflict"
            )

        try:
            async with self.uow:
                await self.oauth_dao.create(_identity_row(created.id, identity))
                await self.uow.commit()
        except IntegrityError:
            # RegisterWebUser commits its own transaction, so the account already
            # exists at this point. Losing the identity row here is self-healing for a
            # verified email (the next attempt lands on A2 and attaches); for A5 it
            # would strand an empty account, which the unique index bounds to one stray
            # row per race. A distributed transaction is not worth that blast radius.
            existing = await self.oauth_dao.get_by_provider(identity.provider, identity.provider_id)
            if existing is None:
                raise
            return existing

        return created


@dataclass
class LinkOAuthProviderDto:
    provider: OAuthProvider
    code: str
    code_verifier: Optional[str]


@dataclass
class OAuthLinkResult:
    user: UserDto
    merged: bool  # True only when a separate account was absorbed into the actor


class LinkOAuthProvider(Interactor[LinkOAuthProviderDto, OAuthLinkResult]):
    """Attach a provider identity to the account the caller is already signed into.

    The same three outcomes as ``LinkTelegram``, for the same reasons:

    - the identity belongs to nobody → plain link;
    - it belongs to a separate account → **merge** that account into the actor;
    - both accounts hold a live paid subscription → refuse, that is a support decision.

    Note what ``stamp_identity`` does *not* do: it never inserts the identity row.
    ``AccountMergeDao.reassign_children`` already repoints ``user_oauth_providers``
    from the absorbed account to the survivor, and the guards above guarantee the
    actor holds no row for this provider — so the row moves on its own. Adding an
    insert here would collide with it.
    """

    required_permission = Permission.PUBLIC

    def __init__(
        self,
        config: AppConfig,
        uow: UnitOfWork,
        registry: OAuthClientRegistry,
        user_dao: UserDao,
        oauth_dao: UserOAuthProviderDao,
        account_merge_service: AccountMergeService,
    ) -> None:
        self.config = config
        self.uow = uow
        self.registry = registry
        self.user_dao = user_dao
        self.oauth_dao = oauth_dao
        self.account_merge_service = account_merge_service

    async def _execute(self, actor: UserDto, data: LinkOAuthProviderDto) -> OAuthLinkResult:
        identity = await _exchange(
            self.registry, self.config, data.provider, data.code, data.code_verifier
        )

        own = [
            p
            for p in await self.oauth_dao.get_user_providers(actor.id)
            if p.provider == identity.provider
        ]
        if own:
            if own[0].provider_id == identity.provider_id:
                return OAuthLinkResult(user=actor, merged=False)
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="already_linked_other")

        existing = await self.oauth_dao.get_by_provider(identity.provider, identity.provider_id)
        if existing is None:
            return OAuthLinkResult(user=await self._link(actor, identity), merged=False)
        if existing.id == actor.id:  # pragma: no cover - the `own` check covers this
            return OAuthLinkResult(user=actor, merged=False)
        return OAuthLinkResult(user=await self._merge(actor, existing, identity), merged=True)

    async def _link(self, actor: UserDto, identity: OAuthIdentity) -> UserDto:
        # Adopt the address only when it is verified, the actor has none, and nobody
        # else holds it. Otherwise just link — the link is what was asked for.
        adopt = (
            identity.email
            and identity.email_verified
            and actor.email is None
            and await self.user_dao.get_by_email(identity.email) is None
        )
        async with self.uow:
            await self.oauth_dao.create(_identity_row(actor.id, identity))
            if adopt:
                actor.email = identity.email
                actor.is_email_verified = True
                updated = await self.user_dao.update(actor)
                if not updated:
                    raise HTTPException(
                        status_code=status.HTTP_404_NOT_FOUND,
                        detail="User not found during OAuth link",
                    )
                actor = updated
            await self.uow.commit()
        return actor

    async def _merge(self, actor: UserDto, loser: UserDto, identity: OAuthIdentity) -> UserDto:
        # Two live Telegram bindings cannot survive one row: absorbing `loser` drops its
        # telegram_id, and its owner's next /start would silently mint a third account.
        if actor.telegram_id is not None and loser.telegram_id is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="two_telegram_accounts"
            )

        def stamp_identity(survivor: UserDto, absorbed: UserDto) -> None:
            # The oauth row itself is repointed by reassign_children — see the class
            # docstring. Only the scalars the absorbed row frees up move here.
            if survivor.telegram_id is None and absorbed.telegram_id is not None:
                survivor.telegram_id = absorbed.telegram_id
                if survivor.username is None:
                    survivor.username = absorbed.username
            if survivor.email is None and absorbed.email is not None:
                survivor.email = absorbed.email
                survivor.is_email_verified = absorbed.is_email_verified
            if survivor.password_hash is None:
                survivor.password_hash = absorbed.password_hash

        return await self.account_merge_service.merge(actor, loser, stamp_identity)


@dataclass
class UnlinkOAuthProviderDto:
    provider: OAuthProvider


class UnlinkOAuthProvider(Interactor[UnlinkOAuthProviderDto, UserDto]):
    """Detach a provider, unless it is the last way into the account.

    Sessions are deliberately left alone: the caller is signed in through this very
    session, and logging them out for tidying up their settings would be hostile.
    ``auth_type`` is not touched either — it records how the account was created, the
    same way a Telegram account keeps ``auth_type=telegram`` after attaching an email.
    """

    required_permission = Permission.PUBLIC

    def __init__(
        self,
        uow: UnitOfWork,
        oauth_dao: UserOAuthProviderDao,
    ) -> None:
        self.uow = uow
        self.oauth_dao = oauth_dao

    async def _execute(self, actor: UserDto, data: UnlinkOAuthProviderDto) -> UserDto:
        providers = await self.oauth_dao.get_user_providers(actor.id)
        if not any(p.provider == data.provider for p in providers):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="not_linked")

        if count_sign_in_methods(actor, providers, excluding=data.provider) == 0:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="last_sign_in_method")

        async with self.uow:
            await self.oauth_dao.delete(actor.id, data.provider)
            await self.uow.commit()
        return actor


def _identity_row(user_id: int, identity: OAuthIdentity) -> UserOAuthProviderDto:
    return UserOAuthProviderDto(
        user_id=user_id,
        provider=identity.provider,
        provider_id=identity.provider_id,
        # Recorded even when unverified: display only, never matched on.
        provider_email=identity.email,
    )


def _display_name(identity: OAuthIdentity) -> str:
    if identity.name:
        return identity.name
    if identity.email:
        return identity.email.split("@")[0]
    return identity.provider.value.capitalize()
