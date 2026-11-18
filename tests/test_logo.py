"""The official logo: one 16x16 source, and every icon built from it stays pixel-exact."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path  # noqa: E402

from PIL import Image  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

ASSETS = Path(__file__).resolve().parent.parent / "craftd" / "assets"


def test_icons_match_the_official_logo():
    src = Image.open(ASSETS / "craftd-logo-16.png").convert("RGBA")
    assert src.size == (16, 16)
    big = Image.open(ASSETS / "craftd.png").convert("RGBA")
    assert big.size == (256, 256) and big.resize((16, 16), Image.NEAREST).tobytes() == src.tobytes()
    ico = Image.open(ASSETS / "craftd.ico")
    sizes = sorted(ico.info["sizes"])
    assert sizes == [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]  # whole multiples of 16
    for s in (16, 32, 48):
        ico.size = (s, s)
        assert ico.convert("RGBA").resize((16, 16), Image.NEAREST).tobytes() == src.tobytes()


def test_logo_in_sidebar_and_about(app):
    from craftd.gui import theme
    from craftd.gui.dialogs import SettingsDialog
    from craftd.gui.main_window import MainWindow
    from craftd.settings import Settings
    QApplication.instance() or QApplication([])
    win = MainWindow(app)
    assert win.brand_logo.pixmap().width() == 32 and not win.windowIcon().isNull()
    win.themer.apply(Settings(text_scale=1.5))
    win._retheme()
    assert win.brand_logo.pixmap().width() == 48  # Large text: a bigger logo, still a multiple of 16
    win.themer.apply(Settings())
    assert theme.logo_pixmap(40).width() == 48 and theme.logo_pixmap(20).width() == 16
    dlg = SettingsDialog(app, win.themer, win)
    assert any(lbl.pixmap() and lbl.pixmap().width() == 64 for lbl in dlg.findChildren(type(win.brand_logo)))
    dlg.reject()
