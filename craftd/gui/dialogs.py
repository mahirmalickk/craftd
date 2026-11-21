"""New Instance, Import from, Settings, Issues, Choose Packs/Worlds, Share and Change Version dialogs."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame,
    QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton,
    QScrollArea, QSizePolicy, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from ..core import Craftd
from ..instances import LOADER_LABELS, LOADERS, Instance
from ..paths import prism_instance_dirs
from . import theme
from .widgets import flow_row
from .workers import Runner


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    return label


def fit_combo(combo: QComboBox, chars: int = 10) -> QComboBox:
    """Let a combo box shrink with its window instead of growing to its longest item (long items are cut
    off with … and shown in full in the open list)."""
    combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
    combo.setMinimumContentsLength(chars)
    combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
    return combo


def launcher_combo(app: Craftd) -> tuple[QComboBox, QLabel]:
    """"Create in: Prism / MultiMC" (only the ones Craftd can find), plus a note when there's none."""
    from ..launchers import LAUNCHERS, available
    combo = QComboBox()
    found = available(app.settings)
    for key, folder in found.items():
        combo.addItem(LAUNCHERS[key], key)
        combo.setItemData(combo.count() - 1, str(folder), Qt.ItemDataRole.ToolTipRole)  # the folder, on hover
    fit_combo(combo)
    note = _muted("")
    if not found:
        combo.addItem("No launcher found", None)
        combo.setEnabled(False)
        note.setText("Craftd makes new instances in Prism Launcher or MultiMC, which launch the game. Install "
                     "Prism, or set MultiMC's instances folder in Settings → General.")
    else:
        combo.setCurrentIndex(max(0, combo.findData(app.settings.last_launcher)))
        note.setText("Craftd can't launch Minecraft yet, so the instance is made there, ready to play.")
    note.setVisible(True)
    return combo, note


# ---------------------------------------------------------------------------------------
class NewInstanceDialog(QDialog):
    """Name, Minecraft version, loader, which launcher to make it in, and where to carry mods over from."""

    def __init__(self, app: Craftd, parent=None):
        super().__init__(parent)
        self.app = app
        self.setWindowTitle("New Instance")
        self.setMinimumWidth(600)
        self._name_edited = False
        self.instances = app.manager.list()

        self.name = QLineEdit()
        self.name.textEdited.connect(lambda _: setattr(self, "_name_edited", True))
        self.version = QComboBox()
        self.version.setEditable(True)
        self.snapshots = QCheckBox("Show snapshots")
        self.snapshots.toggled.connect(self._fill_versions)
        self.loader = QComboBox()
        for key in LOADERS:
            self.loader.addItem(LOADER_LABELS[key], key)

        self.launcher, self.launcher_note = launcher_combo(app)

        self.carry_box = QCheckBox("Carry over mods from")
        self.carry_box.setChecked(True)
        self.source = QComboBox()
        self.carry_hint = _muted("")

        version_row = QHBoxLayout()
        version_row.addWidget(self.version, 1)
        version_row.addWidget(self.snapshots)
        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("Minecraft", version_row)
        form.addRow("Mod loader", self.loader)
        form.addRow("Create in", self.launcher)

        carry_row = QHBoxLayout()
        carry_row.addWidget(self.carry_box)
        carry_row.addWidget(self.source, 1)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Create")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("primary", True)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setEnabled(self.launcher.currentData() is not None)
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.launcher_note)
        layout.addSpacing(8)
        layout.addLayout(carry_row)
        layout.addWidget(self.carry_hint)
        layout.addWidget(buttons)

        self._fill_versions()
        self.version.currentTextChanged.connect(self._changed)
        self.loader.currentIndexChanged.connect(self._changed)
        self.carry_box.toggled.connect(self.source.setEnabled)
        self._changed()

    def _fill_versions(self) -> None:
        current = self.version.currentText()
        self.version.blockSignals(True)
        self.version.clear()
        show_all = self.snapshots.isChecked()
        for gv in self.app.game_versions:
            if show_all or gv.get("version_type") == "release":
                self.version.addItem(gv["version"])
        if not self.app.game_versions:
            self.version.lineEdit().setPlaceholderText("Type a version, e.g. 26.3")
        if current:
            self.version.setCurrentText(current)
        self.version.blockSignals(False)
        self._changed()

    def _draft(self) -> Instance:
        return Instance(id="__new__", name=self.name.text(), game_version=self.version.currentText().strip(),
                        loader=self.loader.currentData(), root=Path("."), game_dir=Path("."))

    def _changed(self, *_):
        draft = self._draft()
        if not self._name_edited:
            self.name.setText(f"{LOADER_LABELS[draft.loader]} {draft.game_version}".strip())
        # Re-suggest the best source every time the version/loader changes
        self.source.clear()
        suggested = self.app.carry.suggest_source(draft, self.instances) if draft.game_version else None
        candidates = [i for i in self.instances]
        for inst in candidates:
            label = f"{inst.name}  ({inst.summary})"
            if suggested and inst.id == suggested.id:
                label += "  — suggested"
            self.source.addItem(label, inst.id)
        if len(candidates) > 1:
            self.source.addItem("All my instances", "__all__")
        if suggested:
            self.source.setCurrentIndex(self.source.findData(suggested.id))
        vanilla = draft.loader == "vanilla"
        has_source = bool(candidates) and not vanilla
        self.carry_box.setEnabled(has_source)
        self.source.setEnabled(has_source and self.carry_box.isChecked())
        if vanilla:
            self.carry_hint.setText("Vanilla can't load mods, so there's nothing to carry over.")
        elif not candidates:
            self.carry_hint.setText("No other instances yet. Once you have some, Craftd will offer their mods here.")
        elif suggested:
            self.carry_hint.setText(f"Craftd picked {suggested.name}: same loader, closest Minecraft version. "
                                    "You'll review every mod before anything is installed.")
        else:
            self.carry_hint.setText("None of your instances have mods yet.")

    def _accept(self):
        if not self.version.currentText().strip():
            QMessageBox.warning(self, "Craftd", "Pick a Minecraft version.")
            return
        if self.launcher.currentData() is None:
            return
        self.accept()

    def launcher_key(self) -> str | None:
        return self.launcher.currentData()

    def values(self) -> tuple[str, str, str, list[Instance]]:
        sources: list[Instance] = []
        if self.carry_box.isEnabled() and self.carry_box.isChecked():
            data = self.source.currentData()
            sources = list(self.instances) if data == "__all__" else [i for i in self.instances if i.id == data]
        return self.name.text().strip(), self.version.currentText().strip(), self.loader.currentData(), sources


# ---------------------------------------------------------------------------------------
MULTIMC_HOW_TO = ("To find it: open MultiMC and click Folders → View Instance Folder in the top toolbar, then "
                  "copy the path from File Explorer's address bar. It's the “instances” folder next to "
                  "MultiMC.exe.\nExample: C:\\MultiMC\\instances")


class ImportPrismDialog(QDialog):
    """Link existing Prism Launcher or MultiMC instances so Craftd can read and sync their mods.

    Both launchers use the same instance format. Prism's folder is found automatically; MultiMC is
    portable (it lives wherever it was unzipped), so its folder comes from Settings or is chosen here."""

    def __init__(self, app: Craftd, parent=None, launcher: str = "prism"):
        super().__init__(parent)
        self.app, self.launcher = app, launcher
        self.launcher_name = "MultiMC" if launcher == "multimc" else "Prism"
        self.setWindowTitle("Import from MultiMC" if launcher == "multimc" else "Import from Prism Launcher")
        self.setMinimumSize(520, 380)
        if launcher == "multimc":
            saved = Path(app.settings.multimc_folder) if app.settings.multimc_folder else None
            self.folder = saved if saved and saved.is_dir() else None
        else:
            defaults = prism_instance_dirs(app.settings.prism_folder)  # the folder set in Settings comes first
            self.folder = defaults[0] if defaults else None

        self.folder_label = _muted("")
        change = QPushButton("Choose Folder…")
        change.clicked.connect(self._choose)
        top = QHBoxLayout()
        top.addWidget(self.folder_label, 1)
        top.addWidget(change)

        self.list = QListWidget()
        info = _muted("Instances are linked in place: Craftd reads them where they are and only changes their "
                      "files when you ask it to. Unlinking one from Craftd never deletes it.")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Link Selected")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("primary", True)
        buttons.accepted.connect(self._link)
        buttons.rejected.connect(self.reject)
        self.linked: list[Instance] = []

        layout = QVBoxLayout(self)
        layout.addLayout(top)
        layout.addWidget(self.list, 1)
        layout.addWidget(info)
        layout.addWidget(buttons)
        self._refresh()

    def _choose(self):
        start = str(self.folder or Path.home())
        path = QFileDialog.getExistingDirectory(self, f"{self.launcher_name}'s instances folder (or one instance)",
                                                start)
        if path:
            self.folder = Path(path)
            if self.launcher == "multimc":  # remember it, so next time it opens right there
                folder = self.folder.parent if (self.folder / "mmc-pack.json").is_file() else self.folder
                self.app.settings.multimc_folder = str(folder)
                self.app.settings.save(self.app.home)
            self._refresh()

    def _refresh(self):
        self.list.clear()
        if not self.folder:
            if self.launcher == "multimc":
                self.folder_label.setText("Choose MultiMC's instances folder. " + MULTIMC_HOW_TO)
            else:
                self.folder_label.setText("Prism Launcher's instances folder wasn't found. Choose it manually "
                                          "(on macOS: ~/Library/Application Support/PrismLauncher/instances; "
                                          "press Cmd+Shift+G in the picker to type that path).")
            return
        self.folder_label.setText(str(self.folder))
        if (self.folder / "mmc-pack.json").is_file():
            found = self.app.manager.discover_prism(self.folder.parent, self.launcher)
            found = [(p, i) for p, i in found if p.resolve() == self.folder.resolve()]
        else:
            found = self.app.manager.discover_prism(self.folder, self.launcher)
        for path, info in found:
            item = QListWidgetItem(f"{info['name']}    {info['game_version']} · {LOADER_LABELS[info['loader']]}")
            item.setData(Qt.ItemDataRole.UserRole, str(path))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            self.list.addItem(item)
        if not found:
            self.list.addItem(f"No new {self.launcher_name} instances here (already linked ones are hidden).")

    def _link(self):
        for row in range(self.list.count()):
            item = self.list.item(row)
            path = item.data(Qt.ItemDataRole.UserRole)
            if path and item.checkState() == Qt.CheckState.Checked:
                self.linked.append(self.app.manager.link_prism(Path(path), self.launcher))
        self.accept()


# ---------------------------------------------------------------------------------------
class _OptionRow(QFrame):
    """One launcher in the Import from list: a radio button, a short line under it, maybe a tag."""

    def __init__(self, title: str, detail: str = "", soon: bool = False, found: bool = False):
        super().__init__()
        self.setObjectName("OptionRow")
        self.radio = QRadioButton(title)
        lay = QHBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        col = QVBoxLayout()
        col.setSpacing(2)
        col.addWidget(self.radio)
        self.detail = QLabel(("● " if found else "") + detail)
        self.detail.setObjectName("OptionFound" if found else "Muted")
        self.detail.setWordWrap(True)
        self.detail.setContentsMargins(26, 0, 0, 0)  # lines up under the radio's text
        if detail:
            col.addWidget(self.detail)
        lay.addLayout(col, 1)
        if soon:
            tag = QLabel("Coming soon")
            tag.setObjectName("SoonTag")
            lay.addWidget(tag, 0, Qt.AlignmentFlag.AlignVCenter)
            self.setEnabled(False)
        self.radio.toggled.connect(self._mark)

    def _mark(self, on: bool) -> None:
        self.setProperty("selected", on)
        self.style().unpolish(self)
        self.style().polish(self)

    def mousePressEvent(self, event) -> None:  # the whole row is clickable, not just the dot
        if self.isEnabled():
            self.radio.setChecked(True)
        super().mousePressEvent(event)


class ImportDialog(QDialog):
    """Import from: pick the launcher (or a modpack file), then Next.

    Prism is found automatically; MultiMC's folder is picked once and remembered. Other launchers
    are listed as coming soon."""

    SOON = ("Official Minecraft Launcher", "Modrinth App", "CurseForge App")

    def __init__(self, app: Craftd, parent=None):
        super().__init__(parent)
        self.app = app
        self.choice: str | None = None
        self.setWindowTitle("Import Instances")
        self.setMinimumWidth(640)
        heading = QLabel("Import from")
        heading.setObjectName("DialogTitle")
        question = QLabel("Which launcher are your instances in?")

        prism = prism_instance_dirs(app.settings.prism_folder)
        self.rows = {
            "prism": _OptionRow("Prism Launcher", "Found automatically" if prism else
                                "Not found automatically: you'll choose its folder next", found=bool(prism)),
            "multimc": _OptionRow("MultiMC", "Craftd remembers the folder you pick"),
            "mrpack": _OptionRow("Modpack file (.mrpack)", "From Share Instance, or downloaded from Modrinth"),
        }
        group = QButtonGroup(self)
        for row in self.rows.values():
            group.addButton(row.radio)
        soon_rows = [_OptionRow(name, soon=True) for name in self.SOON]

        # MultiMC's folder, shown while MultiMC is picked
        self.folder_box = QFrame()
        self.folder_box.setObjectName("FolderBox")
        fb = QVBoxLayout(self.folder_box)
        fb.setContentsMargins(12, 10, 12, 10)
        title = QLabel("MULTIMC INSTANCES FOLDER")
        title.setObjectName("SectionLabel")
        self.mmc_folder = QLineEdit(app.settings.multimc_folder)
        self.mmc_folder.setPlaceholderText(r"e.g. C:\MultiMC\instances")
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse)
        frow = QHBoxLayout()
        frow.addWidget(self.mmc_folder, 1)
        frow.addWidget(browse)
        fb.addWidget(title)
        fb.addLayout(frow)
        fb.addWidget(_muted("In MultiMC: Folders → View Instance Folder. It's the “instances” folder next to "
                            "MultiMC.exe."))

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.next_btn = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.next_btn.setText("Next")
        self.next_btn.setProperty("primary", True)
        self.buttons.accepted.connect(self._next)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(question)
        for row in list(self.rows.values()) + soon_rows:
            layout.addWidget(row)
        layout.addWidget(self.folder_box)
        layout.addStretch(1)
        layout.addWidget(self.buttons)

        for row in self.rows.values():
            row.radio.toggled.connect(lambda _on: self._changed())
        self.mmc_folder.textChanged.connect(lambda _t: self._changed())
        self.rows["prism" if prism or not app.settings.multimc_folder else "multimc"].radio.setChecked(True)
        self._changed()

    def selected(self) -> str:
        return next(key for key, row in self.rows.items() if row.radio.isChecked())

    def _changed(self) -> None:
        key = self.selected()
        self.folder_box.setVisible(key == "multimc")
        folder = self.mmc_folder.text().strip()
        self.next_btn.setEnabled(key != "multimc" or bool(folder and Path(folder).is_dir()))
        lay = self.layout()
        if lay:  # wrapped text needs its height at this exact width, or the folder box gets squashed
            lay.invalidate()
            lay.activate()
            need = lay.totalHeightForWidth(self.width()) if lay.hasHeightForWidth() else lay.totalSizeHint().height()
            need = max(need, lay.totalMinimumSize().height())
            self.setMinimumHeight(need)
            self.resize(self.width(), need)

    def _browse(self) -> None:
        start = self.mmc_folder.text().strip() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "MultiMC's instances folder", start)
        if path:
            folder = Path(path)
            if (folder / "mmc-pack.json").is_file():  # picked one instance: use the folder it's in
                folder = folder.parent
            self.mmc_folder.setText(str(folder))

    def _next(self) -> None:
        self.choice = self.selected()
        if self.choice == "multimc":
            self.app.settings.multimc_folder = self.mmc_folder.text().strip()
            self.app.settings.save(self.app.home)
        self.accept()


# ---------------------------------------------------------------------------------------
class SettingsDialog(QDialog):
    """Prism-style settings: a list of pages on the left, the chosen page on the right.

    Appearance previews live; everything else applies on Save. Cancel puts everything back.
    Clearing the cache (Storage) happens right away, since it can't be "un-saved"."""

    PAGES = ["General", "Appearance", "Mods", "Carry Over", "Storage", "Network", "About"]

    def __init__(self, app: Craftd, themer, parent=None):
        super().__init__(parent)
        from dataclasses import replace

        self.app, self.themer = app, themer
        # appearance as it's showing now (the theme manager's), everything else as saved
        self.original = replace(app.settings, theme=themer.settings.theme, text_scale=themer.settings.text_scale)
        self.setWindowTitle("Settings")
        self.resize(920, 600)
        self.setMinimumSize(640, 440)
        self.runner = Runner(lambda _msg: None, lambda _msg: None)

        self.nav = QListWidget()
        self.nav.setObjectName("SettingsNav")
        self.nav.setFixedWidth(190)
        self.pages = QStackedWidget()
        builders = [self._general, self._appearance, self._mods, self._carry, self._storage, self._network,
                    self._about]
        for name, build in zip(self.PAGES, builders):
            self.nav.addItem(name)
            self.pages.addWidget(self._page(name, build()))
        self.nav.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.nav.setCurrentRow(0)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Save")
        buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("primary", True)
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)

        body = QHBoxLayout()
        body.setSpacing(16)
        body.addWidget(self.nav)
        body.addWidget(self.pages, 1)
        layout = QVBoxLayout(self)
        layout.addLayout(body, 1)
        layout.addWidget(buttons)

        self.theme.currentIndexChanged.connect(self._preview)
        self.size.currentIndexChanged.connect(self._preview)

    # ---- page scaffolding ------------------------------------------------------------------------
    @staticmethod
    def _page(title: str, content: QWidget) -> QWidget:
        heading = QLabel(title)
        heading.setObjectName("DialogTitle")
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.addWidget(heading)
        lay.addWidget(content)
        lay.addStretch(1)
        scroll = QScrollArea()  # Large text can make a page taller than the window
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(inner)
        return scroll

    @staticmethod
    def _section(text: str) -> QLabel:
        label = QLabel(text.upper())
        label.setObjectName("SectionLabel")
        return label

    @staticmethod
    def _column(*items) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(8)
        for item in items:
            if isinstance(item, QWidget):
                lay.addWidget(item)
            elif item == "gap":
                lay.addSpacing(10)
            else:
                lay.addLayout(item)
        return w

    @staticmethod
    def _open(path: Path) -> None:
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ---- pages -----------------------------------------------------------------------------------
    def _general(self) -> QWidget:
        s = self.original
        self.check_waitlist = QCheckBox("Check the waitlist when Craftd starts")
        self.check_waitlist.setChecked(s.check_waitlist_on_start)
        waitlist_note = _muted("Craftd tells you when a waitlisted mod gets a build for your Minecraft version.")

        auto = prism_instance_dirs()
        self.prism_folder = QLineEdit(s.prism_folder)
        self.prism_folder.setPlaceholderText(f"Found automatically: {auto[0]}" if auto
                                             else "Not found automatically — choose it")
        browse = QPushButton("Browse…")
        browse.clicked.connect(self._browse_prism)
        reset = QPushButton("Find Automatically")
        reset.clicked.connect(lambda: self.prism_folder.clear())
        prism_row = QHBoxLayout()
        prism_row.addWidget(self.prism_folder, 1)
        prism_row.addWidget(browse)
        prism_row.addWidget(reset)
        prism_note = _muted("Used by Import from, + New Instance and modpacks. Set this if you use a portable "
                            "Prism or moved its instances folder.")

        self.multimc_folder = QLineEdit(s.multimc_folder)
        self.multimc_folder.setPlaceholderText("Not set: needed to import or create MultiMC instances")
        mmc_browse = QPushButton("Browse…")
        mmc_browse.clicked.connect(self._browse_multimc)
        mmc_clear = QPushButton("Clear")
        mmc_clear.clicked.connect(lambda: self.multimc_folder.clear())
        mmc_row = QHBoxLayout()
        mmc_row.addWidget(self.multimc_folder, 1)
        mmc_row.addWidget(mmc_browse)
        mmc_row.addWidget(mmc_clear)
        mmc_note = _muted("MultiMC runs from wherever you unzipped it, so Craftd can't find it on its own. "
                          + MULTIMC_HOW_TO)

        data = QLabel(str(self.app.home))
        data.setObjectName("Muted")
        data.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        data.setWordWrap(True)
        open_data = QPushButton("Open Data Folder")
        open_data.clicked.connect(lambda: self._open(self.app.home))
        return self._column(self._section("Waitlist"), self.check_waitlist, waitlist_note, "gap",
                            self._section("Prism Launcher instances folder"), prism_row, prism_note, "gap",
                            self._section("MultiMC instances folder"), mmc_row, mmc_note, "gap",
                            self._section("Craftd's data folder"), data, flow_row(open_data))

    def _browse_multimc(self) -> None:
        start = self.multimc_folder.text() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "MultiMC's instances folder", start)
        if path:
            self.multimc_folder.setText(path)

    def _browse_prism(self) -> None:
        start = self.prism_folder.text() or str(Path.home())
        path = QFileDialog.getExistingDirectory(self, "Prism's instances folder", start)
        if path:
            self.prism_folder.setText(path)

    def _appearance(self) -> QWidget:
        from ..settings import SYSTEM_THEME_LABEL, SYSTEM_THEME_WHERE, TEXT_SIZES, THEMES
        self.theme = QComboBox()
        for key, label in THEMES.items():
            self.theme.addItem(label, key)
        self.theme.setCurrentIndex(self.theme.findData(self.original.theme))
        self.size = QComboBox()
        for scale, label in TEXT_SIZES.items():
            self.size.addItem(label, scale)
        self.size.setCurrentIndex(max(0, self.size.findData(self.original.text_scale)))
        form = QFormLayout()
        form.addRow("Appearance", self.theme)
        form.addRow("Text size", self.size)
        return self._column(form, _muted("Changes show up right away. Dark is styled after the block of netherite, "
                                         f"Light after the block of iron. “{SYSTEM_THEME_LABEL}” picks one by "
                                         f"following {SYSTEM_THEME_WHERE}."))

    def _mods(self) -> QWidget:
        s = self.original
        self.builds = QComboBox()
        self.builds.addItem("The stable build (recommended)", True)
        self.builds.addItem("The newest build, even betas", False)
        self.builds.setCurrentIndex(0 if s.stable_first else 1)
        builds_label = QLabel("When a mod has stable and beta builds, pick:")
        builds_note = _muted("Used when installing, carrying over and updating. Betas are newer but more likely "
                             "to crash; if a mod only has betas, Craftd uses the beta either way.")
        self.auto_deps = QCheckBox("Install required dependencies (recommended)")
        self.auto_deps.setChecked(s.auto_dependencies)
        deps_note = _muted("For example, Fabric API for most Fabric mods. When off, Craftd lists what's "
                           "missing instead.")
        self.hide_installed = QCheckBox("Hide mods I already have in Add from Modrinth")
        self.hide_installed.setChecked(s.hide_installed)
        return self._column(self._section("Builds"), builds_label, flow_row(self.builds), builds_note, "gap",
                            self._section("Dependencies"), self.auto_deps, deps_note, "gap",
                            self._section("Add from Modrinth"), self.hide_installed)

    def _carry(self) -> QWidget:
        s = self.original
        self.c_local = QCheckBox("Jars that aren't on Modrinth (copied as-is)")
        self.c_local.setChecked(s.carry_copy_local)
        self.c_packs = QCheckBox("Packs the new instance doesn't have")
        self.c_packs.setChecked(s.carry_packs)
        self.c_config = QCheckBox("Mod settings it doesn't have")
        self.c_config.setChecked(s.carry_config)
        self.c_opts = QCheckBox("Options && server list, if it has none yet")
        self.c_opts.setChecked(s.carry_options_servers)
        note = _muted("What the Carry Over tab ticks for you. Packs means resource and shader packs; options "
                      "includes keybinds. You can still change each one there before carrying over. Nothing the new instance already has is replaced unless you choose "
                      "“Replace what's already there” (and Craftd backs it up first).")
        return self._column(self._section("Ticked by default"), self.c_local, self.c_packs, self.c_config,
                            self.c_opts, "gap", note)

    def _storage(self) -> QWidget:
        from ..extras import human_size
        self._human = human_size
        self.cache_form = QFormLayout()
        self.cache_total = QLabel()
        clear = QPushButton("Clear Cache")
        clear.clicked.connect(self._clear_cache)
        open_data = QPushButton("Open Data Folder")
        open_data.clicked.connect(lambda: self._open(self.app.home))
        note = _muted("The cache is what Craftd can download again: it makes lists and icons load faster. "
                      "Clearing it doesn't touch your instances, mods, settings or waitlists.")
        self._fill_cache()
        return self._column(self._section("Cache"), self.cache_form, self.cache_total, note, "gap",
                            flow_row(clear, open_data))

    def _fill_cache(self) -> None:
        while self.cache_form.rowCount():
            self.cache_form.removeRow(0)
        usage = self.app.cache_usage()
        for label, size in usage:
            value = QLabel(self._human(size))
            value.setObjectName("Muted")
            self.cache_form.addRow(label, value)
        total = sum(size for _, size in usage)
        self.cache_total.setText(f"Total: {self._human(total)}" if usage else "The cache is empty.")

    def _clear_cache(self) -> None:
        if QMessageBox.question(self, "Clear cache", "Delete Craftd's cache? It's rebuilt as needed "
                                "(mod lookups need internet the next time).") != QMessageBox.StandardButton.Yes:
            return
        self.app.clear_cache()
        self._fill_cache()

    def _network(self) -> QWidget:
        from ..settings import PROXY_MODES
        s = self.original
        self.proxy_group = QButtonGroup(self)
        radios = []
        for i, (key, label) in enumerate(PROXY_MODES.items()):
            radio = QRadioButton(label)
            radio.setProperty("mode", key)
            radio.setChecked(key == s.proxy)
            self.proxy_group.addButton(radio, i)
            radios.append(radio)
        self.proxy_host = QLineEdit(s.proxy_host)
        self.proxy_host.setPlaceholderText("127.0.0.1")
        self.proxy_port = QSpinBox()
        self.proxy_port.setRange(1, 65535)
        self.proxy_port.setValue(s.proxy_port)
        host_row = QHBoxLayout()
        host_row.addWidget(QLabel("Address"))
        host_row.addWidget(self.proxy_host, 1)
        host_row.addWidget(QLabel("Port"))
        host_row.addWidget(self.proxy_port)
        self.proxy_group.buttonToggled.connect(lambda *_: self._proxy_fields())
        self._proxy_fields()

        self.timeout = QSpinBox()
        self.timeout.setRange(5, 120)
        self.timeout.setSuffix(" seconds")
        self.timeout.setValue(s.timeout)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.FieldsStayAtSizeHint)
        form.addRow("Give up after", self.timeout)

        test = QPushButton("Test Connection")
        test.clicked.connect(self._test_connection)
        self.test_result = _muted("")
        note = _muted("Only Craftd's own downloads (Modrinth) use this. Minecraft and Prism have their own "
                      "network settings.")
        return self._column(self._section("Proxy"), *radios, host_row, "gap", self._section("Requests"), form,
                            "gap", flow_row(test), self.test_result, note)

    def _proxy_mode(self) -> str:
        checked = self.proxy_group.checkedButton()
        return checked.property("mode") if checked else "system"

    def _proxy_fields(self) -> None:
        on = self._proxy_mode() == "http"
        self.proxy_host.setEnabled(on)
        self.proxy_port.setEnabled(on)

    def _test_connection(self) -> None:
        from ..modrinth import ModrinthClient
        s = self.current()
        self.test_result.setText("Connecting…")

        def work(_progress):
            client = ModrinthClient(timeout=s.timeout)
            client.configure_network(s.proxy, s.proxy_host, s.proxy_port, s.timeout)
            return client.ping()

        self.runner.run(work, on_done=lambda text: self.test_result.setText("✓ " + text),
                        on_error=lambda msg: self.test_result.setText(f"Couldn't reach Modrinth: {msg}"))

    def _about(self) -> QWidget:
        import platform

        import PySide6

        from .. import __version__
        name = QLabel(f"Craftd {__version__}")
        name.setObjectName("InstanceTitle")
        logo = QLabel()
        logo.setPixmap(theme.logo_pixmap(64))
        logo.setAccessibleName("Craftd logo")
        title_row = QHBoxLayout()
        title_row.setSpacing(16)
        title_row.addWidget(logo)
        title_row.addWidget(name, 1)
        tagline = _muted("A personal Minecraft launcher that carries your mods, packs and settings from one "
                         "instance to the next.")
        credits = QLabel(
            "Made by <a href='https://github.com/mahirmalickk'>mahirmalickk</a><br>"
            "Mod data from <a href='https://modrinth.com'>Modrinth</a><br>"
            "Font: <a href='https://github.com/IdreesInc/Monocraft'>Monocraft</a> by Idrees Hassan "
            "(SIL Open Font License 1.1)<br>"
            f"Python {platform.python_version()} · PySide6 {PySide6.__version__}")
        credits.setTextFormat(Qt.TextFormat.RichText)
        credits.setOpenExternalLinks(True)
        credits.setWordWrap(True)
        from ..log import log_file
        from .theme import FONTS_DIR
        license_btn = QPushButton("Font License")
        license_btn.clicked.connect(lambda: self._open(FONTS_DIR / "monocraft" / "OFL.txt"))
        log_btn = QPushButton("Open Log Folder")
        log_btn.clicked.connect(lambda: self._open(self.app.home))
        log_note = _muted(f"Reporting a bug? Attach {log_file(self.app.home).name} from the log folder: it shows "
                          "what Craftd was doing when something went wrong.")
        return self._column(title_row, tagline, "gap", credits, "gap", flow_row(log_btn, license_btn), log_note)

    # ---- saving ----------------------------------------------------------------------------------
    def current(self):
        from ..settings import Settings
        return Settings(
            theme=self.theme.currentData(), text_scale=self.size.currentData(),
            check_waitlist_on_start=self.check_waitlist.isChecked(),
            prism_folder=self.prism_folder.text().strip(), multimc_folder=self.multimc_folder.text().strip(),
            stable_first=bool(self.builds.currentData()), auto_dependencies=self.auto_deps.isChecked(),
            hide_installed=self.hide_installed.isChecked(),
            carry_copy_local=self.c_local.isChecked(), carry_packs=self.c_packs.isChecked(),
            carry_config=self.c_config.isChecked(), carry_options_servers=self.c_opts.isChecked(),
            proxy=self._proxy_mode(), proxy_host=self.proxy_host.text().strip(),
            proxy_port=self.proxy_port.value(), timeout=self.timeout.value(),
            last_launcher=self.app.settings.last_launcher)

    def _preview(self, *_):
        from dataclasses import replace
        self.themer.apply(replace(self.original, theme=self.theme.currentData(),
                                  text_scale=self.size.currentData()))

    def _save(self):
        new = self.current()
        self.app.apply_settings(new)
        self.themer.apply(new)
        new.save(self.app.home)
        self.accept()

    def reject(self):
        self.themer.apply(self.original)
        super().reject()


# ---------------------------------------------------------------------------------------
class IssuesDialog(QDialog):
    """The compatibility check's findings, with what to do about each."""

    def __init__(self, issues, inst: Instance, parent=None):
        super().__init__(parent)
        from html import escape

        from PySide6.QtWidgets import QTextBrowser
        self.setWindowTitle(f"Compatibility check: {inst.name}")
        self.resize(640, 480)
        head = _muted(f"Checked against Minecraft {inst.game_version} and {inst.loader_text}, using the rules each "
                      "mod declares in its own files.")
        body = QTextBrowser()
        body.setOpenExternalLinks(False)
        rows = []
        for i in issues:
            tag = "Problem" if i.severity == "error" else "Warning"
            fix = f"<br><i>What to do:</i> {escape(i.fix)}" if i.fix else ""
            rows.append(f"<p>{theme.strong(f'{tag}: {escape(i.mod)}')}<br>{escape(i.message)}{fix}</p>")
        body.setHtml("".join(rows) or "<p>No problems found.</p>")
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        layout = QVBoxLayout(self)
        layout.addWidget(head)
        layout.addWidget(body, 1)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignRight)



# ---------------------------------------------------------------------------------------
class ChoosePacksDialog(QDialog):
    """Pick which resource packs and shader packs to bring along."""

    def __init__(self, found, chosen: set, parent=None, already: set | None = None):
        super().__init__(parent)
        from ..extras import PACK_FOLDERS, _size, human_size
        self.found = found
        self.setWindowTitle(f"Packs from {found.source.name}")
        self.resize(680, 420)
        heading = QLabel("Tick the packs to bring along")
        heading.setObjectName("SectionLabel")
        self.list = QListWidget()
        for pack in found.packs:
            kind = PACK_FOLDERS.get(pack.parent.name, "Pack").rstrip("s")
            note = " · already copied" if already and pack in already else ""
            item = QListWidgetItem(f"{pack.name}    {kind} · {human_size(_size(pack))}{note}")
            item.setData(Qt.ItemDataRole.UserRole, str(pack))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if pack in chosen else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        note = _muted("Packs are copied as-is. Ones the new instance already has are left alone.")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("primary", True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(self.list, 1)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def chosen(self) -> set:
        out = set()
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.checkState() == Qt.CheckState.Checked:
                out.add(Path(item.data(Qt.ItemDataRole.UserRole)))
        return out



# ---------------------------------------------------------------------------------------
class EditInstanceDialog(QDialog):
    """Change an instance's name, Minecraft version or loader (e.g. 26.3 Vanilla → 26.3 Fabric).

    Loader versions come from the launcher's own list, named the way it expects them."""

    def __init__(self, app: Craftd, inst: Instance, runner: Runner, parent=None):
        super().__init__(parent)
        from ..instances import LOADER_LABELS
        from ..mods import mod_files
        self.app, self.inst, self.runner = app, inst, runner
        self.launcher = inst.launcher if inst.kind == "prism" else "prism"
        self.result_instance: Instance | None = None
        self._request = 0
        self.mod_count = len(mod_files(inst.mods_dir)) if inst.mods_dir.is_dir() else 0
        self.setWindowTitle(f"Edit Instance: {inst.name}")

        self.name = QLineEdit(inst.name)
        self.name.setMinimumWidth(320)  # keeps the window wide enough to read
        self.mc = QComboBox()
        self.mc.setEditable(True)  # snapshots and versions Modrinth doesn't list can be typed in
        releases = [v["version"] for v in app.game_versions if v.get("version_type") == "release"]
        if inst.game_version not in releases:
            releases.insert(0, inst.game_version)
        self.mc.addItems(releases)
        self.mc.setCurrentText(inst.game_version)
        self.loader = QComboBox()
        for key in ("vanilla", "fabric", "quilt", "neoforge", "forge"):
            self.loader.addItem(LOADER_LABELS[key], key)
        self.loader.setCurrentIndex(self.loader.findData(inst.loader))
        self.loader_version = QComboBox()
        self.version_status = _muted("")

        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("Minecraft version", self.mc)
        form.addRow("Loader", self.loader)
        form.addRow("Loader version", self.loader_version)

        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning_box = QFrame()
        self.warning_box.setObjectName("WarnBanner")
        box = QVBoxLayout(self.warning_box)
        box.setContentsMargins(12, 10, 12, 10)
        box.addWidget(self.warning)
        if inst.kind == "prism":
            where = _muted(f"Craftd changes {inst.launcher_label}'s own instance file (mmc-pack.json) and saves a "
                           f"backup next to it first. {inst.launcher_label} needs to be closed while it saves.")
        else:
            where = _muted("This is a Craftd instance: only Craftd's own record changes.")

        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save_btn = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_btn.setProperty("primary", True)
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(self.version_status)
        layout.addWidget(self.warning_box)
        layout.addWidget(where)
        layout.addWidget(self.buttons)

        # a fixed width (wider with Large text) so wrapped warnings get exactly the height they need
        self.setFixedWidth(max(600, layout.totalMinimumSize().width()))
        self.mc.currentTextChanged.connect(lambda _: self._changed())
        self.loader.currentIndexChanged.connect(lambda _: self._changed())
        self._changed()

    # ---- choices ---------------------------------------------------------------------------------
    def chosen(self) -> tuple[str, str, str, str | None]:
        loader = self.loader.currentData()
        version = self.loader_version.currentData() if loader != "vanilla" else None
        return self.name.text().strip() or self.inst.name, self.mc.currentText().strip(), loader, version

    def _changed(self) -> None:
        self._update_warning()
        loader, mc = self.loader.currentData(), self.mc.currentText().strip()
        self.loader_version.clear()
        if loader == "vanilla":
            self.loader_version.setEnabled(False)
            self.version_status.setText("Vanilla Minecraft has no loader.")
            self.save_btn.setEnabled(bool(mc))
            return
        self.loader_version.setEnabled(False)
        self.save_btn.setEnabled(False)
        self.version_status.setText(f"Loading {self.loader.currentText()} versions for Minecraft {mc}…")
        self._request += 1
        token = self._request
        launcher = self.launcher

        def done(versions):
            if token == self._request:  # ignore answers for a choice that has since changed
                self._fill_versions(versions)

        def failed(msg):
            if token == self._request:
                self.version_status.setText(f"Couldn't load loader versions: {msg}")

        self.runner.run(lambda p: self.app.loader_versions(loader, mc, launcher), on_done=done, on_error=failed)

    def _fill_versions(self, versions) -> None:
        from ..loaders import default_version
        loader, mc = self.loader.currentData(), self.mc.currentText().strip()
        if not versions:
            self.version_status.setText(f"{self.loader.currentText()} has no builds for Minecraft {mc} yet.")
            return
        for v in versions:
            self.loader_version.addItem(v.label, v.version)
        pick = default_version(versions).version
        if loader == self.inst.loader and mc == self.inst.game_version and self.inst.loader_version:
            if self.loader_version.findData(self.inst.loader_version) < 0:  # keep the one it has now
                self.loader_version.insertItem(0, f"{self.inst.loader_version} (current)", self.inst.loader_version)
            pick = self.inst.loader_version
        self.loader_version.setCurrentIndex(self.loader_version.findData(pick))
        self.loader_version.setEnabled(True)
        self.save_btn.setEnabled(True)
        self.version_status.setText(f"{len(versions)} {self.loader.currentText()} builds for Minecraft {mc}. "
                                    "Recommended (or newest stable) is picked for you.")
        self._fit()

    def _update_warning(self) -> None:
        from ..instances import LOADER_LABELS, loader_family
        loader, mc = self.loader.currentData(), self.mc.currentText().strip()
        notes = []
        if self.mod_count and loader_family(loader) != loader_family(self.inst.loader):
            old = LOADER_LABELS[self.inst.loader]
            if loader == "vanilla":
                notes.append(f"⚠ This instance has {self.mod_count} mod(s). Vanilla Minecraft won't load them.")
            else:
                notes.append(f"⚠ This instance has {self.mod_count} mod(s) made for {old}. They won't load on "
                             f"{LOADER_LABELS[loader]}: remove them afterwards, or use Carry Over to get "
                             f"{LOADER_LABELS[loader]} versions.")
        if self.mod_count and mc and mc != self.inst.game_version and loader != "vanilla":
            notes.append(f"⚠ The mods are for Minecraft {self.inst.game_version}. After saving, use Check for "
                         f"Updates (or Carry Over) to get builds for {mc}.")
        self.warning.setText("\n\n".join(notes))
        self.warning_box.setVisible(bool(notes))
        # a wrapped label doesn't report its full height on its own: give it exactly what its lines need
        m = self.layout().contentsMargins() if self.layout() else None
        text_w = self.width() - (m.left() + m.right() if m else 22) - 2 * 12 - 2
        self.warning.setMinimumHeight(self.warning.heightForWidth(text_w) if notes else 0)
        self._fit()

    def _fit(self) -> None:
        """Grow (or shrink) to fit the current text: recalculate the layout first, then resize."""
        self.warning_box.layout().activate()  # the warning box's own layout first, then the dialog's
        self.warning_box.updateGeometry()
        if self.layout():
            self.layout().invalidate()
            self.layout().activate()
        lay = self.layout()
        if not lay:
            return
        # wrapped labels count as one line in the plain minimum: ask for the height at this exact width
        need = lay.totalHeightForWidth(self.width()) if lay.hasHeightForWidth() else lay.totalMinimumSize().height()
        need = max(need, lay.totalMinimumSize().height())
        self.setMinimumHeight(need)
        self.resize(self.width(), need)

    # ---- saving ----------------------------------------------------------------------------------
    def _save(self) -> None:
        from ..loaders import launcher_running
        name, mc, loader, version = self.chosen()
        if not mc:
            return
        if loader != "vanilla" and not version:
            return
        if self.inst.kind == "prism":
            while launcher_running(self.inst.launcher):
                answer = QMessageBox.warning(
                    self, "Close " + self.inst.launcher_label,
                    f"{self.inst.launcher_label} is open. Close it first: it can overwrite the change while "
                    "it's running.\n\nClick Retry once it's closed.",
                    QMessageBox.StandardButton.Retry | QMessageBox.StandardButton.Cancel)
                if answer != QMessageBox.StandardButton.Retry:
                    return
        try:
            self.result_instance = self.app.manager.edit(self.inst, name, mc, loader, version)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "Craftd", f"Couldn't save the change: {exc}")
            return
        self.accept()


# ---------------------------------------------------------------------------------------
class ChooseWorldsDialog(QDialog):
    """Pick worlds to copy over. Ones that can't go to this instance are shown, greyed out, with why."""

    def __init__(self, found: list, target: Instance, order, chosen: set, parent=None, missing_mods=()):
        super().__init__(parent)
        from ..extras import human_size
        from ..worlds import why_not
        self.setWindowTitle(f"Worlds for {target.name}")
        self.resize(700, 440)
        heading = QLabel("Tick the worlds to copy")
        heading.setObjectName("SectionLabel")
        self.list = QListWidget()
        self.list.setObjectName("Plain")
        for w in found:
            reason = why_not(w, target, order)
            played = f"Minecraft {w.version}" if w.version else "an old version (before 1.9)"
            text = f"{w.name}    {played} · {human_size(w.size)}"
            if reason:
                text += f"\n    {reason}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, str(w.path))
            if reason:
                item.setFlags(Qt.ItemFlag.NoItemFlags)
            else:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Checked if w.path in chosen else Qt.CheckState.Unchecked)
            self.list.addItem(item)
        notes = [f"Worlds are copied: the originals stay playable in the old instance. Minecraft upgrades a copied "
                 f"world to {target.game_version} the first time you open it there."]
        if missing_mods:
            names = ", ".join(list(missing_mods)[:6]) + ("…" if len(missing_mods) > 6 else "")
            notes.append(f"⚠ The old instance has mods this one won't have yet ({names}). Blocks and items from "
                         "those mods disappear from a world when it's opened without them.")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty("primary", True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(self.list, 1)
        for n in notes:
            layout.addWidget(_muted(n))
        layout.addWidget(buttons)

    def chosen(self) -> set:
        out = set()
        for row in range(self.list.count()):
            item = self.list.item(row)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable and item.checkState() == Qt.CheckState.Checked:
                out.add(Path(item.data(Qt.ItemDataRole.UserRole)))
        return out


# ---------------------------------------------------------------------------------------
class ShareDialog(QDialog):
    """Share Instance: save the instance as a small .mrpack file to send to a friend."""

    def __init__(self, app: Craftd, inst: Instance, runner: Runner, parent=None):
        super().__init__(parent)
        from ..extras import human_size
        from ..worlds import scan
        self.app, self.inst, self.runner = app, inst, runner
        self.saved: Path | None = None
        self.setWindowTitle(f"Share Instance: {inst.name}")
        self.setMinimumWidth(640)
        heading = QLabel("Share Instance")
        heading.setObjectName("DialogTitle")
        intro = _muted("Saves a small .mrpack file you can send to a friend. Mods go in as Modrinth links, so the "
                       "file stays tiny and they get exactly the same builds. They open it in Craftd with "
                       "Import from → Modpack file, or in Prism or the Modrinth App.")
        gd = inst.game_dir
        self.config = QCheckBox("Mod settings (config folder)")
        self.resourcepacks = QCheckBox("Resource packs")
        self.shaderpacks = QCheckBox("Shader packs")
        self.options = QCheckBox("Options && keybinds")
        self.servers = QCheckBox("Server list")
        self.local_jars = QCheckBox("Jars not on Modrinth (put in as files)")
        for box, there, on in ((self.config, (gd / "config").is_dir(), True),
                               (self.resourcepacks, (gd / "resourcepacks").is_dir(), True),
                               (self.shaderpacks, (gd / "shaderpacks").is_dir(), True),
                               (self.options, (gd / "options.txt").is_file(), True),
                               (self.servers, (gd / "servers.dat").is_file(), False),
                               (self.local_jars, True, True)):
            box.setChecked(on and there)
            box.setEnabled(there)
        self.worlds = QListWidget()
        self.worlds.setObjectName("Plain")
        self.worlds.setMaximumHeight(130)
        found = scan(inst)
        for w in found:
            item = QListWidgetItem(f"{w.name}    {human_size(w.size)}")
            item.setData(Qt.ItemDataRole.UserRole, w.folder)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.worlds.addItem(item)
        self.status = _muted("")
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        self.save_btn = self.buttons.button(QDialogButtonBox.StandardButton.Save)
        self.save_btn.setText("Save .mrpack…")
        self.save_btn.setProperty("primary", True)
        self.buttons.accepted.connect(self._save)
        self.buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(intro)
        layout.addWidget(SettingsDialog._section("Include"))
        for box in (self.config, self.resourcepacks, self.shaderpacks, self.options, self.servers, self.local_jars):
            layout.addWidget(box)
        layout.addWidget(SettingsDialog._section("Worlds (big: off unless you tick them)"))
        if found:
            layout.addWidget(self.worlds)
        else:
            layout.addWidget(_muted("This instance has no worlds."))
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)

    def options_chosen(self):
        from ..mrpack import ShareOptions
        worlds = [self.worlds.item(r).data(Qt.ItemDataRole.UserRole) for r in range(self.worlds.count())
                  if self.worlds.item(r).checkState() == Qt.CheckState.Checked]
        return ShareOptions(config=self.config.isChecked(), resourcepacks=self.resourcepacks.isChecked(),
                            shaderpacks=self.shaderpacks.isChecked(), options=self.options.isChecked(),
                            servers=self.servers.isChecked(), local_jars=self.local_jars.isChecked(), worlds=worlds)

    def _save(self, dest: Path | None = None) -> None:
        from ..launchers import folder_name
        from ..mrpack import export
        if dest is None:
            start = Path.home() / "Desktop"
            start = start if start.is_dir() else Path.home()
            path, _ = QFileDialog.getSaveFileName(self, "Save the shared instance",
                                                  str(start / f"{folder_name(self.inst.name, Path('/nonexistent'))}.mrpack"),
                                                  "Modrinth modpack (*.mrpack)")
            if not path:
                return
            dest = Path(path if path.lower().endswith(".mrpack") else path + ".mrpack")
        app, inst, options = self.app, self.inst, self.options_chosen()
        self.save_btn.setEnabled(False)

        def work(progress):
            version = inst.loader_version
            if inst.loader != "vanilla" and not version:
                version = app.default_loader_version(inst.loader, inst.game_version,
                                                     inst.launcher if inst.kind == "prism" else "prism")
            return export(app.scanner, app.client, inst, dest, options, version, progress)

        def done(report):
            self.saved = dest
            self.save_btn.setEnabled(True)
            box = QMessageBox(self)
            box.setWindowTitle("Shared")
            box.setText(report.summary() + "\n\nSend this file to your friend.")
            show = box.addButton("Show in Folder", QMessageBox.ButtonRole.ActionRole)
            box.addButton(QMessageBox.StandardButton.Ok)
            box.exec()
            if box.clickedButton() is show:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(dest.parent)))
            self.accept()

        def failed(msg):
            self.save_btn.setEnabled(True)
            self.status.setText(f"Couldn't save it: {msg}")

        self.runner.run(work, on_done=done, on_error=failed, progress=self.status.setText)


# ---------------------------------------------------------------------------------------
class InstallPackDialog(QDialog):
    """Before installing a modpack file: what it is, its name, and which launcher to make it in."""

    def __init__(self, app: Craftd, index, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Install {index.name}")
        self.setMinimumWidth(500)
        heading = QLabel(index.name)
        heading.setObjectName("DialogTitle")
        heading.setWordWrap(True)
        what = _muted(f"Minecraft {index.game_version} · {index.loader_text} · {len(index.files)} file(s) to "
                      "download" + (f"\n{index.summary}" if index.summary else ""))
        self.name = QLineEdit(index.name)
        self.launcher, note = launcher_combo(app)
        form = QFormLayout()
        form.addRow("Name", self.name)
        form.addRow("Create in", self.launcher)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        ok = buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setText("Install")
        ok.setProperty("primary", True)
        ok.setEnabled(self.launcher.currentData() is not None)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(what)
        layout.addLayout(form)
        layout.addWidget(note)
        layout.addWidget(buttons)

    def values(self) -> tuple[str, str]:
        return self.name.text().strip(), self.launcher.currentData()


# ---------------------------------------------------------------------------------------
class ChangeVersionDialog(QDialog):
    """Right-click a mod → Change Version: pick any build of it for this instance (older ones too)."""

    def __init__(self, app: Craftd, runner: Runner, inst: Instance, mod, parent=None):
        super().__init__(parent)
        from ..instances import compatible_loaders
        self.app, self.inst, self.mod = app, inst, mod
        self.chosen_version: dict | None = None
        self.setWindowTitle(f"Change Version: {mod.title}")
        self.resize(560, 420)
        heading = QLabel(f"Builds of {mod.title} for {inst.summary}")
        heading.setObjectName("SectionLabel")
        heading.setWordWrap(True)
        self.list = QListWidget()
        self.list.setObjectName("Plain")
        self.status = _muted("Loading versions from Modrinth…")
        self.buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        self.ok.setText("Install This Version")
        self.ok.setProperty("primary", True)
        self.ok.setEnabled(False)
        self.buttons.accepted.connect(self._pick)
        self.buttons.rejected.connect(self.reject)
        self.list.currentRowChanged.connect(self._row)
        self.list.itemDoubleClicked.connect(lambda _i: self._pick())
        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(self.list, 1)
        layout.addWidget(self.status)
        layout.addWidget(self.buttons)
        pid = mod.project_id
        runner.run(lambda p: app.client.project_versions(pid, compatible_loaders(inst.loader), [inst.game_version]),
                   on_done=self._fill, on_error=lambda msg: self.status.setText(f"Couldn't load versions: {msg}"),
                   progress=lambda _m: None)

    def _fill(self, versions: list[dict]) -> None:
        self.versions = versions
        for v in versions:
            kind = v.get("version_type", "release")
            date = (v.get("date_published") or "")[:10]
            text = f"{v.get('version_number')}    {'' if kind == 'release' else kind + ' · '}{date}"
            if v.get("id") == self.mod.version_id:
                text += "    (installed)"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, v.get("id"))
            self.list.addItem(item)
        self.status.setText(f"{len(versions)} build(s). The one you pick replaces the jar you have now."
                            if versions else f"Modrinth has no builds of {self.mod.title} for {self.inst.summary}.")

    def _row(self, row: int) -> None:
        ok = 0 <= row < len(getattr(self, "versions", [])) and self.versions[row].get("id") != self.mod.version_id
        self.ok.setEnabled(ok)

    def _pick(self) -> None:
        row = self.list.currentRow()
        if not self.ok.isEnabled() or row < 0:
            return
        self.chosen_version = self.versions[row]
        self.accept()
