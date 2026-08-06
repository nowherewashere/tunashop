from typing import Optional, Protocol
from uuid import UUID

from src.application.dto import PlanSnapshotDto


class TrafficPoolAccess(Protocol):
    """Pool bookkeeping every path that assigns squads from a plan has to go through.

    A port rather than the concrete service because the services package composes use
    cases (``AccountMergeService`` pulls in ``GetReferralSummary``): a use case reaching
    back into ``src.application.services`` closes an import loop through the package
    ``__init__``. The implementation is
    :class:`~src.application.services.traffic_pools.TrafficPoolAccessService`.
    """

    async def effective_squads(
        self,
        plan: PlanSnapshotDto,
        usage_subscription_id: Optional[int],
        *,
        new_term: bool = False,
    ) -> list[UUID]: ...

    async def reconcile_windows(
        self,
        subscription_id: int,
        plan_snapshot: PlanSnapshotDto,
        *,
        new_term: bool = False,
    ) -> None: ...

    async def carry_over(self, from_subscription_id: int, to_subscription_id: int) -> None: ...
