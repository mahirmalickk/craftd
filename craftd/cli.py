"""Command-line access to Craftd's engine.

    python -m craftd.cli list
    python -m craftd.cli create "Survival 26.3" 26.3 fabric
    python -m craftd.cli link-prism                 # link every Prism instance found
    python -m craftd.cli detect <target> [--from <source>]
    python -m craftd.cli carry  <target> [--from <source>] [--yes] [--copy-local]
    python -m craftd.cli waitlist <target>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import Craftd
from .instances import Instance
from .paths import prism_instance_dirs
from .sync import STATUS_LABELS, Status


def _find(app: Craftd, ref: str) -> Instance:
    instances = app.manager.list()
    for inst in instances:
        if ref in (inst.id, inst.name):
            return inst
    matches = [i for i in instances if ref.lower() in i.name.lower()]
    if len(matches) == 1:
        return matches[0]
    sys.exit(f"No single instance matches '{ref}'. Run `list` to see ids.")


def _sources(app: Craftd, target: Instance, ref: str | None) -> list[Instance]:
    if ref == "all":
        return [i for i in app.manager.list() if i.id != target.id]
    if ref:
        return [_find(app, ref)]
    suggested = app.carry.suggest_source(target, app.manager.list())
    if not suggested:
        sys.exit("No other instance with mods to carry over from.")
    print(f"Source: {suggested.name} ({suggested.summary}) — auto-detected")
    return [suggested]


def main(argv: list[str] | None = None, app: Craftd | None = None) -> int:
    p = argparse.ArgumentParser(prog="craftd")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    c = sub.add_parser("create")
    c.add_argument("name"); c.add_argument("game_version"); c.add_argument("loader")
    lp = sub.add_parser("link-prism")
    lp.add_argument("path", nargs="?", help="a Prism instances folder, or one instance folder")
    for name in ("detect", "carry"):
        s = sub.add_parser(name)
        s.add_argument("target")
        s.add_argument("--from", dest="source", help="instance id/name, or 'all'")
        if name == "carry":
            s.add_argument("--yes", action="store_true", help="don't ask for confirmation")
            s.add_argument("--copy-local", action="store_true", help="also copy jars that aren't on Modrinth")
    w = sub.add_parser("waitlist")
    w.add_argument("target")
    w.add_argument("--install", action="store_true")
    args = p.parse_args(argv)

    app = app or Craftd()
    app.refresh_game_versions()

    if args.cmd == "list":
        for inst in app.manager.list():
            tag = " [Prism]" if inst.kind == "prism" else ""
            print(f"{inst.id:28} {inst.name:28} {inst.summary}{tag}")
        return 0

    if args.cmd == "create":
        inst = app.manager.create(args.name, args.game_version, args.loader.lower())
        print(f"Created {inst.name} ({inst.summary}) at {inst.root}")
        return 0

    if args.cmd == "link-prism":
        roots = [Path(args.path).expanduser()] if args.path else prism_instance_dirs()
        linked = 0
        for root in roots:
            if (root / "mmc-pack.json").is_file():
                inst = app.manager.link_prism(root)
                print(f"Linked {inst.name} ({inst.summary})"); linked += 1
                continue
            for path, info in app.manager.discover_prism(root):
                inst = app.manager.link_prism(path)
                print(f"Linked {inst.name} ({inst.summary})"); linked += 1
        print(f"{linked} instance(s) linked." if linked else "No new Prism instances found.")
        return 0

    target = _find(app, args.target)

    if args.cmd == "waitlist":
        ready = app.carry.check_waitlist(target)
        for e in app.carry.waitlist(target):
            flag = "READY" if any(r.project_id == e["project_id"] for r in ready) else "waiting"
            print(f"  [{flag:7}] {e['title']}")
        if ready and args.install:
            print(app.carry.install_from_waitlist(target, ready, print).summary())
        return 0

    sources = _sources(app, target, args.source)
    cands = app.carry.detect(target, sources, progress=print)
    print(f"\nMods for {target.name} ({target.summary}):")
    for c in cands:
        ver = f" → {c.target_version_number}" if c.status == Status.AVAILABLE else ""
        print(f"  [{STATUS_LABELS[c.status]:17}] {c.title}{ver}   (from {', '.join(c.sources)})")

    if args.cmd == "carry":
        chosen = [c for c in cands if c.status in (Status.AVAILABLE, Status.UNAVAILABLE)
                  or (args.copy_local and c.status == Status.LOCAL)]
        if not chosen:
            print("\nNothing to carry over.")
            return 0
        if not args.yes and input(f"\nCarry over {len(chosen)} mod(s)? [y/N] ").strip().lower() != "y":
            return 1
        print(app.carry.carry(target, chosen, progress=print, copy_local=args.copy_local).summary())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
