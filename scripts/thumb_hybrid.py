#!/usr/bin/env python3
"""
thumb_hybrid.py — METHOD A thumbnail: real player photo + AI background + our text.

Why this exists: an image model cannot draw a real NBA player's face, and it
misspells display text often enough to ruin a thumbnail. So we split the job:

  background  -> AI (thumb_ai.generate_backdrop): arena, light, mood, no people
  the player  -> the real photo, background removed, head-and-chest crop
  the word    -> drawn by us, so the spelling is always right

The player is the person most mentioned in today's script.

Library:
  from thumb_hybrid import build
  build(script, word, scene, out)
"""
import json, os, re, sys

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
A = os.path.join(BASE, "assets")
W, H = 3840, 2160

ORANGE = (245, 132, 38)
BLUE = (0, 122, 200)
WHITE = (255, 255, 255)
try:
    import channel as CH
    _p = CH.get("palette", {})
    ORANGE = tuple(_p.get("primary", ORANGE))
    BLUE = tuple(_p.get("secondary", BLUE))
except Exception:
    pass


# ------------------------------------------------------------- who is the star
def key_people(script, photo_dir=None, limit=2):
    """[(name, photo_path, mentions)] — the people today's script talks about
    most, best first. This is what decides who goes on the thumbnail."""
    photo_dir = photo_dir or os.path.join(BASE, "work", "photos")
    if not os.path.isdir(photo_dir):
        return []
    text = json.dumps(script).lower()
    rows = []
    for f in sorted(os.listdir(photo_dir)):
        if not f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        stem = os.path.splitext(f)[0].lower()
        if stem in ("new_york_knicks", "madison_square_garden"):
            continue
        last = stem.split("_")[-1]
        if len(last) < 4:
            continue
        n = len(re.findall(r"\b" + re.escape(last), text))
        if n:
            rows.append((n, os.path.join(photo_dir, f),
                         stem.replace("_", " ").title()))
    rows.sort(key=lambda r: -r[0])
    out = [(name, path, n) for n, path, name in rows[:limit]]
    if not out:                             # nobody named -> lead with the stars
        for star in ("brunson", "towns", "bridges", "anunoby", "hart"):
            for f in sorted(os.listdir(photo_dir)):
                if star in f.lower():
                    out.append((f.split(".")[0].replace("_", " ").title(),
                                os.path.join(photo_dir, f), 0))
                    break
            if len(out) >= limit:
                break
    return out[:limit]


def key_person(script, photo_dir=None):
    """(display_name, photo_path, mentions) for the most-talked-about person."""
    photo_dir = photo_dir or os.path.join(BASE, "work", "photos")
    if not os.path.isdir(photo_dir):
        return None, None, 0
    text = json.dumps(script).lower()
    best = (0, None, None)
    for f in sorted(os.listdir(photo_dir)):
        if not f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        stem = os.path.splitext(f)[0].lower()
        if stem in ("new_york_knicks", "madison_square_garden"):
            continue
        last = stem.split("_")[-1]
        if len(last) < 4:
            continue
        n = len(re.findall(r"\b" + re.escape(last), text))
        if n > best[0]:
            best = (n, os.path.join(photo_dir, f),
                    stem.replace("_", " ").title())
    if not best[1]:                        # nobody named -> fall back to a star
        for star in ("brunson", "towns", "bridges", "anunoby", "hart"):
            for f in sorted(os.listdir(photo_dir)):
                if star in f.lower():
                    return (f.split(".")[0].replace("_", " ").title(),
                            os.path.join(photo_dir, f), 0)
    return best[2], best[1], best[0]


# ------------------------------------------------------------------ background
def _plate(bg_path):
    """AI plate -> graded 4K canvas. Falls back to the template if missing."""
    if bg_path and os.path.exists(bg_path):
        img = Image.open(bg_path).convert("RGB")
        tw, th = img.size
        target = 16 / 9
        if abs(tw / th - target) > 0.01:
            if tw / th > target:
                nw = int(th * target)
                img = img.crop(((tw - nw) // 2, 0, (tw - nw) // 2 + nw, th))
            else:
                nh = int(tw / target)
                img = img.crop((0, (th - nh) // 2, tw, (th - nh) // 2 + nh))
        img = img.resize((W, H), Image.LANCZOS)
        img = ImageEnhance.Color(img).enhance(1.05)
        img = ImageEnhance.Contrast(img).enhance(1.04)
        img = img.filter(ImageFilter.GaussianBlur(
            float(os.environ.get("BG_BLUR", "5"))))
    else:
        from thumbnail import cinematic_bg
        img = cinematic_bg()

    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse([-W // 4, -H // 4, W + W // 4, H + H // 4],
                               fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(420))
    img = Image.composite(img, Image.new("RGB", (W, H), (0, 0, 0)),
                          vig.point(lambda v: 108 + v * 147 // 255))
    return img.convert("RGBA")


# ------------------------------------------------------------------- the word
def _fit(d, word, maxw, start=520, floor=150):
    size = start
    while size > floor:
        fnt = ImageFont.truetype(os.path.join(A, "ArchivoBlack.ttf"), size)
        if d.textlength(word, font=fnt) <= maxw:
            return fnt
        size -= 12
    return ImageFont.truetype(os.path.join(A, "ArchivoBlack.ttf"), floor)


def draw_word(img, word, x0=None, x1=None):
    """Big punch text stacked in the right half, glow + hard shadow."""
    if not word:
        return
    x0 = int(W * 0.46) if x0 is None else x0
    x1 = int(W * 0.965) if x1 is None else x1
    maxw = x1 - x0
    d = ImageDraw.Draw(img)

    words = word.strip().upper().split()
    lines, cur = [], ""
    for w_ in words:                       # greedy wrap, max 3 lines
        t = (cur + " " + w_).strip()
        probe = _fit(d, t, maxw)
        if d.textlength(t, font=probe) <= maxw and probe.size >= 200:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    lines = lines[:3]

    fonts = [_fit(d, ln, maxw) for ln in lines]
    heights = [int(f.size * 1.06) for f in fonts]
    y = (H - sum(heights)) // 2
    for ln, fnt, hh in zip(lines, fonts, heights):
        tw = d.textlength(ln, font=fnt)
        x = int(x0 + (maxw - tw) / 2)
        glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(glow).text((x, y), ln, font=fnt, fill=(255, 150, 20, 255),
                                  stroke_width=30, stroke_fill=(255, 104, 0, 255))
        g = glow.filter(ImageFilter.GaussianBlur(26))
        img.alpha_composite(g)
        img.alpha_composite(g)
        img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(90)))
        sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
        ImageDraw.Draw(sh).text((x + 10, y + 18), ln, font=fnt, fill=(0, 0, 0, 225))
        img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(14)))
        ImageDraw.Draw(img).text((x, y), ln, font=fnt, fill=WHITE,
                                 stroke_width=8, stroke_fill=(26, 12, 2))
        y += hh


# --------------------------------------------------------------------- compose
def compose(bg_path, photo_path, word, out=None, side="left"):
    from thumbnail import cutout, head_crop, place_player
    img = _plate(bg_path)
    placed = False
    if photo_path and os.path.exists(photo_path):
        try:
            cut = head_crop(cutout(photo_path))
            cx = W * (0.27 if side == "left" else 0.73)
            place_player(img, cut, cx, int(H * 0.995), int(H * 0.94), ORANGE)
            placed = True
        except Exception as e:
            print(f"[hybrid] cutout failed ({e})")
    if not placed:
        print("[hybrid] WARNING: no player on the thumbnail — check work/photos")
    if side == "left":
        draw_word(img, word)
    else:
        draw_word(img, word, int(W * 0.035), int(W * 0.54))

    out = out or os.path.join(BASE, "work", "thumbnail.jpg")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    final = img.convert("RGB")
    final.save(out, quality=95, subsampling=0)
    final.resize((1280, 720), Image.LANCZOS).save(
        out.replace(".jpg", "_yt.jpg"), quality=92)
    print(f"[hybrid] {os.path.basename(out)} | word={word!r} player={placed}")
    return out


def build(script, word=None, scene=None, out=None, photo_path=None):
    """Full method A: pick the star, get an AI plate, compose."""
    import thumb_ai
    name = None
    if not photo_path:
        name, photo_path, n = key_person(script)
        print(f"[hybrid] key person: {name} ({n} mentions) -> {photo_path}")
    bg = thumb_ai.generate_backdrop(scene or (script or {}).get("thumb_prompt"))
    return compose(bg, photo_path, word or (script or {}).get("thumb_word"), out)


if __name__ == "__main__":
    with open(sys.argv[1]) as f:
        s = json.load(f)
    build(s, s.get("thumb_word"), s.get("thumb_prompt"),
          sys.argv[2] if len(sys.argv) > 2 else None)
