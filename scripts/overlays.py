#!/usr/bin/env python3
"""
overlays.py — pre-rendered PNG overlay bubbles for Vox-style pop-ups.

Kinds:
  speech  — white rounded speech bubble with tail, navy text
  chat    — messenger-style blue chat chip, white text
  comic   — yellow comic-book starburst with black punch word
  lower3  — balloon/box lower-third (orange box + navy bar, white text)

Each maker writes an RGBA PNG and returns (width, height).
"""
import math, os

from PIL import Image, ImageDraw, ImageFilter, ImageFont

A = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
NAVY = (10, 16, 38, 255)
ORANGE = (245, 132, 38, 255)
BLUE = (0, 122, 255, 255)
WHITE = (255, 255, 255, 255)
YELLOW = (255, 213, 38, 255)

def _font(name, size):
    return ImageFont.truetype(os.path.join(A, name), size)

def _wrap(d, text, fnt, maxw):
    words, lines, cur = str(text).split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if d.textlength(t, font=fnt) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines[:3]

def _shadowed(img, blur=10, dx=6, dy=10, opacity=110):
    sh = Image.new("RGBA", (img.width + 60, img.height + 60), (0, 0, 0, 0))
    alpha = img.split()[3].point(lambda v: opacity if v > 30 else 0)
    black = Image.new("RGBA", img.size, (0, 0, 0, 255))
    sh.paste(black, (30 + dx, 30 + dy), alpha)
    sh = sh.filter(ImageFilter.GaussianBlur(blur))
    sh.paste(img, (30, 30), img)
    return sh

def speech_bubble(text, out, chat=False):
    fnt = _font("Inter-Var.ttf", 46)
    try:
        fnt.set_variation_by_axes([28, 700])
    except Exception:
        pass
    tmp = Image.new("RGBA", (10, 10))
    dt = ImageDraw.Draw(tmp)
    lines = _wrap(dt, text, fnt, 640)
    tw = max(dt.textlength(l, font=fnt) for l in lines)
    w, h = int(tw) + 90, len(lines) * 62 + 66
    img = Image.new("RGBA", (w, h + 46), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fill = BLUE if chat else WHITE
    txt_col = WHITE if chat else NAVY
    d.rounded_rectangle([0, 0, w - 1, h], radius=34, fill=fill,
                        outline=NAVY if not chat else None, width=5)
    # tail
    tx = 90 if not chat else w - 130
    d.polygon([(tx, h - 4), (tx + 52, h - 4), (tx + 10, h + 42)], fill=fill)
    y = 30
    for l in lines:
        d.text((45, y), l, font=fnt, fill=txt_col)
        y += 62
    _shadowed(img).save(out)
    return Image.open(out).size

def comic_burst(word, out):
    fnt = _font("Anton-Regular.ttf", 92)
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    tw = tmp.textlength(word, font=fnt)
    R = int(max(tw / 2 + 90, 190))
    size = R * 2 + 40
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    cx = cy = size // 2
    pts = []
    spikes = 16
    for k in range(spikes * 2):
        r = R if k % 2 == 0 else int(R * 0.72)
        a = math.pi * k / spikes
        pts.append((cx + r * math.cos(a), cy + r * 0.82 * math.sin(a)))
    d.polygon(pts, fill=YELLOW, outline=(0, 0, 0, 255))
    d.line(pts + [pts[0]], fill=(0, 0, 0, 255), width=8)
    d.text((cx - tw / 2, cy - 60), word, font=fnt, fill=(12, 12, 12, 255))
    rot = img.rotate(-5, expand=True, resample=Image.BICUBIC)
    _shadowed(rot, blur=12).save(out)
    return Image.open(out).size

def lower_third(title, sub, out):
    fnt = _font("Anton-Regular.ttf", 62)
    fnt2 = _font("Oswald-Var.ttf", 38)
    tmp = ImageDraw.Draw(Image.new("RGBA", (10, 10)))
    tw = max(tmp.textlength(str(title).upper(), font=fnt),
             tmp.textlength(str(sub).upper(), font=fnt2) if sub else 0)
    w = int(tw) + 150
    h = 168 if sub else 118
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([26, 0, w - 1, h - 1], radius=22, fill=ORANGE)
    d.rounded_rectangle([0, 0, 44, h - 1], radius=18, fill=NAVY)
    d.text((70, 16), str(title).upper(), font=fnt, fill=WHITE,
           stroke_width=2, stroke_fill=(60, 25, 0, 255))
    if sub:
        d.text((72, 104), str(sub).upper(), font=fnt2, fill=(28, 18, 8, 255))
    _shadowed(img, blur=8, dy=8).save(out)
    return Image.open(out).size
