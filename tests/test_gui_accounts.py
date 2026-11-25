"""v2 step 1 in the real window (offscreen): Add Account, Settings → Accounts, the sidebar button."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QMessageBox  # noqa: E402

from craftd.accounts import Account  # noqa: E402
from craftd.gui.accounts import AccountsPanel, SignInDialog, face_pixmap  # noqa: E402
from craftd.gui.dialogs import SettingsDialog  # noqa: E402
from craftd.gui.main_window import MainWindow  # noqa: E402
from fake_auth import tiny_png  # noqa: E402
from test_gui import boxes, qapp, settle  # noqa: E402,F401


def wait_until(qapp, check, seconds=10):
    end = time.time() + seconds
    while time.time() < end and not check():
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()
    return check()


def test_add_account_window(qapp, app, servers, boxes):
    servers.pending_polls = 1
    win = MainWindow(app)
    assert win.account_btn.text() == "Sign In"
    dlg = SignInDialog(app, win.runner, win)
    assert wait_until(qapp, lambda: dlg.code_label.text() == "ABCD-EFGH")
    assert dlg.open_btn.isEnabled() and "microsoft.com/link" in dlg.status.text()
    dlg.copy_code()
    from PySide6.QtGui import QGuiApplication
    assert QGuiApplication.clipboard().text() == "ABCD-EFGH"
    assert wait_until(qapp, lambda: dlg.account is not None)
    assert dlg.result() == 1 and dlg.account.name == "Arkooo"
    assert app.accounts.active().name == "Arkooo" and app.skin_file(dlg.account).is_file()
    win.update_account_button()
    assert win.account_btn.text() == "Arkooo" and not win.account_btn.icon().isNull()


def test_sign_in_problem_is_shown(qapp, app, servers, boxes):
    servers.xerr = 2148916238
    servers.pending_polls = 0
    win = MainWindow(app)
    dlg = SignInDialog(app, win.runner, win)
    assert wait_until(qapp, lambda: boxes)
    assert "child account" in boxes[0] and dlg.result() == 0 and len(app.accounts) == 0


def test_cancel_stops_the_wait(qapp, app, servers, boxes):
    servers.pending_polls = 10_000
    win = MainWindow(app)
    dlg = SignInDialog(app, win.runner, win)
    assert wait_until(qapp, lambda: dlg.code is not None)
    dlg.reject()
    assert wait_until(qapp, lambda: not win.runner.active, seconds=5)  # the background wait ended
    assert not boxes and len(app.accounts) == 0


def test_accounts_page(qapp, app, servers, boxes, monkeypatch):
    first = app.auth.sign_in(app.auth.start_device_code(), sleep=lambda _s: None)
    app.accounts.add(first)
    app.accounts.add(Account(uuid="ab" * 16, name="AltAccount", refresh_token="r", mc_token="m",
                             skin_url=servers.skin_url), make_active=False)
    win = MainWindow(app)
    dlg = SettingsDialog(app, win.themer, win, page="Accounts")
    assert dlg.nav.currentItem().text() == "Accounts"
    panel = dlg.findChild(AccountsPanel)
    settle(qapp, win)
    texts = [panel.list.item(r).text() for r in range(panel.list.count())]
    assert texts[0].startswith("Arkooo\n✓ Playing as this account") and texts[1] == "AltAccount"
    assert app.skin_file(app.accounts.get("ab" * 16)).is_file()  # missing skins are fetched

    panel.list.setCurrentRow(1)
    assert panel.use_btn.isEnabled()
    panel.use_selected()
    assert app.accounts.active().name == "AltAccount"

    panel.list.setCurrentRow(0)
    panel.refresh_selected()  # refresh works for the real (fake) account
    assert wait_until(qapp, lambda: "sign-in works" in panel.status.text())
    servers.refresh_ok = False
    panel.refresh_selected()
    assert wait_until(qapp, lambda: "Sign in again" in panel.status.text())
    assert app.accounts.get(first.uuid).needs_sign_in
    assert "Needs signing in again" in panel.list.item(0).text() and not panel.refresh_btn.isEnabled()

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    panel.list.setCurrentRow(1)
    panel.remove_selected()
    assert [a.name for a in app.accounts] == ["Arkooo"] and app.accounts.active().name == "Arkooo"


def test_face_from_skin(qapp, tmp_path):
    skin = tmp_path / "skin.png"
    skin.write_bytes(tiny_png((10, 200, 30)))
    face = face_pixmap(skin, 32).toImage()
    assert (face.width(), face.height()) == (32, 32) and face.pixelColor(5, 5).green() == 200
    blank = face_pixmap(None, 24)
    assert blank.width() == 24
