# Copyright 2026 A.S.D - Alexander Schwartz Developments
# SPDX-License-Identifier: Apache-2.0
"""Zip the PyInstaller output (dist/ProxTitTags) into the release assets:

  proxtool-<ver>-<rid>.zip           plain zip: unzip anywhere, run ProxTitTags
  proxtool-plugin-<ver>-<rid>.zip    VesperApp plugin pack: the same files plus
                                     plugin.json (kind "tool"), see docs/vesperapp-addon.md
  proxtool-plugin-<ver>-<rid>.json   the pack's feed entry (version, target, size, sha256)

    python packaging/build_pack.py [--rid win-x64|linux-x64] [--out dist]
"""
import argparse
import hashlib
import json
import os
import platform
import shutil
import sys
import tempfile

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from proxtool import __version__  # noqa: E402

PACK_NAME = "proxtool"              # folder under VesperApp's plugins/
TOOL_ABI = 0                        # no .NET adapter: VesperApp only installs and launches


def default_rid() -> str:
    arch = "x64" if platform.machine().lower() in ("amd64", "x86_64") else platform.machine().lower()
    return ("win" if sys.platform == "win32" else "linux") + "-" + arch


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def manifest(rid: str) -> dict:
    exe = ".exe" if rid.startswith("win") else ""
    return {
        "name": "ProxTit Tags",
        "kind": "tool",
        "version": __version__,
        "abi": TOOL_ABI,
        "platform": rid,
        "entryDll": None,
        "launch": f"ProxTitTags{exe}",
        "commandLine": f"proxtool{exe}",
        "description": "Download, clock, settings and firmware update of ProxTit Bluetooth tags.",
        "homepage": "https://github.com/ASD-Alexander-Schwartz-Developments/proxtool",
        "license": "Apache-2.0",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rid", default=default_rid())
    ap.add_argument("--out", default=os.path.join(ROOT, "dist"))
    a = ap.parse_args()
    src = os.path.join(ROOT, "dist", "ProxTitTags")
    if not os.path.isdir(src):
        sys.exit("build first: pyinstaller packaging/proxtool.spec")
    os.makedirs(a.out, exist_ok=True)
    ver, rid = __version__, a.rid

    plain = shutil.make_archive(os.path.join(a.out, f"proxtool-{ver}-{rid}"), "zip", os.path.dirname(src),
                                os.path.basename(src))
    with tempfile.TemporaryDirectory() as tmp:
        pack = os.path.join(tmp, "pack")
        shutil.copytree(src, pack)
        with open(os.path.join(pack, "plugin.json"), "w", encoding="utf-8") as f:
            json.dump(manifest(rid), f, indent=2)
        packzip = shutil.make_archive(os.path.join(a.out, f"proxtool-plugin-{ver}-{rid}"), "zip", pack)
    entry = {"version": ver, "name": "ProxTit Tags", "target": rid,
             "asset": f"{ver}/{os.path.basename(packzip)}", "size": os.path.getsize(packzip),
             "sha256": sha256(packzip), "abi": TOOL_ABI, "kind": "tool"}
    with open(os.path.join(a.out, f"proxtool-plugin-{ver}-{rid}.json"), "w", encoding="utf-8") as f:
        json.dump(entry, f, indent=2)
    for p in (plain, packzip):
        print(f"{p}  {os.path.getsize(p) // 1024} kB  sha256 {sha256(p)}")


if __name__ == "__main__":
    main()
