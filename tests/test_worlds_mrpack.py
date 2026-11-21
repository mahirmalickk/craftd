"""1.1: worlds in Carry Over, modpacks (.mrpack) and Share Instance, and the log file."""

import gzip
import io
import json
import struct
import zipfile

import pytest

from craftd import mrpack, worlds
from craftd.versions import VersionOrder


# ---- a tiny NBT writer, to make real level.dat files -------------------------------------------
def _s(text: str) -> bytes:
    b = text.encode()
    return struct.pack(">H", len(b)) + b


def _compound(items: dict) -> bytes:
    out = b""
    for key, value in items.items():
        if isinstance(value, dict):
            out += b"\x0a" + _s(key) + _compound(value)
        elif isinstance(value, str):
            out += b"\x08" + _s(key) + _s(value)
        elif isinstance(value, int):
            out += b"\x03" + _s(key) + struct.pack(">i", value)
        elif isinstance(value, list):  # list of ints
            out += b"\x09" + _s(key) + b"\x03" + struct.pack(">i", len(value)) + b"".join(struct.pack(">i", v) for v in value)
    return out + b"\x00"


def make_world(saves, folder, name, version=None, data_version=None):
    w = saves / folder
    (w / "region").mkdir(parents=True)
    (w / "region" / "r.0.0.mca").write_bytes(b"\0" * 2048)
    data = {"LevelName": name, "SpawnX": 1, "Flags": [1, 2]}
    if version:
        data["Version"] = {"Name": version, "Id": data_version or 1}
        data["DataVersion"] = data_version or 1
    (w / "level.dat").write_bytes(gzip.compress(b"\x0a" + _s("") + _compound({"Data": data})))
    (w / "session.lock").write_bytes(b"lock")
    return w


@pytest.fixture
def order():
    return VersionOrder([{"version": v, "date": d} for v, d in
                         [("26.3", "2026-10"), ("26.2", "2026-07"), ("1.21.1", "2024-08")]])


def test_world_versions_and_rules(app, order):
    src = app.manager.create("Old", "26.2", "fabric")
    saves = src.game_dir / "saves"
    make_world(saves, "survival", "My Survival", "26.2", 5000)
    make_world(saves, "ancient", "Beta World")  # from before 1.9: no version in level.dat
    make_world(saves, "future", "From 26.3", "26.3", 6000)
    (saves / "not-a-world").mkdir()
    found = {w.folder: w for w in worlds.scan(src)}
    assert set(found) == {"survival", "ancient", "future"}
    assert (found["survival"].name, found["survival"].version, found["survival"].data_version) == ("My Survival", "26.2", 5000)
    assert found["ancient"].version is None and found["survival"].size > 2000

    same = app.manager.create("Same", "26.2", "fabric")
    newer = app.manager.create("New", "26.3", "fabric")
    older = app.manager.create("Older", "1.21.1", "fabric")
    assert worlds.why_not(found["survival"], newer, order) is None
    assert worlds.why_not(found["survival"], same, order) is None
    assert "newer than 1.21.1" in worlds.why_not(found["survival"], older, order)
    assert worlds.why_not(found["ancient"], older, order) is None
    assert "newer than 26.2" in worlds.why_not(found["future"], same, order)

    report = worlds.copy_worlds([found["survival"], found["future"]], same, order)
    assert report.copied == ["My Survival"] and "From 26.3" in report.skipped[0]
    copied = same.game_dir / "saves" / "survival"
    assert (copied / "level.dat").is_file() and not (copied / "session.lock").exists()
    assert (saves / "survival" / "level.dat").is_file()  # the original is untouched
    assert "Already in this instance" in worlds.why_not(found["survival"], same, order)


def test_unreadable_level_dat_is_still_listed(app):
    inst = app.manager.create("T", "26.3", "fabric")
    w = inst.game_dir / "saves" / "broken"
    w.mkdir(parents=True)
    (w / "level.dat").write_bytes(b"not nbt at all")
    [world] = worlds.scan(inst)
    assert world.name == "broken" and world.version is None


# ---- Share Instance → install the .mrpack -----------------------------------------------------
def test_share_then_install_roundtrip(app, fake, setup_262, tmp_path, order):
    src = setup_262
    gd = src.game_dir
    (gd / "config").mkdir()
    (gd / "config" / "sodium-options.json").write_text('{"quality": "fancy"}')
    (gd / "resourcepacks").mkdir()
    (gd / "resourcepacks" / "Faithful.zip").write_bytes(b"pack")
    (gd / "options.txt").write_text("fov:90")
    (gd / "servers.dat").write_bytes(b"servers")
    (gd / "logs").mkdir()
    (gd / "logs" / "latest.log").write_text("log")
    make_world(gd / "saves", "survival", "My Survival", "26.2", 5000)
    disabled = fake.place(fake.v["lithium262"], src.mods_dir)
    disabled.rename(disabled.with_name(disabled.name + ".disabled"))
    src.loader_version = "0.17.2"

    dest = tmp_path / "share" / "Survival 26.2.mrpack"
    report = mrpack.export(app.scanner, app.client, src, dest, mrpack.ShareOptions(worlds=["survival"]), "0.17.2")
    assert sorted(report.linked) == ["Fabric API", "Sodium", "YetAnotherConfigLib"]
    assert report.included_jars == ["My Private Mod"] and "1 turned-off mod(s)" in report.left_out
    assert "Saved Survival 26.2.mrpack" in report.summary()

    with zipfile.ZipFile(dest) as zf:
        names = set(zf.namelist())
        index = json.loads(zf.read("modrinth.index.json"))
    assert index["dependencies"] == {"minecraft": "26.2", "fabric-loader": "0.17.2"}
    assert all(f["downloads"][0].startswith("https://cdn.modrinth.com/") for f in index["files"])
    assert all(len(f["hashes"]["sha512"]) == 128 for f in index["files"])
    assert "overrides/mods/my-private-mod-1.0.jar" in names and "overrides/options.txt" in names
    assert "overrides/config/sodium-options.json" in names and "overrides/saves/survival/level.dat" in names
    assert "overrides/servers.dat" not in names and not any("logs" in n for n in names)  # servers off by default

    parent = tmp_path / "prism"
    parent.mkdir()
    inst = mrpack.install(app.manager, app.client, dest, "prism", parent, name="From a friend")
    assert inst.name == "From a friend" and inst.loader_text == "Fabric 0.17.2" and inst.game_version == "26.2"
    mods = sorted(p.name for p in inst.mods_dir.iterdir())
    assert mods == ["fabric-api-0.120+26.2.jar", "my-private-mod-1.0.jar", "sodium-0.7.0+26.2.jar",
                    "yacl-3.7+26.2.jar"]
    assert (inst.game_dir / "options.txt").read_text() == "fov:90"
    assert (inst.game_dir / "saves" / "survival" / "level.dat").is_file()


def _pack(index: dict, extra: dict | None = None) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps(index))
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_bad_packs_are_refused(tmp_path):
    base = {"formatVersion": 1, "game": "minecraft", "name": "P", "dependencies": {"minecraft": "26.3"}}
    cases = {
        "evil-path": {**base, "files": [{"path": "../../evil.jar", "hashes": {"sha1": "a"},
                                          "downloads": ["https://cdn.modrinth.com/x"]}]},
        "evil-host": {**base, "files": [{"path": "mods/a.jar", "hashes": {"sha1": "a"},
                                          "downloads": ["https://evil.example/a.jar"]}]},
        "no-mc": {**base, "dependencies": {}},
    }
    for name, index in cases.items():
        p = tmp_path / f"{name}.mrpack"
        p.write_bytes(_pack(index))
        with pytest.raises(mrpack.PackError):
            mrpack.read_index(p)
    p = tmp_path / "not-a-pack.mrpack"
    p.write_bytes(b"hello")
    with pytest.raises(mrpack.PackError):
        mrpack.read_index(p)
    p = tmp_path / "escape.mrpack"
    p.write_bytes(_pack({**base, "files": []}, {"overrides/../../escape.txt": "x"}))
    with pytest.raises(mrpack.PackError), zipfile.ZipFile(p) as zf:
        mrpack._extract_overrides(zf, tmp_path / "game")
    assert not (tmp_path / "escape.txt").exists()


def test_failed_install_leaves_nothing_behind(app, fake, tmp_path):
    index = {"formatVersion": 1, "game": "minecraft", "name": "Broken", "versionId": "1",
             "dependencies": {"minecraft": "26.3", "fabric-loader": "0.17.2"},
             "files": [{"path": "mods/missing.jar", "hashes": {"sha1": "0" * 40},
                        "downloads": ["https://cdn.modrinth.com/data/x/missing.jar"]},
                       {"path": "mods/server.jar", "env": {"client": "unsupported"}, "hashes": {"sha1": "1"},
                        "downloads": ["https://cdn.modrinth.com/s.jar"]}]}
    p = tmp_path / "broken.mrpack"
    p.write_bytes(_pack(index))
    assert mrpack.read_index(p).skipped_server_only == 1
    parent = tmp_path / "prism"
    parent.mkdir()
    with pytest.raises(KeyError):  # the fake has no such file
        mrpack.install(app.manager, app.client, p, "prism", parent)
    assert list(parent.iterdir()) == [] and app.manager.list() == []


def test_log_file(app, tmp_path):
    from craftd import log
    path = log.setup(app.home)
    log.log.info("hello from the test")
    for h in log.log.handlers:
        h.flush()
    assert path.name == "craftd.log" and "hello from the test" in path.read_text()
