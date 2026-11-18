import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from craftd.gui import theme  # noqa: E402
from craftd.gui.dialogs import SettingsDialog  # noqa: E402
from craftd.gui.main_window import MainWindow  # noqa: E402
from craftd.gui.widgets import BADGE_ROLE, NAME_ROLE  # noqa: E402
from craftd.settings import Settings  # noqa: E402


def qapp():
    return QApplication.instance() or QApplication([])


def test_settings_round_trip_and_bad_values(tmp_path):
    Settings(theme="light", text_scale=1.5).save(tmp_path)
    assert Settings.load(tmp_path) == Settings("light", 1.5)
    (tmp_path / "settings.json").write_text('{"theme": "neon", "text_scale": "big"}')
    assert Settings.load(tmp_path) == Settings()  # junk falls back to defaults
    # settings from older versions (font picker, 4 text sizes) still load
    (tmp_path / "settings.json").write_text('{"theme": "dark", "font_family": "Arial", "text_scale": 1.3, '
                                            '"pixel_text": true}')
    assert Settings.load(tmp_path) == Settings("dark", 1.5)
    assert Settings.load(tmp_path / "missing") == Settings()


def test_light_and_dark_switch_everything(app):
    q = qapp()
    win = MainWindow(app)
    win.themer.apply(Settings(theme="light"))
    assert win.themer.mode == "light" and theme.color("bg") == theme.PALETTES["light"]["bg"]
    assert theme.PALETTES["light"]["bg"] in q.styleSheet()
    win.themer.apply(Settings(theme="dark", text_scale=1.5))
    assert win.themer.mode == "dark" and theme.PALETTES["dark"]["bg"] in q.styleSheet()
    assert "45px" in q.styleSheet()  # Large: titles at 5x the 9px pixel grid
    win.themer.apply(Settings(theme="system"))
    assert win.themer.mode in ("light", "dark")


def test_settings_dialog_previews_saves_and_cancels(app):
    win = MainWindow(app)
    win.themer.apply(Settings(theme="dark"))
    dlg = SettingsDialog(app, win.themer, win)
    dlg.theme.setCurrentIndex(dlg.theme.findData("light"))
    assert win.themer.mode == "light"  # live preview
    dlg.reject()
    assert win.themer.mode == "dark" and not (app.home / "settings.json").exists()

    dlg = SettingsDialog(app, win.themer, win)
    dlg.theme.setCurrentIndex(dlg.theme.findData("light"))
    dlg.size.setCurrentIndex(dlg.size.findData(1.5))
    dlg._save()
    assert Settings.load(app.home) == Settings(theme="light", text_scale=1.5)


def test_sidebar_rows_carry_name_and_badge(app, setup_262):
    win = MainWindow(app)
    win.ready_counts = {setup_262.id: 2}
    win.refresh_instances()
    item = win.list.item(0)
    assert item.data(NAME_ROLE) == "Survival 26.2" and item.data(BADGE_ROLE) == 2
    win.resize(900, 500)
    assert not win.grab().isNull()  # delegate paints without errors


def test_window_can_shrink_even_with_long_paths(app, setup_262):
    from craftd.gui.widgets import ElidedLabel
    win = MainWindow(app)
    long_path = "Minecraft 26.2 · Fabric · Linked Prism instance · C:\\Users\\mahir\\AppData\\Roaming\\" \
                "PrismLauncher\\instances\\26.2\\.minecraft"
    win.subtitle.setText(long_path)
    win.themer.apply(Settings(text_scale=1.0))
    assert win.minimumSizeHint().width() <= 850
    win.tabs.setCurrentWidget(win.carry_tab)
    assert win.minimumSizeHint().width() <= 850
    win.themer.apply(Settings(text_scale=1.5))
    assert win.minimumSizeHint().width() <= 1150
    # the path is shortened on screen but kept whole in the tooltip
    win.resize(800, 600)
    win.show()
    qapp().processEvents()
    assert isinstance(win.subtitle, ElidedLabel) and ("…" in win.subtitle.text() or "..." in win.subtitle.text())
    assert win.subtitle.toolTip() == long_path
    win.themer.apply(Settings())
