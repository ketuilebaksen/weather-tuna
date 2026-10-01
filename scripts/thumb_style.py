#!/usr/bin/env python3
"""
thumb_style.py — "BIG TYPE" thumbnail: giant word BEHIND the player.

The look the owner picked: a blurred arena plate, one enormous gold word set
across the frame, a small white kicker word above it, and the real player cut
out and composited IN FRONT of the type so he breaks the letters. Optional
secondary subject, smaller and further back, on the opposite side.

Everything that must be readable (the words) is drawn by us, so spelling and
kerning are always right; only the background plate comes from the image model.

Library:
  from thumb_style import bigtype
  bigtype(word="FROM NOWHERE", photo=..., bg=..., out=...)
"""
import os, sys

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
A = os.path.join(BASE, "assets")
W, H = 3840, 2160

GOLD = (247, 181, 22)
WHITE = (255, 255, 255)
INK = (10, 12, 18)
try:
    import channel as CH
    GOLD = tuple(CH.get("palette", {}).get("hero", GOLD))
except Exception:
    pass


def _f(name, size):
    return ImageFont.truetype(os.path.join(A, name), size)


# ------------------------------------------------------------------ the plate
def _synth_arena(seed=7):
    """Offline fallback plate: dark arena with out-of-focus crowd lights."""
    import random
    rnd = random.Random(seed)
    img = Image.new("RGB", (W, H), (9, 12, 22))
    d = ImageDraw.Draw(img, "RGBA")
    for y in range(H):                                   # floor-to-roof gradient
        f = y / H
        d.line([(0, y), (W, y)],
               fill=(int(9 + 26 * f), int(12 + 24 * f), int(22 + 40 * f)))
    for _ in range(240):                                 # crowd bokeh
        x, y = rnd.randint(0, W), rnd.randint(int(H * 0.05), int(H * 0.72))
        r = rnd.randint(14, 62)
        warm = rnd.random() < 0.55
        col = ((255, 176, 70, rnd.randint(30, 90)) if warm
               else (90, 150, 255, rnd.randint(24, 70)))
        d.ellipse([x - r, y - r, x + r, y + r], fill=col)
    for x0, col in ((-500, (255, 168, 60, 26)), (1500, (70, 130, 255, 22)),
                    (3000, (255, 150, 40, 24))):         # light beams
        d.polygon([(x0, H), (x0 + 520, H), (x0 + 520 + H, 0), (x0 + H, 0)],
                  fill=col)
    d.rectangle([0, int(H * 0.72), W, H], fill=(58, 34, 14, 130))   # court
    return img.filter(ImageFilter.GaussianBlur(26))


def plate(bg_path=None, blur=None):
    """Arena background: darkened, defocused, slight cool grade."""
    img = None
    if bg_path and os.path.exists(bg_path):
        img = Image.open(bg_path).convert("RGB")
    if img is None:
        img = _synth_arena()

    tw, th = img.size
    t = 16 / 9
    if abs(tw / th - t) > 0.01:                      # centre-crop to 16:9
        if tw / th > t:
            nw = int(th * t)
            img = img.crop(((tw - nw) // 2, 0, (tw - nw) // 2 + nw, th))
        else:
            nh = int(tw / t)
            img = img.crop((0, (th - nh) // 2, tw, (th - nh) // 2 + nh))
    img = img.resize((W, H), Image.LANCZOS)
    img = img.filter(ImageFilter.GaussianBlur(
        float(os.environ.get("BG_BLUR", blur if blur is not None else 14))))
    img = ImageEnhance.Brightness(img).enhance(0.62)
    img = ImageEnhance.Color(img).enhance(0.85)

    # darken the edges so the type and the player pop
    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse([-W // 5, -H // 5, W + W // 5, H + H // 5], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(360))
    img = Image.composite(img, Image.new("RGB", (W, H), (0, 0, 0)),
                          vig.point(lambda v: 70 + v * 185 // 255))
    return img.convert("RGBA")


# ------------------------------------------------------------------- the words
def split_word(word):
    """'FROM NOWHERE' -> ('FROM', 'NOWHERE'). The longest word becomes the hero."""
    parts = [p for p in (word or "").upper().split() if p]
    if not parts:
        return "", ""
    if len(parts) == 1:
        return "", parts[0]
    hero_i = max(range(len(parts)), key=lambda i: (len(parts[i]), i))
    if hero_i == 0:                       # hero first -> keep the rest as kicker
        return " ".join(parts[1:]), parts[0]
    return " ".join(parts[:hero_i]), " ".join(parts[hero_i:])


def _fit(d, text, font_name, maxw, start, floor=120):
    size = start
    while size > floor:
        fnt = _f(font_name, size)
        if d.textlength(text, font=fnt) <= maxw:
            return fnt
        size -= 10
    return _f(font_name, floor)


def draw_type(img, kicker, hero, y_hero=None):
    """Giant gold hero word + small white kicker above it. Drawn on the plate,
    so the player composited afterwards stands in front of the letters."""
    d = ImageDraw.Draw(img)
    hero = (hero or "").upper()
    if not hero:
        return
    fnt = _fit(d, hero, "Anton-Regular.ttf", int(W * 0.975), int(H * 0.86), 200)
    tw = d.textlength(hero, font=fnt)
    x = int((W - tw) / 2)
    # sit the type behind the torso: the player's head stays clear above it
    y = int(y_hero if y_hero is not None else H * 0.30 - fnt.size * 0.30)

    # soft black bed so gold letters read against a bright crowd
    bed = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(bed).text((x, y), hero, font=fnt, fill=(0, 0, 0, 190),
                             stroke_width=26, stroke_fill=(0, 0, 0, 190))
    img.alpha_composite(bed.filter(ImageFilter.GaussianBlur(40)))
    ImageDraw.Draw(img).text((x + 14, y + 20), hero, font=fnt, fill=(0, 0, 0, 150))
    ImageDraw.Draw(img).text((x, y), hero, font=fnt, fill=GOLD)

    if kicker:
        kf = _fit(d, kicker, "ArchivoBlack.ttf", int(W * 0.34), int(H * 0.11), 90)
        kx, ky = int(W * 0.028), max(10, y - int(kf.size * 1.18))
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((kx + 8, ky + 12), kicker, font=kf,
                                fill=(0, 0, 0, 210))
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(12)))
        ImageDraw.Draw(img).text((kx, ky), kicker, font=kf, fill=WHITE)


# ------------------------------------------------------------------ the people
def body_crop(cut, keep=0.80):
    """Trim a full-body cutout to head-to-thigh so the subject reads big."""
    h = int(cut.height * keep)
    box = cut.crop((0, 0, cut.width, h))
    bb = box.getbbox()
    return box.crop(bb) if bb else box


def place(canvas, cut, cx, bottom, height, dim=1.0, shadow=True):
    from thumbnail import _upscale, retouch
    if height > cut.height * 1.6:
        cut = _upscale(cut, height / cut.height)
    ratio = height / cut.height
    p = cut.resize((max(1, int(cut.width * ratio)), height), Image.LANCZOS)
    p = retouch(p)
    if dim < 1.0:
        p = ImageEnhance.Brightness(p).enhance(dim)
    x, y = int(cx - p.width / 2), int(bottom - p.height)
    alpha = p.split()[3]
    if shadow:
        sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
        sh.paste(Image.new("RGBA", p.size, (0, 0, 0, 200)), (x + 30, y + 30), alpha)
        canvas.alpha_composite(sh.filter(ImageFilter.GaussianBlur(52)))
    canvas.alpha_composite(p.convert("RGBA"), (x, y))


# --------------------------------------------------------------------- compose
def bigtype(word, photo=None, photo2=None, bg=None, out=None, cutouts=None):
    from thumbnail import cutout
    img = plate(bg)
    kicker, hero = split_word(word)

    cuts = cutouts or []
    if not cuts:
        for p in (photo, photo2):
            if p and os.path.exists(p):
                try:
                    cuts.append(cutout(p))
                except Exception as e:
                    print(f"[bigtype] cutout failed {p}: {e}")

    draw_type(img, kicker, hero)

    if len(cuts) > 1:                       # secondary subject, further back
        place(img, body_crop(cuts[1], 0.86), W * 0.878, int(H * 0.985),
              int(H * 0.60), dim=0.70)
    if cuts:                                # hero subject, in front of the type
        place(img, body_crop(cuts[0], 0.86), W * 0.44, int(H * 1.005),
              int(H * 0.99))
    else:
        print("[bigtype] WARNING: no player cutout")

    # final floor shadow so nobody floats
    floor = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(floor).rectangle([0, int(H * 0.93), W, H], fill=(0, 0, 0, 150))
    img.alpha_composite(floor.filter(ImageFilter.GaussianBlur(90)))

    out = out or os.path.join(BASE, "work", "thumbnail.jpg")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    final = img.convert("RGB")
    final = ImageEnhance.Contrast(final).enhance(1.04)
    final.save(out, quality=95, subsampling=0)
    final.resize((1280, 720), Image.LANCZOS).save(
        out.replace(".jpg", "_yt.jpg"), quality=92)
    print(f"[bigtype] {os.path.basename(out)} | kicker={kicker!r} hero={hero!r} "
          f"people={len(cuts)}")
    return out


if __name__ == "__main__":
    bigtype(sys.argv[1] if len(sys.argv) > 1 else "FROM NOWHERE",
            photo=sys.argv[2] if len(sys.argv) > 2 else None,
            photo2=sys.argv[3] if len(sys.argv) > 3 else None,
            out=os.path.join(BASE, "work", "style_demo.jpg"))
