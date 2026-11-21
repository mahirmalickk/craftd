"""Browse Modpacks: find a modpack on Modrinth and install it as a new Prism/MultiMC instance."""

from __future__ import annotations


from PySide6.QtCore import QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QIcon
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem,
    QMessageBox, QPushButton, QSplitter, QVBoxLayout, QWidget,
)

from ..core import Craftd
from ..instances import LOADER_LABELS
from ..modrinth import primary_file
from .browser import SORTS, IconLoader, short_number
from .dialogs import _muted, fit_combo, launcher_combo
from .workers import Runner

HIT_ROLE = Qt.ItemDataRole.UserRole + 20
PACK_LOADERS = ["fabric", "quilt", "neoforge", "forge"]


class ModpacksDialog(QDialog):
    PAGE_SIZE = 30

    def __init__(self, app: Craftd, runner: Runner, parent=None):
        super().__init__(parent)
        self.app, self.runner = app, runner
        self.installed = None  # the new instance, once one is installed
        self.hits: list[dict] = []
        self.total = 0
        self._token = 0
        self._detail_token = 0
        self.versions: list[dict] = []
        self.setWindowTitle("Browse Modpacks")
        self.setMinimumSize(720, 480)
        screen = (parent.screen() if parent else None) or self.screen()
        room = screen.availableGeometry() if screen else None
        self.resize(min(1100, room.width() - 40) if room else 1040, min(700, room.height() - 60) if room else 660)
        self.icons = IconLoader(app.home / "cache" / "icons", getattr(app.client, "session", None))
        self.icons.loaded.connect(self._icon_arrived)

        title = QLabel("Modpacks")
        title.setObjectName("DialogTitle")
        sub = _muted("Whole sets of mods, picked by their makers. Installing one makes a new instance in Prism "
                     "or MultiMC, ready to launch.")
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search Modrinth modpacks")
        self.search.setClearButtonEnabled(True)
        self.loader = QComboBox()
        self.loader.addItem("Any loader", None)
        for key in PACK_LOADERS:
            self.loader.addItem(LOADER_LABELS[key], key)
        self.mc = QComboBox()
        self.mc.addItem("Any version", None)
        for gv in app.game_versions:
            if gv.get("version_type") == "release":
                self.mc.addItem(gv["version"], gv["version"])
        self.sort = QComboBox()
        for label, key in SORTS:
            self.sort.addItem(label, key)
        self.sort.setCurrentIndex(self.sort.findData("downloads"))
        for combo in (self.loader, self.mc, self.sort):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToContents)
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.loader)
        toolbar.addWidget(self.mc)
        toolbar.addWidget(self.sort)

        self.list = QListWidget()
        self.list.setObjectName("PackResults")
        self.list.setIconSize(QSize(48, 48))
        self.list.setWordWrap(True)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)  # text wraps instead
        self.list.setSpacing(3)
        self.list.currentRowChanged.connect(self._selected)
        self.more_btn = QPushButton("Load More")
        self.more_btn.clicked.connect(self.fetch_page)
        self.more_btn.hide()
        self.status = _muted("")
        left = QWidget()
        left.setMinimumWidth(260)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.list, 1)
        ll.addWidget(self.more_btn)
        ll.addWidget(self.status)

        # details + install
        self.detail = QFrame()
        self.detail.setObjectName("DetailPanel")
        self.detail.setMinimumWidth(400)  # room for both buttons and the form
        self.d_title = QLabel("Pick a modpack")
        self.d_title.setObjectName("DetailTitle")
        self.d_title.setWordWrap(True)
        self.d_title.setMinimumWidth(1)
        self.d_desc = _muted("Its versions and an Install button show up here.")
        self.d_desc.setMinimumWidth(1)  # wrap to the panel's width instead of widening it
        # pick the Minecraft version first, then the pack's builds for it: a short list instead of every build ever
        self.pack_mc = fit_combo(QComboBox(), 6)
        self.pack_mc.currentIndexChanged.connect(lambda _i: self._fill_versions())
        self.version = fit_combo(QComboBox())
        self.version.currentIndexChanged.connect(lambda _i: self._version_changed())
        self.shown_versions: list[dict] = []
        self.name = QLineEdit()
        self.launcher, self.launcher_note = launcher_combo(app)
        form = QFormLayout()
        form.addRow("Minecraft", self.pack_mc)
        form.addRow("Version", self.version)
        form.addRow("Name", self.name)
        form.addRow("Create in", self.launcher)
        self.link_btn = QPushButton("View on Modrinth ↗")
        self.link_btn.clicked.connect(self._open_link)
        self.install_btn = QPushButton("Install")
        self.install_btn.setProperty("primary", True)
        self.install_btn.clicked.connect(self.install)
        self.progress = _muted("")
        dl = QVBoxLayout(self.detail)
        dl.setContentsMargins(16, 14, 16, 14)
        dl.addWidget(self.d_title)
        dl.addWidget(self.d_desc)
        dl.addSpacing(6)
        dl.addLayout(form)
        dl.addWidget(self.launcher_note)
        dl.addStretch(1)
        dl.addWidget(self.progress)
        row = QHBoxLayout()
        row.addWidget(self.link_btn)
        row.addStretch(1)
        row.addWidget(self.install_btn)
        dl.addLayout(row)
        self._show_detail(None)

        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.detail)
        split.setChildrenCollapsible(False)
        split.setStretchFactor(0, 3)  # extra room goes mostly to the list
        split.setStretchFactor(1, 2)
        split.setSizes([560, 460])

        layout = QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(sub)
        layout.addLayout(toolbar)
        layout.addWidget(split, 1)

        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.new_search)
        self.search.textChanged.connect(lambda _t: self.timer.start())
        for combo in (self.loader, self.mc, self.sort):
            combo.currentIndexChanged.connect(lambda _i: self.new_search())
        self.new_search()

    # ---- searching -------------------------------------------------------------------------------
    def new_search(self) -> None:
        self._token += 1
        self.hits, self.total = [], 0
        self.list.clear()
        self.fetch_page()

    def fetch_page(self) -> None:
        token, offset = self._token, len(self.hits)
        query, loader, mc, sort = (self.search.text().strip(), self.loader.currentData(), self.mc.currentData(),
                                   self.sort.currentData())
        self.status.setText("Searching…")
        self.more_btn.setEnabled(False)

        def work(_p):
            return self.app.client.search(query, [loader] if loader else [], mc, self.PAGE_SIZE, offset,
                                          index=sort if (query or sort != "relevance") else "downloads",
                                          project_type="modpack")

        def done(result):
            if token != self._token:
                return
            hits = result.get("hits", [])
            self.total = result.get("total_hits", len(hits))
            for hit in hits:
                self._add(hit)
            self.more_btn.setEnabled(True)
            self.more_btn.setVisible(len(self.hits) < self.total)
            self.status.setText(f"{self.total} modpack(s)" if self.hits else "No modpacks match.")

        def failed(msg):
            if token == self._token:
                self.more_btn.setEnabled(True)
                self.status.setText(f"Couldn't search Modrinth: {msg}")

        self.runner.run(work, on_done=done, on_error=failed, progress=lambda _m: None)

    def _add(self, hit: dict) -> None:
        self.hits.append(hit)
        loaders = [LOADER_LABELS[c] for c in hit.get("display_categories") or hit.get("categories") or []
                   if c in LOADER_LABELS]
        line2 = f"by {hit.get('author', '?')} · {short_number(hit.get('downloads', 0))} downloads"
        if loaders:
            line2 += " · " + ", ".join(loaders)
        item = QListWidgetItem(f"{hit.get('title')}\n{line2}\n{hit.get('description', '')}")
        item.setData(HIT_ROLE, hit)
        pm = self.icons.get(hit.get("icon_url"))
        if pm:
            item.setIcon(QIcon(pm))
        self.list.addItem(item)

    def _icon_arrived(self, url: str) -> None:
        pm = self.icons.pixmaps.get(url)
        if not pm:
            return
        for row in range(self.list.count()):
            item = self.list.item(row)
            if (item.data(HIT_ROLE) or {}).get("icon_url") == url:
                item.setIcon(QIcon(pm))

    # ---- details -----------------------------------------------------------------------------------
    def current_hit(self) -> dict | None:
        item = self.list.currentItem()
        return item.data(HIT_ROLE) if item else None

    def _show_detail(self, hit: dict | None) -> None:
        on = hit is not None
        for w in (self.pack_mc, self.version, self.name, self.link_btn):
            w.setEnabled(on)
        self.install_btn.setEnabled(False)
        if not on:
            return
        self.d_title.setText(hit.get("title", ""))
        self.d_desc.setText(hit.get("description", ""))
        self.name.setText(hit.get("title", ""))
        self.name.setCursorPosition(0)  # show the start of a long name

    def _selected(self, _row: int) -> None:
        hit = self.current_hit()
        self._show_detail(hit)
        self.pack_mc.blockSignals(True)
        self.pack_mc.clear()
        self.pack_mc.blockSignals(False)
        self.version.clear()
        self.versions, self.shown_versions = [], []
        if not hit:
            return
        self._detail_token += 1
        token, pid = self._detail_token, hit["project_id"]
        mc, loader = self.mc.currentData(), self.loader.currentData()
        self.progress.setText("Loading versions…")

        def done(versions):
            if token != self._detail_token:
                return
            self.versions = versions
            games = {g for v in versions for g in v.get("game_versions", [])}
            order = sorted(games, key=self.app.order.key, reverse=True)
            self.pack_mc.blockSignals(True)
            for g in order:
                self.pack_mc.addItem(g, g)
            want = mc if mc in games else (order[0] if order else None)
            if want:
                self.pack_mc.setCurrentIndex(self.pack_mc.findData(want))
            self.pack_mc.blockSignals(False)
            self.progress.setText("" if versions else "This modpack has no versions to install.")
            self._fill_versions()

        self.runner.run(lambda p: self.app.client.project_versions(pid, [loader] if loader else None,
                                                                   [mc] if mc else None),
                        on_done=done, on_error=lambda msg: self.progress.setText(f"Couldn't load versions: {msg}"),
                        progress=lambda _m: None)

    def _fill_versions(self) -> None:
        """The pack's builds for the picked Minecraft version, newest first, the newest full release picked."""
        game = self.pack_mc.currentData()
        self.shown_versions = sorted((v for v in self.versions if game in v.get("game_versions", [])),
                                     key=lambda v: v.get("date_published") or "", reverse=True)
        several_loaders = len({tuple(v.get("loaders", [])) for v in self.versions}) > 1
        self.version.blockSignals(True)
        self.version.clear()
        for v in self.shown_versions:
            text = v.get("version_number") or "?"
            kind = v.get("version_type", "release")
            if kind != "release":
                text += f"  ({kind})"
            if several_loaders:
                text += "  · " + ", ".join(LOADER_LABELS.get(x, x) for x in v.get("loaders", []))
            self.version.addItem(text, v.get("id"))
        best = next((i for i, v in enumerate(self.shown_versions) if v.get("version_type") == "release"), 0)
        if self.shown_versions:
            self.version.setCurrentIndex(best)
        self.version.blockSignals(False)
        self._version_changed()

    def _version_changed(self) -> None:
        self.install_btn.setEnabled(bool(self.shown_versions) and self.version.currentIndex() >= 0
                                    and self.launcher.currentData() is not None)

    def _open_link(self) -> None:
        hit = self.current_hit()
        if hit:
            QDesktopServices.openUrl(QUrl(f"https://modrinth.com/modpack/{hit.get('slug') or hit['project_id']}"))

    # ---- installing --------------------------------------------------------------------------------
    def install(self) -> None:
        from .. import mrpack
        from ..launchers import instances_dir
        row = self.version.currentIndex()
        if row < 0 or row >= len(self.shown_versions):
            return
        version, launcher, name = self.shown_versions[row], self.launcher.currentData(), self.name.text().strip()
        parent = instances_dir(self.app.settings, launcher)
        if not parent:
            return
        app = self.app
        self.app.settings.last_launcher = launcher
        self.app.settings.save(self.app.home)

        def work(progress):
            f = primary_file(version)
            dest = app.home / "cache" / "modpacks" / f["filename"]
            if not dest.is_file():
                progress(f"Downloading {f['filename']}…")
                app.client.download(f["url"], dest, (f.get("hashes") or {}).get("sha1"))
            return mrpack.install(app.manager, app.client, dest, launcher, parent, name or None, progress)

        def done(inst):
            self.installed = inst
            self.install_btn.setEnabled(True)
            QMessageBox.information(self, "Craftd", f"Installed {inst.name} in {inst.launcher_label}. "
                                    f"Open {inst.launcher_label} to play it.")
            self.accept()

        def failed(msg):
            self.install_btn.setEnabled(True)
            self.progress.setText("")
            QMessageBox.warning(self, "Craftd", f"Couldn't install the modpack: {msg}")

        self.install_btn.setEnabled(False)
        self.runner.run(work, on_done=done, on_error=failed, progress=self.progress.setText)
