from typing import Optional

from pydantic import BaseModel


class PublicConfigResponse(BaseModel):
    # Public Cloudflare Turnstile site key; null when the captcha is disabled.
    turnstile_site_key: Optional[str] = None
    # Chatwoot live-chat widget config; null when the website chat is disabled.
    chatwoot_base_url: Optional[str] = None
    chatwoot_website_token: Optional[str] = None
