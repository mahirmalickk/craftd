"""Regression tests for the Sodium beta / Iris crash on 26.3 (Nov 2026)."""

from fake_modrinth import FakeModrinth

from craftd.core import Craftd
from craftd.sync import Status


def build(tmp_path):
    f = FakeModrinth()
    v = {}
    # What a 26.2 instance had
    v["sod262"], _ = f.add_version("sodium", "Sodium", "mc26.2-0.8.0", ["26.2"], ["fabric"])
    v["iris262"], _ = f.add_version("iris", "Iris", "1.10.0+26.2", ["26.2"], ["fabric"], deps=("sodium",))
    # Real 26.3 situation: one Sodium release, then newer betas; Iris pins the release
    v["sod263"], _ = f.add_version("sodium", "Sodium", "mc26.3-0.9.2", ["26.3"], ["fabric"])
    v["iris263"], _ = f.add_version("iris", "Iris", "1.11.7+26.3", ["26.3"], ["fabric"],
                                    deps=(("sodium", "sodium-mc26.3-0.9.2"),))
    v["sodbeta"], _ = f.add_version("sodium", "Sodium", "mc26.3-0.9.3-beta.5", ["26.3"], ["fabric"],
                                    version_type="beta")
    app = Craftd(home=tmp_path / "home", client=f)
    app.refresh_game_versions()
    src = app.manager.create("Old", "26.2", "fabric")
    f.place(v["sod262"], src.mods_dir)
    f.place(v["iris262"], src.mods_dir)
    return f, v, app, src


def test_carry_over_picks_release_that_iris_needs(tmp_path):
    f, v, app, src = build(tmp_path)
    target = app.manager.create("New", "26.3", "fabric")
    cands = {c.title: c for c in app.carry.detect(target, [src])}
    assert cands["Sodium"].status == Status.AVAILABLE
    assert cands["Sodium"].target_version["version_number"] == "mc26.3-0.9.2"
    assert not cands["Sodium"].is_prerelease
    app.carry.carry(target, list(cands.values()))
    assert sorted(p.name for p in target.mods_dir.iterdir()) == ["iris-1.11.7+26.3.jar", "sodium-mc26.3-0.9.2.jar"]


def test_pin_from_mod_already_in_target(tmp_path):
    f, v, app, src = build(tmp_path)
    target = app.manager.create("New", "26.3", "fabric")
    f.place(v["iris263"], target.mods_dir)  # Iris installed earlier, Sodium not yet
    f.add_version("sodium", "Sodium", "mc26.3-0.9.4", ["26.3"], ["fabric"])  # newer release Iris doesn't accept
    sod = next(c for c in app.carry.detect(target, [src]) if c.title == "Sodium")
    assert sod.target_version["version_number"] == "mc26.3-0.9.2"
    assert sod.note == "Exact version required by Iris"


def test_dependency_install_uses_pinned_version(tmp_path):
    f, v, app, src = build(tmp_path)
    target = app.manager.create("New", "26.3", "fabric")
    app.installer.install_projects(target, ["iris"])
    assert sorted(p.name for p in target.mods_dir.iterdir()) == ["iris-1.11.7+26.3.jar", "sodium-mc26.3-0.9.2.jar"]


def test_beta_used_when_it_is_the_only_option(tmp_path):
    f = FakeModrinth()
    old, _ = f.add_version("lithium", "Lithium", "0.16", ["26.2"], ["fabric"])
    f.add_version("lithium", "Lithium", "0.17-beta.1", ["26.3"], ["fabric"], version_type="beta")
    app = Craftd(home=tmp_path / "home", client=f)
    src = app.manager.create("Old", "26.2", "fabric")
    f.place(old, src.mods_dir)
    target = app.manager.create("New", "26.3", "fabric")
    lith = app.carry.detect(target, [src])[0]
    assert lith.status == Status.AVAILABLE and lith.is_prerelease and "beta" in lith.note


def test_updates_skip_betas_and_pinned_versions(tmp_path):
    f, v, app, src = build(tmp_path)
    target = app.manager.create("New", "26.3", "fabric")
    f.place(v["sod263"], target.mods_dir)
    f.place(v["iris263"], target.mods_dir)
    assert app.installer.check_updates(target, app.scanner.scan(target)) == {}
    # Without Iris pinning it, a beta still isn't offered over a release...
    (target.mods_dir / "iris-1.11.7+26.3.jar").unlink()
    assert app.installer.check_updates(target, app.scanner.scan(target)) == {}
    # ...but a newer full release is.
    f.add_version("sodium", "Sodium", "mc26.3-0.9.4", ["26.3"], ["fabric"])
    ups = app.installer.check_updates(target, app.scanner.scan(target))
    assert [u["version_number"] for u in ups.values()] == ["mc26.3-0.9.4"]


def test_beta_user_keeps_getting_betas(tmp_path):
    f, v, app, src = build(tmp_path)
    target = app.manager.create("New", "26.3", "fabric")
    f.place(v["sodbeta"], target.mods_dir)
    f.add_version("sodium", "Sodium", "mc26.3-0.9.3-beta.6", ["26.3"], ["fabric"], version_type="beta")
    ups = app.installer.check_updates(target, app.scanner.scan(target))
    assert [u["version_number"] for u in ups.values()] == ["mc26.3-0.9.3-beta.6"]
