"""
build_map_packs: builds the curated offline map .mbtiles files (a small
global default set: USA, UK, Germany, France, Japan, plus a low-detail world
overview) from Protomaps' free, no-login daily basemap build.

Why this exists instead of a "download the whole continent" button: a real
continent at useful zoom is tens of GB (the whole planet at zoom 0-15 is
~138GB per Protomaps' own build), and no free, no-account service hosts
ready continent-sized files the way Kiwix does for ZIM content. What does
exist is Protomaps' free bounding-box extract of its daily planet build
(https://build.protomaps.com/YYYYMMDD.pmtiles) - this script extracts each
region, then converts the result from .pmtiles (a flat single-file format)
to .mbtiles (SQLite), which is what core/tileserver.py actually reads.

Prerequisites (not in requirements.txt - this is a content-authoring tool,
not an app runtime dependency):
    pip install pmtiles
    the `pmtiles` CLI (https://github.com/protomaps/go-pmtiles/releases)
    somewhere on PATH, or pass --pmtiles-exe to point at it directly.

Verified against the live source before writing this: `pmtiles show --metadata`
on the real daily build confirmed its vector_layers are named earth/roads/
buildings/water/landcover/landuse/boundaries/places/pois - matching the
"-tz"-suffixed layers already in templates/portal/index.html's map style
(added a "boundaries-tz" layer there too, the one name that was missing).

Run from the repo root:
    python tools/build_map_packs.py [--out-dir C:\\OfflineHub\\downloads\\maps]
"""

import argparse
import os
import shutil
import sqlite3
import subprocess
import sys
from datetime import date, timedelta

from pmtiles.reader import MmapSource, Reader, all_tiles  # pip install pmtiles

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from core.map_extract import write_mbtiles_schema  # shared mbtiles-schema writer

SOURCE_URL_TEMPLATE = "https://build.protomaps.com/{date}.pmtiles"

# bbox = min_lon, min_lat, max_lon, max_lat. Deliberately mainland-only for
# USA/France (contiguous US, metropolitan France) and main-islands-only for
# Japan/UK - matches how an "national map" is conventionally scoped, and
# keeps file sizes reasonable (full USA incl. Alaska/Hawaii would be one
# huge mostly-ocean bbox for little extra content).
REGIONS = {
    "map_uk":             {"name": "United Kingdom", "bbox": (-8.649, 49.823, 1.763, 60.845), "maxzoom": 12},
    "map_germany":        {"name": "Germany",         "bbox": (5.866, 47.270, 15.042, 55.099), "maxzoom": 12},
    "map_france":         {"name": "France",          "bbox": (-5.142, 41.333, 9.560, 51.124), "maxzoom": 12},
    "map_japan":          {"name": "Japan",           "bbox": (122.7, 24.0, 153.99, 45.7),     "maxzoom": 12},
    "map_usa":            {"name": "United States (contiguous)", "bbox": (-125, 24, -66, 49),  "maxzoom": 12},
    "map_world_overview": {"name": "World (overview)", "bbox": (-180, -85, 180, 85),            "maxzoom": 6},
}


def _find_recent_build(pmtiles_exe: str) -> str:
    """Protomaps publishes a daily build; try today back to 7 days ago."""
    import urllib.request

    for days_ago in range(8):
        d = (date.today() - timedelta(days=days_ago)).strftime("%Y%m%d")
        url = SOURCE_URL_TEMPLATE.format(date=d)
        try:
            req = urllib.request.Request(url, method="HEAD")
            with urllib.request.urlopen(req, timeout=10) as resp:
                if resp.status == 200:
                    return url
        except Exception:
            continue
    raise RuntimeError("No recent Protomaps daily build found in the last 8 days.")


def _extract(pmtiles_exe: str, source_url: str, bbox, maxzoom: int, out_pmtiles: str):
    subprocess.run(
        [pmtiles_exe, "extract", source_url, out_pmtiles,
         "--bbox", ",".join(str(v) for v in bbox),
         "--minzoom", "0", "--maxzoom", str(maxzoom)],
        check=True,
    )


def _convert_to_mbtiles(pmtiles_path: str, mbtiles_path: str):
    """pmtiles CLI only converts mbtiles->pmtiles, not the reverse, so this
    reads tiles directly via the pmtiles Python package and writes a plain
    MBTiles sqlite db per https://github.com/mapbox/mbtiles-spec."""
    if os.path.exists(mbtiles_path):
        os.remove(mbtiles_path)

    with open(pmtiles_path, "rb") as f:
        get_bytes = MmapSource(f)
        reader = Reader(get_bytes)
        header = reader.header()
        meta = reader.metadata()

        bounds = (header["min_lon_e7"] / 1e7, header["min_lat_e7"] / 1e7,
                  header["max_lon_e7"] / 1e7, header["max_lat_e7"] / 1e7)
        conn = sqlite3.connect(mbtiles_path)
        write_mbtiles_schema(conn, bounds, header["max_zoom"], meta,
                              meta.get("name", os.path.basename(mbtiles_path)))

        batch = []
        for (z, x, y), data in all_tiles(get_bytes):
            y_tms = (2 ** z - 1) - y  # MBTiles uses TMS y-axis, pmtiles uses XYZ
            batch.append((z, x, y_tms, data))
            if len(batch) >= 5000:
                conn.executemany("INSERT INTO tiles VALUES (?, ?, ?, ?)", batch)
                batch.clear()
        if batch:
            conn.executemany("INSERT INTO tiles VALUES (?, ?, ?, ?)", batch)

        conn.commit()
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", default=r"C:\OfflineHub\downloads\maps")
    parser.add_argument("--pmtiles-exe", default="pmtiles", help="Path to the pmtiles CLI binary")
    parser.add_argument("--staging", default=None, help="Staging dir for intermediate .pmtiles files")
    parser.add_argument("--only", nargs="*", help="Subset of REGIONS keys to build (default: all)")
    args = parser.parse_args()

    os.makedirs(args.out_dir, exist_ok=True)
    staging = args.staging or os.path.join(args.out_dir, "_staging")
    os.makedirs(staging, exist_ok=True)

    print("Finding the most recent Protomaps daily build...")
    source_url = _find_recent_build(args.pmtiles_exe)
    print(f"Using {source_url}")

    keys = args.only or list(REGIONS.keys())
    for key in keys:
        region = REGIONS[key]
        pmtiles_path = os.path.join(staging, f"{key}.pmtiles")
        mbtiles_path = os.path.join(args.out_dir, f"{key}.mbtiles")

        print(f"[{key}] extracting {region['name']} (maxzoom={region['maxzoom']})...")
        _extract(args.pmtiles_exe, source_url, region["bbox"], region["maxzoom"], pmtiles_path)

        print(f"[{key}] converting to mbtiles...")
        _convert_to_mbtiles(pmtiles_path, mbtiles_path)

        size_mb = os.path.getsize(mbtiles_path) / 1_048_576
        print(f"[{key}] done: {mbtiles_path} ({size_mb:.0f} MB)\n")

    shutil.rmtree(staging, ignore_errors=True)
    print("All map packs built.")


if __name__ == "__main__":
    main()
