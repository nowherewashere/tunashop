from fastapi import APIRouter

from src.core.constants import API_V1

from .auth import router as auth_router
from .config import router as config_router
from .events import router as events_router
from .onboarding import router as onboarding_router
from .plans import router as plans_router
from .referral import router as referral_router
from .subscription import router as subscription_router

router = APIRouter(prefix=API_V1 + "/public")
router.include_router(plans_router)
router.include_router(auth_router)
router.include_router(subscription_router)
router.include_router(referral_router)
router.include_router(onboarding_router)
router.include_router(config_router)
router.include_router(events_router)

__all__ = ["router"]
