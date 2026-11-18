"""Craftd always uses Monocraft; the extras font fills in the few symbols Monocraft doesn't have."""

import ast
import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from fontTools.ttLib import TTCollection, TTFont  # noqa: E402
from PySide6.QtGui import QFont, QFontDatabase  # noqa: E402
from PySide6.QtWidgets import QApplication, QComboBox, QFontComboBox  # noqa: E402

from craftd.gui import theme  # noqa: E402
from craftd.gui.dialogs import SettingsDialog  # noqa: E402
from craftd.gui.main_window import MainWindow  # noqa: E402

PKG = Path(theme.__file__).resolve().parent.parent
EMOJI_OK = {"🎉", "📌"}  # drawn by Windows' color emoji font on purpose


def test_monocraft_is_the_font_and_text_is_crisp(app):
    QApplication.instance() or QApplication([])
    win = MainWindow(app)
    assert win.themer.family == "Monocraft" and win.themer.pixel
    q = QApplication.instance()
    css = q.styleSheet()
    assert 'font-family: "Monocraft"' in css
    # Regular everywhere: no bold in the stylesheet, in fonts set in code, or in rich text
    assert set(re.findall(r"font-weight: (\d+)", css)) == {"400"}
    assert theme.weight("demibold") == QFont.Weight.Normal and theme.weight("bold") == QFont.Weight.Normal
    assert theme.strong("Survival 26.3") == "Survival 26.3"
    assert theme.px("base") == 18 and theme.px("title") == 36  # 2x and 4x the 9px grid
    assert q.font().styleStrategy() & QFont.StyleStrategy.NoAntialias
    assert QFont.substitutes("Monocraft") == ["craftd pixel extras"]
    assert theme.mono_font().family() == "Monocraft"


def test_monocraft_has_no_ligatures():
    """Ligatures would turn things like "->" or "..." in file names and versions into other glyphs."""
    fonts = TTCollection(PKG / "fonts" / "monocraft" / "Monocraft-no-ligatures.ttc").fonts
    assert {f["name"].getDebugName(2) for f in fonts} >= {"Regular", "Bold"}
    assert not any("GSUB" in f for f in fonts)


def test_settings_has_no_font_options(app):
    QApplication.instance() or QApplication([])
    win = MainWindow(app)
    dlg = SettingsDialog(app, win.themer, win)
    assert not dlg.findChildren(QFontComboBox)
    families = set(QFontDatabase.families())
    for combo in dlg.findChildren(QComboBox):  # no combo lists fonts
        assert not {combo.itemText(i) for i in range(combo.count())} & families
    assert [dlg.size.itemText(i) for i in range(dlg.size.count())] == ["Default", "Large"]
    dlg.reject()


def test_license_files_travel_with_the_font():
    folder = PKG / "fonts" / "monocraft"
    assert {p.name for p in folder.iterdir()} >= {"Monocraft-no-ligatures.ttc", "OFL.txt", "README.txt"}
    assert "SIL Open Font License" in (folder / "OFL.txt").read_text()


def test_every_character_in_the_ui_is_covered():
    """Any non-ASCII character in Craftd's strings must exist in Monocraft or the extras font."""
    covered = set(TTCollection(PKG / "fonts" / "monocraft" / "Monocraft-no-ligatures.ttc").fonts[0].getBestCmap())
    covered |= set(TTFont(PKG / "fonts" / "craftd-pixel-extras.ttf").getBestCmap())
    covered |= set(range(32, 127)) & {ord(c) for c in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 "}
    missing = {}
    for src in PKG.rglob("*.py"):  # engine messages show in the UI too
        for node in ast.walk(ast.parse(src.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                for ch in node.value:
                    if ord(ch) > 31 and ord(ch) not in covered and ch not in EMOJI_OK and ch not in "\n\t":
                        missing.setdefault(ch, src.name)
    # ASCII punctuation is covered by the extras font; anything left is a gap to draw
    assert not {c: f for c, f in missing.items() if not (32 <= ord(c) < 127 and c in '!"#$%&\'()*+-/:;<=>?@[\\]^_`{|}~,.')}, missing
