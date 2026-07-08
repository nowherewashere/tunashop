from typing import Optional, Protocol, runtime_checkable


@runtime_checkable
class TurnstileVerifier(Protocol):
    @property
    def is_enabled(self) -> bool:
        """True when a Turnstile secret is configured."""
        ...

    async def verify(self, token: str, ip: Optional[str] = None) -> bool:
        """Validate a Turnstile token with Cloudflare. Passes through when disabled."""
        ...
