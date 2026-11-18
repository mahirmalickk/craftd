"""Add mods from Modrinth: a store-style browser.

Cards with icons, category chips, sorting, "hide installed", a details panel with a
version picker, and an install queue at the bottom.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path

import requests
from PySide6.QtCore import QEvent, QObject, QRect, QRectF, QRunnable, QSize, Qt, QThreadPool, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QFont, QFontMetrics, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QCheckBox, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSizePolicy, QSplitter, QStyle,
    QStyledItemDelegate, QTextBrowser, QVBoxLayout, QWidget,
)

from ..core import Craftd
from ..instances import Instance, compatible_loaders
from ..modrinth import USER_AGENT
from . import theme
from .widgets import ElidedLabel, FlowLayout
from .workers import Runner

SORTS = [("Relevance", "relevance"), ("Most downloaded", "downloads"), ("Most followed", "follows"),
         ("Recently updated", "updated"), ("Newest", "newest")]
CATEGORIES = [("All", None), ("Optimization", "optimization"), ("Utility", "utility"),
              ("Decoration", "decoration"), ("Adventure", "adventure"), ("Technology", "technology"),
              ("Magic", "magic"), ("Storage", "storage"), ("World generation", "worldgen"),
              ("Libraries", "library")]
HIT_ROLE = Qt.ItemDataRole.UserRole + 10


# ---- small helpers ---------------------------------------------------------------------
def short_number(n) -> str:
    """288624256 -> '288M', 1534 -> '1.5K'."""
    n = int(n or 0)
    for div, suffix in ((1_000_000_000, "B"), (1_000_000, "M"), (1_000, "K")):
        if n >= div:
            v = n / div
            return (f"{v:.0f}" if v >= 100 else f"{v:.1f}".rstrip("0").rstrip(".")) + suffix
    return str(n)


def relative_time(iso: str | None) -> str:
    if not iso:
        return ""
    try:
        when = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    days = (datetime.now(timezone.utc) - when).days
    if days < 1:
        return "today"
    if days == 1:
        return "yesterday"
    for size, unit in ((365, "year"), (30, "month"), (7, "week")):
        if days >= size:
            n = days // size
            return f"{n} {unit}{'s' if n > 1 else ''} ago"
    return f"{days} days ago"


def category_label(slug: str) -> str:
    return dict((s, label) for label, s in CATEGORIES if s).get(slug, slug.replace("-", " ").title())


def clean_markdown(body: str) -> str:
    """Modrinth descriptions often embed images and raw HTML; keep the readable text."""
    body = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", body or "")
    body = re.sub(r"<img[^>]*>", "", body, flags=re.I)
    body = re.sub(r"</?(div|center|p|span|br|picture|source|details|summary)[^>]*>", "\n", body, flags=re.I)
    return re.sub(r"\n{3,}", "\n\n", body).strip()


# ---- icons -------------------------------------------------------------------------------
class _Fetch(QRunnable):
    def __init__(self, session, url: str, path: Path, done):
        super().__init__()
        self.session, self.url, self.path, self.done = session, url, path, done

    def run(self):
        data = b""
        try:
            if self.path.is_file():
                data = self.path.read_bytes()
            else:
                resp = self.session.get(self.url, timeout=15)
                resp.raise_for_status()
                data = resp.content
                self.path.parent.mkdir(parents=True, exist_ok=True)
                self.path.write_bytes(data)
        except Exception:
            data = b""
        self.done(self.url, data)


class IconLoader(QObject):
    """Downloads mod icons/screenshots in the background and caches them on disk."""

    loaded = Signal(str)
    _arrived = Signal(str, object)

    def __init__(self, cache_dir: Path, session=None):
        super().__init__()
        self.cache_dir = cache_dir
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.pixmaps: dict[str, QPixmap | None] = {}
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(4)
        self._arrived.connect(self._store)

    def get(self, url: str | None) -> QPixmap | None:
        if not url:
            return None
        if url in self.pixmaps:
            return self.pixmaps[url]
        self.pixmaps[url] = None  # mark as pending so it's only fetched once
        path = self.cache_dir / hashlib.sha1(url.encode()).hexdigest()
        self.pool.start(_Fetch(self.session, url, path, self._arrived.emit))
        return None

    def _store(self, url: str, data) -> None:
        pm = QPixmap()
        if data:
            pm.loadFromData(data)
        self.pixmaps[url] = None if pm.isNull() else pm
        self.loaded.emit(url)


def rounded(pm: QPixmap, size: int, radius: float) -> QPixmap:
    scaled = pm.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                       Qt.TransformationMode.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, size, size), radius, radius)
    p.setClipPath(path)
    p.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
    p.end()
    return out


def draw_placeholder(painter: QPainter, rect: QRect, title: str, font: QFont) -> None:
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(theme.color("selected")))
    painter.drawRoundedRect(QRectF(rect), 10, 10)
    initials = "".join(w[0] for w in re.findall(r"[A-Za-z0-9]+", title)[:2]).upper() or "?"
    painter.setPen(QColor(theme.color("accent")))
    painter.setFont(font)
    painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, initials)


# ---- result cards ---------------------------------------------------------------------------
class ModCardDelegate(QStyledItemDelegate):
    """One mod per row: icon, name + author, description, stats, and an Add button."""

    toggled = Signal(str)
    ICON = 44
    BTN = QSize(96, 30)

    def __init__(self, browser: "BrowseModsDialog"):
        super().__init__(browser)
        self.browser = browser

    def _fonts(self, base: QFont):
        title = QFont(base)
        title.setPixelSize(theme.emphasis_px("base", 1.08))
        title.setWeight(theme.weight("demibold"))
        small = QFont(base)
        small.setPixelSize(theme.px("small"))
        caption = QFont(base)
        caption.setPixelSize(theme.px("caption"))
        button = QFont(base)
        button.setPixelSize(theme.px("small"))
        button.setWeight(theme.weight("demibold"))
        return theme.crisp(title), theme.crisp(small), theme.crisp(caption), theme.crisp(button)

    def sizeHint(self, option, index):
        title, small, caption, _ = self._fonts(option.font)
        h = QFontMetrics(title).height() + QFontMetrics(small).height() + QFontMetrics(caption).height() + 30
        return QSize(option.rect.width(), max(h, self.ICON + 26))

    def button_rect(self, rect: QRect) -> QRect:
        return QRect(rect.right() - 14 - self.BTN.width(), rect.center().y() - self.BTN.height() // 2,
                     self.BTN.width(), self.BTN.height())

    def paint(self, painter: QPainter, option, index):
        hit = index.data(HIT_ROLE) or {}
        pid = hit.get("project_id", "")
        state = self.browser.state_of(pid)
        r = option.rect
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hover = bool(option.state & QStyle.StateFlag.State_MouseOver)
        bg = "banner" if state == "queued" else "raised" if selected else "hover" if hover else None
        if bg:
            painter.fillRect(r, QColor(theme.color(bg)))
        if selected:  # accent bar on the left marks the mod shown in the details panel
            painter.fillRect(QRect(r.left(), r.top(), 3, r.height()), QColor(theme.color("accent")))
        painter.setPen(QColor(theme.color("grid")))
        painter.drawLine(r.left(), r.bottom(), r.right(), r.bottom())

        title_f, small_f, caption_f, button_f = self._fonts(option.font)
        icon = QRect(r.left() + 14, r.center().y() - self.ICON // 2, self.ICON, self.ICON)
        pm = self.browser.icons.get(hit.get("icon_url"))
        if pm:
            painter.drawPixmap(icon, rounded(pm, self.ICON, 10))
        else:
            draw_placeholder(painter, icon, hit.get("title", "?"), title_f)

        btn = self.button_rect(r)
        x = icon.right() + 14
        width = btn.left() - 14 - x
        tm, sm, cm = QFontMetrics(title_f), QFontMetrics(small_f), QFontMetrics(caption_f)
        block_h = tm.height() + sm.height() + cm.height() + 6
        y = r.center().y() - block_h // 2

        title = tm.elidedText(hit.get("title", ""), Qt.TextElideMode.ElideRight, width)
        painter.setFont(title_f)
        painter.setPen(QColor(theme.color("text")))
        painter.drawText(QRect(x, y, width, tm.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, title)
        author_x = x + tm.horizontalAdvance(title) + 8
        if author_x < x + width - 40:
            painter.setFont(caption_f)
            painter.setPen(QColor(theme.color("faint")))
            painter.drawText(QRect(author_x, y, x + width - author_x, tm.height()),
                             Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                             cm.elidedText(f"by {hit.get('author', '')}", Qt.TextElideMode.ElideRight, x + width - author_x))
        y += tm.height() + 2
        painter.setFont(small_f)
        painter.setPen(QColor(theme.color("muted")))
        painter.drawText(QRect(x, y, width, sm.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         sm.elidedText(hit.get("description", ""), Qt.TextElideMode.ElideRight, width))
        y += sm.height() + 4
        cats = [category_label(c) for c in (hit.get("display_categories") or [])
                if c not in ("fabric", "quilt", "forge", "neoforge")][:2]
        meta = " · ".join(filter(None, [f"↓ {short_number(hit.get('downloads'))}", ", ".join(cats),
                                         f"updated {relative_time(hit.get('date_modified'))}"
                                         if hit.get("date_modified") else ""]))
        painter.setFont(caption_f)
        painter.setPen(QColor(theme.color("faint")))
        painter.drawText(QRect(x, y, width, cm.height()), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                         cm.elidedText(meta, Qt.TextElideMode.ElideRight, width))

        # the button
        painter.setFont(button_f)
        if state == "installed":
            painter.setPen(QColor(theme.color("faint")))
            painter.drawText(btn, Qt.AlignmentFlag.AlignCenter, "Installed")
        else:
            queued = state == "queued"
            painter.setBrush(QColor(theme.color("raised")))
            painter.setPen(QColor(theme.color("accent" if queued else "border")))
            painter.drawRoundedRect(QRectF(btn).adjusted(0.5, 0.5, -0.5, -0.5), 7, 7)
            painter.setPen(QColor(theme.color("available" if queued else "text")))
            painter.drawText(btn, Qt.AlignmentFlag.AlignCenter, "✓  Added" if queued else "+  Add")
        painter.restore()

    def editorEvent(self, event, model, option, index):
        if event.type() == QEvent.Type.MouseButtonRelease and \
                self.button_rect(option.rect).contains(event.position().toPoint()):
            pid = (index.data(HIT_ROLE) or {}).get("project_id")
            if pid and self.browser.state_of(pid) != "installed":
                self.toggled.emit(pid)
                return True
        return super().editorEvent(event, model, option, index)


# ---- details panel ----------------------------------------------------------------------------
class _PlainBrowser(QTextBrowser):
    def loadResource(self, rtype, name):  # never try to fetch remote images inline
        return None


class DetailPanel(QFrame):
    """Right-hand panel: icon, title, stats, version picker, Add button, full description."""

    def __init__(self, browser: "BrowseModsDialog"):
        super().__init__()
        self.setObjectName("DetailPanel")
        self.browser = browser
        self.hit: dict | None = None
        self.gallery_url: str | None = None
        self._token = 0

        self.icon = QLabel()
        self.icon.setFixedSize(56, 56)
        self.title = QLabel()
        self.title.setObjectName("DetailTitle")
        self.title.setWordWrap(True)
        self.author = QLabel()
        self.author.setObjectName("Muted")
        head_text = QVBoxLayout()
        head_text.setSpacing(2)
        head_text.addWidget(self.title)
        head_text.addWidget(self.author)
        head = QHBoxLayout()
        head.addWidget(self.icon, 0, Qt.AlignmentFlag.AlignTop)
        head.addLayout(head_text, 1)

        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.stats = QLabel()
        self.stats.setObjectName("Muted")
        self.stats.setWordWrap(True)

        self.version = QComboBox()
        self.version.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.version.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.version.setMinimumContentsLength(8)
        self.version.currentIndexChanged.connect(self._version_changed)
        self.add_btn = QPushButton("Add to queue")
        self.add_btn.setProperty("primary", True)
        self.add_btn.clicked.connect(self._toggle)
        self.link_btn = QPushButton("View on Modrinth ↗")
        self.link_btn.clicked.connect(self._open_link)
        buttons = QHBoxLayout()
        buttons.addWidget(self.add_btn, 1)
        buttons.addWidget(self.link_btn)

        self.gallery = QLabel()
        self.gallery.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.gallery.hide()
        self.body = _PlainBrowser()
        self.body.setOpenExternalLinks(True)
        self.body.setFrameShape(QFrame.Shape.NoFrame)

        version_label = QLabel("VERSION")
        version_label.setObjectName("SectionLabel")
        about_label = QLabel("ABOUT")
        about_label.setObjectName("SectionLabel")

        self.content = QWidget()
        self.content.setObjectName("DetailContent")
        layout = QVBoxLayout(self.content)
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(8)
        layout.addLayout(head)
        layout.addWidget(self.summary)
        layout.addWidget(self.stats)
        layout.addSpacing(4)
        layout.addWidget(version_label)
        layout.addWidget(self.version)
        layout.addLayout(buttons)
        layout.addSpacing(4)
        layout.addWidget(about_label)
        layout.addWidget(self.gallery)
        layout.addWidget(self.body, 1)

        self.empty = QLabel("Select a mod to see its details,\npick a version, and add it to the queue.")
        self.empty.setObjectName("Muted")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.empty, 1)
        outer.addWidget(self.content, 1)
        self.content.hide()
        browser.icons.loaded.connect(self._image_loaded)

    def show_hit(self, hit: dict) -> None:
        self.hit = hit
        self._token += 1
        token, pid = self._token, hit["project_id"]
        self.empty.hide()
        self.content.show()
        self.title.setText(hit.get("title", ""))
        self.author.setText(f"by {hit.get('author', '')}")
        self.summary.setText(hit.get("description", ""))
        cats = ", ".join(category_label(c) for c in (hit.get("display_categories") or [])
                         if c not in ("fabric", "quilt", "forge", "neoforge"))
        self.stats.setText(" · ".join(filter(None, [
            f"↓ {short_number(hit.get('downloads'))} downloads", f"♥ {short_number(hit.get('follows'))}", cats])))
        self._set_icon()
        self.gallery.hide()
        self.gallery_url = None
        self.body.setMarkdown("*Loading description…*")
        self.version.blockSignals(True)
        self.version.clear()
        self.version.addItem("Loading versions…", None)
        self.version.blockSignals(False)
        self.refresh_state()

        b = self.browser
        inst = b.inst

        def load(progress):
            project = b.app.client.project(pid) or {}
            versions = b.app.client.project_versions(pid, compatible_loaders(inst.loader), [inst.game_version])
            return project, versions

        b.runner.run(load, on_done=lambda res: self._loaded(token, *res),
                     on_error=lambda msg: self._failed(token, msg), progress=lambda _: None)

    def _loaded(self, token: int, project: dict, versions: list[dict]) -> None:
        if token != self._token:
            return
        body = clean_markdown(project.get("body", ""))
        body = re.sub(r"^#\s*" + re.escape(self.hit.get("title", "")) + r"\s*\n", "", body) if self.hit else body
        self.body.setMarkdown(body or "*No description.*")
        gallery = project.get("gallery") or []
        featured = next((g for g in gallery if g.get("featured")), gallery[0] if gallery else None)
        if featured and featured.get("url"):
            self.gallery_url = featured["url"]
            self._show_gallery()
        recommended = next((v for v in versions if v.get("version_type", "release") == "release"),
                           versions[0] if versions else None)
        self.version.blockSignals(True)
        self.version.clear()
        for v in versions:
            date = (v.get("date_published") or "")[:10]
            label = f"{v.get('version_number')}  ·  {v.get('version_type', 'release')}  ·  {date}"
            if recommended and v["id"] == recommended["id"]:
                label += "  (recommended)"
            self.version.addItem(label, v)
        if not versions:
            self.version.addItem(f"No builds for {self.browser.inst.summary}", None)
        chosen = self.browser.queue.get(self.hit["project_id"]) if self.hit else None
        target = chosen or recommended
        if target:
            self.version.setCurrentIndex(next((i for i in range(self.version.count())
                                               if (self.version.itemData(i) or {}).get("id") == target["id"]), 0))
        self.version.blockSignals(False)
        self.refresh_state()

    def _failed(self, token: int, msg: str) -> None:
        if token == self._token:
            self.body.setMarkdown(f"*Couldn't load details: {msg}*")
            self.version.clear()
            self.version.addItem("Recommended version", None)

    def _set_icon(self) -> None:
        if not self.hit:
            return
        pm = self.browser.icons.get(self.hit.get("icon_url"))
        if pm:
            self.icon.setPixmap(rounded(pm, 56, 12))
        else:
            canvas = QPixmap(56, 56)
            canvas.fill(Qt.GlobalColor.transparent)
            p = QPainter(canvas)
            p.setRenderHint(QPainter.RenderHint.Antialiasing)
            f = QFont(self.font())
            f.setPixelSize(20)
            f.setWeight(theme.weight("bold"))
            draw_placeholder(p, QRect(0, 0, 56, 56), self.hit.get("title", "?"), f)
            p.end()
            self.icon.setPixmap(canvas)

    def _show_gallery(self) -> None:
        pm = self.browser.icons.get(self.gallery_url)
        if pm:
            w = max(200, self.width() - 32)
            self.gallery.setPixmap(pm.scaledToWidth(w, Qt.TransformationMode.SmoothTransformation))
            self.gallery.show()

    def _image_loaded(self, url: str) -> None:
        if self.hit and url == self.hit.get("icon_url"):
            self._set_icon()
        if url == self.gallery_url:
            self._show_gallery()

    def refresh_state(self) -> None:
        if not self.hit:
            return
        state = self.browser.state_of(self.hit["project_id"])
        has_version = self.version.currentData() is not None or self.version.count() == 0 \
            or self.version.currentText() == "Recommended version"
        self.add_btn.setEnabled(state != "installed" and has_version)
        self.add_btn.setText({"installed": "Already installed", "queued": "Remove from queue"}.get(state, "Add to queue"))
        self.add_btn.setProperty("primary", state == "add")
        self.add_btn.style().unpolish(self.add_btn)
        self.add_btn.style().polish(self.add_btn)

    def _version_changed(self, _i: int) -> None:
        if self.hit and self.browser.state_of(self.hit["project_id"]) == "queued":
            self.browser.queue[self.hit["project_id"]] = self.version.currentData()

    def _toggle(self) -> None:
        if self.hit:
            self.browser.toggle_queue(self.hit["project_id"], self.version.currentData())

    def _open_link(self) -> None:
        if self.hit:
            QDesktopServices.openUrl(QUrl(f"https://modrinth.com/mod/{self.hit.get('slug') or self.hit['project_id']}"))


# ---- the dialog ---------------------------------------------------------------------------------
class BrowseModsDialog(QDialog):
    PAGE_SIZE = 30

    def __init__(self, app: Craftd, runner: Runner, inst: Instance, parent=None):
        super().__init__(parent)
        self.app, self.runner, self.inst = app, runner, inst
        self.setWindowTitle(f"Add mods to {inst.name}")
        self.resize(1080, 700)
        self.setMinimumSize(820, 520)
        self.queue: dict[str, dict | None] = {}  # project_id -> chosen version (None = recommended)
        self.titles: dict[str, str] = {}
        self.installed_ids: set[str] = set()
        self.hits: list[dict] = []
        self.total = 0
        self.offset = 0
        self.loading = False
        self.changed = False
        self._token = 0
        self.icons = IconLoader(app.home / "cache" / "icons", getattr(app.client, "session", None))
        self.icons.loaded.connect(lambda _url: self.list.viewport().update())

        # header
        title = QLabel("Add mods")
        title.setObjectName("DialogTitle")
        badge = QLabel(f"{inst.game_version} · {inst.loader_label}")
        badge.setObjectName("LoaderBadge")
        badge.setToolTip(f"Only mods with a build for Minecraft {inst.game_version} on {inst.loader_label} are shown.")
        target = ElidedLabel(f"to {inst.name}", Qt.TextElideMode.ElideRight)
        target.setObjectName("Muted")
        header = QHBoxLayout()
        header.addWidget(title)
        header.addSpacing(6)
        header.addWidget(badge)
        header.addWidget(target, 1)

        # toolbar
        self.search = QLineEdit()
        self.search.setPlaceholderText(f"Search mods for {inst.game_version} {inst.loader_label}")
        self.search.setClearButtonEnabled(True)
        self.sort = QComboBox()
        for label, key in SORTS:
            self.sort.addItem(label, key)
        self.sort.setCurrentIndex(1)  # most downloaded until you type
        self.hide_installed = QCheckBox("Hide installed")
        self.hide_installed.setChecked(app.settings.hide_installed)  # Settings → Mods
        toolbar = QHBoxLayout()
        toolbar.addWidget(self.search, 1)
        toolbar.addWidget(self.sort)
        toolbar.addSpacing(6)
        toolbar.addWidget(self.hide_installed)

        # category chips
        chips = QWidget()
        flow = FlowLayout(chips)
        self.chip_group = QButtonGroup(self)
        self.chip_group.setExclusive(True)
        for i, (label, slug) in enumerate(CATEGORIES):
            chip = QPushButton(label)
            chip.setObjectName("Chip")
            chip.setCheckable(True)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setProperty("slug", slug)
            chip.setChecked(i == 0)
            self.chip_group.addButton(chip)
            flow.addWidget(chip)

        # results + details
        self.list = QListWidget()
        self.list.setObjectName("Results")
        self.delegate = ModCardDelegate(self)
        self.list.setItemDelegate(self.delegate)
        self.list.setMouseTracking(True)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.status = QLabel("")
        self.status.setObjectName("Muted")
        self.status.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addWidget(self.list, 1)
        ll.addWidget(self.status)
        self.detail = DetailPanel(self)
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.detail)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        split.setSizes([640, 420])
        split.setChildrenCollapsible(False)

        # queue bar
        self.queue_label = QLabel()
        self.queue_label.setObjectName("Muted")
        self.queue_label.setWordWrap(True)
        self.clear_btn = QPushButton("Clear")
        self.clear_btn.clicked.connect(self.clear_queue)
        self.install_btn = QPushButton("Install")
        self.install_btn.setProperty("primary", True)
        self.install_btn.clicked.connect(self.install)
        done = QPushButton("Done")
        done.clicked.connect(self.accept)
        bar = QFrame()
        bar.setObjectName("QueueBar")
        bl = QHBoxLayout(bar)
        bl.setContentsMargins(14, 10, 14, 10)
        bl.addWidget(self.queue_label, 1)
        bl.addWidget(self.clear_btn)
        bl.addWidget(self.install_btn)
        bl.addWidget(done)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 12)
        layout.setSpacing(10)
        layout.addLayout(header)
        layout.addLayout(toolbar)
        layout.addWidget(chips)
        layout.addWidget(split, 1)
        layout.addWidget(bar)

        # wiring
        self.timer = QTimer(self, singleShot=True, interval=350)
        self.timer.timeout.connect(self.new_search)
        self.search.textChanged.connect(self._typed)
        self.sort.currentIndexChanged.connect(lambda _: self.new_search())
        self.chip_group.buttonClicked.connect(lambda _: self.new_search())
        self.hide_installed.toggled.connect(lambda _: self._refilter())
        self.list.currentItemChanged.connect(self._selected)
        self.list.verticalScrollBar().valueChanged.connect(self._scrolled)
        self.delegate.toggled.connect(lambda pid: self.toggle_queue(pid))
        self._update_bar()

        runner.run(lambda p: {m.project_id for m in app.scanner.scan(inst) if m.project_id},
                   on_done=self._set_installed, progress=lambda _: None)
        self.new_search()

    # ---- state ----------------------------------------------------------------------------
    def state_of(self, pid: str) -> str:
        if pid in self.installed_ids:
            return "installed"
        return "queued" if pid in self.queue else "add"

    def _set_installed(self, ids: set[str]) -> None:
        self.installed_ids = ids
        self._refilter()

    def category(self) -> str | None:
        chip = self.chip_group.checkedButton()
        return chip.property("slug") if chip else None

    # ---- searching ----------------------------------------------------------------------------
    def _typed(self, text: str) -> None:
        # Switch to relevance while searching, back to downloads when the box is cleared
        self.sort.blockSignals(True)
        self.sort.setCurrentIndex(0 if text.strip() else 1)
        self.sort.blockSignals(False)
        self.timer.start()

    def new_search(self) -> None:
        self._token += 1
        self.hits, self.offset, self.total, self.loading = [], 0, 0, False
        self.list.clear()
        self.status.setText("Searching…")
        self.fetch_page()

    def fetch_page(self) -> None:
        if self.loading:
            return
        self.loading = True
        token, offset = self._token, self.offset
        query, index, category = self.search.text().strip(), self.sort.currentData(), self.category()
        loaders = compatible_loaders(self.inst.loader)

        def work(progress):
            return self.app.client.search(query, loaders, self.inst.game_version, self.PAGE_SIZE, offset,
                                          index=index, category=category)

        self.runner.run(work, on_done=lambda res: self._got_page(token, res),
                        on_error=lambda msg: self._search_failed(token, msg), progress=lambda _: None)

    def _got_page(self, token: int, result: dict) -> None:
        if token != self._token:
            return  # an older search finished after a newer one started
        self.loading = False
        self.total = result.get("total_hits", 0)
        self.offset += self.PAGE_SIZE
        known = {h["project_id"] for h in self.hits}
        new = [h for h in result.get("hits", []) if h["project_id"] not in known]
        self.hits.extend(new)
        for h in new:
            self.titles[h["project_id"]] = h.get("title", h["project_id"])
        self._add_items(new)
        self._update_status()
        # keep the list from looking empty when many results are hidden as installed
        if self.list.count() < 12 and self.offset < self.total:
            self.fetch_page()

    def _search_failed(self, token: int, msg: str) -> None:
        if token == self._token:
            self.loading = False
            self.status.setText(f"Couldn't reach Modrinth: {msg}")

    def _visible(self, hit: dict) -> bool:
        return not (self.hide_installed.isChecked() and hit["project_id"] in self.installed_ids)

    def _add_items(self, hits: list[dict]) -> None:
        for h in hits:
            if self._visible(h):
                item = QListWidgetItem()
                item.setData(HIT_ROLE, h)
                item.setToolTip(h.get("description", ""))
                self.list.addItem(item)

    def _refilter(self) -> None:
        current = self.list.currentItem().data(HIT_ROLE)["project_id"] if self.list.currentItem() else None
        self.list.clear()
        self._add_items(self.hits)
        for row in range(self.list.count()):
            if self.list.item(row).data(HIT_ROLE)["project_id"] == current:
                self.list.setCurrentRow(row)
        self._update_status()
        if self.list.count() < 12 and self.offset < self.total and not self.loading and self.hits:
            self.fetch_page()

    def _update_status(self) -> None:
        if self.loading and not self.hits:
            return
        shown = self.list.count()
        hidden = len(self.hits) - shown
        if not self.hits:
            q = self.search.text().strip()
            self.status.setText(f"No mods match “{q}” for {self.inst.summary}." if q
                                else f"No mods found for {self.inst.summary}.")
        else:
            more = f"{self.total:,} mods for {self.inst.summary}"
            self.status.setText(more + (f" · {hidden} installed hidden" if hidden else ""))

    def _scrolled(self, value: int) -> None:
        bar = self.list.verticalScrollBar()
        if value >= bar.maximum() - 300 and self.offset < self.total and not self.loading:
            self.fetch_page()

    def _selected(self, current, _previous) -> None:
        if current is not None:
            self.detail.show_hit(current.data(HIT_ROLE))

    # ---- queue + install ------------------------------------------------------------------------
    def toggle_queue(self, pid: str, version: dict | None = None) -> None:
        if self.state_of(pid) == "installed":
            return
        if pid in self.queue:
            del self.queue[pid]
        else:
            self.queue[pid] = version
        self._update_bar()
        self.list.viewport().update()
        self.detail.refresh_state()

    def clear_queue(self) -> None:
        self.queue.clear()
        self._update_bar()
        self.list.viewport().update()
        self.detail.refresh_state()

    def _update_bar(self, message: str | None = None) -> None:
        n = len(self.queue)
        if message:
            self.queue_label.setText(message)
        elif n:
            names = ", ".join(self.titles.get(pid, pid) for pid in list(self.queue)[:3])
            extra = f" and {n - 3} more" if n > 3 else ""
            self.queue_label.setText(f"{n} mod{'s' if n > 1 else ''} queued: {names}{extra}. "
                                     "Anything they require is added automatically.")
        else:
            self.queue_label.setText("Click + Add on any mod to queue it.")
        self.install_btn.setText(f"Install {n} mod{'s' if n != 1 else ''}" if n else "Install")
        self.install_btn.setEnabled(bool(n))
        self.clear_btn.setVisible(bool(n))

    def install(self) -> None:
        if not self.queue:
            return
        inst, queue = self.inst, dict(self.queue)
        installer = self.app.installer

        def work(progress):
            versions, missing = [], []
            for pid, version in queue.items():
                if version is None:
                    progress(f"Finding the best build of {self.titles.get(pid, pid)}…")
                    version = installer.resolve_project(inst, pid)
                if version:
                    versions.append(version)
                else:
                    missing.append(self.titles.get(pid, pid))
            report = installer.install_versions(inst, versions, progress)
            report.failed.extend(f"{name}: no build for {inst.summary}" for name in missing)
            return report

        def done(report):
            self.install_btn.setEnabled(True)
            self.changed = True
            self.queue.clear()
            self._update_bar(f"✓ Installed {len(report.installed)}: {', '.join(report.installed)}"
                             if report.installed else None)
            if report.failed or report.missing_deps:
                QMessageBox.warning(self, "Craftd", report.summary())
            self.runner.run(lambda p: {m.project_id for m in self.app.scanner.scan(inst) if m.project_id},
                            on_done=self._set_installed, progress=lambda _: None)
            self.detail.refresh_state()

        def failed(msg):
            self.install_btn.setEnabled(True)
            QMessageBox.warning(self, "Craftd", msg)

        self.install_btn.setEnabled(False)
        self.runner.run(work, on_done=done, on_error=failed, progress=self.queue_label.setText)
