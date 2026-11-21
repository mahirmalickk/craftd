"""Drives the real window offscreen against the fake Modrinth."""

import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QThread, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from craftd.gui.browser import HIT_ROLE, BrowseModsDialog  # noqa: E402
from craftd.gui.dialogs import NewInstanceDialog  # noqa: E402
from craftd.gui.main_window import MainWindow  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    return app


@pytest.fixture
def boxes(monkeypatch):
    shown = []
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QMessageBox, "information", lambda parent, title, text: shown.append(text))
    monkeypatch.setattr(QMessageBox, "warning", lambda parent, title, text: shown.append("WARN " + text))
    return shown


def settle(qapp, window, timeout=10):
    end = time.time() + timeout
    while time.time() < end:
        qapp.processEvents()
        if not window.runner.active:
            qapp.processEvents()
            return
        time.sleep(0.01)
    raise AssertionError("background work didn't finish")


def test_carry_over_flow_in_window(qapp, app, fake, setup_262, boxes):
    target = app.manager.create("Survival 26.3", "26.3", "fabric")
    win = MainWindow(app)
    settle(qapp, win)

    # Select the new instance, open Carry Over: detection runs automatically
    ids = [i.id for i in win.instances]
    win.list.setCurrentRow(ids.index(target.id))
    win.tabs.setCurrentWidget(win.carry_tab)
    settle(qapp, win)
    tab = win.carry_tab
    assert "Survival 26.2" in tab.source.currentText() and "suggested" in tab.source.currentText()
    rows = {tab.table.item(r, 1).text(): tab.table.item(r, 3).text() for r in range(tab.table.rowCount())}
    assert rows == {"Fabric API": "Ready", "Lithium": "Ready", "Sodium": "Ready",
                    "YetAnotherConfigLib": "No build yet", "My Private Mod": "Not on Modrinth"}
    assert "3 ready" in tab.summary.text()

    tab.carry_btn.click()
    settle(qapp, win)
    assert any("Installed 3" in s and "Waitlisted 1" in s for s in boxes), boxes
    assert len(list(target.mods_dir.glob("*.jar"))) == 3
    assert win.mods_tab.table.rowCount() == 3
    assert "YetAnotherConfigLib" in tab.waitlist_label.text()

    # A YACL build for 26.3 appears; on next start Craftd flags it and installs on click
    fake.add_version("yacl", "YetAnotherConfigLib", "3.8+26.3", ["26.3"], ["fabric"])
    win2 = MainWindow(app)
    settle(qapp, win2)
    assert win2.ready_counts == {target.id: 1}
    win2.list.setCurrentRow([i.id for i in win2.instances].index(target.id))
    settle(qapp, win2)
    assert not win2.carry_tab.banner.isHidden()
    win2.carry_tab.banner_btn.click()
    settle(qapp, win2)
    assert len(list(target.mods_dir.glob("*.jar"))) == 4
    assert app.carry.waitlist(target) == []


def test_callbacks_run_on_ui_thread(qapp, app):
    win = MainWindow(app)
    seen = []
    win.runner.run(lambda p: QThread.currentThread(), on_done=lambda worker: seen.append(
        (worker is not qapp.thread(), QThread.currentThread() is qapp.thread())))
    settle(qapp, win)
    assert seen == [(True, True)]


def test_new_instance_dialog_suggests_source(qapp, app, setup_262):
    dlg = NewInstanceDialog(app)
    dlg.version.setCurrentText("26.3")
    dlg.loader.setCurrentIndex(dlg.loader.findData("fabric"))
    assert dlg.name.text() == "Fabric 26.3"
    assert "suggested" in dlg.source.currentText()
    name, version, loader, sources = dlg.values()
    assert (version, loader, [s.name for s in sources]) == ("26.3", "fabric", ["Survival 26.2"])
    dlg.loader.setCurrentIndex(dlg.loader.findData("vanilla"))
    assert not dlg.carry_box.isEnabled() and dlg.values()[3] == []


def test_new_instance_jumps_to_carry_over(qapp, app, setup_262, boxes, monkeypatch, tmp_path):
    """1.1: the new instance is made inside MultiMC/Prism (so it can be launched), then Carry Over opens."""
    from craftd.loaders import LoaderVersion
    monkeypatch.setattr(NewInstanceDialog, "exec", lambda self: (self.version.setCurrentText("26.3"), 1)[1])
    monkeypatch.setattr(app, "loader_versions", lambda *a, **k: [LoaderVersion("0.17.2", recommended=True)])
    win = MainWindow(app)
    settle(qapp, win)
    win.new_instance()  # no launcher found: nothing is created
    settle(qapp, win)
    assert win.current().name == "Survival 26.2"
    mmc = tmp_path / "MultiMC" / "instances"
    mmc.mkdir(parents=True)
    app.settings.multimc_folder = str(mmc)
    win.new_instance()
    settle(qapp, win)
    assert win.current().name == "Fabric 26.3" and win.current().launcher == "multimc"
    assert win.current().mods_dir == mmc / "Fabric 26.3" / ".minecraft" / "mods"
    assert "Linked MultiMC instance" in win.subtitle.fullText() and win.legacy.isHidden()
    assert win.tabs.currentWidget() is win.carry_tab
    assert win.carry_tab.table.rowCount() == 5


def test_mods_tab_toggle_and_browse(qapp, app, fake, boxes):
    inst = app.manager.create("T", "26.3", "fabric")
    fake.place(fake.v["sodium263"], inst.mods_dir)
    win = MainWindow(app)
    settle(qapp, win)
    table = win.mods_tab.table
    assert table.item(0, 1).text() == "Sodium"
    table.item(0, 0).setCheckState(Qt.CheckState.Unchecked)
    settle(qapp, win)
    assert [p.name for p in inst.mods_dir.iterdir()] == ["sodium-0.7.2+26.3.jar.disabled"]

    dlg = BrowseModsDialog(app, win.runner, inst, win)
    settle(qapp, win)
    dlg.search.setText("mod menu")
    dlg.new_search()
    settle(qapp, win)
    assert dlg.list.count() == 1 and dlg.list.item(0).data(HIT_ROLE)["title"] == "Mod Menu"
    dlg.toggle_queue("modmenu")
    assert dlg.install_btn.text() == "Install 1 mod"
    dlg.install_btn.click()
    settle(qapp, win)
    names = sorted(p.name for p in inst.mods_dir.iterdir())
    assert names == ["fabric-api-0.125+26.3.jar", "modmenu-16.0+26.3.jar", "sodium-0.7.2+26.3.jar.disabled"]


def test_problems_bar_crash_tab_and_waitlisted(qapp, app, fake, setup_262, boxes):
    import shutil
    from pathlib import Path

    from jars import fabric_jar, write
    target = app.manager.create("Survival 26.3", "26.3", "fabric")
    app.carry.carry(target, app.carry.detect(target, [setup_262]))
    write(target.mods_dir, "needs-lib.jar", fabric_jar("needslib", "1.0", depends={"missinglib": "*"}))
    crash_dir = target.game_dir / "crash-reports"
    crash_dir.mkdir(parents=True)
    shutil.copy(Path(__file__).parent / "data" / "neoforge_sodium_mixin_crash.log", crash_dir / "crash-1.txt")

    win = MainWindow(app)
    settle(qapp, win)
    win.list.setCurrentRow([i.id for i in win.instances].index(target.id))
    settle(qapp, win)
    # Mods tab: compatibility problems bar + marked row
    assert not win.mods_tab.problems.isHidden()
    assert "Needs “missinglib”" in win.mods_tab.problems_label.text()
    titles = [win.mods_tab.table.item(r, 1).text() for r in range(win.mods_tab.table.rowCount())]
    assert "⚠ Needslib" in titles
    # Crash Help: badge until opened, then the explanation
    idx = win.tabs.indexOf(win.crash_tab)
    assert win.tabs.tabText(idx) == "Crash Help ●"
    win.tabs.setCurrentWidget(win.crash_tab)
    settle(qapp, win)
    assert win.tabs.tabText(idx) == "Crash Help"
    assert win.crash_tab.title.text() == "Sodium doesn't fit this NeoForge version"
    # Carry Over: YACL is already waitlisted -> labeled, unticked, not selectable
    win.tabs.setCurrentWidget(win.carry_tab)
    settle(qapp, win)
    t = win.carry_tab.table
    row = next(r for r in range(t.rowCount()) if t.item(r, 1).text() == "YetAnotherConfigLib")
    assert t.item(row, 3).text() == "Waitlisted"
    assert t.item(row, 0).checkState() == Qt.CheckState.Unchecked
    assert not (t.item(row, 0).flags() & Qt.ItemFlag.ItemIsUserCheckable)


def test_carry_over_packs_and_settings_in_window(qapp, app, fake, setup_262, boxes):
    src = setup_262
    g = src.game_dir
    (g / "resourcepacks").mkdir(parents=True)
    (g / "resourcepacks" / "Faithful.zip").write_bytes(b"x" * 2048)
    (g / "resourcepacks" / "Bare Bones.zip").write_bytes(b"y" * 1024)
    (g / "shaderpacks").mkdir()
    (g / "shaderpacks" / "Complementary.zip").write_bytes(b"z" * 4096)
    (g / "config").mkdir()
    (g / "config" / "sodium-options.json").write_text('{"quality": 1}')
    (g / "options.txt").write_text("fov:0.5\n")
    (g / "servers.dat").write_bytes(b"\x0a\x00")

    target = app.manager.create("Survival 26.3", "26.3", "fabric")
    (target.game_dir / "config").mkdir(parents=True)
    (target.game_dir / "config" / "sodium-options.json").write_text('{"quality": 2}')

    win = MainWindow(app)
    settle(qapp, win)
    ids = [i.id for i in win.instances]
    win.list.setCurrentRow(ids.index(target.id))
    win.tabs.setCurrentWidget(win.carry_tab)
    settle(qapp, win)
    tab = win.carry_tab

    assert "SURVIVAL 26.2" in tab.extras_title.text()
    assert tab.x_packs.isChecked() and "3" in tab.x_packs.text()
    # the only config file is one the new instance already has: shown, but not ticked
    assert not tab.x_config.isChecked() and "all 1 already there" in tab.x_config.text()
    tab.x_config.setChecked(True)
    assert tab.x_options.isChecked() and tab.x_servers.isChecked()  # target has neither yet
    assert not tab.x_replace.isChecked()

    # Leave one pack behind via the picker
    from craftd.gui.dialogs import ChoosePacksDialog
    dlg = ChoosePacksDialog(tab.extras_scan, tab.pack_choice, tab)
    for row in range(dlg.list.count()):
        if "Bare Bones" in dlg.list.item(row).text():
            dlg.list.item(row).setCheckState(Qt.CheckState.Unchecked)
    tab.pack_choice = dlg.chosen()

    # Untick every mod: packs and settings alone are enough to carry
    for r in range(tab.table.rowCount()):
        item = tab.table.item(r, 0)
        if item.flags() & Qt.ItemFlag.ItemIsUserCheckable:
            item.setCheckState(Qt.CheckState.Unchecked)
    tab._carry()
    settle(qapp, win)

    t = target.game_dir
    assert (t / "resourcepacks" / "Faithful.zip").exists()
    assert not (t / "resourcepacks" / "Bare Bones.zip").exists()
    assert (t / "shaderpacks" / "Complementary.zip").exists()
    assert (t / "options.txt").read_text() == "fov:0.5\n"
    assert (t / "servers.dat").exists()
    # existing setting kept because Replace was off
    assert '"quality": 2' in (t / "config" / "sodium-options.json").read_text()
    assert not list(target.mods_dir.glob("*.jar"))  # no mods were ticked
    assert boxes and "Faithful.zip" in boxes[-1] and "1 kept" in boxes[-1]
    # afterwards only the pack left behind is new; the copied ones say so and aren't ticked again
    assert tab.x_packs.text() == "Packs (1 new, 1.0 KB · 2 already copied)" and tab.x_packs.isChecked()
    assert {p.name for p in tab.pack_choice} == {"Bare Bones.zip"}
    assert not tab.x_options.isChecked() and not tab.x_servers.isChecked()


def test_changing_source_redetects(qapp, app, fake, setup_262, boxes):
    other = app.manager.create("Creative 26.1", "26.1", "fabric")
    fake.place(fake.v["lithium262"], other.mods_dir)
    target = app.manager.create("Survival 26.3", "26.3", "fabric")
    win = MainWindow(app)
    settle(qapp, win)
    ids = [i.id for i in win.instances]
    win.list.setCurrentRow(ids.index(target.id))
    win.tabs.setCurrentWidget(win.carry_tab)
    settle(qapp, win)
    tab = win.carry_tab
    assert tab.table.rowCount() == 5  # from the suggested 26.2

    tab.source.setCurrentIndex(tab.source.findData(other.id))
    settle(qapp, win)
    found_in = {tab.table.item(r, 2).text() for r in range(tab.table.rowCount())}
    assert found_in == {"Creative 26.1"}
    assert "CREATIVE 26.1" in tab.extras_title.text()
