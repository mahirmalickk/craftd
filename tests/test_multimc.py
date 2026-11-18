"""MultiMC instances: same format as Prism, linked from a folder the user sets."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402

from craftd.settings import Settings  # noqa: E402


def qapp():
    return QApplication.instance() or QApplication([])


def multimc_instance(folder, name, comps):
    inst = folder / name
    (inst / ".minecraft" / "mods").mkdir(parents=True)
    (inst / "instance.cfg").write_text(f"InstanceType=OneSix\nname={name}\n")
    (inst / "mmc-pack.json").write_text(json.dumps(
        {"formatVersion": 1, "components": [{"uid": u, "version": v} for u, v in comps]}))
    return inst


def test_link_multimc_instance(app, tmp_path):
    folder = tmp_path / "MultiMC" / "instances"
    path = multimc_instance(folder, "Forge 1.20.1", [("net.minecraft", "1.20.1"), ("net.minecraftforge", "47.3.0")])
    inst = app.manager.link_prism(path, "multimc")
    assert inst.id.startswith("multimc-") and inst.kind == "prism" and inst.launcher == "multimc"
    assert inst.launcher_label == "MultiMC" and inst.loader_text == "Forge 47.3.0"
    assert inst.game_dir == path / ".minecraft"
    again = app.manager.get(inst.id)  # survives a reload
    assert again.launcher_label == "MultiMC"


def test_old_links_are_prism(app, tmp_path):
    path = multimc_instance(tmp_path / "p", "Old", [("net.minecraft", "26.2")])
    inst = app.manager.link_prism(path)
    assert inst.launcher_label == "Prism"
    entries = json.loads(app.manager.linked_file.read_text())
    for e in entries:
        e.pop("launcher", None)  # links saved by 0.8.2 and earlier have no launcher
    app.manager.linked_file.write_text(json.dumps(entries))
    assert app.manager.get(inst.id).launcher_label == "Prism"


def test_import_from_multimc_window(app, tmp_path, monkeypatch):
    from craftd.gui.dialogs import ImportPrismDialog
    from craftd.gui.main_window import MainWindow
    qapp()
    folder = tmp_path / "MultiMC" / "instances"
    multimc_instance(folder, "Fabric 1.21", [("net.minecraft", "1.21.1"), ("net.fabricmc.fabric-loader", "0.16.5")])
    win = MainWindow(app)

    # Not set yet: the dialog explains how to find the folder
    dlg = ImportPrismDialog(app, win, launcher="multimc")
    assert dlg.folder is None and "View Instance Folder" in dlg.folder_label.text()
    assert dlg.windowTitle() == "Import from MultiMC"

    # Choosing it there links from it and remembers it for next time
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(folder))
    dlg._choose()
    assert dlg.list.count() == 1 and "Fabric 1.21" in dlg.list.item(0).text()
    assert Settings.load(app.home).multimc_folder == str(folder)
    dlg._link()
    assert dlg.linked[0].launcher_label == "MultiMC"

    win.refresh_instances(select_id=dlg.linked[0].id)
    assert "Linked MultiMC instance" in win.subtitle.fullText()
    row = [i.id for i in win.instances].index(dlg.linked[0].id)
    from craftd.gui.widgets import KIND_ROLE
    assert win.list.item(row).data(KIND_ROLE) == "MultiMC"

    # Next time, it opens straight in the saved folder
    assert ImportPrismDialog(app, win, launcher="multimc").folder == folder


def test_multimc_folder_in_settings(app):
    from craftd.gui.dialogs import SettingsDialog
    from craftd.gui.main_window import MainWindow
    qapp()
    win = MainWindow(app)
    dlg = SettingsDialog(app, win.themer, win)
    dlg.multimc_folder.setText(r"C:\MultiMC\instances")
    dlg._save()
    assert Settings.load(app.home).multimc_folder == r"C:\MultiMC\instances"


def test_instance_names_wrap_instead_of_being_cut(app, tmp_path):
    """Narrow sidebar: every word of the name and details is still drawn, on more lines."""
    from PySide6.QtGui import QFont, QFontMetrics
    from craftd.gui.main_window import MainWindow
    from craftd.gui.widgets import InstanceDelegate, wrap_words
    qapp()
    path = multimc_instance(tmp_path / "mmc", "My Big Modded Survival World",
                            [("net.minecraft", "1.21.11"), ("net.fabricmc.fabric-loader", "0.17.2")])
    inst = app.manager.link_prism(path, "multimc")
    win = MainWindow(app)
    win.refresh_instances(select_id=inst.id)
    row = [i.id for i in win.instances].index(inst.id)
    index = win.list.model().index(row, 0)
    delegate: InstanceDelegate = win.list.itemDelegate()
    font = win.list.font()

    wide = delegate.layout(index, 600, font)
    narrow = delegate.layout(index, 190, font)
    assert len(wide[0]) == 1 and len(wide[1]) == 1
    assert len(narrow[0]) > 1 and len(narrow[1]) > 1 and narrow[2] > wide[2]  # taller, not cut
    assert " ".join(narrow[0]) == "My Big Modded Survival World"
    assert " · ".join(narrow[1]) == "1.21.11 · Fabric · MultiMC"
    assert not any("…" in line for line in narrow[0] + narrow[1])

    fm = QFontMetrics(QFont())
    assert wrap_words("Supercalifragilistic", fm, 40)  # a too-long word is split, never dropped
    assert "".join(wrap_words("Supercalifragilistic", fm, 40)) == "Supercalifragilistic"
