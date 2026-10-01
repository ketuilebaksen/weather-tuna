#!/usr/bin/env python3
"""
sfx.py — generate transition sound effects programmatically (no licensing issues).
Creates work/sfx/whoosh.wav (fast riser-whoosh) and work/sfx/impact.wav (soft boom).
"""
import math, os, struct, wave

import numpy as np

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SR = 44100

def save(path, x):
    x = np.clip(x, -1, 1)
    with wave.open(path, "w") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())

def onepole_lowpass(x, cutoff_hz):
    """Time-varying one-pole lowpass; cutoff_hz is an array per sample."""
    y = np.zeros_like(x)
    dt = 1.0 / SR
    a = (2 * math.pi * cutoff_hz * dt) / (2 * math.pi * cutoff_hz * dt + 1)
    prev = 0.0
    for i in range(len(x)):
        prev = prev + a[i] * (x[i] - prev)
        y[i] = prev
    return y

def whoosh(dur=0.75):
    n = int(SR * dur)
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(n)
    t = np.linspace(0, 1, n)
    # rising then falling cutoff sweep 300Hz -> 6kHz -> 800Hz
    cutoff = 300 + 5700 * np.sin(np.pi * t) ** 2
    x = onepole_lowpass(noise, cutoff)
    env = np.sin(np.pi * t) ** 1.5 * np.minimum(1, t * 8)
    x = x * env
    return x / (np.max(np.abs(x)) + 1e-9) * 0.9

def impact(dur=0.5):
    n = int(SR * dur)
    t = np.arange(n) / SR
    f = 90 * np.exp(-t * 6) + 40
    phase = np.cumsum(2 * np.pi * f / SR)
    x = np.sin(phase) * np.exp(-t * 7)
    rng = np.random.default_rng(3)
    x += 0.15 * rng.standard_normal(n) * np.exp(-t * 25)
    return x / (np.max(np.abs(x)) + 1e-9) * 0.9

def main():
    out = os.path.join(BASE, "work", "sfx")
    os.makedirs(out, exist_ok=True)
    save(os.path.join(out, "whoosh.wav"), whoosh())
    save(os.path.join(out, "impact.wav"), impact())
    print("[sfx] whoosh + impact generated")

if __name__ == "__main__":
    main()
