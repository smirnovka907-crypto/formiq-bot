"""Approved Telegram images; immutable PNG sources and JPG transport for Bot API.

Do not stylize, crop, or resize the owner's source avatar or welcome artwork.
"""
from functools import lru_cache
from io import BytesIO
from PIL import Image
from approved_assets import AVATAR_PNG, WELCOME_PNG


def _telegram_jpeg(original_png):
    # Telegram InputProfilePhotoStatic requires JPG. Original PNG is untouched.
    with Image.open(BytesIO(original_png)) as picture:
        with BytesIO() as output:
            picture.convert("RGB").save(
                output, format="JPEG", quality=96, subsampling=0, optimize=True)
            return output.getvalue()


@lru_cache(maxsize=1)
def welcome_jpeg():
    return _telegram_jpeg(WELCOME_PNG)


@lru_cache(maxsize=1)
def avatar_jpeg():
    return _telegram_jpeg(AVATAR_PNG)
