"""Ordering Minecraft versions (1.21.4, 26.1, 26.2, snapshots...)."""

from __future__ import annotations

import re


def numeric_key(version: str) -> tuple[int, ...]:
    """'26.2' -> (26, 2); '1.21.4' -> (1, 21, 4). Year-based versions sort after 1.x."""
    return tuple(int(n) for n in re.findall(r"\d+", version)) or (0,)


class VersionOrder:
    """Sorts versions by Modrinth release date when known, falling back to the numbers."""

    def __init__(self, game_versions: list[dict] | None = None):
        self.dates: dict[str, str] = {}
        self.update(game_versions or [])

    def update(self, game_versions: list[dict]) -> None:
        for gv in game_versions:
            if gv.get("version"):
                self.dates[gv["version"]] = gv.get("date", "")

    def key(self, version: str):
        return (self.dates.get(version, ""), numeric_key(version))

    def newer(self, a: str, b: str) -> bool:
        """True when a is newer than b."""
        if a in self.dates and b in self.dates:
            return self.dates[a] > self.dates[b]
        return numeric_key(a) > numeric_key(b)
