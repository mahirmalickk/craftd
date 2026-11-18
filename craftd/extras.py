"""Carry Over for everything besides mods: resource packs, shader packs, mod settings,
game options/keybinds and the server list.

Nothing the target already has is replaced unless asked, and anything replaced is backed
up first (config.craftd-backup-<time>, options.txt.craftd-backup-<time>, ...).
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .instances import Instance
from .versions import numeric_key

Progress = Callable[[str], None]

PACK_FOLDERS = {"resourcepacks": "Resource packs", "shaderpacks": "Shader packs"}


def _noop(_: str) -> None:
    pass


def _packs(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted((p for p in folder.iterdir() if (p.is_file() and p.suffix.lower() == ".zip") or p.is_dir()),
                  key=lambda p: p.name.lower())


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


@dataclass
class ExtrasScan:
    source: Instance
    resourcepacks: list[Path] = field(default_factory=list)
    shaderpacks: list[Path] = field(default_factory=list)
    config_files: list[Path] = field(default_factory=list)  # relative to source config/
    options: bool = False
    servers: bool = False

    @property
    def packs(self) -> list[Path]:
        return self.resourcepacks + self.shaderpacks

    @property
    def empty(self) -> bool:
        return not (self.packs or self.config_files or self.options or self.servers)


def scan(source: Instance) -> ExtrasScan:
    gd = source.game_dir
    cfg = gd / "config"
    return ExtrasScan(
        source=source,
        resourcepacks=_packs(gd / "resourcepacks"),
        shaderpacks=_packs(gd / "shaderpacks"),
        config_files=sorted(p.relative_to(cfg) for p in cfg.rglob("*") if p.is_file()) if cfg.is_dir() else [],
        options=(gd / "options.txt").is_file(),
        servers=(gd / "servers.dat").is_file(),
    )


@dataclass
class ExtrasChoice:
    packs: list[Path] = field(default_factory=list)  # chosen resource/shader packs (source paths)
    config: bool = True
    options: bool = False
    servers: bool = False
    replace: bool = False  # overwrite what the target already has (after backing it up)


def packs_already_there(found: ExtrasScan, target: Instance) -> set[Path]:
    """Source packs the target already has (same folder and name), e.g. after an earlier carry over."""
    return {p for p in found.packs if (target.game_dir / p.parent.name / p.name).exists()}


def new_config_files(found: ExtrasScan, target: Instance) -> list[Path]:
    """Config files (relative paths) the target doesn't have yet."""
    cfg = target.game_dir / "config"
    return [rel for rel in found.config_files if not (cfg / rel).exists()]


def default_choice(found: ExtrasScan, target: Instance, settings=None) -> ExtrasChoice:
    """What's ticked when the Carry Over tab opens.

    Packs and settings the target doesn't have yet are on (Settings → Carry Over can turn them off).
    Options/servers only if the target has none yet, and options from a *newer* Minecraft never
    (older versions can't read them)."""
    packs_on = getattr(settings, "carry_packs", True)
    config_on = getattr(settings, "carry_config", True)
    opt_on = getattr(settings, "carry_options_servers", True)
    tgt = target.game_dir
    source_newer = numeric_key(found.source.game_version) > numeric_key(target.game_version)
    there = packs_already_there(found, target)
    return ExtrasChoice(
        packs=[p for p in found.packs if p not in there] if packs_on else [],
        config=config_on and bool(new_config_files(found, target)),
        options=opt_on and found.options and not (tgt / "options.txt").exists() and not source_newer,
        servers=opt_on and found.servers and not (tgt / "servers.dat").exists(),
    )


@dataclass
class ExtrasReport:
    copied: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    backups: list[str] = field(default_factory=list)
    config_copied: int = 0
    config_skipped: int = 0

    def summary(self) -> str:
        parts = []
        if self.copied:
            parts.append("Copied: " + ", ".join(self.copied))
        if self.config_copied or self.config_skipped:
            line = f"Mod settings: {self.config_copied} file(s) copied"
            if self.config_skipped:
                line += f", {self.config_skipped} kept (the new instance already had them)"
            parts.append(line)
        if self.skipped:
            parts.append("Already there, left alone: " + ", ".join(self.skipped))
        if self.backups:
            parts.append("Backed up before replacing: " + ", ".join(self.backups))
        return "\n".join(parts)


def _stamp() -> str:
    return time.strftime("%Y%m%d-%H%M%S")


def _backup(path: Path, report: ExtrasReport, stamp: str) -> None:
    dest = path.with_name(f"{path.name}.craftd-backup-{stamp}")
    if path.is_dir():
        shutil.copytree(path, dest)
    else:
        shutil.copy2(path, dest)
    report.backups.append(dest.name)


def apply(found: ExtrasScan, target: Instance, choice: ExtrasChoice, progress: Progress = _noop) -> ExtrasReport:
    report = ExtrasReport()
    src, tgt = found.source.game_dir, target.game_dir
    stamp = _stamp()

    # resource & shader packs: copied as-is; existing packs are never touched
    for pack in choice.packs:
        dest = tgt / pack.parent.name / pack.name
        if dest.exists():
            report.skipped.append(pack.name)
            continue
        progress(f"Copying {pack.name}…")
        dest.parent.mkdir(parents=True, exist_ok=True)
        if pack.is_dir():
            shutil.copytree(pack, dest)
        else:
            shutil.copy2(pack, dest)
        report.copied.append(pack.name)

    # mod settings: fill in what's missing, or replace (after a backup of the whole folder)
    if choice.config and found.config_files:
        progress("Copying mod settings…")
        cfg_src, cfg_dst = src / "config", tgt / "config"
        if choice.replace and cfg_dst.is_dir() and any(cfg_dst.iterdir()):
            _backup(cfg_dst, report, stamp)
        for rel in found.config_files:
            dest = cfg_dst / rel
            if dest.exists() and not choice.replace:
                report.config_skipped += 1
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cfg_src / rel, dest)
            report.config_copied += 1

    # single files: options.txt (graphics, keybinds, selected packs) and servers.dat
    for wanted, name, label in ((choice.options, "options.txt", "game options & keybinds"),
                                (choice.servers, "servers.dat", "server list")):
        if not wanted or not (src / name).is_file():
            continue
        dest = tgt / name
        if dest.exists():
            if not choice.replace:
                report.skipped.append(label)
                continue
            _backup(dest, report, stamp)
        tgt.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / name, dest)
        report.copied.append(label)
    return report
