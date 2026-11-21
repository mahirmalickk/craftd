"""1.1 in the real window (offscreen): Import from, right-click menus, worlds, Share Instance, modpacks."""

import json
import os
import zipfile

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QFileDialog, QInputDialog, QMessageBox  # noqa: E402

from craftd.gui.dialogs import ChangeVersionDialog, ImportDialog, InstallPackDialog, ShareDialog  # noqa: E402
from craftd.gui.main_window import MainWindow  # noqa: E402
from craftd.loaders import LoaderVersion  # noqa: E402
from test_gui import boxes, qapp, settle  # noqa: E402,F401
from test_worlds_mrpack import make_world  # noqa: E402


@pytest.fixture
def mmc(app, tmp_path, monkeypatch):
    """A MultiMC instances folder Craftd knows about, and loader versions without the network."""
    folder = tmp_path / "MultiMC" / "instances"
    folder.mkdir(parents=True)
    app.settings.multimc_folder = str(folder)
    monkeypatch.setattr(app, "loader_versions", lambda *a, **k: [LoaderVersion("0.17.2", recommended=True)])
    return folder


def test_import_from_window(qapp, app, mmc, monkeypatch):
    app.settings.multimc_folder = ""
    dlg = ImportDialog(app)
    titles = [r.radio.text() for r in dlg.findChildren(type(dlg.rows["prism"]))]
    assert titles == ["Prism Launcher", "MultiMC", "Modpack file (.mrpack)", "Official Minecraft Launcher",
                      "Modrinth App", "CurseForge App"]
    soon = [r for r in dlg.findChildren(type(dlg.rows["prism"])) if not r.isEnabled()]
    assert len(soon) == 3
    assert "Import" not in dlg.next_btn.text() and dlg.next_btn.text() == "Next"
    dlg.rows["multimc"].radio.setChecked(True)
    assert not dlg.folder_box.isHidden() and not dlg.next_btn.isEnabled()  # needs a real folder first
    dlg.mmc_folder.setText(str(mmc))
    assert dlg.next_btn.isEnabled()
    dlg._next()
    assert dlg.choice == "multimc" and app.settings.multimc_folder == str(mmc)
    dlg.rows["mrpack"].radio.setChecked(True)
    assert dlg.folder_box.isHidden()


def test_sidebar_has_one_import_button(qapp, app):
    from PySide6.QtWidgets import QPushButton
    win = MainWindow(app)
    texts = [b.text() for b in win.findChildren(QPushButton)]
    assert "Import from" in texts and "Browse Modpacks" in texts
    assert not any(t.startswith("Import from ") for t in texts)  # no "Import from Prism…" / "MultiMC…" anymore


def test_legacy_instance_banner_and_move(qapp, app, fake, mmc, boxes):
    old = app.manager.create("Fabric 26.3", "26.3", "fabric")
    fake.place(fake.v["sodium263"], old.mods_dir)
    win = MainWindow(app)
    settle(qapp, win)
    assert not win.legacy.isHidden() and win.legacy_btn.text() == "Move to MultiMC"
    assert "Craftd-only instance" in win.subtitle.fullText()
    menu = [a.text() for a in win.instance_menu(win.current()).actions() if a.text()]
    assert "Move to MultiMC…" in menu and "Unlink from Craftd" not in menu
    win.legacy_btn.click()
    settle(qapp, win)
    new = win.current()
    assert new.launcher == "multimc" and new.name == "Fabric 26.3" and win.legacy.isHidden()
    assert [p.name for p in new.mods_dir.iterdir()] == ["sodium-0.7.2+26.3.jar"]


def test_rename_copy_delete_from_menu(qapp, app, mmc, boxes, monkeypatch):
    inst = app.new_instance("multimc", "Fabric 26.3", "26.3", "fabric")
    win = MainWindow(app)
    win.refresh_instances(select_id=inst.id)
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Survival", True))
    win.rename_instance()
    assert win.current().name == "Survival" and "name=Survival" in (inst.root / "instance.cfg").read_text()
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Survival (Copy)", True))
    win.copy_instance()
    settle(qapp, win)
    assert win.current().name == "Survival (Copy)" and len(app.manager.list()) == 2
    copy_root = win.current().root
    win.delete_instance()
    assert not copy_root.exists() and [i.name for i in app.manager.list()] == ["Survival"]


def test_mods_right_click_menu(qapp, app, fake, boxes, tmp_path, monkeypatch):
    inst = app.manager.create("T", "26.3", "fabric")
    fake.place(fake.v["sodium263"], inst.mods_dir)
    fake.place(fake.v["lithium263"], inst.mods_dir)
    older, _ = fake.add_version("sodium", "Sodium", "0.7.1+26.3", ["26.3"], ["fabric"])
    win = MainWindow(app)
    settle(qapp, win)
    tab = win.mods_tab
    lithium, sodium = tab.mods  # sorted by name
    menu = [a.text() for a in tab.mod_menu([sodium]).actions() if a.text()]
    assert menu == ["Sodium", "Disable", "Change Version…", "View on Modrinth ↗", "Show in Folder", "Copy Name",
                    "Remove…"]
    many = [a.text() for a in tab.mod_menu([lithium, sodium]).actions() if a.text()]
    assert many[0] == "2 mods selected" and "Change Version…" not in many and "Copy Names" in many

    tab.set_enabled([lithium, sodium], False)
    settle(qapp, win)
    assert all(not m.enabled for m in tab.mods)
    assert "Enable" in [a.text() for a in tab.mod_menu(tab.mods).actions()]
    tab.set_enabled(tab.mods, True)
    settle(qapp, win)

    # Change Version: pick the older build
    sodium = next(m for m in tab.mods if m.title == "Sodium")
    dlg = ChangeVersionDialog(app, win.runner, inst, sodium, win)
    settle(qapp, win)
    texts = [dlg.list.item(r).text() for r in range(dlg.list.count())]
    assert len(texts) == 2 and any("0.7.2+26.3" in t and "(installed)" in t for t in texts)
    current = next(r for r, t in enumerate(texts) if "(installed)" in t)
    dlg.list.setCurrentRow(current)
    assert not dlg.ok.isEnabled()  # it's already the installed one
    row = next(r for r, t in enumerate(texts) if "0.7.1" in t)
    dlg.list.setCurrentRow(row)
    assert dlg.ok.isEnabled()
    dlg._pick()
    assert dlg.chosen_version["version_number"] == "0.7.1+26.3"

    class Picked:  # the tab opens the dialog itself: answer it with the build picked above
        def __init__(self, *a, **k):
            self.chosen_version = older

        def exec(self):
            return 1

    import craftd.gui.dialogs as dialogs_module
    monkeypatch.setattr(dialogs_module, "ChangeVersionDialog", Picked)
    tab.change_version(sodium)
    settle(qapp, win)
    assert sorted(p.name for p in inst.mods_dir.iterdir()) == ["lithium-0.17+26.3.jar", "sodium-0.7.1+26.3.jar"]

    # Add File / drag and drop
    jar = tmp_path / "curseforge-only.jar"
    jar.write_bytes(b"PK")
    tab.add_files([str(jar)])
    settle(qapp, win)
    assert (inst.mods_dir / "curseforge-only.jar").is_file()
    assert any(m.filename == "curseforge-only.jar" for m in tab.mods)


def test_carry_over_worlds(qapp, app, fake, setup_262, boxes, monkeypatch):
    make_world(setup_262.game_dir / "saves", "survival", "My Survival", "26.2", 5000)
    make_world(setup_262.game_dir / "saves", "future", "Snapshot World", "26.3", 6000)
    target = app.manager.create("Old Target", "26.2", "fabric")
    win = MainWindow(app)
    win.refresh_instances(select_id=target.id)
    win.tabs.setCurrentWidget(win.carry_tab)
    settle(qapp, win)
    tab = win.carry_tab
    assert tab.x_worlds.text() == "Worlds (1 of 2 can come)" and not tab.x_worlds.isChecked()  # never ticked for you

    from craftd.gui.dialogs import ChooseWorldsDialog
    dlg = ChooseWorldsDialog(tab.world_list, target, app.order, set(), tab, missing_mods=tab.missing_mods())
    texts = [dlg.list.item(r).text() for r in range(dlg.list.count())]
    assert any("newer than 26.2" in t for t in texts)
    blocked = next(r for r, t in enumerate(texts) if "Snapshot" in t)
    assert not (dlg.list.item(blocked).flags() & Qt.ItemFlag.ItemIsUserCheckable)

    survival = next(w for w in tab.world_list if w.folder == "survival")
    tab.world_choice = {survival.path}
    tab.x_worlds.setChecked(True)
    for row in range(tab.table.rowCount()):
        tab.table.item(row, 0).setCheckState(Qt.CheckState.Unchecked)
    tab._carry()
    settle(qapp, win)
    assert (target.game_dir / "saves" / "survival" / "level.dat").is_file()
    assert any("Worlds copied: My Survival" in b for b in boxes)


def test_share_dialog_and_import_mrpack(qapp, app, fake, setup_262, mmc, boxes, tmp_path, monkeypatch):
    setup_262.loader_version = "0.17.2"
    (setup_262.game_dir / "options.txt").write_text("fov:90")
    win = MainWindow(app)
    settle(qapp, win)
    monkeypatch.setattr(QMessageBox, "exec", lambda self: 0)
    dlg = ShareDialog(app, setup_262, win.runner, win)
    assert dlg.options.isChecked() and not dlg.servers.isEnabled() and dlg.local_jars.isChecked()
    dest = tmp_path / "out" / "Survival.mrpack"
    dlg._save(dest)
    settle(qapp, win)
    assert dlg.saved == dest
    with zipfile.ZipFile(dest) as zf:
        index = json.loads(zf.read("modrinth.index.json"))
    assert index["dependencies"]["fabric-loader"] == "0.17.2" and len(index["files"]) == 4

    # A friend opens it: Import from → Modpack file
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(dest), ""))
    monkeypatch.setattr(InstallPackDialog, "exec", lambda self: 1)
    monkeypatch.setattr(ImportDialog, "exec", lambda self: (self.rows["mrpack"].radio.setChecked(True),
                                                            self._next(), 1)[2])
    win.import_from()
    settle(qapp, win)
    inst = win.current()
    assert inst.name == "Survival 26.2" and inst.launcher == "multimc"
    assert len(list(inst.mods_dir.iterdir())) == 5 and (inst.game_dir / "options.txt").read_text() == "fov:90"


def test_browse_and_install_modpack(qapp, app, fake, setup_262, mmc, boxes, tmp_path):
    from craftd import mrpack
    from craftd.gui.modpacks import ModpacksDialog
    setup_262.loader_version = "0.17.2"
    out = tmp_path / "pack.mrpack"
    mrpack.export(app.scanner, app.client, setup_262, out, mrpack.ShareOptions(), "0.17.2")
    fake.add_modpack("cozy-pack", "Cozy Pack", "1.0", out.read_bytes(), ["26.2"], ["fabric"])
    win = MainWindow(app)
    settle(qapp, win)
    dlg = ModpacksDialog(app, win.runner, win)
    settle(qapp, win)
    assert dlg.list.count() == 1 and fake.last_search["project_type"] == "modpack"
    assert dlg.list.item(0).text().startswith("Cozy Pack")
    dlg.list.setCurrentRow(0)
    settle(qapp, win)
    assert dlg.pack_mc.currentText() == "26.2" and dlg.version.count() == 1 and dlg.install_btn.isEnabled()
    dlg.name.setText("Cozy")
    dlg.install()
    settle(qapp, win)
    assert dlg.installed and dlg.installed.name == "Cozy" and dlg.installed.launcher == "multimc"
    assert len(list(dlg.installed.mods_dir.iterdir())) == 5


def test_failures_go_to_the_log(qapp, app, boxes):
    from craftd import log
    path = log.setup(app.home)
    win = MainWindow(app)

    def boom(_p):
        raise RuntimeError("kaboom")

    win.runner.run(boom, on_error=lambda msg: boxes.append(msg))
    settle(qapp, win)
    for h in log.log.handlers:
        h.flush()
    assert "kaboom" in boxes and "RuntimeError: kaboom" in path.read_text()
