import asyncio
from time import perf_counter
from typing import Optional

from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import EventsDao
from src.application.common.remnawave import Remnawave
from src.application.common.uow import UnitOfWork
from src.application.dto import UserDto
from src.application.dto.metrics import NodeInfoDto
from src.core.metrics import PROBE_TCP_TIMEOUT_SECONDS, ConnectOutcome, MetricEvent, MetricSource


class RunNodeProbes(Interactor[None, int]):
    """Light active probe per node (metrics spec §6.2).

    Every few minutes, TCP-reaches each enabled node and writes one ``probe`` row.
    This answers only "is the node up at all?" — the honest limit of an external
    probe (spec §6.4): real ТСПУ reachability is seen from passive RU-user signals,
    so we don't over-weight this. It's what feeds the already-specced ``/status``.

    Footprint is tiny: one check per node, tens of rows per run. ``protocol`` is left
    null (node-level) — per-protocol probing needs the hosts/inbounds inventory and
    is a documented follow-up (see the runbook); node + panel_connected already give
    the up/down signal ``/status`` and the health job need.
    """

    required_permission = None

    def __init__(
        self,
        remnawave: Remnawave,
        events_dao: EventsDao,
        uow: UnitOfWork,
    ) -> None:
        self.remnawave = remnawave
        self.events_dao = events_dao
        self.uow = uow

    async def _execute(self, actor: UserDto, data: None) -> int:
        nodes = [node for node in await self.remnawave.get_nodes() if not node.is_disabled]
        if not nodes:
            logger.info("[metrics] node probe: no enabled nodes")
            return 0

        probed = await asyncio.gather(*(self._probe(node) for node in nodes))

        try:
            async with self.uow:
                for node, (outcome, latency_ms) in zip(nodes, probed):
                    await self.events_dao.append(
                        event_type=MetricEvent.PROBE,
                        source=MetricSource.PROBE,
                        user_ref=None,  # node-level, not per-user
                        properties={
                            "node_id": node.name,
                            "protocol": None,
                            "operator": None,
                            "outcome": outcome,
                            "latency_ms": latency_ms,
                            "panel_connected": node.is_connected,
                            "country": node.country_code,
                        },
                    )
                await self.uow.commit()
        except Exception as error:
            logger.warning(f"[metrics] node probe write failed: {error}")
            return 0

        ok = sum(1 for outcome, _ in probed if outcome == ConnectOutcome.SUCCESS)
        logger.info(f"[metrics] node probe: {ok}/{len(nodes)} reachable")
        return len(nodes)

    @staticmethod
    async def _probe(node: NodeInfoDto) -> tuple[str, Optional[int]]:
        if not node.address or not node.port:
            return ConnectOutcome.FAIL, None
        start = perf_counter()
        try:
            _, writer = await asyncio.wait_for(
                asyncio.open_connection(node.address, node.port),
                timeout=PROBE_TCP_TIMEOUT_SECONDS,
            )
            writer.close()
            try:
                await writer.wait_closed()
            except Exception:  # closing errors don't change reachability
                pass
            return ConnectOutcome.SUCCESS, int((perf_counter() - start) * 1000)
        except (OSError, asyncio.TimeoutError):
            return ConnectOutcome.FAIL, None
