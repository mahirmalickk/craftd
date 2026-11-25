"""Settings → Accounts, the Add Account (sign-in) window, and skin face icons."""

from __future__ import annotations

import threading
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QDialog, QDialogButtonBox, QLabel, QListWidget, QListWidgetItem, QMessageBox, QPushButton,
    QVBoxLayout, QWidget,
)

from ..accounts import Account
from ..core import Craftd
from .theme import color
from .widgets import flow_row
from .workers import Runner

ACCOUNT_ROLE = Qt.ItemDataRole.UserRole + 30


def _muted(text: str) -> QLabel:
    label = QLabel(text)
    label.setObjectName("Muted")
    label.setWordWrap(True)
    return label


def face_pixmap(skin: Path | None, size: int = 32) -> QPixmap:
    """The face from a skin (with its hat layer), scaled up with sharp pixels. A plain block if there's none."""
    img = QImage(str(skin)) if skin and Path(skin).is_file() else QImage()
    if img.isNull() or img.width() < 64 or img.height() < 32:
        pm = QPixmap(size, size)
        pm.fill(QColor(color("border")))
        return pm
    face = img.copy(8, 8, 8, 8).convertToFormat(QImage.Format.Format_ARGB32)
    painter = QPainter(face)
    painter.drawImage(0, 0, img.copy(40, 8, 8, 8))  # the hat / hair layer on top
    painter.end()
    return QPixmap.fromImage(face.scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio,
                                         Qt.TransformationMode.FastTransformation))


def face_icon(app: Craftd, account: Account | None, size: int = 32) -> QIcon:
    skin = app.skin_file(account) if account else None
    return QIcon(face_pixmap(skin, size))


# ---------------------------------------------------------------------------------------
class SignInDialog(QDialog):
    """Add Account: show the code, open microsoft.com/link, wait, then sign in to Xbox and Minecraft."""

    def __init__(self, app: Craftd, runner: Runner, parent=None):
        super().__init__(parent)
        self.app, self.runner = app, runner
        self.account: Account | None = None
        self.code = None
        self.cancel = threading.Event()
        self.setWindowTitle("Add Account")
        self.setMinimumWidth(620)

        heading = QLabel("Sign in with Microsoft")
        heading.setObjectName("DialogTitle")
        steps = _muted("1. Click Open Sign-In Page. Your code is copied for you.\n"
                       "2. Paste the code there and sign in with the Microsoft account that owns Minecraft.\n"
                       "3. Come back here: Craftd finishes on its own.")
        self.code_label = QLabel("…")
        self.code_label.setObjectName("SignInCode")
        self.code_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.code_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.open_btn = QPushButton("Open Sign-In Page")
        self.open_btn.setProperty("primary", True)
        self.open_btn.clicked.connect(self.open_page)
        self.copy_btn = QPushButton("Copy Code")
        self.copy_btn.clicked.connect(self.copy_code)
        for b in (self.open_btn, self.copy_btn):
            b.setEnabled(False)
        self.status = _muted("Asking Microsoft for a code…")
        privacy = _muted("You sign in on Microsoft's own page, so Craftd never sees your password.")
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(heading)
        layout.addWidget(steps)
        layout.addSpacing(6)
        layout.addWidget(self.code_label)
        layout.addWidget(flow_row(self.open_btn, self.copy_btn))
        layout.addWidget(self.status)
        layout.addSpacing(6)
        layout.addWidget(privacy)
        layout.addWidget(buttons)
        self.start()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._fit()

    def _fit(self) -> None:
        """Tall enough for every wrapped line at this width (Qt counts wrapped text as one line)."""
        lay = self.layout()
        lay.activate()
        need = lay.totalHeightForWidth(self.width()) if lay.hasHeightForWidth() else lay.totalSizeHint().height()
        need = max(need, lay.totalMinimumSize().height())
        if self.height() < need:
            self.setMinimumHeight(need)
            self.resize(self.width(), need)

    def start(self) -> None:
        self.runner.run(lambda _p: self.app.auth.start_device_code(), on_done=self._got_code,
                        on_error=self._failed, progress=lambda _m: None)

    def _got_code(self, code) -> None:
        if self.cancel.is_set():
            return
        self.code = code
        self.code_label.setText(code.user_code)
        for b in (self.open_btn, self.copy_btn):
            b.setEnabled(True)
        self.status.setText(f"Waiting for you to sign in at {code.verification_uri.split('://')[-1]}…")
        app, cancel = self.app, self.cancel

        def work(progress):
            acc = app.auth.sign_in(code, cancelled=cancel.is_set, progress=progress)
            progress("Getting your skin…")
            app.auth.download_skin(acc.skin_url, app.skin_file(acc))
            return acc

        self.runner.run(work, on_done=self._signed_in, on_error=self._failed, progress=self._progress)

    def _progress(self, text: str) -> None:
        if not self.cancel.is_set():
            self.status.setText(text)

    def copy_code(self) -> None:
        if self.code:
            QGuiApplication.clipboard().setText(self.code.user_code)
            self.status.setText("Code copied. Paste it on the sign-in page.")

    def open_page(self) -> None:
        if self.code:
            QGuiApplication.clipboard().setText(self.code.user_code)
            QDesktopServices.openUrl(QUrl(self.code.verification_uri))

    def _signed_in(self, account: Account) -> None:
        if self.cancel.is_set():
            return
        self.account = self.app.accounts.add(account)
        self.accept()

    def _failed(self, message: str) -> None:
        if self.cancel.is_set():
            return
        self.cancel.set()
        QMessageBox.warning(self, "Couldn't sign in", message)
        self.reject()

    def reject(self) -> None:
        self.cancel.set()  # stops waiting for the code within a quarter of a second
        super().reject()


# ---------------------------------------------------------------------------------------
class AccountsPanel(QWidget):
    """The Accounts page: who's signed in and which account plays. Changes apply right away."""

    def __init__(self, app: Craftd, runner: Runner, parent=None):
        super().__init__(parent)
        self.app, self.runner = app, runner
        self.list = QListWidget()
        self.list.setObjectName("Plain")
        self.list.setIconSize(QSize(32, 32))
        self.list.setMinimumHeight(170)
        self.list.currentRowChanged.connect(lambda _r: self._buttons())
        self.list.itemDoubleClicked.connect(lambda _i: self.use_selected())
        self.add_btn = QPushButton("Add Account…")
        self.add_btn.setProperty("primary", True)
        self.add_btn.clicked.connect(self.add_account)
        self.use_btn = QPushButton("Play as This Account")
        self.use_btn.clicked.connect(self.use_selected)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.setToolTip("Check the sign-in still works, and pick up a new name or skin")
        self.refresh_btn.clicked.connect(self.refresh_selected)
        self.remove_btn = QPushButton("Remove")
        self.remove_btn.clicked.connect(self.remove_selected)
        self.status = _muted("")
        note = _muted("Sign in with the Microsoft account that owns Minecraft: Java Edition. You sign in on "
                      "Microsoft's page, so Craftd never sees your password. Your sign-in is saved only on this "
                      "computer (encrypted on Windows). Removing an account signs it out of Craftd.")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.list)
        lay.addWidget(flow_row(self.add_btn, self.use_btn, self.refresh_btn, self.remove_btn))
        lay.addWidget(self.status)
        lay.addSpacing(6)
        lay.addWidget(note)
        self.reload()
        self._fetch_missing_skins()

    def selected(self) -> Account | None:
        item = self.list.currentItem()
        return self.app.accounts.get(item.data(ACCOUNT_ROLE)) if item else None

    def reload(self, select: str | None = None) -> None:
        store = self.app.accounts
        keep = select or (self.selected().uuid if self.selected() else store.active_uuid)
        self.list.clear()
        for acc in store:
            notes = []
            if acc.uuid == store.active_uuid:
                notes.append("✓ Playing as this account")
            if acc.needs_sign_in:
                notes.append("⚠ Needs signing in again (Add Account)")
            item = QListWidgetItem(face_icon(self.app, acc), acc.name + ("\n" + " · ".join(notes) if notes else ""))
            item.setData(ACCOUNT_ROLE, acc.uuid)
            self.list.addItem(item)
            if acc.uuid == keep:
                self.list.setCurrentItem(item)
        if not len(store):
            self.status.setText("No accounts yet. Click Add Account… to sign in.")
        self._buttons()

    def _buttons(self) -> None:
        acc = self.selected()
        self.use_btn.setEnabled(bool(acc) and acc.uuid != self.app.accounts.active_uuid)
        self.refresh_btn.setEnabled(bool(acc) and not acc.needs_sign_in)
        self.remove_btn.setEnabled(bool(acc))

    def _fetch_missing_skins(self) -> None:
        missing = [a for a in self.app.accounts if a.skin_url and not self.app.skin_file(a).is_file()]
        if missing:
            app = self.app
            self.runner.run(lambda _p: [app.auth.download_skin(a.skin_url, app.skin_file(a)) for a in missing],
                            on_done=lambda _r: self.reload(), on_error=lambda _m: None, progress=lambda _m: None)

    # ---- actions -----------------------------------------------------------------------------------
    def add_account(self) -> None:
        dialog = SignInDialog(self.app, self.runner, self)
        if dialog.exec() and dialog.account:
            self.reload(select=dialog.account.uuid)
            self.status.setText(f"Signed in as {dialog.account.name}.")

    def use_selected(self) -> None:
        acc = self.selected()
        if acc:
            self.app.accounts.set_active(acc.uuid)
            self.reload()
            self.status.setText(f"Craftd will play as {acc.name}.")

    def refresh_selected(self) -> None:
        acc = self.selected()
        if not acc:
            return
        app, store = self.app, self.app.accounts
        self.refresh_btn.setEnabled(False)

        def work(progress):
            fresh = app.auth.refresh(acc, force=True, progress=progress)
            app.auth.download_skin(fresh.skin_url, app.skin_file(fresh))
            return fresh

        def done(fresh):
            store.add(fresh, make_active=store.active_uuid == fresh.uuid)
            self.reload(select=fresh.uuid)
            self.status.setText(f"{fresh.name}'s sign-in works.")

        def failed(message):
            if "sign in again" in message.lower():
                acc.needs_sign_in = True
                store.save()
            self.reload(select=acc.uuid)
            self.status.setText(message)

        self.runner.run(work, on_done=done, on_error=failed, progress=self.status.setText)

    def remove_selected(self) -> None:
        acc = self.selected()
        if acc and QMessageBox.question(self, "Remove account", f"Sign {acc.name} out of Craftd?") \
                == QMessageBox.StandardButton.Yes:
            self.app.accounts.remove(acc.uuid)
            self.app.skin_file(acc).unlink(missing_ok=True)
            self.reload()
            self.status.setText(f"Removed {acc.name}.")

