"""Craftd's look: light and dark palettes, a type scale, and live theme switching.

Every color in the UI comes from PALETTES, so a theme change re-skins everything.
"""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QGuiApplication, QPalette
from PySide6.QtWidgets import QApplication

from ..settings import Settings

PALETTES: dict[str, dict[str, str]] = {
    "dark": {  # Netherite: sampled from the block of netherite (#1b1617 → #4f4c4f), warm charcoal
        "bg": "#252020", "sidebar": "#1b1617", "surface": "#211c1d", "raised": "#3a3639",
        "raised_hover": "#474547", "border": "#433e40", "grid": "#2f2a2b", "header": "#2d2829", "input": "#1b1617",
        "text": "#eee8e8", "muted": "#ada4a6", "faint": "#857b7d", "accent": "#5cb85c", "accent_hover": "#6dc66d",
        "on_accent": "#0d1a0d", "selected": "#2c3a2b", "hover": "#2d2829", "banner": "#29362a",
        "available": "#6fd36f", "unavailable": "#e6b450", "local": "#ada4a6", "installed": "#7aaee6",
        "wrong_loader": "#e39595", "waitlisted": "#a8a9c2", "warning_bg": "#3e3222", "scroll_track": "#2d2829",
        "scroll": "#787375", "scroll_hover": "#938f91",
    },
    "light": {  # Iron: the block of iron (#dcdcdc), neutral gray; greens darkened to stay readable on it
        "bg": "#dcdcdc", "sidebar": "#cdcdcd", "surface": "#e8e8e8", "raised": "#efefef",
        "raised_hover": "#f7f7f7", "border": "#a8a8a8", "grid": "#d4d4d4", "header": "#d6d6d6", "input": "#f3f3f3",
        "text": "#1a1a1a", "muted": "#474747", "faint": "#6b6b6b", "accent": "#1d612b", "accent_hover": "#195225",
        "on_accent": "#ffffff", "selected": "#c4dcc8", "hover": "#d0d0d0", "banner": "#cfe3d2",
        "available": "#17632c", "unavailable": "#7c4b00", "local": "#555555", "installed": "#235791",
        "wrong_loader": "#933737", "waitlisted": "#4a576b", "warning_bg": "#eadcbf", "scroll_track": "#cecece",
        "scroll": "#6f6f6f", "scroll_hover": "#595959",
    },
}

# First installed family wins. Segoe UI Variable is Windows 11's UI font.
UI_FONTS = ["Segoe UI Variable Text", "Segoe UI", "Inter", "SF Pro Text", "Helvetica Neue",
            "Noto Sans", "DejaVu Sans"]
MONO_FONTS = ["Cascadia Mono", "Cascadia Code", "Consolas", "SF Mono", "Menlo", "JetBrains Mono",
              "DejaVu Sans Mono"]

# Type scale in px at 100% text size
TYPE = {"base": 13, "small": 12, "caption": 11, "title": 24, "brand": 20, "button": 13, "mono": 12}

_current = PALETTES["dark"]
_mono_family = "monospace"
_scale = 1.0
_pixel = False

# Craftd's font is Monocraft (OFL), a Minecraft-style pixel font. It's drawn on a 9-pixel grid
# (1080 units = 9 font pixels of 120, capitals 7 tall), so it's only crisp at multiples of 9px.
FONTS_DIR = Path(__file__).resolve().parent.parent / "fonts"
MONOCRAFT_FILE = FONTS_DIR / "monocraft" / "Monocraft-no-ligatures.ttc"  # every weight, no ligatures
EXTRAS_FILE = FONTS_DIR / "craftd-pixel-extras.ttf"  # the few symbols Monocraft lacks (⚠ ✓ ⚙), same grid
PIXEL_TYPE = {"base": 18, "small": 18, "caption": 18, "button": 18, "mono": 18, "title": 36, "brand": 36}
PIXEL_TYPE_LARGE = {"base": 27, "small": 27, "caption": 18, "button": 27, "mono": 27, "title": 45, "brand": 45}


def load_app_font() -> str | None:
    """Register Monocraft (and the symbols font that fills its gaps). Returns its family, or None."""
    extras = None
    if EXTRAS_FILE.is_file():
        fid = QFontDatabase.addApplicationFont(str(EXTRAS_FILE))
        fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
        extras = fams[0] if fams else None
    if not MONOCRAFT_FILE.is_file():
        return None
    fid = QFontDatabase.addApplicationFont(str(MONOCRAFT_FILE))
    fams = QFontDatabase.applicationFontFamilies(fid) if fid >= 0 else []
    if not fams:
        return None
    if extras:  # characters missing from Monocraft come from the extras font first
        QFont.insertSubstitution(fams[0], extras)
    return fams[0]


def size_for(key: str, scale: float, pixel: bool) -> int:
    if pixel:
        return (PIXEL_TYPE_LARGE if scale >= 1.15 else PIXEL_TYPE)[key]
    return round(TYPE[key] * scale)


def weight(kind: str = "demibold") -> QFont.Weight:
    """Craftd's pixel font is always Regular: no bold anywhere (it looked heavy in the UI)."""
    if _pixel:
        return QFont.Weight.Normal
    return QFont.Weight.Bold if kind == "bold" else QFont.Weight.DemiBold


LOGO_FILE = Path(__file__).resolve().parent.parent / "assets" / "craftd-logo-16.png"


def logo_pixmap(size: int):
    """Craftd's 16x16 pixel logo at `size` (rounded to a whole multiple of 16 so every pixel stays square)."""
    from PySide6.QtGui import QPixmap
    pm = QPixmap(str(LOGO_FILE))
    if pm.isNull():
        return pm
    side = max(16, int(size / 16 + 0.5) * 16)  # ordinary rounding (Python's round() sends 2.5 to 2)
    return pm.scaled(side, side, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.FastTransformation)


def logo_size_for_brand() -> int:
    """The sidebar logo matches the brand text: 32px normally, 48px with Large text."""
    return 48 if px("brand") > 40 else 32


def strong(text: str) -> str:
    """Emphasis for rich-text labels: bold with system fonts, plain with Craftd's pixel font."""
    return text if _pixel else f"<b>{text}</b>"


def crisp(font: QFont) -> QFont:
    if _pixel:
        font.setStyleStrategy(QFont.StyleStrategy.NoAntialias)
        font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    return font


def color(role: str) -> str:
    """A color from the active palette, e.g. color('muted')."""
    return _current[role]


def px(key: str) -> int:
    """A type-scale size in pixels at the current text size."""
    return size_for(key, _scale, _pixel)


def emphasis_px(key: str, factor: float) -> int:
    """A slightly larger size for names/titles; the pixel font stays on its 9px grid."""
    return px(key) if _pixel else round(px(key) * factor)


def mono_font() -> QFont:
    f = QFont(_mono_family)
    f.setPixelSize(px("mono"))
    return crisp(f)


def _first_installed(candidates: list[str]) -> str:
    installed = set(QFontDatabase.families())
    return next((c for c in candidates if c in installed), QApplication.font().family())


def default_font_family() -> str:
    return _first_installed(UI_FONTS)


def build_stylesheet(p: dict[str, str], family: str, scale: float, pixel: bool = False) -> str:
    def px(key: str) -> str:
        return f"{size_for(key, scale, pixel)}px"

    css = f"""
* {{ font-family: "{family}"; }}
QWidget {{ background: {p['bg']}; color: {p['text']}; font-size: {px('base')}; }}
QToolTip {{ background: {p['raised']}; color: {p['text']}; border: 1px solid {p['border']}; padding: 4px 6px; }}
#Sidebar, #Sidebar QListWidget {{ background: {p['sidebar']}; }}
#Sidebar QLabel {{ background: transparent; }}
#BrandRow, #BrandLogo {{ background: transparent; }}
#Brand {{ font-size: {px('brand')}; font-weight: 800; color: {p['accent']}; padding: 0px;
          letter-spacing: 0.5px; }}
#SectionLabel {{ font-size: {px('caption')}; font-weight: 700; color: {p['faint']}; letter-spacing: 1px;
                 padding: 4px 4px 2px 4px; }}
#InstanceTitle {{ font-size: {px('title')}; font-weight: 700; letter-spacing: -0.3px; }}
#Muted {{ color: {p['muted']}; font-size: {px('small')}; }}
#Banner {{ background: {p['banner']}; border: 1px solid {p['accent']}; border-radius: 8px; }}
#Banner QLabel {{ background: transparent; }}
QListWidget {{ border: none; outline: none; }}
QPushButton {{ background: {p['raised']}; border: 1px solid {p['border']}; border-radius: 7px;
               padding: 6px 14px; font-size: {px('button')}; font-weight: 600; }}
QPushButton:hover {{ background: {p['raised_hover']}; }}
#Sidebar QPushButton {{ padding: 6px 6px; }}  /* full-width buttons: side padding only widens the window */
QPushButton:disabled {{ color: {p['faint']}; }}
QPushButton[primary="true"] {{ background: {p['accent']}; border-color: {p['accent']}; color: {p['on_accent']}; }}
QPushButton[primary="true"]:hover {{ background: {p['accent_hover']}; border-color: {p['accent_hover']}; }}
QPushButton[primary="true"]:disabled {{ background: {p['raised']}; border-color: {p['border']}; color: {p['faint']}; }}
QLineEdit, QComboBox {{ background: {p['input']}; border: 1px solid {p['border']}; border-radius: 7px;
                        padding: 5px 8px; selection-background-color: {p['accent']}; }}
QLineEdit:focus, QComboBox:focus {{ border-color: {p['accent']}; }}
QComboBox QAbstractItemView {{ background: {p['surface']}; border: 1px solid {p['border']};
                               selection-background-color: {p['selected']}; selection-color: {p['text']}; }}
QTableWidget, QListWidget#Plain {{ background: {p['surface']}; gridline-color: {p['grid']};
               border: 1px solid {p['border']}; border-radius: 8px;
               selection-background-color: {p['selected']}; selection-color: {p['text']}; }}
QTableWidget::item {{ padding: 4px 6px; border-bottom: 1px solid {p['grid']}; }}
QHeaderView::section {{ background: {p['header']}; color: {p['muted']}; border: none;
                        border-bottom: 1px solid {p['border']}; padding: 7px 6px;
                        font-size: {px('caption')}; font-weight: 700; letter-spacing: 0.6px; }}
QTabWidget::pane {{ border: none; }}
QTabBar::tab {{ background: transparent; padding: 8px 16px; color: {p['muted']}; font-weight: 600;
                border-bottom: 2px solid transparent; }}
QTabBar::tab:selected {{ color: {p['text']}; border-bottom: 2px solid {p['accent']}; }}
QTabBar::tab:hover:!selected {{ color: {p['text']}; }}
QStatusBar {{ background: {p['sidebar']}; color: {p['muted']}; font-size: {px('small')}; }}
QSplitter::handle {{ background: {p['border']}; width: 1px; }}
QScrollBar:vertical {{ background: {p['scroll_track']}; width: 12px; margin: 0; border-radius: 6px; }}
QScrollBar:horizontal {{ background: {p['scroll_track']}; height: 12px; margin: 0; border-radius: 6px; }}
QScrollBar::handle:vertical {{ background: {p['scroll']}; border-radius: 4px; min-height: 36px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {p['scroll']}; border-radius: 4px; min-width: 36px; margin: 2px; }}
QScrollBar::handle:hover, QScrollBar::handle:pressed {{ background: {p['scroll_hover']}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; border: none; background: none; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: none; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator, QTableWidget::indicator, QListWidget::indicator {{
    width: 14px; height: 14px; border: 1px solid {p['faint']}; border-radius: 4px; background: {p['input']}; }}
QCheckBox::indicator:checked, QTableWidget::indicator:checked, QListWidget::indicator:checked {{
    background: {p['accent']}; border-color: {p['accent']}; }}
QCheckBox::indicator:disabled, QTableWidget::indicator:disabled {{ border-color: {p['border']}; background: {p['bg']}; }}
QDialog, QMessageBox {{ background: {p['bg']}; }}
#DialogTitle {{ font-size: {px('brand')}; font-weight: 700; }}
#LoaderBadge {{ background: {p['selected']}; color: {p['accent']}; border-radius: 9px; padding: 3px 10px;
                font-size: {px('small')}; font-weight: 700; }}
QPushButton#Chip {{ border-radius: 11px; padding: 3px 12px; min-height: 16px; font-size: {px('small')}; font-weight: 600;
                    color: {p['muted']}; background: transparent; }}
QPushButton#Chip:hover {{ color: {p['text']}; background: {p['hover']}; }}
QPushButton#Chip:checked {{ background: {p['selected']}; border-color: {p['accent']}; color: {p['accent']}; }}
QListWidget#Results {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 10px; }}
#DetailPanel {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 10px; }}
#DetailContent, #DetailPanel QLabel {{ background: transparent; }}
#DetailPanel QTextBrowser {{ background: transparent; border: none; }}
#DetailPanel QComboBox {{ background: {p['input']}; }}
#DetailTitle {{ font-size: {px('title')}; font-weight: 700; }}
#WarnBanner {{ background: {p['warning_bg']}; border: 1px solid {p['unavailable']}; border-radius: 8px; }}
#WarnBanner QLabel {{ background: transparent; }}
QMenu {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 6px; }}
QMenu::item {{ padding: 7px 18px; border-radius: 6px; color: {p['text']}; }}
QMenu::item:selected {{ background: {p['selected']}; color: {p['accent']}; }}
QMenu::item:disabled {{ color: {p['faint']}; }}
QMenu::separator {{ height: 1px; background: {p['border']}; margin: 5px 8px; }}
#Excerpt {{ background: {p['input']}; border: 1px solid {p['border']}; border-radius: 8px; padding: 8px;
            color: {p['muted']}; }}
#QueueBar {{ background: {p['sidebar']}; border: 1px solid {p['border']}; border-radius: 10px; }}
#QueueBar QLabel {{ background: transparent; }}
QListWidget#SettingsNav {{ background: {p['sidebar']}; border: 1px solid {p['border']}; border-radius: 10px;
                         padding: 6px; }}
QListWidget#SettingsNav::item {{ padding: 8px 10px; border-radius: 7px; color: {p['muted']}; }}
QListWidget#SettingsNav::item:hover {{ background: {p['raised']}; color: {p['text']}; }}
QListWidget#SettingsNav::item:selected {{ background: {p['selected']}; color: {p['accent']}; }}
QRadioButton::indicator {{ width: 12px; height: 12px; border-radius: 8px; border: 2px solid {p['muted']};
                           background: {p['input']}; }}
QRadioButton::indicator:checked {{ background: {p['accent']}; border-color: {p['accent']}; }}
QRadioButton:disabled {{ color: {p['faint']}; }}
QSpinBox {{ background: {p['input']}; border: 1px solid {p['border']}; border-radius: 7px; padding: 4px 8px; }}
QSpinBox:focus {{ border-color: {p['accent']}; }}
QLineEdit:disabled, QSpinBox:disabled {{ color: {p['faint']}; }}
QScrollArea {{ background: transparent; }}
QScrollArea > QWidget > QWidget {{ background: transparent; }}
QListWidget#PackResults {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 10px;
                          padding: 4px; }}
QListWidget#PackResults::item {{ padding: 8px 6px; border-radius: 7px; color: {p['text']}; }}
QListWidget#PackResults::item:hover {{ background: {p['hover']}; }}
QListWidget#PackResults::item:selected {{ background: {p['selected']}; color: {p['text']}; }}
#OptionRow {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 8px; }}
#OptionRow[selected="true"] {{ background: {p['selected']}; border-color: {p['accent']}; }}
#OptionRow:disabled {{ background: {p['bg']}; }}
#OptionRow QLabel, #OptionRow QRadioButton {{ background: transparent; }}
#OptionRow QLabel:disabled, #OptionRow QRadioButton:disabled {{ color: {p['faint']}; }}
#OptionFound {{ color: {p['accent']}; font-size: {px('small')}; }}
#SoonTag {{ color: {p['faint']}; border: 1px solid {p['border']}; border-radius: 9px; padding: 1px 8px;
            font-size: {px('small')}; }}
#FolderBox {{ background: {p['surface']}; border: 1px solid {p['border']}; border-radius: 8px; }}
#FolderBox QLabel {{ background: transparent; }}
#LegacyBanner {{ background: {p['warning_bg']}; border: 1px solid {p['unavailable']}; border-radius: 8px; }}
#LegacyBanner QLabel {{ background: transparent; }}
"""
    if pixel:  # Regular only, no letter-spacing: the pixel font stays plain and crisp
        css = re.sub(r"font-weight: \d+;", "font-weight: 400;", css)
        css = re.sub(r"letter-spacing: [-\d.]+px;", "", css)
    return css


class ThemeManager(QObject):
    """Applies settings to the app and re-applies when Windows switches light/dark (in Match Windows mode)."""

    changed = Signal()

    def __init__(self, qt_app: QApplication, settings: Settings):
        super().__init__()
        loaded = load_app_font()
        self.pixel = loaded is not None
        self.family = loaded or default_font_family()  # fallback only if the font files are missing
        self.app = qt_app
        self.settings = settings
        self.mode = "dark"
        self._applying = False
        QGuiApplication.styleHints().colorSchemeChanged.connect(self._system_changed)

    def resolved_mode(self) -> str:
        if self.settings.theme in ("light", "dark"):
            return self.settings.theme
        hints = QGuiApplication.styleHints()
        hints.unsetColorScheme()  # read the real OS preference
        return "light" if hints.colorScheme() == Qt.ColorScheme.Light else "dark"

    def apply(self, settings: Settings | None = None) -> None:
        if settings is not None:
            self.settings = settings
        self._applying = True
        try:
            self.mode = self.resolved_mode()
            self._apply_mode()
        finally:
            self._applying = False
        self.changed.emit()

    def _apply_mode(self) -> None:
        global _current, _mono_family, _scale, _pixel
        p = PALETTES[self.mode]
        _current, _scale = p, self.settings.text_scale
        family = self.family
        _pixel = self.pixel
        # with the pixel font, versions and file names use it too, so the whole UI matches
        _mono_family = family if _pixel else _first_installed(MONO_FONTS)

        hints = QGuiApplication.styleHints()
        if self.settings.theme == "system":
            hints.unsetColorScheme()
        else:  # also makes the Windows title bar match
            hints.setColorScheme(Qt.ColorScheme.Light if self.mode == "light" else Qt.ColorScheme.Dark)

        font = QFont(family)
        font.setPixelSize(px("base"))
        self.app.setFont(crisp(font))
        pal = QPalette()
        for role, key in [(QPalette.ColorRole.Window, "bg"), (QPalette.ColorRole.WindowText, "text"),
                          (QPalette.ColorRole.Base, "surface"), (QPalette.ColorRole.AlternateBase, "header"),
                          (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.Button, "raised"),
                          (QPalette.ColorRole.ButtonText, "text"), (QPalette.ColorRole.Highlight, "accent"),
                          (QPalette.ColorRole.HighlightedText, "on_accent"), (QPalette.ColorRole.ToolTipBase, "raised"),
                          (QPalette.ColorRole.ToolTipText, "text"), (QPalette.ColorRole.PlaceholderText, "faint"),
                          (QPalette.ColorRole.Link, "accent"), (QPalette.ColorRole.LinkVisited, "accent")]:
            pal.setColor(role, QColor(p[key]))
        self.app.setPalette(pal)
        self.app.setStyleSheet(build_stylesheet(p, family, _scale, _pixel))

    def _system_changed(self, _scheme) -> None:
        if self.settings.theme == "system" and not self._applying:
            new = self.resolved_mode()
            if new != self.mode:
                self.apply()
