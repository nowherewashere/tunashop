from pathlib import Path

import pytest

from src.core.enums import BannerName, Locale
from src.telegram.widgets.banner import get_banner


def make_banner(directory: Path, name: str, fmt: str = "jpg") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    f = directory / f"{name}.{fmt}"
    f.write_bytes(b"")
    return f


def test_user_banner_takes_priority(tmp_path):
    get_banner.cache_clear()
    user_dir = tmp_path / "user_banners"
    default_dir = tmp_path / "default_banners"
    make_banner(user_dir / "ru", "menu")
    make_banner(default_dir, "default")

    path, _ = get_banner(user_dir, default_dir, BannerName.MENU, Locale.RU, Locale.RU)
    assert "user_banners" in str(path)


def test_falls_back_to_default_assets_when_user_has_no_banner(tmp_path):
    get_banner.cache_clear()
    user_dir = tmp_path / "user_banners"
    default_dir = tmp_path / "default_banners"
    user_dir.mkdir()  # empty user dir
    make_banner(default_dir, "default")

    path, _ = get_banner(user_dir, default_dir, BannerName.MENU, Locale.RU, Locale.RU)
    assert "default_banners" in str(path)


def test_raises_when_no_banner_anywhere(tmp_path):
    get_banner.cache_clear()
    user_dir = tmp_path / "user_banners"
    default_dir = tmp_path / "default_banners"
    user_dir.mkdir()
    default_dir.mkdir()

    with pytest.raises(FileNotFoundError):
        get_banner(user_dir, default_dir, BannerName.MENU, Locale.RU, Locale.RU)


def test_falls_back_to_default_locale_in_default_banners(tmp_path):
    get_banner.cache_clear()
    user_dir = tmp_path / "user_banners"
    default_dir = tmp_path / "default_banners"
    user_dir.mkdir()  # no user banners
    # only RU banner in defaults, but user locale is EN
    make_banner(default_dir / "ru", "menu")

    path, _ = get_banner(user_dir, default_dir, BannerName.MENU, Locale.EN, Locale.RU)
    assert "default_banners" in str(path)
    assert "ru" in str(path)
