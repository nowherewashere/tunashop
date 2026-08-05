from httpx import Cookies
from pydantic import SecretStr, field_validator
from pydantic_core.core_schema import FieldValidationInfo

from src.core.utils.validators import is_valid_domain

from .base import BaseConfig
from .validators import validate_not_change_me


class RemnawaveConfig(BaseConfig, env_prefix="REMNAWAVE_"):
    host: SecretStr = SecretStr("http://remnawave:3000")
    token: SecretStr
    caddy_token: SecretStr = SecretStr("")
    cf_client_id: SecretStr = SecretStr("")
    cf_client_secret: SecretStr = SecretStr("")
    webhook_secret: SecretStr
    cookie: SecretStr = SecretStr("")

    @property
    def is_external(self) -> bool:
        return self.url.get_secret_value().startswith("https://")

    @property
    def url(self) -> SecretStr:
        clean_host = self.host.get_secret_value().strip().rstrip("/")

        if "://" in clean_host:
            final_url = clean_host
        elif is_valid_domain(clean_host):
            final_url = f"https://{clean_host}"
        else:
            final_url = f"http://{clean_host}"

        host_part = final_url.split("://")[-1]
        if ":" not in host_part and final_url.startswith("http://"):
            final_url = f"{final_url}:3000"

        return SecretStr(final_url)

    @property
    def client_headers(self) -> dict[str, str]:
        """Every header a request to the panel needs, for any client that talks to it.

        The x-forwarded-* pair is not decoration. An internal (http://) panel drops a
        request that arrives without it, and httpx reports that as
        RemoteProtocolError("Server disconnected without sending a response") -- no
        status code, nothing that reads like an auth or routing problem. Anything
        rebuilding this header set by hand gets a panel that looks unreachable.
        """
        headers = {
            "Authorization": f"Bearer {self.token.get_secret_value()}",
            "X-Api-Key": self.caddy_token.get_secret_value(),
            "CF-Access-Client-Id": self.cf_client_id.get_secret_value(),
            "CF-Access-Client-Secret": self.cf_client_secret.get_secret_value(),
        }

        if not self.is_external:
            headers["x-forwarded-proto"] = "https"
            headers["x-forwarded-for"] = "127.0.0.1"

        return headers

    @property
    def cookies(self) -> Cookies:
        raw_cookie = self.cookie.get_secret_value()
        cookies = Cookies()

        if raw_cookie and "=" in raw_cookie:
            key, value = raw_cookie.split("=", 1)
            cookies.set(key.strip(), value.strip())

        return cookies

    @field_validator("token")
    @classmethod
    def validate_remnawave_token(cls, field: SecretStr, info: FieldValidationInfo) -> SecretStr:
        validate_not_change_me(field, info)
        return field

    @field_validator("webhook_secret")
    @classmethod
    def validate_remnawave_webhook_secret(
        cls,
        field: SecretStr,
        info: FieldValidationInfo,
    ) -> SecretStr:
        validate_not_change_me(field, info)
        return field

    @field_validator("cookie")
    @classmethod
    def validate_cookie(cls, field: SecretStr) -> SecretStr:
        cookie = field.get_secret_value()

        if not cookie:
            return field

        cookie = cookie.strip()

        if "=" not in cookie or cookie.startswith("=") or cookie.endswith("="):
            raise ValueError("REMNAWAVE_COOKIE must be in 'key=value' format")

        return field
