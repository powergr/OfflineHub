"""
Tests _stale_content_keys() - the "know a newer version exists" half of
content-refresh (see core/blueprints/admin.py). A pure function over plain
data structures, so no Flask app/request context is needed to test it.
"""

from core.blueprints.admin import _stale_content_keys
from core.downloader import MAPS_CATALOGUE


def _installed(folder, mod_type, source_url):
    return (folder, {"type": mod_type, "source_url": source_url}, "loaded")


def test_zim_flagged_when_live_url_differs_from_installed_source():
    installed = [_installed("wikipedia_en_mini", "zim", "https://old.example/wp_2026-01.zim")]
    quickstart = {"wikipedia_en_mini": {"live": True, "url": "https://old.example/wp_2026-06.zim"}}
    assert _stale_content_keys(installed, quickstart) == {"wikipedia_en_mini"}


def test_zim_not_flagged_when_urls_match():
    installed = [_installed("wikipedia_en_mini", "zim", "https://example/wp_2026-06.zim")]
    quickstart = {"wikipedia_en_mini": {"live": True, "url": "https://example/wp_2026-06.zim"}}
    assert _stale_content_keys(installed, quickstart) == set()


def test_zim_not_flagged_when_live_lookup_failed():
    """A failed live lookup falls back to a static last-known-good URL that
    can legitimately differ from what's installed for reasons having
    nothing to do with a real newer version existing - must not be
    reported as "stale" just because the two URLs happen to differ."""
    installed = [_installed("wikipedia_en_mini", "zim", "https://example/wp_2026-06.zim")]
    quickstart = {"wikipedia_en_mini": {"live": False, "url": "https://fallback.example/wp_2025-12.zim"}}
    assert _stale_content_keys(installed, quickstart) == set()


def test_manual_install_without_source_url_is_never_flagged():
    installed = [_installed("my_custom_zim", "zim", None)]
    quickstart = {"my_custom_zim": {"live": True, "url": "https://example/whatever.zim"}}
    assert _stale_content_keys(installed, quickstart) == set()


def test_map_flagged_when_maps_catalogue_url_differs(monkeypatch):
    monkeypatch.setitem(MAPS_CATALOGUE, "map_uk", {"url": "https://example/map_uk_v2.mbtiles"})
    installed = [_installed("map_uk", "mbtiles", "https://example/map_uk_v1.mbtiles")]
    assert _stale_content_keys(installed, {}) == {"map_uk"}


def test_map_not_flagged_when_urls_match(monkeypatch):
    monkeypatch.setitem(MAPS_CATALOGUE, "map_uk", {"url": "https://example/map_uk_v1.mbtiles"})
    installed = [_installed("map_uk", "mbtiles", "https://example/map_uk_v1.mbtiles")]
    assert _stale_content_keys(installed, {}) == set()


def test_module_with_no_matching_catalogue_entry_is_not_flagged():
    installed = [_installed("some_removed_catalogue_item", "zim", "https://example/x.zim")]
    assert _stale_content_keys(installed, {}) == set()


def test_only_stale_modules_are_returned_from_a_mixed_list():
    installed = [
        _installed("fresh", "zim", "https://example/fresh.zim"),
        _installed("stale", "zim", "https://example/stale_old.zim"),
        _installed("manual", "zim", None),
    ]
    quickstart = {
        "fresh": {"live": True, "url": "https://example/fresh.zim"},
        "stale": {"live": True, "url": "https://example/stale_new.zim"},
    }
    assert _stale_content_keys(installed, quickstart) == {"stale"}
