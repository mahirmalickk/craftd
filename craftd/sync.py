"""Carry Over: detect the mods you use in other instances and bring them to a new one.

How it works
1. Scan the source instance(s) and fingerprint every jar (see mods.py).
2. Group the jars by Modrinth project, so "sodium-0.6.jar" in 26.2 and
   "sodium-0.7.jar" in 26.1 count as one mod.
3. Ask Modrinth, in one batched call, for the newest build of each project that
   matches the target's Minecraft version and loader.
4. Sort every mod into: ready to install / no build yet / not on Modrinth /
   already installed.
5. Mods with no build yet go on the target's waitlist. Craftd rechecks the
   waitlist on startup and tells you when they become available.
"""

from __future__ import annotations

import shutil
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Callable

from .installer import InstallReport, Installer
from .instances import Instance, InstanceManager, compatible_loaders, loader_family
from .modrinth import ModrinthError
from .mods import LocalMod, ModScanner, mod_files
from .versions import VersionOrder

Progress = Callable[[str], None]


def _noop(_: str) -> None:
    pass


class Status(str, Enum):
    AVAILABLE = "available"  # Modrinth has a build for the target
    UNAVAILABLE = "unavailable"  # on Modrinth, but no build for the target yet
    WRONG_LOADER = "wrong_loader"  # the mod doesn't exist for the target's loader at all
    WAITLISTED = "waitlisted"  # no build yet, and already on this instance's waitlist
    LOCAL = "local"  # jar isn't on Modrinth; Craftd can't check compatibility
    INSTALLED = "installed"  # target already has it


STATUS_ORDER = [Status.AVAILABLE, Status.UNAVAILABLE, Status.WAITLISTED, Status.WRONG_LOADER, Status.LOCAL,
                Status.INSTALLED]
STATUS_LABELS = {
    Status.AVAILABLE: "Ready",
    Status.UNAVAILABLE: "No build yet",
    Status.WRONG_LOADER: "Not for this loader",
    Status.WAITLISTED: "Waitlisted",
    Status.LOCAL: "Not on Modrinth",
    Status.INSTALLED: "Already installed",
}


@dataclass
class Candidate:
    key: str
    title: str
    project_id: str | None
    sources: list[str] = field(default_factory=list)  # instance names it was found in
    source_mods: list[LocalMod] = field(default_factory=list)
    status: Status | None = None
    target_version: dict | None = None
    installed: LocalMod | None = None
    note: str = ""  # why Craftd picked this exact build

    @property
    def is_prerelease(self) -> bool:
        return bool(self.target_version) and self.target_version.get("version_type", "release") != "release"

    @property
    def representative(self) -> LocalMod:
        """The source jar to use for lookups/copying (prefers an enabled one)."""
        return next((m for m in self.source_mods if m.enabled), self.source_mods[0])

    @property
    def target_version_number(self) -> str:
        if self.target_version:
            return self.target_version.get("version_number", "")
        if self.installed:
            return self.installed.version_number or ""
        return ""


class CarryOver:
    def __init__(self, manager: InstanceManager, scanner: ModScanner, installer: Installer,
                 order: VersionOrder | None = None):
        self.manager = manager
        self.scanner = scanner
        self.installer = installer
        self.client = installer.client
        self.order = order or VersionOrder()

    # ---- choosing a source ---------------------------------------------------------
    def suggest_source(self, target: Instance, instances: list[Instance]) -> Instance | None:
        """The instance you most likely want to copy from: same loader family,
        closest Minecraft version at or below the target, and it has mods."""
        others = [i for i in instances if i.id != target.id and mod_files(i.mods_dir)]
        if not others:
            return None
        same_family = [i for i in others if loader_family(i.loader) == loader_family(target.loader)] or others
        not_newer = [i for i in same_family if not self.order.newer(i.game_version, target.game_version)]
        pool = not_newer or same_family
        return max(pool, key=lambda i: (self.order.key(i.game_version), i.created))

    # ---- detection -------------------------------------------------------------------------
    def detect(self, target: Instance, sources: list[Instance], progress: Progress = _noop) -> list[Candidate]:
        if target.loader == "vanilla":
            raise ValueError("Vanilla instances can't load mods. Pick a mod loader for this instance first.")
        sources = [s for s in sources if s.id != target.id]
        progress(f"Scanning mods in {', '.join(s.name for s in sources)}…")
        scans = self.scanner.scan_many([target, *sources])

        installed_by_key = {m.key: m for m in scans[target.id]}
        installed_by_modid = {m.mod_id.lower(): m for m in scans[target.id] if m.mod_id}

        # Newest source first, so the representative jar is the most recent one.
        sources = sorted(sources, key=lambda s: self.order.key(s.game_version), reverse=True)
        groups: dict[str, Candidate] = {}
        for src in sources:
            for mod in scans[src.id]:
                cand = groups.setdefault(mod.key, Candidate(key=mod.key, title=mod.title, project_id=mod.project_id))
                if src.name not in cand.sources:
                    cand.sources.append(src.name)
                cand.source_mods.append(mod)

        to_resolve: list[Candidate] = []
        for cand in groups.values():
            rep = cand.representative
            match = installed_by_key.get(cand.key) or (
                installed_by_modid.get(rep.mod_id.lower()) if rep.mod_id else None
            )
            if match:
                cand.status, cand.installed = Status.INSTALLED, match
            elif not cand.project_id:
                cand.status = Status.LOCAL
            else:
                to_resolve.append(cand)

        if to_resolve:
            progress(f"Checking {len(to_resolve)} mods against Modrinth for {target.summary}…")
            by_hash = {c.representative.sha1: c for c in to_resolve}
            latest = self.client.latest_versions_for(
                list(by_hash), compatible_loaders(target.loader), [target.game_version]
            )
            for sha1, cand in by_hash.items():
                if sha1 in latest:
                    cand.status, cand.target_version = Status.AVAILABLE, latest[sha1]
                else:
                    cand.status = Status.UNAVAILABLE
            self._mark_wrong_loader(target, [c for c in to_resolve if c.status == Status.UNAVAILABLE])
            waiting = {e["project_id"] for e in self.waitlist(target)}
            for c in to_resolve:
                if c.status == Status.UNAVAILABLE and c.project_id in waiting:
                    c.status = Status.WAITLISTED

        available = [c for c in groups.values() if c.status == Status.AVAILABLE]
        if available:
            progress("Choosing stable builds and the exact versions your mods depend on…")
            self._prefer_stable(target, available)
            self._apply_pins(target, scans[target.id], available)

        return sorted(groups.values(), key=lambda c: (STATUS_ORDER.index(c.status), c.title.lower()))

    def _mark_wrong_loader(self, target: Instance, cands: list[Candidate]) -> None:
        """'No build yet' only makes sense if the mod supports the target's loader at all.
        Fabric API will never come to NeoForge, so it shouldn't sit on the waitlist forever."""
        cache = self.installer.cache
        missing = [c.project_id for c in cands if c.project_id
                   and cache.projects.get(c.project_id, {}).get("loaders") is None]
        try:
            if missing:
                for p in self.client.projects(missing):
                    cache.remember_project(p)
                cache.save()
        except ModrinthError:
            return  # can't tell offline; leave them as "No build yet"
        wanted = set(compatible_loaders(target.loader))
        for c in cands:
            loaders = cache.projects.get(c.project_id or "", {}).get("loaders")
            if loaders is not None and not wanted & set(loaders):
                c.status = Status.WRONG_LOADER
                c.note = f"Only made for {', '.join(sorted(loaders)) or 'other loaders'}"

    def _prefer_stable(self, target: Instance, cands: list[Candidate]) -> None:
        """Modrinth's 'latest' can be a beta. Use the newest full release when one exists."""
        if not self.installer.stable_first:  # Settings → Mods: newest builds, betas included
            return
        for c in cands:
            if c.is_prerelease and c.project_id:
                try:
                    release = self.installer.newest_release(target, c.project_id)
                except ModrinthError:
                    continue
                if release:
                    c.target_version = release
                else:
                    c.note = "Only beta/alpha builds exist for this version"

    def _apply_pins(self, target: Instance, installed: list[LocalMod], cands: list[Candidate]) -> None:
        """If a mod needs one exact version of another (Iris -> Sodium), install that version."""
        pairs: list[tuple[str, dict]] = []
        hashes = [m.sha1 for m in installed if m.project_id]
        try:
            if hashes:
                for v in self.client.versions_from_hashes(hashes).values():
                    pairs.append((self.installer.title(v["project_id"]), v))
        except ModrinthError:
            pass
        pairs += [(c.title, c.target_version) for c in cands if c.target_version]
        pins = self.installer.pins(pairs)
        for c in cands:
            pin = pins.get(c.project_id or "")
            if not pin or not c.target_version or pin[0] == c.target_version["id"]:
                continue
            try:
                pinned = self.client.version(pin[0])
            except ModrinthError:
                continue
            if pinned and self.installer.fits(target, pinned):
                c.target_version = pinned
                c.note = f"Exact version required by {pin[1]}"

    # ---- applying ----------------------------------------------------------------------------
    def carry(self, target: Instance, chosen: list[Candidate], progress: Progress = _noop,
              copy_local: bool = False) -> InstallReport:
        """Install the chosen Ready mods (with dependencies), waitlist chosen
        No-build-yet mods, and optionally copy chosen Not-on-Modrinth jars."""
        ready = [c.target_version for c in chosen if c.status == Status.AVAILABLE and c.target_version]
        report = self.installer.install_versions(target, ready, progress)

        waiting = [c for c in chosen if c.status == Status.UNAVAILABLE]
        if waiting:
            self.add_to_waitlist(target, waiting)
            report.waitlisted.extend(c.title for c in waiting)

        if copy_local:
            for c in chosen:
                if c.status == Status.LOCAL:
                    src = c.representative.path
                    dest = target.mods_dir / c.representative.base_name
                    if not dest.exists():
                        target.mods_dir.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(src, dest)
                        report.copied.append(c.title)
        return report

    # ---- waitlist ------------------------------------------------------------------------------
    def waitlist(self, target: Instance) -> list[dict]:
        return self.manager.load_meta(target).get("waitlist", [])

    def add_to_waitlist(self, target: Instance, candidates: list[Candidate]) -> None:
        meta = self.manager.load_meta(target)
        entries = {e["project_id"]: e for e in meta.get("waitlist", [])}
        for c in candidates:
            if c.project_id and c.project_id not in entries:
                entries[c.project_id] = {
                    "project_id": c.project_id,
                    "title": c.title,
                    "sha1": c.representative.sha1,
                    "added": time.time(),
                }
        meta["waitlist"] = sorted(entries.values(), key=lambda e: e["title"].lower())
        self.manager.save_meta(target, meta)

    def remove_from_waitlist(self, target: Instance, project_ids: list[str]) -> None:
        meta = self.manager.load_meta(target)
        meta["waitlist"] = [e for e in meta.get("waitlist", []) if e["project_id"] not in set(project_ids)]
        self.manager.save_meta(target, meta)

    def check_waitlist(self, target: Instance) -> list[Candidate]:
        """Waitlisted mods that now have a build for the target. Drops ones you installed meanwhile."""
        entries = self.waitlist(target)
        if not entries:
            return []
        installed = {m.project_id for m in self.scanner.scan(target) if m.project_id}
        done = [e["project_id"] for e in entries if e["project_id"] in installed]
        if done:
            self.remove_from_waitlist(target, done)
        entries = [e for e in entries if e["project_id"] not in installed]
        if not entries:
            return []
        latest = self.client.latest_versions_for(
            [e["sha1"] for e in entries], compatible_loaders(target.loader), [target.game_version]
        )
        ready = []
        for e in entries:
            if e["sha1"] in latest:
                ready.append(Candidate(key=e["project_id"], title=e["title"], project_id=e["project_id"],
                                       status=Status.AVAILABLE, target_version=latest[e["sha1"]]))
        self._prefer_stable(target, ready)
        return ready

    def install_from_waitlist(self, target: Instance, ready: list[Candidate], progress: Progress = _noop) -> InstallReport:
        report = self.installer.install_versions(target, [c.target_version for c in ready if c.target_version], progress)
        self.remove_from_waitlist(target, [c.project_id for c in ready if c.project_id])
        return report

    def check_all_waitlists(self, instances: list[Instance]) -> dict[str, list[Candidate]]:
        out = {}
        for inst in instances:
            try:
                ready = self.check_waitlist(inst)
            except ModrinthError:
                continue
            if ready:
                out[inst.id] = ready
        return out
