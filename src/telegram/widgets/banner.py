import functools
import re
from pathlib import Path
from typing import Any, Optional

from aiogram.types import ContentType
from aiogram_dialog import DialogManager
from aiogram_dialog.api.entities import MediaAttachment
from aiogram_dialog.widgets.common import Whenable
from aiogram_dialog.widgets.media import StaticMedia
from loguru import logger

from src.application.dto import TelegramUserDto
from src.core.config import AppConfig
from src.core.constants import CONFIG_KEY, USER_KEY
from src.core.enums import BannerFormat, BannerName, Locale

# Data key under which a getter can publish an ordered tuple of banner-file names
# (most specific first) for DataBanner to resolve — see plan_banner_candidates().
BANNER_CANDIDATES_KEY = "banner_candidates"


def _slugify(text: str) -> str:
    """ASCII slug for banner filenames: lowercase, non-alnum runs → single '_'.

    Non-ASCII names (e.g. Cyrillic plan titles) collapse to '', in which case the
    caller falls back to the id-based candidate — see plan_banner_candidates().
    """
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def plan_banner_candidates(display_name: str, plan_id: int) -> tuple[str, ...]:
    """Ordered banner-file names for a plan, most specific first (fix.txt #7).

    Convention: ``plan_<slug>`` (from the visible plan name, e.g. plan_standard),
    then ``plan_<id>`` as a rename-proof alternative, then the shared CHOOSE_SUB
    image; get_named_banner() adds the global DEFAULT as the final fallback.
    """
    names: list[str] = []
    slug = _slugify(display_name)
    if slug:
        names.append(f"plan_{slug}")
    names.append(f"plan_{plan_id}")
    names.append(str(BannerName.CHOOSE_SUB))
    return tuple(names)


def _find_banner_in(directory: Path, name: str) -> Optional[tuple[Path, ContentType]]:
    if not directory.exists():
        return None
    for banner_format in BannerFormat:
        candidate = directory / f"{name}.{banner_format}"
        if candidate.exists():
            return candidate, banner_format.content_type
    return None


@functools.lru_cache(maxsize=128)
def get_named_banner(
    banners_dir: Path,
    default_banners_dir: Path,
    names: tuple[str, ...],
    locale: Locale,
    default_locale: Locale,
) -> tuple[Path, ContentType]:
    """Resolve the first existing banner among ``names`` (then DEFAULT).

    A more specific name wins over a less specific one regardless of which asset
    root it lives in; within a single name, the project's banners take priority
    over the packaged defaults, and the requested locale over the default locale.
    """
    directories = [
        banners_dir / locale,
        banners_dir / default_locale,
        banners_dir,
        default_banners_dir / locale,
        default_banners_dir / default_locale,
        default_banners_dir,
    ]

    for name in (*names, str(BannerName.DEFAULT)):
        for directory in directories:
            found = _find_banner_in(directory, name)
            if found:
                logger.debug(f"Banner '{name}' found at '{found[0]}'")
                return found

    logger.error(f"No banner found for candidates {names} including global default")
    raise FileNotFoundError(f"No banner found for {names} or global default")


@functools.lru_cache(maxsize=64)
def get_banner(
    banners_dir: Path,
    default_banners_dir: Path,
    name: BannerName,
    locale: Locale,
    default_locale: Locale,
) -> tuple[Path, ContentType]:
    search_targets = [
        (banners_dir / locale, name),
        (banners_dir / locale, BannerName.DEFAULT),
        (banners_dir / default_locale, name),
        (banners_dir / default_locale, BannerName.DEFAULT),
        (banners_dir, BannerName.DEFAULT),
        (default_banners_dir / locale, name),
        (default_banners_dir / locale, BannerName.DEFAULT),
        (default_banners_dir / default_locale, name),
        (default_banners_dir / default_locale, BannerName.DEFAULT),
        (default_banners_dir, BannerName.DEFAULT),
    ]

    for directory, banner_name in search_targets:
        if not directory.exists():
            continue

        for banner_format in BannerFormat:
            candidate = directory / f"{banner_name}.{banner_format}"
            if candidate.exists():
                logger.debug(f"Banner '{banner_name}' found at '{candidate}'")
                return candidate, banner_format.content_type

    logger.error(f"Banner '{name}' not found in any location including global default")
    raise FileNotFoundError(f"Banner '{name}' or global default not found")


class Banner(StaticMedia):
    def __init__(self, name: BannerName) -> None:
        self.banner_name = name
        super().__init__(path="path", url=None, type=ContentType.UNKNOWN, when=self._is_use_banners)

    def _is_use_banners(
        self,
        data: dict[str, Any],
        widget: Whenable,
        dialog_manager: DialogManager,
    ) -> bool:
        config: AppConfig = dialog_manager.middleware_data[CONFIG_KEY]
        return config.bot.use_banners

    async def _render_media(self, data: dict, manager: DialogManager) -> Optional[MediaAttachment]:
        user: TelegramUserDto = manager.middleware_data[USER_KEY]
        config: AppConfig = manager.middleware_data[CONFIG_KEY]

        try:
            banner_path, banner_content_type = get_banner(
                banners_dir=config.banners_dir,
                default_banners_dir=config.default_banners_dir,
                name=self.banner_name,
                locale=user.language,
                default_locale=config.default_locale,
            )
        except FileNotFoundError:
            logger.critical(f"Failed to render banner '{self.banner_name}' because file is missing")
            return None

        return MediaAttachment(
            type=banner_content_type,
            path=banner_path,
            use_pipe=self.use_pipe,
            **self.media_params,
        )


class DataBanner(StaticMedia):
    """Banner whose file is chosen at render time from getter data.

    The getter may publish an ordered tuple of candidate names under
    ``BANNER_CANDIDATES_KEY`` (see plan_banner_candidates()); this widget resolves
    the first one that exists. With no candidates it falls back to the global
    default — same worst case as a static ``Banner`` — so it is a safe drop-in on
    any screen.
    """

    def __init__(self, data_key: str = BANNER_CANDIDATES_KEY) -> None:
        self.data_key = data_key
        super().__init__(path="path", url=None, type=ContentType.UNKNOWN, when=self._is_use_banners)

    def _is_use_banners(
        self,
        data: dict[str, Any],
        widget: Whenable,
        dialog_manager: DialogManager,
    ) -> bool:
        config: AppConfig = dialog_manager.middleware_data[CONFIG_KEY]
        return config.bot.use_banners

    async def _render_media(self, data: dict, manager: DialogManager) -> Optional[MediaAttachment]:
        candidates = data.get(self.data_key) or ()

        user: TelegramUserDto = manager.middleware_data[USER_KEY]
        config: AppConfig = manager.middleware_data[CONFIG_KEY]

        try:
            banner_path, banner_content_type = get_named_banner(
                banners_dir=config.banners_dir,
                default_banners_dir=config.default_banners_dir,
                names=tuple(candidates),
                locale=user.language,
                default_locale=config.default_locale,
            )
        except FileNotFoundError:
            logger.critical(f"Failed to render banner for candidates '{candidates}'")
            return None

        return MediaAttachment(
            type=banner_content_type,
            path=banner_path,
            use_pipe=self.use_pipe,
            **self.media_params,
        )
