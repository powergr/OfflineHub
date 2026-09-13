"""
Downloader — resumable HTTP downloads with progress callbacks and checksum
verification, plus live resolution of current Kiwix ZIM download URLs.

Kiwix rotates dated snapshot filenames and deletes old ones (e.g.
wikipedia_en_all_mini_2025-12.zim eventually 404s once a newer snapshot
replaces it), so URLs are resolved live against Kiwix's OPDS v2 catalog
(https://library.kiwix.org/catalog/v2/entries) instead of being hardcoded.
"""

import hashlib
import os
import threading
import xml.etree.ElementTree as ET
from typing import Callable

import requests

BASE_DIR     = r"C:\OfflineHub"
MODULES_DIR  = os.path.join(BASE_DIR, "modules")
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

CATALOG_URL = "https://library.kiwix.org/catalog/v2/entries"
_ATOM_NS = "{http://www.w3.org/2005/Atom}"
_ACQUISITION_REL = "http://opds-spec.org/acquisition/open-access"

# ── Curated "quick start" content ────────────────────────────────────────────
# Only metadata + how-to-find-it lives here. The actual download URL, size,
# and checksum are resolved live via resolve_catalogue_entry() so this never
# goes stale the way a hardcoded filename does. Khan Academy is deliberately
# not curated here: the Kiwix library now only publishes a single ~180GB
# "all" ZIM for it (no small subject-specific version exists anymore) —
# unreasonable as a "quick start" button. Use search_catalogue() instead to
# let the admin browse the live library and see real sizes before choosing.

CATALOGUE: dict[str, dict] = {
    "wikipedia_en_mini": {
        "name":        "Wikipedia (English, Mini)",
        "emoji":       "📚",
        "description": "Top Wikipedia articles — text only, no images.",
        "opds_name":   "wikipedia_en_all",
        "opds_flavour": "mini",
        "server":      "zim",
    },
    "gutenberg_lcc_l": {
        "name":        "Project Gutenberg (Literature)",
        "emoji":       "📖",
        "description": "English & American literature (LCC class L).",
        "opds_name":   "gutenberg_en_lcc-l",
        "opds_flavour": None,
        "server":      "zim",
    },
}

# Last-known-good fallback, used only if the live OPDS lookup fails (e.g. no
# internet at that moment, or the API changes shape). May go stale over time
# like the old hardcoded catalogue did — it's a safety net, not the primary path.
_FALLBACK_URLS = {
    "wikipedia_en_mini": "https://download.kiwix.org/zim/wikipedia/wikipedia_en_all_mini_2026-06.zim",
    "gutenberg_lcc_l":   "https://download.kiwix.org/zim/gutenberg/gutenberg_en_lcc-l_2026-03.zim",
}

# ── Offline LLM (onnxruntime-genai model) ────────────────────────────────────
# Model files ship as several files under one Hugging Face repo path, unlike
# a ZIM's single file, hence a separate small catalogue + Downloader.download_set().
# This exact repo/subfolder/file list was verified working end-to-end this
# session (model loads, tokenizes, and generates real replies) — Hugging Face
# repos do get reorganized over time, so if this ever starts 404ing, check the
# repo's current file tree before assuming the code is at fault.

LLM_REPO      = "xiaoyao9184/Qwen2.5-0.5B-Instruct-onnx-genai"
LLM_SUBFOLDER = "cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4"
LLM_FILES     = [
    "genai_config.json", "tokenizer.json", "tokenizer_config.json",
    "special_tokens_map.json", "added_tokens.json", "chat_template.jinja",
    "model.onnx", "model.onnx.data",
]

LLM_CATALOGUE: dict[str, dict] = {
    "assistant_qwen_0_5b": {
        "name":        "Offline Assistant (Qwen2.5, 0.5B)",
        "emoji":       "🤖",
        "description": "A small, fast offline chat assistant. Good for quick Q&A on "
                        "this machine — not a research tool, and not always accurate.",
        "size":        873_540_870,  # sum of the real file sizes above, confirmed live
    },
}


class CatalogueError(Exception):
    pass


def llm_download_plan(key: str) -> tuple[list[dict], str]:
    """
    Returns (files, dest_dir) for Downloader.download_set(), where `files` is
    [{"url", "dest", "checksum"}, ...] for every file LLM_CATALOGUE[key] needs.
    """
    if key not in LLM_CATALOGUE:
        raise CatalogueError(f"Unknown LLM catalogue key: {key!r}")

    dest_dir = os.path.join(DOWNLOAD_DIR, key)
    base_url = f"https://huggingface.co/{LLM_REPO}/resolve/main/{LLM_SUBFOLDER}"
    files = [
        {"url": f"{base_url}/{fname}", "dest": os.path.join(dest_dir, fname), "checksum": None}
        for fname in LLM_FILES
    ]
    return files, dest_dir


def resolve_catalogue_entry(opds_name: str, opds_flavour: str | None = None,
                             lang: str = "eng", timeout: int = 15) -> dict:
    """
    Look up the current download URL/size for a Kiwix catalogue book by its
    stable `name` (and optional `flavour` to disambiguate mini/nopic/maxi).
    Returns {"url": str, "size": int, "title": str}. Raises CatalogueError
    if nothing matches or the request fails.
    """
    params = {"name": opds_name, "lang": lang, "count": 50}
    resp = requests.get(CATALOG_URL, params=params, timeout=timeout)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    for entry in root.findall(f"{_ATOM_NS}entry"):
        flavour = _text(entry, "flavour") or None
        if opds_flavour is not None and flavour != opds_flavour:
            continue

        link = _find_acquisition_link(entry)
        if link is None:
            continue

        url = link.attrib["href"]
        if url.endswith(".meta4"):
            url = url[: -len(".meta4")]

        return {
            "url":   url,
            "size":  int(link.attrib.get("length", 0)),
            "title": _text(entry, "title") or opds_name,
        }

    raise CatalogueError(f"No catalogue entry found for name={opds_name!r} flavour={opds_flavour!r}")


def search_catalogue(query: str, lang: str = "eng", count: int = 20, timeout: int = 15) -> list[dict]:
    """
    Search the live Kiwix library for the admin's "Discover Content" page.
    Returns a list of {"name", "flavour", "title", "summary", "language",
    "article_count", "url", "size"} dicts.
    """
    params = {"q": query, "lang": lang, "count": count}
    resp = requests.get(CATALOG_URL, params=params, timeout=timeout)
    resp.raise_for_status()

    root = ET.fromstring(resp.content)
    results = []
    for entry in root.findall(f"{_ATOM_NS}entry"):
        link = _find_acquisition_link(entry)
        if link is None:
            continue
        url = link.attrib["href"]
        if url.endswith(".meta4"):
            url = url[: -len(".meta4")]

        results.append({
            "name":          _text(entry, "name"),
            "flavour":       _text(entry, "flavour"),
            "title":         _text(entry, "title"),
            "summary":       _text(entry, "summary"),
            "language":      _text(entry, "language"),
            "article_count": _int(_text(entry, "articleCount")),
            "url":           url,
            "size":          int(link.attrib.get("length", 0)),
        })
    return results


def refresh_catalogue() -> dict:
    """
    Returns CATALOGUE merged with a live-resolved url/size per entry, falling
    back to the last-known-good static URL (with unknown size) if the live
    lookup fails for a given item.
    """
    resolved = {}
    for key, item in CATALOGUE.items():
        merged = dict(item)
        try:
            live = resolve_catalogue_entry(item["opds_name"], item.get("opds_flavour"))
            merged["url"] = live["url"]
            merged["size"] = live["size"]
            merged["live"] = True
        except Exception as exc:
            merged["url"] = _FALLBACK_URLS.get(key)
            merged["size"] = 0
            merged["live"] = False
            merged["error"] = str(exc)
        merged["dest"] = os.path.join(DOWNLOAD_DIR, f"{key}.zim")
        resolved[key] = merged
    return resolved


def _find_acquisition_link(entry) -> ET.Element | None:
    for link in entry.findall(f"{_ATOM_NS}link"):
        if link.attrib.get("rel") == _ACQUISITION_REL:
            return link
    return None


def _text(entry, tag: str) -> str | None:
    el = entry.find(f"{_ATOM_NS}{tag}")
    return el.text if el is not None else None


def _int(value: str | None) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


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
            existing = os.path.getsize(part_file) if os.path.exists(part_file) else 0
            headers  = {"Range": f"bytes={existing}-"} if existing else {}

            with requests.get(url, headers=headers, stream=True, timeout=30) as r:
                r.raise_for_status()

                if r.headers.get("Content-Range"):
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

            if checksum:
                if not _verify_sha256(part_file, checksum):
                    os.remove(part_file)
                    if done_cb:
                        done_cb(False, dest)
                    return

            if os.path.exists(dest):
                os.remove(dest)
            os.rename(part_file, dest)

            if done_cb:
                done_cb(True, dest)

        except Exception as exc:
            print(f"[Downloader] Error downloading {url}: {exc}")
            if done_cb:
                done_cb(False, dest)

    def download_set(
        self,
        files:       list[dict],   # [{"url":..., "dest":..., "checksum": None}, ...]
        dest_dir:    str,
        progress_cb: Callable[[float, float], None] | None = None,
        done_cb:     Callable[[bool, str], None] | None    = None,
    ):
        """
        Sequentially downloads several files into `dest_dir` (used for LLM
        models, which ship as multiple files). Aggregates progress across
        the whole set. Calls done_cb(success, dest_dir) once, at the end.
        """
        os.makedirs(dest_dir, exist_ok=True)
        total_files = len(files)

        for i, f in enumerate(files):
            file_failed = []

            def file_progress(pct, speed_kbps, i=i):
                overall = (i + pct / 100) / total_files * 100
                if progress_cb:
                    progress_cb(overall, speed_kbps)

            def file_done(success, path):
                if not success:
                    file_failed.append(True)

            self.download(f["url"], f["dest"], file_progress, file_done, f.get("checksum"))

            if file_failed:
                if done_cb:
                    done_cb(False, dest_dir)
                return

        if done_cb:
            done_cb(True, dest_dir)


def _verify_sha256(path: str, expected: str) -> bool:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest().lower() == expected.lower()
