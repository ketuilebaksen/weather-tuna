#!/usr/bin/env python3
"""
assemble.py — final video builder.

- Hook (section 0): fast Vox-style cuts from b-roll, white-flash transitions,
  bottom captions + occasional big keyword pops synced to narration.
- Body: info cards + b-roll interludes + slow ken-burns photo segments.
- Audio: narration (+12 dB) + owner's background music (-18.5 dB, looped,
  faded) + at most ~5 transition SFX per video. Final loudness normalized.
- Quality: lanczos scaling + light sharpen, CRF 18.

Usage: python3 scripts/assemble.py content/current/script.json
"""
import datetime, glob, hashlib, json, os, random, re, subprocess, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FPS = 24
W_OUT, H_OUT = 1920, 1080
FONT = os.path.join(BASE, "assets", "Anton-Regular.ttf")
CUT_LEN = 2.8            # seconds per hook cut (fast)
BODY_CUT = 3.4           # seconds per body cut (calmer, professional)
BODY_BROLL_EVERY = 4     # every Nth body paragraph -> b-roll interlude
NARR_GAIN = float(os.environ.get("NARR_GAIN", "12.0"))     # dB
MUSIC_GAIN = float(os.environ.get("MUSIC_GAIN", "-18.5"))  # dB
NARR_PEAK = float(os.environ.get("NARR_PEAK_DBFS", "-3.0"))  # safe headroom
SFX_GAIN = float(os.environ.get("SFX_GAIN", "-15"))        # dB
MAX_SFX = int(os.environ.get("MAX_SFX", "5"))
# CRF 16 gorsel olarak kusursuzdu ama 32 dakikalik bir video 2.2 GB ediyordu ve
# GitHub tek dosyada 2 GB'i kabul etmiyor. CRF 20 gozle ayirt edilemeyecek kadar
# yakin, dosyayi yariya indiriyor. YouTube zaten yeniden kodluyor.
# Daha keskin isteyen depo degiskeni CRF_CUT=16 ile geri alabilir.
CRF_CUT = os.environ.get("CRF_CUT", "20")      # b-roll cuts (lower = sharper)
CRF_PHOTO = os.environ.get("CRF_PHOTO", "20")
PRESET = os.environ.get("X264_PRESET", "fast")
SHARPEN = os.environ.get("SHARPEN", "0") == "1"  # off: keep source look
OVERLAY_KINDS = ["speech", "lower3", "comic", "chat"]

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
try:
    import channel as CH
    CUT_LEN = float(CH.get("hook_cut", CUT_LEN))
    BODY_CUT = float(CH.get("body_cut", BODY_CUT))
    OVERLAY_KINDS = CH.get("overlay_kinds", OVERLAY_KINDS)
    OVERLAY_EVERY = float(CH.get("overlay_every_sec", 25))
    CLIP_OFFSET = int(CH.get("clip_offset", 37))
    BOUNCE = bool(CH.get("bounce", True))
    PHOTO_ZOOM = float(CH.get("photo_zoom", 0.08))
    BRAND = CH.get("name", "NY KNICKS DAILY")
    PALETTE = CH.get("palette", {})
    STOCK_SHARE_CH = CH.get("stock_share", None)
    _CH_GET = CH.get
except Exception as _e:
    print(f"[assemble] channel config default ({_e})")
    OVERLAY_EVERY, CLIP_OFFSET, BOUNCE, PHOTO_ZOOM = 25.0, 37, True, 0.08
    BRAND, PALETTE, STOCK_SHARE_CH = "NY KNICKS DAILY", {}, None
    _CH_GET = lambda k, d=None: d


def _cfg(key, default, cast=float):
    """channel.json value, overridable by an environment variable."""
    env = os.environ.get(key.upper())
    if env not in (None, ""):
        return cast(env)
    return cast(_CH_GET(key, default))


# ---------------------------------------------------------------------------
# PHOTO-LED EDITING
#
# The default edit cuts stock footage all the way through. A photo-led channel
# inverts that: footage is a scarce opening resource and the body is carried by
# still images, each given its own slow push or pull so it never reads as a
# slideshow. The knobs below are what separate the two.
#
#   photo_first        turn the photo-led edit on
#   broll_pool         how many DIFFERENT stock clips the video may draw
#   broll_budget       hard cap on stock cuts, opener included (0 = no cap)
#   broll_window_sec   after this many seconds, no more stock footage at all
#   mix_window_sec     the opening stretch that alternates footage and stills
#   motion_rate        how often a motion-graphics plate replaces a still
#   collage_every_sec  minimum gap between two cut-out text cards
# ---------------------------------------------------------------------------
PHOTO_FIRST = str(_cfg("photo_first", 0, lambda v: v)).lower() in (
    "1", "true", "yes", "on")
BROLL_BUDGET = int(_cfg("broll_budget", 0))
BROLL_WINDOW = _cfg("broll_window_sec", 0.0)
MIX_WINDOW = _cfg("mix_window_sec", 60.0)
MOTION_RATE = _cfg("motion_rate", 0.0)
BROLL_POOL = int(_cfg("broll_pool", 0))
COLLAGE_EVERY = _cfg("collage_every_sec", 22.0)
COLLAGE_ON = str(_cfg("collage", 1 if PHOTO_FIRST else 0,
                      lambda v: v)).lower() in ("1", "true", "yes", "on")

# How long the Vox-style opener runs before the hook falls back to fast cuts.
HOOK_MAX = float(os.environ.get("HOOK_MAX", "9"))

# Variety inside the body. CUTIN_RATE is how often a cut re-frames the same
# footage instead of jumping elsewhere; SLOWMO is the speed of a punch-line
# shot (0 turns it off) and SLOWMO_EVERY is the minimum gap between two.
# These used to be environment-only, which meant a channel could not have its
# own tempo. A documentary channel wants slower, more frequent slow motion and
# fewer re-framings than a news channel, so they read channel.json first.
CUTIN_RATE = _cfg("cutin_rate", 0.22)
SLOWMO = _cfg("slowmo", 0.6)
SLOWMO_EVERY = _cfg("slowmo_every_sec", 30.0)
AMBIENT_UNDER = float(os.environ.get("AMBIENT_UNDER", "26"))  # dB below voice

# The opener opens on footage rather than on a photo. Set OPENER_FOOTAGE=0 to
# go back to the 2.5D still.
OPENER_FOOTAGE = os.environ.get("OPENER_FOOTAGE", "1") != "0"

# How much of the body is real stock footage. The rest is filled from the
# motion-graphics library and player photos. 1.0 = the old all-footage edit.
STOCK_SHARE = float(os.environ.get("STOCK_SHARE",
                                   STOCK_SHARE_CH if STOCK_SHARE_CH is not None
                                   else "1.0"))

# The branded opener runs silent, so the video starts with a few seconds of
# nobody talking. Set INTRO=0 and the video opens on the first spoken word.
INTRO_ON = os.environ.get("INTRO", "1") != "0"

RHYTHM = None          # (envelope, hop) once the narration has been read

def run(cmd):
    subprocess.run(cmd, check=True)

def ffdur(path):
    r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0

def esc(text, maxlen=40):
    """On-screen caption text, safe for an ffmpeg drawtext value.

    The value is wrapped in single quotes inside the filtergraph, and ffmpeg
    offers no way to put a single quote *inside* those quotes — a backslash
    does not help. An apostrophe therefore closed the string early and the
    rest of the filter was parsed as garbage ("No such filter: 't/0.22'").
    So quotes, colons, percent signs and backslashes are dropped outright
    rather than escaped: nothing special is left to go wrong.
    """
    t = str(text)
    for ch in ("'", "‘", "’", "`", "\"", "“", "”", "\\", "%", ":"):
        t = t.replace(ch, " " if ch in (":",) else "")
    t = re.sub(r"[^0-9A-Za-z ÇĞİÖŞÜçğıöşü\-\.\$]", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t.upper()[:maxlen].strip()

def video_seed(script, tm, nparas):
    """A shuffle seed that belongs to THIS video, not to today.

    The seed used to be the date, which was fine while there was one video a
    day. Rendering five in a morning meant five identical draws: same photos in
    the same places, same clips in the same order. Deriving it from the
    script instead gives every video its own arrangement, while a re-render of
    the same script still reproduces exactly (so cached segments stay valid).
    """
    key = "|".join([
        str(script.get("title", "")),
        str(nparas),
        f"{float(tm.get('total', 0)):.2f}",
        "".join(str(s.get("heading", "")) for s in script.get("sections", [])),
    ])
    return int(hashlib.sha1(key.encode("utf-8", "ignore")).hexdigest()[:12], 16)


def media_lib(sub, exts):
    files = []
    for e in exts:
        files += glob.glob(os.path.join(BASE, "work", sub, "**", e), recursive=True)
    return sorted(set(files))

class Broll:
    def __init__(self, rng):
        self.rng = rng
        self.clips = []
        for f in media_lib("broll", ("*.mp4", "*.mov", "*.mkv", "*.webm", "*.m4v",
                                     "*.MP4", "*.MOV")):
            d = ffdur(f)
            if d >= 3.0:
                self.clips.append((f, d))
        self.rng.shuffle(self.clips)
        # A photo-led channel draws only a handful of clips from the depot and
        # lives off them: the same nine shots, re-framed and re-cut. Trimming
        # the deck here rather than counting cuts later is what makes that
        # true everywhere — opener, hook and body all draw from the same nine.
        if BROLL_POOL > 0 and len(self.clips) > BROLL_POOL:
            keep = self.rng.randrange(len(self.clips))
            rot = self.clips[keep:] + self.clips[:keep]
            self.clips = rot[:BROLL_POOL]
            print(f"[assemble] stok havuzu {BROLL_POOL} klibe indirildi "
                  f"({len(rot)} klipten)")
        # Every video starts the deck at its own point. This used to be keyed
        # to the date, so five videos rendered in one morning opened on the
        # same clip in the same order.
        self.i = self.rng.randrange(max(1, len(self.clips)))
        self.recent = []
        self.cooldown = int(os.environ.get("BROLL_COOLDOWN", "8"))
        print(f"[assemble] b-roll: {len(self.clips)} clips (offset {self.i})")

    def any(self):
        return len(self.clips) > 0

    def pick(self, need, avoid_repeat=True):
        """Next clip. Round-robin was perfectly cyclic, so the same footage
        came back in the same order every time and the video felt looped.
        Now we keep a short memory and take a clip that has not been on
        screen recently, chosen at random among those."""
        n = len(self.clips)
        if not avoid_repeat or n <= 2:
            f, d = self.clips[self.i % n]
            self.i += 1
        else:
            cool = min(self.cooldown, n - 1)
            fresh = [k for k in range(n) if k not in self.recent[-cool:]]
            k = self.rng.choice(fresh) if fresh else self.i % n
            f, d = self.clips[k]
            self.recent.append(k)
            self.i += 1
        return f, self.rng.uniform(0, max(0.0, d - need - 0.2))

    def last(self):
        """The clip just used — for a cut-in to the same moment."""
        if not self.recent:
            return None
        return self.clips[self.recent[-1]]

class MotionLib:
    """The pre-rendered motion-graphics plates, picked like stock footage."""

    def __init__(self, rng):
        self.rng = rng
        self.clips = []
        for f in media_lib("motion", ("*.mp4", "*.MP4")):
            d = ffdur(f)
            if d >= 2.5:
                self.clips.append((f, d))
        self.rng.shuffle(self.clips)
        self.recent = []
        if self.clips:
            print(f"[assemble] motion library: {len(self.clips)} plates")

    def any(self):
        return len(self.clips) > 0

    def pick(self, need):
        n = len(self.clips)
        cool = min(6, n - 1) if n > 2 else 0
        fresh = [k for k in range(n) if k not in self.recent[-cool:]] if cool else list(range(n))
        k = self.rng.choice(fresh) if fresh else self.rng.randrange(n)
        f, d = self.clips[k]
        self.recent.append(k)
        return f, self.rng.uniform(0, max(0.0, d - need - 0.2))


def broll_cut(src, start, dur, out, caption=None, big_word=None, flash=True,
              zoom=1.0, slow=1.0):
    """One cut of stock footage.

    `zoom` above 1 crops in tighter — cutting from a wide to a tight framing of
    the same footage reads as a second camera and costs nothing.
    `slow` below 1 stretches time: we pull `dur * slow` seconds of source and
    slow them to fill `dur`, which is what an editor does on a punch line.
    """
    grab = dur * slow
    wide = int(1920 * zoom) // 2 * 2
    tall = int(1080 * zoom) // 2 * 2
    vf = [f"scale={wide}:{tall}:force_original_aspect_ratio=increase:"
          "flags=lanczos+accurate_rnd+full_chroma_int",
          f"crop={wide}:{tall}",
          "crop=1920:1080" if zoom > 1.0 else "null",
          f"fps={FPS}"]
    vf = [f for f in vf if f != "null"]
    if slow < 1.0:
        vf.insert(0, f"setpts=PTS/{slow:.3f}")
    if SHARPEN:
        vf.insert(2, "unsharp=3:3:0.3:3:3:0.0")
    n_plain = len(vf)          # everything after this point is text overlay
    # transition flash disabled (owner preference)
    if caption:
        vf.append(
            f"drawtext=fontfile='{FONT}':text='{esc(caption)}':"
            f"fontsize=62:fontcolor=white:x=(w-text_w)/2:y=h-150:"
            f"borderw=5:bordercolor=black@0.9:shadowx=3:shadowy=3:shadowcolor=black@0.5")
    if big_word:
        vf.append(
            f"drawtext=fontfile='{FONT}':text='{esc(big_word, 24)}':"
            f"fontsize=132:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2-60:"
            f"borderw=7:bordercolor=black@0.85:alpha='min(1,t/0.22)'")
    def _encode(filters):
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}",
             "-t", f"{grab:.3f}", "-i", src,
             "-t", f"{dur:.3f}", "-vf", ",".join(filters), "-r", str(FPS),
             "-c:v", "libx264", "-preset", PRESET, "-crf", CRF_CUT,
             "-x264-params", "aq-mode=3:psy-rd=1.0",
             "-pix_fmt", "yuv420p", "-an", out])
    try:
        _encode(vf)
    except subprocess.CalledProcessError:
        # a caption must never cost us the whole video — drop the text and go on
        print(f"[assemble] text overlay failed on {os.path.basename(src)} "
              f"— rendering this cut without it", flush=True)
        _encode(vf[:n_plain])

def motion_cut(src, start, dur, out, caption=None, big_word=None):
    """One cut from the motion-graphics library.

    These plates were rendered once and are reused forever, so this is just a
    trim plus whatever text belongs on top — the same cost as a stock cut.
    The plate is deliberately calm in the middle, which is where the type sits.
    """
    vf = [f"scale={W_OUT}:{H_OUT}:force_original_aspect_ratio=increase:flags=lanczos",
          f"crop={W_OUT}:{H_OUT}", f"fps={FPS}"]
    n_plain = len(vf)
    if big_word:
        vf.append(
            f"drawtext=fontfile='{FONT}':text='{esc(big_word, 26)}':"
            f"fontsize=128:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:"
            f"borderw=7:bordercolor=black@0.85:alpha='min(1,max(0,(t-0.15)/0.35))'")
    elif caption:
        vf.append(
            f"drawtext=fontfile='{FONT}':text='{esc(caption)}':"
            f"fontsize=70:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:"
            f"borderw=6:bordercolor=black@0.85:alpha='min(1,max(0,(t-0.15)/0.35))'")

    def _encode(filters):
        run(["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.2f}",
             "-t", f"{dur:.3f}", "-i", src,
             "-t", f"{dur:.3f}", "-vf", ",".join(filters), "-r", str(FPS),
             "-c:v", "libx264", "-preset", PRESET, "-crf", CRF_CUT,
             "-pix_fmt", "yuv420p", "-an", out])
    try:
        _encode(vf)
    except subprocess.CalledProcessError:
        print(f"[assemble] motion text failed on {os.path.basename(src)}",
              flush=True)
        _encode(vf[:n_plain])


class PhotoPool:
    """Every photo in the library, dealt out like a shuffled deck.

    Not random: random repeats. The deck is walked start to finish before it
    is reshuffled, so in a video with more cuts than photos each picture is
    used the same number of times, and two neighbouring cuts are never the
    same shot. It also alternates the ken-burns direction, because a whole
    video of pushes in reads as a slideshow — the pull-outs are what make it
    feel cut rather than assembled.
    """

    def __init__(self, rng, photos):
        self.rng = rng
        self.deck = list(photos)
        self.rng.shuffle(self.deck)
        self.i = 0
        self.n = 0

    def any(self):
        return len(self.deck) > 0

    def pick(self):
        if not self.deck:
            return None, False
        if self.i >= len(self.deck):
            self.rng.shuffle(self.deck)
            self.i = 0
        p = self.deck[self.i]
        self.i += 1
        self.n += 1
        return p, (self.n % 2 == 0)      # every other still pulls back out


def choose_visual(t, k, rng, broll, motion, pool, budget):
    """What this cut is made of: "stock", "photo" or "motion".

    On a normal channel the answer is always stock footage. On a photo-led one
    the footage is rationed twice over — a hard budget for the whole video and
    a window of seconds past which it is simply unavailable — because the point
    is not "less footage", it is "footage at the top, stills after".

    Inside the opening window the two alternate rather than being drawn at
    random. Alternating locks the change of texture to the cut, and the cuts
    are already sitting on the speaker's phrasing, so the picture changes
    character exactly where the voice does.
    """
    if not PHOTO_FIRST:
        if motion.any() and rng.random() >= STOCK_SHARE:
            return "motion"
        return "stock" if broll.any() else ("photo" if pool.any() else "stock")

    stock_ok = (broll.any()
                and (BROLL_BUDGET <= 0 or budget[0] > 0)
                and (BROLL_WINDOW <= 0 or t < BROLL_WINDOW))

    if stock_ok and t < MIX_WINDOW:
        # the synced opening minute: footage, still, footage, still
        if k % 2 == 0:
            return "stock"
    elif stock_ok and rng.random() < 0.30:
        # past the first minute footage becomes an accent, not the material
        return "stock"

    if motion.any() and rng.random() < MOTION_RATE:
        return "motion"
    if pool.any():
        return "photo"
    return "stock" if broll.any() else "photo"


def build_collage(para, sec, idx, k, dur, seg_dir):
    """A cut-out text card for this paragraph, or (None, None) if it has none.

    The words come from the same place the info cards get theirs, so the card
    says something the narration is actually about — a card that just repeats
    the sentence under it is what made the earlier page treatment feel empty.
    """
    lines = [str(x).strip() for x in (para.get("card_lines") or []) if str(x).strip()]
    title = str(para.get("card_title") or "").strip()
    words = ([title] if title else []) + lines
    words = [w for w in words if w][:3]
    if not words:
        return None, None
    try:
        import collage as CL
        png = os.path.join(seg_dir, f"col_{idx:04d}_{k}.png")
        accent = tuple(PALETTE.get("primary", (245, 132, 38)))
        CL.card(words, png, FONT, accent=accent, seed=idx * 13 + k)
        return png, min(dur, max(1.9, dur * 0.62))
    except Exception as e:
        print(f"[assemble] collage skipped ({e})", flush=True)
        return None, None


def photo_segment(img, dur, out, caption=None, zoom_out=False, drift=None,
                  collage_png=None, collage_hold=None):
    frames = max(2, round(dur * FPS))
    # slow, professional ken-burns: 1.00 -> 1.08 across the whole segment,
    # or the same move run backwards when this still is a pull-out
    if zoom_out:
        z = f"max({1 + PHOTO_ZOOM}-{PHOTO_ZOOM}*on/{frames},1.0)"
    else:
        z = f"min(1+{PHOTO_ZOOM}*on/{frames},{1 + PHOTO_ZOOM})"
    # A panoramic photo (a stadium shot, say) scaled to 2400 wide comes out far
    # shorter than 1350, and cropping to a size larger than the frame is an
    # ffmpeg error, not a no-op — one such photo used to kill the whole render.
    # force_original_aspect_ratio=increase guarantees both sides reach the
    # target first, so the crop always has something to cut from.
    # A pure zoom with the frame pinned dead centre still feels locked off.
    # Letting the centre travel a little across the move is what turns it into
    # a camera. The number is in source pixels, so it stays small on screen.
    dx, dy = drift if drift else (0, 0)
    xexp = f"iw/2-(iw/zoom/2)+{dx}*on/{frames}"
    yexp = f"ih/2-(ih/zoom/2)+{dy}*on/{frames}"
    # A panoramic photo (a stadium shot, say) scaled to 2400 wide comes out far
    # shorter than 1350, and cropping to a size larger than the frame is an
    # ffmpeg error, not a no-op — one such photo used to kill the whole render.
    # force_original_aspect_ratio=increase guarantees both sides reach the
    # target first, so the crop always has something to cut from.
    plain = (f"scale=2400:1350:force_original_aspect_ratio=increase:"
             f"flags=lanczos+accurate_rnd,crop=2400:1350,"
             f"zoompan=z='{z}':d={frames}:x='{xexp}':y='{yexp}'"
             f":s=1920x1080:fps={FPS},format=yuv420p")
    vf = plain
    if caption:
        vf += (f",drawtext=fontfile='{FONT}':text='{esc(caption)}':"
               f"fontsize=62:fontcolor=white:x=(w-text_w)/2:y=h-150:"
               f"borderw=5:bordercolor=black@0.9:"
               f"shadowx=3:shadowy=3:shadowcolor=black@0.5")

    def _encode(filters, with_collage):
        cmd = ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", img]
        if with_collage:
            import collage as CL
            f = CL.overlay_filter(dur, hold=collage_hold)
            cmd += ["-loop", "1", "-i", collage_png,
                    "-filter_complex",
                    f"[0:v]{filters}[bg];[1:v]{f['prep']}[ov];"
                    f"[bg][ov]overlay={f['xy']}:{f['enable']}[v]",
                    "-map", "[v]"]
        else:
            cmd += ["-vf", filters]
        cmd += ["-t", f"{dur:.3f}", "-r", str(FPS),
                "-c:v", "libx264", "-preset", PRESET, "-crf", CRF_PHOTO,
                "-pix_fmt", "yuv420p", "-an", out]
        run(cmd)

    try:
        _encode(vf, bool(collage_png))
    except subprocess.CalledProcessError:
        # the picture is the point; the words on it are not worth losing it
        print(f"[assemble] photo text failed on {os.path.basename(img)} "
              f"— rendering the photo without it", flush=True)
        _encode(plain, False)

def card_segment(card, dur, idx, out, overlay=None):
    frames = max(2, round(dur * FPS))
    z = "min(1.0+0.00022*on,1.12)" if idx % 2 == 0 else "max(1.12-0.00022*on,1.0)"
    base = (f"[0:v]scale=2400:1350:flags=lanczos,zoompan=z='{z}':d={frames}"
            f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps={FPS},"
            f"format=yuv420p[bg]")
    cmd = ["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", card]
    if not overlay:
        cmd += ["-filter_complex", base, "-map", "[bg]"]
    else:
        png, kind, at, bw, bh = (overlay["png"], overlay["kind"], overlay["at"],
                                 overlay["w"], overlay["h"])
        cmd += ["-i", png]
        if kind == "comic":
            x = (1920 - bw) // 2 + (170 if idx % 2 == 0 else -170)
            y = max(60, (1080 - bh) // 2 - 190)
            fc = (base +
                  f";[1:v]scale=iw*0.55:-1[c1];[1:v]scale=iw*1.18:-1[c2];"
                  f"[bg][c1]overlay=x={x + int(bw*0.22)}:y={y + int(bh*0.22)}:"
                  f"enable='between(t,{at:.2f},{at + 0.09:.2f})'[t1];"
                  f"[t1][c2]overlay=x={x - int(bw*0.09)}:y={y - int(bh*0.09)}:"
                  f"enable='between(t,{at + 0.09:.2f},{at + 0.18:.2f})'[t2];"
                  f"[t2][1:v]overlay=x={x}:y={y}:enable='gte(t,{at + 0.18:.2f})'[vo]")
        else:
            if kind == "chat":
                x, yt = 1920 - bw - 140, 470
            elif kind == "lower3":
                x, yt = 110, 1080 - bh - 210
            else:  # speech
                x, yt = 140, 520
            # bounce-in from below: damped overshoot settling at yt
            yex = (f"{yt}+340*exp(-7.5*(t-{at:.2f}))*cos(9*(t-{at:.2f}))")
            fc = (base + f";[bg][1:v]overlay=x={x}:y='{yex}':"
                  f"enable='gte(t,{at:.2f})'[vo]")
        cmd += ["-filter_complex", fc, "-map", "[vo]"]
    cmd += ["-t", f"{dur:.3f}", "-r", str(FPS),
            "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-an", out]
    run(cmd)


def apply_overlay(vin, overlay, vout, idx=0):
    """Second pass: composite a bubble PNG (bounce/pop) onto a rendered segment."""
    png, kind, at, bw, bh = (overlay["png"], overlay["kind"], overlay["at"],
                             overlay["w"], overlay["h"])
    if kind == "comic":
        x = (1920 - bw) // 2 + (170 if idx % 2 == 0 else -170)
        y = max(60, (1080 - bh) // 2 - 190)
        fc = (f"[0:v][1:v]overlay=x={x}:y={y}:enable='gte(t,{at + 0.18:.2f})'[vo];"
              f"[1:v]scale=iw*0.55:-1[c1];[1:v]scale=iw*1.18:-1[c2]")
        fc = (f"[1:v]scale=iw*0.55:-1[c1];[1:v]scale=iw*1.18:-1[c2];"
              f"[0:v][c1]overlay=x={x + int(bw*0.22)}:y={y + int(bh*0.22)}:"
              f"enable='between(t,{at:.2f},{at + 0.09:.2f})'[t1];"
              f"[t1][c2]overlay=x={x - int(bw*0.09)}:y={y - int(bh*0.09)}:"
              f"enable='between(t,{at + 0.09:.2f},{at + 0.18:.2f})'[t2];"
              f"[t2][1:v]overlay=x={x}:y={y}:enable='gte(t,{at + 0.18:.2f})'[vo]")
    else:
        if kind == "chat":
            x, yt = 1920 - bw - 140, 470
        elif kind == "lower3":
            x, yt = 110, 1080 - bh - 210
        else:
            x, yt = 140, 520
        if BOUNCE:
            yex = f"{yt}+340*exp(-7.5*(t-{at:.2f}))*cos(9*(t-{at:.2f}))"
        else:                      # documentary: gentle slide-up, no overshoot
            yex = f"{yt}+120*exp(-4.5*(t-{at:.2f}))"
        fc = f"[0:v][1:v]overlay=x={x}:y='{yex}':enable='gte(t,{at:.2f})'[vo]"
    run(["ffmpeg", "-y", "-v", "error", "-i", vin, "-i", png,
         "-filter_complex", fc, "-map", "[vo]",
         "-c:v", "libx264", "-preset", PRESET, "-crf", CRF_CUT, "-an", vout])

def make_overlay_png(kind, para, sec, i):
    import overlays as OV
    ov_dir = os.path.join(BASE, "work", "overlays")
    os.makedirs(ov_dir, exist_ok=True)
    png = os.path.join(ov_dir, f"o_{i:04d}.png")
    lines = para.get("card_lines") or [para.get("card_title", "")]
    txt = lines[-1] if len(lines) > 1 else lines[0]
    if kind == "comic":
        word = re.sub(r"[^A-Za-z ]", "", str(para.get("card_title", ""))).split()
        word = (word[0].upper() + "!") if word else "BOOM!"
        w_, h_ = OV.comic_burst(word[:14], png)
    elif kind == "lower3":
        w_, h_ = OV.lower_third(para.get("card_title", ""), sec["heading"], png)
    elif kind == "chat":
        w_, h_ = OV.speech_bubble(txt, png, chat=True)
    else:
        w_, h_ = OV.speech_bubble(txt, png, chat=False)
    return {"png": png, "kind": kind, "w": w_, "h": h_}

def photo_lookup(photos):
    """map lowercase last-name -> photo path (from photo filenames)."""
    m = {}
    for f in photos:
        stem = os.path.splitext(os.path.basename(f))[0]
        key = stem.split("_")[-1].lower()
        if len(key) >= 4:
            m[key] = f
    return m

def make_intro(broll, seg_dir):
    """Fast branded opener: 2 flash cuts + title card. Returns (files, duration)."""
    files, d_total = [], 0.0
    if not INTRO_ON:
        print("[assemble] intro off — video ilk soylenen kelimeyle basliyor")
        return files, d_total
    if broll.any():
        for k in range(2):
            p = os.path.join(seg_dir, f"intro_cut{k}.mp4")
            if not (os.path.exists(p) and os.path.getsize(p) > 5000):
                src, start = broll.pick(1.1)
                broll_cut(src, start, 1.1, p,
                          big_word=BRAND if k == 1 else None, flash=True)
            files.append(p)
            d_total += 1.1
    card = os.path.join(BASE, "work", "intro.jpg")
    if os.path.exists(card):
        p = os.path.join(seg_dir, "intro_card.mp4")
        if not (os.path.exists(p) and os.path.getsize(p) > 5000):
            frames = max(2, round(2.4 * FPS))
            vf = (f"scale=2400:1350:flags=lanczos,"
                  f"zoompan=z='min(1.0+0.004*on,1.10)':d={frames}"
                  f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps={FPS},"
                  f"format=yuv420p")
            run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", card, "-vf", vf,
                 "-t", "2.4", "-r", str(FPS), "-c:v", "libx264", "-preset", "medium",
                 "-crf", "19", "-an", p])
        files.append(p)
        d_total += 2.4
    return files, d_total

def make_outro(seg_dir):
    card = os.path.join(BASE, "work", "outro.jpg")
    if not os.path.exists(card):
        return [], 0.0
    p = os.path.join(seg_dir, "outro_card.mp4")
    if not (os.path.exists(p) and os.path.getsize(p) > 5000):
        frames = max(2, round(7.0 * FPS))
        vf = (f"scale=2400:1350:flags=lanczos,"
              f"zoompan=z='min(1.0+0.0006*on,1.08)':d={frames}"
              f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s=1920x1080:fps={FPS},"
              f"format=yuv420p,fade=t=out:st=6.3:d=0.7")
        run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", card, "-vf", vf,
             "-t", "7.0", "-r", str(FPS), "-c:v", "libx264", "-preset", "medium",
             "-crf", "19", "-an", p])
    return [p], 7.0

def build_opener(out, dur, photos, broll, script, seg_dir, budget=None):
    """The first seconds: a 2.5D shot with headline pages flying across it.

    Built in two stages so each can fail on its own. The moving shot comes
    first — parallax over a real photo if the cut-out works, otherwise fast
    stock cuts. Then the pages fly over whatever that produced. If the pages
    fail we still ship the shot; if the shot fails we still ship the pages
    over footage. Only a total failure sends the caller back to plain cuts.
    """
    base = os.path.join(seg_dir, "hook_base.mp4")
    made = False

    # The opener now starts on real footage, always. A parallax still at the
    # very top of the video reads as a slideshow; motion from frame one is
    # what holds a viewer. The graphics ride on top of it instead.
    if OPENER_FOOTAGE and broll.any():
        n = max(2, round(dur / 2.0))
        cd = dur / n
        parts = []
        for k in range(n):
            p = os.path.join(seg_dir, f"hook_base_{k}.mp4")
            src, start = broll.pick(cd)
            if budget is not None:
                budget[0] -= 1
            broll_cut(src, start, cd, p, zoom=1.0 if k % 2 else 1.18)
            parts.append(p)
        lst = os.path.join(seg_dir, "hook_base.txt")
        with open(lst, "w") as f:
            f.write("\n".join(f"file '{p}'" for p in parts) + "\n")
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", lst, "-c", "copy", base])
        made = True
        print(f"[assemble] opener: {n} stock cuts", flush=True)

    # Prefer a photo of somebody the opening actually names. A stadium
    # panorama has no subject to lift off the background, so parallax on it
    # either fails outright or looks like a wobble.
    opening = " ".join(p.get("text", "")
                       for sec in script.get("sections", [])[:1]
                       for p in sec.get("paragraphs", [])[:3]).lower()
    def _rank(path):
        stem = os.path.splitext(os.path.basename(path))[0].lower()
        parts = [w for w in re.split(r"[^a-z]+", stem) if len(w) > 3]
        return -sum(1 for w in parts if w in opening)
    photos = sorted(photos, key=_rank)

    if not made and photos:
        try:
            import parallax
            # the opener carries the channel name only when there is no intro
            # card ahead of it, so the brand is never stamped twice
            if INTRO_ON:
                parallax.segment(photos[0], dur, base, crf=CRF_PHOTO,
                                 preset=PRESET, fps=FPS)
            else:
                parallax.hero(photos[0], dur, base, title=BRAND, font=FONT,
                              crf=CRF_PHOTO, preset=PRESET, fps=FPS)
            made = True
            print(f"[assemble] opener: parallax over "
                  f"{os.path.basename(photos[0])}", flush=True)
        except Exception as e:
            print(f"[assemble] parallax opener unavailable ({e})", flush=True)
    if not made:
        if not broll.any():
            raise RuntimeError("no photo and no b-roll for the opener")
        n = max(1, round(dur / 2.2))
        cd = dur / n
        parts = []
        for k in range(n):
            p = os.path.join(seg_dir, f"hook_base_{k}.mp4")
            src, start = broll.pick(cd)
            if budget is not None:
                budget[0] -= 1
            broll_cut(src, start, cd, p)
            parts.append(p)
        lst = os.path.join(seg_dir, "hook_base.txt")
        with open(lst, "w") as f:
            f.write("\n".join(f"file '{p}'" for p in parts) + "\n")
        run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
             "-i", lst, "-c", "copy", base])
        print("[assemble] opener: stock cuts (no usable photo)", flush=True)

    try:
        import hook
        hook.vox_pages(base, hook.phrases(script), dur, out,
                       palette=PALETTE, crf=CRF_CUT, preset=PRESET, fps=FPS)
    except Exception as e:
        print(f"[assemble] hook pages skipped ({e})", flush=True)
        run(["ffmpeg", "-y", "-v", "error", "-i", base, "-c", "copy", out])
    return out


def main():
    script_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        BASE, "content", "current", "script.json")
    with open(script_path) as f:
        script = json.load(f)
    with open(os.path.join(BASE, "work", "timings.json")) as f:
        tm = json.load(f)

    paras = []
    for si, sec in enumerate(script["sections"]):
        for para in sec["paragraphs"]:
            paras.append((si, sec, para))

    seed = video_seed(script, tm, len(paras))
    rng = random.Random(seed)
    print(f"[assemble] bu videonun karisim tohumu: {seed % 100000}")
    broll = Broll(rng)
    motion = MotionLib(rng)
    global RHYTHM
    try:
        import rhythm as RH
        RHYTHM = RH.load(BASE)
    except Exception as e:
        print(f"[assemble] rhythm unavailable ({e})")
        RHYTHM = None
    slow_state = [-999.0]
    collage_state = [-999.0]
    mix_tally = {"motion": 0, "stock": 0, "photo": 0, "collage": 0}
    photos = media_lib("photos", ("*.jpg", "*.jpeg", "*.png", "*.webp"))
    pmap = photo_lookup(photos)
    pool = PhotoPool(rng, photos)
    # The stock budget covers the WHOLE video, opener included, so the opener
    # is charged for what it spends before the body gets to see what is left.
    budget = [BROLL_BUDGET if BROLL_BUDGET > 0 else 10 ** 6]
    print(f"[assemble] photo library: {len(photos)} ({list(pmap)[:6]}...)")
    if PHOTO_FIRST:
        print(f"[assemble] foto agirlikli kurgu: stok butcesi {BROLL_BUDGET}, "
              f"ilk {BROLL_WINDOW:.0f} sn icinde, karisik acilis {MIX_WINDOW:.0f} sn")
    seg_dir = os.path.join(BASE, "work", "segs")
    os.makedirs(seg_dir, exist_ok=True)

    concat, section_starts = [], []
    intro_files, INTRO_D = make_intro(broll, seg_dir)
    concat += [f"file '{p}'" for p in intro_files]
    n = len(tm["items"])
    last_popup_t = -999.0
    ov_slot = 0
    for it in tm["items"]:
        i, dur, t0 = it["idx"], it["dur"], it["start"]
        si, sec, para = paras[i]
        if it["para"] == 0 and si > 0:
            section_starts.append(t0)
        card = os.path.join(BASE, "work", "cards", f"c_{i:04d}.jpg")
        seg = os.path.join(seg_dir, f"s_{i:04d}.mp4")
        concat.append(f"file '{seg}'")
        fresh = not (os.path.exists(seg) and os.path.getsize(seg) > 5000)

        is_hook = (si == 0) and broll.any()

        # decide overlay for this paragraph (counters advance even on cache)
        ov_kind = None
        if not is_hook:
            if it["para"] == 0 and si > 0:
                ov_kind = "lower3"          # chapter marker on every section start
                last_popup_t = t0
            elif dur >= 8 and (t0 - last_popup_t) >= OVERLAY_EVERY and para.get("card_lines"):
                ov_kind = OVERLAY_KINDS[ov_slot % len(OVERLAY_KINDS)]
                ov_slot += 1
                last_popup_t = t0

        if is_hook:
            parts = []
            remaining = dur
            # The opener: a 2.5D parallax shot with headline pages flying over
            # it. This is the only place in the video where text arrives in
            # bursts — the first seconds have to earn the rest of the watch.
            if i == 0:
                try:
                    od = min(HOOK_MAX, dur)
                    op = os.path.join(seg_dir, "hook_open.mp4")
                    if fresh or not (os.path.exists(op) and
                                     os.path.getsize(op) > 5000):
                        build_opener(op, od, photos, broll, script, seg_dir, budget)
                    parts.append(f"file '{op}'")
                    remaining = max(0.0, dur - od)
                except Exception as e:
                    print(f"[assemble] opener skipped ({e}) — plain hook cuts",
                          flush=True)
                    remaining = dur

            cuts = max(1, round(remaining / CUT_LEN)) if remaining > 0.7 else 0
            cut_d = remaining / cuts if cuts else 0.0
            for k in range(cuts):
                part = os.path.join(seg_dir, f"h_{i:04d}_{k}.mp4")
                if fresh:
                    big = None
                    if cuts >= 3 and k == cuts // 2 and para.get("card_lines"):
                        big = para["card_lines"][0]
                    cap0 = para.get("card_title") if k == 0 else None
                    # even the hook alternates once the channel is photo-led:
                    # it is the busiest part of the video and the change of
                    # texture is what keeps it from reading as one long clip
                    if PHOTO_FIRST and pool.any() and k % 2 == 1:
                        mix_tally["photo"] += 1
                        img, zoom_out = pool.pick()
                        sgn = -1 if zoom_out else 1
                        photo_segment(img, cut_d, part, caption=cap0,
                                      zoom_out=zoom_out,
                                      drift=(sgn * rng.randint(40, 90),
                                             sgn * rng.randint(-45, 45)))
                    else:
                        mix_tally["stock"] += 1
                        budget[0] -= 1
                        src, start = broll.pick(cut_d)
                        broll_cut(src, start, cut_d, part,
                                  caption=cap0, big_word=big)
                parts.append(f"file '{part}'")
            if fresh:
                lst = os.path.join(seg_dir, f"h_{i:04d}.txt")
                with open(lst, "w") as f:
                    f.write("\n".join(parts) + "\n")
                run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                     "-i", lst, "-c", "copy", seg])
        else:
            # Body: a named player's photo up front, then the cut sequence.
            # A photo-led channel can carry this with no footage at all, so the
            # gate is "do we have ANY pictures", not "do we have clips".
            if fresh and (broll.any() or pool.any()):
                parts = []
                remaining = dur
                ptext = (str(para.get("text", "")) + " " +
                         str(para.get("card_title", ""))).lower()
                photo = None
                for key, path in pmap.items():
                    if key in ptext:
                        photo = path
                        break
                # don't repeat the same words in caption AND lower-third bubble
                cap = None if ov_kind == "lower3" else para.get("card_title")
                if photo and remaining > 5.5:
                    pd = min(6.0, remaining * 0.5)
                    pp = os.path.join(seg_dir, f"b_{i:04d}_photo.mp4")
                    try:
                        # 2.5D first: the subject and the background move at
                        # different speeds, which reads as depth. A flat
                        # ken-burns push is the fallback, not the goal.
                        try:
                            import parallax
                            parallax.segment(photo, pd, pp, caption=cap,
                                             font=FONT, esc=esc,
                                             crf=CRF_PHOTO, preset=PRESET,
                                             fps=FPS)
                        except Exception as pe:
                            print(f"[assemble] flat photo "
                                  f"({os.path.basename(photo)}: {pe})",
                                  flush=True)
                            photo_segment(photo, pd, pp, caption=cap)
                        parts.append(pp)
                        remaining -= pd
                    except Exception as e:
                        # a single unusable photo must never cost the video —
                        # give the time back to the b-roll and carry on
                        print(f"[assemble] photo skipped "
                              f"({os.path.basename(photo)}: {e})", flush=True)
                # Cut lengths come from the voice, not from a stopwatch: the
                # editor cuts where the speaker breathes and moves quicker
                # when the delivery pushes. Falls back to an even grid when
                # the narration cannot be read.
                seg_t0 = t0 + (dur - remaining)
                if RHYTHM:
                    import rhythm as RH
                    lens = RH.cut_points(RHYTHM[0], RHYTHM[1], seg_t0,
                                         remaining, BODY_CUT)
                else:
                    ncuts = max(1, round(remaining / BODY_CUT))
                    lens = [remaining / ncuts] * ncuts

                cut_t = seg_t0
                for k, cd in enumerate(lens):
                    bp = os.path.join(seg_dir, f"b_{i:04d}_{k}.mp4")
                    here, cut_t = cut_t, cut_t + cd

                    kind = choose_visual(here, k, rng, broll, motion, pool,
                                         budget)

                    if kind == "motion":
                        mix_tally["motion"] += 1
                        msrc, mstart = motion.pick(cd)
                        word = None
                        cap2 = None
                        if k == 0 and para.get("card_lines"):
                            word = para["card_lines"][0]
                        elif k == 0 and cap:
                            cap2 = cap
                        motion_cut(msrc, mstart, cd, bp,
                                   caption=cap2, big_word=word)
                        parts.append(bp)
                        continue

                    if kind == "photo":
                        mix_tally["photo"] += 1
                        img, zoom_out = pool.pick()
                        # the drift direction follows the zoom, so a push and
                        # the pull that follows it do not travel the same way
                        sgn = -1 if zoom_out else 1
                        drift = (sgn * rng.randint(40, 90),
                                 sgn * rng.randint(-45, 45))
                        cpng, chold = None, None
                        if (COLLAGE_ON and cd >= 2.4
                                and here - collage_state[0] >= COLLAGE_EVERY):
                            cpng, chold = build_collage(para, sec, i, k, cd,
                                                        seg_dir)
                            if cpng:
                                collage_state[0] = here
                                mix_tally["collage"] += 1
                        try:
                            photo_segment(img, cd, bp,
                                          caption=(cap if (k == 0 and not photo
                                                           and not cpng) else None),
                                          zoom_out=zoom_out, drift=drift,
                                          collage_png=cpng, collage_hold=chold)
                            parts.append(bp)
                            continue
                        except Exception as e:
                            # a broken image gives its time back to the footage
                            print(f"[assemble] still skipped "
                                  f"({os.path.basename(img)}: {e})", flush=True)
                            if not broll.any():
                                raise

                    mix_tally["stock"] += 1
                    budget[0] -= 1
                    zoom, slow = 1.0, 1.0
                    prev = broll.last()

                    # A cut-in: same footage, tighter framing. Reads as a
                    # second camera and costs nothing but a crop.
                    if k > 0 and prev and rng.random() < CUTIN_RATE:
                        src, d_src = prev
                        start = rng.uniform(0, max(0.0, d_src - cd - 0.2))
                        zoom = 1.28
                    else:
                        src, start = broll.pick(cd)

                    # Slow motion on a punch line, rationed: more than one
                    # every half minute and it stops being an accent.
                    if (SLOWMO and cd >= 2.0 and para.get("card_lines")
                            and k == 0 and seg_t0 - slow_state[0] >= SLOWMO_EVERY):
                        slow = SLOWMO
                        slow_state[0] = seg_t0

                    broll_cut(src, start, cd, bp,
                              caption=cap if (k == 0 and not photo) else None,
                              zoom=zoom, slow=slow)
                    parts.append(bp)
                if ov_kind:
                    try:
                        ov = make_overlay_png(ov_kind, para, sec, i)
                        first_d = ffdur(parts[0])
                        ov["at"] = (0.8 if ov_kind == "lower3"
                                    else max(0.9, min(first_d - 1.2, first_d * 0.4)))
                        tmp = parts[0].replace(".mp4", "_ov.mp4")
                        apply_overlay(parts[0], ov, tmp, i)
                        parts[0] = tmp
                    except Exception as e:
                        print(f"[assemble] overlay skipped ({e})")
                lst = os.path.join(seg_dir, f"b_{i:04d}.txt")
                with open(lst, "w") as f:
                    f.write("\n".join(f"file '{p}'" for p in parts) + "\n")
                run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                     "-i", lst, "-c", "copy", seg])
            elif fresh:
                card_segment(card, dur, i, seg)   # no-broll fallback only
        if i % 10 == 0:
            print(f"[assemble] segment {i+1}/{n}", flush=True)

    outro_files, OUTRO_D = make_outro(seg_dir)
    concat += [f"file '{p}'" for p in outro_files]

    listfile = os.path.join(seg_dir, "concat.txt")
    with open(listfile, "w") as f:
        f.write("\n".join(concat) + "\n")
    silent = os.path.join(BASE, "work", "video_noaudio.mp4")
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
         "-i", listfile, "-c", "copy", silent])

    # ---------- audio mix: narration (+gain) + sparse SFX + music bed ----------
    total = tm["total"] + INTRO_D + OUTRO_D
    narration = os.path.join(BASE, "work", "narration.wav")
    mixed_path = os.path.join(BASE, "work", "narration_sfx.wav")
    try:
        from pydub import AudioSegment
        # The owner's spec was narration +12 dB, music -18.5 dB — i.e. the two
        # sit 30.5 dB apart. Those numbers were set when narration came from the
        # quiet offline voice. ElevenLabs output already peaks near 0 dBFS, so
        # adding 12 dB on top clipped it and the result crackled. So: normalise
        # the narration to a safe peak, then place the music the same 30.5 dB
        # below it. The balance the owner asked for is preserved; the clipping
        # is not.
        narr = AudioSegment.from_wav(narration)
        head = NARR_PEAK - narr.max_dBFS
        print(f"[assemble] narration peak {narr.max_dBFS:.1f} dBFS "
              f"-> {NARR_PEAK:.1f} dBFS ({head:+.1f} dB)")
        narr = narr.apply_gain(head)
        mix = (AudioSegment.silent(duration=int(INTRO_D * 1000)) + narr +
               AudioSegment.silent(duration=int(OUTRO_D * 1000)))

        # transition SFX disabled (owner preference)

        # background music bed from owner's library
        tracks = media_lib("music", ("*.mp3", "*.wav", "*.m4a", "*.MP3", "*.WAV"))
        if tracks:
            rng.shuffle(tracks)
            bed = AudioSegment.silent(duration=0)
            ti = 0
            while len(bed) < total * 1000 + 2000:
                try:
                    bed += AudioSegment.from_file(tracks[ti % len(tracks)])
                except Exception as e:
                    print(f"[assemble] music track skipped: {e}")
                ti += 1
                if ti > 50:
                    break
            bed = bed[:int(total * 1000)]
            rel = MUSIC_GAIN - NARR_GAIN          # -30.5 dB under the narration
            bed = bed.apply_gain(NARR_PEAK + rel - bed.max_dBFS)
            bed = bed.fade_in(2500).fade_out(3500)
            mix = mix.overlay(bed)

        # A room tone under everything — crowd, distant whistles, stadium air.
        # It is mixed far below the voice on purpose: you should not be able
        # to point at it, you should only notice its absence.
        amb = media_lib("ambient", ("*.mp3", "*.wav", "*.m4a", "*.MP3", "*.WAV"))
        if amb:
            rng.shuffle(amb)
            room = AudioSegment.silent(duration=0)
            ai = 0
            while len(room) < total * 1000 + 2000 and ai < 40:
                try:
                    room += AudioSegment.from_file(amb[ai % len(amb)])
                except Exception as e:
                    print(f"[assemble] ambient track skipped: {e}")
                ai += 1
            room = room[:int(total * 1000)]
            if len(room) > 1000:
                room = room.apply_gain(NARR_PEAK - AMBIENT_UNDER - room.max_dBFS)
                room = room.fade_in(3000).fade_out(4000)
                mix = mix.overlay(room)
                print(f"[assemble] ambient bed: {len(amb)} files, "
                      f"{AMBIENT_UNDER:.0f} dB under narration")
            print(f"[assemble] music bed: {ti} track loops, "
                  f"{rel:.1f} dB under narration ({bed.max_dBFS:.1f} dBFS)")
        else:
            print("[assemble] no music library — narration only")
        mix.export(mixed_path, format="wav")
    except Exception as e:
        print(f"[assemble] audio mix fallback ({e})")
        mixed_path = narration

    final = os.path.join(BASE, "work", "final.mp4")
    run(["ffmpeg", "-y", "-v", "error", "-i", silent, "-i", mixed_path,
         "-map", "0:v", "-map", "1:a",
         "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
         "-af", "loudnorm=I=-14:TP=-1.5:LRA=11",
         "-movflags", "+faststart", "-shortest", final])
    tot = sum(mix_tally[k] for k in ("motion", "stock", "photo"))
    if tot:
        print(f"[assemble] kurgu karisimi: {mix_tally['stock']} stok video / "
              f"{mix_tally['photo']} fotograf / "
              f"{mix_tally['motion']} hareketli grafik  "
              f"(stok %{100 * mix_tally['stock'] / tot:.0f})  "
              f"{mix_tally['collage']} kolaj yazi")
        if PHOTO_FIRST:
            print(f"[assemble] farkli stok klip kullanildi: {len(broll.clips)}")
    print(f"[assemble] DONE -> work/final.mp4 ({ffdur(final)/60:.1f} min)")

if __name__ == "__main__":
    main()
