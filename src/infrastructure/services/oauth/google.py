from typing import Any, Final, Optional
from urllib.parse import urlencode

import jwt

from src.application.common.oauth import OAuthAuthorizeRequest, OAuthIdentity
from src.core.config.oauth import OAuthProviderCredentials
from src.core.enums import OAuthProvider
from src.core.exceptions import OAuthExchangeError

from .base import generate_pkce_verifier, pkce_challenge, post_form
from .jwks import JwksCache

# Hardcoded rather than read from the OpenID discovery document: these have been
# stable for over a decade, and fetching discovery would add a boot-time dependency
# on Google for a feature that ships disabled.
_AUTHORIZE_URL: Final[str] = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL: Final[str] = "https://oauth2.googleapis.com/token"
_JWKS_URL: Final[str] = "https://www.googleapis.com/oauth2/v3/certs"
# Google documents both spellings of the issuer claim.
_ISSUERS: Final[frozenset[str]] = frozenset({"https://accounts.google.com", "accounts.google.com"})
# Non-sensitive scopes only. Anything beyond these three drags the app into Google's
# verification review, which takes weeks — see the operator checklist.
_SCOPES: Final[str] = "openid email profile"
_CLOCK_SKEW_SECONDS: Final[int] = 60


class GoogleOAuthClient:
    """Google Sign-In over the authorization-code flow with PKCE.

    Identity comes from the ``id_token`` rather than a ``/userinfo`` call: it is one
    fewer round trip, and — the actual reason — it makes ``email_verified`` a *signed*
    claim. That boolean is the sole gate on attaching this identity to an existing
    account, so it should not rest on an unauthenticated JSON body, even one arriving
    over TLS.
    """

    provider = OAuthProvider.GOOGLE

    def __init__(self, credentials: OAuthProviderCredentials, timeout: int) -> None:
        self._credentials = credentials
        self._timeout = timeout
        self._jwks = JwksCache(_JWKS_URL, timeout=timeout)

    def build_authorize_request(self, *, redirect_uri: str, state: str) -> OAuthAuthorizeRequest:
        verifier = generate_pkce_verifier()
        params = {
            "client_id": self._credentials.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": _SCOPES,
            "state": state,
            "code_challenge": pkce_challenge(verifier),
            "code_challenge_method": "S256",
            # No refresh token wanted: we read the identity once and issue our own
            # session. Holding a Google refresh token would be data we never use.
            "access_type": "online",
            # Always show the account chooser. Silently reusing whichever Google
            # account the browser happens to hold is a real footgun on shared devices.
            "prompt": "select_account",
        }
        return OAuthAuthorizeRequest(
            url=f"{_AUTHORIZE_URL}?{urlencode(params)}",
            code_verifier=verifier,
        )

    async def exchange(
        self, *, code: str, redirect_uri: str, code_verifier: Optional[str]
    ) -> OAuthIdentity:
        if not code_verifier:
            raise OAuthExchangeError("missing PKCE verifier for Google exchange")

        payload = await post_form(
            _TOKEN_URL,
            {
                "code": code,
                "client_id": self._credentials.client_id,
                "client_secret": self._credentials.client_secret.get_secret_value(),
                "redirect_uri": redirect_uri,
                "grant_type": "authorization_code",
                "code_verifier": code_verifier,
            },
            timeout=self._timeout,
        )

        id_token = payload.get("id_token")
        if not isinstance(id_token, str) or not id_token:
            raise OAuthExchangeError("token response carried no id_token")

        claims = await self._verify_id_token(id_token)

        subject = claims.get("sub")
        if not isinstance(subject, str) or not subject:
            raise OAuthExchangeError("id_token carried no subject")

        email = claims.get("email")
        return OAuthIdentity(
            provider=OAuthProvider.GOOGLE,
            provider_id=subject,
            email=email if isinstance(email, str) and email else None,
            email_verified=claims.get("email_verified") is True,
            name=claims.get("name") if isinstance(claims.get("name"), str) else None,
        )

    async def _verify_id_token(self, id_token: str) -> dict[str, Any]:
        try:
            kid = jwt.get_unverified_header(id_token).get("kid")
        except jwt.InvalidTokenError as e:
            raise OAuthExchangeError(f"unreadable id_token header: {e}") from e
        if not isinstance(kid, str) or not kid:
            raise OAuthExchangeError("id_token header carried no kid")

        signing_key = await self._jwks.get_key(kid)

        try:
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._credentials.client_id,
                leeway=_CLOCK_SKEW_SECONDS,
                options={"require": ["exp", "iat", "aud", "iss", "sub"]},
            )
        except jwt.InvalidTokenError as e:
            raise OAuthExchangeError(f"id_token failed verification: {e}") from e

        # pyjwt only checks `iss` when handed a single expected value; Google uses two
        # spellings, so the check happens here instead.
        if claims.get("iss") not in _ISSUERS:
            raise OAuthExchangeError("id_token issuer is not Google")

        return claims
