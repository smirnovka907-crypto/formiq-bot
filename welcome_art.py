"""Telegram artwork: unchanged PNG source; JPEG only for Bot API avatar upload."""
from functools import lru_cache
from io import BytesIO
from PIL import Image
from approved_assets import WELCOME_PNG, AVATAR_PNG


@lru_cache(maxsize=1)
def welcome_png():
    return WELCOME_PNG


@lru_cache(maxsize=1)
def avatar_jpeg():
    with Image.open(BytesIO(AVATAR_PNG)) as source:
        output = BytesIO()
        source.convert('RGB').save(
            output, format='JPEG', quality=95, subsampling=0, optimize=True
        )
        return output.getvalue()
