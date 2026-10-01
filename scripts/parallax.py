#!/usr/bin/env python3
"""
parallax.py — turn a flat photo into a 2.5D shot.

A still photo pushed in with a ken-burns zoom always looks like what it is: a
still photo. Real depth comes from the foreground and the background moving at
different speeds — that is what the eye reads as three dimensions.

So we cut the subject out of the photo, paint over the hole they leave, and
then move the two layers at different rates:

  background   drifts slowly, slightly blurred, scaled a little larger
  subject      drifts faster and grows faster, staying sharp

The cut-out is done with rembg (the same model the cover generator used), the
hole is filled with OpenCV's inpainting, and the motion itself is done in one
ffmpeg pass — no frame-by-frame Python, so it costs about the same as the old
ken-burns segment.

Everything here is best-effort. If the model cannot run, if the photo has no
clear subject, if anything at all goes wrong, the caller falls back to the
plain ken-burns move. A missing effect is a small loss; a failed render is a
big one.

Env:
  PARALLAX        "0" turns the effect off everywhere (default: on)
  PARALLAX_BG     background drift in pixels (default 26)
  PARALLAX_FG     subject drift in pixels (default 78)
  REMBG_MODEL     cut-out model (default u2net_human_seg)
"""
import math, os, subprocess

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
W, H = 1920, 1080
ON = os.environ.get("PARALLAX", "1") != "0"
BG_AMP = float(os.environ.get("PARALLAX_BG", "26"))
FG_AMP = float(os.environ.get("PARALLAX_FG", "78"))
MIN_SUBJECT = 0.02      # under 2% of the frame there is nothing to separate
MAX_SUBJECT = 0.92      # over 92% the "background" would be invented, not real


def _cache(img, tag):
    d = os.path.join(BASE, "work", "parallax")
    os.makedirs(d, exist_ok=True)
    stem = os.path.splitext(os.path.basename(img))[0]
    return os.path.join(d, f"{stem}_{tag}.png")


def layers(img):
    """(background_png, subject_png) — or None when the photo cannot be split.

    The subject keeps its position on the canvas, so the two layers line up
    exactly; only their motion differs later.
    """
    bg_p, fg_p = _cache(img, "bg"), _cache(img, "fg")
    if os.path.exists(bg_p) and os.path.exists(fg_p):
        return bg_p, fg_p

    from PIL import Image
    import numpy as np

    src = Image.open(img).convert("RGB")
    # work at a fixed, generous size: big enough to move inside a 1080p frame
    src = src.resize((2400, int(2400 * src.height / src.width)), Image.LANCZOS)

    from rembg import new_session, remove
    sess = new_session(os.environ.get("REMBG_MODEL", "u2net_human_seg"))
    cut = remove(src, session=sess).convert("RGBA")

    alpha = np.array(cut.split()[-1])
    share = float((alpha > 128).mean())
    if not (MIN_SUBJECT <= share <= MAX_SUBJECT):
        raise ValueError(f"subject covers {share:.0%} of the frame — not usable")

    # Paint over the subject so the background layer has no person-shaped hole.
    # The subject is about to slide across this area, so the fill only has to
    # survive a glance; TELEA inpainting is more than enough and is fast.
    import cv2
    rgb = np.array(src)[:, :, ::-1].copy()
    mask = cv2.dilate((alpha > 128).astype(np.uint8) * 255,
                      np.ones((15, 15), np.uint8), iterations=2)
    filled = cv2.inpaint(rgb, mask, 9, cv2.INPAINT_TELEA)
    Image.fromarray(filled[:, :, ::-1]).save(bg_p)
    cut.save(fg_p)
    return bg_p, fg_p


def segment(img, dur, out, caption=None, font=None, esc=None,
            crf="20", preset="fast", fps=24):
    """Render a 2.5D move over `img`. Raises if the photo cannot be split."""
    if not ON:
        raise RuntimeError("parallax disabled")
    bg_p, fg_p = layers(img)

    # One slow sweep across the shot: the layers travel in opposite directions,
    # which reads as depth far more strongly than either one moving alone.
    # The move is one-way — a sine would drift out and come back, which reads
    # as a wobble rather than a camera push. `p` runs 0..1 across the segment
    # and is centred so the shot is framed correctly at the halfway point.
    d = max(0.8, dur)
    p = f"(t/{d:.3f}-0.5)"
    bg_zoom = 1.06
    fg_zoom = 1.14

    bw, bh = int(W * 1.35), int(H * 1.35)
    vf = (
        f"[0:v]scale={bw}:{bh}:force_original_aspect_ratio=increase:"
        f"flags=lanczos,crop={bw}:{bh},"
        f"gblur=sigma=2.2,"
        f"crop={W}:{H}:"
        f"x='(iw-{W})/2 + {BG_AMP:.1f}*{p}':"
        f"y='(ih-{H})/2',"
        f"scale=iw*{bg_zoom}:-1,crop={W}:{H},fps={fps}[bg];"
        f"[1:v]scale={int(W*1.05)}:-1:flags=lanczos,fps={fps},"
        f"format=rgba[fg];"
        f"[bg][fg]overlay="
        f"x='(W-w)/2 - {FG_AMP:.1f}*{p}':"
        f"y='(H-h)/2 + 18*{p}':"
        f"format=auto,format=yuv420p"
    )
    if caption and font and esc:
        vf += (f",drawtext=fontfile='{font}':text='{esc(caption)}':"
               f"fontsize=62:fontcolor=white:x=(w-text_w)/2:y=h-150:"
               f"borderw=5:bordercolor=black@0.9:"
               f"shadowx=3:shadowy=3:shadowcolor=black@0.5")

    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-loop", "1", "-t", f"{dur:.3f}", "-i", bg_p,
         "-loop", "1", "-t", f"{dur:.3f}", "-i", fg_p,
         "-filter_complex", vf, "-t", f"{dur:.3f}", "-r", str(fps),
         "-c:v", "libx264", "-preset", preset, "-crf", crf,
         "-pix_fmt", "yuv420p", "-an", out], check=True)
    return out


def hero(img, dur, out, title=None, font=None, crf="19", preset="medium", fps=24):
    """Opening shot: the same 2.5D move, pushed harder, with the channel name.

    Used for the intro so a video opens on something alive rather than a card.
    """
    bg_p, fg_p = layers(img)
    d = max(0.8, dur)
    p = f"(t/{d:.3f}-0.5)"
    vf = (
        f"[0:v]scale={int(W*1.5)}:-1:flags=lanczos,gblur=sigma=3.5,"
        f"crop={W}:{H}:x='(iw-{W})/2 + 44*{p}':y='(ih-{H})/2',"
        f"eq=brightness=-0.06,fps={fps}[bg];"
        f"[1:v]scale={int(W*1.12)}:-1:flags=lanczos,fps={fps},format=rgba[fg];"
        f"[bg][fg]overlay=x='(W-w)/2 - 150*{p}':"
        f"y='(H-h)/2 + 26*{p}',"
        f"format=yuv420p"
    )
    if title and font:
        safe = "".join(c for c in str(title).upper()
                       if c.isalnum() or c in " -").strip()[:28]
        if safe:
            vf += (f",drawtext=fontfile='{font}':text='{safe}':"
                   f"fontsize=150:fontcolor=white:x=(w-text_w)/2:y=(h-text_h)/2:"
                   f"borderw=9:bordercolor=black@0.9:"
                   f"alpha='min(1,max(0,(t-0.25)/0.5))'")
    vf += f",fade=t=out:st={max(0.2, dur-0.5):.2f}:d=0.5"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-loop", "1", "-t", f"{dur:.3f}", "-i", bg_p,
         "-loop", "1", "-t", f"{dur:.3f}", "-i", fg_p,
         "-filter_complex", vf, "-t", f"{dur:.3f}", "-r", str(fps),
         "-c:v", "libx264", "-preset", preset, "-crf", crf,
         "-pix_fmt", "yuv420p", "-an", out], check=True)
    return out
