from typing import Optional

from pydantic import BaseModel


class PublicConfigResponse(BaseModel):
    # Public Cloudflare Turnstile site key; null when the captcha is disabled.
    turnstile_site_key: Optional[str] = None
