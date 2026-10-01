#!/usr/bin/env python3
"""
motion_lib.py — build the reusable motion-graphics library.

Remotion draws every frame in a browser, so it runs about 27x slower than real
time on a two-core runner. Animating 80% of a fifteen-minute video that way
would take five hours per video, which is impossible. So we pay for the motion
ONCE: this script renders a library of short animated plates, they get stored
as a GitHub Release, and from then on every video pulls from that library the
same way it pulls stock footage. Per-video cost: nothing.

The plates are deliberately backgrounds, not scenes — the middle of the frame
stays calm so the day's words can sit on top of them.

Usage:
  python3 scripts/motion_lib.py            # render into work/motion
Env:
  MOTION_COUNT     how many clips (default 24)
  MOTION_SECONDS   length of each clip (default 8)
  REMOTION_CHROME  browser to render with, if not the bundled one
"""
import json, os, subprocess, sys

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "work", "motion")
ROOT = os.path.join(BASE, "remotion")
FPS = 24

STYLES = ["sweep", "grid", "particles", "rings",
          "bars", "court", "halftone", "blobs"]


def palette():
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    try:
        import channel as CH
        p = CH.get("palette", {})
        return (list(p.get("primary", (245, 132, 38))),
                list(p.get("secondary", (0, 107, 182))),
                list(p.get("ink", (10, 16, 38))))
    except Exception:
        return [245, 132, 38], [0, 107, 182], [10, 16, 38]


def main():
    if not os.path.isdir(os.path.join(ROOT, "node_modules", "remotion")):
        sys.exit("[motion] remotion is not installed — run scripts/remotion_setup.py first")

    count = int(os.environ.get("MOTION_COUNT", "24"))
    seconds = float(os.environ.get("MOTION_SECONDS", "8"))
    frames = max(2, int(round(seconds * FPS))) - 1
    primary, secondary, ink = palette()
    os.makedirs(OUT, exist_ok=True)

    made, skipped = 0, 0
    for i in range(count):
        style = STYLES[i % len(STYLES)]
        seed = 101 + i * 37
        out = os.path.join(OUT, f"m_{style}_{seed}.mp4")
        if os.path.exists(out) and os.path.getsize(out) > 20000:
            skipped += 1
            continue

        props = os.path.join(OUT, "_props.json")
        with open(props, "w") as f:
            json.dump({"style": style, "seed": seed, "primary": primary,
                       "secondary": secondary, "ink": ink}, f)

        cmd = ["npx", "remotion", "render", "Motion", out,
               f"--props={props}", f"--frames=0-{frames}",
               # the config file is set up for the transparent hook overlay;
               # these plates are opaque video, so both must be overridden
               "--codec=h264", "--pixel-format=yuv420p", "--crf=20",
               "--concurrency=2", "--log=error"]
        chrome = os.environ.get("REMOTION_CHROME", "")
        if chrome:
            cmd.append(f"--browser-executable={chrome}")
        print(f"[motion] {i + 1}/{count}  {style} (seed {seed}) …", flush=True)
        try:
            subprocess.run(cmd, cwd=ROOT, check=True)
            made += 1
        except subprocess.CalledProcessError as e:
            # one bad plate must not cost the whole library
            print(f"[motion] skipped {style}/{seed}: {e}", flush=True)

    print(f"[motion] DONE — {made} new, {skipped} already there, "
          f"library at {OUT}")


if __name__ == "__main__":
    main()
