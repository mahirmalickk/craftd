"""Worlds (the saves folder) for Carry Over.

A world can go to the same Minecraft version or a newer one: Minecraft upgrades it when it's opened.
Going to an older version can corrupt it, so Craftd never offers that. Worlds are always copied, never
moved, so the original stays playable in the old instance.

Each world's version comes from its level.dat (gzip-compressed NBT): Data.Version.Name, e.g. "1.21.1".
Worlds from before 1.9 have no version there; those are old enough that any newer instance is fine.
"""

from __future__ import annotations

import gzip
import shutil
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

Progress = Callable[[str], None]


def _noop(_: str) -> None:
    pass


# ---- a small NBT reader (only what level.dat needs) -------------------------------------------
class NBTError(ValueError):
    pass


class _Reader:
    def __init__(self, data: bytes):
        self.data, self.pos = data, 0

    def take(self, n: int) -> bytes:
        if self.pos + n > len(self.data):
            raise NBTError("level.dat ends too early")
        chunk = self.data[self.pos:self.pos + n]
        self.pos += n
        return chunk

    def unpack(self, fmt: str):
        size = struct.calcsize(fmt)
        return struct.unpack(fmt, self.take(size))[0]

    def string(self) -> str:
        return self.take(self.unpack(">H")).decode("utf-8", errors="replace")

    def payload(self, tag: int, depth: int = 0):
        if depth > 64:
            raise NBTError("level.dat is nested too deeply")
        if tag == 1:
            return self.unpack(">b")
        if tag == 2:
            return self.unpack(">h")
        if tag == 3:
            return self.unpack(">i")
        if tag == 4:
            return self.unpack(">q")
        if tag == 5:
            return self.unpack(">f")
        if tag == 6:
            return self.unpack(">d")
        if tag == 7:
            return self.take(self.unpack(">i"))
        if tag == 8:
            return self.string()
        if tag == 9:
            inner, count = self.unpack(">b"), self.unpack(">i")
            return [self.payload(inner, depth + 1) for _ in range(max(count, 0))]
        if tag == 10:
            out = {}
            while True:
                inner = self.unpack(">b")
                if inner == 0:
                    return out
                key = self.string()
                out[key] = self.payload(inner, depth + 1)
        if tag == 11:
            count = self.unpack(">i")
            return [self.unpack(">i") for _ in range(max(count, 0))]
        if tag == 12:
            count = self.unpack(">i")
            return [self.unpack(">q") for _ in range(max(count, 0))]
        raise NBTError(f"Unknown NBT tag {tag}")


def read_nbt(path: Path) -> dict:
    raw = path.read_bytes()
    data = gzip.decompress(raw) if raw[:2] == b"\x1f\x8b" else raw
    r = _Reader(data)
    tag = r.unpack(">b")
    if tag != 10:
        raise NBTError("level.dat doesn't start with a compound tag")
    r.string()  # the root's name (usually empty)
    return r.payload(10)


# ---- worlds ------------------------------------------------------------------------------------
@dataclass
class World:
    path: Path
    name: str  # the name shown in Minecraft (LevelName), else the folder name
    version: str | None  # Minecraft version it was last played in, e.g. "1.21.1"
    data_version: int | None
    size: int

    @property
    def folder(self) -> str:
        return self.path.name


def _folder_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def read_world(path: Path) -> World | None:
    level = path / "level.dat"
    if not level.is_file():
        return None
    name, version, data_version = path.name, None, None
    try:
        data = read_nbt(level).get("Data", {})
        name = data.get("LevelName") or name
        v = data.get("Version") or {}
        version = v.get("Name") or None
        data_version = data.get("DataVersion", v.get("Id"))
    except (OSError, EOFError, NBTError, gzip.BadGzipFile, struct.error, AttributeError):
        pass  # unreadable level.dat: still listed, with the version unknown
    return World(path, str(name), version, data_version if isinstance(data_version, int) else None,
                 _folder_size(path))


def scan(inst) -> list[World]:
    saves = inst.game_dir / "saves"
    if not saves.is_dir():
        return []
    worlds = [w for d in sorted(saves.iterdir()) if d.is_dir() and (w := read_world(d))]
    return sorted(worlds, key=lambda w: w.name.lower())


def why_not(world: World, target, order) -> str | None:
    """Why this world can't go to the target instance, or None when it can."""
    if (target.game_dir / "saves" / world.folder).exists():
        return "Already in this instance"
    if world.version and world.version != target.game_version and order.newer(world.version, target.game_version):
        return (f"Played in {world.version}, which is newer than {target.game_version}. "
                "Opening it in an older version can break it.")
    return None


@dataclass
class WorldsReport:
    copied: list[str]
    skipped: list[str]

    def summary(self) -> str:
        parts = []
        if self.copied:
            parts.append(f"Worlds copied: {', '.join(self.copied)}")
        if self.skipped:
            parts.append(f"Worlds skipped: {'; '.join(self.skipped)}")
        return "\n".join(parts)


def copy_worlds(worlds: list[World], target, order, progress: Progress = _noop) -> WorldsReport:
    """Copy worlds into the target's saves folder. The originals are never touched."""
    report = WorldsReport([], [])
    saves = target.game_dir / "saves"
    for w in worlds:
        reason = why_not(w, target, order)
        if reason:
            report.skipped.append(f"{w.name}: {reason}")
            continue
        progress(f"Copying the world {w.name}…")
        tmp = saves / (w.folder + ".craftd-copying")
        shutil.rmtree(tmp, ignore_errors=True)
        try:
            shutil.copytree(w.path, tmp, ignore=shutil.ignore_patterns("session.lock"))
            tmp.rename(saves / w.folder)  # only shows up in Minecraft once it's complete
        except OSError as exc:
            shutil.rmtree(tmp, ignore_errors=True)
            report.skipped.append(f"{w.name}: {exc}")
            continue
        report.copied.append(w.name)
    return report
