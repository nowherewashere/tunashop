from typing import Final, NamedTuple, Optional

from pydantic import SecretStr, model_validator

from src.core.constants import API_V1
from src.core.enums import OAuthProvider

from .base import BaseConfig


class OAuthProviderCredentials(NamedTuple):
    client_id: str
    client_secret: SecretStr


# Path shape of the provider redirect URI, appended to the public base URL. It is
# registered byte-for-byte in each provider's console, so it lives in exactly one
# place — change it here and the operator checklist changes with it.
_CALLBACK_PATH: Final[str] = API_V1 + "/public/auth/oauth/{provider}/callback"


class OAuthConfig(BaseConfig, env_prefix="OAUTH_"):
    """Social sign-in over the authorization-code flow with PKCE.

    The whole exchange runs server-side: the SPA is a static export with no server
    of its own, and a client secret has no business reaching a browser. The browser
    only follows redirects — see ``src/web/endpoints/public/auth.py``.

    Ships OFF. With no provider enabled, ``/public/config`` reports an empty provider
    list (so the SPA renders no buttons) and ``/auth/oauth/*`` answers 404 — the same
    surface as a typo, so a disabled provider is not a config oracle.

    Adding a provider is deliberately mechanical: three fields here, one row in
    ``_PROVIDER_FIELDS``, one client module under
    ``src/infrastructure/services/oauth/``, and one line in its registry. Nothing
    else in the codebase branches on a provider name.
    """

    # Public origin the provider redirects back to.
    #
    # MUST be the SITE origin (https://v-tuna.com), never the API host: the auth
    # cookies are host-only (``set_auth_cookies`` sets no ``domain=``), so a callback
    # landing anywhere else would set the session on the wrong host and the SPA would
    # never see it.
    #
    # Its own variable rather than a derivation of WEB_CABINET_URL, because the public
    # domain rotates under blocking (tuna-vpn.com -> v-tuna.com) and the redirect URI
    # must be re-registered in the provider console *before* the switch. Keeping the
    # two independently rotatable is the point. Falls back to WEB_CABINET_URL when
    # unset — see ``AppConfig.oauth_public_base_url``.
    public_base_url: str = ""

    google_enabled: bool = False
    google_client_id: str = ""
    google_client_secret: Optional[SecretStr] = None

    # How long a started flow may sit on the provider's consent screen before its
    # state is discarded. Long enough for a slow account chooser, short enough that
    # an abandoned flow does not linger.
    state_ttl_seconds: int = 600
    http_timeout_seconds: int = 10
    # Per-IP budgets. One sign-in spends two requests (start + callback), so these
    # are generous; the sharp edge is the nginx `tuna_auth` zone in front.
    start_max_per_ip: int = 30
    callback_max_per_ip: int = 30
    rate_window_seconds: int = 600

    @property
    def _provider_fields(self) -> dict[OAuthProvider, tuple[bool, str, Optional[SecretStr]]]:
        """The single mapping from provider to its flat settings.

        pydantic-settings composes sub-configs by prefix, so genuinely nested
        per-provider settings would need ``env_nested_delimiter`` and would read
        nothing like the rest of the config tree. Flat fields plus this one mapping
        keep the env vars conventional while leaving exactly one place that knows a
        provider's name.
        """
        return {
            OAuthProvider.GOOGLE: (
                self.google_enabled,
                self.google_client_id,
                self.google_client_secret,
            ),
        }

    @property
    def enabled_providers(self) -> tuple[OAuthProvider, ...]:
        return tuple(
            provider
            for provider, (enabled, client_id, secret) in self._provider_fields.items()
            if enabled and client_id and secret is not None
        )

    @property
    def is_active(self) -> bool:
        return bool(self.enabled_providers)

    def credentials(self, provider: OAuthProvider) -> Optional[OAuthProviderCredentials]:
        fields = self._provider_fields.get(provider)
        if fields is None:
            return None
        enabled, client_id, secret = fields
        if not (enabled and client_id and secret is not None):
            return None
        return OAuthProviderCredentials(client_id=client_id, client_secret=secret)

    def redirect_uri(self, base_url: str, provider: OAuthProvider) -> str:
        """The exact value registered in the provider's console.

        Providers match it byte-for-byte: no trailing slash, no query string.
        """
        return base_url.rstrip("/") + _CALLBACK_PATH.format(provider=provider.value)

    @model_validator(mode="after")
    def _validate(self) -> "OAuthConfig":
        # Refuse to boot half-configured rather than failing at the first user's
        # click: an enabled provider missing its credentials would 500 mid-redirect,
        # after the user has already left for the consent screen.
        for provider, (enabled, client_id, secret) in self._provider_fields.items():
            if not enabled:
                continue
            prefix = f"OAUTH_{provider.value.upper()}"
            if not client_id:
                raise ValueError(f"{prefix}_CLIENT_ID must be set when {prefix}_ENABLED=true")
            if secret is None:
                raise ValueError(f"{prefix}_CLIENT_SECRET must be set when {prefix}_ENABLED=true")
        return self
