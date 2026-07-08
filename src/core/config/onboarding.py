from typing import Final

from .base import BaseConfig

# Default Happ client download links per platform.
# App Store entry serves both iOS and macOS; Android via Play; desktop via GitHub.
_DEFAULT_HAPP_IOS: Final[str] = "https://apps.apple.com/app/happ-proxy-utility/id6504287215"
_DEFAULT_HAPP_ANDROID: Final[str] = "https://play.google.com/store/apps/details?id=com.happproxy"
_DEFAULT_HAPP_WINDOWS: Final[str] = (
    "https://github.com/Happ-proxy/happ-desktop/releases/latest/download/setup-Happ.x64.exe"
)
_DEFAULT_HAPP_MAC: Final[str] = "https://apps.apple.com/app/happ-proxy-utility/id6504287215"
_DEFAULT_HAPP_LINUX: Final[str] = "https://github.com/happ-proxy"
# RU App Store has a separate Happ listing (the global one is geo-blocked there),
# so Apple devices get an extra "RU region" download button.
_DEFAULT_HAPP_IOS_RU: Final[str] = "https://apps.apple.com/ru/app/happ-proxy-utility/id6783623643"
# TV clients import the subscription via a web page (no custom-scheme deep link on
# TV), with per-platform setup FAQs.
_DEFAULT_TV_WEB_IMPORT: Final[str] = "https://tv.happ.su"
_DEFAULT_FAQ_APPLE_TV: Final[str] = "https://www.happ.su/main/faq/apple-tv-tvos"
_DEFAULT_FAQ_ANDROID_TV: Final[str] = "https://www.happ.su/main/faq/android-tv"


class OnboardingConfig(BaseConfig, env_prefix="ONBOARDING_"):
    """Config for the guided onboarding funnel.

    All values have safe defaults, so the feature is fully driven by env without
    requiring any variable to be set. The runtime on/off switch lives in the Extra
    settings (``settings.extra.onboarding_enabled``), not here.
    """

    happ_link_ios: str = _DEFAULT_HAPP_IOS
    happ_link_ios_ru: str = _DEFAULT_HAPP_IOS_RU
    happ_link_android: str = _DEFAULT_HAPP_ANDROID
    happ_link_windows: str = _DEFAULT_HAPP_WINDOWS
    happ_link_mac: str = _DEFAULT_HAPP_MAC
    happ_link_linux: str = _DEFAULT_HAPP_LINUX

    # TV setup: web-import page + per-platform FAQ (TV has no deep-link import).
    tv_web_import_url: str = _DEFAULT_TV_WEB_IMPORT
    happ_faq_apple_tv: str = _DEFAULT_FAQ_APPLE_TV
    happ_faq_android_tv: str = _DEFAULT_FAQ_ANDROID_TV

    # Optional "how to refresh in Happ" video (O3 tip). Hidden when empty.
    refresh_video_url: str = ""

    # Template that wraps the personal subscription URL into a one-tap Happ import
    # deeplink. Kept configurable so a different client scheme can be swapped in.
    happ_import_template: str = "happ://add/{sub_url}"

    # Pre-connect nudge schedule (hours after funnel start) and frequency cap.
    nudge_delays_hours: str = "0.5,3,24"
    nudge_min_gap_minutes: int = 180
    nudge_daily_cap: int = 4

    @property
    def nudge_delays(self) -> list[float]:
        delays: list[float] = []
        for chunk in self.nudge_delays_hours.split(","):
            chunk = chunk.strip()
            if not chunk:
                continue
            try:
                delays.append(float(chunk))
            except ValueError:
                continue
        return delays

    def store_link(self, platform: str) -> str:
        return {
            "ios": self.happ_link_ios,
            "android": self.happ_link_android,
            "windows": self.happ_link_windows,
            "mac": self.happ_link_mac,
            "linux": self.happ_link_linux,
        }.get(platform, self.happ_link_ios)

    def tv_faq_link(self, platform: str) -> str:
        return {
            "apple_tv": self.happ_faq_apple_tv,
            "android_tv": self.happ_faq_android_tv,
        }.get(platform, "")
