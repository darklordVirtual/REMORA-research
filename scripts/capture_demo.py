#!/usr/bin/env python3
# Author: Stian Skogbrott
# License: Apache-2.0
"""
Capture the HTML demo animation as a high-quality GIF using Playwright.
Records 44 seconds of animation at 12fps = ~528 frames.
"""
from __future__ import annotations
from pathlib import Path
from PIL import Image
import io

ROOT  = Path(__file__).parent.parent
HTML  = ROOT / "artifacts" / "demo" / "demo.html"
OUT   = ROOT / "artifacts" / "use-cases" / "remora_demo.gif"

# Animation timing matches the HTML (total ~44s)
FPS      = 8            # frames per second (lower = smaller file)
DURATION = 44           # seconds to capture (one full loop)
N_FRAMES = FPS * DURATION
WIDTH    = 1280
HEIGHT   = 720

def capture():
    from playwright.sync_api import sync_playwright

    print(f"Capturing {N_FRAMES} frames at {FPS}fps ({DURATION}s)...")
    frames = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page    = browser.new_page(viewport={"width": WIDTH, "height": HEIGHT})
        page.goto(f"file:///{HTML.as_posix()}")
        page.wait_for_timeout(800)  # let first scene render

        interval_ms = 1000 / FPS
        for i in range(N_FRAMES):
            if i % (FPS * 5) == 0:
                elapsed = i / FPS
                print(f"  Frame {i}/{N_FRAMES} ({elapsed:.0f}s / {DURATION}s)")
            png = page.screenshot(type="png")
            frames.append(Image.open(io.BytesIO(png)).convert("RGB"))
            # Advance time in the animation by waiting
            page.wait_for_timeout(int(interval_ms))

        browser.close()

    print(f"Assembling {len(frames)} frames into GIF...")
    # Convert to palette mode for smaller file size with good quality
    palette_frames = []
    for f in frames:
        # Resize for file size (960x540 = good quality under 10MB at 8fps)
        f_small = f.resize((960, 540), Image.LANCZOS)
        palette_frames.append(f_small.quantize(colors=256, method=Image.Quantize.MEDIANCUT))

    palette_frames[0].save(
        OUT,
        save_all=True,
        append_images=palette_frames[1:],
        duration=int(1000 / FPS),
        loop=0,
        optimize=True,
    )
    size_mb = OUT.stat().st_size / 1024 / 1024
    print(f"\nSaved: {OUT}")
    print(f"Size:  {size_mb:.1f} MB")
    print(f"Dimensions: 1024x576 @ {FPS}fps")


if __name__ == "__main__":
    capture()
