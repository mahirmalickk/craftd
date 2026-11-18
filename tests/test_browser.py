"""The store-style Modrinth browser, driven offscreen against the fake Modrinth."""

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from craftd.gui.browser import HIT_ROLE, BrowseModsDialog, clean_markdown, relative_time, short_number  # noqa: E402
from craftd.gui.main_window import MainWindow  # noqa: E402


def qapp():
    return QApplication.instance() or QApplication([])


def settle(win, timeout=10):
    q, end = qapp(), time.time() + timeout
    while time.time() < end:
        q.processEvents()
        if not win.runner.active:
            q.processEvents()
            return
        time.sleep(0.01)
    raise AssertionError("background work didn't finish")


def open_browser(app, fake, monkeypatch, **inst_kw):
    qapp()
    monkeypatch.setattr(QMessageBox, "warning", lambda *a: None)
    inst = app.manager.create("T", inst_kw.get("gv", "26.3"), inst_kw.get("loader", "fabric"))
    fake.place(fake.v["sodium263"], inst.mods_dir)
    win = MainWindow(app)
    settle(win)
    dlg = BrowseModsDialog(app, win.runner, inst, win)
    dlg.resize(1000, 650)
    dlg.show()
    settle(win)
    return win, dlg, inst


def titles(dlg):
    return [dlg.list.item(i).data(HIT_ROLE)["title"] for i in range(dlg.list.count())]


def test_helpers():
    assert short_number(288_624_256) == "289M" and short_number(1534) == "1.5K" and short_number(12) == "12"
    assert relative_time("2000-01-01T00:00:00Z").endswith("years ago") and relative_time(None) == ""
    md = clean_markdown('<center><img src="x.png"></center>\n![shot](a.png)\n**Fast** mod')
    assert "img" not in md and "shot" not in md and "**Fast** mod" in md


def test_installed_hidden_by_default_and_shown_on_toggle(app, fake, monkeypatch):
    win, dlg, inst = open_browser(app, fake, monkeypatch)
    assert "Sodium" not in titles(dlg) and "Lithium" in titles(dlg)
    assert "1 installed hidden" in dlg.status.text()
    dlg.hide_installed.setChecked(False)
    assert "Sodium" in titles(dlg)
    assert dlg.state_of("sodium") == "installed"


def test_category_chip_and_sort_reach_modrinth(app, fake, monkeypatch):
    fake.add_version("chunky", "Chunky", "1.0", ["26.3"], ["fabric"], categories=("worldgen",))
    win, dlg, inst = open_browser(app, fake, monkeypatch)
    assert fake.last_search["index"] == "downloads"
    chip = next(b for b in dlg.chip_group.buttons() if b.property("slug") == "worldgen")
    chip.click()
    settle(win)
    assert fake.last_search["category"] == "worldgen" and titles(dlg) == ["Chunky"]
    dlg.sort.setCurrentIndex(dlg.sort.findData("updated"))
    settle(win)
    assert fake.last_search["index"] == "updated"
    dlg.search.setText("chu")  # typing switches to relevance
    assert dlg.sort.currentData() == "relevance"


def test_add_button_click_queues_and_installs_with_dependencies(app, fake, monkeypatch):
    win, dlg, inst = open_browser(app, fake, monkeypatch)
    row = titles(dlg).index("Mod Menu")
    rect = dlg.list.visualItemRect(dlg.list.item(row))
    click = dlg.delegate.button_rect(rect).center()
    QTest.mouseClick(dlg.list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click)
    assert dlg.state_of("modmenu") == "queued"
    assert dlg.install_btn.text() == "Install 1 mod" and "Mod Menu" in dlg.queue_label.text()
    QTest.mouseClick(dlg.list.viewport(), Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, click)
    assert dlg.state_of("modmenu") == "add"  # clicking again removes it
    dlg.toggle_queue("modmenu")
    dlg.install()
    settle(win)
    assert sorted(p.name for p in inst.mods_dir.iterdir()) == [
        "fabric-api-0.125+26.3.jar", "modmenu-16.0+26.3.jar", "sodium-0.7.2+26.3.jar"]
    assert "Installed 2" in dlg.queue_label.text() and dlg.changed
    assert "Mod Menu" not in titles(dlg)  # now installed, so hidden
    _ = QPoint  # keep import used


def test_details_panel_and_version_picker(app, fake, monkeypatch):
    fake.add_version("lithium", "Lithium", "0.18-beta.1+26.3", ["26.3"], ["fabric"], version_type="beta")
    win, dlg, inst = open_browser(app, fake, monkeypatch)
    dlg.list.setCurrentRow(titles(dlg).index("Lithium"))
    settle(win)
    d = dlg.detail
    assert d.title.text() == "Lithium" and "great" in d.body.toPlainText()
    labels = [d.version.itemText(i) for i in range(d.version.count())]
    assert labels[0].startswith("0.18-beta.1+26.3") and "beta" in labels[0]
    assert "(recommended)" in d.version.currentText() and d.version.currentText().startswith("0.17+26.3")
    d.version.setCurrentIndex(0)  # pick the beta on purpose
    d.add_btn.click()
    assert dlg.queue["lithium"]["version_number"] == "0.18-beta.1+26.3"
    assert d.add_btn.text() == "Remove from queue"
    dlg.install()
    settle(win)
    assert (inst.mods_dir / "lithium-0.18-beta.1+26.3.jar").exists()


def test_infinite_scroll_loads_next_page(app, fake, monkeypatch):
    for i in range(45):
        fake.add_version(f"extra{i:02d}", f"Extra {i:02d}", "1.0", ["26.3"], ["fabric"])
    monkeypatch.setattr(BrowseModsDialog, "PAGE_SIZE", 20)
    win, dlg, inst = open_browser(app, fake, monkeypatch)
    first = dlg.list.count()
    assert first == 20 or first >= 12
    bar = dlg.list.verticalScrollBar()
    bar.setValue(bar.maximum())
    settle(win)
    assert dlg.list.count() > first


def test_loader_badge_and_neoforge_filter(app, fake, monkeypatch):
    win, dlg, inst = open_browser(app, fake, monkeypatch, loader="neoforge")
    badge = dlg.findChild(type(dlg.status), "LoaderBadge")
    assert badge.text() == "26.3 · NeoForge"
    assert titles(dlg) == []  # only Sodium ships for NeoForge here, and it's installed
    dlg.hide_installed.setChecked(False)
    assert titles(dlg) == ["Sodium"]
