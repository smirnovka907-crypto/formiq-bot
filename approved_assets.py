"""Exact owner-approved Telegram artwork sources.

The original avatar PNG is kept byte-identical. Telegram's official
InputProfilePhotoStatic requires JPG, created only in memory from this source.
Only the welcome slogan was changed in the second PNG, before this commit.
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parent / "assets"
AVATAR_PNG = (_ROOT / "telegram_avatar_owner_approved_original.png").read_bytes()
WELCOME_PNG = (_ROOT / "telegram_welcome_owner_approved_slogan.png").read_bytes()
