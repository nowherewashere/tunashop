# ruff: noqa: E501 — inline styles are mandatory in email HTML (clients strip <style>),
# and breaking a style attribute across lines only makes it harder to audit.
"""Rendering for the transactional emails.

Written against the constraints of email clients, not browsers: table layout, inline
styles only (Gmail drops <style> in several contexts), `bgcolor` alongside CSS so the
Word engine behind Outlook still paints a background, no web fonts, no external assets.
Rounded corners and the like simply degrade to square where they are unsupported.

Every message is built as a pair — the plain-text part is not a courtesy, it is the
part that still works when a client blocks HTML, and for a login code that is the only
part that matters.
"""

from html import escape
from typing import Final, NamedTuple, Optional

# The dive palette, flattened to solid hex: email clients have no custom properties,
# and translucent fills over a dark page render unpredictably.
_BG: Final[str] = "#05101f"
_CARD: Final[str] = "#0b2138"
_BORDER: Final[str] = "#1e3a55"
_INK: Final[str] = "#eaf2fa"
_DIM: Final[str] = "#a8c2db"
_AMBER: Final[str] = "#f5a623"
_AMBER_INK: Final[str] = "#241703"

_SANS: Final[str] = "-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
_MONO: Final[str] = "'SFMono-Regular',Consolas,'Liberation Mono',Menlo,monospace"

LOGIN_CODE_SUBJECT: Final[str] = "Код для входа в Tuna"
EMAIL_VERIFY_SUBJECT: Final[str] = "Код для подтверждения почты в Tuna"


class RenderedEmail(NamedTuple):
    subject: str
    text: str
    html: str


def render_login_code_email(
    *,
    code: str,
    minutes: int,
    link_url: Optional[str] = None,
    site_url: str = "",
) -> RenderedEmail:
    """The passwordless sign-in email: a code to type, and optionally a one-tap link."""
    link_text = (
        f"\n\nИли просто открой эту ссылку — она откроет страницу, где нужно будет "
        f"подтвердить вход одним нажатием:\n{link_url}"
        if link_url
        else ""
    )
    text = (
        f"Код для входа в Tuna: {code}\n\n"
        f"Введи его на сайте. Код действует {minutes} минут и срабатывает один раз."
        f"{link_text}\n\n"
        "Если вход запрашивал не ты — просто удали это письмо, ничего не произойдёт."
    )
    return RenderedEmail(
        subject=LOGIN_CODE_SUBJECT,
        text=text,
        html=_login_code_html(code=code, minutes=minutes, link_url=link_url, site_url=site_url),
    )


def render_email_verification_email(
    *, code: str, minutes: int, site_url: str = ""
) -> RenderedEmail:
    """Confirming an address on an account that already exists. No one-tap link here:
    this code is the proof that the address belongs to the person adding it, so it must
    be typed back on the site rather than followed from the inbox."""
    text = (
        f"Код для подтверждения почты в Tuna: {code}\n\n"
        f"Введи его на сайте. Код действует {minutes} минут.\n\n"
        "Если ты не добавлял эту почту — просто удали это письмо."
    )
    return RenderedEmail(
        subject=EMAIL_VERIFY_SUBJECT,
        text=text,
        html=_code_email_html(
            kicker="почта",
            title="Подтверждение почты",
            lead=f"Введи код на сайте — он действует {minutes} минут.",
            preheader=f"Код для подтверждения почты. Действует {minutes} минут.",
            code=code,
            footer=(
                "Если ты не добавлял эту почту — просто удали это письмо. "
                "Без кода ничего не произойдёт."
            ),
            link_url=None,
            site_url=site_url,
        ),
    )


def _login_code_html(*, code: str, minutes: int, link_url: Optional[str], site_url: str) -> str:
    return _code_email_html(
        kicker="вход",
        title="Код для входа",
        lead=f"Введи его на сайте — код действует {minutes} минут и срабатывает один раз.",
        # Deliberately not in the subject or the preheader: both surface on a lock
        # screen, and a sign-in code has no business being readable from a locked phone.
        preheader=f"Подтверди вход в Tuna. Код действует {minutes} минут.",
        code=code,
        footer=(
            "Если вход запрашивал не ты — просто удали это письмо. "
            "Без кода и ссылки ничего не произойдёт."
        ),
        link_url=link_url,
        site_url=site_url,
    )


def _code_email_html(
    *,
    kicker: str,
    title: str,
    lead: str,
    preheader: str,
    code: str,
    footer: str,
    link_url: Optional[str],
    site_url: str,
) -> str:
    host = escape(site_url.replace("https://", "").replace("http://", "").rstrip("/"))

    button = ""
    if link_url:
        safe_link = escape(link_url, quote=True)
        button = f"""
            <tr><td style="padding:0 32px 8px;">
              <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
                <tr><td align="center" bgcolor="{_AMBER}" style="background:{_AMBER};border-radius:12px;">
                  <a href="{safe_link}" style="display:block;padding:14px 24px;font-family:{_SANS};font-size:16px;font-weight:600;color:{_AMBER_INK};text-decoration:none;">Войти одним нажатием</a>
                </td></tr>
              </table>
            </td></tr>
            <tr><td style="padding:12px 32px 0;font-family:{_SANS};font-size:13px;line-height:1.5;color:{_DIM};">
              Ссылка откроет страницу, где вход нужно подтвердить — так письмо не сможет
              «войти» само, если его откроет почтовый сканер.
            </td></tr>"""

    return f"""<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark light">
<meta name="supported-color-schemes" content="dark light">
<title>{escape(title)}</title>
</head>
<body style="margin:0;padding:0;background:{_BG};">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{escape(preheader)}</div>
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%" bgcolor="{_BG}" style="background:{_BG};">
  <tr><td align="center" style="padding:32px 16px;">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="520" style="width:520px;max-width:100%;">

      <tr><td style="padding:0 0 16px;font-family:{_MONO};font-size:12px;letter-spacing:.08em;color:{_DIM};">
        // tuna &middot; {escape(kicker)}
      </td></tr>

      <tr><td bgcolor="{_CARD}" style="background:{_CARD};border:1px solid {_BORDER};border-radius:14px;">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">

          <tr><td style="padding:32px 32px 8px;font-family:{_SANS};font-size:22px;font-weight:700;color:{_INK};">
            {escape(title)}
          </td></tr>
          <tr><td style="padding:0 32px 24px;font-family:{_SANS};font-size:15px;line-height:1.5;color:{_DIM};">
            {escape(lead)}
          </td></tr>

          <tr><td style="padding:0 32px 24px;">
            <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
              <tr><td align="center" bgcolor="{_BG}" style="background:{_BG};border:1px solid {_BORDER};border-radius:12px;padding:18px 12px;font-family:{_MONO};font-size:32px;font-weight:700;letter-spacing:.28em;color:{_AMBER};">
                {escape(code)}
              </td></tr>
            </table>
          </td></tr>
{button}
          <tr><td style="padding:28px 32px 32px;font-family:{_SANS};font-size:13px;line-height:1.5;color:{_DIM};">
            {escape(footer)}
          </td></tr>
        </table>
      </td></tr>

      <tr><td style="padding:16px 4px 0;font-family:{_SANS};font-size:12px;color:{_DIM};">
        Tuna VPN{f" &middot; {host}" if host else ""}
      </td></tr>
    </table>
  </td></tr>
</table>
</body>
</html>"""
