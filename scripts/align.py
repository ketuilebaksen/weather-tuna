#!/usr/bin/env python3
"""
align.py — build a video from the owner's own narration recording.

Drop an audio file into content/current/ (narration.mp3, .wav, .m4a …) and this
replaces the whole text-to-speech step. It listens to the recording, works out
exactly when every word is spoken, and writes the two files the rest of the
pipeline already expects:

  work/narration.wav   the audio, normalised to the pipeline's format
  work/timings.json    when each block of speech starts and how long it runs
  content/current/script.json   the block structure, so cuts follow the voice

There are NO subtitles. The owner's rule: the screen stays on the footage, and
only occasionally a short punch phrase appears, timed to the moment it is said.
So most blocks carry no on-screen text at all; every few blocks one short,
loud phrase is lifted out of what was actually said and handed to the editor.

Env:
  WHISPER_MODEL   faster-whisper model size (default: small)
  PUNCH_EVERY     how many blocks between punch phrases (default: 4)
"""
import glob, json, os, re, subprocess, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CUR = os.path.join(BASE, "content", "current")
WORK = os.path.join(BASE, "work")
SR = 44100
AUDIO_EXT = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".mp4", ".MP3", ".WAV", ".M4A")

# words that make a phrase feel like a headline rather than a fragment
STOP_START = {"and", "but", "so", "the", "a", "an", "of", "to", "in", "on", "at",
              "for", "with", "that", "this", "it", "is", "was", "as", "he", "his",
              "they", "their", "you", "we", "i", "who", "which", "when", "then"}

# filler that a recorded voice produces but a headline must never contain
FILLER = {"um", "uh", "yeah", "okay", "ok", "like", "know", "mean", "kind",
          "sort", "right", "guys", "anyway", "basically", "actually", "really",
          "just", "gonna", "wanna", "stuff", "thing", "things"}


def find_audio():
    # a queued render names the file it is responsible for; otherwise take
    # whatever the owner dropped into content/current
    pick = os.environ.get("AUDIO_FILE", "").strip()
    if pick:
        if not os.path.exists(pick):
            sys.exit(f"[align] AUDIO_FILE set to {pick} but that file is not there")
        return pick
    for f in sorted(os.listdir(CUR)):
        if f.lower().endswith(tuple(e.lower() for e in AUDIO_EXT)):
            return os.path.join(CUR, f)
    return None


def to_wav(src, dst):
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", src,
                    "-ar", str(SR), "-ac", "1", "-c:a", "pcm_s16le", dst],
                   check=True)
    return dst


def transcribe(wav):
    """[(start, end, text, [words])] — one entry per spoken sentence."""
    from faster_whisper import WhisperModel
    size = os.environ.get("WHISPER_MODEL", "small")
    print(f"[align] listening with faster-whisper '{size}' …", flush=True)
    model = WhisperModel(size, device="cpu", compute_type="int8")
    segments, info = model.transcribe(wav, language="en", word_timestamps=True,
                                      vad_filter=True)
    out = []
    for s in segments:
        words = [(w.start, w.end, w.word.strip()) for w in (s.words or [])]
        out.append((s.start, s.end, s.text.strip(), words))
    print(f"[align] {len(out)} spoken sentences, {info.duration/60:.1f} minutes")
    return out


def blocks(sentences, target_words=45):
    """Group sentences into edit blocks. A block is one 'paragraph' to the
    editor: one span of speech that gets its own run of cuts."""
    out, cur, n = [], [], 0
    for s in sentences:
        cur.append(s)
        n += len(s[2].split())
        if n >= target_words:
            out.append(cur); cur, n = [], 0
    if cur:
        if out and n < target_words * 0.4:      # tiny tail -> fold into previous
            out[-1] += cur
        else:
            out.append(cur)
    return out


def punch_phrase(words, max_words=4):
    """Lift a short, loud phrase out of what was actually said.

    Not a subtitle — a headline. It has to survive being read in half a second
    on someone's phone, so: never open or close on a filler word, never longer
    than four words, and prefer numbers and names, which are what actually make
    a viewer stop. If nothing in the block clears that bar, we return nothing
    and the screen simply stays on the footage — which is the default anyway.
    """
    toks = [re.sub(r"[^A-Za-z0-9$%.\-]", "", w) for _, _, w in words]
    best, best_score, best_i = None, 1, 0        # score must beat 1 to qualify
    for i in range(len(toks)):
        for L in range(2, max_words + 1):
            if i + L > len(toks):
                break
            span = toks[i:i + L]
            if any(not t for t in span):
                break
            low = [t.lower() for t in span]
            if low[0] in STOP_START or low[-1] in STOP_START:
                continue
            if any(t in FILLER for t in low):
                continue                         # a headline with "yeah" in it is not a headline
            has_num = any(re.search(r"\d", t) for t in span)
            has_name = any(t[:1].isupper() for t in span)
            score = sum(3 if re.search(r"\d", t) else
                        2 if t[:1].isupper() else
                        0 if t.lower() in STOP_START else 1
                        for t in span)
            if has_num and has_name:
                score += 2                       # "BRUNSON 539 POINTS"
            score -= sum(1 for t in low if t in STOP_START)   # filler inside dilutes it
            score -= abs(L - 3)                  # three words reads best
            if score > best_score:
                best, best_score, best_i = span, score, i
    if not best:
        return None, 0.0
    return " ".join(best).upper(), words[best_i][0]


# file names that clearly are not a title
GENERIC = {"narration", "audio", "ses", "record", "recording", "voice", "final",
           "output", "sound", "track", "kayit", "kayıt", "new recording", "untitled"}


def title_from(src):
    """The title of the video is the name of the audio file.

    Nothing else to fill in: name the file the way the video should be called,
    drop it in, done. If the file has a throwaway name (narration.mp3, ses.mp3)
    we fall back to meta.json, and failing that to the date — the owner writes
    the real title on YouTube by hand anyway, so this only needs to be a label
    good enough to tell two downloads apart.
    """
    stem = os.path.splitext(os.path.basename(src))[0]
    stem = re.sub(r"[_]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    clean = re.sub(r"[^a-z ]", "", stem.lower()).strip()
    if clean and clean not in GENERIC and len(stem) > 4:
        title = stem
    else:
        title = ""
        mp = os.path.join(CUR, "meta.json")
        if os.path.exists(mp):
            try:
                title = (json.load(open(mp)).get("title") or "").strip()
            except Exception:
                title = ""
        if not title or title.lower() in GENERIC:
            import datetime
            title = "Video " + datetime.date.today().strftime("%d.%m.%Y")

    # the rest of the pipeline reads meta.json, so keep it in step
    mp = os.path.join(CUR, "meta.json")
    meta = {}
    if os.path.exists(mp):
        try:
            meta = json.load(open(mp))
        except Exception:
            meta = {}
    meta["title"] = title
    meta.setdefault("description", "")
    meta.setdefault("tags", [])
    with open(mp, "w") as f:
        json.dump(meta, f, indent=1, ensure_ascii=False)
    print(f"[align] title: {title}")
    return title


def main():
    os.makedirs(WORK, exist_ok=True)
    src = find_audio()
    if not src:
        sys.exit("[align] no audio file in content/current — nothing to align")
    print(f"[align] narration: {os.path.basename(src)}")
    wav = to_wav(src, os.path.join(WORK, "narration.wav"))

    sentences = transcribe(wav)
    if not sentences:
        sys.exit("[align] no speech found in the recording")

    groups = blocks(sentences)
    punch_every = int(os.environ.get("PUNCH_EVERY", "4"))

    timings, sections, idx = [], [], 0
    SEC_SIZE = 6                       # blocks per section (drives chapter beats)
    for gi in range(0, len(groups), SEC_SIZE):
        chunk = groups[gi:gi + SEC_SIZE]
        paras = []
        for pi, g in enumerate(chunk):
            start = g[0][0]
            end = g[-1][1]
            text = " ".join(s[2] for s in g)
            words = [w for s in g for w in s[3]]

            card_title, card_lines = "", []
            if idx % punch_every == 0 and words:
                phrase, _at = punch_phrase(words)
                if phrase:
                    card_title, card_lines = phrase, [phrase]

            paras.append({"text": text, "card_title": card_title,
                          "card_lines": card_lines})
            timings.append({"idx": idx, "section": len(sections), "para": pi,
                            "start": round(start, 3),
                            "dur": round(max(0.8, end - start), 3)})
            idx += 1
        sections.append({"heading": "", "paragraphs": paras})

    total = round(sentences[-1][1], 3)
    with open(os.path.join(WORK, "timings.json"), "w") as f:
        json.dump({"total": total, "items": timings}, f, indent=1)

    title = title_from(src)
    script = {"title": title, "sections": sections}
    with open(os.path.join(CUR, "script.json"), "w") as f:
        json.dump(script, f, indent=1, ensure_ascii=False)

    n_punch = sum(1 for s in sections for p in s["paragraphs"] if p["card_title"])
    print(f"[align] {idx} edit blocks over {total/60:.1f} minutes, "
          f"{n_punch} punch phrases, {len(sections)} sections")


if __name__ == "__main__":
    main()
