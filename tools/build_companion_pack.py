"""
build_companion_pack: assembles a downloadable "companion zip" of pre-fetched
content modules, for testing (or distributing) without re-downloading the
same files every time C:\\OfflineHub gets wiped.

No app code changes were needed for this: ModuleManager.list_modules() already
scans modules/ for any folder with a manifest.json at startup, so a zip that
unpacks to C:\\OfflineHub\\modules\\<key>\\manifest.json + content\\... is
auto-detected on next launch. This script just assembles that folder layout
using the same catalogue/downloader code the app itself uses, then zips it.

Run from the repo root:
    python tools/build_companion_pack.py [--out DEST.zip] [--staging DIR]
"""

import argparse
import json
import os
import shutil
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.downloader import (  # noqa: E402
    CATALOGUE, LLM_CATALOGUE, CatalogueError,
    Downloader, llm_download_plan, resolve_catalogue_entry,
)

# The "minimum viable school" bundle agreed on: general reference, a kids'
# encyclopedia, a dictionary, interactive science, and a small offline
# assistant. Gutenberg (literature, ~630MB) was dropped from this list on
# request: the full bundle was measured at 2.22GB, over Dropbox's 2GB
# single-file limit on free accounts, and Gutenberg was the easiest module
# to cut without losing a core reference tool (encyclopedia/dictionary/
# science stay in). Confirmed by measuring the actual downloaded module
# folders in C:\OfflineHub\modules, not by estimating: dropping it brings
# the total to ~1.59GB, leaving headroom for Kiwix's dated snapshots
# growing slightly release over release.
ZIM_KEYS = [
    "wikipedia_en_simple",
    "vikidia_en",
    "wiktionary_en_simple",
    "phet_simulations",
]
LLM_KEYS = [
    "assistant_qwen_0_5b",
]


def _progress_printer(label: str):
    last = [-10.0]

    def cb(pct: float, speed_kbps: float):
        if pct - last[0] >= 5 or pct >= 100:
            last[0] = pct
            print(f"  {label}: {pct:5.1f}%  ({speed_kbps/1024:.1f} MB/s)", flush=True)

    return cb


def build_zim_module(key: str, staging_dir: str, downloader: Downloader):
    item = CATALOGUE[key]
    print(f"[{key}] resolving live download URL...")
    live = resolve_catalogue_entry(item["opds_name"], item.get("opds_flavour"))
    url = live["url"]
    filename = url.rsplit("/", 1)[-1]

    mod_dir = os.path.join(staging_dir, key)
    content_dir = os.path.join(mod_dir, "content")
    os.makedirs(content_dir, exist_ok=True)
    dest = os.path.join(content_dir, filename)

    print(f"[{key}] downloading {filename} ({live['size'] / 1_073_741_824:.2f} GB)...")
    result = {}

    def done_cb(success, path):
        result["success"] = success

    downloader.download(url, dest, _progress_printer(key), done_cb)
    if not result.get("success"):
        raise RuntimeError(f"Download failed for {key}")

    manifest = {
        "name": item["name"],
        "emoji": item["emoji"],
        "type": "zim",
        "description": item.get("description", ""),
    }
    with open(os.path.join(mod_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"[{key}] done.\n")


def build_llm_module(key: str, staging_dir: str, downloader: Downloader):
    item = LLM_CATALOGUE[key]
    files, _default_dest_dir = llm_download_plan(key)

    mod_dir = os.path.join(staging_dir, key)
    content_dir = os.path.join(mod_dir, "content")
    os.makedirs(content_dir, exist_ok=True)
    # llm_download_plan() points at C:\OfflineHub\downloads\<key> by default;
    # redirect each file's dest into our staging content/ dir instead.
    for f in files:
        f["dest"] = os.path.join(content_dir, os.path.basename(f["dest"]))

    print(f"[{key}] downloading {len(files)} files ({item['size'] / 1_073_741_824:.2f} GB total)...")
    result = {}

    def done_cb(success, path):
        result["success"] = success

    downloader.download_set(files, content_dir, _progress_printer(key), done_cb)
    if not result.get("success"):
        raise RuntimeError(f"Download failed for {key}")

    manifest = {
        "name": item["name"],
        "emoji": item.get("emoji", "🤖"),
        "type": "llm",
        "description": item.get("description", ""),
    }
    with open(os.path.join(mod_dir, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    print(f"[{key}] done.\n")


def zip_staging(staging_dir: str, out_path: str):
    print(f"Zipping into {out_path} ...")
    if os.path.exists(out_path):
        os.remove(out_path)
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_STORED) as zf:
        # ZIM/model files are already compressed; ZIP_STORED avoids wasting
        # time re-compressing multi-GB files that won't shrink further.
        for root, _dirs, files in os.walk(staging_dir):
            for fname in files:
                full = os.path.join(root, fname)
                arcname = os.path.join("modules", os.path.relpath(full, staging_dir))
                zf.write(full, arcname)
    size_gb = os.path.getsize(out_path) / 1_073_741_824
    print(f"Done: {out_path} ({size_gb:.2f} GB)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="OfflineHub_CompanionPack.zip")
    parser.add_argument("--staging", default=None, help="Staging dir (default: a temp dir next to --out)")
    args = parser.parse_args()

    staging_dir = args.staging or (os.path.splitext(args.out)[0] + "_staging")
    os.makedirs(staging_dir, exist_ok=True)

    downloader = Downloader()
    t0 = time.time()

    for key in ZIM_KEYS:
        build_zim_module(key, staging_dir, downloader)
    for key in LLM_KEYS:
        build_llm_module(key, staging_dir, downloader)

    zip_staging(staging_dir, args.out)
    shutil.rmtree(staging_dir, ignore_errors=True)

    print(f"\nTotal time: {(time.time() - t0) / 60:.1f} min")
    print(f"Unzip {args.out} directly into C:\\OfflineHub\\ (so it creates")
    print("C:\\OfflineHub\\modules\\<key>\\...). Modules are picked up automatically")
    print("the next time the app starts.")


if __name__ == "__main__":
    main()
