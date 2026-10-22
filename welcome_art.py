"""FORMIQ chat welcome artwork, generated locally with Pillow.

No remote image hosts, no user data, and no image updates to profile history.
The previous orange graphic is deliberately not used.
"""
from functools import lru_cache
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont


def _font(size, bold=False):
    family = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(family, size)
    except OSError:
        return ImageFont.load_default()


@lru_cache(maxsize=1)
def welcome_jpeg():
    """Landscape welcome card, less than Telegram's 10 MB sendPhoto limit."""
    width, height = 1200, 675
    image = Image.new("RGB", (width, height), "#060e21")
    draw = ImageDraw.Draw(image)
    # Quiet navy/blue gradient, with blue glow only in the edges.
    for y in range(height):
        t = y / max(1, height - 1)
        draw.line((0, y, width, y), fill=(int(5+3*t), int(13+13*t), int(30+25*t)))
    for layer in range(18, 0, -1):
        opacity = (19-layer) / 18
        color = (int(5+9*opacity), int(20+33*opacity), int(51+93*opacity))
        draw.arc((-640-layer*7, 450-layer*4, 790+layer*6, 1590+layer*7),
                 185, 310, fill=color, width=2+layer//5)
        draw.arc((760-layer*7, -680-layer*6, 1920+layer*8, 280+layer*6),
                 65, 175, fill=color, width=2+layer//5)
    # Simple horizontal monogram inspired by moving air, distinct from old orange mark.
    draw.rounded_rectangle((493, 122, 714, 141), 9, fill="#1d87ff")
    draw.polygon([(472, 153), (734, 153), (692, 209), (451, 209)],
                 fill="#f8fbff")
    draw.polygon([(451, 215), (549, 215), (488, 329), (399, 329)],
                 fill="#ecf7ff")
    draw.polygon([(536, 215), (677, 215), (638, 265), (508, 265)],
                 fill="#319cfa")
    draw.polygon([(508, 265), (638, 265), (620, 285), (497, 285)],
                 fill="#1466ed")
    # Primary type.
    brand = "FORMI"
    accent = "Q"
    primary = _font(108, True)
    left_bound = draw.textbbox((0, 0), brand+accent, font=primary)
    start_x = (width - (left_bound[2]-left_bound[0])) // 2
    draw.text((start_x, 340), brand, font=primary, fill="#fafcff")
    first_width = draw.textbbox((0,0),brand,font=primary)[2]
    draw.text((start_x+first_width, 340), accent, font=primary, fill="#399cff")
    # Compact byline and clear human-centered message.
    sub = _font(29)
    subtitle = "A I   C O A C H"
    box = draw.textbbox((0,0),subtitle,font=sub)
    draw.text(((width-box[2])/2, 465), subtitle, font=sub, fill="#cbd9f0")
    draw.rounded_rectangle((559, 532, 640, 537), 3, fill="#238cfe")
    tagline = "Твой ритм. Твой прогресс."
    end_font = _font(37)
    box = draw.textbbox((0,0),tagline,font=end_font)
    draw.text(((width-box[2])/2, 574), tagline, font=end_font, fill="#e9f1ff")
    result = BytesIO()
    image.save(result, format="JPEG", quality=85, optimize=True, subsampling=0)
    return result.getvalue()
