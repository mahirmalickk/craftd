"""User preferences, saved as settings.json in Craftd's data folder.

The font isn't a setting: Craftd always uses Monocraft, a Minecraft-style pixel font."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict, dataclass, fields
from pathlib import Path

SYSTEM_THEME_LABEL = "Match Windows" if sys.platform.startswith("win") else "Match system"
SYSTEM_THEME_WHERE = {  # where the OS's own light/dark switch lives
    "win": "Settings → Personalization → Colors",
    "darwin": "System Settings → Appearance",
}.get("win" if sys.platform.startswith("win") else sys.platform, "your system's appearance setting")
THEMES = {"system": SYSTEM_THEME_LABEL, "light": "Light (Iron)", "dark": "Dark (Netherite)"}
TEXT_SIZES = {1.0: "Default", 1.5: "Large"}
PROXY_MODES = {"system": "Use system settings", "none": "None", "http": "HTTP proxy"}


@dataclass
class Settings:
    # Appearance
    theme: str = "system"  # "system", "light" or "dark"
    text_scale: float = 1.0
    # General
    check_waitlist_on_start: bool = True
    prism_folder: str = ""  # "" = find Prism's instances folder automatically
    multimc_folder: str = ""  # MultiMC is portable, so this is set by the user (Settings or Import from MultiMC)
    # Mods
    stable_first: bool = True  # pick full releases over betas when both exist
    auto_dependencies: bool = True
    hide_installed: bool = True  # in Add from Modrinth
    # Carry Over defaults
    carry_copy_local: bool = False
    carry_packs: bool = True
    carry_config: bool = True
    carry_options_servers: bool = True  # only ever when the new instance has none yet
    # Network
    proxy: str = "system"
    proxy_host: str = ""
    proxy_port: int = 8080
    timeout: int = 20  # seconds

    @classmethod
    def load(cls, home: Path) -> "Settings":
        try:
            data = json.loads((home / "settings.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls()
        if not isinstance(data, dict):
            return cls()
        s = cls()
        for f in fields(cls):  # keep only known keys of the right type; older files just lack the new ones
            value = data.get(f.name)
            default = getattr(s, f.name)
            if isinstance(default, bool):
                if isinstance(value, bool):
                    setattr(s, f.name, value)
            elif isinstance(default, (int, float)):
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    setattr(s, f.name, type(default)(value))
            elif isinstance(value, str):
                setattr(s, f.name, value)
        if s.theme not in THEMES:
            s.theme = "system"
        s.text_scale = 1.5 if s.text_scale >= 1.15 else 1.0  # older versions had more steps
        if s.proxy not in PROXY_MODES:
            s.proxy = "system"
        s.proxy_port = min(max(s.proxy_port, 1), 65535)
        s.timeout = min(max(s.timeout, 5), 120)
        return s

    def save(self, home: Path) -> None:
        (home / "settings.json").write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
