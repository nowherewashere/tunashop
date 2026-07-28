import base64
import hashlib
import json
import secrets
from typing import Any

import aiohttp
from loguru import logger

from src.core.exceptions import OAuthExchangeError


def generate_pkce_verifier() -> str:
    """RFC 7636 code verifier: 43-128 chars from the unreserved set."""
    return secrets.token_urlsafe(64)[:96]


def pkce_challenge(verifier: str) -> str:
    """S256 challenge — base64url(sha256(verifier)) with the padding stripped."""
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


async def post_form(url: str, data: dict[str, str], timeout: int) -> dict[str, Any]:
    """POST an x-www-form-urlencoded body and return the JSON response.

    A per-call session, like ``TurnstileVerifierImpl``: a sign-in costs a couple of
    requests, which is not enough traffic to justify an app-scoped session and its
    lifecycle. Unlike Turnstile this raises rather than failing open — see
    ``OAuthExchangeError``.
    """
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                url, data=data, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                body = await response.text()
                if response.status != 200:
                    # The body can carry the client secret back in an echoed request
                    # on some providers, so log the status and a short prefix only.
                    logger.warning(f"OAuth token endpoint {url} returned {response.status}")
                    raise OAuthExchangeError(f"token endpoint returned {response.status}")
                return _parse_json(body, url)
    except aiohttp.ClientError as e:
        raise OAuthExchangeError(f"token endpoint unreachable: {e}") from e
    except TimeoutError as e:
        raise OAuthExchangeError("token endpoint timed out") from e


async def get_json(url: str, headers: dict[str, str], timeout: int) -> dict[str, Any]:
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                url, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)
            ) as response:
                body = await response.text()
                if response.status != 200:
                    logger.warning(f"OAuth endpoint {url} returned {response.status}")
                    raise OAuthExchangeError(f"endpoint returned {response.status}")
                return _parse_json(body, url)
    except aiohttp.ClientError as e:
        raise OAuthExchangeError(f"endpoint unreachable: {e}") from e
    except TimeoutError as e:
        raise OAuthExchangeError("endpoint timed out") from e


def _parse_json(body: str, url: str) -> dict[str, Any]:
    try:
        payload = json.loads(body)
    except ValueError as e:
        raise OAuthExchangeError(f"non-JSON response from {url}") from e
    if not isinstance(payload, dict):
        raise OAuthExchangeError(f"unexpected JSON shape from {url}")
    return payload
