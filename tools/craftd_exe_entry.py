"""Entry point for Craftd.exe (used by build_exe.bat). Does exactly what `python -m craftd` does.

PyInstaller runs its entry file as a plain script, so craftd/__main__.py's relative import can't be used here.
"""

from craftd.gui.main_window import run

raise SystemExit(run())
