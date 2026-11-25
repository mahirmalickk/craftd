"""Small Modrinth API v2 client.

Docs: https://docs.modrinth.com/api/
Modrinth asks every client to send a unique User-Agent that identifies the app.
"""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Callable, Iterable

import requests

from . import __version__

API_BASE = "https://api.modrinth.com/v2"
USER_AGENT = f"mahirmalickk/craftd/{__version__} (github.com/mahirmalickk)"
HASH_BATCH = 100  # keep request bodies a sensible size


class ModrinthError(Exception):
    """Any failure talking to Modrinth (network down, bad response, rate limited)."""


def _chunks(items: list[str], size: int) -> Iterable[list[str]]:
    for i in range(0, len(items), size):
        yield items[i : i + size]


def apply_proxy(session: requests.Session, proxy: str = "system", host: str = "", port: int = 8080) -> None:
    """Settings → Network for any session (Modrinth, sign-in): "system", "none", or "http" (host:port)."""
    session.proxies.clear()
    if proxy == "http" and host:
        url = host if "://" in host else f"http://{host}"
        url = f"{url}:{port}" if url.count(":") < 2 else url
        session.proxies.update({"http": url, "https": url})
        session.trust_env = False  # the proxy set here wins over environment variables
    else:
        session.trust_env = proxy != "none"


class ModrinthClient:
    def __init__(self, session: requests.Session | None = None, base_url: str = API_BASE, timeout: float = 20):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})

    def configure_network(self, proxy: str = "system", host: str = "", port: int = 8080, timeout: float = 20) -> None:
        """proxy: "system" (Windows/macOS proxy settings), "none", or "http" (host:port)."""
        self.timeout = timeout
        apply_proxy(self.session, proxy, host, port)

    def ping(self) -> str:
        """A tiny request to check that Modrinth can be reached with the current network settings."""
        loaders = self._request("GET", "/tag/loader", attempts=1) or []
        return f"Connected to Modrinth ({len(loaders)} mod loaders listed)."

    # ---- low level -------------------------------------------------------
    def _request(self, method: str, path: str, *, params=None, body=None, attempts: int = 3):
        url = f"{self.base_url}{path}"
        for attempt in range(attempts):
            try:
                resp = self.session.request(method, url, params=params, json=body, timeout=self.timeout)
            except requests.RequestException as exc:
                if attempt == attempts - 1:
                    raise ModrinthError(f"Could not reach Modrinth: {exc}") from exc
                time.sleep(1 + attempt)
                continue
            if resp.status_code == 429:  # rate limited: wait for the window to reset
                wait = float(resp.headers.get("X-Ratelimit-Reset", "5"))
                time.sleep(min(max(wait, 1), 30))
                continue
            if resp.status_code == 404:
                return None
            if resp.status_code >= 400:
                raise ModrinthError(f"Modrinth returned {resp.status_code} for {path}: {resp.text[:200]}")
            if resp.status_code == 204 or not resp.content:
                return None
            return resp.json()
        raise ModrinthError(f"Gave up on {path} after {attempts} attempts")

    # ---- tags -------------------------------------------------------------
    def game_versions(self) -> list[dict]:
        """All Minecraft versions, newest first: [{version, version_type, date, major}]."""
        data = self._request("GET", "/tag/game_version") or []
        return sorted(data, key=lambda v: v.get("date", ""), reverse=True)

    # ---- hash lookups (the heart of mod detection) -------------------------
    def versions_from_hashes(self, sha1s: list[str]) -> dict[str, dict]:
        """Identify jar files. Returns {sha1: version} for files Modrinth knows."""
        found: dict[str, dict] = {}
        for batch in _chunks(sorted(set(sha1s)), HASH_BATCH):
            found.update(self._request("POST", "/version_files", body={"hashes": batch, "algorithm": "sha1"}) or {})
        return found

    def latest_versions_for(self, sha1s: list[str], loaders: list[str], game_versions: list[str]) -> dict[str, dict]:
        """For each file hash, the newest version of *that project* that fits the loaders/game versions.

        A hash missing from the result means the project has no build for that target yet.
        """
        found: dict[str, dict] = {}
        for batch in _chunks(sorted(set(sha1s)), HASH_BATCH):
            body = {"hashes": batch, "algorithm": "sha1", "loaders": loaders, "game_versions": game_versions}
            found.update(self._request("POST", "/version_files/update", body=body) or {})
        return found

    # ---- projects / versions ----------------------------------------------
    def projects(self, ids: list[str]) -> list[dict]:
        out: list[dict] = []
        for batch in _chunks(sorted(set(ids)), HASH_BATCH):
            out.extend(self._request("GET", "/projects", params={"ids": json.dumps(batch)}) or [])
        return out

    def version(self, version_id: str) -> dict | None:
        return self._request("GET", f"/version/{version_id}")

    def project_versions(self, project_id: str, loaders: list[str] | None = None,
                         game_versions: list[str] | None = None) -> list[dict]:
        """Versions of a project for a target (or all of them), newest first."""
        params = {}
        if loaders:
            params["loaders"] = json.dumps(loaders)
        if game_versions:
            params["game_versions"] = json.dumps(game_versions)
        data = self._request("GET", f"/project/{project_id}/version", params=params) or []
        return sorted(data, key=lambda v: v.get("date_published", ""), reverse=True)

    def project(self, project_id: str) -> dict | None:
        """Full project page: body (markdown), gallery, links, loaders..."""
        return self._request("GET", f"/project/{project_id}")

    def search(self, query: str, loaders: list[str], game_version: str | None, limit: int = 30, offset: int = 0,
               index: str | None = None, category: str | None = None, project_type: str = "mod") -> dict:
        """index: relevance, downloads, follows, newest or updated. project_type: mod or modpack."""
        facets = [[f"project_type:{project_type}"]]
        if game_version:
            facets.append([f"versions:{game_version}"])
        if loaders:
            facets.append([f"categories:{l}" for l in loaders])
        if category:
            facets.append([f"categories:{category}"])
        params = {
            "query": query,
            "facets": json.dumps(facets),
            "limit": limit,
            "offset": offset,
            "index": index or ("relevance" if query else "downloads"),
        }
        return self._request("GET", "/search", params=params) or {"hits": [], "total_hits": 0}

    # ---- downloads ----------------------------------------------------------
    def download(self, url: str, dest: Path, expected_sha1: str | None = None,
                 progress: Callable[[int, int], None] | None = None) -> Path:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".part")
        sha1 = hashlib.sha1()
        try:
            with self.session.get(url, stream=True, timeout=self.timeout) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("Content-Length", 0))
                done = 0
                with open(tmp, "wb") as fh:
                    for chunk in resp.iter_content(65536):
                        fh.write(chunk)
                        sha1.update(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)
        except requests.RequestException as exc:
            tmp.unlink(missing_ok=True)
            raise ModrinthError(f"Download failed: {exc}") from exc
        if expected_sha1 and sha1.hexdigest() != expected_sha1:
            tmp.unlink(missing_ok=True)
            raise ModrinthError(f"Checksum mismatch for {dest.name}; the download was discarded")
        tmp.replace(dest)
        return dest


def primary_file(version: dict) -> dict:
    """The main .jar of a Modrinth version."""
    files = version.get("files") or []
    if not files:
        raise ModrinthError(f"Version {version.get('id')} has no files")
    return next((f for f in files if f.get("primary")), files[0])
