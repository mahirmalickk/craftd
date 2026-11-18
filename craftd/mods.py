"""Scanning an instance's mods folder and identifying each jar.

Every jar is fingerprinted (SHA-1) and looked up on Modrinth, so Craftd knows
which project a file belongs to no matter who installed it — Craftd, Prism, or
you dragging a file into the folder. Results are cached so rescans are instant.
"""

from __future__ import annotations

import hashlib
import json
import time
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .instances import Instance
from .modrinth import ModrinthClient, ModrinthError

MISS_RECHECK_SECONDS = 24 * 3600  # re-ask Modrinth about unknown jars once a day


@dataclass
class LocalMod:
    path: Path
    sha1: str
    enabled: bool
    title: str
    project_id: str | None = None
    version_id: str | None = None
    version_number: str | None = None
    mod_id: str | None = None  # id from the jar's own metadata (fabric.mod.json etc.)
    icon_url: str | None = None

    @property
    def filename(self) -> str:
        return self.path.name

    @property
    def key(self) -> str:
        """Stable identity for matching the same mod across instances."""
        if self.project_id:
            return self.project_id
        return f"local:{(self.mod_id or self.base_name).lower()}"

    @property
    def base_name(self) -> str:
        name = self.path.name
        return name[: -len(".disabled")] if name.endswith(".disabled") else name

    @property
    def on_modrinth(self) -> bool:
        return self.project_id is not None


def sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def read_jar_metadata(path: Path) -> dict:
    """Best-effort {id, name, version} from a mod jar, for mods not on Modrinth."""
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
            if "fabric.mod.json" in names:
                data = json.loads(zf.read("fabric.mod.json").decode("utf-8", "replace"), strict=False)
                return {"id": data.get("id"), "name": data.get("name"), "version": data.get("version")}
            if "quilt.mod.json" in names:
                data = json.loads(zf.read("quilt.mod.json").decode("utf-8", "replace"), strict=False)
                ql = data.get("quilt_loader", {})
                return {"id": ql.get("id"), "name": ql.get("metadata", {}).get("name"), "version": ql.get("version")}
            for toml_name in ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"):
                if toml_name in names:
                    data = tomllib.loads(zf.read(toml_name).decode("utf-8", "replace"))
                    mods = data.get("mods") or [{}]
                    m = mods[0]
                    return {"id": m.get("modId"), "name": m.get("displayName"), "version": m.get("version")}
    except (zipfile.BadZipFile, OSError, ValueError, KeyError, tomllib.TOMLDecodeError):
        pass
    return {}


def mod_files(mods_dir: Path) -> list[Path]:
    if not mods_dir.is_dir():
        return []
    return sorted(
        p for p in mods_dir.iterdir()
        if p.is_file() and (p.name.endswith(".jar") or p.name.endswith(".jar.disabled"))
    )


class HashCache:
    """sha1 -> Modrinth identity, and project_id -> title/icon, stored on disk."""

    def __init__(self, path: Path):
        self.path = path
        self.hashes: dict[str, dict] = {}
        self.projects: dict[str, dict] = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                self.hashes = data.get("hashes", {})
                self.projects = data.get("projects", {})
            except (OSError, json.JSONDecodeError):
                pass

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"hashes": self.hashes, "projects": self.projects}), encoding="utf-8")

    def needs_lookup(self, sha1: str) -> bool:
        entry = self.hashes.get(sha1)
        if entry is None:
            return True
        return entry.get("miss", False) and time.time() - entry.get("checked", 0) > MISS_RECHECK_SECONDS

    def remember_version(self, sha1: str, version: dict) -> None:
        self.hashes[sha1] = {
            "project_id": version["project_id"],
            "version_id": version["id"],
            "version_number": version.get("version_number"),
            "checked": time.time(),
        }

    def remember_miss(self, sha1: str) -> None:
        self.hashes[sha1] = {"miss": True, "checked": time.time()}

    def remember_project(self, project: dict) -> None:
        self.projects[project["id"]] = {
            "title": project.get("title"),
            "slug": project.get("slug"),
            "icon_url": project.get("icon_url"),
            "loaders": project.get("loaders"),
        }


class ModScanner:
    def __init__(self, client: ModrinthClient, cache: HashCache):
        self.client = client
        self.cache = cache
        self.offline = False  # set when the last lookup couldn't reach Modrinth

    def scan(self, inst: Instance) -> list[LocalMod]:
        return self.scan_many([inst])[inst.id]

    def scan_many(self, instances: list[Instance]) -> dict[str, list[LocalMod]]:
        files: dict[str, list[tuple[Path, str]]] = {}
        for inst in instances:
            files[inst.id] = [(p, sha1_file(p)) for p in mod_files(inst.mods_dir)]

        all_hashes = {h for entries in files.values() for _, h in entries}
        self._identify(all_hashes)

        result: dict[str, list[LocalMod]] = {}
        for inst in instances:
            mods = []
            for path, sha1 in files[inst.id]:
                entry = self.cache.hashes.get(sha1, {})
                project_id = entry.get("project_id")
                project = self.cache.projects.get(project_id, {}) if project_id else {}
                meta = read_jar_metadata(path)
                title = project.get("title") or meta.get("name") or path.name.split(".jar")[0]
                mods.append(
                    LocalMod(
                        path=path, sha1=sha1, enabled=not path.name.endswith(".disabled"),
                        title=title, project_id=project_id, version_id=entry.get("version_id"),
                        version_number=entry.get("version_number") or meta.get("version"),
                        mod_id=meta.get("id"), icon_url=project.get("icon_url"),
                    )
                )
            result[inst.id] = sorted(mods, key=lambda m: m.title.lower())
        return result

    def _identify(self, hashes: set[str]) -> None:
        unknown = [h for h in hashes if self.cache.needs_lookup(h)]
        self.offline = False
        try:
            if unknown:
                found = self.client.versions_from_hashes(unknown)
                for h in unknown:
                    if h in found:
                        self.cache.remember_version(h, found[h])
                    else:
                        self.cache.remember_miss(h)
            needed = {
                e["project_id"] for h in hashes
                if (e := self.cache.hashes.get(h)) and e.get("project_id") and e["project_id"] not in self.cache.projects
            }
            if needed:
                for project in self.client.projects(sorted(needed)):
                    self.cache.remember_project(project)
        except ModrinthError:
            self.offline = True  # still return what the jars themselves tell us
        self.cache.save()
