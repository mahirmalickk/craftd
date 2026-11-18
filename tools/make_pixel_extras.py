"""Build craftd/fonts/craftd-pixel-extras.ttf: UI symbols that Monocraft lacks (it was first made for Mojangles),
drawn on the same 9-pixel grid (7px capitals) so they blend in.

Dev tool only (needs fontTools):  python tools/make_pixel_extras.py
"""

from pathlib import Path

from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen

UPM = 900
PX = UPM // 9  # one font pixel, same proportions as Mojangles (2048 units / 9 px)
FAMILY = "Craftd Pixel Extras"

# char: (bottom row's y in font pixels, rows top->bottom). "#" = filled.
GLYPHS: dict[str, tuple[int, list[str]]] = {
    "!": (0, ["#", "#", "#", "#", "#", ".", "#"]),
    '"': (5, ["#.#", "#.#"]),
    "#": (0, [".#.#.", ".#.#.", "#####", ".#.#.", "#####", ".#.#.", ".#.#."]),
    "$": (0, ["..#..", ".####", "#....", ".###.", "....#", "####.", "..#.."]),
    "%": (0, ["#...#", "#..#.", "...#.", "..#..", ".#...", ".#..#", "#...#"]),
    "&": (0, ["..#..", ".#.#.", "..#..", ".##.#", "#..#.", "#..#.", ".##.#"]),
    "'": (5, ["#", "#"]),
    "(": (0, ["..##", ".#..", "#...", "#...", "#...", ".#..", "..##"]),
    ")": (0, ["##..", "..#.", "...#", "...#", "...#", "..#.", "##.."]),
    "*": (2, ["#..#", ".##.", "#..#"]),
    "+": (1, ["..#..", "..#..", "#####", "..#..", "..#.."]),
    "-": (3, ["#####"]),
    "/": (0, ["....#", "...#.", "...#.", "..#..", ".#...", ".#...", "#...."]),
    ":": (0, ["#", ".", ".", ".", "#"]),
    ";": (-1, ["#", ".", ".", ".", "#", "#"]),
    "<": (0, ["...#", "..#.", ".#..", "#...", ".#..", "..#.", "...#"]),
    "=": (1, ["#####", ".....", "#####"]),
    ">": (0, ["#...", ".#..", "..#.", "...#", "..#.", ".#..", "#..."]),
    "?": (0, [".###.", "#...#", "....#", "...#.", "..#..", ".....", "..#.."]),
    "@": (0, [".####.", "#....#", "#.##.#", "#.##.#", "#.####", "#.....", ".####."]),
    "[": (0, ["###", "#..", "#..", "#..", "#..", "#..", "###"]),
    "\\": (0, ["#....", ".#...", ".#...", "..#..", "...#.", "...#.", "....#"]),
    "]": (0, ["###", "..#", "..#", "..#", "..#", "..#", "###"]),
    "^": (4, ["..#..", ".#.#.", "#...#"]),
    "_": (-1, ["#####"]),
    "`": (5, ["#.", ".#"]),
    "{": (0, ["..##", ".#..", ".#..", "#...", ".#..", ".#..", "..##"]),
    "|": (-1, ["#", "#", "#", "#", "#", "#", "#", "#"]),
    "}": (0, ["##..", "..#.", "..#.", "...#", "..#.", "..#.", "##.."]),
    "~": (5, [".##..#", "#..##."]),
    # UI symbols Craftd uses
    "·": (3, ["#"]),
    "•": (2, [".##.", "####", "####", ".##."]),
    "…": (0, ["#.#.#"]),
    "–": (3, ["######"]),
    "—": (3, ["########"]),
    "‘": (5, ["#", "#"]),
    "’": (5, ["#", "#"]),
    "“": (5, ["#.#", "#.#"]),
    "”": (5, ["#.#", "#.#"]),
    "↓": (0, ["..#..", "..#..", "..#..", "#.#.#", ".###.", "..#.."]),
    "→": (1, ["...#.", "....#", "#####", "....#", "...#."]),
    "←": (1, [".#...", "#....", "#####", "#....", ".#..."]),
    "↗": (1, ["..###", "...##", "..#.#", ".#...", "#...."]),
    "♥": (1, [".#.#.", "#####", "#####", ".###.", "..#.."]),
    "✓": (1, ["....#", "...#.", "#.#..", ".#..."]),
    "⚙": (0, [".#.#.#.", "#######", ".##.##.", "###.###", ".##.##.", "#######", ".#.#.#."]),
    "▣": (0, ["#######", "#.....#", "#.###.#", "#.###.#", "#.###.#", "#.....#", "#######"]),
    "⟐": (1, ["..#..", ".#.#.", "#...#", ".#.#.", "..#.."]),
    "●": (1, [".###.", "#####", "#####", "#####", ".###."]),
    "×": (1, ["#...#", ".#.#.", "..#..", ".#.#.", "#...#"]),
    "⚠": (0, ["...#...", "..#.#..", "..#.#..", ".#.#.#.", ".#...#.", "#..#..#", "#######"]),
}


def glyph_for(bottom: int, rows: list[str]):
    pen = TTGlyphPen(None)
    height = len(rows)
    for r, row in enumerate(rows):
        y0 = (bottom + height - 1 - r) * PX
        x = 0
        while x < len(row):  # one rectangle per horizontal run of pixels
            if row[x] == "#":
                start = x
                while x < len(row) and row[x] == "#":
                    x += 1
                pen.moveTo((start * PX, y0))
                pen.lineTo((start * PX, y0 + PX))
                pen.lineTo((x * PX, y0 + PX))
                pen.lineTo((x * PX, y0))
                pen.closePath()
            else:
                x += 1
    width = max(len(r) for r in rows)
    return pen.glyph(), (width + 1) * PX


def build(out: Path) -> None:
    order = [".notdef"]
    cmap, glyphs, metrics = {}, {".notdef": TTGlyphPen(None).glyph()}, {".notdef": (5 * PX, 0)}
    for ch, (bottom, rows) in GLYPHS.items():
        name = f"uni{ord(ch):04X}"
        glyph, advance = glyph_for(bottom, rows)
        order.append(name)
        cmap[ord(ch)] = name
        glyphs[name] = glyph
        metrics[name] = (advance, 0)
    fb = FontBuilder(UPM, isTTF=True)
    fb.setupGlyphOrder(order)
    fb.setupCharacterMap(cmap)
    fb.setupGlyf(glyphs)
    fb.setupHorizontalMetrics(metrics)
    ascent, descent = 7 * PX, -2 * PX  # matches Mojangles (1592 / -455 of 2048)
    fb.setupHorizontalHeader(ascent=ascent, descent=descent)
    fb.setupNameTable({"familyName": FAMILY, "styleName": "Regular",
                       "copyright": "Drawn for Craftd by Claude (Anthropic) and Mahir Malick"})
    fb.setupOS2(sTypoAscender=ascent, sTypoDescender=descent, usWinAscent=ascent, usWinDescent=-descent)
    fb.setupPost()
    out.parent.mkdir(parents=True, exist_ok=True)
    fb.save(str(out))


if __name__ == "__main__":
    target = Path(__file__).resolve().parent.parent / "craftd" / "fonts" / "craftd-pixel-extras.ttf"
    build(target)
    print(f"Wrote {target} ({len(GLYPHS)} glyphs)")
