import os
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from craftd.crash import diagnose, latest_diagnosis, newest_crash_file  # noqa: E402

REAL_LOG = Path(__file__).parent / "data" / "neoforge_sodium_mixin_crash.log"


def make_inst(app, loader="neoforge"):
    inst = app.manager.create("T", "26.3", loader)
    inst.loader_version = "26.3.0.109"
    return inst


def test_real_sodium_neoforge_crash(app):
    d = diagnose(REAL_LOG.read_text(encoding="utf-8", errors="replace"), make_inst(app))
    assert d.title == "Sodium doesn't fit this NeoForge version"
    assert "Sodium 0.9.2+mc26.3" in d.explanation and "26.3.0.109" in d.explanation
    assert "LevelExtractor" in d.explanation and d.mods == ["sodium"]
    assert any("beta build of Sodium" in s for s in d.suggestions)


def test_fabric_incompatible_screen(app):
    text = ("net.fabricmc.loader.impl.FormattedException: Some of your mods are incompatible with the game or each other!\n"
            "\t - Mod 'Sodium' (sodium) 0.9.3-beta.5+mc26.3 is incompatible with version 1.12.0 or earlier of mod "
            "'Iris' (iris), yet a conflicting version is present: 1.11.7+mc26.3!")
    d = diagnose(text, make_inst(app, "fabric"))
    assert d.title == "Sodium and Iris don't work together" and d.mods == ["sodium", "iris"]


def test_fabric_missing_dependency(app):
    text = "Mod 'Mod Menu' (modmenu) 16.0 requires any version of 'Fabric API' (fabric-api), which is missing!"
    d = diagnose(text, make_inst(app, "fabric"))
    assert d.title == "Mod Menu needs Fabric API" and "isn't installed" in d.explanation


def test_neoforge_loader_too_old(app):
    text = "Mod §esodium§r requires §6neoforge§r §o26.3.0.65 or above§r\n§7Currently, §6neoforge§r§7 is §o26.3.0.30"
    d = diagnose(text, make_inst(app))
    assert d.title == "sodium needs a different NeoForge version"
    assert "Change the NeoForge version in Prism" in d.suggestions[0]


def test_memory_and_java(app):
    assert diagnose("java.lang.OutOfMemoryError: Java heap space", make_inst(app)).title == "Minecraft ran out of memory"
    j = diagnose("java.lang.UnsupportedClassVersionError: x has been compiled by a more recent version of the Java "
                 "Runtime", make_inst(app))
    assert j.title == "Wrong Java version"


def test_unknown_crash_points_at_the_mod_in_the_stack(app):
    text = ("Description: Ticking entity\njava.lang.NullPointerException: boom\n"
            "\tat TRANSFORMER/minecraft@26.3/net.minecraft.A.b(A.java:1)\n"
            "\tat TRANSFORMER/jade@26.3.5/snownee.jade.X.y(X.java:2)\n")
    d = diagnose(text, make_inst(app))
    assert d.title == "Crash while ticking entity" and "inside jade" in d.explanation and d.mods == ["jade"]


def test_newest_file_and_latest_log(app):
    inst = make_inst(app)
    assert newest_crash_file(inst) is None and latest_diagnosis(inst) is None
    reports = inst.game_dir / "crash-reports"
    reports.mkdir(parents=True)
    old = reports / "crash-old.txt"
    old.write_text(REAL_LOG.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    os.utime(old, (time.time() - 100, time.time() - 100))
    assert newest_crash_file(inst) == old
    logs = inst.game_dir / "logs"
    logs.mkdir()
    (logs / "latest.log").write_text("all good, game started\n")
    assert newest_crash_file(inst) == old  # a normal log isn't a crash
    (logs / "latest.log").write_text("Incompatible mods found!\n - Mod 'A' (a) 1 is incompatible with any version "
                                     "of mod 'B' (b), yet a conflicting version is present: 2!")
    assert newest_crash_file(inst) == logs / "latest.log"
    assert latest_diagnosis(inst).title == "A and B don't work together"


def crash_report_only():
    """Just the crash-reports/*.txt part of the real log (no Prism header)."""
    text = REAL_LOG.read_text(encoding="utf-8", errors="replace")
    return text[text.index("---- Minecraft Crash Report ----"):]


def test_crash_report_file_keeps_details(app):
    inst = make_inst(app)
    inst.loader_version = "26.3.0.110"  # the instance was updated after the crash
    d = diagnose(crash_report_only(), inst)
    assert "LevelExtractor" in d.explanation
    assert "you have 26.3.0.109" in d.explanation  # the version at the time of the crash


def test_old_crash_is_marked_resolved_after_a_clean_start(app):
    inst = make_inst(app)
    reports = inst.game_dir / "crash-reports"
    reports.mkdir(parents=True)
    crash = reports / "crash-1.txt"
    crash.write_text(crash_report_only(), encoding="utf-8")
    os.utime(crash, (time.time() - 600, time.time() - 600))
    assert not latest_diagnosis(inst).resolved  # no later launch yet
    logs = inst.game_dir / "logs"
    logs.mkdir()
    (logs / "latest.log").write_text("[Render thread/INFO]: Setting user: Player\n[Sound engine started]\n")
    d = latest_diagnosis(inst)
    assert d.resolved and d.title == "Sodium doesn't fit this NeoForge version"
