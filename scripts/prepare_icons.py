"""Generate PNG (all platforms) and ICNS (macOS bundle icon) from assets/appIcon.ico."""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[misc, assignment]

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
ICO_PATH = ASSETS / "appIcon.ico"
PNG_PATH = ASSETS / "appIcon.png"
ICNS_PATH = ASSETS / "appIcon.icns"

# macOS iconutil .iconset layout (base size -> filename).
MAC_ICON_SIZES: tuple[tuple[int, str], ...] = (
    (16, "icon_16x16.png"),
    (32, "icon_16x16@2x.png"),
    (32, "icon_32x32.png"),
    (64, "icon_32x32@2x.png"),
    (128, "icon_128x128.png"),
    (256, "icon_128x128@2x.png"),
    (256, "icon_256x256.png"),
    (512, "icon_256x256@2x.png"),
    (512, "icon_512x512.png"),
    (1024, "icon_512x512@2x.png"),
)


def _load_source_image() -> Image.Image:
    if Image is None:
        raise RuntimeError("Pillow is required. Install with: pip install pillow")
    if not ICO_PATH.is_file():
        raise FileNotFoundError(f"Missing icon source: {ICO_PATH}")
    with Image.open(ICO_PATH) as img:
        return img.convert("RGBA")


def write_png(image: Image.Image) -> Path:
    largest = image.resize((512, 512), Image.Resampling.LANCZOS)
    ASSETS.mkdir(parents=True, exist_ok=True)
    largest.save(PNG_PATH, format="PNG")
    return PNG_PATH


def write_icns(image: Image.Image) -> Path:
    if sys.platform != "darwin":
        raise RuntimeError("ICNS generation requires macOS (iconutil).")

    iconset = ASSETS / "appIcon.iconset"
    if iconset.exists():
        shutil.rmtree(iconset)
    iconset.mkdir(parents=True)

    for size, filename in MAC_ICON_SIZES:
        resized = image.resize((size, size), Image.Resampling.LANCZOS)
        resized.save(iconset / filename, format="PNG")

    if ICNS_PATH.exists():
        ICNS_PATH.unlink()

    subprocess.run(
        ["iconutil", "-c", "icns", str(iconset), "-o", str(ICNS_PATH)],
        check=True,
    )
    shutil.rmtree(iconset)
    return ICNS_PATH


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--macos",
        action="store_true",
        help="Also build assets/appIcon.icns (macOS only).",
    )
    args = parser.parse_args()

    image = _load_source_image()
    png = write_png(image)
    print(f"Wrote {png.relative_to(ROOT)}")

    if args.macos:
        icns = write_icns(image)
        print(f"Wrote {icns.relative_to(ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
