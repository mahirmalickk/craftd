"""Where Craftd keeps its data, and where to look for Prism Launcher instances."""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP_NAME = "Craftd"


def data_dir() -> Path:
    """Craftd's home folder. Override with the CRAFTD_HOME environment variable."""
    override = os.environ.get("CRAFTD_HOME")
    if override:
        path = Path(override).expanduser()
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / APP_NAME
    elif sys.platform.startswith("win"):
        path = Path(os.environ.get("APPDATA", str(Path.home()))) / APP_NAME
    else:
        base = os.environ.get("XDG_DATA_HOME", str(Path.home() / ".local" / "share"))
        path = Path(base) / "craftd"
    if not override:
        _migrate_from_blockn(path)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _migrate_from_blockn(new: Path) -> None:
    """One-time move of data from the app's old name (Blockn) to Craftd."""
    old = new.with_name("blockn" if new.name == "craftd" else "Blockn")
    if new.exists() or not old.is_dir():
        return
    old.rename(new)
    for f in (new / "instances").glob("*/blockn-instance.json"):
        f.rename(f.with_name("craftd-instance.json"))


def prism_instance_dirs(custom: str = "") -> list[Path]:
    """Prism Launcher instance folders that exist on this machine (the one set in Settings first)."""
    home = Path.home()
    candidates: list[Path] = [Path(custom).expanduser()] if custom else []
    if sys.platform == "darwin":
        candidates.append(home / "Library" / "Application Support" / "PrismLauncher" / "instances")
    elif sys.platform.startswith("win"):
        appdata = Path(os.environ.get("APPDATA", str(home)))
        candidates.append(appdata / "PrismLauncher" / "instances")
    else:
        candidates.append(home / ".local" / "share" / "PrismLauncher" / "instances")
        candidates.append(
            home / ".var" / "app" / "org.prismlauncher.PrismLauncher" / "data" / "PrismLauncher" / "instances"
        )
    out: list[Path] = []
    for c in candidates:
        if c.is_dir() and c not in out:
            out.append(c)
    return out
