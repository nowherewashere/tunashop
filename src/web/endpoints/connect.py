import base64
import binascii
import re
from typing import Final

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import HTMLResponse

router = APIRouter()

# base64url alphabet (+ padding) — the only thing a valid Happ payload contains.
_PAYLOAD_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_=-]{1,4096}$")
# A safe http(s) subscription URL (no chars that could break the HTML/JS embed).
_SUB_URL_RE: Final[re.Pattern[str]] = re.compile(r"^https?://[^\s\"'<>]{1,2048}$")

_PAGE: Final[str] = """<!doctype html>
<html lang="ru">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tuna — подключение</title>
<script>window.location.replace("__LINK__");</script>
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif;
         text-align: center; padding: 2.5rem 1.5rem; color: #e7e7e7; background: #17212b; }
  a.btn { display: inline-block; margin-top: 1rem; padding: .9rem 1.4rem;
          background: #2ea6ff; color: #fff; border-radius: 12px;
          text-decoration: none; font-weight: 600; }
  p { line-height: 1.5; }
</style>
</head>
<body>
  <h2>🐟 Открываем Happ…</h2>
  <p>Если приложение не открылось автоматически — нажми кнопку ниже.</p>
  <p><a class="btn" href="__LINK__">➡️ Открыть в Happ</a></p>
  <p style="opacity:.6;font-size:.9rem">Happ должен быть установлен на устройстве.</p>
</body>
</html>"""


@router.get("/connect/happ/{payload}", include_in_schema=False, response_class=HTMLResponse)
async def connect_happ(payload: str) -> HTMLResponse:
    """Bounce an https tap to the ``happ://add/<subscription_url>`` deep link.

    Lets the bot expose a real inline "Open in Happ" button (Telegram forbids
    custom schemes in buttons, but allows https that then redirects).
    """
    if not _PAYLOAD_RE.match(payload):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    try:
        sub_url = base64.urlsafe_b64decode(payload).decode()
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if not _SUB_URL_RE.match(sub_url):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    deeplink = f"happ://add/{sub_url}"
    return HTMLResponse(_PAGE.replace("__LINK__", deeplink))
