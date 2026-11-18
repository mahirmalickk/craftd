import json

from fake_modrinth import FakeModrinth
from jars import fabric_jar, neoforge_jar, write

from craftd import compat
from craftd.core import Craftd


def issues_for(folder, game="26.3", loader="fabric", loader_version="0.17.2", label="Fabric"):
    return compat.check_files(sorted(folder.glob("*.jar")), game, loader, loader_version, label)


def test_sodium_breaks_old_iris_is_caught(tmp_path):
    write(tmp_path, "sodium.jar", fabric_jar("sodium", "0.9.3-beta.5+mc26.3", breaks={"iris": "<=1.12.0"}))
    write(tmp_path, "iris.jar", fabric_jar("iris", "1.11.7+mc26.3", depends={"sodium": "0.9.2"}))
    issues = issues_for(tmp_path)
    msgs = {(i.mod, i.message) for i in issues}
    assert ("Sodium", "Doesn't work with Iris 1.11.7+mc26.3 (it breaks with 1.12.0 or older).") in msgs
    assert ("Iris", "Needs Sodium exactly 0.9.2, but 0.9.3-beta.5+mc26.3 is installed.") in msgs
    assert all(i.severity == "error" for i in issues)


def test_loader_and_minecraft_ranges(tmp_path):
    write(tmp_path, "sodium.jar", neoforge_jar("sodium", "0.9.3", deps=[("neoforge", "required", "[26.3.0.65,)"),
                                                                       ("minecraft", "required", "[26.3,26.4)")]))
    old = issues_for(tmp_path, loader="neoforge", loader_version="26.3.0.30", label="NeoForge")
    assert [i.message for i in old] == ["Needs NeoForge 26.3.0.65 or newer, but this instance has NeoForge 26.3.0.30."]
    assert "Prism" in old[0].fix
    assert issues_for(tmp_path, loader="neoforge", loader_version="26.3.0.110", label="NeoForge") == []
    wrong_mc = issues_for(tmp_path, game="26.2", loader="neoforge", loader_version="26.3.0.110", label="NeoForge")
    assert wrong_mc[0].message.startswith("Needs Minecraft 26.3 or newer and older than 26.4")
    # unknown loader version: nothing to compare against, so no false alarm
    assert issues_for(tmp_path, loader="neoforge", loader_version=None, label="NeoForge") == []


def test_missing_dependency_and_jar_in_jar(tmp_path):
    lib = fabric_jar("yumi_mc_core", "1.1.3")
    write(tmp_path, "lights.jar", fabric_jar("lambdynlights", "4.13", depends={"yumi_mc_core": "*", "spruceui": ">=12"},
                                             nested=[("yumi", lib)]))
    msgs = [i.message for i in issues_for(tmp_path)]
    assert msgs == ["Needs “spruceui”, which isn't installed."]  # yumi_mc_core is bundled inside, so it counts


def test_fabric_only_mod_in_neoforge_instance(tmp_path):
    write(tmp_path, "modmenu.jar", fabric_jar("modmenu", "16.0", depends={"fabricloader": ">=0.16"}))
    msgs = [i.message for i in issues_for(tmp_path, loader="neoforge", loader_version="26.3.0.110", label="NeoForge")]
    assert msgs == ["This is a Fabric Loader mod, but this instance uses NeoForge."]


def test_multi_loader_jar_uses_the_right_metadata(tmp_path):
    fabric_meta = {"schemaVersion": 1, "id": "zoomify", "version": "2.17", "depends": {"fabricloader": ">=99"}}
    write(tmp_path, "zoomify.jar", neoforge_jar("zoomify", "2.17", extra_fabric=fabric_meta))
    assert issues_for(tmp_path, loader="neoforge", loader_version="26.3.0.110", label="NeoForge") == []
    assert issues_for(tmp_path, loader="fabric")[0].message.startswith("Needs Fabric 99 or newer")


def test_prism_loader_version_is_read(app, tmp_path):
    prism = tmp_path / "PrismLauncher" / "instances" / "Neo"
    (prism / "minecraft" / "mods").mkdir(parents=True)
    (prism / "mmc-pack.json").write_text(json.dumps({"components": [
        {"uid": "net.minecraft", "version": "26.3"}, {"uid": "net.neoforged", "version": "26.3.0.110"}]}))
    inst = app.manager.link_prism(prism)
    assert inst.loader_version == "26.3.0.110" and inst.loader_text == "NeoForge 26.3.0.110"


def test_installer_picks_a_build_that_fits_the_loader(tmp_path):
    f = FakeModrinth()
    # Newest release says it needs NeoForge 26.3.0.65+; an older one fits 26.3.0.30
    f.add_version("sodium", "Sodium", "0.9.1", ["26.3"], ["neoforge"],
                  content=neoforge_jar("sodium", "0.9.1", deps=[("neoforge", "required", "[26.3.0.0,26.3.0.65)")]))
    f.add_version("sodium", "Sodium", "0.9.3", ["26.3"], ["neoforge"],
                  content=neoforge_jar("sodium", "0.9.3", deps=[("neoforge", "required", "[26.3.0.65,)")]))
    app = Craftd(home=tmp_path / "home", client=f)
    prism = tmp_path / "instances" / "Neo"
    (prism / "minecraft" / "mods").mkdir(parents=True)
    (prism / "mmc-pack.json").write_text(json.dumps({"components": [
        {"uid": "net.minecraft", "version": "26.3"}, {"uid": "net.neoforged", "version": "26.3.0.30"}]}))
    inst = app.manager.link_prism(prism)
    report = app.installer.install_projects(inst, ["sodium"])
    assert [p.name for p in inst.mods_dir.iterdir()] == ["sodium-0.9.1.jar"]
    assert report.swapped and "0.9.1 instead of 0.9.3" in report.swapped[0]
    assert app.installer.check_instance(inst) == []
    assert not (app.home / "cache" / "fit-check").exists()  # scratch folder cleaned up


def test_two_loader_jar_ignores_the_other_loaders_bundled_pieces(tmp_path):
    """WorldEdit 7.4.6 ships Fabric API pieces in META-INF/jars/ that NeoForge never loads."""
    fabric_piece = fabric_jar("fabric-lifecycle-events-v1", "2.5", depends={"fabricloader": ">=0.16"})
    neo_piece = neoforge_jar("worldeditcui_protocol", "4.0.3", deps=[("neoforge", "required", "[26.3,)")])
    fabric_side = {"schemaVersion": 1, "id": "worldedit", "version": "7.4.6",
                   "depends": {"fabricloader": ">=0.16", "fabric-lifecycle-events-v1": "*"}}
    write(tmp_path, "worldedit-mod-7.4.6.jar",
          neoforge_jar("worldedit", "7.4.6", deps=[("worldeditcui_protocol", "required", "*")], extra_fabric=fabric_side,
                       fabric_nested=[("fabric-lifecycle", fabric_piece)], neo_nested=[("cui", neo_piece)]))
    assert issues_for(tmp_path, loader="neoforge", loader_version="26.3.0.110", label="NeoForge") == []
    assert issues_for(tmp_path, loader="fabric", loader_version="0.17.2") == []
    metas = compat.read_mods(tmp_path / "worldedit-mod-7.4.6.jar", "neoforge")
    assert {m.mod_id for m in metas} == {"worldedit", "worldeditcui_protocol"}
    metas = compat.read_mods(tmp_path / "worldedit-mod-7.4.6.jar", "fabric")
    assert {m.mod_id for m in metas} == {"worldedit", "fabric-lifecycle-events-v1"}


def test_neoforge_reads_its_jarjar_list_even_when_it_points_into_meta_inf_jars(tmp_path):
    """LambDynamicLights 4.13 keeps its NeoForge helpers in META-INF/jars/ and lists them in jarjar/metadata.json."""
    api = neoforge_jar("lambdynlights_api", "4.13.0")
    spruce = neoforge_jar("spruceui", "12.0.0")
    yumi = neoforge_jar("yumi_mc_core", "1.1.3")
    fabric_only = fabric_jar("fabric-api-base", "1.0", depends={"fabricloader": "*"})
    write(tmp_path, "lambdynamiclights-4.13.0+26.3.jar", neoforge_jar(
        "lambdynlights", "4.13.0", deps=[("lambdynlights_api", "required", "*"), ("spruceui", "required", "*"),
                                         ("yumi_mc_core", "required", "*")],
        fabric_nested=[("lambdynamiclights-api", api), ("spruceui", spruce), ("yumi", yumi), ("fapi", fabric_only)],
        jarjar_list=["META-INF/jars/lambdynamiclights-api.jar", "META-INF/jars/spruceui.jar", "META-INF/jars/yumi.jar"]))
    assert issues_for(tmp_path, loader="neoforge", loader_version="26.3.0.110", label="NeoForge") == []
    ids = {m.mod_id for m in compat.read_mods(tmp_path / "lambdynamiclights-4.13.0+26.3.jar", "neoforge")}
    assert ids == {"lambdynlights", "lambdynlights_api", "spruceui", "yumi_mc_core"}  # not the Fabric-only piece


def test_last_successful_start_is_a_safety_net(app, tmp_path):
    inst = app.manager.create("Neo", "26.3", "neoforge")
    write(inst.mods_dir, "odd.jar", neoforge_jar("oddmod", "1.0", deps=[("hidden_helper", "required", "*")]))
    assert [i.message for i in app.installer.check_instance(inst)] == ["Needs “hidden_helper”, which isn't installed."]
    logs = inst.game_dir / "logs"
    logs.mkdir()
    (logs / "latest.log").write_text("     Mod List:\n\t\tName Version (Mod Id)\n\t\tOdd Mod 1.0 (oddmod)\n"
                                     "\t\tHidden Helper 2.0 (hidden_helper)\n[Render thread/INFO]: Setting user: Player\n")
    assert app.installer.check_instance(inst) == []
    (logs / "latest.log").write_text("Mod loading has failed\n\t\tHidden Helper 2.0 (hidden_helper)\n")
    assert len(app.installer.check_instance(inst)) == 1  # a failed start proves nothing
