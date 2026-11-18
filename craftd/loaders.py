"""Loader versions and the launcher's instance format, for Edit Instance.

Versions come from the launcher's own metadata server, so the names match exactly what that launcher
expects in an instance's mmc-pack.json: Prism's (meta.prismlauncher.org) for Prism and Craftd
instances, MultiMC's (meta.multimc.org) for MultiMC ones. Both use the same format:
<uid>/index.json → {"versions": [{"version", "type", "recommended", "releaseTime", "requires": [...]}]}."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass

META_URLS = {"prism": "https://meta.prismlauncher.org/v1", "multimc": "https://meta.multimc.org/v1"}
LOADER_UIDS = {  # Craftd's loader names → the launcher's component uid
    "fabric": "net.fabricmc.fabric-loader",
    "quilt": "org.quiltmc.quilt-loader",
    "neoforge": "net.neoforged",
    "forge": "net.minecraftforge",
}
INTERMEDIARY_UID = "net.fabricmc.intermediary"  # Fabric and Quilt need it, matched to the Minecraft version
LAUNCHER_PROCESSES = {"prism": ["prismlauncher.exe", "prismlauncher"], "multimc": ["MultiMC.exe", "MultiMC"]}


@dataclass
class LoaderVersion:
    version: str
    recommended: bool = False
    stable: bool = True
    released: str = ""

    @property
    def label(self) -> str:
        tags = [t for t, on in (("recommended", self.recommended), ("beta", not self.stable)) if on]
        return f"{self.version} ({', '.join(tags)})" if tags else self.version


def parse_index(data: dict, loader: str, game_version: str) -> list[LoaderVersion]:
    """Builds of `loader` that fit `game_version`, newest first.

    NeoForge and Forge builds name the Minecraft version they need; Fabric and Quilt loaders work on
    any version (their Intermediary component is what's tied to Minecraft)."""
    out = []
    for v in (data or {}).get("versions", []):
        version = v.get("version")
        if not version:
            continue
        needs = [r.get("equals") for r in v.get("requires", []) if r.get("uid") == "net.minecraft" and r.get("equals")]
        if needs and game_version not in needs:
            continue
        stable = v.get("type", "release") == "release" and not any(
            tag in version.lower() for tag in ("beta", "alpha", "snapshot", "rc", "pre"))
        out.append(LoaderVersion(version, bool(v.get("recommended")), stable, v.get("releaseTime", "")))
    out.sort(key=lambda lv: lv.released, reverse=True)
    return out


def default_version(versions: list[LoaderVersion]) -> LoaderVersion | None:
    """What Prism would pick: the recommended build, else the newest stable one, else the newest."""
    return (next((v for v in versions if v.recommended), None)
            or next((v for v in versions if v.stable), None)
            or (versions[0] if versions else None))


def fetch_loader_versions(session, loader: str, game_version: str, launcher: str = "prism",
                          timeout: float = 20) -> list[LoaderVersion]:
    if loader not in LOADER_UIDS:
        return []
    base = META_URLS.get(launcher, META_URLS["prism"])
    resp = session.get(f"{base}/{LOADER_UIDS[loader]}/index.json", timeout=timeout)
    resp.raise_for_status()
    return parse_index(resp.json(), loader, game_version)


def build_components(old: list[dict], game_version: str, loader: str, loader_version: str | None) -> list[dict]:
    """The new mmc-pack.json component list, the way Prism writes it.

    Keeps anything the user added that isn't Minecraft or a loader (e.g. a custom library). LWJGL and
    other entries Prism added by itself are kept if Minecraft stays the same and dropped if it changes,
    so the launcher picks the right ones again the next time it opens the instance."""
    old_mc = next((c.get("version") for c in old if c.get("uid") == "net.minecraft"), None)
    replaced = {"net.minecraft", INTERMEDIARY_UID, "org.quiltmc.hashed", *LOADER_UIDS.values()}
    keep_before, keep_after = [], []
    seen_mc = False
    for c in old:
        uid = c.get("uid", "")
        if uid == "net.minecraft":
            seen_mc = True
        if uid in replaced:
            continue
        if c.get("dependencyOnly") and old_mc != game_version:
            continue
        (keep_after if seen_mc else keep_before).append(c)
    comps = keep_before + [{"important": True, "uid": "net.minecraft", "version": game_version}]
    if loader in ("fabric", "quilt"):
        comps.append({"dependencyOnly": True, "uid": INTERMEDIARY_UID, "version": game_version})
    if loader in LOADER_UIDS and loader_version:
        comps.append({"uid": LOADER_UIDS[loader], "version": loader_version})
    return comps + keep_after


def launcher_running(launcher: str) -> bool:
    """Is Prism / MultiMC open right now? It can overwrite an instance's files while it's running."""
    names = LAUNCHER_PROCESSES.get(launcher, [])
    try:
        if sys.platform.startswith("win"):
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=10,
                                 creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.lower()
            return any(f'"{n.lower()}"' in out for n in names if n.endswith(".exe"))
        out = subprocess.run(["ps", "-A", "-o", "comm="], capture_output=True, text=True, timeout=10).stdout
        procs = {line.strip().rsplit("/", 1)[-1].lower() for line in out.splitlines()}
        return any(n.lower() in procs for n in names)
    except (OSError, subprocess.SubprocessError):
        return False  # can't tell: don't block the user
