"""One object that wires Craftd's pieces together (used by the GUI and the CLI)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from .installer import Installer
from .instances import InstanceManager
from .modrinth import ModrinthClient, ModrinthError
from .mods import HashCache, ModScanner
from .paths import data_dir
from .settings import Settings
from .sync import CarryOver
from .versions import VersionOrder


class Craftd:
    def __init__(self, home: Path | None = None, client=None):
        self.home = home or data_dir()
        self.client = client or ModrinthClient()
        self.manager = InstanceManager(self.home)
        self.cache = HashCache(self.home / "cache" / "modrinth.json")
        self.scanner = ModScanner(self.client, self.cache)
        self.installer = Installer(self.client, self.scanner, self.cache)
        self.order = VersionOrder()
        self.carry = CarryOver(self.manager, self.scanner, self.installer, self.order)
        self.game_versions: list[dict] = []
        self._load_cached_versions()
        self.settings = Settings.load(self.home)
        self._loader_cache: dict = {}
        self.apply_settings()

    def apply_settings(self, settings: Settings | None = None) -> None:
        """Hand the engine-side preferences (builds, dependencies, network) to the pieces that use them."""
        if settings is not None:
            self.settings = settings
        s = self.settings
        self.installer.stable_first = s.stable_first
        self.installer.auto_dependencies = s.auto_dependencies
        if hasattr(self.client, "configure_network"):
            self.client.configure_network(s.proxy, s.proxy_host, s.proxy_port, s.timeout)

    # ---- Edit Instance ----------------------------------------------------------------------------
    def loader_versions(self, loader: str, game_version: str, launcher: str = "prism"):
        """Builds of a loader for a Minecraft version, newest first, named the way the launcher names them."""
        from .loaders import fetch_loader_versions
        key = (loader, game_version, launcher)
        if key not in self._loader_cache:
            session = getattr(self.client, "session", None)
            if session is None:
                import requests
                session = requests.Session()
            self._loader_cache[key] = fetch_loader_versions(session, loader, game_version, launcher,
                                                            timeout=self.settings.timeout)
        return self._loader_cache[key]

    # ---- storage ---------------------------------------------------------------------------------
    CACHE_ITEMS = {"modrinth.json": "Mod lookups (which jar is which Modrinth mod)",
                   "icons": "Mod icons from Add from Modrinth",
                   "game_versions.json": "Minecraft version list",
                   "fit-check": "Leftover build checks"}

    def cache_usage(self) -> list[tuple[str, int]]:
        """(description, bytes) for each thing in the cache folder that exists."""
        out = []
        for name, label in self.CACHE_ITEMS.items():
            path = self.home / "cache" / name
            if path.is_file():
                out.append((label, path.stat().st_size))
            elif path.is_dir():
                out.append((label, sum(f.stat().st_size for f in path.rglob("*") if f.is_file())))
        return out

    def clear_cache(self) -> None:
        """Delete everything Craftd can download again. Instances, settings and waitlists stay."""
        cache = self.home / "cache"
        for name in self.CACHE_ITEMS:
            path = cache / name
            if path.is_dir():
                shutil.rmtree(path, ignore_errors=True)
            elif path.is_file():
                path.unlink(missing_ok=True)
        self.cache.hashes.clear()
        self.cache.projects.clear()

    @property
    def _versions_file(self) -> Path:
        return self.home / "cache" / "game_versions.json"

    def _load_cached_versions(self) -> None:
        if self._versions_file.is_file():
            try:
                self.game_versions = json.loads(self._versions_file.read_text(encoding="utf-8"))
                self.order.update(self.game_versions)
            except (OSError, json.JSONDecodeError):
                pass

    def refresh_game_versions(self) -> list[dict]:
        """Fetch the Minecraft version list from Modrinth (falls back to the cached copy offline)."""
        try:
            versions = self.client.game_versions()
        except ModrinthError:
            return self.game_versions
        if versions:
            self.game_versions = versions
            self.order.update(versions)
            self._versions_file.parent.mkdir(parents=True, exist_ok=True)
            self._versions_file.write_text(json.dumps(versions), encoding="utf-8")
        return self.game_versions
