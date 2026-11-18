"""Craftd's main window: instance sidebar on the left, Mods / Carry Over tabs on the right."""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QListView, QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
    QPushButton, QSplitter, QStackedWidget, QTabWidget, QVBoxLayout, QWidget,
)

from .. import __version__
from ..core import Craftd
from ..instances import Instance
from .dialogs import EditInstanceDialog, ImportPrismDialog, NewInstanceDialog, SettingsDialog
from .tabs import CarryOverTab, CrashTab, ModsTab
from .theme import ThemeManager
from .widgets import BADGE_ROLE, KIND_ROLE, NAME_ROLE, SUMMARY_ROLE, ElidedLabel, InstanceDelegate
from .workers import Runner

ICON_FILE = Path(__file__).resolve().parent.parent / "assets" / "craftd.png"


class MainWindow(QMainWindow):
    def __init__(self, app: Craftd, themer: ThemeManager | None = None):
        super().__init__()
        self.app = app
        if themer is None:
            themer = ThemeManager(QApplication.instance(), app.settings)
            themer.apply()
        self.themer = themer
        self.setWindowTitle("Craftd")
        if ICON_FILE.is_file():
            self.setWindowIcon(QIcon(str(ICON_FILE)))
        self.resize(1100, 680)
        self.instances: list[Instance] = []
        self.ready_counts: dict[str, int] = {}
        self.runner = Runner(self.statusBar().showMessage, self._error)

        # ---- sidebar -------------------------------------------------------------------------
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        brand = QWidget()  # the official pixel logo + "Craftd"
        brand.setObjectName("BrandRow")
        brand_row = QHBoxLayout(brand)
        brand_row.setContentsMargins(2, 2, 2, 10)
        brand_row.setSpacing(12)
        self.brand_logo = QLabel()
        self.brand_logo.setObjectName("BrandLogo")
        self.brand_logo.setAccessibleName("Craftd logo")
        brand_text = QLabel("Craftd")
        brand_text.setObjectName("Brand")
        brand_row.addWidget(self.brand_logo, 0, Qt.AlignmentFlag.AlignVCenter)
        brand_row.addWidget(brand_text, 1, Qt.AlignmentFlag.AlignVCenter)
        self._set_brand_logo()
        section = QLabel("INSTANCES")
        section.setObjectName("SectionLabel")
        self.list = QListWidget()
        self.list.setItemDelegate(InstanceDelegate(self.list))
        # rows re-measure on every resize, so names wrap instead of being cut off
        self.list.setResizeMode(QListView.ResizeMode.Adjust)
        self.list.setUniformItemSizes(False)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)  # right-click → instance menu
        self.list.customContextMenuRequested.connect(self._instance_menu)
        self.list.setMouseTracking(True)
        self.list.currentRowChanged.connect(self._selected)
        new_btn = QPushButton("+ New Instance")
        new_btn.setProperty("primary", True)
        new_btn.clicked.connect(self.new_instance)
        import_btn = QPushButton("Import from Prism…")
        import_btn.clicked.connect(lambda: self.import_prism("prism"))
        import_mmc_btn = QPushButton("Import from MultiMC…")
        import_mmc_btn.clicked.connect(lambda: self.import_multimc())
        side = QVBoxLayout(sidebar)
        side.setContentsMargins(12, 12, 12, 12)
        settings_btn = QPushButton("⚙  Settings")
        settings_btn.clicked.connect(self.open_settings)
        side.addWidget(brand)
        side.addWidget(section)
        side.addWidget(self.list, 1)
        side.addWidget(new_btn)
        side.addWidget(import_btn)
        side.addWidget(import_mmc_btn)
        side.addWidget(settings_btn)

        # ---- detail -----------------------------------------------------------------------------
        self.title = QLabel()
        self.title.setObjectName("InstanceTitle")
        self.subtitle = ElidedLabel(mode=Qt.TextElideMode.ElideRight)  # long paths get "…", not a wider window
        self.subtitle.setObjectName("Muted")
        folder_btn = QPushButton("Open Folder")
        folder_btn.clicked.connect(self.open_folder)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self.remove_instance)
        header = QHBoxLayout()
        titles = QVBoxLayout()
        titles.addWidget(self.title)
        titles.addWidget(self.subtitle)
        header.addLayout(titles, 1)
        header.addWidget(folder_btn)
        header.addWidget(self.remove_btn)

        self.mods_tab = ModsTab(app, self.runner)
        self.carry_tab = CarryOverTab(app, self.runner)
        self.tabs = QTabWidget()
        self.tabs.addTab(self.mods_tab, "Mods")
        self.tabs.addTab(self.carry_tab, "Carry Over")
        self.crash_tab = CrashTab(app, self.runner)
        self.tabs.addTab(self.crash_tab, "Crash Help")
        self.crash_tab.unseen.connect(self._crash_badge)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.themer.changed.connect(self._retheme)
        self.mods_tab.mods_changed.connect(lambda: setattr(self.carry_tab, "detected_for", None))
        self.carry_tab.mods_changed.connect(self.mods_tab.reload)
        self.carry_tab.mods_changed.connect(self._recount_ready)

        detail = QWidget()
        dl = QVBoxLayout(detail)
        dl.setContentsMargins(20, 16, 20, 12)
        dl.addLayout(header)
        dl.addWidget(self.tabs, 1)

        empty = QLabel("No instances yet.\n\nClick “+ New Instance” to make one, or “Import from Prism…” "
                       "to bring in the instances you already have.")
        empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty.setWordWrap(True)
        empty.setMargin(24)
        empty.setObjectName("Muted")
        self.stack = QStackedWidget()
        self.stack.addWidget(empty)
        self.stack.addWidget(detail)

        splitter = QSplitter()
        splitter.addWidget(sidebar)
        splitter.addWidget(self.stack)
        splitter.setSizes([260, 840])
        splitter.setChildrenCollapsible(False)
        self.setCentralWidget(splitter)
        self.statusBar().showMessage(f"Craftd {__version__}")

        self.refresh_instances()
        self.runner.run(lambda p: app.refresh_game_versions(), on_error=lambda _: None)
        if app.settings.check_waitlist_on_start:
            self._check_waitlists()

    # ---- instance list ---------------------------------------------------------------------------
    def refresh_instances(self, select_id: str | None = None) -> None:
        current = select_id or (self.current().id if self.current() else None)
        self.instances = self.app.manager.list()
        self.list.blockSignals(True)
        self.list.clear()
        for inst in self.instances:
            item = QListWidgetItem(inst.name)
            item.setData(Qt.ItemDataRole.UserRole, inst.id)
            item.setData(NAME_ROLE, inst.name)
            item.setData(SUMMARY_ROLE, inst.summary)
            item.setData(BADGE_ROLE, self.ready_counts.get(inst.id, 0))
            item.setData(KIND_ROLE, inst.launcher_label)
            self.list.addItem(item)
        ids = [i.id for i in self.instances]
        row = ids.index(current) if current in ids else (0 if ids else -1)
        self.list.setCurrentRow(row)
        self.list.blockSignals(False)
        self._selected(row)

    def current(self) -> Instance | None:
        row = self.list.currentRow()
        return self.instances[row] if 0 <= row < len(self.instances) else None

    def _selected(self, row: int) -> None:
        inst = self.instances[row] if 0 <= row < len(self.instances) else None
        self.stack.setCurrentIndex(1 if inst else 0)
        if inst:
            self.title.setText(inst.name)
            kind = f"Linked {inst.launcher_label} instance" if inst.kind == "prism" else "Craftd instance"
            self.subtitle.setText(f"Minecraft {inst.game_version} · {inst.loader_text} · {kind} · {inst.game_dir}")
            self.remove_btn.setText("Unlink" if inst.kind == "prism" else "Delete")
        self.mods_tab.set_instance(inst)
        self.carry_tab.set_instance(inst)
        self.crash_tab.set_instance(inst)
        if inst and self.tabs.currentWidget() is self.carry_tab:
            self.carry_tab.ensure_detected()

    def _tab_changed(self, _index: int) -> None:
        if self.tabs.currentWidget() is self.carry_tab:
            self.carry_tab.ensure_detected()
        elif self.tabs.currentWidget() is self.crash_tab:
            self.crash_tab.refresh()
            self.crash_tab.mark_seen()

    def _crash_badge(self, unseen: bool) -> None:
        if unseen and self.tabs.currentWidget() is self.crash_tab:
            self.crash_tab.mark_seen()
            return
        self.tabs.setTabText(self.tabs.indexOf(self.crash_tab), "Crash Help ●" if unseen else "Crash Help")

    # ---- actions ----------------------------------------------------------------------------------
    def new_instance(self) -> None:
        dialog = NewInstanceDialog(self.app, self)
        if not dialog.exec():
            return
        name, version, loader, sources = dialog.values()
        try:
            inst = self.app.manager.create(name, version, loader)
        except (OSError, ValueError) as exc:
            self._error(str(exc))
            return
        self.refresh_instances(select_id=inst.id)
        if sources:
            # The headline feature: jump straight to the carry-over review for the new instance
            self.carry_tab.set_source(sources)
            self.tabs.setCurrentWidget(self.carry_tab)
            self.carry_tab.detected_for = None
            self.carry_tab.ensure_detected()

    def import_prism(self, launcher: str = "prism") -> None:
        dialog = ImportPrismDialog(self.app, self, launcher=launcher)
        if dialog.exec() and dialog.linked:
            self.refresh_instances(select_id=dialog.linked[-1].id)
            self.statusBar().showMessage(f"Linked {len(dialog.linked)} {dialog.launcher_name} instance(s)")

    def instance_menu(self, inst: Instance) -> QMenu:
        """The right-click menu for an instance. More options will be added here over time."""
        menu = QMenu(self)
        header = menu.addAction(inst.name)
        header.setEnabled(False)
        menu.addSeparator()
        menu.addAction("Edit Instance…", self.edit_instance)
        return menu

    def _instance_menu(self, pos) -> None:
        row = self.list.indexAt(pos).row()
        if row < 0:
            return
        self.list.setCurrentRow(row)
        inst = self.current()
        if inst:
            self.instance_menu(inst).exec(self.list.viewport().mapToGlobal(pos))

    def edit_instance(self) -> None:
        inst = self.current()
        if not inst:
            return
        dialog = EditInstanceDialog(self.app, inst, self.runner, self)
        if dialog.exec() and dialog.result_instance:
            new = dialog.result_instance
            self.refresh_instances(select_id=new.id)
            self.statusBar().showMessage(f"Saved {new.name}: Minecraft {new.game_version} · {new.loader_text}")

    def import_multimc(self) -> None:
        self.import_prism("multimc")

    def remove_instance(self) -> None:
        inst = self.current()
        if not inst:
            return
        if inst.kind == "prism":
            question = f"Unlink {inst.name} from Craftd?\n\nIts files stay in {inst.launcher_label} untouched."
        else:
            question = f"Delete {inst.name} and all of its files?\n\n{inst.root}\n\nThis can't be undone."
        if QMessageBox.question(self, "Craftd", question) == QMessageBox.StandardButton.Yes:
            self.app.manager.remove(inst)
            self.refresh_instances()

    def open_folder(self) -> None:
        inst = self.current()
        if inst:
            inst.mods_dir.mkdir(parents=True, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(inst.game_dir)))

    # ---- waitlist notifications ---------------------------------------------------------------------
    def _check_waitlists(self) -> None:
        def done(ready_by_id):
            self.ready_counts = {k: len(v) for k, v in ready_by_id.items()}
            if ready_by_id:
                total = sum(self.ready_counts.values())
                self.refresh_instances()
                self.statusBar().showMessage(f"{total} waitlisted mod(s) now have builds — see the Carry Over tab", 15000)
                cur = self.current()
                if cur and cur.id in ready_by_id:
                    self.carry_tab.show_ready(ready_by_id[cur.id])

        self.runner.run(lambda p: self.app.carry.check_all_waitlists(self.app.manager.list()),
                        on_done=done, on_error=lambda _: None)

    def _recount_ready(self) -> None:
        cur = self.current()
        if cur and cur.id in self.ready_counts:
            self.ready_counts.pop(cur.id)
            self.refresh_instances()

    def open_settings(self) -> None:
        if SettingsDialog(self.app, self.themer, self).exec():
            self.carry_tab.set_instance(self.current())  # new Carry Over defaults show right away
            self.carry_tab.detected_for = None
            if self.tabs.currentWidget() is self.carry_tab:
                self.carry_tab.ensure_detected()

    def _set_brand_logo(self) -> None:
        from . import theme
        self.brand_logo.setPixmap(theme.logo_pixmap(theme.logo_size_for_brand()))

    def _retheme(self) -> None:
        self._set_brand_logo()  # 32px, or 48px with Large text
        self.mods_tab.retheme()
        self.carry_tab.retheme()
        self.list.doItemsLayout()
        self.list.viewport().update()

    def fit_to_screen(self) -> None:
        """Open at a comfortable size that fits the screen, centered."""
        screen = self.screen().availableGeometry() if self.screen() else None
        if not screen:
            return
        w = min(1200, int(screen.width() * 0.85))
        h = min(760, int(screen.height() * 0.85))
        self.resize(max(w, self.minimumSizeHint().width()), max(h, 480))
        self.move(screen.center() - self.rect().center())

    def _error(self, message: str) -> None:
        QMessageBox.warning(self, "Craftd", message)

    def closeEvent(self, event) -> None:
        self.runner.wait(5000)
        super().closeEvent(event)


def run() -> int:
    qt_app = QApplication.instance() or QApplication(sys.argv)
    qt_app.setApplicationName("Craftd")
    qt_app.setStyle("Fusion")
    if sys.platform.startswith("win"):  # so the taskbar shows Craftd's icon instead of Python's
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("mahirmalickk.craftd")
        except (AttributeError, OSError):
            pass
    if ICON_FILE.is_file():
        qt_app.setWindowIcon(QIcon(str(ICON_FILE)))
    core = Craftd()
    themer = ThemeManager(qt_app, core.settings)
    themer.apply()
    window = MainWindow(core, themer)
    window.fit_to_screen()
    window.show()
    return qt_app.exec()
