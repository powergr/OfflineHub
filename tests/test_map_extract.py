"""
Tests core/map_extract.py: the pure bbox/tile-count math (no network), and
extract_country() against a fake pmtiles Reader (no real network, no real
Protomaps build) so the mbtiles-writing/progress-reporting logic is
verified without depending on the live internet.
"""

import os
import sqlite3
import threading

import pytest
import requests

from core.map_extract import (
    DEFAULT_MAX_ZOOM,
    _HTTP_MAX_RETRIES,
    ExtractionCancelled,
    _HttpRangeSource,
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
        if (z, x, y) in _FAKE_FAILURES:
            raise requests.exceptions.ReadTimeout("fake timeout")
        if (z, x, y) in _FAKE_TILES:
            return _FAKE_TILES[(z, x, y)]
        return None


_FAKE_TILES = {}
_FAKE_FAILURES = set()


@pytest.fixture(autouse=True)
def _patch_reader(monkeypatch):
    monkeypatch.setattr("core.map_extract.Reader", _FakeReader)
    monkeypatch.setattr("core.map_extract.find_daily_build_url", lambda: "https://example.test/fake.pmtiles")
    _FAKE_TILES.clear()
    _FAKE_FAILURES.clear()
    yield
    _FAKE_TILES.clear()
    _FAKE_FAILURES.clear()


def _all_coords(bbox):
    coords = []
    for z in range(0, DEFAULT_MAX_ZOOM + 1):
        x0, x1, y0, y1 = tile_range(bbox, z)
        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                coords.append((z, x, y))
    return coords


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


# ── Regression tests: a real admin report of a 30-minute extraction dying
# on a single read timeout, then a retry hitting a locked leftover file ──

def test_extract_country_tolerates_a_few_failed_tiles(tmp_path):
    """A handful of tiles failing (simulating a transient network hiccup
    that survives every retry) must not abort the whole extraction -
    confirmed live to matter: a single read timeout among thousands of
    tile fetches used to kill an entire 20-30 minute extraction outright."""
    countries = load_countries()
    _name, bbox = countries["LU"]
    coords = _all_coords(bbox)
    for coord in coords:
        _FAKE_TILES[coord] = b"data"
    for coord in coords[:2]:  # a small fraction, well under the threshold
        _FAKE_FAILURES.add(coord)
        del _FAKE_TILES[coord]

    dest = str(tmp_path / "lu.mbtiles")
    result = extract_country("LU", dest)

    assert result["failed_tiles"] == 2
    assert os.path.exists(dest)


def test_extract_country_raises_and_cleans_up_when_too_many_tiles_fail(tmp_path):
    """More than _MAX_FAILED_TILE_FRACTION of tiles failing must raise
    instead of silently installing a mostly-blank map, and must not leave
    a partial .mbtiles file behind for a retry to trip over."""
    countries = load_countries()
    _name, bbox = countries["LU"]
    for coord in _all_coords(bbox):
        _FAKE_FAILURES.add(coord)  # fail everything

    dest = str(tmp_path / "lu.mbtiles")
    with pytest.raises(RuntimeError):
        extract_country("LU", dest)

    assert not os.path.exists(dest)


def test_extract_country_retry_after_failure_does_not_hit_a_locked_file(tmp_path):
    """Regression test for a real report: a failed extraction used to
    leave its sqlite connection open (conn.close() only ran on the
    success path), so a second attempt at the same destination path
    failed with WinError 32 ('used by another process') instead of just
    being able to try again."""
    countries = load_countries()
    _name, bbox = countries["LU"]
    coords = _all_coords(bbox)
    for coord in coords:
        _FAKE_FAILURES.add(coord)

    dest = str(tmp_path / "lu.mbtiles")
    with pytest.raises(RuntimeError):
        extract_country("LU", dest)
    assert not os.path.exists(dest)

    # Now fix the "network" and retry against the exact same path a real
    # admin would use clicking "Download" again - must succeed cleanly,
    # not raise a file-in-use error from the previous attempt's connection.
    _FAKE_FAILURES.clear()
    for coord in coords:
        _FAKE_TILES[coord] = b"data"

    result = extract_country("LU", dest)

    assert os.path.exists(dest)
    assert result["failed_tiles"] == 0


class _FakeResponse:
    def __init__(self, content: bytes):
        self.content = content

    def raise_for_status(self):
        pass


class _FlakySession:
    """A fake requests.Session whose .get() fails a fixed number of times
    before succeeding (or never succeeds), so _HttpRangeSource's own retry
    logic can be tested without any real network call."""

    def __init__(self, fail_times: int):
        self.fail_times = fail_times
        self.calls = 0

    def get(self, url, headers=None, timeout=None):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise requests.exceptions.ReadTimeout("fake timeout")
        return _FakeResponse(b"tile-bytes")


def test_http_range_source_retries_transient_failures_and_succeeds(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a: None)  # don't really wait in tests
    session = _FlakySession(fail_times=_HTTP_MAX_RETRIES - 1)  # fails all but the last attempt
    source = _HttpRangeSource("https://example.test/fake.pmtiles", session=session)

    data = source(0, 10)

    assert data == b"tile-bytes"
    assert session.calls == _HTTP_MAX_RETRIES


def test_http_range_source_raises_after_exhausting_all_retries(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *_a: None)
    session = _FlakySession(fail_times=_HTTP_MAX_RETRIES + 5)  # never succeeds
    source = _HttpRangeSource("https://example.test/fake.pmtiles", session=session)

    with pytest.raises(requests.exceptions.ReadTimeout):
        source(0, 10)

    assert session.calls == _HTTP_MAX_RETRIES


# ── Cancellation ──────────────────────────────────────────────────────────────

def test_extract_country_cancelled_before_starting_raises_and_leaves_no_file(tmp_path):
    countries = load_countries()
    _name, bbox = countries["LU"]
    for coord in _all_coords(bbox):
        _FAKE_TILES[coord] = b"data"

    cancel_event = threading.Event()
    cancel_event.set()  # already cancelled before extraction gets going

    dest = str(tmp_path / "lu.mbtiles")
    with pytest.raises(ExtractionCancelled):
        extract_country("LU", dest, cancel_event=cancel_event)

    assert not os.path.exists(dest)


def test_extract_country_cancelled_mid_extraction_stops_and_cleans_up(tmp_path):
    """Regression test for the admin's own request: cancelling a long
    country extraction must actually stop it (not silently keep running to
    completion in the background) and must not leave a half-written
    .mbtiles file behind - there's no resume support for extraction the
    way a plain HTTP download has, so a cancelled attempt should look
    exactly like it never started."""
    countries = load_countries()
    _name, bbox = countries["LU"]
    for coord in _all_coords(bbox):
        _FAKE_TILES[coord] = b"data"

    cancel_event = threading.Event()
    progress_calls = []

    def progress_cb(pct, _speed):
        progress_calls.append(pct)
        if pct >= 50:
            cancel_event.set()

    dest = str(tmp_path / "lu.mbtiles")
    with pytest.raises(ExtractionCancelled):
        extract_country("LU", dest, progress_cb=progress_cb, cancel_event=cancel_event)

    assert not os.path.exists(dest)
    assert progress_calls, "expected at least some progress before cancellation took effect"
