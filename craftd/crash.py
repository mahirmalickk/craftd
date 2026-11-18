"""Crash helper: read the newest crash report or log and explain it in plain English."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from .instances import Instance

# Things in latest.log that mean the game failed to start (Fabric's "Incompatible mods" screen
# and NeoForge's loading errors don't always write a crash report).
LOG_FAILURE_MARKERS = ("FormattedException", "Incompatible mods found", "Some of your mods are incompatible",
                       "Game crashed!", "ModLoadingException", "Mod loading has failed",
                       "Exception in thread \"main\"", "Missing or unsupported mandatory dependencies")
CORE_IDS = {"minecraft", "neoforge", "forge", "fml", "fabricloader", "java", "mixin", "mixinextras"}


@dataclass
class Diagnosis:
    title: str
    explanation: str
    suggestions: list[str] = field(default_factory=list)
    mods: list[str] = field(default_factory=list)  # mod ids involved
    source: Path | None = None
    when: float = 0.0
    excerpt: str = ""  # the key line(s) from the report
    resolved: bool = False  # the game has started fine since this crash

    @property
    def when_text(self) -> str:
        return time.strftime("%b %d, %I:%M %p", time.localtime(self.when)) if self.when else ""


def newest_crash_file(inst: Instance) -> Path | None:
    """Newest crash report, or latest.log if it's newer and shows a failed start."""
    candidates = []
    reports = inst.game_dir / "crash-reports"
    if reports.is_dir():
        candidates += [p for p in reports.glob("*.txt") if p.is_file()]
    log = inst.game_dir / "logs" / "latest.log"
    if log.is_file():
        try:
            text = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        if any(m in text for m in LOG_FAILURE_MARKERS):
            candidates.append(log)
    return max(candidates, key=lambda p: p.stat().st_mtime) if candidates else None


def _clean(text: str) -> str:
    return re.sub(r"§.", "", text)  # Minecraft formatting codes


def _names(text: str) -> dict[str, tuple[str, str]]:
    """mod id -> (display name, version), from the mod lists in crash reports and logs."""
    out: dict[str, tuple[str, str]] = {}
    for m in re.finditer(r"^\s+([a-z0-9_.\-]+): (.+?) v(\S+)\s*$", text, re.M):  # crash report "Mods:" section
        out.setdefault(m.group(1), (m.group(2), m.group(3)))
    for m in re.finditer(r"^\s+(.+?) (\S+) \(([a-z0-9_.\-]+)\)\s*$", text, re.M):  # NeoForge "Mod List:"
        out.setdefault(m.group(3), (m.group(1), m.group(2)))
    for m in re.finditer(r"^\s+- ([a-z0-9_.\-]+) (\S+)\s*$", text, re.M):  # Fabric "Loading N mods:"
        out.setdefault(m.group(1), (m.group(1), m.group(2)))
    return out


def _loader_info(text: str, inst: Instance) -> tuple[str, str | None]:
    """Loader and version at the time of the crash (it may have changed since)."""
    m = re.search(r"NeoForge \(net\.neoforged\) (\S+)|--fml\.neoForgeVersion (\S+)|^\s*NeoForge: (\S+)\s*$", text, re.M)
    if m:
        return "NeoForge", m.group(1) or m.group(2) or m.group(3)
    m = re.search(r"^\s*neoforge: NeoForge v(\S+)\s*$", text, re.M)
    if m:
        return "NeoForge", m.group(1)
    m = re.search(r"^\s*fabricloader: Fabric Loader (\S+)\s*$", text, re.M)
    if m:
        return "Fabric Loader", m.group(1)
    m = re.search(r"Fabric Loader \(net\.fabricmc\.fabric-loader\) (\S+)|Loading Minecraft \S+ with Fabric Loader (\S+)", text)
    if m:
        return "Fabric Loader", m.group(1) or m.group(2)
    return inst.loader_label, inst.loader_version


def diagnose(text: str, inst: Instance, source: Path | None = None, when: float = 0.0) -> Diagnosis:
    text = _clean(text)
    names = _names(text)

    def nm(mid: str) -> str:
        return names.get(mid, (mid, ""))[0]

    def ver(mid: str) -> str:
        return names.get(mid, ("", ""))[1]

    loader, loader_ver = _loader_info(text, inst)
    d = None

    # 1. Fabric: two mods that refuse to run together
    m = re.search(r"Mod '(?P<a>[^']+)' \((?P<aid>[^)]+)\) (?P<av>\S+) is incompatible with (?P<range>.+?) of mod "
                  r"'(?P<b>[^']+)' \((?P<bid>[^)]+)\), yet a conflicting version is present: (?P<bv>[^!\s]+)", text)
    if m:
        d = Diagnosis(
            title=f"{m['a']} and {m['b']} don't work together",
            explanation=f"{m['a']} {m['av']} refuses to run with {m['range']} of {m['b']}, and you have "
                        f"{m['b']} {m['bv']}.",
            suggestions=[f"Use the version of {m['a']} that {m['b']} {m['bv']} was made for, or a newer {m['b']}.",
                         f"Or remove {m['b']} for now (Mods tab → select it → Remove)."],
            mods=[m["aid"], m["bid"]], excerpt=m.group(0))

    # 2. Fabric: a required mod is missing or the wrong version
    if d is None:
        m = re.search(r"Mod '(?P<a>[^']+)' \((?P<aid>[^)]+)\) (?P<av>\S+) requires (?P<range>.+?) of (?:mod )?"
                      r"'?(?P<b>[^'(]+?)'? \((?P<bid>[^)]+)\), (?:which is missing|but only the wrong version is "
                      r"present: (?P<bv>[^!\s]+))", text)
        if m:
            missing = not m["bv"]
            d = Diagnosis(
                title=f"{m['a']} needs {m['b'].strip()}",
                explanation=(f"{m['a']} needs {m['range']} of {m['b'].strip()}, which isn't installed." if missing else
                             f"{m['a']} needs {m['range']} of {m['b'].strip()}, but {m['bv']} is installed."),
                suggestions=[f"Add {m['b'].strip()} from Modrinth (Mods tab → Add from Modrinth)." if missing else
                             f"Install a matching version of {m['b'].strip()}."],
                mods=[m["aid"], m["bid"]], excerpt=m.group(0))

    # 3. NeoForge/Forge: a mod needs a different version of something (incl. the loader itself)
    if d is None:
        m = re.search(r"Mod (?P<a>\S+) (?P<verb>requires|is incompatible with|discourages) (?P<b>\S+) (?P<range>.+?)\s+"
                      r"Currently, (?P=b) is (?P<have>[^\n]+)", text)
        if m:
            a, b, have = m["a"], m["b"], m["have"].strip()
            if m["verb"] == "requires" and have.lower().startswith("not installed"):
                d = Diagnosis(f"{nm(a)} needs {nm(b)}", f"{nm(a)} needs {nm(b)} {m['range']}, which isn't installed.",
                              [f"Add {nm(b)} from Modrinth (Mods tab → Add from Modrinth)."], [a, b], excerpt=m.group(0))
            elif m["verb"] == "requires":
                label = "NeoForge" if b == "neoforge" else nm(b)
                fix = ([f"Change the NeoForge version in Prism (Edit → Version) to {m['range']}.",
                        f"Or install a different build of {nm(a)} that supports NeoForge {have}."]
                       if b in ("neoforge", "forge", "minecraft") else [f"Install {nm(b)} {m['range']}."])
                d = Diagnosis(f"{nm(a)} needs a different {label} version",
                              f"{nm(a)} needs {label} {m['range']}, but this instance has {have}.", fix, [a, b],
                              excerpt=m.group(0))
            else:
                d = Diagnosis(f"{nm(a)} doesn't work with {nm(b)}",
                              f"{nm(a)} {m['verb']} {nm(b)} {m['range']}, and you have {have}.",
                              ["Remove one of them, or use versions that work together."], [a, b], excerpt=m.group(0))

    # 4. Mixin hook failed: the mod was built for a different Minecraft/loader build
    if d is None:
        m = (re.search(r"Mixin apply for mod (?P<mod>\S+) failed (?P<cfg>\S+) .*?-> (?P<target>[\w.$]+)", text) or
             re.search(r"Mixin \[(?P<cfg>[^\]]+?) from mod (?P<mod>[^\]]+)\] from phase \[\w+\] in config \[[^\]]+\] "
                       r"FAILED", text))
        if m:
            mod = m["mod"]
            target = m.groupdict().get("target") or ""
            if not target:  # crash reports name the class in the injection error instead
                t = re.search(r"targets matching .*? in ([\w/$]+)\.", text)
                target = t.group(1).replace("/", ".") if t else ""
            target = target.rsplit(".", 1)[-1]
            where = f"Minecraft's {target}" if target else "Minecraft"
            d = Diagnosis(
                title=f"{nm(mod)} doesn't fit this {loader} version",
                explanation=(f"{nm(mod)} {ver(mod)} tried to hook into {where} and couldn't find what it expected. "
                             f"That usually means this build of {nm(mod)} was made for a different "
                             f"{loader} version (you have {loader_ver or 'an unknown version'}) or Minecraft build."),
                suggestions=[f"Try a newer or beta build of {nm(mod)}: Mods tab → Add from Modrinth → click "
                             f"{nm(mod)} → pick a version.",
                             f"Or change the {loader} version in Prism (Edit → Version) to one this build of "
                             f"{nm(mod)} was made for. Its changelog on Modrinth usually says which.",
                             f"If another mod needs this exact {nm(mod)} version (like Iris needs a specific "
                             f"Sodium), you may have to remove that mod until it updates."],
                mods=[mod], excerpt=m.group(0)[:400])

    # 5. Out of memory / wrong Java
    if d is None and "java.lang.OutOfMemoryError" in text:
        d = Diagnosis("Minecraft ran out of memory",
                      "The game used up all the memory it was allowed to have.",
                      ["In Prism: Edit → Settings → Java → raise Maximum memory (e.g. to 6144 MiB)."],
                      excerpt="java.lang.OutOfMemoryError")
    if d is None:
        m = re.search(r"UnsupportedClassVersionError|compiled by a more recent version of the Java Runtime", text)
        if m:
            d = Diagnosis("Wrong Java version", "A mod was built for a newer Java than the one this instance uses.",
                          ["In Prism: Edit → Settings → Java → Auto-detect, and pick the newest Java."],
                          excerpt=m.group(0))

    # 6. A class from another mod is missing
    if d is None:
        m = re.search(r"(?:Caused by: |^)java\.lang\.(?:NoClassDefFoundError|ClassNotFoundException): (?P<cls>[\w./$]+)"
                      r"(?P<rest>(?:\n\s+at .*){0,40})", text, re.M)
        if m:
            frame = re.search(r"TRANSFORMER/([a-z0-9_.\-]+)@", m["rest"])
            mod = frame.group(1) if frame and frame.group(1) not in CORE_IDS else None
            who = nm(mod) if mod else "A mod"
            d = Diagnosis(f"{who} is missing something it needs",
                          f"{who} tried to use {m['cls'].replace('/', '.')}, which isn't there. Usually a required "
                          f"library mod is missing or is the wrong version.",
                          [f"Check {who}'s Modrinth page for required mods and install them.",
                           f"Or update {who} to the newest build for this version."],
                          [mod] if mod else [], excerpt=m.group(0).split("\n")[0])

    # 7. Fallbacks: the crash report's own hints
    if d is None:
        desc = re.search(r"^Description: (.+)$", text, re.M)
        suspects = re.findall(r"Suspected Mods?: ([^\n]+)", text)
        first_exc = re.search(r"^(?:Caused by: )?([\w.$]+(?:Exception|Error)[^\n]*)", text, re.M)
        frame = next((f for f in re.findall(r"TRANSFORMER/([a-z0-9_.\-]+)@", text) if f not in CORE_IDS), None)
        mods = [frame] if frame else []
        if suspects and suspects[0].strip().lower() not in ("none", "unknown"):
            who = suspects[0].strip()
        elif frame:
            who = nm(frame)
        else:
            who = None
        d = Diagnosis(
            title=f"Crash while {desc.group(1).strip().lower()}" if desc else "The game crashed",
            explanation=(f"The crash happened inside {who}." if who else
                         "Craftd couldn't match this crash to a known cause.")
                        + (f" Error: {first_exc.group(1)[:200]}" if first_exc else ""),
            suggestions=([f"Try updating {who}, or remove it to see if the game starts."] if who else []) +
                        ["Open the full report below and search the error online, or send it for help."],
            mods=mods, excerpt=first_exc.group(1)[:300] if first_exc else "")

    d.source, d.when = source, when
    return d


def latest_diagnosis(inst: Instance) -> Diagnosis | None:
    path = newest_crash_file(inst)
    if not path:
        return None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    d = diagnose(text, inst, path, path.stat().st_mtime)
    log = inst.game_dir / "logs" / "latest.log"
    if path != log and log.is_file() and log.stat().st_mtime > d.when:
        try:
            later = log.read_text(encoding="utf-8", errors="replace")
        except OSError:
            later = ""
        d.resolved = not any(m in later for m in LOG_FAILURE_MARKERS)
    return d
