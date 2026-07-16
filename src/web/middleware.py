from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.core.constants import API_V1


class NoStoreCacheControlMiddleware:
    """Add `Cache-Control: no-store` to API responses lacking an explicit policy.

    Defense in depth against edge/CDN caching: the CDN in front of the origin
    caches responses without Cache-Control for a long time by default, which is
    never acceptable for the per-user /api/v1 endpoints. Endpoints that manage
    their own caching semantics (e.g. the SSE support stream sends `no-cache`)
    are left untouched.

    Implemented as pure ASGI (not BaseHTTPMiddleware) so streaming/SSE
    responses pass through without buffering.
    """

    def __init__(self, app: ASGIApp, prefix: str = API_V1) -> None:
        self.app = app
        self.prefix = prefix

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self._matches(scope["path"]):
            await self.app(scope, receive, send)
            return

        async def send_with_cache_control(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers: list[tuple[bytes, bytes]] = message.setdefault("headers", [])
                if not any(name.lower() == b"cache-control" for name, _ in headers):
                    headers.append((b"cache-control", b"no-store"))
            await send(message)

        await self.app(scope, receive, send_with_cache_control)

    def _matches(self, path: str) -> bool:
        return path == self.prefix or path.startswith(self.prefix + "/")
