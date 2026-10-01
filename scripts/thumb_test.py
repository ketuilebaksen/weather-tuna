#!/usr/bin/env python3
"""
thumb_test.py — fast, standalone thumbnail test. No video, no upload.

Give it a title. It asks Claude who the story is really about and what the
thumbnail should show, downloads that player's best high-resolution photo, then
builds thumbnails with both methods so they can be compared side by side:

  A_hybrid : real photo cutout + AI background plate + text drawn by us
  B_gpt    : the real photo handed to gpt-image-1, which paints everything

Env:
  TITLE       the video title (required)
  VARIANTS    candidates per method (default 2)
  METHOD      both | a | b   (default both)
  ANTHROPIC_API_KEY, OPENAI_API_KEY / GEMINI_API_KEY

Output: work/test/
"""
import json, os, re, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import photos as PH
import thumb_ai
import thumb_hybrid

OUT = os.path.join(BASE, "work", "test")

BRIEF_PROMPT = """You design YouTube thumbnails for a New York Knicks channel.

Video title: "{title}"

Return ONE JSON object in a ```json block:
{{
 "person": "The full real name of the single person the story is most about - the one who must be on the thumbnail. A player, coach or executive. Just the name.",
 "person2": "The full real name of the second most important person, or empty string if the story is about one man only.",
 "thumb_word": "1-4 words, ALL CAPS, the single most dramatic beat of the title, usually with '!'. Examples: '3 DAYS DEADLINE!', 'HE'S GONE?!', '$212M GAMBLE!', 'BREAKING NEWS!'",
 "thumb_prompt": "One vivid sentence describing the thumbnail BACKGROUND for an image generator: arena mood, lighting and symbolic props that dramatise the story (a jumbotron countdown, an empty locker, embers, a tunnel of light, scattered contract paper). Describe the environment only - no people, no text.",
 "thumb_subject": "The figure described by role and uniform only, e.g. 'a determined point guard in a blue and orange number two jersey wearing a white headband'. Never a real name."
}}
Output only the JSON block."""


def brief(title):
    try:
        import anthropic
    except ImportError:
        return None
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    c = anthropic.Anthropic()
    r = c.messages.create(
        model=os.environ.get("MODEL", "claude-sonnet-4-5"), max_tokens=1200,
        messages=[{"role": "user", "content": BRIEF_PROMPT.format(title=title)}])
    text = "".join(b.text for b in r.content if getattr(b, "text", None))
    m = re.findall(r"```json\s*(.*?)```", text, re.S)
    raw = m[-1] if m else text[text.find("{"):text.rfind("}") + 1]
    return json.loads(raw)


def get_photo(name):
    """Best high-resolution, biggest-face photo of this person."""
    d = os.path.join(BASE, "work", "photos")
    os.makedirs(d, exist_ok=True)
    dest = os.path.join(d, re.sub(r"[^a-z0-9]+", "_", name.lower()) + ".jpg")
    if os.path.exists(dest) and os.path.getsize(dest) > 40000:
        return dest
    cands = PH.candidates(name + " basketball")
    best = None
    for k, (_, url, _a, _l, _t) in enumerate(cands[:4]):
        tmp = f"{dest}.c{k}"
        try:
            PH.download(url, tmp)
        except Exception as e:
            print(f"[thumb-test] photo dl fail #{k}: {e}")
            continue
        s = PH.face_score(tmp)
        print(f"[thumb-test]   candidate {k}: face score {s:.0f}")
        if best is None or s > best[0]:
            if best:
                os.remove(best[1])
            best = (s, tmp)
        else:
            os.remove(tmp)
        if s > 220:
            break
    if not best:
        return None
    os.replace(best[1], dest)
    try:
        from PIL import Image
        print(f"[thumb-test] photo: {name} {Image.open(dest).size}")
    except Exception:
        pass
    return dest


def main():
    title = os.environ.get("TITLE", "").strip()
    if not title:
        sys.exit("set TITLE")
    n = int(os.environ.get("VARIANTS", "2"))
    method = os.environ.get("METHOD", "style").lower()
    os.makedirs(OUT, exist_ok=True)

    b = brief(title) or {
        "person": "Jalen Brunson", "thumb_word": "BREAKING NEWS!",
        "thumb_prompt": "a jumbotron countdown clock over an empty Madison "
                        "Square Garden court, embers drifting in the light beams",
        "thumb_subject": "a determined guard in a blue and orange jersey"}
    print(f"[thumb-test] title : {title}")
    print(f"[thumb-test] person: {b['person']}")
    print(f"[thumb-test] word  : {b['thumb_word']}")
    print(f"[thumb-test] scene : {b['thumb_prompt']}", flush=True)
    with open(os.path.join(OUT, "brief.json"), "w") as f:
        json.dump({"title": title, **b}, f, indent=1, ensure_ascii=False)

    photo = get_photo(b["person"])
    photo2 = get_photo(b["person2"]) if b.get("person2") else None
    import shutil
    if photo:
        shutil.copy(photo, os.path.join(OUT, "source_photo.jpg"))
    else:
        print("[thumb-test] WARNING: no photo found for this person")
    if photo2:
        shutil.copy(photo2, os.path.join(OUT, "source_photo2.jpg"))

    made = 0
    for i in range(1, n + 1):
        if method in ("style", "both", "s"):
            try:
                import thumb_style
                bg = thumb_ai.generate_backdrop(
                    b["thumb_prompt"], os.path.join(OUT, f"plate_s{i}.png"))
                thumb_style.bigtype(b["thumb_word"], photo, photo2, bg,
                                    os.path.join(OUT, f"S_bigtype_{i}.jpg"))
                made += 1
            except Exception as e:
                print(f"[thumb-test] S#{i} failed: {e}")
        if method in ("a",):
            try:
                bg = thumb_ai.generate_backdrop(
                    b["thumb_prompt"], os.path.join(OUT, f"plate_{i}.png"))
                thumb_hybrid.compose(bg, photo, b["thumb_word"],
                                     os.path.join(OUT, f"A_hybrid_{i}.jpg"))
                made += 1
            except Exception as e:
                print(f"[thumb-test] A#{i} failed: {e}")
        if method in ("b",):
            try:
                raw = thumb_ai.generate_edit(
                    photo, b["thumb_prompt"], b["thumb_word"],
                    os.path.join(OUT, f"raw_B_{i}.png"))
                if raw:
                    thumb_ai.finish(raw, os.path.join(OUT, f"B_gpt_{i}.jpg"))
                    made += 1
            except Exception as e:
                print(f"[thumb-test] B#{i} failed: {e}")
        print(f"[thumb-test] round {i} done", flush=True)

    for f in os.listdir(OUT):                      # keep the folder light
        if f.startswith(("plate_", "raw_")):
            os.remove(os.path.join(OUT, f))
    print(f"[thumb-test] {made} thumbnails -> work/test/")
    if not made:
        sys.exit("no thumbnail produced — check the logs above")


if __name__ == "__main__":
    main()
