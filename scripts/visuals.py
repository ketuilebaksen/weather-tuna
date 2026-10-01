#!/usr/bin/env python3
"""
visuals.py — generate 1920x1080 slide cards + 1280x720 thumbnail from script JSON.

One card per paragraph. Knicks brand palette (navy/blue/orange).
Usage: python3 scripts/visuals.py work/script.json
"""
import json, math, os, random, sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A = os.path.join(BASE, "assets")
W, H = 1920, 1080

NAVY   = (10, 16, 38)
NAVY2  = (16, 28, 66)
BLUE   = (0, 107, 182)    # Knicks blue
ORANGE = (245, 132, 38)   # Knicks orange
WHITE  = (244, 246, 252)
GREY   = (150, 160, 185)

try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import channel as CH
    BRAND = CH.get("name", "NY KNICKS DAILY")
    OUTRO_TAG = CH.get("outro_tag", "NEW KNICKS VIDEO EVERY DAY")
    _pal = CH.get("palette", {})
    ORANGE = tuple(_pal.get("primary", ORANGE))
    BLUE = tuple(_pal.get("secondary", BLUE))
except Exception:
    BRAND, OUTRO_TAG = "NY KNICKS DAILY", "NEW KNICKS VIDEO EVERY DAY"

def font(name, size):
    return ImageFont.truetype(os.path.join(A, name), size)

def bg(seed):
    """Dark navy court-inspired background with diagonal beams + halftone arcs."""
    rnd = random.Random(seed)
    img = Image.new("RGB", (W, H), NAVY)
    d = ImageDraw.Draw(img, "RGBA")
    # vertical gradient
    for y in range(H):
        f = y / H
        c = tuple(int(NAVY[i] + (NAVY2[i] - NAVY[i]) * f) for i in range(3))
        d.line([(0, y), (W, y)], fill=c)
    # diagonal beams
    for _ in range(3):
        x = rnd.randint(-300, W)
        w = rnd.randint(180, 420)
        col = (BLUE if rnd.random() < 0.6 else ORANGE) + (18,)
        d.polygon([(x, H), (x + w, H), (x + w + 500, 0), (x + 500, 0)], fill=col)
    # concentric arcs (three-point line vibe)
    cx, cy = rnd.choice([(-100, H + 150), (W + 100, -100), (W + 150, H + 100)])
    for r in range(200, 1500, 130):
        d.arc([cx - r, cy - r, cx + r, cy + r], 0, 360, fill=BLUE + (34,), width=3)
    img = img.filter(ImageFilter.GaussianBlur(1.2))
    return img

def wrap(d, text, fnt, maxw):
    words, lines, cur = text.split(), [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if d.textlength(t, font=fnt) <= maxw:
            cur = t
        else:
            if cur: lines.append(cur)
            cur = w_
    if cur: lines.append(cur)
    return lines

def draw_common(d, kicker, page, total):
    # top brand bar
    d.rectangle([0, 0, W, 8], fill=ORANGE)
    kf = font("Oswald-Var.ttf", 44)
    d.text((90, 52), BRAND, font=kf, fill=ORANGE)
    kw = d.textlength(BRAND, font=kf)
    d.text((90 + kw + 28, 52), kicker.upper(), font=kf, fill=GREY)
    # progress
    pf = font("Oswald-Var.ttf", 36)
    tag = f"{page:02d} / {total:02d}"
    d.text((W - 90 - d.textlength(tag, font=pf), 58), tag, font=pf, fill=GREY)

def card(seed, kicker, title, lines, page, total, out):
    img = bg(seed)
    d = ImageDraw.Draw(img, "RGBA")
    draw_common(d, kicker, page, total)
    tf = font("Anton-Regular.ttf", 110)
    tl = wrap(d, title.upper(), tf, W - 260)[:3] if title else []
    y = 300 if len(lines) else 380
    # In audio-driven mode most blocks carry no on-screen text at all — that is
    # the owner's rule, not a bug. So a card with no title is normal, and the
    # accent bar (whose height is derived from the number of title lines) must
    # simply not be drawn rather than collapse to a negative rectangle.
    if tl:
        d.rectangle([90, y + 8, 106, y + len(tl) * 118 - 10], fill=ORANGE)
        for ln in tl:
            d.text((140, y), ln, font=tf, fill=WHITE)
            y += 118
        y += 46
    bf = font("Inter-Var.ttf", 52)
    bf.set_variation_by_axes([28, 600])
    for ln in lines[:4]:
        for sub in wrap(d, ln, bf, W - 380)[:2]:
            d.ellipse([140, y + 22, 162, y + 44], fill=BLUE)
            d.text((196, y), sub, font=bf, fill=(210, 218, 235))
            y += 78
    img.save(out, quality=92)

def thumbnail(title_lines, out):
    img = bg(9137).resize((1280, 720))
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, 1280, 10], fill=ORANGE)
    d.rectangle([0, 710, 1280, 720], fill=ORANGE)
    kf = font("Oswald-Var.ttf", 54)
    d.text((60, 44), BRAND, font=kf, fill=ORANGE)
    tf = font("Anton-Regular.ttf", 128)
    y = 200
    for ln in title_lines[:3]:
        w_ = d.textlength(ln.upper(), font=tf)
        d.rectangle([52, y - 10, 52 + w_ + 36, y + 148], fill=(6, 10, 26, 235))
        d.text((70, y), ln.upper(), font=tf, fill=WHITE)
        y += 168
    img.save(out, quality=92)

def intro_card(out):
    import datetime
    img = bg(4242)
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, W, 10], fill=ORANGE)
    d.rectangle([0, H - 10, W, H], fill=ORANGE)
    tf = font("Anton-Regular.ttf", 190)
    parts = BRAND.split(" ", 1) if " " in BRAND else [BRAND, ""]
    for li, (txt, col) in enumerate([(parts[0], WHITE), (parts[1], ORANGE)]):
        w_ = d.textlength(txt, font=tf)
        d.text(((W - w_) / 2, 250 + li * 220), txt, font=tf, fill=col,
               stroke_width=8, stroke_fill=(0, 0, 0))
    kf = font("Oswald-Var.ttf", 58)
    date_s = datetime.date.today().strftime("%B %d, %Y").upper()
    w_ = d.textlength(date_s, font=kf)
    d.rectangle([(W - w_) / 2 - 30, 740, (W + w_) / 2 + 30, 740 + 88],
                fill=(0, 0, 0, 210))
    d.text(((W - w_) / 2, 752), date_s, font=kf, fill=GREY)
    img.save(out, quality=92)

def outro_card(out):
    img = bg(777)
    d = ImageDraw.Draw(img, "RGBA")
    d.rectangle([0, 0, W, 10], fill=ORANGE)
    d.rectangle([0, H - 10, W, H], fill=ORANGE)
    tf = font("Anton-Regular.ttf", 130)
    for li, (txt, col) in enumerate([("THANKS FOR WATCHING", WHITE),
                                     ("SUBSCRIBE", ORANGE)]):
        w_ = d.textlength(txt, font=tf)
        d.text(((W - w_) / 2, 300 + li * 200), txt, font=tf, fill=col,
               stroke_width=7, stroke_fill=(0, 0, 0))
    kf = font("Oswald-Var.ttf", 54)
    tag = OUTRO_TAG
    w_ = d.textlength(tag, font=kf)
    d.text(((W - w_) / 2, 760), tag, font=kf, fill=GREY)
    img.save(out, quality=92)

def main():
    with open(sys.argv[1]) as f:
        script = json.load(f)
    out_dir = os.path.join(BASE, "work", "cards")
    os.makedirs(out_dir, exist_ok=True)
    total = sum(len(s["paragraphs"]) for s in script["sections"])
    idx = 0
    for si, sec in enumerate(script["sections"]):
        for para in sec["paragraphs"]:
            title = para.get("card_title") or sec["heading"]
            lines = para.get("card_lines") or []
            card(1000 + idx * 7, sec["heading"], title, lines,
                 idx + 1, total, os.path.join(out_dir, f"c_{idx:04d}.jpg"))
            idx += 1
    out_thumb = os.path.join(BASE, "work", "thumbnail.jpg")
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    made = False
    engine = "template"
    try:
        import channel as _CH
        engine = _CH.get("thumb_engine", "ai")
    except Exception:
        engine = "ai"
    _pd = os.path.join(BASE, "work", "photos")
    _n = len(os.listdir(_pd)) if os.path.isdir(_pd) else 0
    print(f"[visuals] photo library: {_n} files in work/photos")

    if engine == "none":
        # the owner designs the cover by hand — see work/kapak_brief.md
        print("[visuals] thumbnail engine off — no cover generated")
        made = True
    if engine == "bigtype":
        # giant word behind the real player, AI arena plate, text drawn by us
        try:
            import thumb_ai, thumb_hybrid, thumb_style
            people = thumb_hybrid.key_people(script, limit=2)
            for nm, _p, n in people:
                print(f"[visuals] thumbnail person: {nm} ({n} mentions)")
            bg = thumb_ai.generate_backdrop(script.get("thumb_prompt"))
            thumb_style.bigtype(script.get("thumb_word") or "BREAKING NEWS",
                                photo=people[0][1] if people else None,
                                photo2=people[1][1] if len(people) > 1 else None,
                                bg=bg, out=out_thumb)
            made = os.path.exists(out_thumb)
        except Exception as e:
            print(f"[visuals] bigtype thumbnail failed ({e})")
    if not made and engine == "hybrid":
        # real player photo + AI background plate + text drawn by us
        try:
            import thumb_hybrid
            thumb_hybrid.build(script, script.get("thumb_word"),
                               script.get("thumb_prompt"), out_thumb)
            made = os.path.exists(out_thumb)
        except Exception as e:
            print(f"[visuals] hybrid thumbnail failed ({e})")
    if not made and engine in ("ai", "hybrid", "bigtype"):
        try:
            import thumb_ai
            raw = thumb_ai.generate(script.get("thumb_prompt"),
                                    script.get("thumb_word"),
                                    script.get("thumb_subject"))
            if raw:
                thumb_ai.finish(raw, out_thumb)
                made = True
        except Exception as e:
            print(f"[visuals] AI thumbnail failed ({e})")
    if not made:
        try:
            from thumbnail import make_thumb, players_from_script, word_for_today
            make_thumb(script.get("thumb_word") or word_for_today(script),
                       players_from_script(script), out_thumb)
        except Exception as e:
            print(f"[visuals] cinematic thumbnail failed ({e}) — basic fallback")
            thumbnail(script.get("thumbnail_lines") or [script["title"][:20]], out_thumb)
    intro_card(os.path.join(BASE, "work", "intro.jpg"))
    outro_card(os.path.join(BASE, "work", "outro.jpg"))
    print(f"[visuals] {idx} cards + intro/outro + thumbnail -> work/cards/")

if __name__ == "__main__":
    main()
