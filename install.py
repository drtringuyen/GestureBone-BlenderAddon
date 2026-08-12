#!/usr/bin/env python3
"""
Install GestureBone addon to Blender.
Run from PyCharm terminal or command line after editing source files.

Deploys to EVERY Blender version that already has a GestureBone install, so
copies in multiple Blender versions (e.g. 5.1 and 5.2) stay in sync. Override
by setting BLENDER_VERSIONS to an explicit list, e.g. ["5.1", "5.2"].
"""

import os
import shutil
import sys
import json
import socket
from pathlib import Path
from datetime import datetime

ADDON_NAME = "GestureBone"
# None  -> auto-detect (every version that already has GestureBone; else newest).
# list  -> force these version folders, e.g. ["5.1", "5.2"].
BLENDER_VERSIONS = ["5.1", "5.2"]
MCP_HOST = "localhost"
MCP_PORT = 9876

SCRIPT_DIR = Path(__file__).parent
ADDON_SRC = SCRIPT_DIR / "addons" / ADDON_NAME
BLENDER_ROOT = Path.home() / "AppData" / "Roaming" / "Blender Foundation" / "Blender"


def _ver_key(p):
    try:
        return tuple(int(x) for x in p.name.split("."))
    except ValueError:
        return ()


def _resolve_versions():
    """Return the list of Blender version folder names to deploy into."""
    if BLENDER_VERSIONS:
        return list(BLENDER_VERSIONS)

    installable = [
        p for p in BLENDER_ROOT.glob("*")
        if p.is_dir() and (p / "scripts" / "addons").is_dir() and _ver_key(p)
    ]
    if not installable:
        print(f"[ERROR] No Blender scripts/addons folder found under {BLENDER_ROOT}")
        sys.exit(1)

    # Prefer every version that already has GestureBone installed (keep them in sync).
    with_addon = [p for p in installable if (p / "scripts" / "addons" / ADDON_NAME).is_dir()]
    chosen = with_addon if with_addon else [max(installable, key=_ver_key)]
    return [p.name for p in sorted(chosen, key=_ver_key)]


def deploy_to(version):
    """Copy the addon source into one Blender version's addons folder."""
    addons = BLENDER_ROOT / version / "scripts" / "addons"
    addons.mkdir(parents=True, exist_ok=True)
    dest = addons / ADDON_NAME
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(ADDON_SRC, dest)

    build_info = {
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "date": datetime.now().strftime("%d/%m/%Y"),
    }
    with open(dest / "build_info.json", "w") as f:
        json.dump(build_info, f)
    print(f"[SUCCESS] {version}: installed at {dest}")


def reload_via_mcp(addon_name: str) -> None:
    """Reload the addon in whichever Blender is listening on the MCP port."""
    code = f"""
import sys, bpy
addon = "{addon_name}"
bpy.ops.preferences.addon_disable(module=addon)
mods = [k for k in sys.modules if k == addon or k.startswith(addon + ".")]
for m in mods:
    del sys.modules[m]
bpy.ops.preferences.addon_enable(module=addon)
result = {{"status": "reloaded"}}
"""
    request = json.dumps({"type": "execute", "code": code, "strict_json": False}) + "\0"
    with socket.socket() as sock:
        sock.settimeout(10.0)
        sock.connect((MCP_HOST, MCP_PORT))
        sock.sendall(request.encode("utf-8"))
        buf = bytearray()
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            buf.extend(chunk)
            if b"\0" in buf:
                break
    response = json.loads(buf.split(b"\0")[0].decode())
    if response.get("status") == "error":
        raise RuntimeError(response.get("message", "Blender MCP error"))


def main():
    if not ADDON_SRC.exists():
        print(f"[ERROR] Addon source not found: {ADDON_SRC}")
        sys.exit(1)

    versions = _resolve_versions()
    mode = "explicit" if BLENDER_VERSIONS else "auto-detected"
    print(f"[*] Installing {ADDON_NAME}...")
    print(f"    Source:   {ADDON_SRC}")
    print(f"    Targets:  {', '.join(versions)} ({mode})")

    for version in versions:
        deploy_to(version)

    # Only the running Blender (bound to MCP_PORT) can be hot-reloaded; the rest
    # pick up the new files on their next start / manual reload.
    print(f"[*] Reloading {ADDON_NAME} in the running Blender via MCP...")
    try:
        reload_via_mcp(ADDON_NAME)
        print(f"[OK] Reloaded in the Blender on port {MCP_PORT}")
    except ConnectionRefusedError:
        print(f"[WARN] No Blender on MCP port {MCP_PORT} — files deployed, reload skipped")
    except Exception as e:
        print(f"[WARN] MCP reload failed: {e}")


if __name__ == "__main__":
    main()
