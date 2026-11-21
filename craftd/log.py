"""Craftd's log file: craftd.log in the data folder (Settings → About → Open Log Folder).

Craftd.exe has no console window, so without this an error would leave no trace. Testers can attach
craftd.log to a bug report. The file is kept small: 1 MB, plus two older copies.
"""

from __future__ import annotations

import logging
import platform
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_NAME = "craftd.log"
log = logging.getLogger("craftd")


def log_file(home: Path) -> Path:
    return home / LOG_NAME


def setup(home: Path) -> Path:
    """Start writing to craftd.log, and log anything that would otherwise crash silently."""
    from . import __version__
    path = log_file(home)
    for h in list(log.handlers):  # a different data folder (e.g. CRAFTD_HOME changed): switch files
        if isinstance(h, RotatingFileHandler) and Path(h.baseFilename) != path.resolve():
            log.removeHandler(h)
            h.close()
    if not any(isinstance(h, RotatingFileHandler) for h in log.handlers):
        try:
            handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
        except OSError:
            return path  # e.g. a read-only data folder: carry on without a log
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S"))
        log.addHandler(handler)
        log.setLevel(logging.INFO)
    log.info("Craftd %s started · %s %s · Python %s", __version__, platform.system(), platform.release(),
             platform.python_version())

    if getattr(sys.excepthook, "_craftd", False):
        return path
    previous = sys.excepthook

    def on_crash(kind, value, tb):
        log.critical("Unexpected error", exc_info=(kind, value, tb))
        if previous and previous is not sys.__excepthook__:
            previous(kind, value, tb)
        elif sys.stderr:  # the exe has no console, so there may be nowhere else to print it
            sys.__excepthook__(kind, value, tb)

    on_crash._craftd = True
    sys.excepthook = on_crash
    threading.excepthook = lambda args: log.critical(
        "Unexpected error in a background thread", exc_info=(args.exc_type, args.exc_value, args.exc_traceback))
    return path
