#!/usr/bin/env python3
"""
pick_player_pool.py — which player's footage does this video need?

NFL Tunnel tells one player's story per video, and the owner keeps a separate
Release of footage for each player, tagged "oyuncu-<name>":

    oyuncu-patrick-mahomes
    oyuncu-josh-allen

A video can also be about a whole team, tagged "takim-san-francisco-49ers".
Both prefixes work the same way.

This reads the list of Release tags on stdin, reads the video's script and
title, and prints the one tag whose subject the script is actually about.
Prints nothing when no player pool fits — the workflow then falls back to the
general "broll" pools.

Matching is on the surname, because a narrator says "Mahomes" far more often
than "Patrick Mahomes". The full name counts extra, so a script that is about
Josh Allen but mentions Mahomes in passing still picks Allen.

Usage:
  gh release list ... | python3 scripts/pick_player_pool.py script.json "Title"
"""
import json
import re
import sys

# Bir video tek bir oyuncuyu anlatabilir ("oyuncu-patrick-mahomes") ya da bir
# takimi ("takim-san-francisco-49ers"). Ikisi de ayni sekilde calisiyor:
# havuz, metinde en cok gecen isme gore seciliyor.
PREFIXES = ("oyuncu-", "takim-")


def _strip_prefix(tag):
    low = tag.lower()
    for p in PREFIXES:
        if low.startswith(p):
            return tag[len(p):]
    return ""


def script_text(path, title):
    parts = [title or ""]
    try:
        with open(path, encoding="utf-8") as f:
            s = json.load(f)
        parts.append(str(s.get("title", "")))
        for sec in s.get("sections", []):
            parts.append(str(sec.get("heading", "")))
            for p in sec.get("paragraphs", []):
                parts.append(str(p.get("text", "")))
                parts.append(str(p.get("card_title", "")))
    except Exception as e:
        print(f"[pool] metin okunamadi ({e}), sadece baslik kullaniliyor",
              file=sys.stderr)
    return " ".join(parts).lower()


def words_of(tag):
    name = _strip_prefix(tag)
    return [w for w in re.split(r"[-_.\s]+", name.lower()) if w]


def score(tag, text):
    words = words_of(tag)
    if not words:
        return 0
    surname = words[-1]
    if len(surname) < 3:            # "jr", "ii" alone would match everything
        surname = words[-2] if len(words) > 1 else surname
    hits = len(re.findall(r"\b" + re.escape(surname) + r"\b", text))
    full = len(re.findall(r"\b" + r"\s+".join(map(re.escape, words)) + r"\b",
                          text)) if len(words) > 1 else 0
    return hits + 3 * full


def pick(tags, text):
    cands = [t.strip() for t in tags
             if t.strip().lower().startswith(PREFIXES)]
    best, best_s = "", 0
    for t in cands:
        s = score(t, text)
        print(f"[pool] {t:32} puan {s}", file=sys.stderr)
        if s > best_s:
            best, best_s = t, s
    return best


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "content/current/script.json"
    title = sys.argv[2] if len(sys.argv) > 2 else ""
    tags = sys.stdin.read().splitlines()
    chosen = pick(tags, script_text(path, title))
    if chosen:
        print(chosen)


if __name__ == "__main__":
    main()
