from typing import Optional

import aiohttp
from loguru import logger

from src.core.config import AppConfig

_SITEVERIFY_URL = "https://challenges.cloudflare.com/turnstile/v0/siteverify"


class TurnstileVerifierImpl:
    """Verifies Cloudflare Turnstile tokens via the siteverify API.

    Disabled (always passes) when TURNSTILE_SECRET is unset, so the flow keeps
    working until the captcha is turned on. Fails open on network/parse errors —
    the per-email/IP rate limit remains the hard backstop.
    """

    def __init__(self, config: AppConfig) -> None:
        self._config = config

    @property
    def is_enabled(self) -> bool:
        secret = self._config.turnstile_secret
        return bool(secret and secret.get_secret_value())

    async def verify(self, token: str, ip: Optional[str] = None) -> bool:
        if not self.is_enabled:
            return True
        if not token:
            return False

        secret = self._config.turnstile_secret
        assert secret is not None  # guaranteed by is_enabled
        data = {"secret": secret.get_secret_value(), "response": token}
        if ip:
            data["remoteip"] = ip

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _SITEVERIFY_URL,
                    data=data,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as response:
                    payload = await response.json()
                    return bool(payload.get("success"))
        except Exception as e:  # noqa: BLE001 - fail open on infra errors
            logger.warning(f"Turnstile verification error (failing open): {e}")
            return True
