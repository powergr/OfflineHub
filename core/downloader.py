"""
Downloader: resumable HTTP downloads with progress callbacks and checksum
verification, plus live resolution of current Kiwix ZIM download URLs.

Kiwix rotates dated snapshot filenames and deletes old ones (e.g.
wikipedia_en_all_mini_2025-12.zim eventually 404s once a newer snapshot
replaces it), so URLs are resolved live against Kiwix's OPDS v2 catalog
(https://library.kiwix.org/catalog/v2/entries) instead of being hardcoded.
"""

import errno
import hashlib
import logging
import os
import threading
import time
import xml.etree.ElementTree as ET
from typing import Callable

import requests

logger = logging.getLogger(__name__)

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
# "all" ZIM for it (no small subject-specific version exists anymore),
# unreasonable as a "quick start" button. Use search_catalogue() instead to
# let the admin browse the live library and see real sizes before choosing.

CATALOGUE: dict[str, dict] = {
    "wikipedia_en_mini": {
        "name":        "Wikipedia (English, Mini)",
        "emoji":       "📚",
        "description": "Top Wikipedia articles, text only, no images.",
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
    "vikidia_en": {
        "name":        "Vikidia",
        "emoji":       "🧒",
        "description": "A kids' encyclopedia written for ~8-13 year olds.",
        "opds_name":   "vikidia_en_all",
        "opds_flavour": "maxi",
        "server":      "zim",
    },
    "wikipedia_en_simple": {
        "name":        "Wikipedia (Simple English)",
        "emoji":       "🔤",
        "description": "Simplified vocabulary and shorter sentences, good for younger or ESL readers.",
        "opds_name":   "wikipedia_en-simple_all",
        "opds_flavour": "mini",
        "server":      "zim",
    },
    "phet_simulations": {
        "name":        "PhET Interactive Simulations",
        "emoji":       "🧪",
        "description": "Free interactive science & math simulations from University of Colorado Boulder.",
        "opds_name":   "phet_en_all",
        "opds_flavour": None,
        "server":      "zim",
    },
    "wikibooks_en": {
        "name":        "Wikibooks",
        "emoji":       "📓",
        "description": "Collaboratively written textbooks and study guides across subjects.",
        "opds_name":   "wikibooks_en_all",
        "opds_flavour": "maxi",
        "server":      "zim",
    },
    "wiktionary_en_simple": {
        "name":        "Wiktionary (Simple English)",
        "emoji":       "📔",
        "description": "A basic dictionary with simplified definitions.",
        "opds_name":   "wiktionary_en-simple_all",
        "opds_flavour": "nopic",
        "server":      "zim",
    },

    # ── Non-English (Phase 3: "more content variety") ───────────────────────
    # Checked live against the Kiwix catalog before adding rather than
    # guessed - e.g. there's no non-English "mini" flavour of every language
    # some only ship "maxi"/"nopic", and sizes vary a lot by language
    # (Spanish/French each have ~4M articles, so "mini" is still ~3.5GB,
    # nowhere near English "mini"'s ~12GB but not small either). Paired each
    # language with its own Vikidia (kids' encyclopedia), which is a much
    # smaller, easy first download in that language.
    "wikipedia_es_mini": {
        "name":        "Wikipedia (Spanish, Mini)",
        "emoji":       "🇪🇸",
        "description": "Top Spanish Wikipedia articles, text only, no images.",
        "opds_name":   "wikipedia_es_all",
        "opds_flavour": "mini",
        "lang":        "spa",
        "server":      "zim",
    },
    "vikidia_es": {
        "name":        "Vikidia (Spanish)",
        "emoji":       "🧒",
        "description": "A kids' encyclopedia in Spanish, written for ~8-13 year olds.",
        "opds_name":   "vikidia_es_all",
        "opds_flavour": "nopic",
        "lang":        "spa",
        "server":      "zim",
    },
    "wikipedia_fr_mini": {
        "name":        "Wikipedia (French, Mini)",
        "emoji":       "🇫🇷",
        "description": "Top French Wikipedia articles, text only, no images.",
        "opds_name":   "wikipedia_fr_all",
        "opds_flavour": "mini",
        "lang":        "fra",
        "server":      "zim",
    },
    "vikidia_fr": {
        "name":        "Vikidia (French)",
        "emoji":       "🧒",
        "description": "A kids' encyclopedia in French, written for ~8-13 year olds.",
        "opds_name":   "vikidia_fr_all",
        "opds_flavour": "nopic",
        "lang":        "fra",
        "server":      "zim",
    },

    # ── Subject-specific (Phase 3: "more subject-specific content beyond
    # PhET") ─────────────────────────────────────────────────────────────
    # Kiwix curates dozens of subject-filtered Wikipedia slices; checked
    # live for which subjects actually exist rather than assuming ("civics"
    # and "art" specifically do NOT exist as of this check - "history",
    # "mathematics", and "chemistry" do). Picked the smallest flavour
    # (nopic/mini) that still keeps real article counts, matching how the
    # existing wikipedia_en_mini/wiktionary_en_simple entries above already
    # favor a light footprint over the full-image "maxi" builds.
    "wikipedia_en_history": {
        "name":        "Wikipedia (History)",
        "emoji":       "📜",
        "description": "224,000+ history articles, from ancient civilizations to modern events.",
        "opds_name":   "wikipedia_en_history",
        "opds_flavour": "nopic",
        "server":      "zim",
    },
    "wikipedia_en_mathematics": {
        "name":        "Wikipedia (Mathematics)",
        "emoji":       "🔢",
        "description": "112,000+ mathematics articles, from arithmetic to advanced topics.",
        "opds_name":   "wikipedia_en_mathematics",
        "opds_flavour": "mini",
        "server":      "zim",
    },
    "wikipedia_en_chemistry": {
        "name":        "Wikipedia (Chemistry)",
        "emoji":       "⚗️",
        "description": "57,000+ chemistry articles, from the periodic table to organic chemistry.",
        "opds_name":   "wikipedia_en_chemistry",
        "opds_flavour": "mini",
        "server":      "zim",
    },
}

# Recommended "install everything a normal school wants" default, used by
# the single "Install Starter Bundle" button so a new admin doesn't have to
# individually evaluate all six Quick Start cards on day one. Deliberately
# NOT wikipedia_en_mini - checked its real live-resolved size while picking
# this list and "mini" is still ~12GB (no images, but still every article),
# a surprising default for a "day one, don't think about it" button.
# wikipedia_en_simple (~450MB, Simple English's much smaller article set)
# + gutenberg literature + a kids' encyclopedia + a small dictionary
# together land around ~1.2GB - a sensible default that still covers
# general reference, literature, and a younger-reader-friendly source.
STARTER_BUNDLE_KEYS: list[str] = [
    "wikipedia_en_simple", "gutenberg_lcc_l", "vikidia_en", "wiktionary_en_simple",
]

# Last-known-good fallback, used only if the live OPDS lookup fails (e.g. no
# internet at that moment, or the API changes shape). May go stale over time
# like the old hardcoded catalogue did. It's a safety net, not the primary path.
_FALLBACK_URLS = {
    "wikipedia_en_mini":   "https://download.kiwix.org/zim/wikipedia/wikipedia_en_all_mini_2026-06.zim",
    "gutenberg_lcc_l":     "https://download.kiwix.org/zim/gutenberg/gutenberg_en_lcc-l_2026-03.zim",
    "vikidia_en":          "https://download.kiwix.org/zim/vikidia/vikidia_en_all_maxi_2026-06.zim",
    "wikipedia_en_simple": "https://download.kiwix.org/zim/wikipedia/wikipedia_en-simple_all_mini_2026-06.zim",
    "phet_simulations":    "https://download.kiwix.org/zim/phet/phet_en_all_2026-08.zim",
    "wikibooks_en":        "https://download.kiwix.org/zim/wikibooks/wikibooks_en_all_maxi_2026-04.zim",
    "wiktionary_en_simple": "https://download.kiwix.org/zim/wiktionary/wiktionary_en-simple_all_nopic_2026-07.zim",
    "wikipedia_es_mini":    "https://lb.download.kiwix.org/zim/wikipedia/wikipedia_es_all_mini_2026-08.zim",
    "vikidia_es":           "https://lb.download.kiwix.org/zim/vikidia/vikidia_es_all_nopic_2026-09.zim",
    "wikipedia_fr_mini":    "https://lb.download.kiwix.org/zim/wikipedia/wikipedia_fr_all_mini_2026-05.zim",
    "vikidia_fr":           "https://lb.download.kiwix.org/zim/vikidia/vikidia_fr_all_nopic_2026-09.zim",
    "wikipedia_en_history": "https://lb.download.kiwix.org/zim/wikipedia/wikipedia_en_history_nopic_2026-07.zim",
    "wikipedia_en_mathematics": "https://lb.download.kiwix.org/zim/wikipedia/wikipedia_en_mathematics_mini_2026-06.zim",
    "wikipedia_en_chemistry": "https://lb.download.kiwix.org/zim/wikipedia/wikipedia_en_chemistry_mini_2026-07.zim",
}

# ── Offline LLM (onnxruntime-genai model) ────────────────────────────────────
# Model files ship as several files under one Hugging Face repo path, unlike
# a ZIM's single file, hence a separate small catalogue + Downloader.download_set().
# Each entry carries its OWN repo/subfolder/file list (rather than one shared
# constant) because different model repos use different onnx filenames (some
# ship "model.onnx", others "phi3-mini-4k-instruct-....onnx") and different
# subfolder layouts. File lists and sizes below were checked live against
# each repo's file tree this session. Hugging Face repos do get reorganized
# over time, so if one ever starts 404ing, check that repo's current file
# tree before assuming the code is at fault. All three are ungated/MIT or
# Apache-licensed public repos (no HF login/token needed to download).
#
# Sizes are ordered smallest-to-largest so the download panel (which lists
# LLM_CATALOGUE in dict order) shows the easy option first and the heaviest
# last; "assistant_phi4_mini" is flagged recommended as the best quality/size
# tradeoff for a typical PC (~5GB disk, 8GB+ RAM). The Qwen2.5 0.5B option
# was removed - answers were too weak to be useful in practice.

LLM_CATALOGUE: dict[str, dict] = {
    "assistant_phi3_mini": {
        "name":        "Offline Assistant: Phi-3-mini 3.8B (~2.7 GB)",
        "emoji":       "🤖",
        "description": "Noticeably smarter than the 0.5B model at a modest size. A good "
                        "middle ground if you want better answers but limited disk space.",
        "size":        2_725_547_235,
        "repo":        "microsoft/Phi-3-mini-4k-instruct-onnx",
        "subfolder":   "cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4",
        "files": [
            "added_tokens.json", "config.json", "configuration_phi3.py", "genai_config.json",
            "phi3-mini-4k-instruct-cpu-int4-rtn-block-32-acc-level-4.onnx",
            "phi3-mini-4k-instruct-cpu-int4-rtn-block-32-acc-level-4.onnx.data",
            "special_tokens_map.json", "tokenizer.json", "tokenizer.model", "tokenizer_config.json",
        ],
    },
    "assistant_phi4_mini": {
        "name":        "Offline Assistant: Phi-4-mini 3.8B (~4.9 GB, recommended)",
        "emoji":       "⭐",
        "description": "Newer and noticeably better quality than Phi-3-mini at a similar "
                        "parameter count. Recommended default for most PCs (~5GB disk, 8GB+ RAM).",
        "size":        4_930_563_630,
        "repo":        "microsoft/Phi-4-mini-instruct-onnx",
        "subfolder":   "cpu_and_mobile/cpu-int4-rtn-block-32-acc-level-4",
        "files": [
            "added_tokens.json", "config.json", "configuration_phi3.py", "genai_config.json",
            "merges.txt", "model.onnx", "model.onnx.data", "special_tokens_map.json",
            "tokenizer.json", "tokenizer_config.json", "vocab.json",
        ],
    },
    "assistant_phi3_medium": {
        "name":        "Offline Assistant: Phi-3-medium 14B (~9.3 GB, largest)",
        "emoji":       "🏋️",
        "description": "The best answer quality of these options, but needs a capable "
                        "PC (16GB+ RAM) and is noticeably slower per reply.",
        "size":        9_285_363_032,
        "repo":        "microsoft/Phi-3-medium-4k-instruct-onnx-cpu",
        "subfolder":   "cpu-int4-rtn-block-32-acc-level-4",
        "files": [
            "added_tokens.json", "config.json", "configuration_phi3.py", "genai_config.json",
            "phi3-medium-4k-instruct-cpu-int4-rtn-block-32-acc-level-4.onnx",
            "phi3-medium-4k-instruct-cpu-int4-rtn-block-32-acc-level-4.onnx.data",
            "special_tokens_map.json", "tokenizer.json", "tokenizer.model", "tokenizer_config.json",
        ],
    },
}

# ── Offline maps (curated .mbtiles downloads) ────────────────────────────────
# Built from Protomaps' free daily OpenStreetMap basemap build via
# tools/build_map_packs.py (see that file for why there's no "whole
# continent" option: a real continent at useful zoom is tens of GB, and no
# free no-account service hosts ready continent-sized files the way Kiwix
# does for ZIM content). Hosted on Google Drive rather than resolved live
# like CATALOGUE, since there's no equivalent OPDS-style catalog for these -
# the URLs below already carry Drive's "confirm=t" large-file bypass,
# confirmed against every one of these six files (Range/resume, exact
# Content-Length, no virus-scan interstitial) before being pasted in here.
MAPS_CATALOGUE: dict[str, dict] = {
    "map_world_overview": {
        "name":        "Map: World (overview)",
        "emoji":       "🗺️",
        "description": "Low-detail whole-world map - country outlines and major borders, no street detail.",
        "size":        47_063_040,
        "url":         "https://drive.usercontent.google.com/download?id=175XC8PxwGaiP8OkIbh2y9raEBA9JOASY&export=download&confirm=t",
    },
    "map_uk": {
        "name":        "Map: United Kingdom",
        "emoji":       "🗺️",
        "description": "Offline vector map of the United Kingdom, roads and cities down to town level.",
        "size":        360_099_840,
        "url":         "https://drive.usercontent.google.com/download?id=1nhNDE4MUqbOeVz2rIpw830O1xwkbkq6r&export=download&confirm=t",
    },
    "map_japan": {
        "name":        "Map: Japan",
        "emoji":       "🗺️",
        "description": "Offline vector map of Japan's main islands, roads and cities down to town level.",
        "size":        439_545_856,
        "url":         "https://drive.usercontent.google.com/download?id=19-a61dQ0OGf6s3nxuHfrIvooF1T-0rH9&export=download&confirm=t",
    },
    "map_germany": {
        "name":        "Map: Germany",
        "emoji":       "🗺️",
        "description": "Offline vector map of Germany, roads and cities down to town level.",
        "size":        886_685_696,
        "url":         "https://drive.usercontent.google.com/download?id=1hhydSvmw80FjtXaWU8LOEQFxaQo9V-A7&export=download&confirm=t",
    },
    "map_france": {
        "name":        "Map: France",
        "emoji":       "🗺️",
        "description": "Offline vector map of metropolitan France, roads and cities down to town level.",
        "size":        1_132_564_480,
        "url":         "https://drive.usercontent.google.com/download?id=1hMM5f4bU-YflgBzzd1T0w-rGNkV56C1W&export=download&confirm=t",
    },
    "map_usa": {
        "name":        "Map: United States (contiguous)",
        "emoji":       "🗺️",
        "description": "Offline vector map of the contiguous United States, roads and cities down to town level.",
        "size":        2_044_141_568,
        "url":         "https://drive.usercontent.google.com/download?id=116LMKyRfj1Ms2LJFfHfLMhWi-nF53OIy&export=download&confirm=t",
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

    entry = LLM_CATALOGUE[key]
    dest_dir = os.path.join(DOWNLOAD_DIR, key)
    base_url = f"https://huggingface.co/{entry['repo']}/resolve/main/{entry['subfolder']}"
    files = [
        {"url": f"{base_url}/{fname}", "dest": os.path.join(dest_dir, fname), "checksum": None}
        for fname in entry["files"]
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


# refresh_catalogue() used to do a live HTTP request per CATALOGUE entry on
# every single call (one per key: currently 14, growing as more are added),
# with no caching at all - confirmed live to be the actual cause of "the
# Modules page takes a long time to open," since both setup() and modules()
# call it fresh on every page load. Cached here for _CATALOGUE_CACHE_TTL so
# repeat page loads within that window are instant, while still refreshing
# automatically often enough to catch a real newer Kiwix snapshot.
_CATALOGUE_CACHE_TTL = 300  # seconds
_catalogue_cache: dict | None = None
_catalogue_cache_at: float = 0.0


def refresh_catalogue(force: bool = False) -> dict:
    """
    Returns CATALOGUE merged with a live-resolved url/size per entry, falling
    back to the last-known-good static URL (with unknown size) if the live
    lookup fails for a given item. Cached for _CATALOGUE_CACHE_TTL seconds;
    pass force=True to bypass the cache and re-resolve every entry live.
    """
    global _catalogue_cache, _catalogue_cache_at
    now = time.monotonic()
    if not force and _catalogue_cache is not None and (now - _catalogue_cache_at) < _CATALOGUE_CACHE_TTL:
        return _catalogue_cache

    resolved = {}
    for key, item in CATALOGUE.items():
        merged = dict(item)
        try:
            live = resolve_catalogue_entry(
                item["opds_name"], item.get("opds_flavour"), lang=item.get("lang", "eng")
            )
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

    _catalogue_cache = resolved
    _catalogue_cache_at = now
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
    done_cb(success: bool, path: str, error: str | None = None)

    On failure, `error` is a plain-English message (not a raw traceback) -
    e.g. disk-full is reported as "Not enough disk space..." rather than
    whatever OSError.__str__ happens to say. The partially-downloaded
    `.part` file is deliberately left in place on any I/O/network failure
    (as opposed to the checksum-mismatch case below, where it's deleted
    because it's actively wrong) so a later retry can resume from where it
    stopped instead of re-downloading from zero.
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
                        done_cb(False, dest, "Downloaded file failed checksum verification "
                                             "- it may be corrupted. Try downloading again.")
                    return

            if os.path.exists(dest):
                os.remove(dest)
            os.rename(part_file, dest)

            if done_cb:
                done_cb(True, dest)

        except Exception as exc:
            message = _friendly_error(exc)
            logger.error("Error downloading %s: %s", url, exc)
            if done_cb:
                done_cb(False, dest, message)

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
            file_error = []

            def file_progress(pct, speed_kbps, i=i):
                overall = (i + pct / 100) / total_files * 100
                if progress_cb:
                    progress_cb(overall, speed_kbps)

            def file_done(success, path, error=None):
                if not success:
                    file_failed.append(True)
                    file_error.append(error)

            self.download(f["url"], f["dest"], file_progress, file_done, f.get("checksum"))

            if file_failed:
                if done_cb:
                    done_cb(False, dest_dir, file_error[0] if file_error else None)
                return

        if done_cb:
            done_cb(True, dest_dir)


def _friendly_error(exc: Exception) -> str:
    """
    Turns a raw exception into a plain-English message a non-technical
    school admin can act on, instead of a Python traceback. Disk-full is
    the specific case this was written for (OSError.__str__ for ENOSPC is
    just "[Errno 28] No space left on device: '...'"), but network errors
    get a friendlier prefix too since requests' own messages are verbose.
    """
    if isinstance(exc, OSError):
        if exc.errno == errno.ENOSPC:
            return "Not enough disk space to finish this download. Free up space and try again."
        if exc.errno == errno.EACCES:
            return f"Permission denied writing to '{exc.filename or 'the destination folder'}'. Check folder permissions and try again."
    if isinstance(exc, requests.RequestException):
        return f"Network error: {exc}"
    return str(exc)


def _verify_sha256(path: str, expected: str) -> bool:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            sha.update(block)
    return sha.hexdigest().lower() == expected.lower()
