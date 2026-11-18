import json

from craftd.cli import main as cli_main
from craftd.mods import sha1_file
from craftd.sync import Status


def by_title(cands):
    return {c.title: c for c in cands}


def test_detects_mods_from_262_for_263(app, setup_262):
    target = app.manager.create("Survival 26.3", "26.3", "fabric")
    cands = by_title(app.carry.detect(target, [setup_262]))

    assert cands["Sodium"].status == Status.AVAILABLE
    assert cands["Sodium"].target_version_number == "0.7.2+26.3"
    assert cands["Lithium"].status == Status.AVAILABLE
    assert cands["Fabric API"].status == Status.AVAILABLE
    assert cands["YetAnotherConfigLib"].status == Status.UNAVAILABLE
    assert cands["My Private Mod"].status == Status.LOCAL
    assert all(c.sources == ["Survival 26.2"] for c in cands.values())


def test_carry_installs_verified_files_and_waitlists_the_rest(app, fake, setup_262):
    target = app.manager.create("Survival 26.3", "26.3", "fabric")
    cands = app.carry.detect(target, [setup_262])
    report = app.carry.carry(target, [c for c in cands if c.status != Status.LOCAL])

    files = {p.name: p for p in target.mods_dir.iterdir()}
    assert set(files) == {"sodium-0.7.2+26.3.jar", "lithium-0.17+26.3.jar", "fabric-api-0.125+26.3.jar"}
    assert sha1_file(files["sodium-0.7.2+26.3.jar"]) == fake.v["sodium263"]["files"][0]["hashes"]["sha1"]
    assert report.waitlisted == ["YetAnotherConfigLib"]
    assert [e["title"] for e in app.carry.waitlist(target)] == ["YetAnotherConfigLib"]

    # Running detection again shows everything as installed (no duplicates offered)
    again = by_title(app.carry.detect(target, [setup_262]))
    assert again["Sodium"].status == Status.INSTALLED
    assert again["YetAnotherConfigLib"].status == Status.WAITLISTED  # already waiting: not offered again


def test_copy_local_copies_unknown_jars_only_when_asked(app, setup_262):
    target = app.manager.create("Survival 26.3", "26.3", "fabric")
    cands = app.carry.detect(target, [setup_262])
    local = [c for c in cands if c.status == Status.LOCAL]
    app.carry.carry(target, local)
    assert not (target.mods_dir / "my-private-mod-1.0.jar").exists()
    report = app.carry.carry(target, local, copy_local=True)
    assert (target.mods_dir / "my-private-mod-1.0.jar").exists()
    assert report.copied == ["My Private Mod"]
    assert by_title(app.carry.detect(target, [setup_262]))["My Private Mod"].status == Status.INSTALLED


def test_required_dependencies_are_pulled_in(app, fake):
    target = app.manager.create("Fresh 26.3", "26.3", "fabric")
    report = app.installer.install_projects(target, ["modmenu"])
    names = sorted(p.name for p in target.mods_dir.iterdir())
    assert names == ["fabric-api-0.125+26.3.jar", "modmenu-16.0+26.3.jar"]
    assert "Fabric API 0.125+26.3" in report.installed


def test_waitlist_notices_new_builds(app, fake, setup_262):
    target = app.manager.create("Survival 26.3", "26.3", "fabric")
    app.carry.carry(target, app.carry.detect(target, [setup_262]))
    assert app.carry.check_waitlist(target) == []

    fake.add_version("yacl", "YetAnotherConfigLib", "3.8+26.3", ["26.3"], ["fabric"], deps=("fabric-api",))
    ready = app.carry.check_waitlist(target)
    assert [c.title for c in ready] == ["YetAnotherConfigLib"]
    assert app.carry.check_all_waitlists(app.manager.list()) .keys() == {target.id}

    report = app.carry.install_from_waitlist(target, ready)
    assert report.installed == ["YetAnotherConfigLib 3.8+26.3"]
    assert app.carry.waitlist(target) == []


def test_suggests_closest_older_instance_with_same_loader(app, fake):
    old = app.manager.create("Old", "1.21.11", "fabric")
    mid = app.manager.create("Mid", "26.1", "fabric")
    best = app.manager.create("Best", "26.2", "fabric")
    neo = app.manager.create("Neo", "26.2", "neoforge")
    empty = app.manager.create("Empty", "26.2", "quilt")  # no mods -> never suggested
    for inst in (old, mid, best, neo):
        fake.place(fake.v["sodium262"], inst.mods_dir)
    target = app.manager.create("New", "26.3", "fabric")
    assert app.carry.suggest_source(target, app.manager.list()).name == "Best"

    neo_target = app.manager.create("New Neo", "26.3", "neoforge")
    assert app.carry.suggest_source(neo_target, app.manager.list()).name == "Neo"
    assert empty.name != app.carry.suggest_source(target, app.manager.list()).name


def test_cross_loader_and_quilt(app, setup_262):
    # Sodium also ships for NeoForge, so a NeoForge 26.3 target can still get it
    neo = app.manager.create("Neo 26.3", "26.3", "neoforge")
    cands = by_title(app.carry.detect(neo, [setup_262]))
    assert cands["Sodium"].status == Status.AVAILABLE
    assert cands["Lithium"].status == Status.WRONG_LOADER
    # Quilt runs Fabric mods
    quilt = app.manager.create("Quilt 26.3", "26.3", "quilt")
    assert by_title(app.carry.detect(quilt, [setup_262]))["Lithium"].status == Status.AVAILABLE


def test_multiple_sources_are_merged(app, fake, setup_262):
    other = app.manager.create("Creative 26.1", "26.1", "fabric")
    fake.place(fake.v["sodium262"], other.mods_dir)
    target = app.manager.create("Survival 26.3", "26.3", "fabric")
    cands = by_title(app.carry.detect(target, [setup_262, other]))
    assert sorted(cands["Sodium"].sources) == ["Creative 26.1", "Survival 26.2"]
    assert len([c for c in cands.values() if c.title == "Sodium"]) == 1


def test_offline_scan_still_lists_mods(app, fake, setup_262):
    fake.online = False
    mods = app.scanner.scan(setup_262)
    assert app.scanner.offline
    assert len(mods) == 5
    assert "Sodium" in {m.title for m in mods}  # name read from the jar itself


def test_hash_cache_avoids_repeat_lookups(app, fake, setup_262):
    app.scanner.scan(setup_262)
    fake.calls.clear()
    app.scanner.scan(setup_262)
    assert "versions_from_hashes" not in fake.calls


def test_toggle_update_and_remove(app, fake):
    inst = app.manager.create("T", "26.3", "fabric")
    fake.place(fake.v["sodium263"], inst.mods_dir)
    old_lithium = fake.add_version("lithium", "Lithium", "0.16.9+26.3", ["26.3"], ["fabric"])[0]
    # make the 0.17 build the newest by publishing it again later
    fake.versions.remove(fake.v["lithium263"]); fake.versions.append({**fake.v["lithium263"], "date_published": "2026-12-01T00:00:00Z"})
    fake.place(old_lithium, inst.mods_dir)

    mods = {m.title: m for m in app.scanner.scan(inst)}
    app.installer.set_enabled(mods["Sodium"], False)
    mods = {m.title: m for m in app.scanner.scan(inst)}
    assert not mods["Sodium"].enabled and mods["Sodium"].path.name.endswith(".jar.disabled")

    updates = app.installer.check_updates(inst, list(mods.values()))
    assert list(updates) == [mods["Lithium"].sha1]
    app.installer.update(inst, mods["Lithium"], updates[mods["Lithium"].sha1])
    names = sorted(p.name for p in inst.mods_dir.iterdir())
    assert names == ["lithium-0.17+26.3.jar", "sodium-0.7.2+26.3.jar.disabled"]

    app.installer.remove(mods["Sodium"])
    assert [p.name for p in inst.mods_dir.iterdir()] == ["lithium-0.17+26.3.jar"]


def test_prism_instances_are_linked_in_place(app, fake, tmp_path):
    prism = tmp_path / "PrismLauncher" / "instances" / "MyPack"
    (prism / "minecraft" / "mods").mkdir(parents=True)
    (prism / "instance.cfg").write_text("[General]\nname=My Prism Pack\n")
    (prism / "mmc-pack.json").write_text(json.dumps({"components": [
        {"uid": "net.minecraft", "version": "26.2"},
        {"uid": "net.fabricmc.fabric-loader", "version": "0.17.0"},
    ]}))
    fake.place(fake.v["lithium262"], prism / "minecraft" / "mods")

    found = app.manager.discover_prism(prism.parent)
    assert [info["name"] for _, info in found] == ["My Prism Pack"]
    inst = app.manager.link_prism(prism)
    assert (inst.kind, inst.game_version, inst.loader) == ("prism", "26.2", "fabric")
    assert app.manager.discover_prism(prism.parent) == []

    target = app.manager.create("New", "26.3", "fabric")
    assert app.carry.suggest_source(target, app.manager.list()).id == inst.id
    assert by_title(app.carry.detect(target, [inst]))["Lithium"].status == Status.AVAILABLE

    app.manager.remove(inst)  # unlink only
    assert (prism / "minecraft" / "mods").is_dir() and app.manager.get(inst.id) is None


def test_cli_end_to_end(app, setup_262, capsys):
    app.manager.create("Survival 26.3", "26.3", "fabric")
    assert cli_main(["detect", "Survival 26.3"], app=app) == 0
    out = capsys.readouterr().out
    assert "auto-detected" in out and "Survival 26.2" in out and "No build yet" in out
    assert cli_main(["carry", "Survival 26.3", "--yes"], app=app) == 0
    assert "Installed 3" in capsys.readouterr().out


def test_fabric_only_mods_are_not_waitlisted_for_neoforge(app, setup_262):
    neo = app.manager.create("Neo 26.3", "26.3", "neoforge")
    cands = by_title(app.carry.detect(neo, [setup_262]))
    assert cands["Sodium"].status == Status.AVAILABLE  # ships for both loaders
    assert cands["Fabric API"].status == Status.WRONG_LOADER
    assert cands["Lithium"].status == Status.WRONG_LOADER
    assert "fabric" in cands["Lithium"].note
    report = app.carry.carry(neo, list(cands.values()))
    assert report.waitlisted == [] and app.carry.waitlist(neo) == []
    assert [p.name for p in neo.mods_dir.iterdir()] == ["sodium-0.7.2+26.3.jar"]
