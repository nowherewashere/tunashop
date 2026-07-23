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

    # Hard caps on passwordless code requests within `code_rate_window_seconds`.
    # Per-IP is generous by default so shared/CGNAT clients aren't blocked
    # (captcha + per-email are the tighter gates). Tune via EMAIL_CODE_* env.
    code_max_per_email: int = 5
    code_max_per_ip: int = 60
    # Backstop across every caller: per-email caps protect one victim, but nothing
    # bounded a spray across many distinct addresses, which is what turns this
    # endpoint into a spam cannon (sender reputation, provider cost). Deliberately
    # generous — locking real users out of login is worse than a bounded burst — so
    # raise it via EMAIL_CODE_MAX_GLOBAL if legitimate volume ever approaches it.
    code_max_global: int = 1000
    code_rate_window_seconds: int = 3600
