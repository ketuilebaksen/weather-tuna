#!/usr/bin/env python3
"""
tts.py — narration synthesis. Engine: ElevenLabs (primary) or Piper (fallback).

Env:
  ELEVEN_API_KEY   ElevenLabs key (if absent -> piper fallback)
  ELEVEN_VOICE_ID  optional explicit voice id
  ELEVEN_VOICE     voice name to search in "My Voices" (default: "alex")
  ELEVEN_MODEL     default: eleven_flash_v2_5
  TTS_ENGINE       force "eleven" or "piper"

Usage: python3 scripts/tts.py content/current/script.json
Output: work/audio/p_XXXX.(mp3|wav), work/narration.wav, work/timings.json
"""
import json, os, subprocess, sys, time, urllib.request

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PARA_PAUSE, SECT_PAUSE, SR = 0.55, 1.10, 44100
API = "https://api.elevenlabs.io/v1"
DEFAULT_VOICE_ID = "S9UjcNYIwfBOtZiDnIQT"  # Alex - Smooth, Balanced and Clear
try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import channel as CH
    DEFAULT_VOICE_ID = CH.get("eleven_voice_id", DEFAULT_VOICE_ID)
    CH_VOICE_EARLY = CH.get("google_voice_early", "en-US-Chirp3-HD-Charon")
    CH_VOICE_LATE = CH.get("google_voice_late", "en-US-Chirp3-HD-Fenrir")
except Exception:
    CH_VOICE_EARLY, CH_VOICE_LATE = "en-US-Chirp3-HD-Charon", "en-US-Chirp3-HD-Fenrir"

def ffdur(path):
    r = subprocess.run(["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                        "-of", "csv=p=0", path], capture_output=True, text=True)
    return float(r.stdout.strip())

def http(url, key, data=None, retries=4):
    import urllib.error
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "xi-api-key": key, "Content-Type": "application/json",
                "Accept": "application/json, audio/mpeg, */*",
                "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                               "AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/126.0.0.0 Safari/537.36")},
                data=json.dumps(data).encode() if data else None)
            with urllib.request.urlopen(req, timeout=180) as r:
                return r.read()
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode()[:400]
            except Exception:
                pass
            print(f"[tts] API error HTTP {e.code}: {body}", flush=True)
            if e.code in (400, 401, 403, 404, 422):
                raise SystemExit(f"[tts] fatal: HTTP {e.code} — {body}")
            if i == retries - 1:
                raise
            time.sleep(5 * (i + 1))
        except Exception as e:
            if i == retries - 1:
                raise
            print(f"[tts] retry {i+1}: {e}", flush=True)
            time.sleep(5 * (i + 1))

def pick_voice(key):
    """No API call needed: explicit id via env/file, else the baked-in Alex id."""
    vid = os.environ.get("ELEVEN_VOICE_ID", "").strip()
    if vid:
        return vid
    fpath = os.path.join(BASE, "assets", "voice_id.txt")
    if os.path.exists(fpath):
        v = open(fpath).read().strip()
        if v:
            return v
    return DEFAULT_VOICE_ID


GOOGLE_API = "https://texttospeech.googleapis.com/v1/text:synthesize"

def google_voice():
    """Pick the voice for this slot (two different hosts per day)."""
    import datetime
    slot = os.environ.get("SLOT", "").strip().lower()
    late = (slot == "late" if slot in ("early", "late")
            else datetime.datetime.utcnow().hour >= 16)
    default = CH_VOICE_LATE if late else CH_VOICE_EARLY
    return os.environ.get("GOOGLE_VOICE_LATE" if late else "GOOGLE_VOICE_EARLY",
                          os.environ.get("GOOGLE_VOICE", default))

def synth_google(text, out, key, voice):
    import base64, urllib.error
    body = {
        "input": {"text": text},
        "voice": {"languageCode": "-".join(voice.split("-")[:2]), "name": voice},
        "audioConfig": {"audioEncoding": "MP3", "sampleRateHertz": 44100,
                        "speakingRate": float(os.environ.get("TTS_RATE", "1.0"))},
    }
    for attempt in range(4):
        try:
            req = urllib.request.Request(
                f"{GOOGLE_API}?key={key}",
                data=json.dumps(body).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as r:
                data = json.load(r)
            with open(out, "wb") as f:
                f.write(base64.b64decode(data["audioContent"]))
            return
        except urllib.error.HTTPError as e:
            msg = ""
            try:
                msg = e.read().decode()[:300]
            except Exception:
                pass
            print(f"[tts] google HTTP {e.code}: {msg}", flush=True)
            if e.code in (400, 401, 403) or attempt == 3:
                raise SystemExit(f"[tts] google fatal: {e.code} {msg}")
            time.sleep(4 * (attempt + 1))
        except Exception as e:
            if attempt == 3:
                raise
            time.sleep(4 * (attempt + 1))

def synth_eleven(text, out, key, voice_id):
    body = {"text": text,
            "model_id": os.environ.get("ELEVEN_MODEL", "eleven_flash_v2_5"),
            "voice_settings": {"stability": 0.45, "similarity_boost": 0.75,
                                "style": 0.35, "speed": 1.0}}
    audio = http(f"{API}/text-to-speech/{voice_id}?output_format=mp3_44100_128",
                 key, body)
    with open(out, "wb") as f:
        f.write(audio)

def synth_piper(text, out):
    voice = os.path.join(BASE, "assets", "voice", "en-us-ryan-high.onnx")
    r = subprocess.run([sys.executable, "-m", "piper", "-m", voice, "-f", out,
                        "--length-scale", "1.05", "--sentence-silence", "0.35"],
                       input=text.encode(), capture_output=True, timeout=1800)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode()[-400:])

def main():
    with open(sys.argv[1]) as f:
        script = json.load(f)
    key = os.environ.get("ELEVEN_API_KEY", "").strip()
    gkey = os.environ.get("GOOGLE_TTS_KEY", "").strip()
    # channel.json decides the narrator; env can still override for a test run
    try:
        ch_engine = CH.get("tts_engine", "").strip().lower()
    except Exception:
        ch_engine = ""
    engine = (os.environ.get("TTS_ENGINE", "").strip().lower() or ch_engine
              or ("google" if gkey else ("eleven" if key else "piper")))
    # A channel's voice is its identity. If channel.json names an engine and
    # that engine cannot run, stop — publishing a video in the wrong (or the
    # robotic offline) voice is worse than publishing nothing. The owner gets
    # a "Run failed" notification and can fix the key.
    if ch_engine == "eleven" and engine == "eleven" and not key:
        sys.exit("[tts] fatal: channel.json asks for ElevenLabs but "
                 "ELEVEN_API_KEY is missing/empty — refusing to fall back "
                 "to a different voice.")
    if ch_engine == "google" and engine == "google" and not gkey:
        sys.exit("[tts] fatal: channel.json asks for Google but "
                 "GOOGLE_TTS_KEY is missing/empty — refusing to fall back.")
    if engine == "eleven" and not key:
        print("[tts] ELEVEN_API_KEY missing — falling back")
        engine = "google" if gkey else "piper"
    if engine == "google" and not gkey:
        print("[tts] GOOGLE_TTS_KEY missing — falling back")
        engine = "eleven" if key else "piper"
    ext = "wav" if engine == "piper" else "mp3"
    voice_id = pick_voice(key) if engine == "eleven" else None
    gvoice = google_voice() if engine == "google" else None
    print(f"[tts] engine: {engine}" + (f" voice: {gvoice}" if gvoice else ""))

    audio_dir = os.path.join(BASE, "work", "audio")
    os.makedirs(audio_dir, exist_ok=True)

    def sil(dur, path):
        subprocess.run(["ffmpeg", "-y", "-v", "quiet", "-f", "lavfi", "-i",
                        f"anullsrc=r={SR}:cl=mono", "-t", f"{dur:.3f}", path], check=True)
    sp, ss = os.path.join(audio_dir, "_sp.wav"), os.path.join(audio_dir, "_ss.wav")
    sil(PARA_PAUSE, sp); sil(PARA_PAUSE + SECT_PAUSE, ss)

    timings, concat, t, idx = [], [], 0.0, 0
    n_secs = len(script["sections"])
    for si, sec in enumerate(script["sections"]):
        n_p = len(sec["paragraphs"])
        for pi, para in enumerate(sec["paragraphs"]):
            out = os.path.join(audio_dir, f"p_{idx:04d}.{ext}")
            if not (os.path.exists(out) and os.path.getsize(out) > 1000):
                if engine == "google":
                    synth_google(para["text"].strip(), out, gkey, gvoice)
                elif engine == "eleven":
                    synth_eleven(para["text"].strip(), out, key, voice_id)
                else:
                    synth_piper(para["text"].strip(), out)
            dur = ffdur(out)
            last = (pi == n_p - 1)
            pause = 0.0 if (si == n_secs - 1 and last) else \
                    (PARA_PAUSE + SECT_PAUSE if last else PARA_PAUSE)
            timings.append({"idx": idx, "section": si, "para": pi,
                            "start": round(t, 3), "dur": round(dur + pause, 3)})
            concat.append(f"file '{out}'")
            if pause:
                concat.append(f"file '{ss if last else sp}'")
            t += dur + pause; idx += 1
            if idx % 5 == 0:
                print(f"[tts] {idx} paragraphs, {t/60:.1f} min", flush=True)

    lf = os.path.join(audio_dir, "concat.txt")
    with open(lf, "w") as f:
        f.write("\n".join(concat) + "\n")
    narr = os.path.join(BASE, "work", "narration.wav")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0",
                    "-i", lf, "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le",
                    narr], check=True)
    with open(os.path.join(BASE, "work", "timings.json"), "w") as f:
        json.dump({"total": round(t, 3), "items": timings}, f, indent=1)
    print(f"[tts] DONE — {t/60:.1f} min -> work/narration.wav")

if __name__ == "__main__":
    main()
