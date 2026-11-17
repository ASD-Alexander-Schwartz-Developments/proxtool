# Copyright 2026 A.S.D - Alexander Schwartz Developments
# SPDX-License-Identifier: Apache-2.0
# PyInstaller build of the stand-alone programs, one folder for both:
#   ProxTitTags(.exe)  the window          proxtool(.exe)  the command line
# Build:  pyinstaller packaging/proxtool.spec   (from the repository root)
# Output: dist/ProxTitTags/   (packaging/build_pack.py zips it)
import os
import sys
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
datas = collect_data_files("proxtool")                 # assets/, api/sl_bt.xapi, notices
datas += [(os.path.join(ROOT, f), ".") for f in ("LICENSE", "NOTICE")]
hidden = collect_submodules("proxtool") + collect_submodules("bleak")
if sys.platform == "win32":
    hidden += collect_submodules("winrt")
try:
    import bgapi  # noqa: F401  (optional: the USB NCP adapter)
    hidden += collect_submodules("bgapi") + collect_submodules("serial")
except ImportError:
    pass
icon = os.path.join(ROOT, "proxtool", "assets", "asd-icon.ico") if sys.platform == "win32" else None


def program(script):
    return Analysis([os.path.join(SPECPATH, script)], pathex=[ROOT], datas=datas, hiddenimports=hidden)


a_gui = program("entry_gui.py")
a_cli = program("entry_cli.py")
MERGE((a_gui, "entry_gui", "ProxTitTags"), (a_cli, "entry_cli", "proxtool"))

gui_exe = EXE(PYZ(a_gui.pure), a_gui.scripts, [], exclude_binaries=True, name="ProxTitTags",
              console=False, icon=icon)
cli_exe = EXE(PYZ(a_cli.pure), a_cli.scripts, [], exclude_binaries=True, name="proxtool",
              console=True, icon=icon)
COLLECT(gui_exe, a_gui.binaries, a_gui.datas, cli_exe, a_cli.binaries, a_cli.datas, name="ProxTitTags")
