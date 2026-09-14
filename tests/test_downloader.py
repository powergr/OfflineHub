import errno
import hashlib
import os
from unittest.mock import patch

import pytest
import requests

from core.downloader import Downloader, _friendly_error


class FakeResponse:
    """Stands in for requests.get(..., stream=True)'s context-manager result."""

    def __init__(self, content: bytes, headers: dict, ok: bool = True):
        self.content_bytes = content
        self.headers = headers
        self._ok = ok

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if not self._ok:
            raise requests.HTTPError("simulated HTTP error")

    def iter_content(self, chunk_size):
        for i in range(0, len(self.content_bytes), chunk_size):
            yield self.content_bytes[i : i + chunk_size]


@pytest.fixture
def downloader():
    return Downloader()


def test_download_success_writes_file_and_calls_done_cb(downloader, tmp_path):
    content = b"hello offline hub"
    dest = str(tmp_path / "file.zim")
    results = {}

    def fake_get(url, headers=None, stream=None, timeout=None):
        return FakeResponse(content, {"Content-Length": str(len(content))})

    with patch("core.downloader.requests.get", side_effect=fake_get):
        downloader.download(
            "http://example.test/file.zim", dest,
            done_cb=lambda success, path, error=None: results.update(success=success, path=path),
        )

    assert results == {"success": True, "path": dest}
    assert open(dest, "rb").read() == content
    assert not os.path.exists(dest + ".part")


def test_download_progress_callback_reaches_100(downloader, tmp_path):
    content = b"x" * 1000
    dest = str(tmp_path / "file.zim")
    pcts = []

    def fake_get(url, headers=None, stream=None, timeout=None):
        return FakeResponse(content, {"Content-Length": str(len(content))})

    with patch("core.downloader.requests.get", side_effect=fake_get):
        downloader.download(
            "http://example.test/file.zim", dest,
            progress_cb=lambda pct, speed: pcts.append(pct),
        )

    assert pcts[-1] == 100


def test_download_resumes_with_range_header(downloader, tmp_path):
    dest = str(tmp_path / "file.zim")
    part = dest + ".part"
    with open(part, "wb") as f:
        f.write(b"already-here-")  # 13 bytes already downloaded

    rest = b"rest-of-file"
    captured_headers = {}

    def fake_get(url, headers=None, stream=None, timeout=None):
        captured_headers.update(headers or {})
        return FakeResponse(rest, {"Content-Range": f"bytes 13-24/{13 + len(rest)}"})

    with patch("core.downloader.requests.get", side_effect=fake_get):
        downloader.download("http://example.test/file.zim", dest)

    assert captured_headers.get("Range") == "bytes=13-"
    assert open(dest, "rb").read() == b"already-here-" + rest


def test_download_checksum_mismatch_removes_partial_and_fails(downloader, tmp_path):
    content = b"tampered content"
    dest = str(tmp_path / "file.zim")
    results = {}

    def fake_get(url, headers=None, stream=None, timeout=None):
        return FakeResponse(content, {"Content-Length": str(len(content))})

    with patch("core.downloader.requests.get", side_effect=fake_get):
        downloader.download(
            "http://example.test/file.zim", dest,
            done_cb=lambda success, path, error=None: results.update(success=success, path=path, error=error),
            checksum="0" * 64,  # deliberately wrong
        )

    assert results["success"] is False
    assert not os.path.exists(dest)
    assert not os.path.exists(dest + ".part")
    assert "checksum" in results["error"].lower()


def test_download_checksum_match_succeeds(downloader, tmp_path):
    content = b"correct content"
    real_checksum = hashlib.sha256(content).hexdigest()
    dest = str(tmp_path / "file.zim")
    results = {}

    def fake_get(url, headers=None, stream=None, timeout=None):
        return FakeResponse(content, {"Content-Length": str(len(content))})

    with patch("core.downloader.requests.get", side_effect=fake_get):
        downloader.download(
            "http://example.test/file.zim", dest,
            done_cb=lambda success, path, error=None: results.update(success=success),
            checksum=real_checksum,
        )

    assert results["success"] is True
    assert open(dest, "rb").read() == content


def test_download_http_error_calls_done_cb_false(downloader, tmp_path):
    dest = str(tmp_path / "file.zim")
    results = {}

    def fake_get(url, headers=None, stream=None, timeout=None):
        return FakeResponse(b"", {}, ok=False)

    with patch("core.downloader.requests.get", side_effect=fake_get):
        downloader.download(
            "http://example.test/file.zim", dest,
            done_cb=lambda success, path, error=None: results.update(success=success, error=error),
        )

    assert results["success"] is False
    assert not os.path.exists(dest)
    assert "network error" in results["error"].lower()


def test_download_set_stops_on_first_failure(downloader, tmp_path):
    calls = []

    def fake_get(url, headers=None, stream=None, timeout=None):
        calls.append(url)
        if url == "http://example.test/2":
            return FakeResponse(b"", {}, ok=False)
        return FakeResponse(b"data", {"Content-Length": "4"})

    files = [
        {"url": "http://example.test/1", "dest": str(tmp_path / "1.bin")},
        {"url": "http://example.test/2", "dest": str(tmp_path / "2.bin")},
        {"url": "http://example.test/3", "dest": str(tmp_path / "3.bin")},
    ]
    results = {}

    with patch("core.downloader.requests.get", side_effect=fake_get):
        downloader.download_set(
            files, str(tmp_path),
            done_cb=lambda success, path, error=None: results.update(success=success, error=error),
        )

    assert results["success"] is False
    assert calls == ["http://example.test/1", "http://example.test/2"]  # never reached file 3
    assert results["error"] is not None


def test_download_set_all_succeed(downloader, tmp_path):
    def fake_get(url, headers=None, stream=None, timeout=None):
        return FakeResponse(b"data", {"Content-Length": "4"})

    files = [
        {"url": "http://example.test/1", "dest": str(tmp_path / "1.bin")},
        {"url": "http://example.test/2", "dest": str(tmp_path / "2.bin")},
    ]
    results = {}

    with patch("core.downloader.requests.get", side_effect=fake_get):
        downloader.download_set(
            files, str(tmp_path),
            done_cb=lambda success, path, error=None: results.update(success=success),
        )

    assert results["success"] is True
    assert os.path.exists(str(tmp_path / "1.bin"))
    assert os.path.exists(str(tmp_path / "2.bin"))


def test_download_disk_full_gives_friendly_message_and_keeps_part_file(downloader, tmp_path):
    """A disk-full mid-write must surface "Not enough disk space", not a raw
    OSError traceback, and must leave the .part file in place so a later
    retry can resume instead of starting the whole download over."""
    dest = str(tmp_path / "file.zim")
    results = {}

    class DiskFullResponse(FakeResponse):
        def iter_content(self, chunk_size):
            yield b"partial-data"
            raise OSError(errno.ENOSPC, "No space left on device")

    def fake_get(url, headers=None, stream=None, timeout=None):
        return DiskFullResponse(b"", {"Content-Length": "999999"})

    with patch("core.downloader.requests.get", side_effect=fake_get):
        downloader.download(
            "http://example.test/file.zim", dest,
            done_cb=lambda success, path, error=None: results.update(success=success, error=error),
        )

    assert results["success"] is False
    assert "disk space" in results["error"].lower()
    assert os.path.exists(dest + ".part")
    assert open(dest + ".part", "rb").read() == b"partial-data"


def test_friendly_error_disk_full():
    exc = OSError(errno.ENOSPC, "No space left on device")
    assert "disk space" in _friendly_error(exc).lower()


def test_friendly_error_permission_denied():
    exc = PermissionError(errno.EACCES, "Permission denied")
    exc.filename = r"C:\OfflineHub\downloads\x.zim"
    assert "permission denied" in _friendly_error(exc).lower()


def test_friendly_error_network_error():
    exc = requests.ConnectionError("could not connect")
    assert "network error" in _friendly_error(exc).lower()


def test_friendly_error_generic_exception_falls_back_to_str():
    exc = ValueError("something else broke")
    assert _friendly_error(exc) == "something else broke"
