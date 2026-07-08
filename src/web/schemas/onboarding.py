from typing import Optional

from pydantic import BaseModel


class OnboardingStoreLinks(BaseModel):
    ios: str
    android: str
    windows: str
    mac: str
    linux: str


class OnboardingTvFaq(BaseModel):
    apple_tv: str
    android_tv: str


class OnboardingTvConfig(BaseModel):
    web_import_url: str
    faq: OnboardingTvFaq


class OnboardingConfigResponse(BaseModel):
    """Canonical Happ install data (single source: OnboardingConfig, shared with the bot)."""

    happ_import_template: str
    refresh_video_url: Optional[str] = None
    store_links: OnboardingStoreLinks
    store_link_ios_ru: str
    tv: OnboardingTvConfig
