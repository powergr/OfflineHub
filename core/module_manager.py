"""
ModuleManager — install, list, remove, and launch content modules.
"""

import os
import sys
import glob
import json
import socket
import webbrowser
import shutil
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
        results =[]
        if not os.path.isdir(MODULES_DIR):
            return results
        for folder in sorted(os.listdir(MODULES_DIR)):
            manifest_path = os.path.join(MODULES_DIR, folder, "manifest.json")
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path, encoding="utf-8") as f:
                        data = json.load(f)
                    results.append((folder, data))
                except Exception as e:
                    print(f"[WARNING] Skipping module '{folder}': invalid manifest.json ({e})")
        return results

    # ── Install ───────────────────────────────────────────────────────────────

    def install_from_raw_file(self, filepath: str):
        """
        MAGIC INSTALLER: Takes a raw .zim or .mbtiles file, figures out the name,
        builds the folder structure, generates the manifest, and launches it.
        """
        filename = os.path.basename(filepath)
        basename, ext = os.path.splitext(filename)
        ext = ext.lower()

        if ext not in [".zim", ".mbtiles"]:
            raise ValueError(f"Unsupported file type '{ext}'. Please select a .zim or .mbtiles file.")

        mod_type = "kiwix" if ext == ".zim" else "mbtiles"
        
        # 1. Clean up the filename to make a readable title
        clean_name = basename.replace("_", " ").title()
        
        # 2. Smart Emoji Guesser
        emoji = "📦"
        lower_name = basename.lower()
        if "wikipedia" in lower_name: emoji = "📚"
        elif "gutenberg" in lower_name: emoji = "📖"
        elif "khan" in lower_name or "kolibri" in lower_name: emoji = "🎓"
        elif ext == ".mbtiles": emoji = "🗺️"

        # 3. Create a safe folder name
        safe_name = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in basename).strip()
        dest_dir = os.path.join(MODULES_DIR, safe_name)
        
        if os.path.exists(dest_dir):
            raise FileExistsError(f"Module '{safe_name}' is already installed.")

        # 4. Build the folder structure
        content_dir = os.path.join(dest_dir, "content")
        os.makedirs(content_dir, exist_ok=True)

        # 5. Move the massive file instantly (instead of copying, which takes forever)
        dest_file = os.path.join(content_dir, filename)
        shutil.move(filepath, dest_file)

        # 6. Copy kiwix-serve.exe if needed
        if mod_type == "kiwix":
            self._ensure_kiwix(dest_dir)

        # 7. Auto-generate the manifest.json
        manifest = {
            "name": clean_name,
            "emoji": emoji,
            "type": mod_type,
            "description": f"Imported automatically from {filename}"
        }
        
        if mod_type == "mbtiles":
            manifest["format"] = "vector" if "vector" in lower_name else "raster"

        with open(os.path.join(dest_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        # 8. Start it up!
        self.launch_module(safe_name, manifest)


    def install_from_zip(self, zip_path: str):
        """Safely extracts a ZIP file and installs the module."""
        import zipfile
        import tempfile

        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)

            manifest_dir = None
            for root, dirs, files in os.walk(temp_dir):
                if "manifest.json" in files:
                    manifest_dir = root
                    break

            if not manifest_dir:
                raise FileNotFoundError("Invalid ZIP: 'manifest.json' not found inside.")

            manifest_path = os.path.join(manifest_dir, "manifest.json")
            try:
                with open(manifest_path, encoding="utf-8") as f:
                    data = json.load(f)
            except Exception as e:
                raise ValueError(f"manifest.json is corrupted or invalid JSON. Error: {e}")

            raw_name = data.get("name", "Custom Module")
            safe_name = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in raw_name).strip()
            
            dest = os.path.join(MODULES_DIR, safe_name)
            if os.path.exists(dest):
                raise FileExistsError(f"Module '{safe_name}' is already installed.")

            shutil.copytree(manifest_dir, dest)

            if data.get("type", "kiwix") == "kiwix":
                self._ensure_kiwix(dest)

            self.launch_module(safe_name, data)

    def install_from_download(self, key: str, item: dict, downloaded_path: str):
        mod_dir = os.path.join(MODULES_DIR, key)
        os.makedirs(os.path.join(mod_dir, "content"), exist_ok=True)

        dest_file = os.path.join(mod_dir, "content", os.path.basename(downloaded_path))
        if downloaded_path != dest_file:
            copy2(downloaded_path, dest_file)

        if item.get("server") == "kiwix":
            self._ensure_kiwix(mod_dir)

        manifest = {
            "name":        item["name"],
            "emoji":       item["emoji"],
            "type":        item.get("server", "kiwix"),
            "description": item.get("description", ""),
        }
        with open(os.path.join(mod_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

    def add_from_folder(self, src_folder: str):
        pass # Replaced by install_from_zip and install_from_raw_file

    def _ensure_kiwix(self, mod_dir: str):
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
        status = self.service_mgr.get_status(folder)
        if status != "running":
            ok, err = self._start_service(folder, data)
            if not ok:
                return None, err

        port = self.service_mgr.get_port(folder)
        
        if port and data.get("type") != "mbtiles":
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

        exe = glob.glob(os.path.join(path, "**", "kiwix-serve*.exe"), recursive=True)
        if not exe:
            bin_exe = os.path.join(BIN_DIR, "kiwix-serve.exe")
            if os.path.exists(bin_exe):
                exe = [bin_exe]

        zims = glob.glob(os.path.join(path, "**", "*.zim"), recursive=True)

        if not exe:
            return False, ("kiwix-serve.exe not found.")

        if not zims:
            return False, ("No .zim file found in module folder.")

        port = _free_port(8081)
        cmd  = [exe[0], f"--port={port}"] + zims
        proc = subprocess.Popen(
            cmd, cwd=path,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW
        )
        self.service_mgr.register(folder, proc, port)
        return True, None

    def _start_kolibri(self, folder: str, path: str):
        import subprocess
        exe = glob.glob(os.path.join(path, "**", "kolibri*.exe"), recursive=True)
        if not exe:
            return False, "kolibri.exe not found"

        port = _free_port(8080)
        env  = os.environ.copy()
        env["KOLIBRI_HOME"] = os.path.join(path, "kolibri_home")
        cmd  =[exe[0], "start", "--port", str(port), "--foreground"]
        proc = subprocess.Popen(cmd, cwd=path, env=env,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        self.service_mgr.register(folder, proc, port)
        return True, None


# ── Utility ───────────────────────────────────────────────────────────────────

def _free_port(start: int = 8081) -> int:
    for port in range(start, start + 200):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    return start