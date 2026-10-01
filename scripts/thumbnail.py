#!/usr/bin/env python3
"""
thumbnail.py — channel-template thumbnail, 4K, cinematic.

Base   : assets/thumb_base2.jpg (Knicks striped template)
Adds   : cinematic grade (vignette, light beams, glow, contrast)
Players: 2-3 AI-cutout PNGs (rembg/u2net_human_seg) with rim-light + shadow
Banner : bottom band with a rotating punch word — sometimes NO text at all

Usage:
  python3 scripts/thumbnail.py "URGENT UPDATE!" photo1.jpg photo2.jpg [out.jpg]
Library:
  from thumbnail import make_thumb
"""
import math, os, random, sys

from PIL import Image, ImageChops, ImageDraw, ImageEnhance, ImageFilter, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A = os.path.join(BASE, "assets")
W, H = 3840, 2160                 # 4K master
BAND_TOP = int(H * 0.775)         # matches template's bottom band
ORANGE = (245, 132, 38)
ORANGE_HI = (255, 168, 66)
BLUE = (0, 122, 200)
WHITE = (255, 255, 255)

WORDS = ["BREAKING NEWS!", "URGENT UPDATE!", "EMERGENCY!", "PROBLEM!", "SCARY!",
         "HUGE NEWS!", "CRAZY TRADE!", "IT'S OVER?!", "SHOCKING!", None, None]
TEMPLATE = "thumb_base3.png"
CINEMATIC_TPL = False
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import channel as CH
    WORDS = CH.get("thumb_words", WORDS)
    TEMPLATE = CH.get("thumb_template", TEMPLATE)
    CINEMATIC_TPL = bool(CH.get("thumb_cinematic", False))
    _p = CH.get("palette", {})
    ORANGE = tuple(_p.get("primary", ORANGE))
    BLUE = tuple(_p.get("secondary", BLUE))
except Exception:
    pass

def _font(name, size):
    return ImageFont.truetype(os.path.join(A, name), size)

# --------------------------------------------------------------- background
TEXT_ZONE = (0.735, 1.0)          # where the template's baked-in word sits

def _erase_baked_text(img):
    """Hide the template's built-in word by extending the floor beneath it."""
    y0 = int(H * TEXT_ZONE[0])
    strip = img.crop((0, int(H * 0.60), W, y0))
    filler = strip.resize((W, H - y0), Image.LANCZOS)
    filler = filler.filter(ImageFilter.GaussianBlur(26))
    filler = ImageEnhance.Brightness(filler).enhance(0.86)
    # feather the seam
    mask = Image.new("L", (W, H - y0), 255)
    md = ImageDraw.Draw(mask)
    for i in range(90):
        md.line([(0, i), (W, i)], fill=int(255 * i / 90))
    img.paste(filler, (0, y0), mask)
    return img

def cinematic_bg():
    src = None
    for cand in (TEMPLATE, "thumb_base3.png", "thumb_base3.jpg",
                 "thumb_base2.jpg", "thumb_base.jpg"):
        p = os.path.join(A, cand)
        if os.path.exists(p):
            src = p
            break
    img = Image.open(src).convert("RGB").resize((W, H), Image.LANCZOS)
    if os.path.basename(src).startswith("thumb_base3") or CINEMATIC_TPL:
        img = _erase_baked_text(img)          # template already cinematic
        img = ImageEnhance.Color(img).enhance(1.06)
        img = ImageEnhance.Contrast(img).enhance(1.05)
    else:
        img = ImageEnhance.Color(img).enhance(1.22)
        img = ImageEnhance.Contrast(img).enhance(1.18)
        img = ImageEnhance.Sharpness(img).enhance(1.25)
        beams = Image.new("RGB", (W, H), (0, 0, 0))
        bd = ImageDraw.Draw(beams)
        for x0, col, wdt in ((-400, (46, 36, 20), 260), (900, (58, 45, 22), 180),
                             (2500, (38, 46, 62), 220)):
            bd.polygon([(x0, H), (x0 + 420, H), (x0 + 420 + H, 0), (x0 + H, 0)],
                       fill=col)
        img = ImageChops.screen(img, beams.filter(ImageFilter.GaussianBlur(160)))

    # slight defocus so the player cutouts pop (depth of field)
    img = img.filter(ImageFilter.GaussianBlur(float(os.environ.get("BG_BLUR", "7"))))
    img = ImageEnhance.Brightness(img).enhance(0.94)

    # cinematic vignette
    vig = Image.new("L", (W, H), 0)
    ImageDraw.Draw(vig).ellipse([-W // 4, -H // 4, W + W // 4, H + H // 4], fill=255)
    vig = vig.filter(ImageFilter.GaussianBlur(420))
    img = Image.composite(img, Image.new("RGB", (W, H), (0, 0, 0)),
                          vig.point(lambda v: 104 + v * 151 // 255))
    return img

# ------------------------------------------------------------------- cutouts
def cutout(path, cache_dir=None):
    """AI background removal -> RGBA cutout (cached next to the source)."""
    cache_dir = cache_dir or os.path.join(BASE, "work", "cutouts")
    os.makedirs(cache_dir, exist_ok=True)
    dst = os.path.join(cache_dir,
                       os.path.splitext(os.path.basename(path))[0] + "_cut.png")
    if os.path.exists(dst) and os.path.getsize(dst) > 5000:
        return Image.open(dst).convert("RGBA")
    from rembg import new_session, remove
    sess = new_session(os.environ.get("REMBG_MODEL", "u2net_human_seg"))
    out = remove(Image.open(path).convert("RGB"), session=sess)
    bbox = out.getbbox()
    if bbox:
        out = out.crop(bbox)
    out.save(dst)
    return out.convert("RGBA")


def _detect_face(rgb):
    """Return (x, y, w, h) of the largest face, or None."""
    try:
        import cv2, numpy as np
        arr = np.array(rgb)[:, :, ::-1].copy()
        gray = cv2.cvtColor(arr, cv2.COLOR_BGR2GRAY)
        casc = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        faces = casc.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))
        if len(faces) == 0:
            casc = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_profileface.xml")
            faces = casc.detectMultiScale(gray, 1.1, 5, minSize=(60, 60))
        if len(faces) == 0:
            return None
        return max(faces, key=lambda f: f[2] * f[3])
    except Exception as e:
        print(f"[thumb] face detect skipped: {e}")
        return None

def head_crop(cut, headroom=0.75, chest=3.2):
    """Crop an RGBA cutout to a head-and-chest portrait."""
    rgb = cut.convert("RGB")
    f = _detect_face(rgb)
    if f is not None:
        x, y, w, h = [int(v) for v in f]
        top = max(0, int(y - h * headroom))
        bottom = min(cut.height, int(y + h * chest))
        cx = x + w // 2
        half = int((bottom - top) * 0.62)
        left = max(0, cx - half)
        right = min(cut.width, cx + half)
    else:                      # fallback: upper portion of the body
        top, bottom = 0, int(cut.height * 0.62)
        left, right = 0, cut.width
    box = cut.crop((left, top, right, bottom))
    return box if box.width > 40 and box.height > 40 else cut

def retouch(img):
    """Skin-smooth + detail sharpen for large on-screen faces."""
    try:
        import cv2, numpy as np
        rgba = np.array(img)
        rgb, a = rgba[:, :, :3], rgba[:, :, 3]
        bgr = rgb[:, :, ::-1].copy()
        smooth = cv2.bilateralFilter(bgr, 9, 45, 45)          # even skin tone
        blend = cv2.addWeighted(bgr, 0.45, smooth, 0.55, 0)   # keep some texture
        blur = cv2.GaussianBlur(blend, (0, 0), 2.2)
        sharp = cv2.addWeighted(blend, 1.55, blur, -0.55, 0)  # crisp detail
        out = np.dstack([sharp[:, :, ::-1], a])
        img = Image.fromarray(out, "RGBA")
    except Exception as e:
        print(f"[thumb] retouch skipped: {e}")
        img = img.filter(ImageFilter.UnsharpMask(radius=3, percent=140, threshold=3))
    img = ImageEnhance.Contrast(img).enhance(1.08)
    img = ImageEnhance.Color(img).enhance(1.06)
    return img

def _upscale(img, factor):
    """Two-step Lanczos upscale with mild sharpening — cleaner than one jump."""
    steps = max(1, int(math.ceil(math.log(factor, 2))))
    cur = img
    for _ in range(steps):
        f = min(2.0, factor)
        cur = cur.resize((int(cur.width * f), int(cur.height * f)), Image.LANCZOS)
        cur = cur.filter(ImageFilter.UnsharpMask(radius=2, percent=70, threshold=3))
        factor /= f
        if factor <= 1.01:
            break
    return cur

def place_player(canvas, cut, cx, bottom, height, glow_rgb):
    """Scale + composite a cutout with rim glow and drop shadow."""
    if height > cut.height * 1.6:          # big upscale -> do it gently
        cut = _upscale(cut, height / cut.height)
    ratio = height / cut.height
    p = cut.resize((max(1, int(cut.width * ratio)), height), Image.LANCZOS)
    p = retouch(p)
    x, y = int(cx - p.width / 2), int(bottom - p.height)
    alpha = p.split()[3]

    # drop shadow (grounding)
    sh = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sh.paste(Image.new("RGBA", p.size, (0, 0, 0, 190)), (x + 26, y + 34), alpha)
    sh = sh.filter(ImageFilter.GaussianBlur(46))
    canvas.alpha_composite(sh)

    # rim glow in team colour
    gl = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    col = Image.new("RGBA", p.size, glow_rgb + (255,))
    for dx, dy in ((-16, 0), (16, 0), (0, -16), (0, 16), (-12, -12), (12, 12)):
        gl.paste(col, (x + dx, y + dy), alpha)
    gl = gl.filter(ImageFilter.GaussianBlur(38))
    canvas.alpha_composite(Image.blend(Image.new("RGBA", canvas.size, (0, 0, 0, 0)),
                                       gl, 0.85))
    canvas.alpha_composite(p.convert("RGBA"), (x, y))

# ------------------------------------------------------------------- banner
def draw_banner(img, word):
    if not word:
        return
    word = word.strip().upper()
    d = ImageDraw.Draw(img)
    size = 460
    while size > 140:
        fnt = _font("ArchivoBlack.ttf", size)
        if d.textlength(word, font=fnt) <= W - 240:
            break
        size -= 14
    tw = d.textlength(word, font=fnt)
    x = int((W - tw) // 2)
    y = int(H * 0.775)

    # orange fire glow behind the letters
    glow = Image.new("RGBA", img.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.text((x, y), word, font=fnt, fill=(255, 150, 20, 255),
            stroke_width=34, stroke_fill=(255, 108, 0, 255))
    g1 = glow.filter(ImageFilter.GaussianBlur(30))
    img.alpha_composite(g1)
    img.alpha_composite(g1)
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(95)))

    # hard drop shadow for depth
    sh = Image.new("RGBA", img.size, (0, 0, 0, 0))
    ImageDraw.Draw(sh).text((x + 12, y + 20), word, font=fnt, fill=(0, 0, 0, 220))
    img.alpha_composite(sh.filter(ImageFilter.GaussianBlur(16)))

    ImageDraw.Draw(img).text((x, y), word, font=fnt, fill=WHITE,
                             stroke_width=9, stroke_fill=(28, 14, 2))

# ------------------------------------------------------------------ compose
def make_thumb(word=None, players=None, out=None, seed=0):
    rnd = random.Random(seed)
    if word is None:
        word = rnd.choice(WORDS)
    img = cinematic_bg().convert("RGBA")

    cuts = []
    for p in (players or [])[:3]:
        try:
            if os.path.exists(p):
                cuts.append(cutout(p))
        except Exception as e:
            print(f"[thumb] cutout failed {p}: {e}")

    cuts = [head_crop(c) for c in cuts]           # close-up portraits
    bottom = int(H * 0.985)                        # feet at the floor line
    if len(cuts) == 1:
        place_player(img, cuts[0], W * 0.74, bottom, int(H * 0.82), ORANGE)
    elif len(cuts) == 2:
        place_player(img, cuts[0], W * 0.185, bottom, int(H * 0.80), BLUE)
        place_player(img, cuts[1], W * 0.815, bottom, int(H * 0.80), ORANGE)
    elif len(cuts) >= 3:
        place_player(img, cuts[2], W * 0.50, bottom - int(H * 0.04),
                     int(H * 0.58), (150, 150, 170))
        place_player(img, cuts[0], W * 0.155, bottom, int(H * 0.78), BLUE)
        place_player(img, cuts[1], W * 0.845, bottom, int(H * 0.78), ORANGE)

    draw_banner(img, word)
    out = out or os.path.join(BASE, "work", "thumbnail.jpg")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    final = img.convert("RGB")
    final.save(out, quality=95, subsampling=0)          # 4K master
    # YouTube-ready copy (<2MB) next to it
    yt = out.replace(".jpg", "_yt.jpg")
    final.resize((1280, 720), Image.LANCZOS).save(yt, quality=92)
    if not cuts:
        print("[thumb] WARNING: no player cutouts — check work/photos "
              f"({os.path.join(BASE, 'work', 'photos')})", flush=True)
    print(f"[thumb] {os.path.basename(out)} 4K + 720p | word={word!r} "
          f"players={len(cuts)}")
    return out


def players_from_script(script, photo_dir=None, limit=3):
    """Pick photo files for the players most mentioned in today's script."""
    """Pick photo files for the players most mentioned in today's script."""
    photo_dir = photo_dir or os.path.join(BASE, "work", "photos")
    if not os.path.isdir(photo_dir):
        return []
    import json as _json, re as _re
    text = _json.dumps(script).lower()
    scored = []
    for f in sorted(os.listdir(photo_dir)):
        if not f.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue
        stem = os.path.splitext(f)[0].lower()
        if stem in ("new_york_knicks", "madison_square_garden"):
            continue
        last = stem.split("_")[-1]
        if len(last) < 4:
            continue
        n = len(_re.findall(last, text))
        if n:
            scored.append((n, os.path.join(photo_dir, f)))
    scored.sort(reverse=True)
    picked = [p for _, p in scored[:limit]]
    if not picked:   # nobody named today -> use star players from the library
        for star in ("brunson", "towns", "bridges", "anunoby", "hart"):
            for f in sorted(os.listdir(photo_dir)):
                if star in f.lower() and os.path.join(photo_dir, f) not in picked:
                    picked.append(os.path.join(photo_dir, f))
                    break
            if len(picked) >= 2:
                break
    return picked[:limit]

def word_for_today(script=None, seed=None):
    """Rotate the banner word; sometimes returns None (no text)."""
    import datetime
    s = seed if seed is not None else datetime.date.today().toordinal()
    return random.Random(s).choice(WORDS)

if __name__ == "__main__":
    args = sys.argv[1:]
    word = args[0] if args else None
    if word == "-":
        word = None
    imgs = [a for a in args[1:] if not a.endswith((".jpg-out", ".out"))]
    out = None
    if imgs and imgs[-1].startswith("out:"):
        out = imgs.pop()[4:]
    make_thumb(word, imgs, out)
