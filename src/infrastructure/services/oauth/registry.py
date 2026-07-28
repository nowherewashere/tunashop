from typing import Callable, Final, Optional

from loguru import logger

from src.application.common.oauth import OAuthProviderClient
from src.core.config import AppConfig
from src.core.config.oauth import OAuthProviderCredentials
from src.core.enums import OAuthProvider

from .google import GoogleOAuthClient

# The one place a provider is bound to its implementation. Adding a provider is a
# single entry here plus its client module — nothing else in the codebase branches
# on a provider name.
_FACTORIES: Final[
    dict[OAuthProvider, Callable[[OAuthProviderCredentials, int], OAuthProviderClient]]
] = {
    OAuthProvider.GOOGLE: GoogleOAuthClient,
}


class OAuthClientRegistryImpl:
    """Clients for the providers that are both enabled and implemented.

    Built once at startup so a misconfiguration surfaces in the boot log rather than
    on a user's first click.
    """

    def __init__(self, config: AppConfig) -> None:
        self._clients: dict[OAuthProvider, OAuthProviderClient] = {}

        for provider in config.oauth.enabled_providers:
            factory = _FACTORIES.get(provider)
            if factory is None:
                # Enabled in config but with no implementation shipped — the config
                # validator cannot catch this, so say so loudly and stay off.
                logger.warning(f"OAuth provider '{provider}' is enabled but not implemented")
                continue
            credentials = config.oauth.credentials(provider)
            if credentials is None:  # pragma: no cover - enabled_providers guarantees it
                continue
            self._clients[provider] = factory(credentials, config.oauth.http_timeout_seconds)

        if self._clients:
            logger.info(f"OAuth sign-in enabled for: {', '.join(self._clients)}")

    def get(self, provider: OAuthProvider) -> Optional[OAuthProviderClient]:
        return self._clients.get(provider)

    @property
    def enabled(self) -> tuple[OAuthProvider, ...]:
        return tuple(self._clients)
