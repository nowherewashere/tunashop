from typing import Final

from src.application.common import Interactor

from .commands.manage import (
    CommitTrafficPool,
    DeleteTrafficPool,
    GetPoolNodes,
    GetPoolNodesDto,
    GetTrafficPools,
)

TRAFFIC_POOL_USE_CASES: Final[tuple[type[Interactor], ...]] = (
    CommitTrafficPool,
    DeleteTrafficPool,
    GetPoolNodes,
    GetTrafficPools,
)

__all__ = [
    "TRAFFIC_POOL_USE_CASES",
    "CommitTrafficPool",
    "DeleteTrafficPool",
    "GetPoolNodes",
    "GetPoolNodesDto",
    "GetTrafficPools",
]
