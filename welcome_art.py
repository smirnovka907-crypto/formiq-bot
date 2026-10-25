"""Telegram-approved FORMIQ artwork from owner's exact PNG source files.

The owner-approved avatar is stored unmodified in assets/ as PNG.  Telegram
receives a high-quality JPEG encode because the existing Bot API profile-photo
upload uses image/jpeg.  No image hosting or external assets are needed.
"""
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PIL import Image

_ASSETS = Path(__file__).resolve().parent / 'assets'


def _as_jpeg(filename):
    with Image.open(_ASSETS / filename) as image:
        output = BytesIO()
        image.convert('RGB').save(
            output, format='JPEG', quality=95, subsampling=0, optimize=True
        )
        return output.getvalue()


@lru_cache(maxsize=1)
def welcome_jpeg():
    return _as_jpeg('telegram_welcome_owner_approved.png')


@lru_cache(maxsize=1)
def avatar_jpeg():
    return _as_jpeg('telegram_avatar_owner_approved.png')
