#!/usr/bin/env python3
"""
thumb_ai.py — AI-generated YouTube thumbnail (Google Gemini / Imagen).

The daily script writer supplies `thumb_prompt` (the scene) and `thumb_word`
(the punch phrase). This module wraps them in a fixed house-style prompt so
every thumbnail looks like the same channel, then asks the image model.

Env:
  GEMINI_API_KEY   (falls back to GOOGLE_TTS_KEY — same Google API key works
                    if "Generative Language API" is enabled on the project)
  IMAGE_MODEL      override model id

Returns the path of a 16:9 image, or None so the caller can fall back to the
template thumbnail. Never raises.
"""
import base64, json, os, sys, time, urllib.error, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API = "https://generativelanguage.googleapis.com/v1beta/models"
MODELS = [
    os.environ.get("IMAGE_MODEL", "").strip(),
    "gemini-3-pro-image-preview",
    "gemini-2.5-flash-image",
    "gemini-2.0-flash-preview-image-generation",
]

HOUSE_STYLE = (
    "Ultra high quality 16:9 YouTube thumbnail, cinematic sports-hype poster art. "
    "Photoreal basketball arena atmosphere: Madison Square Garden style crowd, "
    "dramatic stage lighting, glowing embers, volumetric light beams, subtle smoke, "
    "New York Knicks colour language (deep blue and vivid orange) with fiery accents. "
    "Bold depth of field, rim lighting on the subject, rich contrast, sharp focus, "
    "professional colour grading. Composition leaves the lower right area clear. "
    "No watermarks, no logos of other brands, no gibberish text anywhere."
)

def _key():
    return (os.environ.get("GEMINI_API_KEY", "").strip()
            or os.environ.get("GOOGLE_TTS_KEY", "").strip())

def build_prompt(scene, word=None, subject=None):
    parts = [HOUSE_STYLE]
    if subject:
        parts.append(f"Main subject: {subject}. Generic basketball player, "
                     "no real person's likeness, blue and orange New York uniform, "
                     "intense expression, upper body, left third of the frame.")
    parts.append(f"Scene: {scene}")
    if word:
        parts.append(
            f'Render exactly this text, large, in the lower right area: "{word}". '
            "Heavy extruded 3D display lettering, white and gold with a red outline "
            "and a soft glow. Spell it perfectly. No other text in the image.")
    else:
        parts.append("Do not render any text in the image.")
    return " ".join(parts)


# ----------------------------------------------------------------- OpenAI
OPENAI_URL = "https://api.openai.com/v1/images/generations"

def _openai_key():
    return os.environ.get("OPENAI_API_KEY", "").strip()

def _openai_call(prompt, key, timeout=300):
    body = {
        "model": os.environ.get("OPENAI_IMAGE_MODEL", "gpt-image-1"),
        "prompt": prompt[:3900],
        "size": os.environ.get("OPENAI_IMAGE_SIZE", "1536x1024"),   # 3:2, cropped to 16:9
        "quality": os.environ.get("OPENAI_IMAGE_QUALITY", "high"),
        "n": 1,
    }
    req = urllib.request.Request(
        OPENAI_URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    item = data["data"][0]
    if item.get("b64_json"):
        return base64.b64decode(item["b64_json"])
    with urllib.request.urlopen(item["url"], timeout=timeout) as r:   # url mode
        return r.read()

OPENAI_EDIT_URL = "https://api.openai.com/v1/images/edits"


def _multipart(fields, files):
    """Build a multipart/form-data body. files = [(field, filename, bytes)]."""
    boundary = "----knicksthumb7f3a9c2b1e"
    out = bytearray()
    for k, v in fields.items():
        out += (f"--{boundary}\r\nContent-Disposition: form-data; "
                f'name="{k}"\r\n\r\n{v}\r\n').encode()
    for field, fname, blob in files:
        ext = os.path.splitext(fname)[1].lower()
        ctype = "image/png" if ext == ".png" else "image/jpeg"
        out += (f"--{boundary}\r\nContent-Disposition: form-data; "
                f'name="{field}"; filename="{fname}"\r\n'
                f"Content-Type: {ctype}\r\n\r\n").encode()
        out += blob + b"\r\n"
    out += f"--{boundary}--\r\n".encode()
    return bytes(out), f"multipart/form-data; boundary={boundary}"


def generate_edit(photo_path, scene, word=None, out=None, timeout=420):
    """METHOD B — hand the real photo to gpt-image-1 and let it paint the whole
    thumbnail, text included. Keeps the real face as a reference; likeness and
    spelling are the model's call. Returns a path or None."""
    key = _openai_key()
    if not key or not photo_path or not os.path.exists(photo_path):
        print("[thumb-ai] edit mode needs OPENAI_API_KEY + a reference photo")
        return None
    out = out or os.path.join(BASE, "work", "thumbnail_edit.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    prompt = (
        "Turn the attached photograph of this basketball player into a "
        "high-impact 16:9 YouTube thumbnail. KEEP HIS FACE AND LIKENESS EXACTLY "
        "as in the photo — same face, same skin tone, same hair — but relight "
        "him dramatically and place him large on the left, cut out from his "
        "original background. " + HOUSE_STYLE + f" Scene behind him: {scene}")
    if word:
        prompt += (f' Render exactly this text, very large, in the right half: '
                   f'"{word}". Heavy extruded 3D display lettering, white and '
                   "gold with a red outline and a glow. Spell it perfectly, "
                   "no other text anywhere.")
    else:
        prompt += " Do not render any text."
    with open(photo_path, "rb") as f:
        blob = f.read()
    fields = {"model": "gpt-image-1", "prompt": prompt[:3900],
              "size": os.environ.get("OPENAI_IMAGE_SIZE", "1536x1024"),
              "quality": os.environ.get("OPENAI_IMAGE_QUALITY", "high"),
              "input_fidelity": "high", "n": "1"}
    body, ctype = _multipart(
        fields, [("image", os.path.basename(photo_path), blob)])
    req = urllib.request.Request(
        OPENAI_EDIT_URL, data=body,
        headers={"Content-Type": ctype, "Authorization": f"Bearer {key}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.load(r)
        item = data["data"][0]
        raw = (base64.b64decode(item["b64_json"]) if item.get("b64_json")
               else urllib.request.urlopen(item["url"], timeout=120).read())
        with open(out, "wb") as f:
            f.write(raw)
        print(f"[thumb-ai] edit-mode thumbnail ({os.path.getsize(out)//1024} KB)")
        return out
    except urllib.error.HTTPError as e:
        msg = ""
        try:
            msg = e.read().decode()[:300]
        except Exception:
            pass
        print(f"[thumb-ai] edit HTTP {e.code}: {msg}")
    except Exception as e:
        print(f"[thumb-ai] edit failed: {e}")
    return None


BACKDROP_STYLE = (
    "Ultra high quality 16:9 cinematic sports background plate for a YouTube "
    "thumbnail. Madison Square Garden style arena atmosphere, dramatic stage "
    "lighting, volumetric light beams, drifting embers, subtle haze, deep blue "
    "and vivid orange colour language with fiery accents, rich contrast, "
    "professional colour grading, shallow depth of field. "
    "ABSOLUTELY NO PEOPLE, no faces, no crowd close-ups, no text, no letters, "
    "no numbers, no logos, no watermarks. The left half must stay visually "
    "simple and slightly darker so a person can be composited on top of it."
)


def generate_backdrop(scene, out=None):
    """METHOD A, step 1 — an empty, people-free, text-free background plate.
    The real player photo and the punch word get composited on top of it."""
    out = out or os.path.join(BASE, "work", "backdrop.png")
    prompt = f"{BACKDROP_STYLE} Scene: {scene or 'an empty arena at tip-off'}. " \
             "Remember: no people and no text of any kind."
    okey = _openai_key()
    os.makedirs(os.path.dirname(out), exist_ok=True)
    if okey:
        try:
            raw = _openai_call(prompt, okey)
            with open(out, "wb") as f:
                f.write(raw)
            print(f"[thumb-ai] backdrop OK ({os.path.getsize(out)//1024} KB)")
            return out
        except Exception as e:
            print(f"[thumb-ai] backdrop failed: {e}")
    key = _key()
    for model in [m for m in MODELS if m]:
        try:
            raw = _call(model, prompt, key)
            with open(out, "wb") as f:
                f.write(raw)
            print(f"[thumb-ai] backdrop OK via {model}")
            return out
        except Exception as e:
            print(f"[thumb-ai] backdrop {model} failed: {e}")
    return None


def _call(model, prompt, key, timeout=180):
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"responseModalities": ["IMAGE"]},
    }
    req = urllib.request.Request(
        f"{API}/{model}:generateContent?key={key}",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        data = json.load(r)
    for cand in data.get("candidates", []):
        for part in cand.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                return base64.b64decode(inline["data"])
    raise RuntimeError("no image part in response")

def generate(scene, word=None, subject=None, out=None):
    if not scene:
        print("[thumb-ai] no scene prompt in script — skipping")
        return None
    prompt = build_prompt(scene, word, subject)
    out = out or os.path.join(BASE, "work", "thumbnail_ai.png")
    os.makedirs(os.path.dirname(out), exist_ok=True)

    # 1) OpenAI first when available — this is the look the owner picked
    okey = _openai_key()
    if okey:
        for attempt in range(2):
            try:
                raw = _openai_call(prompt, okey)
                with open(out, "wb") as f:
                    f.write(raw)
                print(f"[thumb-ai] generated with OpenAI "
                      f"{os.environ.get('OPENAI_IMAGE_MODEL', 'gpt-image-1')} "
                      f"({os.path.getsize(out)//1024} KB)")
                return out
            except urllib.error.HTTPError as e:
                msg = ""
                try:
                    msg = e.read().decode()[:250]
                except Exception:
                    pass
                print(f"[thumb-ai] OpenAI HTTP {e.code}: {msg}")
                if e.code in (400, 401, 403, 404):
                    break
                time.sleep(5)
            except Exception as e:
                print(f"[thumb-ai] OpenAI failed: {e}")
                time.sleep(4)

    # 2) Google Gemini / Imagen fallback
    key = _key()
    if not key:
        print("[thumb-ai] no OPENAI_API_KEY / GEMINI_API_KEY — skipping")
        return None

    for model in [m for m in MODELS if m]:
        for attempt in range(2):
            try:
                raw = _call(model, prompt, key)
                with open(out, "wb") as f:
                    f.write(raw)
                print(f"[thumb-ai] generated with {model} "
                      f"({os.path.getsize(out)//1024} KB)")
                return out
            except urllib.error.HTTPError as e:
                msg = ""
                try:
                    msg = e.read().decode()[:220]
                except Exception:
                    pass
                print(f"[thumb-ai] {model} HTTP {e.code}: {msg}")
                if e.code in (400, 401, 403, 404):
                    break              # wrong model / no access -> try next
                time.sleep(4)
            except Exception as e:
                print(f"[thumb-ai] {model} failed: {e}")
                time.sleep(3)
    print("[thumb-ai] all models failed — falling back to template")
    return None

def finish(path, out=None):
    """Crop/pad to exact 16:9, save a 4K master and a <2MB 1280x720 upload copy."""
    try:
        from PIL import Image
    except Exception:
        return path
    out = out or os.path.join(BASE, "work", "thumbnail.jpg")
    img = Image.open(path).convert("RGB")
    target = 16 / 9
    w, h = img.size
    if abs(w / h - target) > 0.01:      # centre-crop to 16:9
        if w / h > target:
            nw = int(h * target)
            img = img.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
        else:
            nh = int(w / target)
            img = img.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
    img = img.resize((3840, 2160), Image.LANCZOS)
    img.save(out, quality=95, subsampling=0)
    img.resize((1280, 720), Image.LANCZOS).save(
        out.replace(".jpg", "_yt.jpg"), quality=92)
    return out

if __name__ == "__main__":
    scene = sys.argv[1] if len(sys.argv) > 1 else "a torn contract burning on the court"
    word = sys.argv[2] if len(sys.argv) > 2 else "3 DAYS DEADLINE!"
    p = generate(scene, word)
    if p:
        print(finish(p))
