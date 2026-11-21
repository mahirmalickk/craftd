"""Installing, updating, removing and toggling mods in an instance."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from typing import Callable

import shutil

from . import compat
from .instances import Instance, compatible_loaders
from .modrinth import ModrinthClient, ModrinthError, primary_file
from .mods import HashCache, LocalMod, ModScanner

Progress = Callable[[str], None]


def _noop(_: str) -> None:
    pass


@dataclass
class InstallReport:
    installed: list[str] = field(default_factory=list)
    skipped: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    missing_deps: list[str] = field(default_factory=list)
    waitlisted: list[str] = field(default_factory=list)
    copied: list[str] = field(default_factory=list)
    swapped: list[str] = field(default_factory=list)  # picked another build because the first didn't fit
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = []
        if self.installed:
            parts.append(f"Installed {len(self.installed)}: " + ", ".join(self.installed))
        if self.swapped:
            parts.append("Picked a different build: " + "; ".join(self.swapped))
        if self.warnings:
            parts.append("Heads up: " + "; ".join(self.warnings))
        if self.copied:
            parts.append("Copied as-is (not verified for this version): " + ", ".join(self.copied))
        if self.waitlisted:
            parts.append(f"Waitlisted {len(self.waitlisted)} (no build yet): " + ", ".join(self.waitlisted))
        if self.skipped:
            parts.append("Already present: " + ", ".join(self.skipped))
        if self.missing_deps:
            parts.append("Missing dependencies: " + ", ".join(self.missing_deps))
        if self.failed:
            parts.append("Failed: " + "; ".join(self.failed))
        return "\n".join(parts) or "Nothing to do."


class Installer:
    def __init__(self, client: ModrinthClient, scanner: ModScanner, cache: HashCache):
        self.client = client
        self.scanner = scanner
        self.cache = cache
        self.stable_first = True  # Settings → Mods
        self.auto_dependencies = True

    def title(self, project_id: str) -> str:
        if project_id not in self.cache.projects:
            try:
                for p in self.client.projects([project_id]):
                    self.cache.remember_project(p)
            except ModrinthError:
                pass
        return self.cache.projects.get(project_id, {}).get("title") or project_id

    @staticmethod
    def fits(inst: Instance, version: dict) -> bool:
        """Does a Modrinth version run on this instance's Minecraft version and loader?"""
        return inst.game_version in (version.get("game_versions") or []) and bool(
            set(version.get("loaders") or []) & set(compatible_loaders(inst.loader)))

    def newest_release(self, inst: Instance, project_id: str) -> dict | None:
        versions = self.client.project_versions(project_id, compatible_loaders(inst.loader), [inst.game_version])
        return next((v for v in versions if v.get("version_type", "release") == "release"), None)

    def pins(self, versions: list[tuple[str, dict]]) -> dict[str, tuple[str, str]]:
        """Exact versions that mods require of other mods: {project_id: (version_id, required_by)}.

        Example: Iris 1.11.7 for 26.3 requires exactly Sodium mc26.3-0.9.2."""
        out: dict[str, tuple[str, str]] = {}
        for required_by, v in versions:
            for d in v.get("dependencies") or []:
                if d.get("dependency_type") == "required" and d.get("project_id") and d.get("version_id"):
                    out.setdefault(d["project_id"], (d["version_id"], required_by))
        return out

    def resolve_project(self, inst: Instance, project_id: str) -> dict | None:
        """Best version of a project for this instance: newest release, else newest anything.
        With stable_first off (Settings → Mods), simply the newest build, betas included."""
        versions = self.client.project_versions(project_id, compatible_loaders(inst.loader), [inst.game_version])
        if not versions:
            return None
        if not self.stable_first:
            return versions[0]
        return next((v for v in versions if v.get("version_type") == "release"), versions[0])

    def install_projects(self, inst: Instance, project_ids: list[str], progress: Progress = _noop) -> InstallReport:
        report = InstallReport()
        versions = []
        for pid in project_ids:
            progress(f"Finding a build of {self.title(pid)} for {inst.summary}…")
            v = self.resolve_project(inst, pid)
            if v:
                versions.append(v)
            else:
                report.failed.append(f"{self.title(pid)}: no build for {inst.summary}")
        sub = self.install_versions(inst, versions, progress)
        for f in fields(InstallReport):  # merge every list, including swapped builds and warnings
            getattr(report, f.name).extend(getattr(sub, f.name))
        return report

    def install_versions(self, inst: Instance, versions: list[dict], progress: Progress = _noop) -> InstallReport:
        """Download versions into the instance, pulling in required dependencies."""
        report = InstallReport()
        present = {m.project_id for m in self.scanner.scan(inst) if m.project_id}
        seen = set(present)
        queue = list(versions)
        while queue:
            v = queue.pop(0)
            pid = v["project_id"]
            title = self.title(pid)
            if pid in seen:
                if pid in present:
                    report.skipped.append(title)
                continue
            seen.add(pid)
            try:
                f = primary_file(v)
                progress(f"Downloading {title} {v.get('version_number', '')}…")
                dest = inst.mods_dir / f["filename"]
                self.client.download(f["url"], dest, f.get("hashes", {}).get("sha1"))
                problems = self.environment_problems(inst, dest)
                if problems:  # the jar itself says it won't run on this Minecraft/loader version
                    progress(f"{title} {v.get('version_number', '')} doesn't fit {inst.loader_text}; "
                             f"looking for a build that does…")
                    alt = self._find_fitting_build(inst, v, progress)
                    if alt:
                        dest.unlink(missing_ok=True)
                        report.swapped.append(f"{title} {alt['version_number']} instead of "
                                              f"{v.get('version_number')} ({problems[0].message.rstrip('.')})")
                        v, f = alt, primary_file(alt)
                    else:
                        report.warnings.append(f"{title}: {problems[0].message}")
                if f.get("hashes", {}).get("sha1"):
                    self.cache.remember_version(f["hashes"]["sha1"], v)
                report.installed.append(f"{title} {v.get('version_number', '')}".strip())
            except ModrinthError as exc:
                report.failed.append(f"{title}: {exc}")
                continue

            for dep in v.get("dependencies") or []:
                if dep.get("dependency_type") != "required":
                    continue
                dep_pid = dep.get("project_id")
                if not self.auto_dependencies:  # Settings → Mods: just report what's missing
                    if dep_pid and dep_pid not in seen:
                        seen.add(dep_pid)
                        report.missing_deps.append(f"{self.title(dep_pid)} (needed by {title})")
                    continue
                try:
                    dv = None
                    if dep.get("version_id"):  # the mod asks for one exact version: use it if it fits
                        if dep_pid in seen:
                            continue
                        pinned = self.client.version(dep["version_id"])
                        if pinned and self.fits(inst, pinned):
                            dv = pinned
                            dep_pid = dep_pid or pinned["project_id"]
                        elif pinned and not dep_pid:
                            dep_pid = pinned["project_id"]
                    if not dep_pid or dep_pid in seen:
                        continue
                    if dv is None:
                        progress(f"Resolving dependency {self.title(dep_pid)}…")
                        dv = self.resolve_project(inst, dep_pid)
                except ModrinthError as exc:
                    report.failed.append(f"dependency of {title}: {exc}")
                    continue
                if dv:
                    queue.append(dv)
                else:
                    report.missing_deps.append(f"{self.title(dep_pid)} (needed by {title})")
        self.cache.save()
        return report

    # ---- fitting the loader version ---------------------------------------------------------
    @staticmethod
    def environment_problems(inst: Instance, path) -> list:
        return compat.fits_environment(path, inst.game_version, inst.loader, inst.loader_version, inst.loader_label)

    def _find_fitting_build(self, inst: Instance, rejected: dict, progress: Progress, limit: int = 5) -> dict | None:
        """Try other builds of the same project (stable first, newest first) until one fits."""
        versions = [x for x in self.client.project_versions(rejected["project_id"], compatible_loaders(inst.loader),
                                                             [inst.game_version]) if x["id"] != rejected["id"]]
        versions.sort(key=lambda x: (x.get("version_type", "release") != "release",))  # keeps newest-first order
        scratch = self.cache.path.parent / "fit-check"
        scratch.mkdir(parents=True, exist_ok=True)
        try:
            for cand in versions[:limit]:
                f = primary_file(cand)
                progress(f"Checking {cand.get('version_number')}…")
                tmp = scratch / f["filename"]
                try:
                    self.client.download(f["url"], tmp, f.get("hashes", {}).get("sha1"))
                except ModrinthError:
                    continue
                if not self.environment_problems(inst, tmp):
                    shutil.move(str(tmp), str(inst.mods_dir / f["filename"]))
                    return cand
                tmp.unlink(missing_ok=True)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        return None

    def check_instance(self, inst: Instance, mods: list[LocalMod] | None = None) -> list:
        """Problems between the instance's mods, Minecraft and the loader (enabled mods only)."""
        files = [m.path for m in (mods if mods is not None else self.scanner.scan(inst)) if m.enabled]
        known = compat.loaded_in_last_good_start(inst.game_dir / "logs" / "latest.log")
        issues = compat.check_files(files, inst.game_version, inst.loader, inst.loader_version, inst.loader_label, known)
        # A required mod that the last successful start loaded can't really be missing
        return [i for i in issues if not (i.message.startswith("Needs “") and i.message.split("”")[0][7:] in known)]

    # ---- managing installed mods ------------------------------------------------
    def check_updates(self, inst: Instance, mods: list[LocalMod]) -> dict[str, dict]:
        """{sha1: newer version} for Modrinth mods with an update for this instance."""
        tracked = [m for m in mods if m.on_modrinth]
        if not tracked:
            return {}
        hashes = [m.sha1 for m in tracked]
        latest = self.client.latest_versions_for(hashes, compatible_loaders(inst.loader), [inst.game_version])
        current = self.client.versions_from_hashes(hashes)
        pins = self.pins([(self.title(v["project_id"]), v) for v in current.values()])
        out: dict[str, dict] = {}
        for m in tracked:
            new, cur = latest.get(m.sha1), current.get(m.sha1)
            if not new or new["id"] == m.version_id:
                continue
            if m.project_id in pins and pins[m.project_id][0] == m.version_id:
                continue  # another mod needs exactly this version (e.g. Iris -> Sodium)
            if new.get("version_type", "release") != "release" and self.stable_first:
                if cur and cur.get("version_type", "release") != "release":
                    pass  # already on a beta: newer betas are fair game
                else:
                    new = self.newest_release(inst, m.project_id)
                    if not new or new["id"] == m.version_id:
                        continue
            if cur and new.get("date_published", "") <= cur.get("date_published", ""):
                continue  # never "update" to something older
            out[m.sha1] = new
        return out

    def update(self, inst: Instance, mod: LocalMod, version: dict) -> str:
        f = primary_file(version)
        name = f["filename"] + ("" if mod.enabled else ".disabled")
        dest = inst.mods_dir / name
        self.client.download(f["url"], dest, f.get("hashes", {}).get("sha1"))
        if f.get("hashes", {}).get("sha1"):
            self.cache.remember_version(f["hashes"]["sha1"], version)
        if dest.resolve() != mod.path.resolve():
            mod.path.unlink(missing_ok=True)
        self.cache.save()
        return f"{mod.title} → {version.get('version_number')}"

    @staticmethod
    def add_files(inst: Instance, paths) -> tuple[list[str], list[str]]:
        """Add File / drag and drop: copy jars into the mods folder. Returns (added, skipped with why)."""
        from pathlib import Path
        added, skipped = [], []
        inst.mods_dir.mkdir(parents=True, exist_ok=True)
        for p in map(Path, paths):
            if not p.is_file() or not p.name.lower().endswith(".jar"):
                skipped.append(f"{p.name} (not a .jar file)")
                continue
            dest = inst.mods_dir / p.name
            if dest.exists() or dest.with_name(dest.name + ".disabled").exists():
                skipped.append(f"{p.name} (already there)")
                continue
            if p.resolve().parent == inst.mods_dir.resolve():
                continue
            shutil.copy2(p, dest)
            added.append(p.name)
        return added, skipped

    @staticmethod
    def remove(mod: LocalMod) -> None:
        mod.path.unlink(missing_ok=True)

    @staticmethod
    def set_enabled(mod: LocalMod, enabled: bool) -> None:
        if enabled == mod.enabled:
            return
        if enabled:
            mod.path.rename(mod.path.with_name(mod.base_name))
        else:
            mod.path.rename(mod.path.with_name(mod.base_name + ".disabled"))
