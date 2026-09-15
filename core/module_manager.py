"""
ModuleManager: install, list, remove, and open content modules.

No subprocesses. `zim` modules are opened in-process via ZimReader (libzim),
`mbtiles` modules are read in-process by TileServer (sqlite), and `llm`
modules are opened in-process via LLMEngine (onnxruntime-genai). There is no
vendor binary of any kind involved.
"""

import glob
import json
import logging
import os
import shutil
import sqlite3
from shutil import copy2, rmtree

from core.registry import ContentRegistry
from core.zim_reader import ZimReader

logger = logging.getLogger(__name__)


def _detect_mbtiles_format(path: str) -> str:
    """
    Reads the real "vector" vs "raster" split straight from the .mbtiles
    file's own metadata table ("format": "pbf" for vector, "png"/"jpg"/
    "webp" for raster - required by the MBTiles spec), instead of guessing
    from the filename. Confirmed live to matter: the old filename-substring
    guess ("vector" in the name -> vector, else raster) tagged real vector
    files as raster whenever the filename didn't happen to contain the word
    "vector," which made the portal request the wrong tile endpoint and
    render a blank map with no error. Defaults to "raster" if the file has
    no readable metadata table at all.
    """
    try:
        conn = sqlite3.connect(path)
        try:
            row = conn.execute(
                "SELECT value FROM metadata WHERE name = 'format'"
            ).fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return "raster"
    return "vector" if row and row[0] == "pbf" else "raster"

BASE_DIR    = r"C:\OfflineHub"
MODULES_DIR = os.path.join(BASE_DIR, "modules")

VALID_TYPES = {"zim", "mbtiles", "llm"}


class ModuleManager:

    def __init__(self, registry: ContentRegistry):
        self.registry = registry
        self._llm_loaded_module: str | None = None

    # ── Listing ───────────────────────────────────────────────────────────────

    def list_modules(self) -> list[tuple[str, dict]]:
        results = []
        if not os.path.isdir(MODULES_DIR):
            return results
        for folder in sorted(os.listdir(MODULES_DIR)):
            mod_dir = os.path.join(MODULES_DIR, folder)
            if not os.path.isdir(mod_dir):
                continue
            manifest_path = os.path.join(mod_dir, "manifest.json")
            if os.path.exists(manifest_path):
                try:
                    with open(manifest_path, encoding="utf-8") as f:
                        data = json.load(f)
                    results.append((folder, data))
                    continue
                except Exception as e:
                    logger.warning(
                        "Module '%s' has an unreadable manifest.json (%s) - "
                        "attempting to reconstruct it from its actual content", folder, e
                    )
            # No manifest.json at all, or one that failed to parse. Confirmed
            # live to happen for a real reason, not just a theoretical edge
            # case: an uninstall that caught the app with a module's
            # .mbtiles connection still open deleted manifest.json (a tiny
            # file, never held open) while the locked .mbtiles data file
            # itself survived. Without this, a folder full of real,
            # perfectly good content just silently vanishes from every
            # listing - which is exactly what a reinstalled app showed the
            # admin: two real map files sitting right there on disk, and
            # "no maps installed" in the UI. Reconstruct + persist a
            # manifest from whatever content is actually still there,
            # rather than losing the module a second time.
            data = _reconstruct_manifest(folder, mod_dir)
            if data is not None:
                results.append((folder, data))
            else:
                logger.warning("Skipping module '%s': no manifest.json and no recognizable content", folder)
        return results

    def get_manifest(self, folder: str) -> dict | None:
        manifest_path = os.path.join(MODULES_DIR, folder, "manifest.json")
        if not os.path.exists(manifest_path):
            return None
        with open(manifest_path, encoding="utf-8") as f:
            return json.load(f)

    # ── Install: raw file / zip / catalogue download ────────────────────────────

    def install_from_raw_file(self, filepath: str):
        """MAGIC INSTALLER: a raw .zim or .mbtiles file -> folder + manifest."""
        filename = os.path.basename(filepath)
        basename, ext = os.path.splitext(filename)
        ext = ext.lower()

        if ext not in (".zim", ".mbtiles"):
            raise ValueError(f"Unsupported file type '{ext}'. Please select a .zim or .mbtiles file.")

        mod_type = "zim" if ext == ".zim" else "mbtiles"

        clean_name = basename.replace("_", " ").title()

        emoji = "📦"
        lower_name = basename.lower()
        if "wikipedia" in lower_name: emoji = "📚"
        elif "gutenberg" in lower_name: emoji = "📖"
        elif "khan" in lower_name: emoji = "🎓"
        elif ext == ".mbtiles": emoji = "🗺️"

        safe_name = _safe_name(basename)
        dest_dir = os.path.join(MODULES_DIR, safe_name)
        if os.path.exists(dest_dir):
            raise FileExistsError(f"Module '{safe_name}' is already installed.")

        content_dir = os.path.join(dest_dir, "content")
        os.makedirs(content_dir, exist_ok=True)

        dest_file = os.path.join(content_dir, filename)
        shutil.move(filepath, dest_file)

        manifest = {
            "name": clean_name,
            "emoji": emoji,
            "type": mod_type,
            "description": f"Imported automatically from {filename}",
        }
        if mod_type == "mbtiles":
            manifest["format"] = _detect_mbtiles_format(dest_file)

        with open(os.path.join(dest_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        self.open_module(safe_name, manifest)

    def install_from_zip(self, zip_path: str):
        """Extracts a ZIP (manifest.json + content/) and installs the module."""
        import tempfile
        import zipfile

        with tempfile.TemporaryDirectory() as temp_dir:
            with zipfile.ZipFile(zip_path, "r") as zip_ref:
                _safe_extract(zip_ref, temp_dir)

            manifest_dir = None
            for root, _dirs, files in os.walk(temp_dir):
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

            mod_type = data.get("type", "zim")
            if mod_type not in VALID_TYPES:
                raise ValueError(
                    f"Unknown module type '{mod_type}'. Must be one of: {', '.join(sorted(VALID_TYPES))}."
                )

            safe_name = _safe_name(data.get("name", "Custom Module"))
            dest = os.path.join(MODULES_DIR, safe_name)
            if os.path.exists(dest):
                raise FileExistsError(f"Module '{safe_name}' is already installed.")

            shutil.copytree(manifest_dir, dest)
            self.open_module(safe_name, data)

    def install_from_download(self, key: str, item: dict, downloaded_path: str, replace: bool = False):
        """
        A single-file catalogue download (ZIM) finished. Install it as a
        module. `item["url"]` (the exact resolved download URL used) is
        recorded as the manifest's "source_url" - the admin Modules page
        compares this against the catalogue's CURRENT resolved URL to tell
        whether a newer snapshot has since been published, without needing
        to store a separate version number Kiwix doesn't expose directly.
        `replace=True` (used by the "update" flow) removes an existing
        install of the same key first instead of raising.
        """
        mod_dir = os.path.join(MODULES_DIR, key)
        if os.path.exists(mod_dir):
            if not replace:
                raise FileExistsError(
                    f"'{key}' is already installed. Remove it first if you want to replace it."
                )
            self.remove(mod_dir)
        os.makedirs(os.path.join(mod_dir, "content"), exist_ok=True)

        dest_file = os.path.join(mod_dir, "content", os.path.basename(downloaded_path))
        if downloaded_path != dest_file:
            copy2(downloaded_path, dest_file)

        manifest = {
            "name":        item["name"],
            "emoji":       item["emoji"],
            "type":        "zim",
            "description": item.get("description", ""),
            "source_url":  item.get("url"),
        }
        with open(os.path.join(mod_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        self.open_module(key, manifest)

    def install_map_from_download(self, key: str, item: dict, downloaded_path: str, replace: bool = False):
        """A single-file catalogue download (mbtiles map) finished - install
        it as a module. See install_from_download for "source_url"/"replace"."""
        mod_dir = os.path.join(MODULES_DIR, key)
        if os.path.exists(mod_dir):
            if not replace:
                raise FileExistsError(
                    f"'{key}' is already installed. Remove it first if you want to replace it."
                )
            self.remove(mod_dir)
        os.makedirs(os.path.join(mod_dir, "content"), exist_ok=True)

        dest_file = os.path.join(mod_dir, "content", os.path.basename(downloaded_path))
        if downloaded_path != dest_file:
            copy2(downloaded_path, dest_file)

        manifest = {
            "name":        item["name"],
            "emoji":       item["emoji"],
            "type":        "mbtiles",
            "format":      _detect_mbtiles_format(dest_file),
            "description": item.get("description", ""),
            "source_url":  item.get("url"),
        }
        with open(os.path.join(mod_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        self.open_module(key, manifest)

    def install_extracted_map(self, iso: str, name: str, mbtiles_path: str) -> str:
        """
        A self-serve country map (core/map_extract.py's live, in-app
        extraction from Protomaps' daily build) finished - install it as a
        module. Uses a "country_<iso>" key, distinct from MAPS_CATALOGUE's
        "map_<region>" keys, so extracting e.g. France here can never
        collide with the existing hand-curated map_france pack. Returns the
        installed folder key.
        """
        key = f"country_{iso.lower()}"
        mod_dir = os.path.join(MODULES_DIR, key)
        if os.path.exists(mod_dir):
            raise FileExistsError(
                f"'{key}' is already installed. Remove it first if you want to replace it."
            )
        os.makedirs(os.path.join(mod_dir, "content"), exist_ok=True)

        dest_file = os.path.join(mod_dir, "content", f"{key}.mbtiles")
        if mbtiles_path != dest_file:
            shutil.move(mbtiles_path, dest_file)

        manifest = {
            "name":        f"Map: {name}",
            "emoji":       "🗺️",
            "type":        "mbtiles",
            "format":      _detect_mbtiles_format(dest_file),
            "description": f"Self-serve extract of {name} from Protomaps' daily basemap build.",
            "source":      "protomaps_daily_build",
            "iso":         iso,
        }
        with open(os.path.join(mod_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        self.open_module(key, manifest)
        return key

    def install_llm_from_download(self, key: str, item: dict, downloaded_dir: str):
        """A multi-file LLM model download finished. Install it as an llm module."""
        mod_dir = os.path.join(MODULES_DIR, key)
        if os.path.exists(mod_dir):
            raise FileExistsError(
                f"'{key}' is already installed. Remove it first if you want to replace it."
            )
        content_dir = os.path.join(mod_dir, "content")
        os.makedirs(mod_dir, exist_ok=True)

        if downloaded_dir != content_dir:
            shutil.move(downloaded_dir, content_dir)

        manifest = {
            "name":        item["name"],
            "emoji":       item.get("emoji", "🤖"),
            "type":        "llm",
            "description": item.get("description", ""),
        }
        with open(os.path.join(mod_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        self.registry.register(key, "llm")

    # ── Remove ────────────────────────────────────────────────────────────────

    def remove(self, folder_path: str):
        name = os.path.basename(folder_path.rstrip("/\\"))
        self.registry.unload(name)
        if name == self._llm_loaded_module:
            self._llm_loaded_module = None
        rmtree(folder_path)

    # ── Open (in-process, no subprocess) ─────────────────────────────────────

    def open_module(self, folder: str, data: dict):
        """Validate + register a module right after install so the admin UI
        can immediately show it as loaded rather than waiting for first use."""
        mod_type = data.get("type")
        path = os.path.join(MODULES_DIR, folder)

        if mod_type == "zim":
            self.get_zim_reader(folder)
        elif mod_type == "mbtiles":
            mbtiles = glob.glob(os.path.join(path, "**", "*.mbtiles"), recursive=True)
            if not mbtiles:
                self.registry.mark_error(folder, "No .mbtiles file found in module folder.")
            else:
                self.registry.register(folder, "mbtiles")
        elif mod_type == "llm":
            self.registry.register(folder, "llm")
        else:
            self.registry.mark_error(folder, f"Unknown module type: '{mod_type}'")

    def get_zim_reader(self, folder: str) -> ZimReader:
        """Return the cached ZimReader for `folder`, opening it on first use."""
        existing = self.registry.get_handle(folder)
        if existing is not None:
            return existing

        path = os.path.join(MODULES_DIR, folder)
        zims = glob.glob(os.path.join(path, "**", "*.zim"), recursive=True)
        if not zims:
            self.registry.mark_error(folder, "No .zim file found in module folder.")
            raise FileNotFoundError(f"No .zim file found for module '{folder}'.")

        try:
            reader = ZimReader(zims[0])
        except Exception as e:
            self.registry.mark_error(folder, str(e))
            raise

        self.registry.register(folder, "zim", handle=reader)
        return reader

    def get_llm_engine(self, folder: str):
        """
        Return the cached LLMEngine for `folder`, loading it on first use.
        Only one LLM model is kept resident at a time. Loading a different
        one unloads whichever was previously loaded.
        """
        from core.llm_engine import LLMEngine  # imported lazily: heavy dependency

        existing = self.registry.get_handle(folder)
        if existing is not None:
            return existing

        if self._llm_loaded_module and self._llm_loaded_module != folder:
            self.registry.unload(self._llm_loaded_module)

        path = os.path.join(MODULES_DIR, folder, "content")
        try:
            engine = LLMEngine(path)
            engine.load()
        except Exception as e:
            self.registry.mark_error(folder, str(e))
            raise

        self.registry.register(folder, "llm", handle=engine)
        self._llm_loaded_module = folder
        return engine


# ── Utility ───────────────────────────────────────────────────────────────────

def _safe_extract(zip_ref, dest_dir: str):
    """
    zipfile.ZipFile.extractall() does not guard against "zip slip": a member
    named e.g. "../../Windows/System32/evil.dll" or an absolute path extracts
    outside dest_dir (os.path.join silently discards the first argument when
    the second is absolute, which is exactly how an absolute-path member
    escapes too). Manual Install explicitly accepts ZIPs uploaded from any
    device on the hotspot, so a crafted "content pack" is a real path here,
    not a theoretical one - reject any member that resolves outside dest_dir
    before extracting anything.
    """
    dest_root = os.path.realpath(dest_dir)
    for member in zip_ref.namelist():
        target = os.path.realpath(os.path.join(dest_dir, member))
        if target != dest_root and not target.startswith(dest_root + os.sep):
            raise ValueError(f"Refusing to extract '{member}': escapes the destination folder.")
    zip_ref.extractall(dest_dir)


def _safe_name(raw: str) -> str:
    return "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in raw).strip()


def _reconstruct_manifest(folder: str, mod_dir: str) -> dict | None:
    """
    Rebuilds a manifest.json from whatever real content is still sitting in
    `mod_dir`, and persists it so this only has to happen once per folder.
    Returns None if there's nothing recognizable to recover (an empty or
    genuinely unrelated folder), in which case the caller still skips it.

    Prefers real, known-good data over a guess wherever one is available:
    - A "country_<iso>" folder (core/map_extract.py's self-serve extractor)
      gets its exact original name/description/emoji reconstructed from the
      bundled country list and _detect_mbtiles_format(), matching
      ModuleManager.install_extracted_map() exactly, not approximated.
    - A folder whose key matches a live catalogue entry (Kiwix ZIM, curated
      map pack, or LLM model - core/downloader.py) gets that entry's real
      name/emoji/description back, the same way it would look if installed
      fresh today.
    - Anything else falls back to a title-cased folder name, same heuristic
      install_from_raw_file() already uses for a manually-dropped-in file.
    """
    mbtiles = glob.glob(os.path.join(mod_dir, "**", "*.mbtiles"), recursive=True)
    zims = glob.glob(os.path.join(mod_dir, "**", "*.zim"), recursive=True)
    has_llm_content = os.path.isdir(os.path.join(mod_dir, "content")) and bool(
        os.listdir(os.path.join(mod_dir, "content"))
    ) and not mbtiles and not zims
    if not mbtiles and not zims and not has_llm_content:
        return None

    if folder.startswith("country_") and mbtiles:
        from core.map_extract import load_countries
        iso = folder[len("country_"):].upper()
        try:
            country_name = load_countries()[iso][0]
        except (FileNotFoundError, KeyError):
            country_name = folder[len("country_"):].replace("_", " ").title()
        manifest = {
            "name":        f"Map: {country_name}",
            "emoji":       "🗺️",
            "type":        "mbtiles",
            "format":      _detect_mbtiles_format(mbtiles[0]),
            "description": f"Self-serve extract of {country_name} from Protomaps' daily basemap build.",
            "source":      "protomaps_daily_build",
            "iso":         iso.lower(),
        }
    else:
        from core.downloader import CATALOGUE, LLM_CATALOGUE, MAPS_CATALOGUE
        catalogue_item = CATALOGUE.get(folder) or MAPS_CATALOGUE.get(folder) or LLM_CATALOGUE.get(folder)
        name = catalogue_item["name"] if catalogue_item else folder.replace("_", " ").title()
        description = catalogue_item.get("description", "") if catalogue_item else (
            "Recovered module: manifest.json was missing or unreadable, "
            "rebuilt from the content still on disk."
        )
        if mbtiles:
            manifest = {
                "name": name, "emoji": catalogue_item["emoji"] if catalogue_item else "🗺️",
                "type": "mbtiles", "format": _detect_mbtiles_format(mbtiles[0]), "description": description,
            }
        elif zims:
            manifest = {
                "name": name, "emoji": catalogue_item["emoji"] if catalogue_item else "📚",
                "type": "zim", "description": description,
            }
        else:
            manifest = {
                "name": name, "emoji": catalogue_item["emoji"] if catalogue_item else "🤖",
                "type": "llm", "description": description,
            }

    try:
        with open(os.path.join(mod_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        logger.warning("Reconstructed manifest.json for module '%s' from its content", folder)
    except Exception:
        logger.exception("Could not persist reconstructed manifest.json for '%s'", folder)

    return manifest
