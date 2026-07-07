from pydantic import SecretStr

from .base import BaseConfig


class EmailConfig(BaseConfig, env_prefix="EMAIL_"):
    enabled: bool = False

    # Dev/local only: log the message (incl. the code) instead of sending via SMTP,
    # so passwordless/verification flows work without an email provider.
    # NEVER enable in production — codes would be written to logs.
    console: bool = False

    host: str = ""
    port: int = 587
    use_tls: bool = True
    use_ssl: bool = False

    username: SecretStr = SecretStr("")
    password: SecretStr = SecretStr("")

    from_email: str = ""
    from_name: str = ""

    verification_code_ttl_minutes: int = 15
