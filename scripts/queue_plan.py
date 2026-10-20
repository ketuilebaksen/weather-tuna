#!/usr/bin/env python3
"""
queue_plan.py — decide which queued recordings still need a video.

content/queue holds one audio file per video. The file name is the title, and
also the identity: it becomes the Release tag. If a Release with that tag is
already published, the video exists and the file is skipped — so leaving old
recordings in the queue costs nothing and nothing is ever rendered twice.

Writes a GitHub Actions matrix to $GITHUB_OUTPUT:
  jobs   [{"path": ..., "title": ..., "tag": ...}]
  count  how many will actually render
"""
import json, os, re, subprocess, sys, urllib.parse

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
Q = os.path.join(BASE, "content", "queue")
AUDIO = (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")
# Bu kanalda ses disaridan geliyor (sahibin kendi ses klonu programi), o
# yuzden kuyruk SADECE ses dosyasi kabul ediyor. Yanlislikla birakilan bir
# .txt sessizce yok sayilir, render'i kirmaz.
TEXT = ()
MAX_JOBS = 20                     # GitHub'ın eşzamanlı iş sınırına saygı


def title_of(fn):
    stem = os.path.splitext(os.path.basename(fn))[0]
    stem = re.sub(r"[_]+", " ", stem)
    # başlık workflow içinde kabuk komutuna giriyor: tırnak, ters tırnak ve $
    # oradan geçemez, temizliyoruz
    stem = re.sub(r"[\"'`$\\\n\r]", " ", stem)
    return re.sub(r"\s+", " ", stem).strip()


def slug(title):
    s = title.lower()
    for a, b in (("ı", "i"), ("ğ", "g"), ("ü", "u"), ("ş", "s"),
                 ("ö", "o"), ("ç", "c"), ("İ", "i")):
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return ("v-" + s)[:90].rstrip("-") or "v-video"


def published():
    """Tags that already have a video, so we do not build them again."""
    try:
        out = subprocess.run(
            ["gh", "release", "list", "-L", "200",
             "--json", "tagName,publishedAt,createdAt", "-R", os.environ["GITHUB_REPOSITORY"]],
            capture_output=True, text=True, timeout=90)
        if out.returncode == 0:
            return {r["tagName"]: (r.get("publishedAt") or r.get("createdAt") or "")
                    for r in json.loads(out.stdout or "[]")}
        print(f"[queue] release listesi alinamadi: {out.stderr.strip()[:200]}")
    except Exception as e:
        print(f"[queue] release listesi alinamadi ({e})")
    return {}          # emin olamıyorsak render et — eksik video, fazladan videodan kötüdür


def pushed_at(path):
    """ISO time of the last commit touching this queue file (checkout is shallow,
    so we ask the API instead of git log)."""
    try:
        q = urllib.parse.quote(path)
        out = subprocess.run(
            ["gh", "api", f"repos/{os.environ['GITHUB_REPOSITORY']}/commits?path={q}&per_page=1",
             "-q", ".[0].commit.committer.date"],
            capture_output=True, text=True, timeout=60)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def main():
    if not os.path.isdir(Q):
        print("[queue] content/queue yok — yapacak is yok")
        return emit([])

    files = sorted(f for f in os.listdir(Q)
                   if f.lower().endswith(AUDIO + TEXT) and not f.startswith("."))
    if not files:
        print("[queue] kuyruk bos")
        return emit([])

    done = published()
    jobs, skipped = [], []
    for f in files:
        t = title_of(f)
        tag = slug(t)
        if tag in done:
            path = f"content/queue/{f}"
            when = pushed_at(path)
            # eski ayni adli video, ses dosyasi ondan SONRA yeniden gonderilmis
            if when and done[tag] and done[tag] < when:
                tag = (tag[:80].rstrip("-") + "-" + when[:10].replace("-", ""))
                if tag in done:
                    skipped.append(t)
                    continue
                print(f"[queue] ayni baslik yeniden gonderilmis -> {tag}")
            else:
                skipped.append(t)
                continue
        if any(j["tag"] == tag for j in jobs):
            print(f"[queue] ayni isimde ikinci dosya atlandi: {f}")
            continue
        jobs.append({"path": os.path.join("content", "queue", f),
                     "title": t, "tag": tag,
                     "kind": "audio"})

    if len(jobs) > MAX_JOBS:
        print(f"[queue] {len(jobs)} video var, bu turda ilk {MAX_JOBS} tanesi "
              f"kuruluyor; kalanlar icin tekrar calistir")
        jobs = jobs[:MAX_JOBS]

    for j in jobs:
        how = "metin -> ElevenLabs" if j["kind"] == "text" else "hazir ses"
        print(f"[queue] KURULACAK  {j['title']}  ({how})")
    for t in skipped:
        print(f"[queue] zaten var   {t}")
    print(f"[queue] {len(jobs)} yeni video, {len(skipped)} atlandi")
    emit(jobs)


def emit(jobs):
    out = os.environ.get("GITHUB_OUTPUT")
    if not out:
        print(json.dumps(jobs, ensure_ascii=False))
        return
    with open(out, "a") as f:
        f.write("jobs=" + json.dumps(jobs, ensure_ascii=False) + "\n")
        f.write(f"count={len(jobs)}\n")


if __name__ == "__main__":
    main()
