#!/usr/bin/env python3
"""
channel.py — per-channel identity. Everything that must differ between
channels lives in channel.json at the repo root; code reads it from here.

Missing file or keys fall back to the Ketuil KNICKS (news) defaults.
"""
import json, os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DEFAULTS = {
    "name": "NY KNICKS DAILY",
    "outro_tag": "NEW KNICKS VIDEO EVERY DAY",
    "editorial": "news",          # news | documentary
    "clip_offset": 37,            # different per channel -> different scenes
    # pacing
    "hook_cut": 2.8,
    "body_cut": 3.4,
    "photo_zoom": 0.08,
    # overlays
    "overlay_kinds": ["speech", "lower3", "comic", "chat"],
    "overlay_every_sec": 25,
    "bounce": True,
    # audio
    "eleven_voice_id": "S9UjcNYIwfBOtZiDnIQT",
    "google_voice_early": "en-US-Chirp3-HD-Charon",
    "google_voice_late": "en-US-Chirp3-HD-Fenrir",
    # look
    "palette": {"primary": [245, 132, 38], "secondary": [0, 122, 200],
                "ink": [10, 16, 38]},
    "thumb_template": "thumb_base3.png",
    "thumb_words": ["BREAKING NEWS!", "URGENT UPDATE!", "EMERGENCY!", "PROBLEM!",
                    "SCARY!", "HUGE NEWS!", "CRAZY TRADE!", "IT'S OVER?!",
                    "SHOCKING!", None, None],
}

def load():
    cfg = dict(DEFAULTS)
    path = os.path.join(BASE, "channel.json")
    if os.path.exists(path):
        try:
            with open(path) as f:
                cfg.update(json.load(f))
        except Exception as e:
            print(f"[channel] channel.json unreadable ({e}) — using defaults")
    return cfg

CFG = load()

def get(key, default=None):
    return CFG.get(key, DEFAULTS.get(key, default))
