"""Build small mod jars with real-looking metadata for compatibility tests."""

import io
import json
import zipfile
from pathlib import Path


def _zip(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0)), data)
    return buf.getvalue()


def fabric_jar(mod_id, version, depends=None, breaks=None, provides=None, nested=()):
    meta = {"schemaVersion": 1, "id": mod_id, "name": mod_id.title(), "version": version,
            "depends": depends or {}, "breaks": breaks or {}, "provides": provides or [],
            "jars": [{"file": f"META-INF/jars/{n}.jar"} for n, _ in nested]}
    entries = {"fabric.mod.json": json.dumps(meta).encode()}
    for name, data in nested:
        entries[f"META-INF/jars/{name}.jar"] = data
    return _zip(entries)


def neoforge_jar(mod_id, version, deps=(), extra_fabric=None, fabric_nested=(), neo_nested=(), jarjar_list=None):
    lines = ['modLoader="javafml"', 'loaderVersion="[1,)"', "[[mods]]", f'modId="{mod_id}"',
             f'version="{version}"', f'displayName="{mod_id.title()}"']
    for dep_id, dtype, rng in deps:
        lines += [f"[[dependencies.{mod_id}]]", f'modId="{dep_id}"', f'type="{dtype}"', f'versionRange="{rng}"']
    entries = {"META-INF/neoforge.mods.toml": "\n".join(lines).encode()}
    if extra_fabric:  # multi-loader jar
        entries["fabric.mod.json"] = json.dumps(extra_fabric).encode()
    for name, data in fabric_nested:  # bundled pieces only Fabric loads
        entries[f"META-INF/jars/{name}.jar"] = data
    for name, data in neo_nested:  # bundled pieces only NeoForge loads
        entries[f"META-INF/jarjar/{name}.jar"] = data
    if jarjar_list is not None:  # NeoForge's own list of what to load, which may point anywhere
        entries["META-INF/jarjar/metadata.json"] = json.dumps(
            {"jars": [{"identifier": {"group": "x", "artifact": p}, "path": p} for p in jarjar_list]}).encode()
    return _zip(entries)


def write(folder: Path, name: str, data: bytes) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / name
    path.write_bytes(data)
    return path
