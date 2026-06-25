"""Generate a PDF from REMORA_Enterprise_Whitepaper.html.

Strategy: render each HTML .page section as a high-resolution screenshot
(device_scale_factor=3, ~288 dpi), then assemble them into a PDF where
each screenshot occupies exactly one A4 page — scaled to fit without
clipping. This gives exactly N PDF pages for N HTML .page sections.

Output: docs/whitepaper/REMORA_Enterprise_Whitepaper.pdf
"""

import io
import pathlib
import sys
import tempfile

from fpdf import FPDF
from PIL import Image
from playwright.sync_api import sync_playwright

HTML_PATH = (
    pathlib.Path(__file__).parent.parent
    / "docs"
    / "whitepaper"
    / "REMORA_Enterprise_Whitepaper.html"
)
PDF_PATH = HTML_PATH.with_suffix(".pdf")

# A4 dimensions in mm
A4_W_MM = 210.0
A4_H_MM = 297.0

# Screen pixels per mm at 96 dpi
PX_PER_MM = 96 / 25.4  # ≈ 3.78

# Device scale factor for high-res screenshots (3x ≈ 288 dpi)
SCALE = 3


def capture_pages(html_path: pathlib.Path) -> list[bytes]:
    """Return a list of PNG bytes, one per .page section."""
    file_url = html_path.resolve().as_uri()
    # Viewport matches exactly 210 mm at 96 dpi
    viewport_w = round(A4_W_MM * PX_PER_MM)  # 794 px
    viewport_h = round(A4_H_MM * PX_PER_MM)   # 1122 px

    pngs: list[bytes] = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        context = browser.new_context(
            viewport={"width": viewport_w, "height": viewport_h * 10},
            device_scale_factor=SCALE,
        )
        page = context.new_page()
        page.goto(file_url, wait_until="networkidle", timeout=30_000)

        # Wait for web fonts to load
        page.wait_for_timeout(800)

        sections = page.query_selector_all("section.page")
        print(f"Found {len(sections)} .page sections")

        for i, section in enumerate(sections, 1):
            box = section.bounding_box()
            if box is None:
                print(f"  WARNING: section {i} has no bounding box, skipping")
                continue

            # element.screenshot() automatically scrolls to the element and
            # captures exactly its rendered area — no clip-outside-viewport error.
            png = section.screenshot(type="png")
            pngs.append(png)
            h_mm = box["height"] / PX_PER_MM
            print(f"  Page {i:>2}: {box['width']:.0f}×{box['height']:.0f} px  "
                  f"({A4_W_MM:.0f}×{h_mm:.1f} mm)")

        browser.close()

    return pngs


def pngs_to_pdf(pngs: list[bytes], pdf_path: pathlib.Path) -> None:
    """Combine PNG bytes into a single PDF, one image per A4 page."""
    pdf = FPDF(unit="mm", format="A4")
    pdf.set_auto_page_break(auto=False)
    pdf.set_margins(0, 0, 0)

    with tempfile.TemporaryDirectory() as tmp:
        for idx, png_bytes in enumerate(pngs):
            img = Image.open(io.BytesIO(png_bytes))
            img_w, img_h = img.size  # in device pixels

            # Physical dimensions at SCALE× device pixel ratio
            # img_w / SCALE = logical px; then / PX_PER_MM = mm
            phys_w_mm = img_w / SCALE / PX_PER_MM
            phys_h_mm = img_h / SCALE / PX_PER_MM

            # Scale to fit A4 while preserving aspect ratio
            scale_x = A4_W_MM / phys_w_mm
            scale_y = A4_H_MM / phys_h_mm
            fit_scale = min(scale_x, scale_y)

            placed_w = phys_w_mm * fit_scale
            placed_h = phys_h_mm * fit_scale

            # Center on A4 page
            x_offset = (A4_W_MM - placed_w) / 2
            y_offset = (A4_H_MM - placed_h) / 2

            tmp_path = pathlib.Path(tmp) / f"page_{idx:03d}.png"
            tmp_path.write_bytes(png_bytes)

            pdf.add_page()
            pdf.image(str(tmp_path), x=x_offset, y=y_offset,
                      w=placed_w, h=placed_h)

    pdf.output(str(pdf_path))


def main():
    if not HTML_PATH.exists():
        print(f"ERROR: HTML not found at {HTML_PATH}", file=sys.stderr)
        sys.exit(1)

    print(f"Source: {HTML_PATH}")
    pngs = capture_pages(HTML_PATH)

    if not pngs:
        print("ERROR: no pages captured", file=sys.stderr)
        sys.exit(1)

    print(f"\nAssembling {len(pngs)}-page PDF …")
    pngs_to_pdf(pngs, PDF_PATH)

    size_kb = PDF_PATH.stat().st_size / 1024
    print(f"\nDone: {PDF_PATH}")
    print(f"      {len(pngs)} pages · {size_kb:.0f} KB")


if __name__ == "__main__":
    main()
