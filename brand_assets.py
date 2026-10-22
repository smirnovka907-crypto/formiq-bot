"""FORMIQ welcome artwork — branded, generated in-house, no external image hosts.

This replaces the oversized legacy orange logo card. Render once per worker;
returned bytes are a compact JPEG usable both by Telegram and /mini/welcome-cover.jpg.
"""
from functools import lru_cache
from io import BytesIO
import math
import os

from PIL import Image, ImageDraw, ImageFilter, ImageFont


def _font(size: int, bold: bool = False):
    candidate = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold
        else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    )
    try:
        return ImageFont.truetype(candidate, size)
    except OSError:
        return ImageFont.load_default()


@lru_cache(maxsize=1)
def welcome_cover_jpeg() -> bytes:
    """1200×700 premium welcome banner, readable in Telegram's media bubble."""
    w, h = 1200, 700
    canvas = Image.new("RGB", (w, h), (8, 17, 34))
    draw = ImageDraw.Draw(canvas)

    # Restrained navy-to-indigo gradient with one blue ambient light.
    for y in range(h):
        t = y / h
        draw.line([(0, y), (w, y)], fill=(
            int(9 + 3 * t), int(21 + 10 * t), int(39 + 23 * t)
        ))
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    g = ImageDraw.Draw(glow)
    g.ellipse((650, -280, 1500, 650), fill=(26, 104, 255, 85))
    g.ellipse((900, 220, 1400, 780), fill=(18, 129, 240, 65))
    glow = glow.filter(ImageFilter.GaussianBlur(110))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), glow)
    d = ImageDraw.Draw(canvas, "RGBA")

    # Quiet precision lines: no glow around typography.
    for i in range(5):
        box = (690 + i * 54, 95 + i * 54, 1280 + i * 17, 690 + i * 17)
        d.arc(box, 190, 315, fill=(158, 200, 255, 32 + i * 5), width=2)
    d.ellipse((840, 160, 1240, 560), outline=(175, 216, 255, 60), width=3)
    d.ellipse((918, 238, 1162, 482), fill=(67, 145, 255, 20))
    d.ellipse((992, 312, 1088, 408), fill=(70, 154, 255, 110))

    # Proprietary geometric F mark in a 90 x 82 grid.
    d.rounded_rectangle((72, 67, 162, 153), radius=22, fill=(255, 255, 255, 12),
                        outline=(255, 255, 255, 38), width=2)
    d.polygon([(94, 91), (144, 91), (135, 104), (87, 104)], fill=(248, 250, 255, 255))
    d.polygon([(87, 110), (105, 110), (92, 136), (76, 136)], fill=(248, 250, 255, 255))
    d.polygon([(109, 112), (139, 112), (132, 124), (102, 124)], fill=(51, 137, 255, 255))

    navy_white = (246, 248, 255, 255)
    accent = (81, 155, 255, 255)
    d.text((188, 73), "FORMI", font=_font(49, True), fill=navy_white)
    w_brand = d.textbbox((188, 73), "FORMI", font=_font(49, True))[2]
    d.text((w_brand + 6, 73), "Q", font=_font(49, True), fill=accent)
    d.text((191, 137), "A I   C O A C H", font=_font(19), fill=(193, 206, 230, 255))

    d.rounded_rectangle((75, 260, 160, 266), radius=3, fill=accent)
    d.text((72, 294), "Твоя форма.", font=_font(62, True), fill=navy_white)
    d.text((72, 376), "Твой ритм.", font=_font(62, True), fill=navy_white)
    d.text((75, 495), "Тренировки · питание · прогресс", font=_font(25),
           fill=(191, 212, 242, 255))
    d.text((75, 620), "Начни с малого. Двигайся уверенно.", font=_font(21),
           fill=(157, 183, 216, 255))

    output = BytesIO()
    canvas.convert("RGB").save(output, "JPEG", quality=86, optimize=True, progressive=True)
    return output.getvalue()
