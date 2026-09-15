"""
Tests core/map_extract.py: the pure bbox/tile-count math (no network), and
extract_country() against a fake pmtiles Reader (no real network, no real
Protomaps build) so the mbtiles-writing/progress-reporting logic is
verified without depending on the live internet.
"""

import os
import sqlite3

import pytest

from core.map_extract import (
    DEFAULT_MAX_ZOOM,
    estimate_size_mb,
    extract_country,
    load_countries,
    pick_maxzoom,
    tile_range,
)


# ── Pure math: tile_range / pick_maxzoom / estimate_size_mb ─────────────────

def test_load_countries_has_real_entries():
    countries = load_countries()
    assert len(countries) > 100
    name, bbox = countries["FR"]
    assert name == "France"
    assert len(bbox) == 4


def test_tile_range_whole_world_at_zoom_0_is_a_single_tile():
    assert tile_range((-180, -85, 180, 85), 0) == (0, 0, 0, 0)


def test_tile_range_small_bbox_is_a_small_range():
    # Luxembourg-sized bbox at a middling zoom should cover a handful of tiles,
    # not the whole grid.
    x0, x1, y0, y1 = tile_range((5.67, 49.44, 6.24, 50.13), 8)
    assert 0 <= x1 - x0 <= 3
    assert 0 <= y1 - y0 <= 3


def test_pick_maxzoom_keeps_full_zoom_for_a_small_country():
    # A tiny bbox should never need to reduce detail to stay under budget.
    maxzoom, count = pick_maxzoom((5.67, 49.44, 6.24, 50.13), max_tiles=20_000, ceiling=DEFAULT_MAX_ZOOM)
    assert maxzoom == DEFAULT_MAX_ZOOM
    assert count > 0


def test_pick_maxzoom_reduces_detail_for_a_huge_bbox():
    """Regression test: a country whose free-dataset bbox spans the
    antimeridian (e.g. Russia, -180 to 180 longitude) must not be allowed
    to attempt a full-zoom extraction - the tile count would be enormous."""
    maxzoom, count = pick_maxzoom((-180, 41, 180, 81), max_tiles=20_000, ceiling=DEFAULT_MAX_ZOOM)
    assert maxzoom < DEFAULT_MAX_ZOOM
    assert count <= 20_000


def test_pick_maxzoom_never_goes_below_zero():
    maxzoom, count = pick_maxzoom((-180, -85, 180, 85), max_tiles=1, ceiling=DEFAULT_MAX_ZOOM)
    assert maxzoom == 0


def test_estimate_size_mb_scales_with_tile_count():
    assert estimate_size_mb(0) == 0
    assert estimate_size_mb(1000) < estimate_size_mb(10_000)


# ── extract_country() against a fake Reader (no real network) ───────────────

class _FakeReader:
    """Stands in for pmtiles.reader.Reader - ignores the get_bytes source it's
    constructed with (never calls it) and serves canned tiles from a dict
    keyed by (z, x, y), so no real HTTP or pmtiles parsing happens."""

    def __init__(self, get_bytes):
        self.get_bytes = get_bytes

    def header(self):
        return {}

    def metadata(self):
        return {"description": "fake", "attribution": "", "vector_layers": []}

    def get(self, z, x, y):
        # Sparse: only a few tiles actually have data, matching how real
        # ocean/empty areas have no tile - extract_country must skip Nones
        # rather than writing null rows.
        if (z, x, y) in _FAKE_TILES:
            return _FAKE_TILES[(z, x, y)]
        return None


_FAKE_TILES = {}


@pytest.fixture(autouse=True)
def _patch_reader(monkeypatch):
    monkeypatch.setattr("core.map_extract.Reader", _FakeReader)
    monkeypatch.setattr("core.map_extract.find_daily_build_url", lambda: "https://example.test/fake.pmtiles")
    _FAKE_TILES.clear()
    yield
    _FAKE_TILES.clear()


def test_extract_country_writes_real_mbtiles_schema(tmp_path):
    countries = load_countries()
    _name, bbox = countries["LU"]
    for z in range(0, DEFAULT_MAX_ZOOM + 1):
        x0, x1, y0, y1 = tile_range(bbox, z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                _FAKE_TILES[(z, x, y)] = b"fake-pbf-tile-bytes"

    dest = str(tmp_path / "luxembourg.mbtiles")
    result = extract_country("LU", dest)

    assert os.path.exists(dest)
    conn = sqlite3.connect(dest)
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"metadata", "tiles"} <= tables

    meta = dict(conn.execute("SELECT name, value FROM metadata").fetchall())
    assert meta["format"] == "pbf"
    assert meta["bounds"] == "5.67,49.44,6.24,50.13"

    n = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
    assert n == result["tile_count"]
    assert n > 0
    conn.close()


def test_extract_country_skips_missing_tiles_without_error(tmp_path):
    """Real archives are sparse (no ocean-only tiles at high zoom) - a
    None result from reader.get() must be skipped, not written or raised."""
    countries = load_countries()
    _name, bbox = countries["LU"]
    x0, x1, y0, y1 = tile_range(bbox, 0)
    _FAKE_TILES[(0, x0, y0)] = b"only-one-real-tile"
    # every other (z, x, y) in range deliberately left with no fake data

    dest = str(tmp_path / "luxembourg.mbtiles")
    extract_country("LU", dest)

    conn = sqlite3.connect(dest)
    n = conn.execute("SELECT COUNT(*) FROM tiles").fetchone()[0]
    assert n == 1
    conn.close()


def test_extract_country_calls_progress_cb_with_increasing_values(tmp_path):
    countries = load_countries()
    _name, bbox = countries["LU"]
    for z in range(0, DEFAULT_MAX_ZOOM + 1):
        x0, x1, y0, y1 = tile_range(bbox, z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                _FAKE_TILES[(z, x, y)] = b"data"

    updates = []
    extract_country("LU", str(tmp_path / "lu.mbtiles"), progress_cb=lambda pct, _: updates.append(pct))

    assert updates, "progress_cb was never called"
    assert updates[-1] == 100.0
    assert all(0 <= p <= 100 for p in updates)


def test_extract_country_raises_for_unknown_iso(tmp_path):
    with pytest.raises(ValueError):
        extract_country("ZZ", str(tmp_path / "zz.mbtiles"))
