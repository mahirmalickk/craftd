"""The Settings pages: what's saved, and that each option really changes what Craftd does."""

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from craftd.core import Craftd  # noqa: E402
from craftd.modrinth import ModrinthClient  # noqa: E402
from craftd.paths import prism_instance_dirs  # noqa: E402
from craftd.settings import Settings  # noqa: E402


def qapp():
    return QApplication.instance() or QApplication([])


def test_settings_load_old_files_and_junk(tmp_path):
    (tmp_path / "settings.json").write_text(json.dumps({"theme": "dark", "text_scale": 1.0}))
    s = Settings.load(tmp_path)  # a 0.7 file: new options get their defaults
    assert s.theme == "dark" and s.stable_first and s.auto_dependencies and s.proxy == "system"
    (tmp_path / "settings.json").write_text(json.dumps({"stable_first": "no", "proxy": "socks9", "timeout": 999,
                                                        "proxy_port": True, "hide_installed": False}))
    s = Settings.load(tmp_path)
    assert s.stable_first is True and s.proxy == "system" and s.timeout == 120 and s.proxy_port == 8080
    assert s.hide_installed is False


def test_craftd_hands_settings_to_the_engine(tmp_path, fake):
    Settings(stable_first=False, auto_dependencies=False).save(tmp_path)
    app = Craftd(home=tmp_path, client=fake)
    assert not app.installer.stable_first and not app.installer.auto_dependencies
    app.apply_settings(Settings())
    assert app.installer.stable_first and app.installer.auto_dependencies


def test_network_settings_reach_the_session():
    client = ModrinthClient()
    client.configure_network("http", "10.0.0.5", 3128, 30)
    assert client.session.proxies == {"http": "http://10.0.0.5:3128", "https": "http://10.0.0.5:3128"}
    assert client.timeout == 30 and client.session.trust_env is False
    client.configure_network("none")
    assert client.session.proxies == {} and client.session.trust_env is False
    client.configure_network("system")
    assert client.session.proxies == {} and client.session.trust_env is True


def test_stable_first_can_be_turned_off(app, fake):
    fake.add_version("sodium", "Sodium", "0.8.0-beta.1+26.3", ["26.3"], ["fabric"], version_type="beta")
    inst = app.manager.create("Beta 26.3", "26.3", "fabric")
    assert app.installer.resolve_project(inst, "sodium")["version_number"] == "0.7.2+26.3"
    app.apply_settings(Settings(stable_first=False))
    assert app.installer.resolve_project(inst, "sodium")["version_number"] == "0.8.0-beta.1+26.3"


def test_dependencies_listed_instead_of_installed_when_turned_off(app, fake):
    inst = app.manager.create("Plain 26.2", "26.2", "fabric")
    app.apply_settings(Settings(auto_dependencies=False))
    report = app.installer.install_versions(inst, [fake.v["yacl262"]])
    assert report.installed == ["YetAnotherConfigLib 3.7+26.2"]
    assert report.missing_deps == ["Fabric API (needed by YetAnotherConfigLib)"]
    assert len(list(inst.mods_dir.glob("*.jar"))) == 1


def test_custom_prism_folder_comes_first(tmp_path):
    folder = tmp_path / "PortablePrism" / "instances"
    folder.mkdir(parents=True)
    assert prism_instance_dirs(str(folder))[0] == folder
    assert str(tmp_path / "missing") not in map(str, prism_instance_dirs(str(tmp_path / "missing")))


def test_clear_cache_keeps_instances_and_settings(app, setup_262):
    app.scanner.scan(setup_262)  # fills the lookup cache
    app.cache.save()
    (app.home / "cache" / "icons").mkdir(parents=True, exist_ok=True)
    (app.home / "cache" / "icons" / "sodium.png").write_bytes(b"x" * 500)
    Settings(theme="dark").save(app.home)
    labels = {label for label, _ in app.cache_usage()}
    assert "Mod icons from Add from Modrinth" in labels and "Mod lookups (which jar is which Modrinth mod)" in labels
    app.clear_cache()
    assert app.cache_usage() == [] and not app.cache.hashes
    assert app.manager.list() and Settings.load(app.home).theme == "dark"


def test_settings_window_pages_save_and_apply(app, setup_262, monkeypatch):
    from craftd.gui.dialogs import SettingsDialog
    from craftd.gui.main_window import MainWindow
    qapp()
    win = MainWindow(app)
    dlg = SettingsDialog(app, win.themer, win)
    assert [dlg.nav.item(i).text() for i in range(dlg.nav.count())] == \
        ["General", "Accounts", "Appearance", "Mods", "Carry Over", "Storage", "Network", "About"]
    dlg.nav.setCurrentRow(6)
    assert dlg.pages.currentIndex() == 6
    assert not dlg.proxy_host.isEnabled()
    next(b for b in dlg.proxy_group.buttons() if b.property("mode") == "http").setChecked(True)
    assert dlg.proxy_host.isEnabled()
    dlg.proxy_host.setText("127.0.0.1")
    dlg.builds.setCurrentIndex(1)
    dlg.check_waitlist.setChecked(False)
    dlg.c_packs.setChecked(False)
    dlg.hide_installed.setChecked(False)
    dlg._save()

    saved = Settings.load(app.home)
    assert saved.proxy == "http" and saved.proxy_host == "127.0.0.1" and not saved.stable_first
    assert not saved.check_waitlist_on_start and not saved.carry_packs and not saved.hide_installed
    assert app.settings == saved and not app.installer.stable_first

    # waitlist check is skipped at startup when turned off
    calls = []
    monkeypatch.setattr(MainWindow, "_check_waitlists", lambda self: calls.append(1))
    MainWindow(app)
    assert calls == []

    # Add from Modrinth starts with "Hide installed" as set
    from craftd.gui.browser import BrowseModsDialog
    browser = BrowseModsDialog(app, win.runner, setup_262, win)
    assert not browser.hide_installed.isChecked()
    browser.reject()


def test_clear_cache_button(app, setup_262, monkeypatch):
    from craftd.gui.dialogs import SettingsDialog
    from craftd.gui.main_window import MainWindow
    qapp()
    app.scanner.scan(setup_262)
    app.cache.save()
    win = MainWindow(app)
    dlg = SettingsDialog(app, win.themer, win)
    assert dlg.cache_form.rowCount() >= 1
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Yes)
    dlg._clear_cache()
    assert dlg.cache_form.rowCount() == 0 and dlg.cache_total.text() == "The cache is empty."
    dlg.reject()


def test_theme_wording_follows_the_os(monkeypatch):
    """Windows says "Match Windows"; a Mac says "Match system" and points to its own Appearance setting."""
    import importlib
    import sys

    import craftd.settings as settings_mod
    try:
        monkeypatch.setattr(sys, "platform", "darwin")
        mac = importlib.reload(settings_mod)
        assert mac.THEMES["system"] == "Match system" and "Appearance" in mac.SYSTEM_THEME_WHERE
        monkeypatch.setattr(sys, "platform", "win32")
        win = importlib.reload(settings_mod)
        assert win.THEMES["system"] == "Match Windows" and "Personalization" in win.SYSTEM_THEME_WHERE
    finally:
        monkeypatch.undo()
        importlib.reload(settings_mod)
