"""In-memory stand-in for the Modrinth API, with real (tiny) jar files."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

from craftd.modrinth import ModrinthError


def make_jar(mod_id: str, name: str, version: str, loader: str = "fabric") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        info = zipfile.ZipInfo("fabric.mod.json" if loader in ("fabric", "quilt") else "META-INF/mods.toml",
                               date_time=(2026, 1, 1, 0, 0, 0))
        if loader in ("fabric", "quilt"):
            zf.writestr(info, json.dumps({"schemaVersion": 1, "id": mod_id, "name": name, "version": version}))
        else:
            zf.writestr(info, f'modLoader="javafml"\n[[mods]]\nmodId="{mod_id}"\ndisplayName="{name}"\nversion="{version}"\n')
    return buf.getvalue()


class FakeModrinth:
    def __init__(self):
        self.projects_db: dict[str, dict] = {}
        self.versions: list[dict] = []
        self.blobs: dict[str, bytes] = {}
        self.calls: list[str] = []
        self.online = True
        self._tick = 0
        self.game_versions_list = [
            {"version": v, "version_type": "release", "date": d, "major": False}
            for v, d in [("26.3", "2026-10-01"), ("26.2", "2026-07-01"), ("26.1", "2026-03-01"), ("1.21.11", "2025-12-01")]
        ]

    # ---- building the fake catalogue -------------------------------------------------
    def add_version(self, pid: str, title: str, number: str, game_versions: list[str], loaders: list[str],
                    deps: tuple = (), version_type: str = "release", categories: tuple = (),
                    content: bytes | None = None) -> tuple[dict, bytes]:
        proj = self.projects_db.setdefault(pid, {"id": pid, "title": title, "slug": pid, "icon_url": None,
                                                 "loaders": [], "categories": [], "description": f"{title} mod",
                                                 "body": f"# {title}\n\nA **great** mod.", "gallery": [],
                                                 "downloads": 1000, "follows": 10, "team": "dev"})
        proj["loaders"] = sorted(set(proj["loaders"]) | set(loaders))
        proj["categories"] = sorted(set(proj["categories"]) | set(categories))
        self._tick += 1
        content = content if content is not None else make_jar(pid, title, number, loaders[0])
        sha1 = hashlib.sha1(content).hexdigest()
        url = f"https://cdn.fake/{pid}/{number}.jar"
        self.blobs[url] = content
        version = {
            "id": f"{pid}-{number}",
            "project_id": pid,
            "version_number": number,
            "game_versions": game_versions,
            "loaders": loaders,
            "version_type": version_type,
            "date_published": f"2026-01-01T00:00:{self._tick:02d}Z",
            "dependencies": [
                {"project_id": d[0], "version_id": d[1], "dependency_type": "required"} if isinstance(d, tuple)
                else {"project_id": d, "version_id": None, "dependency_type": "required"} for d in deps],
            "files": [{"url": url, "filename": f"{pid}-{number}.jar", "hashes": {"sha1": sha1}, "primary": True}],
        }
        self.versions.append(version)
        return version, content

    def place(self, version: dict, mods_dir: Path) -> Path:
        """Put a version's jar in a mods folder, as if it had been installed earlier."""
        f = version["files"][0]
        mods_dir.mkdir(parents=True, exist_ok=True)
        dest = mods_dir / f["filename"]
        dest.write_bytes(self.blobs[f["url"]])
        return dest

    # ---- API surface used by Craftd ----------------------------------------------------
    def _check(self, name):
        self.calls.append(name)
        if not self.online:
            raise ModrinthError("offline")

    def _by_hash(self) -> dict[str, dict]:
        return {v["files"][0]["hashes"]["sha1"]: v for v in self.versions}

    def _newest(self, pid, loaders, gvs):
        matches = [v for v in self.versions if v["project_id"] == pid
                   and set(v["loaders"]) & set(loaders) and set(v["game_versions"]) & set(gvs)]
        return sorted(matches, key=lambda v: v["date_published"], reverse=True)

    def game_versions(self):
        self._check("game_versions")
        return self.game_versions_list

    def versions_from_hashes(self, sha1s):
        self._check("versions_from_hashes")
        idx = self._by_hash()
        return {h: idx[h] for h in sha1s if h in idx}

    def latest_versions_for(self, sha1s, loaders, game_versions):
        self._check("latest_versions_for")
        idx, out = self._by_hash(), {}
        for h in sha1s:
            if h in idx:
                newest = self._newest(idx[h]["project_id"], loaders, game_versions)
                if newest:
                    out[h] = newest[0]
        return out

    def projects(self, ids):
        self._check("projects")
        return [self.projects_db[i] for i in ids if i in self.projects_db]

    def version(self, version_id):
        self._check("version")
        return next((v for v in self.versions if v["id"] == version_id), None)

    def project_versions(self, project_id, loaders, game_versions):
        self._check("project_versions")
        return self._newest(project_id, loaders, game_versions)

    def project(self, project_id):
        self._check("project")
        return self.projects_db.get(project_id)

    def search(self, query, loaders, game_version, limit=30, offset=0, index=None, category=None):
        self._check("search")
        self.last_search = {"query": query, "index": index, "category": category, "offset": offset}
        hits = []
        for pid, p in self.projects_db.items():
            if category and category not in p["categories"]:
                continue
            if query.lower() in p["title"].lower() and self._newest(pid, loaders, [game_version]):
                hits.append({"project_id": pid, "slug": pid, "title": p["title"], "author": "dev",
                             "downloads": p["downloads"], "follows": p["follows"], "description": p["description"],
                             "icon_url": None, "display_categories": p["categories"],
                             "date_modified": "2026-11-10T00:00:00Z"})
        return {"hits": hits[offset: offset + limit], "total_hits": len(hits)}

    def download(self, url, dest: Path, expected_sha1=None, progress=None):
        self._check("download")
        data = self.blobs[url]
        if expected_sha1 and hashlib.sha1(data).hexdigest() != expected_sha1:
            raise ModrinthError("Checksum mismatch")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest
