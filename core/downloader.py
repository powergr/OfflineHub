"""
Downloader — resumable HTTP downloads with progress callbacks and checksum verification.
Also defines the CATALOGUE of downloadable content.
"""

import hashlib
import os
import threading
from typing import Callable

import requests

BASE_DIR    = r"C:\OfflineHub"
MODULES_DIR = os.path.join(BASE_DIR, "modules")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

# ── Content catalogue ─────────────────────────────────────────────────────────
# Replace URL / checksum values with real Kiwix library URLs before shipping.
# Kiwix ZIM catalogue: https://library.kiwix.org/

CATALOGUE: dict[str, dict] = {
    "wikipedia_en_mini": {
        "name":        "Wikipedia (English, Mini)",
        "emoji":       "📚",
        "description": "Top ~50,000 Wikipedia articles — compact and fast.",
        "url":         "https://download.kiwix.org/zim/wikipedia/wikipedia_en_all_mini_2025-12.zim",
        "dest":        os.path.join(DOWNLOAD_DIR, "wikipedia_en_mini.zim"),
        "size":        "~12 GB",
        "checksum":    None,   # SHA-256 hex string, or None to skip
        "server":      "kiwix",
    },
    "gutenberg": {
        "name":        "Project Gutenberg",
        "emoji":       "📖",
        "description": "English Literature",
        "url":         "https://download.kiwix.org/zim/gutenberg/gutenberg_en_lcc-pr_2026-03.zim",
        "dest":        os.path.join(DOWNLOAD_DIR, "gutenberg.zim"),
        "size":        "~15 GB",
        "checksum":    None,
        "server":      "kiwix",
    },
    "khanacademy": {
        "name":        "Khan Academy",
        "emoji":       "🎓",
        "description": "Maths, science, computing, and more.",
        "url":         "https://download.kiwix.org/zim/other/khanacademy_en_all_2023-03.zim",
        "dest":        os.path.join(DOWNLOAD_DIR, "khanacademy.zim"),
        "size":        "~168 GB",
        "checksum":    None,
        "server":      "kiwix",
    },
    "osm_europe": {
        "name":        "OpenStreetMap — Europe",
        "emoji":       "📖",
        "description": "Offline vector map tiles for all of Europe.",
        "url":         "https://download.openfreemap.org/planet/2024-11-07/tiles/europe.mbtiles",
        "dest":        os.path.join(MODULES_DIR, "osm_europe", "content", "europe.mbtiles"),
        "size":        "~8 GB",
        "checksum":    None,
        "server":      "mbtiles",
    },
}


# ── Downloader ────────────────────────────────────────────────────────────────

class Downloader:
    """
    Thread-safe, resumable HTTP downloader.

    progress_cb(pct: float, speed_kbps: float)
    done_cb(success: bool, path: str)
    """

    def download(
        self,
        url:         str,
        dest:        str,
        progress_cb: Callable[[float, float], None] | None = None,
        done_cb:     Callable[[bool, str], None] | None    = None,
        checksum:    str | None                            = None,
    ):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        part_file = dest + ".part"

        try:
            # ── Resume support ────────────────────────────────────────────────
            existing = os.path.getsize(part_file) if os.path.exists(part_file) else 0
            headers  = {"Range": f"bytes={existing}-"} if existing else {}

            with requests.get(url, headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status()

                total_header = r.headers.get("Content-Range") or r.headers.get("Content-Length")
                if r.headers.get("Content-Range"):
                    # "bytes 1234-5678/TOTAL"
                    total = int(r.headers["Content-Range"].split("/")[-1])
                else:
                    total = int(r.headers.get("Content-Length", 0)) + existing

                mode = "ab" if existing else "wb"

                import time
                downloaded = existing
                t0         = time.time()

                with open(part_file, mode) as f:
                    for chunk in r.iter_content(chunk_size=1024 * 256):
                        if not chunk:
                            continue
                        f.write(chunk)
                        downloaded += len(chunk)
                        elapsed     = max(time.time() - t0, 0.001)
                        speed_kbps  = (downloaded - existing) / elapsed / 1024
                        pct         = (downloaded / total * 100) if total else 0

                        if progress_cb:
                            progress_cb(min(pct, 100), speed_kbps)

            # ── Checksum ──────────────────────────────────────────────────────
            if checksum:
                if not _verify_sha256(part_file, checksum):
                    os.remove(part_file)
                    if done_cb:
                        done_cb(False, dest)
                    return

            # ── Finalise ──────────────────────────────────────────────────────
            if os.path.exists(dest):
                os.remove(dest)
            os.rename(part_file, dest)

            if done_cb:
                done_cb(True, dest)

        except Exception as exc:
            print(f"[Downloader] Error downloading {url}: {exc}")
            if done_cb:
                done_cb(False, dest)


def _verify_sha256(path: str, expected: str) -> bool:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest().lower() == expected.lower()