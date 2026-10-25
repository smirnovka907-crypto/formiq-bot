"""Owner-approved original PNG assets for the single FORMIQ Telegram bot.

Source images are stored unmodified in assets/telegram. The Telegram static
avatar upload requires JPEG; generate only that transport representation.
The welcome PNG is sent without any local compression or artwork changes.
"""
from io import BytesIO
from pathlib import Path
from PIL import Image

_ASSETS = Path(__file__).resolve().parent / "assets" / "telegram"
AVATAR_PNG = (_ASSETS / "formiq_avatar_approved_20261026.png").read_bytes()
WELCOME_PNG = (_ASSETS / "formiq_welcome_approved_20261026.png").read_bytes()

def _avatar_transport_jpeg():
    with Image.open(BytesIO(AVATAR_PNG)) as original:
        out = BytesIO()
        original.convert("RGB").save(out, format="JPEG", quality=96, subsampling=0)
        return out.getvalue()

AVATAR_JPEG = _avatar_transport_jpeg()
# Backward-compatible name consumed by welcome_art: now retains original PNG bytes.
WELCOME_JPEG = WELCOME_PNG
