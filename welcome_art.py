"""Telegram welcome artwork approved for FORMIQ.

The original approved art is embedded in approved_assets.py for reliability.
The same JPEG bytes are displayed in chat; no image hosting is required.
"""
from functools import lru_cache
from approved_assets import WELCOME_JPEG, AVATAR_JPEG


@lru_cache(maxsize=1)
def welcome_jpeg():
    return WELCOME_JPEG


@lru_cache(maxsize=1)
def avatar_jpeg():
    return AVATAR_JPEG
