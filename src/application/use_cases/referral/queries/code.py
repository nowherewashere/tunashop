from dataclasses import dataclass

from loguru import logger

from src.application.common import Interactor
from src.application.common.dao import UserDao
from src.application.dto import UserDto
from src.core.constants import ASSETS_DIR
from src.core.utils.qr import render_qr_png_base64


@dataclass(frozen=True)
class ValidateReferralCodeDto:
    user_id: int
    referral_code: str


class ValidateReferralCode(Interactor[ValidateReferralCodeDto, bool]):
    required_permission = None

    def __init__(self, user_dao: UserDao) -> None:
        self.user_dao = user_dao

    async def _execute(self, actor: UserDto, data: ValidateReferralCodeDto) -> bool:
        referrer = await self.user_dao.get_by_referral_code(data.referral_code)
        if not referrer or referrer.id == data.user_id:
            logger.warning(
                f"Invalid referral code '{data.referral_code}' "
                f"or self-referral by user_id '{data.user_id}'"
            )
            return False
        return True


class GenerateReferralQr(Interactor[str, str]):
    required_permission = None

    async def _execute(self, actor: UserDto, url: str) -> str:
        qr_base64 = render_qr_png_base64(url, logo_path=ASSETS_DIR / "logo.png")
        logger.info(f"{actor.log} Generated referral QR for URL '{url}'")
        return qr_base64
