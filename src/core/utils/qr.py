import base64
from io import BytesIO
from pathlib import Path
from typing import Any, Optional, cast


def render_qr_png_base64(data: str, logo_path: Optional[Path] = None) -> str:
    """Render `data` as a base64-encoded PNG QR code.

    High error correction so the optional centre logo cannot make the code
    unreadable. Imports are deferred because Pillow and qrcode are only needed on the
    handful of paths that draw a code — keeping them out of the bot's import graph.
    """
    from PIL import Image  # noqa: PLC0415
    from qrcode import ERROR_CORRECT_H, QRCode  # type: ignore[attr-defined]  # noqa: PLC0415

    qr: Any = QRCode(version=1, error_correction=ERROR_CORRECT_H, box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)

    raw = qr.make_image(fill_color="black", back_color="white")
    image = cast(Image.Image, raw.get_image() if hasattr(raw, "get_image") else raw)
    image = image.convert("RGB")

    if logo_path is not None and logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA")
        width, _ = image.size
        size = int(width * 0.2)
        logo = logo.resize((size, size), resample=Image.Resampling.LANCZOS)
        image.paste(logo, ((width - size) // 2, (width - size) // 2), mask=logo)

    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")
