#!/usr/bin/env python3
"""
hook.py — the Vox-style opener: pages flying in over a moving shot.

The first thirty seconds decide whether anyone watches the rest, so the opener
is built differently from the body. Three things stack on top of each other:

  1. a 2.5D parallax shot instead of a flat photo, so the frame has depth
  2. "pages" — headline cards cut from what the narrator is actually saying —
     that fly in, hold for a beat and fly out, two or three on screen at once
  3. fast stock cuts filling whatever is left of the hook

The pages are the Vox signature: they arrive fast, at an angle, with a hard
accent bar, and they leave before you finish reading them. That is the point —
they punctuate the voice, they do not replace it. (The owner's rule still
holds: these are not subtitles. They are headlines, and they only appear in
the opener.)

Everything is guarded. If the parallax model cannot run, the opener falls back
to stock footage; if the pages cannot be drawn, the opener still plays. A
missing effect costs a little polish, a raised exception costs the whole video.

Env:
  HOOK_PAGES      how many pages fly through (default 5)
  HOOK_PAGES_SEC  how long the page burst runs (default 6.5)
  HOOK_MAX        opener length cap in seconds (default 9)
  REMOTION        "0" forces the ffmpeg pages even when Remotion is installed
"""
import json, os, random, re, subprocess

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
A = os.path.join(BASE, "assets")
W, H = 1920, 1080
N_PAGES = int(os.environ.get("HOOK_PAGES", "5"))
PAGES_SEC = float(os.environ.get("HOOK_PAGES_SEC", "6.5"))
HOOK_MAX = float(os.environ.get("HOOK_MAX", "9"))

STOP = {"the", "a", "an", "of", "to", "in", "on", "at", "for", "with", "and",
        "but", "so", "that", "this", "it", "is", "was", "as", "he", "his",
        "they", "their", "you", "we", "i", "who", "which", "when", "then",
        "not", "are", "be", "been", "has", "have", "had", "will", "would"}


def phrases(script, limit=None):
    """Short, loud lines lifted out of the opening — never invented."""
    limit = limit or N_PAGES
    out, seen = [], set()

    for sec in script.get("sections", [])[:2]:
        for para in sec.get("paragraphs", []):
            t = (para.get("card_title") or "").strip()
            if t and t.upper() not in seen:
                seen.add(t.upper()); out.append(t.upper())

    # then whatever the opening actually says, in two-to-four word bites.
    # Only the first couple of paragraphs: the "subscribe to the channel"
    # housekeeping that follows is not a headline and must never become one.
    text = " ".join(p.get("text", "")
                    for s in script.get("sections", [])[:1]
                    for p in s.get("paragraphs", [])[:2])
    for sent in re.split(r"[.!?]", text):
        toks = [w for w in re.findall(r"[A-Za-z0-9$%.\-]+", sent)]
        for i in range(len(toks) - 1):
            for L in (3, 2, 4):
                span = toks[i:i + L]
                if len(span) < 2:
                    continue
                low = [w.lower() for w in span]
                if low[0] in STOP or low[-1] in STOP:
                    continue
                score = sum(3 if any(c.isdigit() for c in w) else
                            2 if w[:1].isupper() else 1 for w in span)
                if score < 6:
                    continue
                cand = " ".join(span).upper()
                if cand in seen or len(cand) > 26:
                    continue
                # two phrases that share most of their words are the same
                # headline twice — "OUT OF NEW YORK" after "COMING OUT OF NEW"
                # reads as a stutter, not as two beats
                new = set(cand.split())
                if any(len(new & set(o.split())) >= 2 for o in out):
                    continue
                seen.add(cand); out.append(cand)
                break
            if len(out) >= limit * 3:
                break
    return out[:limit]


def page_png(text, out, idx=0, palette=None):
    """One headline card on transparency: accent bar, heavy type, soft shadow."""
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
    pal = palette or {}
    accent = tuple(pal.get("primary", (245, 132, 38)))
    ink = (12, 14, 22)

    f = ImageFont.truetype(os.path.join(A, "Anton-Regular.ttf"), 74)
    tmp = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if tmp.textlength(t, font=f) <= 760:
            cur = t
        else:
            if cur: lines.append(cur)
            cur = w
    if cur: lines.append(cur)
    lines = lines[:2]

    tw = max(int(tmp.textlength(l, font=f)) for l in lines)
    pw, ph = tw + 150, len(lines) * 92 + 74
    card = Image.new("RGBA", (pw + 30, ph + 30), (0, 0, 0, 0))
    d = ImageDraw.Draw(card)
    d.rectangle([16, 16, pw + 12, ph + 12], fill=(0, 0, 0, 120))     # shadow
    card = card.filter(ImageFilter.GaussianBlur(9))
    d = ImageDraw.Draw(card)
    d.rectangle([0, 0, pw, ph], fill=(246, 247, 250, 250))
    d.rectangle([0, 0, 18, ph], fill=accent + (255,))
    y = 34
    for ln in lines:
        d.text((52, y), ln, font=f, fill=ink)
        y += 92
    card.save(out)
    return out, card.size


REMOTION_ON = os.environ.get("REMOTION", "1") != "0"


def _beats(n, dur, hold=1.25):
    """When each page lands. Shared by both renderers so the two look alike."""
    step = max(0.5, (dur - hold) / max(1, n))
    return [round(0.3 + i * step, 3) for i in range(n)]


def _remotion_pages(base_clip, texts, dur, out, palette, crf, preset, fps):
    """Render the pages in Remotion and composite them over the footage.

    Remotion gives the cards real motion — they overshoot, settle and leave
    at an angle — which ffmpeg's overlay filter cannot express. It is slow
    (a browser draws every frame), so only these few seconds go through it.
    Raises on any problem; the caller falls back to the ffmpeg pages.
    """
    root = os.path.join(BASE, "remotion")
    if not os.path.isdir(os.path.join(root, "node_modules", "remotion")):
        raise RuntimeError("remotion is not installed")

    work = os.path.join(BASE, "work", "hook")
    os.makedirs(work, exist_ok=True)
    pal = palette or {}
    props = {
        "pages": [{"text": t, "at": at}
                  for t, at in zip(texts, _beats(len(texts), dur))],
        "accent": list(pal.get("primary", (245, 132, 38))),
    }
    props_path = os.path.join(work, "props.json")
    with open(props_path, "w") as f:
        json.dump(props, f, ensure_ascii=False)

    overlay = os.path.join(work, "overlay.webm")
    frames = max(2, int(round(dur * fps))) - 1
    cmd = ["npx", "remotion", "render", "HookPages", overlay,
           f"--props={props_path}", f"--frames=0-{frames}",
           "--concurrency=2", "--log=error"]
    chrome = os.environ.get("REMOTION_CHROME", "")
    if chrome:
        cmd.append(f"--browser-executable={chrome}")
    print(f"[hook] remotion rendering {frames + 1} frames …", flush=True)
    subprocess.run(cmd, cwd=root, check=True)

    # -c:v libvpx before the overlay input: without it ffmpeg decodes the
    # WebM without its alpha plane and the card arrives as an opaque block
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", base_clip,
         "-c:v", "libvpx", "-i", overlay,
         "-filter_complex",
         f"[0:v]scale={W}:{H},fps={fps}[b];"
         f"[b][1:v]overlay=0:0:format=auto,format=yuv420p",
         "-t", f"{dur:.3f}", "-r", str(fps),
         "-c:v", "libx264", "-preset", preset, "-crf", crf,
         "-pix_fmt", "yuv420p", "-an", out], check=True)
    print("[hook] opener pages: remotion", flush=True)
    return out


def vox_pages(base_clip, texts, dur, out, palette=None, crf="20", preset="fast",
              fps=24):
    """Fly `texts` across `base_clip` as pages. Returns `out`."""
    if not texts:
        raise ValueError("no page text")
    work = os.path.join(BASE, "work", "hook")
    os.makedirs(work, exist_ok=True)

    # never outrun the footage underneath: the tail would freeze or go black
    try:
        r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries",
                            "format=duration", "-of", "csv=p=0", base_clip],
                           capture_output=True, text=True)
        base_dur = float(r.stdout.strip())
        dur = min(dur, base_dur)
    except Exception:
        pass

    if REMOTION_ON:
        try:
            return _remotion_pages(base_clip, texts, dur, out, palette,
                                   crf, preset, fps)
        except Exception as e:
            print(f"[hook] remotion pages unavailable ({e}) — ffmpeg pages",
                  flush=True)

    rnd = random.Random(len(texts) * 977 + int(dur * 10))
    pages = []
    for i, t in enumerate(texts):
        p = os.path.join(work, f"page_{i:02d}.png")
        _, size = page_png(t, p, i, palette)
        pages.append((p, size))

    # Beats: pages overlap by design — one is still leaving as the next lands.
    hold = 1.15
    beats = _beats(len(pages), dur)
    inputs, chains, last = [], [], "[base]"
    inputs += ["-i", base_clip]
    for i, (p, _s) in enumerate(pages):
        inputs += ["-loop", "1", "-t", f"{dur:.3f}", "-i", p]

    chains.append(f"[0:v]scale={W}:{H},fps={fps},format=rgba[base]")
    for i, (p, (pw, ph)) in enumerate(pages):
        t0 = beats[i]
        t1 = round(t0 + hold, 3)
        side = -1 if i % 2 == 0 else 1
        # land on a lane, not dead centre, so two pages can share the screen
        lane_y = int(H * (0.24 + 0.17 * (i % 3)))
        x_end = int(W * 0.10) if side < 0 else int(W * 0.90) - pw
        x_start = x_end - side * -1 * int(W * 0.55)
        ramp = 0.22
        xexpr = (f"'{x_start}+({x_end}-{x_start})*"
                 f"min(1,max(0,(t-{t0})/{ramp}))"
                 f"-({x_end}-{x_start})*min(1,max(0,(t-{t1})/{ramp}))'")
        chains.append(
            f"[{i+1}:v]format=rgba,fps={fps},"
            f"fade=t=in:st={t0}:d=0.10:alpha=1,"
            f"fade=t=out:st={t1}:d=0.14:alpha=1[p{i}]")
        chains.append(
            f"{last}[p{i}]overlay=x={xexpr}:y={lane_y}:"
            f"enable='between(t,{t0},{t1+ramp+0.1})'[s{i}]")
        last = f"[s{i}]"
    chains.append(f"{last}format=yuv420p[v]")

    subprocess.run(
        ["ffmpeg", "-y", "-v", "error"] + inputs +
        ["-filter_complex", ";".join(chains), "-map", "[v]",
         "-t", f"{dur:.3f}", "-r", str(fps),
         "-c:v", "libx264", "-preset", preset, "-crf", crf,
         "-pix_fmt", "yuv420p", "-an", out], check=True)
    return out
