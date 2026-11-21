"""Modrinth modpacks (.mrpack): installing them, and Share Instance (making one from an instance).

An .mrpack is a zip with:
    modrinth.index.json   Minecraft + loader versions, and every mod as a download link with its hashes
    overrides/            files copied into the game folder as-is (config, resource packs, ...)
    client-overrides/     same, for the game only (server-overrides/ is for servers and is skipped)
Spec: https://support.modrinth.com/en/articles/8802351-modrinth-modpack-format-mrpack

Because mods are links rather than jars, a shared instance is usually only a few KB, and whoever
opens it gets exactly the same builds.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import time
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable
from urllib.parse import urlparse

from .instances import LOADER_LABELS, Instance

Progress = Callable[[str], None]
INDEX = "modrinth.index.json"
# The spec only allows downloads from these hosts, so a pack can't point a launcher anywhere else
ALLOWED_HOSTS = {"cdn.modrinth.com", "github.com", "raw.githubusercontent.com", "gitlab.com"}
PACK_LOADERS = {"fabric-loader": "fabric", "quilt-loader": "quilt", "neoforge": "neoforge", "forge": "forge"}
LOADER_KEYS = {v: k for k, v in PACK_LOADERS.items()}


def _noop(_: str) -> None:
    pass


class PackError(ValueError):
    """The file isn't a usable .mrpack."""


@dataclass
class PackFile:
    path: str
    url: str
    sha1: str
    size: int = 0


@dataclass
class PackIndex:
    name: str
    version: str
    summary: str
    game_version: str
    loader: str
    loader_version: str | None
    files: list[PackFile]
    skipped_server_only: int = 0

    @property
    def loader_text(self) -> str:
        label = LOADER_LABELS.get(self.loader, self.loader)
        return f"{label} {self.loader_version}" if self.loader_version else label


def safe_path(rel: str) -> PurePosixPath:
    """A path inside the instance. Anything that could escape it (.., C:\\, /etc) is refused."""
    rel = rel.replace("\\", "/")
    p = PurePosixPath(rel)
    if not rel or p.is_absolute() or ".." in p.parts or ":" in rel or rel.startswith("/"):
        raise PackError(f"The modpack has a file path that isn't allowed: {rel}")
    return p


def read_index(pack: Path) -> PackIndex:
    try:
        with zipfile.ZipFile(pack) as zf:
            data = json.loads(zf.read(INDEX).decode("utf-8"))
    except KeyError as exc:
        raise PackError(f"{pack.name} isn't a Modrinth modpack (no {INDEX} inside)") from exc
    except (zipfile.BadZipFile, json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        raise PackError(f"Couldn't read {pack.name}: {exc}") from exc
    if data.get("game") != "minecraft":
        raise PackError(f"{pack.name} isn't a Minecraft modpack")
    deps = data.get("dependencies") or {}
    if not deps.get("minecraft"):
        raise PackError(f"{pack.name} doesn't say which Minecraft version it's for")
    loader, loader_version = "vanilla", None
    for key, name in PACK_LOADERS.items():
        if deps.get(key):
            loader, loader_version = name, deps[key]
            break
    files, server_only = [], 0
    for f in data.get("files") or []:
        if (f.get("env") or {}).get("client") == "unsupported":
            server_only += 1
            continue
        path = str(safe_path(f.get("path", "")))
        urls = [u for u in f.get("downloads") or [] if urlparse(u).scheme == "https" and urlparse(u).hostname in ALLOWED_HOSTS]
        sha1 = (f.get("hashes") or {}).get("sha1")
        if not urls or not sha1:
            raise PackError(f"The modpack's download for {path} isn't from Modrinth or GitHub, so Craftd won't use it")
        files.append(PackFile(path, urls[0], sha1, int(f.get("fileSize") or 0)))
    return PackIndex(name=data.get("name") or pack.stem, version=str(data.get("versionId") or ""),
                     summary=data.get("summary") or "", game_version=deps["minecraft"], loader=loader,
                     loader_version=loader_version, files=files, skipped_server_only=server_only)


def _extract_overrides(zf: zipfile.ZipFile, game_dir: Path) -> int:
    count = 0
    for prefix in ("overrides/", "client-overrides/"):  # client-overrides win, so they go second
        for info in zf.infolist():
            if not info.filename.startswith(prefix) or info.is_dir():
                continue
            rel = info.filename[len(prefix):]
            if not rel:
                continue
            dest = game_dir.joinpath(*safe_path(rel).parts)
            dest.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(dest, "wb") as out:
                shutil.copyfileobj(src, out)
            count += 1
    return count


def install(manager, client, pack: Path, launcher: str, parent: Path, name: str | None = None,
            progress: Progress = _noop) -> Instance:
    """Create a Prism/MultiMC instance from an .mrpack: download every mod, then copy the overrides.
    If anything fails, the half-made instance is removed again."""
    index = read_index(pack)
    inst = manager.create_in_launcher(launcher, parent, name or index.name, index.game_version, index.loader,
                                      index.loader_version)
    try:
        total = len(index.files)
        for n, f in enumerate(index.files, 1):
            progress(f"Downloading {n}/{total}: {PurePosixPath(f.path).name}")
            client.download(f.url, inst.game_dir.joinpath(*PurePosixPath(f.path).parts), f.sha1)
        progress("Copying the modpack's settings and files…")
        with zipfile.ZipFile(pack) as zf:
            _extract_overrides(zf, inst.game_dir)
    except BaseException:
        manager.delete(inst)
        raise
    return manager.get(inst.id) or inst


# ---- Share Instance ------------------------------------------------------------------------------
@dataclass
class ShareOptions:
    config: bool = True
    resourcepacks: bool = True
    shaderpacks: bool = True
    options: bool = True  # options.txt: keybinds, video settings
    servers: bool = False  # servers.dat: the multiplayer list
    local_jars: bool = True  # jars that aren't on Modrinth go in as files
    worlds: list[str] = field(default_factory=list)  # world folder names


@dataclass
class ShareReport:
    path: Path
    linked: list[str] = field(default_factory=list)
    included_jars: list[str] = field(default_factory=list)
    left_out: list[str] = field(default_factory=list)
    files: int = 0

    def summary(self) -> str:
        size = self.path.stat().st_size if self.path.exists() else 0
        from .extras import human_size
        parts = [f"Saved {self.path.name} ({human_size(size)})",
                 f"{len(self.linked)} mod(s) as Modrinth links"]
        if self.included_jars:
            parts.append(f"{len(self.included_jars)} jar(s) not on Modrinth included as files: "
                         + ", ".join(self.included_jars))
        if self.files:
            parts.append(f"{self.files} other file(s): config, packs and settings")
        if self.left_out:
            parts.append("Left out: " + "; ".join(self.left_out))
        return "\n".join(parts)


def _hashes(path: Path) -> tuple[str, str, int]:
    s1, s512 = hashlib.sha1(), hashlib.sha512()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            s1.update(chunk)
            s512.update(chunk)
    return s1.hexdigest(), s512.hexdigest(), path.stat().st_size


def export(scanner, client, inst: Instance, dest: Path, options: ShareOptions, loader_version: str | None,
           progress: Progress = _noop) -> ShareReport:
    """Write an .mrpack of this instance that Craftd, Prism and the Modrinth App can open."""
    report = ShareReport(dest)
    progress("Looking up the mods on Modrinth…")
    mods = scanner.scan(inst)
    enabled = [m for m in mods if m.enabled]
    disabled = [m for m in mods if not m.enabled]
    if disabled:
        report.left_out.append(f"{len(disabled)} turned-off mod(s)")
    versions = client.versions_from_hashes([m.sha1 for m in enabled if m.on_modrinth]) if enabled else {}

    files, jar_overrides = [], []
    for m in enabled:
        version = versions.get(m.sha1) if m.on_modrinth else None
        url = next((f.get("url") for f in (version or {}).get("files", [])
                    if (f.get("hashes") or {}).get("sha1") == m.sha1), None)
        if url and urlparse(url).hostname in ALLOWED_HOSTS:
            sha1, sha512, size = _hashes(m.path)
            files.append({"path": f"mods/{m.base_name}", "hashes": {"sha1": sha1, "sha512": sha512},
                          "env": {"client": "required", "server": "required"}, "downloads": [url],
                          "fileSize": size})
            report.linked.append(m.title)
        elif options.local_jars:
            jar_overrides.append(m.path)
            report.included_jars.append(m.title)
        else:
            report.left_out.append(f"{m.title} (not on Modrinth)")

    deps = {"minecraft": inst.game_version}
    if inst.loader in LOADER_KEYS:
        if not loader_version:
            raise PackError(f"Craftd doesn't know which {inst.loader_label} version {inst.name} uses")
        deps[LOADER_KEYS[inst.loader]] = loader_version
    index = {"formatVersion": 1, "game": "minecraft", "versionId": time.strftime("%Y.%m.%d"),
             "name": inst.name, "summary": f"Shared from Craftd · Minecraft {inst.game_version} · {inst.loader_label}",
             "files": files, "dependencies": deps}

    gd = inst.game_dir
    extra: list[tuple[Path, str]] = []  # (file on disk, path inside overrides/)

    def add_tree(folder: Path, rel_root: str) -> None:
        if folder.is_dir():
            for f in sorted(folder.rglob("*")):
                if f.is_file() and not f.name.endswith((".craftd-tmp", ".lock")) and "craftd-backup" not in f.name:
                    extra.append((f, f"{rel_root}/{f.relative_to(folder).as_posix()}"))

    if options.config:
        add_tree(gd / "config", "config")
    if options.resourcepacks:
        add_tree(gd / "resourcepacks", "resourcepacks")
    if options.shaderpacks:
        add_tree(gd / "shaderpacks", "shaderpacks")
    if options.options and (gd / "options.txt").is_file():
        extra.append((gd / "options.txt", "options.txt"))
    if options.servers and (gd / "servers.dat").is_file():
        extra.append((gd / "servers.dat", "servers.dat"))
    for world in options.worlds:
        add_tree(gd / "saves" / world, f"saves/{world}")
    report.files = len(extra)

    progress(f"Writing {dest.name}…")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".craftd-tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr(INDEX, json.dumps(index, indent=2))
            for jar in jar_overrides:
                zf.write(jar, f"overrides/mods/{jar.name}")
            for path, rel in extra:
                zf.write(path, f"overrides/{rel}")
        tmp.replace(dest)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    return report
