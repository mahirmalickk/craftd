"""Edit Instance: change a name, Minecraft version or loader (e.g. 26.3 Vanilla → 26.3 Fabric)."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QMessageBox  # noqa: E402

from craftd import loaders  # noqa: E402
from craftd.instances import read_prism_instance  # noqa: E402
from craftd.loaders import LoaderVersion, build_components, default_version, parse_index  # noqa: E402
import test_gui  # noqa: E402

qapp = test_gui.qapp  # the shared QApplication fixture
settle = test_gui.settle

# Shaped like meta.prismlauncher.org/v1/<uid>/index.json
NEOFORGE_INDEX = {"versions": [
    {"version": "26.3.0.110", "type": "release", "recommended": False, "releaseTime": "2026-11-17T10:00:00+00:00",
     "requires": [{"uid": "net.minecraft", "equals": "26.3"}]},
    {"version": "26.2.0.94", "type": "release", "recommended": True, "releaseTime": "2026-11-16T23:54:00+00:00",
     "requires": [{"uid": "net.minecraft", "equals": "26.2"}]},
    {"version": "26.3.0.75-beta", "type": "release", "recommended": False, "releaseTime": "2026-11-01T00:00:00+00:00",
     "requires": [{"uid": "net.minecraft", "equals": "26.3"}]},
    {"version": "26.3.0.106", "type": "release", "recommended": False, "releaseTime": "2026-11-17T00:01:00+00:00",
     "requires": [{"uid": "net.minecraft", "equals": "26.3"}]},
]}
FABRIC_INDEX = {"versions": [
    {"version": "0.20.0", "type": "release", "recommended": False, "releaseTime": "2026-10-15T10:23:56+00:00",
     "requires": [{"uid": "net.fabricmc.intermediary"}]},
    {"version": "0.20.1", "type": "release", "recommended": True, "releaseTime": "2026-10-19T19:02:12+00:00",
     "requires": [{"uid": "net.fabricmc.intermediary"}]},
]}


def test_loader_lists_match_the_launcher():
    neo = parse_index(NEOFORGE_INDEX, "neoforge", "26.3")
    assert [v.version for v in neo] == ["26.3.0.110", "26.3.0.106", "26.3.0.75-beta"]  # only 26.3, newest first
    assert [v.stable for v in neo] == [True, True, False]
    assert default_version(neo).version == "26.3.0.110"  # no recommended one for 26.3: newest stable
    fabric = parse_index(FABRIC_INDEX, "fabric", "26.3")  # Fabric Loader works on any Minecraft version
    assert [v.version for v in fabric] == ["0.20.1", "0.20.0"]
    assert default_version(fabric).version == "0.20.1" and fabric[0].label == "0.20.1 (recommended)"


def test_components_written_the_way_prism_writes_them():
    vanilla = [{"uid": "org.lwjgl3", "version": "3.3.3", "dependencyOnly": True},
               {"uid": "net.minecraft", "version": "26.3", "important": True},
               {"uid": "com.example.custom", "version": "1"}]
    fabric = build_components(vanilla, "26.3", "fabric", "0.20.1")
    assert [c["uid"] for c in fabric] == ["org.lwjgl3", "net.minecraft", "net.fabricmc.intermediary",
                                          "net.fabricmc.fabric-loader", "com.example.custom"]
    assert fabric[2] == {"dependencyOnly": True, "uid": "net.fabricmc.intermediary", "version": "26.3"}
    assert fabric[3] == {"uid": "net.fabricmc.fabric-loader", "version": "0.20.1"}

    neo = build_components(fabric, "26.3", "neoforge", "26.3.0.110")  # Fabric → NeoForge: Fabric pieces go
    assert [c["uid"] for c in neo] == ["org.lwjgl3", "net.minecraft", "net.neoforged", "com.example.custom"]

    newer = build_components(fabric, "26.4", "fabric", "0.20.1")  # new Minecraft: launcher re-picks LWJGL
    assert "org.lwjgl3" not in [c["uid"] for c in newer]
    assert newer[0]["version"] == "26.4" and newer[1]["version"] == "26.4"
    assert [c["uid"] for c in build_components(fabric, "26.3", "vanilla", None)] == \
        ["org.lwjgl3", "net.minecraft", "com.example.custom"]


def prism_vanilla(tmp_path, name="26.3"):
    inst = tmp_path / "PrismLauncher" / "instances" / name
    (inst / "minecraft" / "mods").mkdir(parents=True)
    (inst / "instance.cfg").write_text(f"InstanceType=OneSix\niconKey=default\nname={name}\n")
    (inst / "mmc-pack.json").write_text(json.dumps({"formatVersion": 1, "components": [
        {"uid": "org.lwjgl3", "version": "3.3.3", "dependencyOnly": True},
        {"uid": "net.minecraft", "version": "26.3", "important": True}]}))
    return inst


def test_edit_prism_instance_vanilla_to_fabric(app, tmp_path):
    path = prism_vanilla(tmp_path)
    inst = app.manager.link_prism(path)
    assert inst.loader == "vanilla"
    new = app.manager.edit(inst, "26.3 Fabric", "26.3", "fabric", "0.20.1")
    assert new.id == inst.id and new.loader == "fabric" and new.loader_version == "0.20.1"
    assert new.name == "26.3 Fabric" and "name=26.3 Fabric" in (path / "instance.cfg").read_text()
    assert "iconKey=default" in (path / "instance.cfg").read_text()  # other settings kept
    info = read_prism_instance(path)
    assert (info["loader"], info["loader_version"], info["game_version"]) == ("fabric", "0.20.1", "26.3")
    backups = list(path.glob("mmc-pack.json.craftd-backup-*"))
    assert len(backups) == 1 and "fabric" not in backups[0].read_text()
    assert not list(path.glob("*.craftd-tmp"))


def test_edit_craftd_instance(app):
    inst = app.manager.create("Test", "26.3", "vanilla")
    new = app.manager.edit(inst, "Test", "26.3", "neoforge", "26.3.0.110")
    again = app.manager.get(inst.id)
    assert new.loader == again.loader == "neoforge" and again.loader_version == "26.3.0.110"
    assert again.loader_text == "NeoForge 26.3.0.110"


def test_right_click_edit_in_window(qapp, app, tmp_path, monkeypatch):
    from craftd.gui.dialogs import EditInstanceDialog
    from craftd.gui.main_window import MainWindow
    path = prism_vanilla(tmp_path)
    inst = app.manager.link_prism(path)
    monkeypatch.setattr(app, "loader_versions", lambda loader, mc, launcher="prism": parse_index(
        FABRIC_INDEX if loader == "fabric" else NEOFORGE_INDEX, loader, mc))
    win = MainWindow(app)
    win.refresh_instances(select_id=inst.id)
    menu = win.instance_menu(win.current())
    assert [a.text() for a in menu.actions() if a.text()] == ["26.3", "Edit Instance…"]

    dlg = EditInstanceDialog(app, win.current(), win.runner, win)
    assert dlg.loader_version.isEnabled() is False and dlg.save_btn.isEnabled()  # vanilla: nothing to load
    dlg.loader.setCurrentIndex(dlg.loader.findData("fabric"))
    settle(qapp, win)
    assert dlg.loader_version.currentData() == "0.20.1" and dlg.save_btn.isEnabled()
    assert dlg.warning_box.isHidden()  # no mods yet: nothing to warn about

    # Prism is open: Craftd asks to close it and saves nothing on Cancel
    monkeypatch.setattr(loaders, "launcher_running", lambda launcher: True)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: QMessageBox.StandardButton.Cancel)
    dlg._save()
    assert dlg.result_instance is None and read_prism_instance(path)["loader"] == "vanilla"

    monkeypatch.setattr(loaders, "launcher_running", lambda launcher: False)
    dlg._save()
    assert dlg.result_instance.loader == "fabric"
    win.refresh_instances(select_id=inst.id)
    assert win.current().loader_text == "Fabric 0.20.1"


def test_switching_loader_warns_about_mods(qapp, app, setup_262, monkeypatch):
    from craftd.gui.dialogs import EditInstanceDialog
    from craftd.gui.main_window import MainWindow
    monkeypatch.setattr(app, "loader_versions",
                        lambda loader, mc, launcher="prism": [LoaderVersion("26.2.0.94", recommended=True)])
    win = MainWindow(app)
    dlg = EditInstanceDialog(app, setup_262, win.runner, win)
    assert dlg.warning_box.isHidden()
    dlg.loader.setCurrentIndex(dlg.loader.findData("neoforge"))
    settle(qapp, win)
    assert not dlg.warning_box.isHidden() and "made for Fabric" in dlg.warning.text()
    dlg.loader.setCurrentIndex(dlg.loader.findData("quilt"))  # Quilt runs Fabric mods: no warning
    settle(qapp, win)
    assert dlg.warning_box.isHidden()
    dlg.reject()
