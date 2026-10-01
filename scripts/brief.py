#!/usr/bin/env python3
"""
brief.py — "kapak brief": the note the owner gets after every upload.

The video goes up scheduled and thumbnail-less; this writes everything needed
to design the cover by hand — the title, when it goes live, the Studio link,
who the episode is actually about, punch-word options and a scene idea.

Output: work/kapak_brief.md  (used as the body of a GitHub issue)
Usage:  python3 scripts/brief.py content/current/script.json content/current/meta.json
"""
import datetime, json, os, re, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "work", "kapak_brief.md")

try:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import channel as CH
    NAMES = CH.get("roster", []) or []
except Exception:
    NAMES = []
if not NAMES:
    NAMES = ["Jalen Brunson", "Karl-Anthony Towns", "OG Anunoby", "Mikal Bridges",
             "Josh Hart", "Miles McBride", "Deuce McBride", "Mitchell Robinson",
             "Mike Brown", "Leon Rose", "Tom Thibodeau", "Julius Randle",
             "RJ Barrett", "Immanuel Quickley", "Donte DiVincenzo"]


def mentions(text):
    """[(name, count)] for everyone the script actually talks about."""
    rows = []
    for n in NAMES:
        last = n.split()[-1].lower()
        c = len(re.findall(r"\b" + re.escape(last) + r"\b", text))
        if c:
            rows.append((n, c))
    rows.sort(key=lambda r: -r[1])
    return rows


def istanbul(pub):
    if not pub:
        return "hemen yayında"
    try:
        t = datetime.datetime.strptime(pub, "%Y-%m-%dT%H:%M:%SZ")
        t += datetime.timedelta(hours=3)
        return t.strftime("%d.%m.%Y %H:%M") + " (İstanbul)"
    except Exception:
        return pub


def word_options(script, title):
    """Punch-word candidates: the writer's own pick first, then safe patterns."""
    opts = []
    w = (script.get("thumb_word") or "").strip()
    if w:
        opts.append(w)
    caps = re.findall(r"\b[A-Z]{4,}!?\b", title)
    for c in caps:
        if c not in [o.upper() for o in opts] and c not in ("KNICKS", "NBA"):
            opts.append(c + ("" if c.endswith("!") else "!"))
    num = re.search(r"(\$?\d[\d.,]*\s*(?:M|K|MILLION|DAYS|YEARS|POINTS)?)", title,
                    re.I)
    if num:
        opts.append(num.group(1).upper() + "!")
    for extra in ("BREAKING NEWS!", "URGENT UPDATE!", "IT'S OVER?!"):
        if len(opts) < 5 and extra not in opts:
            opts.append(extra)
    return opts[:5]


def build(script, meta, result=None):
    result = result or {}
    text = json.dumps(script).lower()
    people = mentions(text)
    star = people[0][0] if people else "Jalen Brunson"
    second = people[1][0] if len(people) > 1 else "-"
    heads = [s.get("heading", "") for s in script.get("sections", [])][:8]

    lines = []
    lines.append(f"## {meta.get('title','(başlıksız)')}")
    lines.append("")
    lines.append(f"**Yayın saati:** {istanbul(result.get('publish_at') or meta.get('publish_at'))}  ")
    if result.get("studio"):
        lines.append(f"**Kapağı buradan yükle:** {result['studio']}  ")
    if result.get("url"):
        lines.append(f"**Video:** {result['url']}  ")
    lines.append("")
    lines.append("Video planlandı ve **kapaksız** yüklendi. Yayın saatinden önce "
                 "Studio'dan kapağı ekleyip kaydetmen yeterli.")
    lines.append("")
    lines.append("### Kapakta kim olmalı")
    if people:
        lines.append(f"- **Ana kişi: {star}** — metinde {people[0][1]} kez geçiyor")
    else:
        lines.append(f"- **Ana kişi: {star}** — metinde belirgin bir isim "
                     "öne çıkmadı, takım geneli bir kapak daha uygun")
    if second != "-":
        lines.append(f"- İkinci kişi: {second} ({people[1][1]} kez) — istersen arkada küçük dur")
    if len(people) > 2:
        lines.append("- Ayrıca geçenler: "
                     + ", ".join(f"{n} ({c})" for n, c in people[2:6]))
    lines.append("")
    lines.append("### Kapak yazısı (biri yeter, 1-3 kelime)")
    for o in word_options(script, meta.get("title", "")):
        lines.append(f"- `{o}`")
    lines.append("")
    if script.get("thumb_prompt"):
        lines.append("### Sahne fikri")
        lines.append(script["thumb_prompt"])
        lines.append("")
    lines.append("### Video neyi anlatıyor")
    for h in heads:
        lines.append(f"- {h}")
    lines.append("")
    first = ""
    for s in script.get("sections", []):
        for p in s.get("paragraphs", []):
            first = p.get("text", "")
            break
        if first:
            break
    if first:
        lines.append("### Açılış cümleleri")
        lines.append("> " + " ".join(first.split()[:70]) + " …")
        lines.append("")
    lines.append("---")
    lines.append("Kapağı yükledikten sonra bu notu kapatabilirsin.")
    return "\n".join(lines)


def main():
    script = json.load(open(sys.argv[1]))
    meta = json.load(open(sys.argv[2]))
    result = {}
    rp = os.path.join(BASE, "upload_result.json")
    if os.path.exists(rp):
        try:
            result = json.load(open(rp))
        except Exception:
            pass
    body = build(script, meta, result)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w") as f:
        f.write(body + "\n")
    print(body)


if __name__ == "__main__":
    main()
