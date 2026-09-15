"""
update_check: compares the running VERSION against the latest GitHub
release tag (see .github/workflows/release.yml, which tags releases
"vX.Y.Z"). No auto-download, no auto-install - just a "a newer version
exists, here's the link" signal for the admin Settings page, since nothing
in this app should install new code on its own without an admin choosing to.

Cached for _CACHE_SECONDS so the Settings page (and the base-template
banner, which polls on every admin page load) doesn't hit the GitHub API on
every navigation - a school's admin may have Settings open in a background
tab for a long session.
"""

import logging
import time

import requests

logger = logging.getLogger(__name__)

REPO = "powergr/OfflineHub"
RELEASES_API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"

_CACHE_SECONDS = 3600
_cache: dict | None = None
_cache_time = 0.0
_cache_version: str | None = None


def check_for_update(current_version: str, force: bool = False) -> dict | None:
    """
    Returns {"version": str, "url": str} if a newer release is published on
    GitHub, else None (including on any network/parse failure - this must
    never raise, since it's called opportunistically and a missing internet
    connection is the normal case for this app, not an error).
    """
    global _cache, _cache_time, _cache_version

    # Keyed on current_version too, not just a plain time-based cache - a
    # VERSION change mid-process (only realistic case: dev/test, but cheap
    # to get right) must not keep serving a comparison made against the old
    # version for up to an hour.
    if (not force and _cache is not None and _cache_version == current_version
            and (time.time() - _cache_time) < _CACHE_SECONDS):
        return _cache

    result = None
    try:
        resp = requests.get(RELEASES_API_URL, timeout=5,
                             headers={"Accept": "application/vnd.github+json"})
        resp.raise_for_status()
        data = resp.json()
        latest = str(data.get("tag_name", "")).lstrip("vV")
        if latest and _is_newer(latest, current_version):
            result = {"version": latest, "url": data.get("html_url", "")}
    except Exception as e:
        logger.info("Update check failed (this is normal without internet): %s", e)
        result = None

    _cache = result
    _cache_time = time.time()
    _cache_version = current_version
    return result


def _parse_version(v: str) -> tuple[int, ...]:
    parts = []
    for piece in v.split("."):
        digits = "".join(c for c in piece if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts) or (0,)


def _is_newer(candidate: str, current: str) -> bool:
    return _parse_version(candidate) > _parse_version(current)
