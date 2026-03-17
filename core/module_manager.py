"""
ModuleManager — install, list, remove, and launch content modules.
"""

import os
import sys
import glob
import json
import socket
import webbrowser
from shutil import copytree, rmtree, copy2

# Resolved at runtime by main.py bootstrapping
BASE_DIR    = r"C:\OfflineHub"
MODULES_DIR = os.path.join(BASE_DIR, "modules")
BIN_DIR     = os.path.join(BASE_DIR, "bin")


class ModuleManager:

    def __init__(self, service_mgr):
        self.service_mgr = service_mgr

    # ── Listing ───────────────────────────────────────────────────────────────

    def list_modules(self) -> list[tuple[str, dict]]:
        results = []
        if not os.path.isdir(MODULES_DIR):
            return results
        for folder in sorted(os.listdir(MODULES_DIR)):
            manifest_path = os.path.join(MODULES_DIR, folder, "manifest.json")
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path, encoding="utf-8") as f:
                        data = json.load(f)
                    results.append((folder, data))
                except Exception:
                    pass
        return results

    # ── Install ───────────────────────────────────────────────────────────────

    def add_from_folder(self, src_folder: str):
        name = os.path.basename(src_folder.rstrip("/\\"))
        dest = os.path.join(MODULES_DIR, name)
        if os.path.exists(dest):
            raise FileExistsError(f"Module '{name}' already exists.")
        copytree(src_folder, dest)

    def install_from_download(self, key: str, item: dict, downloaded_path: str):
        """
        Called after a download completes.
        Moves the downloaded file into the correct module directory
        and writes/updates the manifest.
        """
        mod_dir = os.path.join(MODULES_DIR, key)
        os.makedirs(os.path.join(mod_dir, "content"), exist_ok=True)

        dest_file = os.path.join(mod_dir, "content", os.path.basename(downloaded_path))
        if downloaded_path != dest_file:
            copy2(downloaded_path, dest_file)

        # Copy kiwix-serve if needed
        if item.get("server") == "kiwix":
            self._ensure_kiwix(mod_dir)

        # Write manifest
        manifest = {
            "name":        item["name"],
            "emoji":       item["emoji"],
            "type":        item.get("server", "kiwix"),
            "description": item.get("description", ""),
        }
        with open(os.path.join(mod_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    def _ensure_kiwix(self, mod_dir: str):
        """Copy kiwix-serve.exe from vendor bin into module dir if missing."""
        kiwix_bin = os.path.join(BIN_DIR, "kiwix-serve.exe")
        dest      = os.path.join(mod_dir, "kiwix-serve.exe")
        if os.path.exists(kiwix_bin) and not os.path.exists(dest):
            copy2(kiwix_bin, dest)

    # ── Remove ────────────────────────────────────────────────────────────────

    def remove(self, folder_path: str):
        name = os.path.basename(folder_path.rstrip("/\\"))
        self.service_mgr.stop(name)
        rmtree(folder_path)

    # ── Launch ────────────────────────────────────────────────────────────────

    def launch_module(self, folder: str, data: dict) -> tuple[int | None, str | None]:
        """
        Starts the module's backing service if not running.
        Returns (port, None) on success, or (None, error_message) on failure.
        """
        status = self.service_mgr.get_status(folder)
        if status != "running":
            ok, err = self._start_service(folder, data)
            if not ok:
                return None, err

        # Wait up to 10 seconds for the port to be ready
        port = self.service_mgr.get_port(folder)
        if port:
            import time
            for _ in range(20):
                with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                    if s.connect_ex(("127.0.0.1", port)) == 0:
                        break
                time.sleep(0.5)

        return port, None

    def _start_service(self, folder: str, data: dict) -> tuple[bool, str | None]:
        mod_type = data.get("type", "kiwix")
        path     = os.path.join(MODULES_DIR, folder)

        if mod_type == "kiwix":
            return self._start_kiwix(folder, path)
        elif mod_type == "kolibri":
            return self._start_kolibri(folder, path)
        elif mod_type == "mbtiles":
            self.service_mgr.register_virtual(folder, 8082)
            return True, None
        return False, f"Unknown module type: '{mod_type}'"

    def _start_kiwix(self, folder: str, path: str):
        import subprocess

        # Look for kiwix-serve in the module folder first, then fall back to BIN_DIR
        exe = glob.glob(os.path.join(path, "**", "kiwix-serve*.exe"), recursive=True)
        if not exe:
            bin_exe = os.path.join(BIN_DIR, "kiwix-serve.exe")
            if os.path.exists(bin_exe):
                exe = [bin_exe]

        zims = glob.glob(os.path.join(path, "**", "*.zim"), recursive=True)

        if not exe:
            return False, (
                "kiwix-serve.exe not found.\n\n"
                f"Place kiwix-serve.exe in:\n  {BIN_DIR}\n"
                "or inside the module folder, then try again.\n\n"
                "Download it from: https://www.kiwix.org/en/downloads/ "
                "(kiwix-tools Windows build)"
            )

        if not zims:
            return False, (
                f"No .zim file found in module folder:\n  {path}\n\n"
                "Make sure your module ZIP contains a .zim file inside a "
                "'content/' subfolder."
            )

        port = _free_port(8081)
        cmd  = [exe[0], f"--port={port}"] + zims
        proc = subprocess.Popen(
            cmd, cwd=path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW  # suppress console window
        )
        self.service_mgr.register(folder, proc, port)
        return True, None

    def _start_kolibri(self, folder: str, path: str):
        import subprocess
        exe = glob.glob(os.path.join(path, "**", "kolibri*.exe"), recursive=True)
        if not exe:
            return

        port = _free_port(8080)
        env  = os.environ.copy()
        env["KOLIBRI_HOME"] = os.path.join(path, "kolibri_home")
        cmd  = [exe[0], "start", "--port", str(port), "--foreground"]
        proc = subprocess.Popen(cmd, cwd=path, env=env,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        self.service_mgr.register(folder, proc, port)


# ── Utility ───────────────────────────────────────────────────────────────────

def _free_port(start: int = 8081) -> int:
    for port in range(start, start + 200):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start