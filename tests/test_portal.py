"""
Tests core/blueprints/portal.py's Range-request handling for ZIM content
(_serve_zim_range / _range_not_satisfiable) directly against a fake reader,
covering the actual HTTP Range semantics: normal ranges, open-ended ranges,
suffix ranges, and the 416 edge cases - no Flask app/request context or real
.zim file needed, since these are plain functions taking a reader and a
header string.
"""

from core.blueprints.portal import _range_not_satisfiable, _serve_zim_range


class _FakeReader:
    def __init__(self, content: bytes, mimetype: str = "video/mp4"):
        self.content = content
        self.mimetype = mimetype

    def entry_info(self, path):
        if path != "video.mp4":
            return None
        return len(self.content), self.mimetype

    def resolve_range(self, path, start, end):
        return self.content[start : end + 1]


def _reader():
    return _FakeReader(bytes(range(100)))  # 100 bytes, values 0..99


def test_normal_range_returns_206_with_exact_slice():
    response = _serve_zim_range(_reader(), "video.mp4", "bytes=10-19")
    assert response.status_code == 206
    assert response.get_data() == bytes(range(10, 20))
    assert response.headers["Content-Range"] == "bytes 10-19/100"
    assert response.headers["Accept-Ranges"] == "bytes"
    assert response.headers["Content-Length"] == "10"
    assert response.mimetype == "video/mp4"


def test_open_ended_range_goes_to_the_end():
    response = _serve_zim_range(_reader(), "video.mp4", "bytes=90-")
    assert response.status_code == 206
    assert response.get_data() == bytes(range(90, 100))
    assert response.headers["Content-Range"] == "bytes 90-99/100"


def test_suffix_range_returns_last_n_bytes():
    """"bytes=-500" means "the last 500 bytes" - a real form browsers use,
    not just start-end pairs."""
    response = _serve_zim_range(_reader(), "video.mp4", "bytes=-10")
    assert response.status_code == 206
    assert response.get_data() == bytes(range(90, 100))
    assert response.headers["Content-Range"] == "bytes 90-99/100"


def test_suffix_range_longer_than_content_clamps_to_whole_thing():
    response = _serve_zim_range(_reader(), "video.mp4", "bytes=-1000")
    assert response.status_code == 206
    assert response.get_data() == bytes(range(100))
    assert response.headers["Content-Range"] == "bytes 0-99/100"


def test_end_beyond_content_length_clamps_to_last_byte():
    response = _serve_zim_range(_reader(), "video.mp4", "bytes=95-999")
    assert response.status_code == 206
    assert response.get_data() == bytes(range(95, 100))
    assert response.headers["Content-Range"] == "bytes 95-99/100"


def test_start_past_end_of_content_is_416():
    response = _serve_zim_range(_reader(), "video.mp4", "bytes=200-300")
    assert response.status_code == 416
    assert response.headers["Content-Range"] == "bytes */100"


def test_malformed_range_header_is_416():
    response = _serve_zim_range(_reader(), "video.mp4", "not-a-range-header")
    assert response.status_code == 416


def test_empty_bytes_equals_bytes_is_416():
    """"bytes=-" (no start, no end) isn't a valid range in either direction."""
    response = _serve_zim_range(_reader(), "video.mp4", "bytes=-")
    assert response.status_code == 416


def test_unknown_path_returns_none_not_a_response():
    """The caller (content_page()) is responsible for 404ing when this
    returns None - a missing entry isn't a Range-specific concern."""
    assert _serve_zim_range(_reader(), "does-not-exist.mp4", "bytes=0-10") is None


def test_zero_length_content_is_416():
    response = _serve_zim_range(_FakeReader(b""), "video.mp4", "bytes=0-10")
    assert response.status_code == 416
    assert response.headers["Content-Range"] == "bytes */0"


def test_range_not_satisfiable_sets_content_range_and_status():
    response = _range_not_satisfiable(42)
    assert response.status_code == 416
    assert response.headers["Content-Range"] == "bytes */42"
