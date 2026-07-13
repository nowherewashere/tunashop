import hashlib

from aiogram import F, Router
from aiogram.enums import ButtonStyle, ParseMode
from aiogram.types import (
    InlineKeyboardButton,
    InlineQuery,
    InlineQueryResultArticle,
    InlineQueryResultCachedPhoto,
    InlineQueryResultUnion,
    InputTextMessageContent,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from dishka import FromDishka
from dishka.integrations.aiogram_dialog import inject
from loguru import logger

from src.application.common import BotService, TranslatorRunner
from src.application.common.dao import PlanDao, UserDao
from src.core.constants import INLINE_QUERY_INVITE

router = Router(name=__name__)


@inject
@router.inline_query(F.query == INLINE_QUERY_INVITE)
async def handle_inline_query(
    inline_query: InlineQuery,
    user_dao: FromDishka[UserDao],
    bot_service: FromDishka[BotService],
    plan_dao: FromDishka[PlanDao],
    i18n: FromDishka[TranslatorRunner],
) -> None:
    user = await user_dao.get_by_telegram_id(inline_query.from_user.id)

    if not user:
        logger.warning(
            f"User with Telegram ID '{inline_query.from_user.id}' not found for inline query"
        )
        return

    logger.info(f"{user.log} Sent inline query {INLINE_QUERY_INVITE}")

    result_id = hashlib.md5(inline_query.query.strip().encode()).hexdigest()
    referral_url = await bot_service.get_referral_url(user.referral_code)
    bot_name = await bot_service.get_my_name()
    # Real length of the INVITED trial plan (Trial+), not a hardcoded number — same
    # single source as the invite screen and the site /config.
    trial_days = (await plan_dao.get_invited_trial_days()) or 0
    message_text = i18n.get("inline-invite.message", bot_name=bot_name, trial_days=trial_days)

    builder = InlineKeyboardBuilder()
    builder.row(
        InlineKeyboardButton(
            text=i18n.get("inline-invite.start"),
            style=ButtonStyle.SUCCESS,
            url=referral_url,
        )
    )

    # Preferred: a photo card with the banner (fix.txt #6). Inline results can only
    # carry media by file_id; if that can't be prepared we fall back to a text card
    # so sharing always works.
    banner_file_id = await bot_service.get_invite_banner_file_id()

    result: InlineQueryResultUnion
    if banner_file_id:
        result = InlineQueryResultCachedPhoto(
            id=result_id,
            photo_file_id=banner_file_id,
            title=i18n.get("inline-invite.title"),
            description=i18n.get("inline-invite.description"),
            caption=message_text,
            parse_mode=ParseMode.HTML,
            reply_markup=builder.as_markup(),
        )
    else:
        result = InlineQueryResultArticle(
            id=result_id,
            title=i18n.get("inline-invite.title"),
            description=i18n.get("inline-invite.description"),
            input_message_content=InputTextMessageContent(
                message_text=message_text,
                parse_mode=ParseMode.HTML,
            ),
            reply_markup=builder.as_markup(),
        )

    await inline_query.answer([result], cache_time=1, is_personal=True)
