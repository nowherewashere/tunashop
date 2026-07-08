from typing import Protocol, runtime_checkable


@runtime_checkable
class RateLimiter(Protocol):
    async def hit(
        self,
        scope: str,
        identifier: str,
        *,
        limit: int,
        window_seconds: int,
    ) -> bool:
        """Register one hit for (scope, identifier) in a fixed window.

        Returns True while the count is within ``limit``, False once it is exceeded.
        """
        ...
