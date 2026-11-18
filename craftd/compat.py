"""Compatibility check: read what mods declare about each other and about the loader.

Every mod jar carries metadata (fabric.mod.json, quilt.mod.json, neoforge.mods.toml,
mods.toml) that says which Minecraft / loader versions it needs, which mods it
requires, and which versions of other mods it breaks with. Modrinth doesn't expose
those rules, so Craftd reads them from the files themselves.
"""

from __future__ import annotations

import io
import json
import re
import tomllib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

# Mod ids that mean "the loader itself", per loader
LOADER_IDS = {
    "fabric": {"fabricloader", "fabric-loader"},
    "quilt": {"quilt_loader", "quilt-loader"},
    "neoforge": {"neoforge"},
    "forge": {"forge"},
}
ALL_LOADER_IDS = set().union(*LOADER_IDS.values())
LOADER_NAMES = {"fabricloader": "Fabric Loader", "fabric-loader": "Fabric Loader", "quilt_loader": "Quilt Loader",
                "quilt-loader": "Quilt Loader", "neoforge": "NeoForge", "forge": "Forge", "minecraft": "Minecraft"}
ALIASES = {"fabric": "fabric-api"}  # old id for Fabric API
SKIP_IDS = {"java", "mixinextras", "mixinextras.neoforge", "javafml", "lowcodefml"}


# ---- versions ------------------------------------------------------------------------------
def _key(version: str):
    v = version.strip()
    if v[:1] in "vV" and v[1:2].isdigit():
        v = v[1:]
    v = v.split("+", 1)[0]  # build metadata never counts
    main, sep, pre = v.partition("-")
    nums = [int(n) for n in re.findall(r"\d+", main)] or [0]
    while len(nums) > 1 and nums[-1] == 0:  # 1.0 == 1.0.0
        nums.pop()
    if sep:
        parts = tuple((0, int(t), "") if t.isdigit() else (1, 0, t.lower()) for t in re.split(r"[.\-]", pre) if t)
        return (tuple(nums), 0, parts)  # pre-releases sort before the release
    return (tuple(nums), 1, ())


def compare(a: str, b: str) -> int:
    ka, kb = _key(a), _key(b)
    return (ka > kb) - (ka < kb)


_OPS = {
    "=": lambda c: c == 0, ">=": lambda c: c >= 0, "<=": lambda c: c <= 0,
    ">": lambda c: c > 0, "<": lambda c: c < 0,
}


@dataclass
class Pred:
    """Version rule: any of the alternatives, each a list of (op, version) that must all hold."""
    alts: list[list[tuple[str, str]]]
    raw: str = "*"

    def matches(self, version: str | None) -> bool:
        if version is None or not self.alts:
            return True
        return any(all(_OPS[op](compare(version, v)) for op, v in cons) for cons in self.alts)

    @property
    def constrained(self) -> bool:
        return any(self.alts)


ANY = Pred([], "*")


def fabric_predicate(spec) -> Pred:
    """Fabric/Quilt rules: ">=1.2 <2", "~26.3", "^1.4", "1.2.x", "*", or a list meaning OR."""
    specs = spec if isinstance(spec, list) else [spec]
    alts = []
    for s in specs:
        cons: list[tuple[str, str]] = []
        for tok in str(s).split():
            m = re.match(r"(>=|<=|>|<|=|\^|~)?(.*)", tok)
            op, ver = m.group(1) or "", m.group(2)
            if ver in ("*", "", "x", "X"):
                continue
            if re.search(r"\.[xX*]$", ver):
                base = ver[:-2]
                parts = base.split(".")
                cons.append((">=", base))
                if parts[-1].isdigit():
                    cons.append(("<", ".".join(parts[:-1] + [str(int(parts[-1]) + 1)])))
                continue
            nums = re.findall(r"\d+", ver.split("+")[0].split("-")[0])
            if op == "^" and nums:
                cons += [(">=", ver), ("<", str(int(nums[0]) + 1))]
            elif op == "~" and nums:
                upper = f"{nums[0]}.{int(nums[1]) + 1}" if len(nums) > 1 else str(int(nums[0]) + 1)
                cons += [(">=", ver), ("<", upper)]
            else:
                cons.append(("=" if op in ("", "=") else op, ver))
        alts.append(cons)
    if any(not c for c in alts):  # an alternative with no limits accepts everything
        return Pred([], " || ".join(map(str, specs)))
    return Pred(alts, " || ".join(map(str, specs)))


def maven_predicate(spec: str) -> Pred:
    """NeoForge/Forge rules: "[26.3.0.65,)", "[1.0,2.0)", "(,1.12.0]", several = OR; bare "1.0" = at least."""
    spec = (spec or "").strip()
    if spec in ("", "*"):
        return ANY
    ranges = re.findall(r"[\[(][^\])]*[\])]", spec)
    if not ranges:
        return Pred([[(">=", spec)]], spec)
    alts = []
    for r in ranges:
        inner = r[1:-1]
        if "," not in inner:
            alts.append([("=", inner.strip())])
            continue
        lo, hi = (x.strip() for x in inner.split(",", 1))
        cons = []
        if lo:
            cons.append((">=" if r[0] == "[" else ">", lo))
        if hi:
            cons.append(("<=" if r[-1] == "]" else "<", hi))
        alts.append(cons)
    return Pred(alts, spec)


def describe(pred: Pred) -> str:
    """Plain-English version of a rule, e.g. '26.3.0.65 or newer'."""
    if not pred.constrained:
        return "any version"
    words = []
    for cons in pred.alts:
        part = []
        for op, v in cons:
            part.append({"=": f"exactly {v}", ">=": f"{v} or newer", ">": f"newer than {v}",
                         "<=": f"{v} or older", "<": f"older than {v}"}[op])
        words.append(" and ".join(part))
    return " or ".join(words)


# ---- reading jar metadata --------------------------------------------------------------------
@dataclass
class Dep:
    mod_id: str
    kind: str  # required | optional | breaks | conflicts
    pred: Pred


@dataclass
class ModMeta:
    mod_id: str
    name: str
    version: str
    file: str  # the top-level jar in the mods folder
    platform: str  # fabric | quilt | neoforge | forge
    provides: set[str] = field(default_factory=set)
    deps: list[Dep] = field(default_factory=list)
    nested: bool = False


def _manifest_version(zf: zipfile.ZipFile) -> str | None:
    try:
        for line in zf.read("META-INF/MANIFEST.MF").decode("utf-8", "replace").splitlines():
            if line.startswith("Implementation-Version:"):
                return line.split(":", 1)[1].strip()
    except KeyError:
        pass
    return None


def _fabric(data: dict, file: str, nested: bool, platform: str = "fabric") -> list[ModMeta]:
    meta = ModMeta(mod_id=str(data.get("id", "")), name=str(data.get("name") or data.get("id", "")),
                   version=str(data.get("version", "0")), file=file, platform=platform, nested=nested,
                   provides=set(data.get("provides") or []))
    for key, kind in (("depends", "required"), ("breaks", "breaks"), ("conflicts", "conflicts")):
        for mid, spec in (data.get(key) or {}).items():
            meta.deps.append(Dep(mid, kind, fabric_predicate(spec)))
    return [meta]


def _quilt(data: dict, file: str, nested: bool) -> list[ModMeta]:
    ql = data.get("quilt_loader", {})
    meta = ModMeta(mod_id=str(ql.get("id", "")), name=str(ql.get("metadata", {}).get("name") or ql.get("id", "")),
                   version=str(ql.get("version", "0")), file=file, platform="quilt", nested=nested)
    for p in ql.get("provides") or []:
        meta.provides.add(p if isinstance(p, str) else p.get("id", ""))
    for key, kind in (("depends", "required"), ("breaks", "breaks")):
        for d in ql.get(key) or []:
            if isinstance(d, str):
                meta.deps.append(Dep(d, kind, ANY))
            elif isinstance(d, dict) and d.get("id"):
                versions = d.get("versions", "*")
                pred = fabric_predicate(versions) if isinstance(versions, (str, list)) else ANY
                k = "optional" if kind == "required" and d.get("optional") else kind
                meta.deps.append(Dep(d["id"], k, pred))
    return [meta]


def _toml(data: dict, file: str, nested: bool, platform: str, jar_version: str | None) -> list[ModMeta]:
    out = []
    deps_table = data.get("dependencies") or {}
    for m in data.get("mods") or []:
        mid = str(m.get("modId", ""))
        version = str(m.get("version", "0"))
        if "${" in version:
            version = jar_version or "0"
        meta = ModMeta(mod_id=mid, name=str(m.get("displayName") or mid), version=version, file=file,
                       platform=platform, nested=nested)
        for d in deps_table.get(mid) or []:
            if str(d.get("side", "BOTH")).upper() == "SERVER":
                continue
            dtype = str(d.get("type", "")).lower()
            if not dtype:
                dtype = "required" if d.get("mandatory", False) else "optional"
            kind = {"required": "required", "optional": "optional", "incompatible": "breaks",
                    "discouraged": "conflicts"}.get(dtype, "optional")
            meta.deps.append(Dep(str(d.get("modId", "")), kind, maven_predicate(str(d.get("versionRange", "")))))
        out.append(meta)
    return out


PLATFORM_FILES = {
    "neoforge": ["META-INF/neoforge.mods.toml", "META-INF/mods.toml"],
    "forge": ["META-INF/mods.toml"],
    "fabric": ["fabric.mod.json"],
    "quilt": ["quilt.mod.json", "fabric.mod.json"],
}


# Where each loader looks for bundled mods when a jar doesn't list them explicitly
NESTED_DIRS = {"fabric": ("META-INF/jars/",), "quilt": ("META-INF/jars/",),
               "neoforge": ("META-INF/jarjar/",), "forge": ("META-INF/jarjar/",)}


def _nested_paths(zf: zipfile.ZipFile, names: set[str], loader: str) -> list[str]:
    """The bundled jars this loader will actually load, from the jar's own list when it has one.

    NeoForge reads META-INF/jarjar/metadata.json, whose paths can point anywhere (multi-loader mods
    like LambDynamicLights keep them in META-INF/jars/). Fabric reads "jars" in fabric.mod.json.
    """
    try:
        if loader in ("neoforge", "forge") and "META-INF/jarjar/metadata.json" in names:
            data = json.loads(zf.read("META-INF/jarjar/metadata.json").decode("utf-8", "replace"), strict=False)
            return [j["path"] for j in data.get("jars", []) if isinstance(j, dict) and j.get("path")]
        if loader in ("fabric", "quilt") and "fabric.mod.json" in names:
            data = json.loads(zf.read("fabric.mod.json").decode("utf-8", "replace"), strict=False)
            listed = [j.get("file") for j in data.get("jars") or [] if isinstance(j, dict) and j.get("file")]
            if listed or "jars" in data:
                return listed
        if loader == "quilt" and "quilt.mod.json" in names:
            data = json.loads(zf.read("quilt.mod.json").decode("utf-8", "replace"), strict=False)
            listed = [j if isinstance(j, str) else j.get("file", "") for j in data.get("quilt_loader", {}).get("jars") or []]
            if listed:
                return [x for x in listed if x]
    except (ValueError, KeyError):
        pass
    return [n for n in names if n.endswith(".jar") and n.startswith(NESTED_DIRS.get(loader, ()))]


def _read_zip(zf: zipfile.ZipFile, file: str, loader: str, nested: bool, depth: int) -> list[ModMeta]:
    names = set(zf.namelist())
    metas: list[ModMeta] = []
    own = [e for e in PLATFORM_FILES.get(loader, []) if e in names]
    if nested and not own:
        return []  # bundled for another loader (or a plain library): this loader never loads it
    # Top-level jars without metadata for this loader are still read, so a Fabric-only mod in a
    # NeoForge instance gets reported.
    order = own or [n for files in PLATFORM_FILES.values() for n in files]
    for entry in dict.fromkeys(order):  # first metadata file that fits the loader wins
        if entry not in names:
            continue
        try:
            raw = zf.read(entry).decode("utf-8", "replace")
            if entry == "fabric.mod.json":
                metas = _fabric(json.loads(raw, strict=False), file, nested)
            elif entry == "quilt.mod.json":
                metas = _quilt(json.loads(raw, strict=False), file, nested)
            else:
                plat = "neoforge" if "neoforge" in entry else ("neoforge" if loader == "neoforge" else "forge")
                metas = _toml(tomllib.loads(raw), file, nested, plat, _manifest_version(zf))
        except (ValueError, tomllib.TOMLDecodeError, KeyError):
            metas = []
        break
    if own and depth < 3:  # mods bundled inside this jar (jar-in-jar) count as installed too
        for inner in _nested_paths(zf, names, loader):
            if inner in names:
                try:
                    with zipfile.ZipFile(io.BytesIO(zf.read(inner))) as nz:
                        metas += _read_zip(nz, file, loader, True, depth + 1)
                except (zipfile.BadZipFile, KeyError):
                    continue
    return metas


def read_mods(path: Path, loader: str) -> list[ModMeta]:
    """All mods inside one jar (including bundled ones), read with the instance's loader in mind."""
    try:
        with zipfile.ZipFile(path) as zf:
            return _read_zip(zf, path.name, loader, False, 0)
    except (zipfile.BadZipFile, OSError):
        return []


# ---- checking ------------------------------------------------------------------------------
@dataclass
class Issue:
    severity: str  # "error" (won't start / will crash) or "warning"
    mod: str  # display name of the mod with the problem
    file: str  # its jar in the mods folder
    message: str
    fix: str | None = None


def environment(game_version: str, loader: str, loader_version: str | None) -> dict[str, str | None]:
    env: dict[str, str | None] = {"minecraft": game_version}
    for lid in LOADER_IDS.get(loader, set()):
        env[lid] = loader_version
    return env


def _loader_of(mod_id: str) -> str | None:
    return next((l for l, ids in LOADER_IDS.items() if mod_id in ids), None)


def check(metas: list[ModMeta], game_version: str, loader: str, loader_version: str | None,
          loader_label: str, known_loaded: dict[str, str] | None = None) -> list[Issue]:
    """known_loaded: mod id -> version seen in the last successful game start (a safety net
    for mods bundled in ways Craftd can't see)."""
    env = environment(game_version, loader, loader_version)
    installed: dict[str, ModMeta] = {}
    for mid, ver in (known_loaded or {}).items():
        installed.setdefault(mid, ModMeta(mod_id=mid, name=mid, version=ver, file="", platform=loader, nested=True))
    for m in metas:
        installed.setdefault(m.mod_id, m)
        for p in m.provides:
            installed.setdefault(p, m)
    issues: list[Issue] = []
    seen: set[tuple[str, str]] = set()

    def add(sev, meta, msg, fix=None):
        key = (meta.file, msg)
        if key not in seen:
            seen.add(key)
            top = next((x for x in metas if x.file == meta.file and not x.nested), meta)
            name = meta.name if not meta.nested else f"{meta.name} (inside {top.name})"
            issues.append(Issue(sev, name, meta.file, msg, fix))

    for meta in metas:
        for dep in meta.deps:  # (log-only entries have no deps, so they're never reported)
            did = ALIASES.get(dep.mod_id, dep.mod_id)
            if did in SKIP_IDS or not did:
                continue
            if did in env:  # Minecraft or the loader itself
                have = env[did]
                label = "Minecraft" if did == "minecraft" else loader_label
                if have is None:
                    continue
                if dep.kind in ("required", "optional") and not dep.pred.matches(have):
                    fix = (f"Install a build of {meta.name} made for Minecraft {game_version}." if did == "minecraft" else
                           f"Use a different build of {meta.name}, or change the {label} version in Prism "
                           f"(Edit → Version).")
                    add("error", meta, f"Needs {label} {describe(dep.pred)}, but this instance has {label} {have}.", fix)
                elif dep.kind == "breaks" and dep.pred.matches(have):
                    add("error", meta, f"Doesn't work with {label} {have}.",
                        f"Use a different build of {meta.name}, or change the {label} version in Prism.")
                continue
            other_loader = _loader_of(did)
            if other_loader and other_loader != loader:
                if dep.kind == "required" and not (loader == "quilt" and other_loader == "fabric"):
                    add("error", meta, f"This is a {LOADER_NAMES.get(did, did)} mod, but this instance uses {loader_label}.",
                        f"Remove it, or install the {loader_label} build of {meta.name} if one exists.")
                continue
            other = installed.get(did)
            if dep.kind == "required":
                if other is None:
                    add("error", meta, f"Needs “{did}”, which isn't installed.",
                        f"Search Modrinth for “{did}” (Mods → Add from Modrinth).")
                elif not dep.pred.matches(other.version):
                    add("error", meta, f"Needs {other.name} {describe(dep.pred)}, but {other.version} is installed.",
                        f"Install a matching version of {other.name}.")
            elif dep.kind == "optional" and other and dep.pred.constrained and not dep.pred.matches(other.version):
                add("error", meta, f"Only works with {other.name} {describe(dep.pred)}, but {other.version} is installed.",
                    f"Update or change the version of {other.name}.")
            elif dep.kind == "breaks" and other and dep.pred.matches(other.version):
                add("error", meta, f"Doesn't work with {other.name} {other.version} "
                                   f"(it breaks with {describe(dep.pred)}).",
                    f"Use a different version of {other.name} or {meta.name}, or remove one of them.")
            elif dep.kind == "conflicts" and other and dep.pred.matches(other.version):
                add("warning", meta, f"May cause problems with {other.name} {other.version}.",
                    f"If you see glitches or crashes, try removing {other.name}.")
    return sorted(issues, key=lambda i: (i.severity != "error", i.mod.lower()))


def check_files(files: list[Path], game_version: str, loader: str, loader_version: str | None,
                loader_label: str, known_loaded: dict[str, str] | None = None) -> list[Issue]:
    metas: list[ModMeta] = []
    for f in files:
        metas += read_mods(f, loader)
    return check(metas, game_version, loader, loader_version, loader_label, known_loaded)


def loaded_in_last_good_start(log: Path) -> dict[str, str]:
    """Mods the game actually loaded last time, if that start succeeded (from logs/latest.log)."""
    from .crash import LOG_FAILURE_MARKERS
    try:
        text = log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    if any(m in text for m in LOG_FAILURE_MARKERS):
        return {}
    found: dict[str, str] = {}
    for m in re.finditer(r"^\s+(.+?) (\S+) \(([a-z0-9_.\-]+)\)\s*$", text, re.M):  # NeoForge "Mod List:"
        found.setdefault(m.group(3), m.group(2))
    for m in re.finditer(r"^\s+- ([a-z0-9_.\-]+) (\S+)\s*$", text, re.M):  # Fabric "Loading N mods:"
        found.setdefault(m.group(1), m.group(2))
    for m in re.finditer(r"^\s+\|-- ([a-z0-9_.\-]+) (\S+)\s*$", text, re.M):  # Fabric bundled mods
        found.setdefault(m.group(1), m.group(2))
    return found


def fits_environment(path: Path, game_version: str, loader: str, loader_version: str | None,
                     loader_label: str) -> list[Issue]:
    """Problems a single jar has with Minecraft/the loader itself (ignores other mods)."""
    metas = [m for m in read_mods(path, loader) if not m.nested]
    issues = check(metas, game_version, loader, loader_version, loader_label)
    return [i for i in issues if i.message.startswith(("Needs Minecraft", f"Needs {loader_label}", "Doesn't work with "
                                                       + loader_label, "This is a"))]
