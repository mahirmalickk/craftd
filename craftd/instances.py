"""Instances: Craftd's own, plus Prism Launcher instances linked in place.

Craftd instance layout (inside the Craftd data folder):
    instances/<id>/craftd-instance.json
    instances/<id>/minecraft/mods/*.jar

Prism and MultiMC instances are linked in place (they stay in the launcher's folder). Craftd only
changes their files when you ask it to (carrying over, Edit Instance, Rename, Delete), and unlinking one
from Craftd never deletes it. Since 1.1, + New Instance creates instances inside Prism or MultiMC;
Craftd-only instances from older versions still work and can be moved there.
"""

from __future__ import annotations

import json
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path

LOADERS = ["fabric", "quilt", "neoforge", "forge", "vanilla"]
LOADER_LABELS = {
    "fabric": "Fabric",
    "quilt": "Quilt",
    "neoforge": "NeoForge",
    "forge": "Forge",
    "vanilla": "Vanilla",
}
# Prism (mmc-pack.json) component uids -> loader
PRISM_LOADER_UIDS = {
    "net.fabricmc.fabric-loader": "fabric",
    "org.quiltmc.quilt-loader": "quilt",
    "net.neoforged": "neoforge",
    "net.minecraftforge": "forge",
}
INSTANCE_FILE = "craftd-instance.json"
LAUNCHER_LABELS = {"prism": "Prism", "multimc": "MultiMC"}


def compatible_loaders(loader: str) -> list[str]:
    """Mod loaders whose mods run on this loader. Quilt can load Fabric mods."""
    if loader == "quilt":
        return ["quilt", "fabric"]
    if loader == "vanilla":
        return []
    return [loader]


def loader_family(loader: str) -> str:
    return "fabric" if loader in ("fabric", "quilt") else loader


def slugify(text: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", text.strip()).strip("-").lower()
    return slug or "instance"


@dataclass
class Instance:
    id: str
    name: str
    game_version: str
    loader: str
    root: Path
    game_dir: Path
    kind: str = "craftd"  # "craftd", or "prism" for any instance linked in place from a launcher
    launcher: str = ""  # for linked instances: "prism" or "multimc" (same instance format)
    created: float = field(default_factory=time.time)
    loader_version: str | None = None  # e.g. "26.3.0.110" for NeoForge, "0.17.2" for Fabric Loader

    @property
    def mods_dir(self) -> Path:
        return self.game_dir / "mods"

    @property
    def loader_label(self) -> str:
        return LOADER_LABELS.get(self.loader, self.loader.title())

    @property
    def summary(self) -> str:
        return f"{self.game_version} · {self.loader_label}"

    @property
    def launcher_label(self) -> str:
        """'Prism' or 'MultiMC' for linked instances, '' for Craftd's own."""
        return LAUNCHER_LABELS.get(self.launcher, "") if self.kind == "prism" else ""

    @property
    def loader_text(self) -> str:
        """'NeoForge 26.3.0.110' (or just 'NeoForge' when the version isn't known)."""
        return f"{self.loader_label} {self.loader_version}" if self.loader_version else self.loader_label

    def to_json(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "game_version": self.game_version,
            "loader": self.loader,
            "loader_version": self.loader_version,
            "created": self.created,
        }


def _cfg_value(raw: str) -> str:
    """A value from instance.cfg. Prism (Qt's ini format) quotes values with commas and escapes some characters."""
    raw = raw.strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        raw = raw[1:-1].replace('\\"', '"').replace("\\\\", "\\")
    return raw


def read_prism_instance(path: Path, launcher: str = "prism") -> dict | None:
    """Read name / Minecraft version / loader from a Prism or MultiMC instance folder."""
    from .launchers import game_dir
    pack = path / "mmc-pack.json"
    if not pack.is_file():
        return None
    try:
        data = json.loads(pack.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    game_version, loader, loader_version = None, "vanilla", None
    for comp in data.get("components", []):
        uid = comp.get("uid", "")
        if uid == "net.minecraft":
            game_version = comp.get("version") or comp.get("cachedVersion")
        elif uid in PRISM_LOADER_UIDS:
            loader = PRISM_LOADER_UIDS[uid]
            loader_version = comp.get("version") or comp.get("cachedVersion")
    if not game_version:
        return None

    name = path.name
    cfg = path / "instance.cfg"
    if cfg.is_file():
        for line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("name="):
                name = _cfg_value(line.split("=", 1)[1]) or name
                break

    return {"name": name, "game_version": game_version, "loader": loader, "loader_version": loader_version,
            "game_dir": game_dir(path, launcher)}


class InstanceManager:
    def __init__(self, home: Path):
        self.home = home
        self.instances_dir = home / "instances"
        self.meta_dir = home / "meta"
        self.linked_file = home / "linked.json"
        for d in (self.instances_dir, self.meta_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ---- listing -------------------------------------------------------------
    def list(self) -> list[Instance]:
        out: list[Instance] = []
        for d in sorted(self.instances_dir.iterdir()):
            f = d / INSTANCE_FILE
            if not f.is_file():
                continue
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out.append(
                Instance(
                    id=data["id"], name=data["name"], game_version=data["game_version"],
                    loader=data.get("loader", "vanilla"), root=d, game_dir=d / "minecraft",
                    kind="craftd", created=data.get("created", 0), loader_version=data.get("loader_version"),
                )
            )
        for entry in self._linked():
            path = Path(entry["path"])
            info = read_prism_instance(path, entry.get("launcher", "prism"))
            if not info:
                continue  # folder moved or deleted in Prism; skip quietly
            out.append(
                Instance(
                    id=entry["id"], name=info["name"], game_version=info["game_version"],
                    loader=info["loader"], root=path, game_dir=info["game_dir"],
                    kind="prism", created=entry.get("linked", 0), loader_version=info["loader_version"],
                    launcher=entry.get("launcher", "prism"),
                )
            )
        return out

    def get(self, instance_id: str) -> Instance | None:
        return next((i for i in self.list() if i.id == instance_id), None)

    def _unique_id(self, base: str) -> str:
        taken = {i.id for i in self.list()}
        candidate, n = base, 2
        while candidate in taken or (self.instances_dir / candidate).exists():
            candidate = f"{base}-{n}"
            n += 1
        return candidate

    # ---- Craftd instances ------------------------------------------------------
    def create(self, name: str, game_version: str, loader: str) -> Instance:
        if loader not in LOADERS:
            raise ValueError(f"Unknown loader: {loader}")
        inst_id = self._unique_id(slugify(name))
        root = self.instances_dir / inst_id
        inst = Instance(id=inst_id, name=name.strip() or inst_id, game_version=game_version,
                        loader=loader, root=root, game_dir=root / "minecraft")
        inst.mods_dir.mkdir(parents=True, exist_ok=True)
        (root / INSTANCE_FILE).write_text(json.dumps(inst.to_json(), indent=2), encoding="utf-8")
        return inst

    def remove(self, inst: Instance) -> None:
        """Delete a Craftd instance, or unlink a Prism one (its files are left alone)."""
        if inst.kind == "prism":
            self._save_linked([e for e in self._linked() if e["id"] != inst.id])
        else:
            shutil.rmtree(inst.root, ignore_errors=True)
        (self.meta_dir / f"{inst.id}.json").unlink(missing_ok=True)

    # ---- Prism linking ------------------------------------------------------------
    def _linked(self) -> list[dict]:
        if not self.linked_file.is_file():
            return []
        try:
            return json.loads(self.linked_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

    def _save_linked(self, entries: list[dict]) -> None:
        self.linked_file.write_text(json.dumps(entries, indent=2), encoding="utf-8")

    def discover_prism(self, instances_dir: Path, launcher: str = "prism") -> list[tuple[Path, dict]]:
        """Prism (or MultiMC) instances in a folder that aren't linked yet."""
        linked = {str(Path(e["path"]).resolve()) for e in self._linked()}
        found = []
        if not instances_dir.is_dir():
            return found
        for d in sorted(instances_dir.iterdir()):
            if d.is_dir() and str(d.resolve()) not in linked:
                info = read_prism_instance(d, launcher)
                if info:
                    found.append((d, info))
        return found

    def link_prism(self, path: Path, launcher: str = "prism") -> Instance:
        """Link a Prism or MultiMC instance in place (both launchers use the same instance format)."""
        info = read_prism_instance(path, launcher)
        if not info:
            name = LAUNCHER_LABELS.get(launcher, "Prism")
            raise ValueError(f"{path} doesn't look like a {name} instance (no usable mmc-pack.json)")
        entries = self._linked()
        resolved = str(path.resolve())
        existing = next((e for e in entries if e["path"] == resolved), None)
        if existing is None:
            existing = {"id": self._unique_id(f"{launcher}-" + slugify(path.name)), "path": resolved,
                        "linked": time.time(), "launcher": launcher}
            entries.append(existing)
            self._save_linked(entries)
        return self.get(existing["id"])  # type: ignore[return-value]

    # ---- Edit Instance ----------------------------------------------------------------
    def edit(self, inst: Instance, name: str, game_version: str, loader: str,
             loader_version: str | None) -> Instance:
        """Rename an instance, or change its Minecraft version or loader.

        Craftd instances: their own record. Prism/MultiMC instances: the launcher's mmc-pack.json
        (backed up first, as mmc-pack.json.craftd-backup-<date>) and the name in instance.cfg.
        Mods aren't touched; the compatibility check flags any that don't fit anymore."""
        from .loaders import build_components
        if loader not in LOADERS:
            raise ValueError(f"Unknown loader: {loader}")
        name = name.strip() or inst.name
        if loader == "vanilla":
            loader_version = None
        if inst.kind != "prism":
            inst.name, inst.game_version, inst.loader, inst.loader_version = name, game_version, loader, loader_version
            (inst.root / INSTANCE_FILE).write_text(json.dumps(inst.to_json(), indent=2), encoding="utf-8")
            return self.get(inst.id) or inst

        pack_file = inst.root / "mmc-pack.json"
        data = json.loads(pack_file.read_text(encoding="utf-8"))
        stamp = time.strftime("%Y%m%d-%H%M%S")
        shutil.copy2(pack_file, inst.root / f"mmc-pack.json.craftd-backup-{stamp}")
        data["components"] = build_components(data.get("components", []), game_version, loader, loader_version)
        data.setdefault("formatVersion", 1)
        tmp = pack_file.with_suffix(".json.craftd-tmp")
        tmp.write_text(json.dumps(data, indent=4), encoding="utf-8")
        tmp.replace(pack_file)  # all or nothing: never a half-written file

        if name != inst.name:
            from .launchers import write_cfg_name
            write_cfg_name(inst.root / "instance.cfg", name)
        return self.get(inst.id) or inst

    # ---- right-click actions ------------------------------------------------------------------------
    def rename(self, inst: Instance, name: str) -> Instance:
        """Change only the name: instance.cfg for linked instances (the folder keeps its name, like in
        Prism and MultiMC), Craftd's own record otherwise."""
        from .launchers import write_cfg_name
        name = name.strip()
        if not name:
            raise ValueError("The name can't be empty")
        if inst.kind == "prism":
            write_cfg_name(inst.root / "instance.cfg", name)
        else:
            inst.name = name
            (inst.root / INSTANCE_FILE).write_text(json.dumps(inst.to_json(), indent=2), encoding="utf-8")
        return self.get(inst.id) or inst

    def copy(self, inst: Instance, name: str) -> Instance:
        """Copy an instance with everything in it. A linked one is copied inside its launcher and linked."""
        from .launchers import copy_instance
        if inst.kind == "prism":
            return self.link_prism(copy_instance(inst.root, name), inst.launcher or "prism")
        new = self.create(name, inst.game_version, inst.loader)
        shutil.rmtree(new.root / "minecraft", ignore_errors=True)
        if inst.game_dir.is_dir():
            shutil.copytree(inst.game_dir, new.root / "minecraft")
        new.loader_version = inst.loader_version
        (new.root / INSTANCE_FILE).write_text(json.dumps(new.to_json(), indent=2), encoding="utf-8")
        return self.get(new.id) or new

    def delete(self, inst: Instance, remove_folder=None) -> None:
        """Delete an instance's files for good (linked ones too: they disappear from the launcher).

        remove_folder(path) can send the folder to the Recycle Bin instead; it returns True when done."""
        if not (remove_folder and remove_folder(inst.root)):
            shutil.rmtree(inst.root)
        if inst.kind == "prism":
            self._save_linked([e for e in self._linked() if e["id"] != inst.id])
        (self.meta_dir / f"{inst.id}.json").unlink(missing_ok=True)

    def create_in_launcher(self, launcher: str, parent: Path, name: str, game_version: str, loader: str,
                           loader_version: str | None) -> Instance:
        """Make a new instance inside Prism or MultiMC and link it."""
        from .launchers import create_instance
        if loader not in LOADERS:
            raise ValueError(f"Unknown loader: {loader}")
        root = create_instance(parent, name.strip() or f"{LOADER_LABELS[loader]} {game_version}", game_version,
                               loader, loader_version, launcher)
        return self.link_prism(root, launcher)

    def move_to_launcher(self, inst: Instance, launcher: str, parent: Path, loader_version: str | None) -> Instance:
        """Turn a Craftd-only instance (made before 1.1) into a Prism/MultiMC one: same name, version and
        loader, with everything in its game folder moved over and its waitlist kept."""
        if inst.kind == "prism":
            raise ValueError(f"{inst.name} is already in {inst.launcher_label}")
        new = self.create_in_launcher(launcher, parent, inst.name, inst.game_version, inst.loader,
                                      loader_version or inst.loader_version)
        new.game_dir.mkdir(parents=True, exist_ok=True)
        if inst.game_dir.is_dir():
            for item in inst.game_dir.iterdir():
                dest = new.game_dir / item.name
                if dest.is_dir() and item.is_dir():  # e.g. the empty mods folder the new instance starts with
                    for child in item.iterdir():
                        shutil.move(str(child), str(dest / child.name))
                elif not dest.exists():
                    shutil.move(str(item), str(dest))
        meta = self.meta_dir / f"{inst.id}.json"
        if meta.is_file():
            meta.replace(self.meta_dir / f"{new.id}.json")
        shutil.rmtree(inst.root, ignore_errors=True)
        return self.get(new.id) or new

    # ---- per-instance Craftd metadata (waitlist etc.) -------------------------------
    def load_meta(self, inst: Instance) -> dict:
        f = self.meta_dir / f"{inst.id}.json"
        if f.is_file():
            try:
                return json.loads(f.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                pass
        return {}

    def save_meta(self, inst: Instance, meta: dict) -> None:
        (self.meta_dir / f"{inst.id}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
