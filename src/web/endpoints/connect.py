import base64
import binascii
import re
from typing import Final

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse

from src.core.constants import API_V1

# Mounted under /api/v1 because the prod nginx only proxies that prefix to the
# app; a bare "/connect/..." route is unreachable from the internet (nginx 404).
router = APIRouter(prefix=API_V1)

# base64url alphabet (+ padding) — the only thing a valid payload contains.
_PAYLOAD_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_=-]{1,4096}$")
# A safe http(s) subscription URL (no chars that could break the HTML/JS embed).
_SUB_URL_RE: Final[re.Pattern[str]] = re.compile(r"^https?://[^\s\"'<>]{1,2048}$")

# Client apps whose subscription-import deep link this bouncer can target, keyed by
# the URL segment. An allowlist (not a free-form {app} → scheme) so the path can
# never inject an arbitrary custom scheme. Value: (deep-link prefix, display name).
# The prefix takes the FULL subscription URL, scheme included, e.g.
# happ://add/https://sub.tuna-transfer.xyz/<token> — stripping http(s):// makes the
# client open but fail to recognise the link.
_APPS: Final[dict[str, tuple[str, str]]] = {
    "happ": ("happ://add/", "Happ"),
    "incy": ("incy://add/", "INCY"),
}

_PAGE: Final[str] = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tuna — подключение</title>
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif;
         text-align: center; padding: 2.5rem 1.5rem; color: #e7e7e7; background: #17212b; }
  a.btn { display: inline-block; margin-top: 1rem; padding: 1rem 1.6rem;
          background: #2ea6ff; color: #fff; border-radius: 12px;
          text-decoration: none; font-weight: 600; font-size: 1.05rem; }
  p { line-height: 1.5; }
</style>
</head>
<body>
  <h2>🐟 Открываем __APP__…</h2>
  <p>Если приложение не открылось само — нажми кнопку ниже.</p>
  <p><a class="btn" id="open" href="__LINK__">➡️ Открыть в __APP__</a></p>
  <p style="opacity:.6;font-size:.9rem">__APP__ должен быть установлен. Если ничего не происходит —
  открой эту страницу во внешнем браузере (⋮ → «Открыть в браузере»).</p>
<script>
  // Custom-scheme navigation is often blocked without a user gesture (and inside
  // Telegram's in-app browser), so try automatically but also leave the button.
  try { window.location.href = "__LINK__"; } catch (e) {}
  document.getElementById("open").addEventListener("click", function () {
    window.location.href = "__LINK__";
  });
</script>
</body>
</html>"""


@router.get("/connect/{app}/{payload}", include_in_schema=False, response_class=HTMLResponse)
async def connect_app(app: str, payload: str) -> HTMLResponse:
    """Bounce an https tap to a client's ``<app>://add/<subscription_url>`` deep link.

    Lets the bot expose real inline "Open in <app>" buttons (Telegram forbids custom
    schemes in buttons, but allows https that then redirects). ``app`` is restricted
    to the ``_APPS`` allowlist (happ / incy).
    """
    entry = _APPS.get(app)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    prefix, name = entry

    if not _PAYLOAD_RE.match(payload):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    try:
        sub_url = base64.urlsafe_b64decode(payload).decode()
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if not _SUB_URL_RE.match(sub_url):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    deeplink = f"{prefix}{sub_url}"
    return HTMLResponse(_PAGE.replace("__LINK__", deeplink).replace("__APP__", name))
