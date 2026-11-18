"""The Mods tab and the Carry Over tab shown for the selected instance."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

from ..core import Craftd
from ..instances import Instance
from ..mods import LocalMod
from ..sync import STATUS_LABELS, Candidate, Status
from .browser import BrowseModsDialog
from . import theme
from .widgets import flow_row
from .workers import Runner


def _table(headers: list[str], stretch_cols: tuple[int, ...]) -> QTableWidget:
    """Columns in stretch_cols share the free space (long names elide); the rest fit their contents."""
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.verticalHeader().hide()
    t.setShowGrid(False)
    t.setAlternatingRowColors(False)
    t.setWordWrap(False)  # one line per mod; long names end in "…"
    t.setTextElideMode(Qt.TextElideMode.ElideRight)
    header = t.horizontalHeader()
    header.setDefaultAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
    for col in range(len(headers)):
        mode = QHeaderView.ResizeMode.Stretch if col in stretch_cols else QHeaderView.ResizeMode.ResizeToContents
        header.setSectionResizeMode(col, mode)
    return t


def _check_item(checked: bool, enabled: bool = True) -> QTableWidgetItem:
    item = QTableWidgetItem()
    flags = Qt.ItemFlag.ItemIsSelectable
    if enabled:
        flags |= Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable
    item.setFlags(flags)
    item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
    return item


def _text_item(text: str, role: str | None = None, tooltip: str | None = None, mono: bool = False,
               bold: bool = False) -> QTableWidgetItem:
    """A table cell. `role` is a theme color name (muted, faint, available...)."""
    item = QTableWidgetItem(text)
    if role:
        item.setForeground(QColor(theme.color(role)))
    if mono:
        item.setFont(theme.mono_font())
    elif bold:
        f = item.font()
        f.setWeight(theme.weight("demibold"))
        item.setFont(f)
    item.setToolTip(tooltip or text)  # hovering a cell shortened with "…" shows all of it
    return item


# =======================================================================================
class ModsTab(QWidget):
    mods_changed = Signal()

    def __init__(self, app: Craftd, runner: Runner):
        super().__init__()
        self.app, self.runner = app, runner
        self.inst: Instance | None = None
        self.mods: list[LocalMod] = []
        self.updates: dict[str, dict] = {}

        self.table = _table(["On", "Mod", "Version", "File", "Source"], stretch_cols=(1, 3))
        self.table.itemChanged.connect(self._item_changed)

        self.add_btn = QPushButton("Add from Modrinth…")
        self.add_btn.setProperty("primary", True)
        self.add_btn.clicked.connect(self._browse)
        self.check_btn = QPushButton("Check for Updates")
        self.check_btn.clicked.connect(self._check_updates)
        self.update_btn = QPushButton("Update All")
        self.update_btn.clicked.connect(self._update_all)
        self.update_btn.hide()
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self._remove)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self.reload)
        self.count = QLabel()
        self.count.setObjectName("Muted")

        buttons = QHBoxLayout()
        buttons.addWidget(flow_row(self.add_btn, self.check_btn, self.update_btn, self.remove_btn,
                                   self.refresh_btn), 1)
        buttons.addWidget(self.count, 0, Qt.AlignmentFlag.AlignTop)

        self.issues: list = []
        self.problems = QFrame()
        self.problems.setObjectName("WarnBanner")
        self.problems_label = QLabel()
        self.problems_label.setWordWrap(True)
        self.problems_btn = QPushButton("Show Problems")
        self.problems_btn.clicked.connect(self._show_problems)
        pl = QHBoxLayout(self.problems)
        pl.setContentsMargins(10, 6, 10, 6)
        pl.addWidget(self.problems_label, 1)
        pl.addWidget(self.problems_btn)
        self.problems.hide()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.addLayout(buttons)
        layout.addWidget(self.problems)
        layout.addWidget(self.table, 1)

    def set_instance(self, inst: Instance | None) -> None:
        self.inst = inst
        self.issues = []
        self.problems.hide()
        self.updates = {}
        self.update_btn.hide()
        self.table.setRowCount(0)
        enabled = bool(inst and inst.loader != "vanilla")
        for b in (self.add_btn, self.check_btn, self.remove_btn, self.refresh_btn):
            b.setEnabled(enabled)
        if inst:
            self.reload()

    def retheme(self) -> None:
        if self.inst and self.mods:
            self._fill(self.inst, self.mods)

    def reload(self) -> None:
        inst = self.inst
        if not inst:
            return
        def work(progress):
            mods = self.app.scanner.scan(inst)
            progress("Checking mod compatibility…")
            return mods, self.app.installer.check_instance(inst, mods)

        def done(result):
            mods, issues = result
            if self.inst and inst.id == self.inst.id:
                self.issues = issues
            self._fill(inst, mods)
            self._show_issue_bar()

        self.runner.run(work, on_done=done)

    def _show_issue_bar(self) -> None:
        errors = [i for i in self.issues if i.severity == "error"]
        warnings = [i for i in self.issues if i.severity != "error"]
        if not self.issues:
            self.problems.hide()
            return
        parts = []
        if errors:
            parts.append(f"{len(errors)} problem{'s' if len(errors) != 1 else ''} that will stop the game from starting")
        if warnings:
            parts.append(f"{len(warnings)} warning{'s' if len(warnings) != 1 else ''}")
        first = (errors or warnings)[0]
        self.problems_label.setText(f"⚠ Compatibility check: {' and '.join(parts)}. "
                                    f"First: {first.mod}: {first.message}")
        self.problems.show()

    def _show_problems(self) -> None:
        from .dialogs import IssuesDialog
        IssuesDialog(self.issues, self.inst, self).exec()

    def _fill(self, inst: Instance, mods: list[LocalMod]) -> None:
        if not self.inst or inst.id != self.inst.id:
            return  # the user switched instances while we were scanning
        self.mods = mods
        self.table.blockSignals(True)
        self.table.setRowCount(len(mods))
        bad_files = {}
        for issue in self.issues:
            bad_files.setdefault(issue.file, issue)
        for row, mod in enumerate(mods):
            version = mod.version_number or ""
            if mod.sha1 in self.updates:
                version += f"  →  {self.updates[mod.sha1].get('version_number')}"
            self.table.setItem(row, 0, _check_item(mod.enabled))
            issue = bad_files.get(mod.filename) if mod.enabled else None
            title_role = ("wrong_loader" if issue.severity == "error" else "unavailable") if issue else \
                (None if mod.enabled else "faint")
            self.table.setItem(row, 1, _text_item(("⚠ " if issue else "") + mod.title, title_role,
                                                  issue.message if issue else None, bold=mod.enabled))
            self.table.setItem(row, 2, _text_item(version, "available" if mod.sha1 in self.updates else "muted", mono=True))
            self.table.setItem(row, 3, _text_item(mod.filename, "faint", mono=True))
            self.table.setItem(row, 4, _text_item("Modrinth" if mod.on_modrinth else "Local file",
                                                  "muted" if mod.on_modrinth else "faint"))
        self.table.blockSignals(False)
        offline = "  (offline — showing names from the jars)" if self.app.scanner.offline else ""
        self.count.setText(f"{len(mods)} mods{offline}")

    def _item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0 or item.row() >= len(self.mods):
            return
        mod = self.mods[item.row()]
        try:
            self.app.installer.set_enabled(mod, item.checkState() == Qt.CheckState.Checked)
        except OSError as exc:
            QMessageBox.warning(self, "Craftd", f"Couldn't rename {mod.filename}: {exc}")
        self.reload()

    def _selected(self) -> list[LocalMod]:
        rows = sorted({i.row() for i in self.table.selectedIndexes()})
        return [self.mods[r] for r in rows if r < len(self.mods)]

    def _browse(self) -> None:
        if not self.inst:
            return
        dialog = BrowseModsDialog(self.app, self.runner, self.inst, self)
        dialog.exec()
        if dialog.changed:
            self.reload()
            self.mods_changed.emit()

    def _remove(self) -> None:
        mods = self._selected()
        if not mods:
            return
        names = "\n".join(f"• {m.title}" for m in mods)
        if QMessageBox.question(self, "Remove mods", f"Delete these from {self.inst.name}?\n\n{names}") \
                != QMessageBox.StandardButton.Yes:
            return
        for m in mods:
            self.app.installer.remove(m)
        self.reload()
        self.mods_changed.emit()

    def _check_updates(self) -> None:
        inst, mods = self.inst, list(self.mods)

        def done(updates):
            self.updates = updates
            self.update_btn.setText(f"Update All ({len(updates)})")
            self.update_btn.setVisible(bool(updates))
            self._fill(inst, self.mods)
            self.runner.status(f"{len(updates)} update(s) available" if updates else "Everything is up to date")

        self.runner.run(lambda p: self.app.installer.check_updates(inst, mods), on_done=done)

    def _update_all(self) -> None:
        inst = self.inst
        todo = [(m, self.updates[m.sha1]) for m in self.mods if m.sha1 in self.updates]

        def work(progress):
            done = []
            for mod, version in todo:
                progress(f"Updating {mod.title}…")
                done.append(self.app.installer.update(inst, mod, version))
            return done

        def finished(done):
            self.updates = {}
            self.update_btn.hide()
            self.reload()
            QMessageBox.information(self, "Craftd", "Updated:\n" + "\n".join(done))

        self.runner.run(work, on_done=finished)


# =======================================================================================
class CarryOverTab(QWidget):
    """The feature Craftd exists for: bring the mods you already use to this instance."""

    mods_changed = Signal()

    def __init__(self, app: Craftd, runner: Runner):
        super().__init__()
        self.app, self.runner = app, runner
        self.inst: Instance | None = None
        self.cands: list[Candidate] = []
        self.shown: list[Candidate] = []
        self.detected_for: str | None = None
        self.detected_source = None
        self.ready_waitlist: list[Candidate] = []

        self.intro = QLabel()
        self.intro.setWordWrap(True)
        self.intro.setTextFormat(Qt.TextFormat.RichText)

        self.source = QComboBox()
        self.source.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.source.setMinimumContentsLength(10)
        self.detect_btn = QPushButton("Detect Mods")
        self.detect_btn.clicked.connect(self.detect)
        self.show_installed = QCheckBox("Show already installed")
        self.show_installed.toggled.connect(lambda _: self._fill(self.cands))
        top = QHBoxLayout()
        top.addWidget(QLabel("Copy mods from"))
        top.addWidget(self.source, 1)
        top.addWidget(self.detect_btn)

        self.banner = QWidget()
        self.banner.setObjectName("Banner")
        self.banner_label = QLabel()
        self.banner_label.setWordWrap(True)
        self.banner_btn = QPushButton("Install Now")
        self.banner_btn.setProperty("primary", True)
        self.banner_btn.clicked.connect(self._install_waitlist)
        banner_layout = QHBoxLayout(self.banner)
        banner_layout.setContentsMargins(10, 6, 10, 6)
        banner_layout.addWidget(self.banner_label, 1)
        banner_layout.addWidget(self.banner_btn)
        self.banner.hide()

        self.table = _table(["", "Mod", "Found in", "Status", "New version"], stretch_cols=(1, 4))

        self.summary = QLabel()
        self.summary.setObjectName("Muted")
        self.summary.setWordWrap(True)
        self.copy_local = QCheckBox("Also copy jars not on Modrinth")
        self.copy_local.setToolTip("Copies them as-is. Craftd can't check if they work on this Minecraft version.")
        self.copy_local.toggled.connect(lambda _: self._fill(self.cands))
        self.waitlist_label = QLabel()
        self.waitlist_label.setObjectName("Muted")
        self.waitlist_label.setWordWrap(True)
        self.select_ready = QPushButton("Select Ready")
        self.select_ready.clicked.connect(self._select_ready)
        self.carry_btn = QPushButton("Carry Over Selected")
        self.carry_btn.setProperty("primary", True)
        self.carry_btn.clicked.connect(self._carry)
        bottom = QHBoxLayout()
        bottom.addStretch(1)
        bottom.addWidget(self.select_ready)
        bottom.addWidget(self.carry_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 8, 0, 0)
        layout.addWidget(self.intro)
        layout.addLayout(top)
        layout.addWidget(self.banner)
        # ---- packs & settings ("extras") from the source instance
        self.extras_scan = None
        self.pack_choice: set = set()
        self.packs_there: set = set()
        self.extras_title = QLabel("ALSO BRING")
        self.extras_title.setObjectName("SectionLabel")
        self.x_packs = QCheckBox("Packs")
        self.x_packs.setToolTip("Resource packs and shader packs. Packs the new instance already has are left alone.")
        self.x_config = QCheckBox("Mod settings")
        self.x_config.setToolTip("The config folder. Files the new instance already has are kept unless "
                                 "“Replace” is on.")
        self.x_options = QCheckBox("Options && keybinds")
        self.x_options.setToolTip("options.txt: graphics, controls, selected resource packs.")
        self.x_servers = QCheckBox("Server list")
        self.x_servers.setToolTip("servers.dat: your multiplayer server list.")
        self.x_replace = QCheckBox("Replace what's already there")
        self.x_replace.setToolTip("Overwrite settings the new instance already has. Craftd backs them up first "
                                  "(e.g. config.craftd-backup-<date>).")
        self.choose_packs = QPushButton("Choose Packs…")
        self.choose_packs.clicked.connect(self._choose_packs)
        self.source.currentIndexChanged.connect(lambda _: self._source_changed())

        layout.addWidget(self.table, 1)
        layout.addWidget(flow_row(self.show_installed, self.copy_local, spacing=18))
        layout.addWidget(self.extras_title)
        layout.addWidget(flow_row(self.x_packs, self.choose_packs, self.x_config, self.x_options, self.x_servers,
                                  self.x_replace, spacing=14))
        layout.addWidget(self.waitlist_label)
        layout.addWidget(self.summary)
        layout.addLayout(bottom)

    # ---- instance / source selection ---------------------------------------------------------
    def set_instance(self, inst: Instance | None) -> None:
        self.inst = inst
        self.cands, self.shown, self.detected_for = [], [], None
        self.detected_source = None
        self.table.setRowCount(0)
        self.banner.hide()
        self.source.clear()
        if not inst:
            return
        if inst.loader == "vanilla":
            self.intro.setText("This is a Vanilla instance, so it can't load mods.")
            self._set_enabled(False)
            return
        self._set_enabled(True)
        self.copy_local.setChecked(self.app.settings.carry_copy_local)
        self.intro.setText(
            f"Craftd looks at the mods in your other instances and finds the right build of each one for "
            f"{theme.strong(inst.name)} ({theme.strong(inst.summary)}). Nothing is installed until you confirm.")
        instances = [i for i in self.app.manager.list() if i.id != inst.id]
        suggested = self.app.carry.suggest_source(inst, self.app.manager.list())
        for other in instances:
            label = f"{other.name}  ({other.summary})"
            if suggested and other.id == suggested.id:
                label += "  — suggested"
            self.source.addItem(label, other.id)
        if len(instances) > 1:
            self.source.addItem("All my other instances", "__all__")
        if suggested:
            self.source.setCurrentIndex(self.source.findData(suggested.id))
        if not instances:
            self.summary.setText("No other instances yet. Create or import one with mods to carry them over.")
            self._set_enabled(False)
        else:
            self.summary.setText("Press Detect Mods to compare." if not suggested else "")
        self._refresh_waitlist()
        self._load_extras()

    def set_source(self, sources: list[Instance]) -> None:
        if len(sources) == 1:
            idx = self.source.findData(sources[0].id)
        else:
            idx = self.source.findData("__all__")
        if idx >= 0:
            self.source.setCurrentIndex(idx)

    def _set_enabled(self, on: bool) -> None:
        for w in (self.source, self.detect_btn, self.select_ready, self.carry_btn, self.copy_local, self.show_installed,
                  self.x_packs, self.x_config, self.x_options, self.x_servers, self.x_replace, self.choose_packs):
            w.setEnabled(on)

    # ---- packs & settings -------------------------------------------------------------------------
    def _extras_source(self) -> Instance | None:
        sources = self._sources()
        if not sources:
            return None
        # with "All my other instances", take packs/settings from the newest one
        return max(sources, key=lambda s: self.app.order.key(s.game_version))

    def _load_extras(self) -> None:
        from .. import extras
        inst, src = self.inst, self._extras_source()
        self.extras_scan = extras.scan(src) if (inst and src) else None
        found = self.extras_scan
        boxes = (self.x_packs, self.x_config, self.x_options, self.x_servers)
        if not found or found.empty:
            self.extras_title.setText("ALSO BRING" + (f" FROM {src.name.upper()}: NOTHING FOUND" if src else ""))
            for b in boxes + (self.x_replace,):
                b.setChecked(False)
                b.setEnabled(False)
            self.choose_packs.setEnabled(False)
            return
        choice = extras.default_choice(found, inst, self.app.settings)
        self.pack_choice = set(choice.packs)
        self.packs_there = extras.packs_already_there(found, inst)
        self.extras_title.setText(f"ALSO BRING FROM {src.name.upper()}")
        n_packs, n_new = len(found.packs), len(found.packs) - len(self.packs_there)
        size = extras.human_size(sum(extras._size(p) for p in found.packs if p not in self.packs_there))
        if not n_packs:
            self.x_packs.setText("Packs (none)")
        elif n_new == n_packs:
            self.x_packs.setText(f"Packs ({n_packs}, {size})")
        elif n_new:
            self.x_packs.setText(f"Packs ({n_new} new, {size} · {len(self.packs_there)} already copied)")
        else:
            self.x_packs.setText(f"Packs (all {n_packs} already copied)")
        n_cfg, n_cfg_new = len(found.config_files), len(extras.new_config_files(found, inst))
        if not n_cfg:
            self.x_config.setText("Mod settings (none)")
        elif n_cfg_new == n_cfg:
            self.x_config.setText(f"Mod settings ({n_cfg} files)")
        elif n_cfg_new:
            self.x_config.setText(f"Mod settings ({n_cfg_new} new of {n_cfg} files)")
        else:
            self.x_config.setText(f"Mod settings (all {n_cfg} already there)")
        for box, available, on in ((self.x_packs, bool(found.packs), bool(choice.packs)),
                                   (self.x_config, bool(found.config_files), choice.config),
                                   (self.x_options, found.options, choice.options),
                                   (self.x_servers, found.servers, choice.servers)):
            box.setEnabled(available)
            box.setChecked(on)
        self.x_replace.setEnabled(True)
        self.x_replace.setChecked(False)
        self.choose_packs.setEnabled(bool(found.packs))

    def _choose_packs(self) -> None:
        from .dialogs import ChoosePacksDialog
        if not self.extras_scan:
            return
        dlg = ChoosePacksDialog(self.extras_scan, self.pack_choice, self, already=self.packs_there)
        if dlg.exec():
            self.pack_choice = dlg.chosen()
            n = len(self.pack_choice)
            self.x_packs.setChecked(n > 0)
            self.x_packs.setText(f"Packs ({n} of {len(self.extras_scan.packs)})")

    def extras_choice(self):
        from .. import extras
        found = self.extras_scan
        if not found:
            return None
        choice = extras.ExtrasChoice(
            packs=[p for p in found.packs if p in self.pack_choice] if self.x_packs.isChecked() else [],
            config=self.x_config.isChecked(), options=self.x_options.isChecked(),
            servers=self.x_servers.isChecked(), replace=self.x_replace.isChecked())
        if not (choice.packs or choice.config or choice.options or choice.servers):
            return None
        return choice

    def _sources(self) -> list[Instance]:
        data = self.source.currentData()
        others = [i for i in self.app.manager.list() if self.inst and i.id != self.inst.id]
        return others if data == "__all__" else [i for i in others if i.id == data]

    def _source_changed(self) -> None:
        """Keep the mod list and the "Also bring" section on the same source."""
        self._load_extras()
        if (self.inst and self.detected_for == self.inst.id and self.source.currentData()
                and self.source.currentData() != self.detected_source):
            self.detect()

    def ensure_detected(self) -> None:
        """Called when the tab is shown: auto-detect once per instance."""
        if self.inst and self.detected_for != self.inst.id and self.detect_btn.isEnabled() \
                and self.source.currentData():
            self.detect()

    # ---- detection ------------------------------------------------------------------------
    def detect(self) -> None:
        inst, sources = self.inst, self._sources()
        if not inst or not sources:
            return
        self.detected_for = inst.id
        self.detected_source = source = self.source.currentData()
        self.detect_btn.setEnabled(False)
        self.table.setRowCount(0)
        self.summary.setText("Detecting…")

        def done(cands):
            self.detect_btn.setEnabled(True)
            # ignore results from a source the user has since switched away from
            if self.inst and inst.id == self.inst.id and source == self.detected_source:
                self.cands = cands
                self._fill(cands)

        def failed(msg):
            self.detect_btn.setEnabled(True)
            self.detected_for = None
            self.summary.setText(f"Couldn't check mods: {msg}")

        self.runner.run(lambda p: self.app.carry.detect(inst, sources, p), on_done=done, on_error=failed)

    def retheme(self) -> None:
        if self.cands:
            checked = {c.key for c in self._checked()}
            self._fill(self.cands)
            for row, c in enumerate(self.shown):
                item = self.table.item(row, 0)
                if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                    item.setCheckState(Qt.CheckState.Checked if c.key in checked else Qt.CheckState.Unchecked)

    def _fill(self, cands: list[Candidate]) -> None:
        show_installed = self.show_installed.isChecked()
        self.shown = [c for c in cands if show_installed or c.status != Status.INSTALLED]
        self.table.setRowCount(len(self.shown))
        tips = {
            Status.AVAILABLE: "A build for this instance exists and will be downloaded.",
            Status.UNAVAILABLE: "No build for this version yet. If selected, Craftd adds it to the waitlist and "
                                "tells you when one is released.",
            Status.LOCAL: "This jar isn't on Modrinth, so Craftd can't check it against this version.",
            Status.INSTALLED: "Already in this instance.",
            Status.WRONG_LOADER: "This mod isn't made for this loader, so there's nothing to wait for.",
            Status.WAITLISTED: "Already on the waitlist. Craftd tells you when a build for this version comes out.",
        }
        for row, c in enumerate(self.shown):
            if c.status == Status.AVAILABLE:
                check = _check_item(True)
            elif c.status == Status.UNAVAILABLE:
                check = _check_item(True)  # selected by default -> goes on the waitlist
            elif c.status == Status.LOCAL:
                check = _check_item(False, enabled=self.copy_local.isChecked())
            else:
                check = _check_item(False, enabled=False)
            self.table.setItem(row, 0, check)
            self.table.setItem(row, 1, _text_item(c.title, bold=True))
            self.table.setItem(row, 2, _text_item(", ".join(c.sources), "muted"))
            status_label = (f"Not for {self.inst.loader_label}" if c.status == Status.WRONG_LOADER and self.inst
                            else STATUS_LABELS[c.status])
            self.table.setItem(row, 3, _text_item(status_label, c.status.value, c.note or tips[c.status], bold=True))
            label = c.target_version_number + ("  beta" if c.is_prerelease else "") + ("  📌" if c.note.startswith("Exact") else "")
            self.table.setItem(row, 4, _text_item(label, "unavailable" if c.is_prerelease else "muted", c.note or None,
                                                  mono=True))

        counts = {s: sum(1 for c in cands if c.status == s) for s in Status}
        if not cands:
            self.summary.setText("The source instance has no mods.")
        else:
            self.summary.setText(
                f"{counts[Status.AVAILABLE]} ready · {counts[Status.UNAVAILABLE]} no build yet · "
                f"{counts[Status.LOCAL]} not on Modrinth · {counts[Status.INSTALLED]} already installed"
                + (f" · {counts[Status.WAITLISTED]} waitlisted" if counts[Status.WAITLISTED] else "")
                + (f" · {counts[Status.WRONG_LOADER]} not for {self.inst.loader_label}"
                   if counts[Status.WRONG_LOADER] and self.inst else ""))

    def _select_ready(self) -> None:
        for row, c in enumerate(self.shown):
            item = self.table.item(row, 0)
            if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
                item.setCheckState(Qt.CheckState.Checked if c.status == Status.AVAILABLE else Qt.CheckState.Unchecked)

    def _checked(self) -> list[Candidate]:
        return [c for row, c in enumerate(self.shown)
                if self.table.item(row, 0).checkState() == Qt.CheckState.Checked]

    # ---- applying ---------------------------------------------------------------------------
    def _carry(self) -> None:
        inst, chosen = self.inst, self._checked()
        x_choice, x_found = self.extras_choice(), self.extras_scan
        if not inst or not (chosen or x_choice):
            self.summary.setText("Tick the mods, packs or settings you want first.")
            return
        ready = sum(1 for c in chosen if c.status == Status.AVAILABLE)
        waiting = sum(1 for c in chosen if c.status == Status.UNAVAILABLE)
        local = sum(1 for c in chosen if c.status == Status.LOCAL)
        lines = [f"• Download {ready} mod(s) (plus any required dependencies)"] if ready else []
        if waiting:
            lines.append(f"• Waitlist {waiting} mod(s) that have no {inst.game_version} build yet")
        if local:
            lines.append(f"• Copy {local} jar(s) as-is (unverified)")
        if x_choice:
            what = []
            if x_choice.packs:
                what.append(f"{len(x_choice.packs)} pack(s)")
            if x_choice.config:
                what.append("mod settings")
            if x_choice.options:
                what.append("options & keybinds")
            if x_choice.servers:
                what.append("server list")
            lines.append(f"• Copy {', '.join(what)} from {x_found.source.name}")
            if x_choice.replace:
                lines.append("• Replace settings it already has (backed up first)")
            else:
                lines.append("• Keep any settings it already has")
        if QMessageBox.question(self, "Carry over", f"For {inst.name}:\n\n" + "\n".join(lines)) \
                != QMessageBox.StandardButton.Yes:
            return
        self.carry_btn.setEnabled(False)

        def done(report):
            self.carry_btn.setEnabled(True)
            QMessageBox.information(self, "Carry over finished", report.summary())
            self.mods_changed.emit()
            self.detected_for = None
            self.detect()
            self._refresh_waitlist()

        def failed(msg):
            self.carry_btn.setEnabled(True)
            QMessageBox.warning(self, "Craftd", msg)

        copy_local = self.copy_local.isChecked()

        def work(progress):
            from .. import extras
            texts = []
            if chosen:
                texts.append(self.app.carry.carry(inst, chosen, progress, copy_local=copy_local).summary())
            if x_choice:
                texts.append(extras.apply(x_found, inst, x_choice, progress).summary())
            return "\n".join(t for t in texts if t) or "Nothing to do."

        def done_text(text):
            class _R:  # the finished dialog only needs .summary()
                def summary(self):
                    return text
            done(_R())
            self._load_extras()

        self.runner.run(work, on_done=done_text, on_error=failed)

    # ---- waitlist -----------------------------------------------------------------------------
    def _refresh_waitlist(self) -> None:
        inst = self.inst
        if not inst:
            return
        waiting = self.app.carry.waitlist(inst)
        self.waitlist_label.setText(
            f"Waitlist: {', '.join(e['title'] for e in waiting)}. Craftd checks for new builds every time it starts."
            if waiting else "")
        if waiting:
            def done(ready):
                if self.inst and inst.id == self.inst.id:
                    self.show_ready(ready)
            self.runner.run(lambda p: self.app.carry.check_waitlist(inst), on_done=done, on_error=lambda _: None)

    def show_ready(self, ready: list[Candidate]) -> None:
        self.ready_waitlist = ready
        if ready:
            names = ", ".join(c.title for c in ready)
            self.banner_label.setText(f"🎉 New builds for {self.inst.game_version} are out: {names}")
            self.banner.show()
        else:
            self.banner.hide()

    def _install_waitlist(self) -> None:
        inst, ready = self.inst, list(self.ready_waitlist)

        def done(report):
            self.banner.hide()
            QMessageBox.information(self, "Craftd", report.summary())
            self.mods_changed.emit()
            self._refresh_waitlist()
            if self.detected_for:
                self.detected_for = None
                self.detect()

        self.runner.run(lambda p: self.app.carry.install_from_waitlist(inst, ready, p), on_done=done)


# =======================================================================================
class CrashTab(QWidget):
    """Explains the newest crash report for the selected instance in plain English."""

    unseen = Signal(bool)

    def __init__(self, app: Craftd, runner: Runner):
        super().__init__()
        from PySide6.QtWidgets import QScrollArea
        self.app, self.runner = app, runner
        self.inst: Instance | None = None
        self.diag = None

        self.title = QLabel()
        self.title.setObjectName("DetailTitle")
        self.title.setWordWrap(True)
        self.meta = QLabel()
        self.meta.setObjectName("Muted")
        self.meta.setWordWrap(True)
        self.explanation = QLabel()
        self.explanation.setWordWrap(True)
        self.explanation.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        try_label = QLabel("WHAT TO TRY")
        try_label.setObjectName("SectionLabel")
        self.suggestions = QLabel()
        self.suggestions.setWordWrap(True)
        self.suggestions.setTextFormat(Qt.TextFormat.RichText)
        report_label = QLabel("FROM THE REPORT")
        report_label.setObjectName("SectionLabel")
        self.excerpt = QLabel()
        self.excerpt.setObjectName("Excerpt")
        self.excerpt.setWordWrap(True)
        self.excerpt.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        self.open_btn = QPushButton("Open Crash Report")
        self.open_btn.clicked.connect(self._open_report)
        self.rescan_btn = QPushButton("Rescan")
        self.rescan_btn.clicked.connect(self.refresh)
        buttons = QHBoxLayout()
        buttons.addWidget(self.open_btn)
        buttons.addWidget(self.rescan_btn)
        buttons.addStretch(1)

        self.details = QWidget()
        dl = QVBoxLayout(self.details)
        dl.setContentsMargins(0, 0, 8, 0)
        dl.setSpacing(8)
        for w in (self.title, self.meta, self.explanation, try_label, self.suggestions, report_label, self.excerpt):
            dl.addWidget(w)
        dl.addLayout(buttons)
        dl.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.details)
        self.scroll = scroll

        self.empty = QLabel()
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 12, 0, 0)
        layout.addWidget(self.scroll, 1)
        layout.addWidget(self.empty, 1)
        self._show(None, searching=True)

    def set_instance(self, inst: Instance | None) -> None:
        self.inst = inst
        self.diag = None
        self.unseen.emit(False)
        if inst:
            self.refresh()
        else:
            self._show(None)

    def refresh(self) -> None:
        inst = self.inst
        if not inst:
            return
        from ..crash import latest_diagnosis

        def done(diag):
            if self.inst and inst.id == self.inst.id:
                self.diag = diag
                self._show(diag)
                seen = self.app.manager.load_meta(inst).get("crash_seen", 0)
                self.unseen.emit(bool(diag and not diag.resolved and diag.when > seen + 0.5))

        self.runner.run(lambda p: latest_diagnosis(inst), on_done=done, on_error=lambda _: self._show(None),
                        progress=lambda _: None)

    def mark_seen(self) -> None:
        if self.inst and self.diag:
            meta = self.app.manager.load_meta(self.inst)
            meta["crash_seen"] = self.diag.when
            self.app.manager.save_meta(self.inst, meta)
        self.unseen.emit(False)

    def _show(self, diag, searching: bool = False) -> None:
        from html import escape
        self.scroll.setVisible(diag is not None)
        self.empty.setVisible(diag is None)
        if diag is None:
            self.empty.setText("Looking for crash reports…" if searching else
                               "No crashes found for this instance.\n\nIf the game crashes, open this tab and Craftd "
                               "will explain what went wrong.")
            return
        self.title.setText(diag.title)
        where = diag.source.name if diag.source else ""
        if diag.resolved:
            self.meta.setText(f"✓ Old crash ({diag.when_text}). The game has started fine since, so this is "
                              f"probably already fixed. · {where}")
        else:
            self.meta.setText(f"Newest crash: {diag.when_text} · {where}")
        self.explanation.setText(diag.explanation)
        self.suggestions.setText("<ul style='margin-left:-20px'>" +
                                 "".join(f"<li>{escape(s)}</li>" for s in diag.suggestions) + "</ul>")
        self.excerpt.setText(diag.excerpt or "(no single error line found)")
        self.excerpt.setFont(theme.mono_font())

    def _open_report(self) -> None:
        if self.diag and self.diag.source:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.diag.source)))
