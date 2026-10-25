"""Exact owner-approved Telegram PNG artwork, stored without recompression."""
from pathlib import Path

_ART_DIR = Path(__file__).resolve().parent / 'assets'
AVATAR_PNG = (_ART_DIR / 'telegram_avatar_approved.png').read_bytes()
WELCOME_PNG = (_ART_DIR / 'telegram_welcome_approved.png').read_bytes()
