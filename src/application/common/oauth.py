from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable

from src.core.enums import OAuthProvider


@dataclass(frozen=True)
class OAuthIdentity:
    """What a provider tells us about the person who just signed in.

    The canonical shape every provider is normalized into, so the use cases never
    learn a provider's wire format.
    """

    provider: OAuthProvider
    # Stable, opaque, provider-scoped subject id. Never an email: emails get
    # reassigned and renamed, and this is the account's primary key with the provider.
    provider_id: str
    email: Optional[str]
    # Whether the PROVIDER asserts it verified this address. The single input to the
    # auto-link decision, and the reason a provider that cannot assert it (or asserts
    # false) may never be matched onto an existing account — see AuthenticateOAuth.
    email_verified: bool
    name: Optional[str]


@dataclass(frozen=True)
class OAuthAuthorizeRequest:
    url: str
    # None for a provider without PKCE support; the flow then rests on the client
    # secret plus the single-use bound state.
    code_verifier: Optional[str]


@runtime_checkable
class OAuthProviderClient(Protocol):
    @property
    def provider(self) -> OAuthProvider: ...

    def build_authorize_request(
        self, *, redirect_uri: str, state: str
    ) -> OAuthAuthorizeRequest: ...

    async def exchange(
        self, *, code: str, redirect_uri: str, code_verifier: Optional[str]
    ) -> OAuthIdentity:
        """Trade an authorization code for a verified identity.

        Deliberately one call rather than exchange-then-fetch: *how* an identity is
        established is provider-private (Google reads a signed id_token, others call
        a userinfo endpoint) and must not leak into the use case. Raises on any
        failure — this path fails closed, never granting a session on a bad exchange.
        """
        ...


@runtime_checkable
class OAuthClientRegistry(Protocol):
    def get(self, provider: OAuthProvider) -> Optional[OAuthProviderClient]:
        """The client for an enabled provider, or None when it is off/unknown."""
        ...

    @property
    def enabled(self) -> tuple[OAuthProvider, ...]: ...
