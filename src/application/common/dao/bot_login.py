from dataclasses import dataclass
from typing import Literal, Optional, Protocol, runtime_checkable

BotLoginStatus = Literal["pending", "approved", "declined"]


@dataclass(frozen=True)
class BotLoginRequest:
    """A website sign-in waiting to be confirmed inside the bot."""

    status: BotLoginStatus
    # sha256 of the httpOnly cookie handed to the browser that started this. The claim
    # is refused without it, so learning the token alone — by reading the QR off a
    # screen, say — is not enough to take the session.
    binding_hash: str
    # Shown in the bot's confirmation message so the person can tell whether the
    # request plausibly came from them.
    ip: Optional[str] = None
    # Filled in on approval.
    user_id: Optional[int] = None


@runtime_checkable
class BotLoginDao(Protocol):
    async def put(self, token: str, value: BotLoginRequest, ttl: int) -> None: ...

    async def get(self, token: str) -> Optional[BotLoginRequest]: ...

    async def resolve(self, token: str, status: BotLoginStatus, user_id: Optional[int]) -> bool:
        """Move a pending request to approved/declined. False if it is gone or already
        resolved — which is what makes a confirmation single-use."""
        ...

    async def consume(self, token: str) -> Optional[BotLoginRequest]:
        """Read and delete, so a session can be claimed exactly once."""
        ...
