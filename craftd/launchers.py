"""Prism Launcher and MultiMC instances on disk: where their game folder is, and making new ones.

Both launchers use the same instance format (instance.cfg + mmc-pack.json), so Craftd can create an
instance that either one opens and launches like its own. Until Craftd launches Minecraft itself (v2),
every new instance is made inside one of them.
"""

from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .paths import prism_instance_dirs

LAUNCHERS = {"prism": "Prism", "multimc": "MultiMC"}
_BAD_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def game_dir(instance_root: Path, launcher: str) -> Path:
    """The folder the launcher runs the game in (mods/, config/, saves/ live there).

    Copied from each launcher's own rule (MinecraftInstance::gameRoot), including for instances
    that were never launched: Prism uses "minecraft" unless only ".minecraft" exists; MultiMC uses
    ".minecraft" unless only "minecraft" exists."""
    mc, dot = instance_root / "minecraft", instance_root / ".minecraft"
    if launcher == "multimc":
        return mc if (mc.exists() and not dot.exists()) else dot
    return dot if (dot.exists() and not mc.exists()) else mc


def instances_dir(settings, launcher: str) -> Path | None:
    """Where this launcher keeps its instances, or None when Craftd doesn't know (MultiMC not set up)."""
    if launcher == "multimc":
        folder = Path(settings.multimc_folder).expanduser() if settings.multimc_folder else None
        return folder if folder and folder.is_dir() else None
    found = prism_instance_dirs(settings.prism_folder)
    return found[0] if found else None


def available(settings) -> dict[str, Path]:
    """{launcher: instances folder} for each launcher Craftd can create instances in right now."""
    return {key: folder for key in LAUNCHERS if (folder := instances_dir(settings, key))}


def folder_name(name: str, parent: Path) -> str:
    """A folder name for an instance, the way the launchers make one: unsafe characters replaced and a
    number added if it's taken."""
    base = _BAD_CHARS.sub("-", name).strip(" .") or "instance"
    candidate, n = base, 2
    while (parent / candidate).exists():
        candidate = f"{base} ({n})"
        n += 1
    return candidate


def write_cfg_name(cfg: Path, name: str) -> None:
    """Set name= in instance.cfg, keeping everything else (both launchers' formats)."""
    lines = cfg.read_text(encoding="utf-8", errors="replace").splitlines() if cfg.is_file() else []
    qt_format = any(line.strip() == "[General]" or line.startswith("ConfigVersion=") for line in lines)
    value = name
    if qt_format and (any(c in name for c in ',;"\\') or name != name.strip()):
        # Prism saves instance.cfg with Qt, which would read an unquoted "a, b" as a list
        value = '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
    out, done = [], False
    for line in lines:
        if line.startswith("name="):
            out.append(f"name={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"name={value}")
    cfg.write_text("\n".join(out) + "\n", encoding="utf-8")


def create_instance(parent: Path, name: str, game_version: str, loader: str, loader_version: str | None,
                    launcher: str) -> Path:
    """Make a new instance folder in a launcher's instances folder and return it.

    instance.cfg is written in the plain key=value format that MultiMC uses and Prism converts on first
    open. mmc-pack.json lists Minecraft and the loader; the launcher adds LWJGL and the rest itself
    the first time it opens the instance, exactly as for one made in the launcher."""
    from .loaders import build_components
    if not parent.is_dir():
        raise ValueError(f"{LAUNCHERS.get(launcher, launcher)}'s instances folder doesn't exist: {parent}")
    if loader != "vanilla" and not loader_version:
        raise ValueError(f"No {loader} version was picked")
    root = parent / folder_name(name, parent)
    root.mkdir()
    try:
        (root / "instance.cfg").write_text(f"InstanceType=OneSix\nname={name}\niconKey=default\n", encoding="utf-8")
        pack = {"formatVersion": 1,
                "components": build_components([], game_version, loader, loader_version if loader != "vanilla" else None)}
        (root / "mmc-pack.json").write_text(json.dumps(pack, indent=4), encoding="utf-8")
        # the folder this launcher will use, so mods put here before the first launch are found
        (root / (".minecraft" if launcher == "multimc" else "minecraft") / "mods").mkdir(parents=True)
    except OSError:
        shutil.rmtree(root, ignore_errors=True)
        raise
    return root


def copy_instance(root: Path, new_name: str) -> Path:
    """Copy a whole instance folder next to the original, with a new name."""
    dest = root.parent / folder_name(new_name, root.parent)
    shutil.copytree(root, dest, ignore=shutil.ignore_patterns("*.craftd-tmp"))
    write_cfg_name(dest / "instance.cfg", new_name)
    return dest
