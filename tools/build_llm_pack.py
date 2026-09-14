"""
build_llm_pack — assembles a standalone downloadable zip of one offline LLM
module, for distribution (e.g. via Google Drive) separately from the
Wikipedia/Gutenberg "companion pack".

Same drop-in format as build_companion_pack.py: unzips into C:\\OfflineHub\\
directly, creating C:\\OfflineHub\\modules\\<key>\\manifest.json + content\\...,
auto-detected by ModuleManager.list_modules() on next launch.

Run from the repo root:
    python tools/build_llm_pack.py [--model KEY] [--out DEST.zip]

KEY defaults to "assistant_phi4_mini" - confirmed the latest small model
Microsoft has exported for onnxruntime-genai as of this session (Phi-4-mini,
Feb 2025, MIT license; no Phi-4.5/Phi-5 onnx-genai export exists yet).
"""

import argparse
import json
import os
import shutil
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.downloader import LLM_CATALOGUE, Downloader, llm_download_plan  # noqa: E402


def _progress_printer(label: str):
    last = [-10.0]

    def cb(pct: float, speed_kbps: float):
        if pct - last[0] >= 5 or pct >= 100:
            last[0] = pct
            print(f"  {label}: {pct:5.1f}%  ({speed_kbps/1024:.1f} MB/s)", flush=True)

    return cb


def build_llm_module(key: str, staging_dir: str, downloader: Downloader):
    item = LLM_CATALOGUE[key]
    files, _default_dest_dir = llm_download_plan(key)

    mod_dir = os.path.join(staging_dir, key)
    content_dir = os.path.join(mod_dir, "content")
    os.makedirs(content_dir, exist_ok=True)
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
        for root, _dirs, files in os.walk(staging_dir):
            for fname in files:
                full = os.path.join(root, fname)
                arcname = os.path.join("modules", os.path.relpath(full, staging_dir))
                zf.write(full, arcname)
    size_gb = os.path.getsize(out_path) / 1_073_741_824
    print(f"Done: {out_path} ({size_gb:.2f} GB)")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default="assistant_phi4_mini", choices=list(LLM_CATALOGUE.keys()))
    parser.add_argument("--out", default=None)
    parser.add_argument("--staging", default=None)
    args = parser.parse_args()

    out_path = args.out or f"OfflineHub_LLM_{args.model}.zip"
    staging_dir = args.staging or (os.path.splitext(out_path)[0] + "_staging")
    os.makedirs(staging_dir, exist_ok=True)

    downloader = Downloader()
    t0 = time.time()

    build_llm_module(args.model, staging_dir, downloader)

    zip_staging(staging_dir, out_path)
    shutil.rmtree(staging_dir, ignore_errors=True)

    print(f"\nTotal time: {(time.time() - t0) / 60:.1f} min")
    print(f"Unzip {out_path} directly into C:\\OfflineHub\\ - modules are picked up")
    print("automatically the next time the app starts.")


if __name__ == "__main__":
    main()
