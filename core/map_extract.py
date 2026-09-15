"""
map_extract: pure-Python, self-serve extraction of a single country's map
tiles from Protomaps' free, no-login daily global basemap build
(https://build.protomaps.com/YYYYMMDD.pmtiles), written straight to a local
.mbtiles file - the same format core/tileserver.py already reads.

Exists so an admin can pick literally any country in the Admin "Maps" tab,
not just the 6 pre-built regions in MAPS_CATALOGUE. tools/build_map_packs.py
(a maintainer-only dev tool, never shipped) does the same underlying job by
shelling out to the `pmtiles` Go CLI's `extract` command - fine on a dev
machine, but a Go binary can't be bundled into the shipped app without
breaking this project's "no vendor binaries" design. Verified before
writing this: the official `pmtiles` Python package (protomaps/PMTiles) has
no extract() of its own, but Reader.get(z, x, y) accepts any
get_bytes(offset, length) source, which is exactly the shape of an HTTP
Range request - so bbox extraction is reimplemented here in pure Python
instead of needing the Go binary at all.

Country list: core/data/country_bboxes.json, vendored from
https://github.com/sandstrom/country-bounding-boxes (Unlicense/public
domain). 173 countries as {"FR": ["France", [min_lon, min_lat, max_lon,
max_lat]]}. Some entries (Russia, France, USA...) include remote
territories or span the antimeridian - a known simplification of that free
dataset. pick_maxzoom() below auto-reduces detail for any country whose
tile count balloons as a result, instead of attempting an impractical
download.

Performance note, confirmed by reading the actual Reader.get() source: it
re-fetches the 127-byte header and walks up to 4 directory levels on every
single call, with no caching of its own. Fetching thousands of tiles
one at a time, sequentially, with no caching would be far too slow (hours
for a mid-sized country). _HttpRangeSource below adds the two things
Reader.get() doesn't: a same-process byte-range cache (most tiles share
the same root/near-root directory nodes) and concurrent fetches via a
thread pool.
"""

import json
import math
import os
import sqlite3
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import requests
from pmtiles.reader import Reader

_HERE = os.path.dirname(os.path.abspath(__file__))
COUNTRIES_PATH = os.path.join(_HERE, "data", "country_bboxes.json")

SOURCE_URL_TEMPLATE = "https://build.protomaps.com/{date}.pmtiles"
_BUILD_URL_CACHE_TTL = 3600  # seconds
_build_url_cache: str | None = None
_build_url_cache_at: float = 0.0

# 15 is the live Protomaps daily build's own actual maximum zoom (confirmed
# via its header, not assumed) - raised from an earlier 12 after a real
# admin report: a country extracted at z12 opened real gaps once zoomed
# past that level (see the frontend maxzoom fix in templates/portal/
# index.html), and separately z12 is too shallow for this app's own road-
# label and POI layers, which don't start rendering until z13/z15 - a
# capital city extracted at the old ceiling could never show a single POI
# regardless of the gap issue, since minzoom: 13/15 on those layers simply
# excluded them entirely at z12.
DEFAULT_MAX_ZOOM = 15
# Confirmed live: a real end-to-end extraction of Luxembourg (139 tiles at
# the old z12 ceiling) through the actual admin route completed in ~10s,
# but a real France extraction (a far larger, less spatially-compact bbox)
# took much longer than that throughput would predict - directory-node
# cache reuse (see _HttpRangeSource) is far less effective across a big,
# spread-out area than a small one. Raising the ceiling to 15 multiplies
# tile counts roughly 4x per extra zoom level (confirmed via the exact
# tile-count math, not estimated), so this budget is sized to let small/
# city-state-sized countries (Cyprus, Luxembourg, and a handful more) reach
# the new full z15 ceiling, while larger countries auto-reduce via
# pick_maxzoom() the same way they did before, just from a higher starting
# point.
DEFAULT_TILE_BUDGET = 20_000

# Deliberately approximate - see module docstring. Real bytes/tile varies
# 2.9-42x across the existing curated packs depending on how much of a
# country's bbox rectangle is empty ocean vs. dense urban data; this is a
# conservative middle estimate, not a guaranteed size.
_BYTES_PER_TILE_ESTIMATE = 12 * 1024

CONCURRENCY = 48
_BATCH_SIZE = 2000


def load_countries() -> dict:
    """{"FR": ["France", [min_lon, min_lat, max_lon, max_lat]], ...}"""
    with open(COUNTRIES_PATH, encoding="utf-8") as f:
        return json.load(f)


def find_daily_build_url(force: bool = False) -> str:
    """
    Protomaps publishes a new global build daily; try today back to 7 days
    ago, the same approach as tools/build_map_packs.py's _find_recent_build.
    Cached for _BUILD_URL_CACHE_TTL so repeat calls (e.g. every time the
    country list is requested) don't re-probe every time.
    """
    global _build_url_cache, _build_url_cache_at
    now = time.monotonic()
    if not force and _build_url_cache is not None and (now - _build_url_cache_at) < _BUILD_URL_CACHE_TTL:
        return _build_url_cache

    for days_ago in range(8):
        d = (date.today() - timedelta(days=days_ago)).strftime("%Y%m%d")
        url = SOURCE_URL_TEMPLATE.format(date=d)
        try:
            resp = requests.head(url, timeout=10)
            if resp.status_code == 200:
                _build_url_cache = url
                _build_url_cache_at = now
                return url
        except requests.RequestException:
            continue
    raise RuntimeError("No recent Protomaps daily build found in the last 8 days.")


def _lon2tile(lon: float, z: int) -> int:
    return max(0, min(2 ** z - 1, int((lon + 180.0) / 360.0 * (2 ** z))))


def _lat2tile(lat: float, z: int) -> int:
    lat = max(min(lat, 85.0511), -85.0511)  # clamp to Web Mercator's valid range
    lat_rad = math.radians(lat)
    n = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0
    return max(0, min(2 ** z - 1, int(n * (2 ** z))))


def tile_range(bbox, z: int) -> tuple[int, int, int, int]:
    """Returns (x_min, x_max, y_min, y_max) tile coordinates covering bbox at zoom z."""
    min_lon, min_lat, max_lon, max_lat = bbox
    x0, x1 = sorted([_lon2tile(min_lon, z), _lon2tile(max_lon, z)])
    y0, y1 = sorted([_lat2tile(max_lat, z), _lat2tile(min_lat, z)])
    return x0, x1, y0, y1


def _tile_count_up_to(bbox, maxzoom: int) -> int:
    total = 0
    for z in range(0, maxzoom + 1):
        x0, x1, y0, y1 = tile_range(bbox, z)
        total += (x1 - x0 + 1) * (y1 - y0 + 1)
    return total


def pick_maxzoom(bbox, max_tiles: int = DEFAULT_TILE_BUDGET,
                  ceiling: int = DEFAULT_MAX_ZOOM) -> tuple[int, int]:
    """
    Starts at `ceiling` (matching the existing curated MAPS_CATALOGUE packs)
    and steps down while the summed tile count from z=0..zoom exceeds
    max_tiles, so a huge country (or one whose free-dataset bbox spans the
    antimeridian, like Russia) auto-reduces detail instead of an
    impractical download. Returns (maxzoom, tile_count_at_that_maxzoom).
    """
    zoom = ceiling
    count = _tile_count_up_to(bbox, zoom)
    while count > max_tiles and zoom > 0:
        zoom -= 1
        count = _tile_count_up_to(bbox, zoom)
    return zoom, count


def estimate_size_mb(tile_count: int) -> float:
    return (tile_count * _BYTES_PER_TILE_ESTIMATE) / 1_048_576


class _HttpRangeSource:
    """
    get_bytes(offset, length) backed by HTTP Range requests against a
    single remote pmtiles URL, with a small same-process cache - most tile
    fetches share the same root/near-root directory nodes and the 127-byte
    header, so caching those avoids re-fetching them on every single tile
    (confirmed necessary by reading pmtiles.reader.Reader.get()'s actual
    source: it has no caching of its own and re-fetches the header on every
    call). Thread-safe: called concurrently from a thread pool.
    """

    def __init__(self, url: str, session: requests.Session | None = None):
        self.url = url
        if session is None:
            # requests' default HTTPAdapter caps its connection pool at 10
            # per host - confirmed live to silently bottleneck this class's
            # whole point (many concurrent range requests) far below
            # CONCURRENCY's actual thread count, however many workers a
            # caller spins up. Sized generously since these are small,
            # short-lived range requests, not sustained transfers.
            session = requests.Session()
            adapter = requests.adapters.HTTPAdapter(pool_connections=64, pool_maxsize=64)
            session.mount("https://", adapter)
            session.mount("http://", adapter)
        self.session = session
        self._cache: dict[tuple[int, int], bytes] = {}
        self._lock = threading.Lock()

    def __call__(self, offset: int, length: int) -> bytes:
        key = (offset, length)
        with self._lock:
            cached = self._cache.get(key)
        if cached is not None:
            return cached

        resp = self.session.get(
            self.url,
            headers={"Range": f"bytes={offset}-{offset + length - 1}"},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.content

        with self._lock:
            self._cache[key] = data
        return data


def write_mbtiles_schema(conn: sqlite3.Connection, bounds: tuple, maxzoom: int,
                          meta: dict, name: str):
    """
    Creates the metadata/tiles tables per https://github.com/mapbox/mbtiles-spec
    and inserts the metadata row. Shared with tools/build_map_packs.py so
    the two pmtiles-to-mbtiles conversion paths (maintainer's offline build
    vs. this module's live in-app extraction) don't duplicate the schema.
    `bounds` and `maxzoom` are passed in explicitly rather than read off a
    pmtiles header, since this module never materializes an intermediate
    .pmtiles file for the extracted subset - the header available here is
    the remote *source* planet build's header (the whole world), not the
    extracted country's own bounds.
    """
    conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    conn.execute(
        "CREATE TABLE tiles (zoom_level INTEGER, tile_column INTEGER, "
        "tile_row INTEGER, tile_data BLOB)"
    )
    conn.execute("CREATE UNIQUE INDEX tile_index ON tiles (zoom_level, tile_column, tile_row)")

    kv = {
        "name": name,
        "format": "pbf",
        "type": "baselayer",
        "version": "1",
        "description": meta.get("description", ""),
        "attribution": meta.get("attribution", ""),
        "minzoom": "0",
        "maxzoom": str(maxzoom),
        "bounds": ",".join(str(round(b, 6)) for b in bounds),
        "json": json.dumps({"vector_layers": meta.get("vector_layers", [])}),
    }
    conn.executemany("INSERT INTO metadata VALUES (?, ?)", kv.items())


def extract_country(iso: str, dest_mbtiles_path: str, progress_cb=None,
                     max_tiles: int = DEFAULT_TILE_BUDGET) -> dict:
    """
    Extracts one country's tiles from the live Protomaps daily build
    straight into dest_mbtiles_path. progress_cb(pct: float, _unused: float)
    is called periodically, matching Downloader.download()'s callback shape
    so the existing JobTracker (core/jobs.py) works unchanged. Returns
    {"tile_count", "maxzoom", "name"}.
    """
    countries = load_countries()
    if iso not in countries:
        raise ValueError(f"Unknown country code: {iso!r}")
    name, bbox = countries[iso]

    maxzoom, _ = pick_maxzoom(bbox, max_tiles=max_tiles)

    source_url = find_daily_build_url()
    source = _HttpRangeSource(source_url)
    reader = Reader(source)
    reader.header()  # pre-warms the header cache before concurrent fetches start
    meta = reader.metadata()

    if os.path.exists(dest_mbtiles_path):
        os.remove(dest_mbtiles_path)
    os.makedirs(os.path.dirname(dest_mbtiles_path), exist_ok=True)
    conn = sqlite3.connect(dest_mbtiles_path)
    write_mbtiles_schema(conn, bbox, maxzoom, meta, name)

    coords = []
    for z in range(0, maxzoom + 1):
        x0, x1, y0, y1 = tile_range(bbox, z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                coords.append((z, x, y))
    total = len(coords)

    def fetch(coord):
        z, x, y = coord
        return coord, reader.get(z, x, y)

    done = 0
    batch = []
    lock = threading.Lock()

    with ThreadPoolExecutor(max_workers=CONCURRENCY) as executor:
        futures = [executor.submit(fetch, c) for c in coords]
        for future in as_completed(futures):
            (z, x, y), data = future.result()
            with lock:
                if data is not None:
                    y_tms = (2 ** z - 1) - y  # MBTiles uses TMS y-axis, pmtiles uses XYZ
                    batch.append((z, x, y_tms, data))
                    if len(batch) >= _BATCH_SIZE:
                        conn.executemany("INSERT INTO tiles VALUES (?, ?, ?, ?)", batch)
                        conn.commit()
                        batch.clear()
                done += 1
                if progress_cb and (done % 200 == 0 or done == total):
                    progress_cb(done / total * 100 if total else 100.0, 0)

    if batch:
        conn.executemany("INSERT INTO tiles VALUES (?, ?, ?, ?)", batch)
        conn.commit()
    conn.close()

    return {"tile_count": total, "maxzoom": maxzoom, "name": name}
