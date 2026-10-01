#!/usr/bin/env python3
"""
collage.py — magazine cut-out text cards.

The look is a torn strip of newsprint dropped on the picture: off-white paper,
a hard black condensed word on it, the strip sitting at a slight angle with a
shadow under it. One strip is printed in the channel colour instead, so the
group reads as a deliberate composition rather than a caption.

Everything here draws to a transparent PNG. The animation (the snap-in) is
done by ffmpeg at overlay time, because moving a finished card is far cheaper
than redrawing it per frame.

Why torn edges matter: a clean rectangle reads as a lower-third, which is the
television look we are trying to get away from. The irregular edge is what
makes the eye read "cut out of something" instead of "graphic overlay".
"""
import os
import random

from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
PAPER = (244, 241, 234, 255)
INKBLACK = (17, 17, 19, 255)


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except Exception:
        return ImageFont.load_default()


def _torn(draw_size, rng, bite=7):
    """A paper-edge mask: a rectangle whose border wobbles like a tear."""
    w, h = draw_size
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    step = 26
    pts = []
    for x in range(0, w + step, step):                      # top edge
        pts.append((min(x, w), rng.randint(0, bite)))
    for y in range(0, h + step, step):                      # right edge
        pts.append((w - rng.randint(0, bite), min(y, h)))
    for x in range(w, -step, -step):                        # bottom edge
        pts.append((max(x, 0), h - rng.randint(0, bite)))
    for y in range(h, -step, -step):                        # left edge
        pts.append((rng.randint(0, bite), max(y, 0)))
    d.polygon(pts, fill=255)
    return m


def _strip(text, font_path, size, fill, text_col, rng, pad=(34, 18)):
    """One cut-out strip, already torn and rotated."""
    f = _font(font_path, size)
    tmp = ImageDraw.Draw(Image.new("RGB", (8, 8)))
    box = tmp.textbbox((0, 0), text, font=f)
    tw, th = box[2] - box[0], box[3] - box[1]
    w = tw + pad[0] * 2
    h = th + pad[1] * 2 + int(size * 0.30)

    card = Image.new("RGBA", (w, h), fill)
    ImageDraw.Draw(card).text((pad[0] - box[0], pad[1] - box[1]),
                              text, font=f, fill=text_col)
    card.putalpha(_torn((w, h), rng))

    # a shadow that is offset and blurred, so the strip sits ON the picture
    shadow = Image.new("RGBA", (w + 40, h + 40), (0, 0, 0, 0))
    sh = Image.new("RGBA", (w, h), (0, 0, 0, 150))
    sh.putalpha(Image.eval(card.getchannel("A"), lambda a: int(a * 0.58)))
    shadow.paste(sh, (26, 24), sh)
    shadow = shadow.filter(ImageFilter.GaussianBlur(9))
    shadow.paste(card, (14, 12), card)

    return shadow.rotate(rng.uniform(-7.5, 7.5), resample=Image.BICUBIC,
                         expand=True)


def card(lines, out_png, font_path, accent=(245, 132, 38), seed=0,
         side=None):
    """Draw up to three strips onto a transparent 1920x1080 frame.

    `lines` is whatever words should appear — the first is the loudest.
    `side` is "left" or "right"; leaving it None picks one from the seed, which
    keeps consecutive cards from stacking in the same corner.
    """
    lines = [str(t).strip().upper() for t in lines if str(t).strip()][:3]
    if not lines:
        raise ValueError("collage card with no text")

    rng = random.Random(seed * 7919 + len(lines))
    if side is None:
        side = "left" if seed % 2 == 0 else "right"

    frame = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sizes = [128, 82, 62]
    # the accent strip is never the first line: the eye should land on the
    # word, then travel to the colour
    accent_at = 1 if len(lines) > 1 else 0

    y = int(H * 0.30) + rng.randint(-40, 40)
    for i, text in enumerate(lines):
        if i == accent_at:
            strip = _strip(text, font_path, sizes[i],
                           tuple(accent) + (255,), (255, 255, 255, 255), rng)
        else:
            strip = _strip(text, font_path, sizes[i], PAPER, INKBLACK, rng)

        if side == "left":
            x = int(W * 0.07) + rng.randint(-18, 46) + i * rng.randint(20, 70)
        else:
            x = W - strip.width - int(W * 0.07) - rng.randint(-18, 46) \
                - i * rng.randint(20, 70)
        x = max(24, min(W - strip.width - 24, x))
        yy = max(20, min(H - strip.height - 20, y))
        frame.alpha_composite(strip, (x, yy))
        y = yy + strip.height - rng.randint(14, 34)

    frame.save(out_png)
    return out_png


def overlay_filter(dur, hold=None, snap=0.22):
    """The ffmpeg bits that snap the finished card onto a segment.

    Two channels of motion, both short: opacity comes up over `snap` seconds
    while the card slides the last few pixels into place. That reads as a
    physical drop. A slow fade would read as television.
    """
    hold = dur if hold is None else min(hold, dur)
    return {
        "prep": (f"format=rgba,fade=t=in:st=0:d={snap:.2f}:alpha=1,"
                 f"fade=t=out:st={max(0.0, hold - 0.35):.2f}:d=0.35:alpha=1"),
        "xy": ("x=0:"
               f"y='if(lt(t,{snap:.2f}), -18+18*t/{snap:.2f}, 0)'"),
        "enable": f"enable='lt(t,{hold:.2f})'",
    }
