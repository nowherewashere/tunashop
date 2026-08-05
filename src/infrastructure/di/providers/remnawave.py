from collections.abc import AsyncIterator

from dishka import Provider, Scope, provide
from httpx import AsyncClient, Timeout
from loguru import logger
from remnapy import RemnawaveSDK

from src.core.config import AppConfig


class RemnawaveProvider(Provider):
    scope = Scope.APP

    @provide
    async def get_remnawave(self, config: AppConfig) -> AsyncIterator[RemnawaveSDK]:
        logger.debug("Initializing RemnawaveSDK")

        client = AsyncClient(
            base_url=f"{config.remnawave.url.get_secret_value()}/api",
            headers=config.remnawave.client_headers,
            cookies=config.remnawave.cookies,
            verify=True,
            timeout=Timeout(connect=15.0, read=25.0, write=10.0, pool=5.0),
        )

        try:
            yield RemnawaveSDK(client)
        finally:
            await client.aclose()
            logger.debug("RemnawaveSDK AsyncClient closed")
