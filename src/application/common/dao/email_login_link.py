from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class EmailLoginLinkDao(Protocol):
    """One-tap sign-in links mailed alongside the login code.

    A link in an email is a bearer credential, so it is held separately from the
    6-digit code (which is bound to the address by delivery) and given far more
    entropy. Single-use and short-lived, like the code it accompanies.
    """

    async def put(self, token: str, email: str, ttl: int) -> None: ...

    async def consume(self, token: str) -> Optional[str]:
        """The address the link was issued for, read and deleted in one step."""
        ...
