#!/usr/bin/env python3
"""
rhythm.py — cut the picture to the voice instead of to a stopwatch.

Until now every body cut was the same length. Nobody notices consciously, but
within a minute the eye learns the beat and stops paying attention — that
regularity is what makes an edit feel machine-made. Real editors cut where the
speaker breathes, and they cut faster when the speaker pushes.

So we read the narration itself. The loudness envelope tells us two things:
where the gaps are (a pause is a low patch), and how hard the passage is being
delivered (a loud stretch wants a quicker cut). Both come out of the audio we
already have, which means this works for a recorded voice and a synthesised
one alike, with no extra input.

The one rule that must never break: the cut points inside a block have to add
up to exactly the block's duration, or the picture drifts away from the sound.
Everything here is built to preserve that.
"""
import os, wave

HOP = 0.05          # seconds per envelope sample
MIN_CUT = 1.6       # never cut shorter than this — flicker reads as a glitch
MAX_CUT = 7.5       # never hold longer than this in the body


def envelope(wav_path, hop=HOP):
    """Loudness per `hop` seconds, normalised to its own peak (0..1)."""
    import numpy as np
    with wave.open(wav_path, "rb") as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        raw = w.readframes(w.getnframes())
    a = np.frombuffer(raw, dtype=np.int16).astype(np.float32)
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    step = max(1, int(sr * hop))
    n = len(a) // step
    if n < 2:
        raise ValueError("narration too short to read a rhythm from")
    env = np.abs(a[:n * step].reshape(n, step)).mean(axis=1)
    peak = float(env.max()) or 1.0
    return env / peak, hop


def _target(env, hop, t0, dur, base):
    """How long a cut in this block wants to be.

    A passage delivered loudly is a passage being pushed; the picture should
    keep up. A quiet one is usually explanation, and explanation needs room.
    The scaling is deliberately gentle — 25% either way — because a cut length
    that swings wildly reads as an accident rather than as intent.
    """
    import numpy as np
    i0, i1 = int(t0 / hop), int((t0 + dur) / hop)
    block = env[i0:i1]
    if len(block) < 4:
        return base
    loud_here = float(block.mean())
    loud_all = float(env.mean()) or 1e-6
    ratio = loud_here / loud_all
    scale = min(1.25, max(0.75, 1.0 / max(0.6, min(1.6, ratio))))
    return base * scale


def cut_points(env, hop, t0, dur, base_cut):
    """Cut lengths for one block: they sum to exactly `dur`.

    Candidate points sit near an ideal grid, then slide to the quietest moment
    within half a cut of it — that is the pause the speaker actually left.
    """
    import numpy as np
    target = _target(env, hop, t0, dur, base_cut)
    n = max(1, int(round(dur / max(MIN_CUT, min(MAX_CUT, target)))))
    if n == 1 or dur < MIN_CUT * 2:
        return [dur]

    ideal = [dur * k / n for k in range(1, n)]
    window = max(1, int((target * 0.45) / hop))
    picked = []
    for want in ideal:
        centre = int((t0 + want) / hop)
        lo, hi = max(0, centre - window), min(len(env) - 1, centre + window)
        if hi <= lo:
            picked.append(want)
            continue
        seg = env[lo:hi]
        quiet = lo + int(np.argmin(seg))          # the gap between phrases
        at = quiet * hop - t0
        # keep the moved point sane: it must stay inside the block and must
        # not collapse the neighbouring cut below the minimum
        prev = picked[-1] if picked else 0.0
        at = min(max(at, prev + MIN_CUT), dur - MIN_CUT)
        picked.append(at)

    picked = sorted(set(round(p, 3) for p in picked if 0 < p < dur))
    lens, last = [], 0.0
    for p in picked:
        if p - last >= MIN_CUT:
            lens.append(round(p - last, 3))
            last = p
    tail = round(dur - last, 3)
    if tail < MIN_CUT and lens:
        lens[-1] = round(lens[-1] + tail, 3)      # fold a stub into the one before
    else:
        lens.append(tail)
    return [l for l in lens if l > 0.05]


def load(base_dir):
    """(env, hop) for work/narration.wav, or None when it cannot be read."""
    p = os.path.join(base_dir, "work", "narration.wav")
    if not os.path.exists(p):
        return None
    try:
        env, hop = envelope(p)
        print(f"[rhythm] narration envelope: {len(env)} samples "
              f"({len(env) * hop / 60:.1f} min)", flush=True)
        return env, hop
    except Exception as e:
        print(f"[rhythm] falling back to fixed cut length ({e})", flush=True)
        return None
