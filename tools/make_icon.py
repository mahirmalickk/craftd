"""Build Craftd's app icons from the official 16x16 pixel logo.

  craftd/assets/craftd-logo-16.png  the logo itself (the source: edit this one)
  craftd/assets/craftd.png          256x256, window and taskbar icon
  craftd/assets/craftd.ico          16-256 px, for Windows (and the future Craftd.exe)

Every size is a whole-number multiple of 16, scaled nearest-neighbour, so each logo pixel stays a sharp square.
Run from the project folder after changing the logo:  .venv\\Scripts\\python tools\\make_icon.py   (needs Pillow)"""

import sys
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parent.parent / "craftd" / "assets"
SOURCE = ASSETS / "craftd-logo-16.png"
ICO_SIZES = [16, 32, 48, 64, 128, 256]


def build(source: Path = SOURCE) -> None:
    logo = Image.open(source).convert("RGBA")
    if logo.size != (16, 16):
        raise SystemExit(f"{source.name} is {logo.size[0]}x{logo.size[1]}; the logo must be 16x16")
    logo.resize((256, 256), Image.NEAREST).save(ASSETS / "craftd.png")
    frames = [logo.resize((s, s), Image.NEAREST) for s in ICO_SIZES]
    frames[-1].save(ASSETS / "craftd.ico", sizes=[(s, s) for s in ICO_SIZES], append_images=frames[:-1])


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else SOURCE)
    print("Built craftd.png and craftd.ico from", SOURCE.name)
