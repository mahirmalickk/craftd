from craftd import extras


def fill_source(inst):
    gd = inst.game_dir
    (gd / "resourcepacks").mkdir(parents=True)
    (gd / "resourcepacks" / "Faithful 32x.zip").write_bytes(b"pk" * 100)
    (gd / "resourcepacks" / "MyFolderPack").mkdir()
    (gd / "resourcepacks" / "MyFolderPack" / "pack.mcmeta").write_text("{}")
    (gd / "resourcepacks" / "notes.txt").write_text("not a pack")
    (gd / "shaderpacks").mkdir()
    (gd / "shaderpacks" / "ComplementaryReimagined.zip").write_bytes(b"sh" * 100)
    (gd / "config" / "sodium").mkdir(parents=True)
    (gd / "config" / "sodium-options.json").write_text('{"quality": "fancy"}')
    (gd / "config" / "sodium" / "extra.json").write_text("{}")
    (gd / "config" / "iris.properties").write_text("shaderPack=ComplementaryReimagined.zip")
    (gd / "options.txt").write_text("version:4000\nkey_key.jump:key.keyboard.space\n")
    (gd / "servers.dat").write_bytes(b"\x0a\x00")


def test_scan_finds_everything(app):
    src = app.manager.create("Old", "26.2", "fabric")
    fill_source(src)
    found = extras.scan(src)
    assert [p.name for p in found.resourcepacks] == ["Faithful 32x.zip", "MyFolderPack"]
    assert [p.name for p in found.shaderpacks] == ["ComplementaryReimagined.zip"]
    assert len(found.config_files) == 3 and found.options and found.servers


def test_fresh_instance_gets_everything(app):
    src = app.manager.create("Old", "26.2", "fabric")
    fill_source(src)
    tgt = app.manager.create("New", "26.3", "fabric")
    found = extras.scan(src)
    choice = extras.default_choice(found, tgt)
    assert choice.options and choice.servers and choice.config and len(choice.packs) == 3
    report = extras.apply(found, tgt, choice)
    gd = tgt.game_dir
    assert (gd / "resourcepacks" / "Faithful 32x.zip").read_bytes() == b"pk" * 100
    assert (gd / "resourcepacks" / "MyFolderPack" / "pack.mcmeta").exists()
    assert (gd / "shaderpacks" / "ComplementaryReimagined.zip").exists()
    assert (gd / "config" / "sodium" / "extra.json").exists()
    assert (gd / "options.txt").read_text().startswith("version:4000")
    assert report.config_copied == 3 and report.backups == []
    assert "game options & keybinds" in report.copied and "server list" in report.copied


def test_existing_settings_are_kept_unless_replacing_and_backed_up(app):
    src = app.manager.create("Old", "26.2", "fabric")
    fill_source(src)
    tgt = app.manager.create("New", "26.3", "fabric")
    gd = tgt.game_dir
    (gd / "config").mkdir(parents=True)
    (gd / "config" / "sodium-options.json").write_text('{"quality": "fast"}')
    (gd / "options.txt").write_text("version:4100\n")
    (gd / "resourcepacks").mkdir()
    (gd / "resourcepacks" / "Faithful 32x.zip").write_bytes(b"newer")

    found = extras.scan(src)
    choice = extras.default_choice(found, tgt)
    assert not choice.options  # target already has its own options
    # Faithful is already there, so it isn't ticked
    assert [x.name for x in choice.packs] == ["MyFolderPack", "ComplementaryReimagined.zip"]
    assert {x.name for x in extras.packs_already_there(found, tgt)} == {"Faithful 32x.zip"}
    assert len(extras.new_config_files(found, tgt)) == len(found.config_files) - 1
    choice.packs = list(found.packs)  # tick it anyway: packs are still never overwritten
    choice.options = True
    report = extras.apply(found, tgt, choice)
    assert (gd / "config" / "sodium-options.json").read_text() == '{"quality": "fast"}'  # kept
    assert report.config_copied == 2 and report.config_skipped == 1
    assert (gd / "options.txt").read_text() == "version:4100\n"
    assert (gd / "resourcepacks" / "Faithful 32x.zip").read_bytes() == b"newer"  # packs never overwritten
    assert "Faithful 32x.zip" in report.skipped and "game options & keybinds" in report.skipped

    choice.replace = True
    report = extras.apply(found, tgt, choice)
    assert (gd / "config" / "sodium-options.json").read_text() == '{"quality": "fancy"}'
    assert (gd / "options.txt").read_text().startswith("version:4000")
    backups = sorted(p.name for p in gd.iterdir() if "craftd-backup" in p.name)
    assert len(backups) == 3 and backups[0].startswith("config.craftd-backup-")  # config, options, servers
    old_cfg = next(p for p in gd.iterdir() if p.name.startswith("config.craftd-backup-"))
    assert (old_cfg / "sodium-options.json").read_text() == '{"quality": "fast"}'


def test_options_from_newer_minecraft_not_copied_by_default(app):
    src = app.manager.create("Newer", "26.3", "fabric")
    fill_source(src)
    tgt = app.manager.create("Older", "26.2", "fabric")
    assert not extras.default_choice(extras.scan(src), tgt).options


def test_human_size():
    assert extras.human_size(512) == "512 B" and extras.human_size(2048) == "2.0 KB"
    assert extras.human_size(5 * 1024 ** 3) == "5.0 GB"


def test_settings_change_what_is_ticked_by_default(app):
    from craftd.settings import Settings
    src = app.manager.create("Old", "26.2", "fabric")
    fill_source(src)
    tgt = app.manager.create("New", "26.3", "fabric")
    found = extras.scan(src)
    on = extras.default_choice(found, tgt, Settings())
    assert on.packs and on.config and on.options and on.servers
    off = extras.default_choice(found, tgt, Settings(carry_packs=False, carry_config=False,
                                                     carry_options_servers=False))
    assert not (off.packs or off.config or off.options or off.servers)

    extras.apply(found, tgt, on)  # after carrying everything, nothing new is left to tick
    again = extras.default_choice(found, tgt, Settings())
    assert not (again.packs or again.config or again.options or again.servers)
