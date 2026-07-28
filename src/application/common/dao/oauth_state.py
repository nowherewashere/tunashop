from dataclasses import dataclass
from typing import Literal, Optional, Protocol, runtime_checkable

from src.core.enums import OAuthProvider

OAuthFlowMode = Literal["login", "link"]


@dataclass(frozen=True)
class OAuthFlowState:
    """Everything the callback needs to trust, carried server-side between legs.

    None of it travels through the browser: the only thing the user agent holds is
    the opaque ``state`` key and the binding cookie, so nothing here is client
    controlled. That is what lets the callback act on ``mode`` and ``actor_user_id``
    without re-deriving them from a request the provider shaped.
    """

    provider: OAuthProvider
    # Set by the route, never by the client — there is a separate authenticated
    # endpoint for link mode precisely so this cannot be requested.
    mode: OAuthFlowMode
    code_verifier: Optional[str]
    # sha256 of the value in the httpOnly binding cookie. Stops a login-CSRF where an
    # attacker starts their own flow, harvests the state, and feeds the victim a
    # callback URL that would sign the victim into the attacker's account.
    binding_hash: str
    referral_code: Optional[str]
    # Link mode only: the account the identity attaches to. Resolved here rather than
    # from the access-token cookie because a 15-minute token can expire while the user
    # sits on the provider's consent screen.
    actor_user_id: Optional[int] = None


@runtime_checkable
class OAuthStateDao(Protocol):
    async def put(self, state: str, value: OAuthFlowState, ttl: int) -> None: ...

    async def consume(self, state: str) -> Optional[OAuthFlowState]:
        """Read and delete in one step — a state is single-use by construction."""
        ...
