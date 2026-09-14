"""
Tests update_check's version comparison and its "never raise, never break
the admin page" contract - a missing internet connection (the normal case
for this app) must resolve to None, not an exception.
"""

from unittest.mock import Mock, patch

import requests

import core.update_check as update_check
from core.update_check import _is_newer, _parse_version, check_for_update


def _reset_cache():
    update_check._cache = None
    update_check._cache_time = 0.0
    update_check._cache_version = None


def test_parse_version_simple():
    assert _parse_version("1.2.3") == (1, 2, 3)


def test_is_newer_true_for_higher_patch():
    assert _is_newer("0.2.6", "0.2.5") is True


def test_is_newer_false_for_equal_version():
    assert _is_newer("0.2.5", "0.2.5") is False


def test_is_newer_false_for_older_version():
    assert _is_newer("0.2.4", "0.2.5") is False


def test_is_newer_handles_different_segment_counts():
    assert _is_newer("0.3", "0.2.9") is True


def test_check_for_update_returns_none_when_up_to_date():
    _reset_cache()
    resp = Mock()
    resp.json.return_value = {"tag_name": "v0.2.5", "html_url": "https://example.test/v0.2.5"}
    resp.raise_for_status = Mock()
    with patch("core.update_check.requests.get", return_value=resp):
        assert check_for_update("0.2.5", force=True) is None


def test_check_for_update_returns_info_when_newer_available():
    _reset_cache()
    resp = Mock()
    resp.json.return_value = {"tag_name": "v0.3.0", "html_url": "https://example.test/v0.3.0"}
    resp.raise_for_status = Mock()
    with patch("core.update_check.requests.get", return_value=resp):
        result = check_for_update("0.2.5", force=True)
    assert result == {"version": "0.3.0", "url": "https://example.test/v0.3.0"}


def test_check_for_update_never_raises_on_network_failure():
    _reset_cache()
    with patch("core.update_check.requests.get", side_effect=requests.ConnectionError("no internet")):
        assert check_for_update("0.2.5", force=True) is None


def test_check_for_update_uses_cache_within_ttl():
    _reset_cache()
    resp = Mock()
    resp.json.return_value = {"tag_name": "v0.3.0", "html_url": "https://example.test/v0.3.0"}
    resp.raise_for_status = Mock()
    with patch("core.update_check.requests.get", return_value=resp) as mock_get:
        check_for_update("0.2.5", force=True)
        check_for_update("0.2.5")  # not forced - should hit the cache, not the network again
        assert mock_get.call_count == 1


def test_check_for_update_cache_does_not_leak_across_version_change():
    """A cached answer computed for one running version must not be served
    back for a different version within the same TTL window - otherwise a
    version change (dev testing, or an update actually being applied)
    could show a stale/wrong comparison for up to an hour."""
    _reset_cache()
    resp = Mock()
    resp.json.return_value = {"tag_name": "v0.3.0", "html_url": "https://example.test/v0.3.0"}
    resp.raise_for_status = Mock()
    with patch("core.update_check.requests.get", return_value=resp) as mock_get:
        result_old = check_for_update("0.0.1")   # 0.3.0 is newer than 0.0.1
        result_new = check_for_update("0.3.0")   # 0.3.0 is NOT newer than itself
        assert result_old == {"version": "0.3.0", "url": "https://example.test/v0.3.0"}
        assert result_new is None
        assert mock_get.call_count == 2  # second call must not reuse the first's cached answer
