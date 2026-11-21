"""1.1: instances are made inside Prism/MultiMC, with each launcher's own game-folder rule."""

import json

import pytest

from craftd.launchers import copy_instance, create_instance, game_dir, write_cfg_name
from craftd.instances import read_prism_instance


def test_game_folder_rule_matches_each_launcher(tmp_path):
    root = tmp_path / "inst"
    root.mkdir()
    # never launched: each launcher's default
    assert game_dir(root, "multimc") == root / ".minecraft"
    assert game_dir(root, "prism") == root / "minecraft"
    # only "minecraft" exists: both use it
    (root / "minecraft").mkdir()
    assert game_dir(root, "multimc") == root / "minecraft"
    assert game_dir(root, "prism") == root / "minecraft"
    # both exist: MultiMC prefers .minecraft, Prism prefers minecraft
    (root / ".minecraft").mkdir()
    assert game_dir(root, "multimc") == root / ".minecraft"
    assert game_dir(root, "prism") == root / "minecraft"


def test_friends_bug_new_multimc_instance_gets_mods_where_multimc_looks(app, tmp_path):
    """A MultiMC instance that was never launched: carried-over mods must go in .minecraft/mods."""
    folder = tmp_path / "MultiMC" / "instances"
    (folder / "Fabric 26.3").mkdir(parents=True)
    (folder / "Fabric 26.3" / "instance.cfg").write_text("InstanceType=OneSix\nname=Fabric 26.3\n")
    (folder / "Fabric 26.3" / "mmc-pack.json").write_text(json.dumps({"components": [
        {"uid": "net.minecraft", "version": "26.3"}, {"uid": "net.fabricmc.fabric-loader", "version": "0.17.2"}]}))
    inst = app.manager.link_prism(folder / "Fabric 26.3", "multimc")
    assert inst.mods_dir == folder / "Fabric 26.3" / ".minecraft" / "mods"


@pytest.mark.parametrize("launcher,dirname", [("multimc", ".minecraft"), ("prism", "minecraft")])
def test_create_instance_in_launcher(app, tmp_path, launcher, dirname):
    parent = tmp_path / launcher / "instances"
    parent.mkdir(parents=True)
    inst = app.manager.create_in_launcher(launcher, parent, "Fabric 26.3", "26.3", "fabric", "0.17.2")
    root = parent / "Fabric 26.3"
    assert inst.root == root.resolve() or inst.root == root
    assert (root / dirname / "mods").is_dir() and inst.mods_dir.name == "mods"
    assert inst.mods_dir.parent.name == dirname
    cfg = (root / "instance.cfg").read_text()
    assert "InstanceType=OneSix" in cfg and "name=Fabric 26.3" in cfg
    comps = json.loads((root / "mmc-pack.json").read_text())["components"]
    assert {c["uid"]: c["version"] for c in comps} == {
        "net.minecraft": "26.3", "net.fabricmc.intermediary": "26.3", "net.fabricmc.fabric-loader": "0.17.2"}
    assert inst.kind == "prism" and inst.launcher == launcher and inst.loader_text == "Fabric 0.17.2"
    # a second one with the same name gets its own folder
    again = app.manager.create_in_launcher(launcher, parent, "Fabric 26.3", "26.3", "fabric", "0.17.2")
    assert again.root.name == "Fabric 26.3 (2)" and again.id != inst.id


def test_unsafe_names_and_vanilla(tmp_path):
    root = create_instance(tmp_path, 'Big: "Survival"?', "26.3", "vanilla", None, "prism")
    assert root.name == "Big- -Survival--"
    info = read_prism_instance(root)
    assert info["name"] == 'Big: "Survival"?' and info["loader"] == "vanilla"
    with pytest.raises(ValueError):
        create_instance(tmp_path, "X", "26.3", "fabric", None, "prism")  # a loader needs a version


def test_prism_quoted_names_are_read_and_written(tmp_path):
    cfg = tmp_path / "instance.cfg"
    cfg.write_text('[General]\nConfigVersion=1.3\nname="Create, Survival"\niconKey=default\n')
    (tmp_path / "mmc-pack.json").write_text(json.dumps({"components": [{"uid": "net.minecraft", "version": "26.3"}]}))
    assert read_prism_instance(tmp_path)["name"] == "Create, Survival"
    write_cfg_name(cfg, "Hard, Mode")
    assert 'name="Hard, Mode"' in cfg.read_text() and "iconKey=default" in cfg.read_text()
    assert read_prism_instance(tmp_path)["name"] == "Hard, Mode"


def test_rename_copy_delete_linked(app, tmp_path):
    parent = tmp_path / "prism"
    parent.mkdir()
    inst = app.manager.create_in_launcher("prism", parent, "Fabric 26.3", "26.3", "fabric", "0.17.2")
    (inst.mods_dir / "a.jar").write_bytes(b"x")
    renamed = app.manager.rename(inst, "My World")
    assert renamed.name == "My World" and renamed.root == inst.root  # the folder keeps its name, like Prism
    copy = app.manager.copy(renamed, "My World (Copy)")
    assert copy.id != inst.id and copy.name == "My World (Copy)" and (copy.mods_dir / "a.jar").is_file()
    trashed = []
    app.manager.delete(copy, remove_folder=lambda p: trashed.append(p) or True)
    assert trashed == [copy.root] and app.manager.get(copy.id) is None
    app.manager.delete(renamed)
    assert not inst.root.exists() and app.manager.list() == []


def test_copy_instance_keeps_files(tmp_path):
    root = create_instance(tmp_path, "A", "26.3", "fabric", "0.17.2", "multimc")
    (root / ".minecraft" / "options.txt").write_text("fov:90")
    dest = copy_instance(root, "A (Copy)")
    assert (dest / ".minecraft" / "options.txt").read_text() == "fov:90"
    assert read_prism_instance(dest, "multimc")["name"] == "A (Copy)"


def test_move_craftd_instance_to_launcher(app, fake, tmp_path):
    """The fix for instances made with + New Instance before 1.1 (they couldn't be launched)."""
    old = app.manager.create("Fabric 26.3", "26.3", "fabric")
    fake.place(fake.v["sodium263"], old.mods_dir)
    (old.game_dir / "config").mkdir()
    (old.game_dir / "config" / "sodium.json").write_text("{}")
    app.manager.save_meta(old, {"waitlist": [{"project_id": "yacl", "title": "YACL"}]})
    parent = tmp_path / "MultiMC" / "instances"
    parent.mkdir(parents=True)
    new = app.manager.move_to_launcher(old, "multimc", parent, "0.17.2")
    assert new.launcher == "multimc" and new.name == "Fabric 26.3"
    assert [p.name for p in new.mods_dir.iterdir()] == ["sodium-0.7.2+26.3.jar"]
    assert (new.game_dir / "config" / "sodium.json").is_file()
    assert new.game_dir.name == ".minecraft"
    assert app.manager.load_meta(new)["waitlist"][0]["title"] == "YACL"
    assert not old.root.exists() and [i.id for i in app.manager.list()] == [new.id]


def test_core_new_instance_uses_launcher_and_default_loader(app, tmp_path, monkeypatch):
    from craftd.loaders import LoaderVersion
    monkeypatch.setattr(app, "loader_versions", lambda loader, mc, launcher="prism": [
        LoaderVersion("0.18.0", stable=False, released="2026-11-02"),
        LoaderVersion("0.17.2", recommended=True, released="2026-10-01")])
    with pytest.raises(ValueError, match="Settings"):
        app.new_instance("multimc", "X", "26.3", "fabric")  # MultiMC's folder isn't set
    folder = tmp_path / "mmc"
    folder.mkdir()
    app.settings.multimc_folder = str(folder)
    inst = app.new_instance("multimc", "Fabric 26.3", "26.3", "fabric")
    assert inst.loader_version == "0.17.2" and inst.launcher == "multimc"


def test_add_files(app, tmp_path):
    inst = app.manager.create("T", "26.3", "fabric")
    jar, txt = tmp_path / "cool-mod.jar", tmp_path / "readme.txt"
    jar.write_bytes(b"jar")
    txt.write_text("hi")
    added, skipped = app.installer.add_files(inst, [jar, txt])
    assert added == ["cool-mod.jar"] and skipped == ["readme.txt (not a .jar file)"]
    assert app.installer.add_files(inst, [jar]) == ([], ["cool-mod.jar (already there)"])
