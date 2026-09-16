"""
Tests ZimReader.get_text_snippet()'s HTML-stripping logic in isolation.
Bypasses __init__ (which opens a real libzim.Archive - a heavy native
dependency requiring an actual .zim file) via __new__, then monkeypatches
resolve() with canned HTML, since the snippet logic itself is pure text
processing that never touches libzim once resolve() has returned bytes.
"""

from core.zim_reader import ZimReader


def _reader_with_content(content: bytes, mimetype: str = "text/html"):
    reader = ZimReader.__new__(ZimReader)  # skip Archive(path) in __init__
    reader.resolve = lambda path: (content, mimetype)
    return reader


# ── entry_info() / resolve_range(): a fake Archive matching libzim's own
# documented API shape (see this file's own module docstring), so the Range
# logic is verified against something that behaves like the real thing
# without needing an actual .zim file. ──────────────────────────────────────

class _FakeItem:
    def __init__(self, content: bytes, mimetype: str):
        self.content = memoryview(content)
        self.mimetype = mimetype
        self.size = len(content)


class _FakeEntry:
    def __init__(self, item: _FakeItem, is_redirect: bool = False, target: "_FakeEntry | None" = None):
        self._item = item
        self.is_redirect = is_redirect
        self._target = target

    def get_item(self):
        return self._item

    def get_redirect_entry(self):
        return self._target


class _FakeArchive:
    def __init__(self, entries: dict[str, _FakeEntry]):
        self._entries = entries

    def has_entry_by_path(self, path):
        return path in self._entries

    def get_entry_by_path(self, path):
        return self._entries[path]


def _reader_with_archive(entries: dict[str, _FakeEntry]) -> ZimReader:
    reader = ZimReader.__new__(ZimReader)
    reader._archive = _FakeArchive(entries)
    return reader


def test_strips_html_tags():
    html = b"<html><body><p>Hello <b>world</b>.</p></body></html>"
    reader = _reader_with_content(html)
    assert reader.get_text_snippet("Hello") == "Hello world ."


def test_strips_script_and_style_blocks_entirely():
    html = b"<p>Real text</p><script>alert('x')</script><style>.a{color:red}</style><p>more</p>"
    reader = _reader_with_content(html)
    snippet = reader.get_text_snippet("x")
    assert "alert" not in snippet
    assert "color" not in snippet
    assert "Real text" in snippet
    assert "more" in snippet


def test_unescapes_html_entities():
    html = b"<p>Tom &amp; Jerry &mdash; a classic &lt;show&gt;</p>"
    reader = _reader_with_content(html)
    snippet = reader.get_text_snippet("x")
    assert "&amp;" not in snippet
    assert "Tom & Jerry" in snippet


def test_collapses_whitespace():
    html = b"<p>Line one</p>\n\n\n<p>   Line   two   </p>"
    reader = _reader_with_content(html)
    snippet = reader.get_text_snippet("x")
    assert "  " not in snippet


def test_truncates_to_max_chars():
    html = b"<p>" + b"a" * 2000 + b"</p>"
    reader = _reader_with_content(html)
    snippet = reader.get_text_snippet("x", max_chars=100)
    assert len(snippet) == 100


def test_non_html_mimetype_returns_empty():
    reader = _reader_with_content(b"binary image data", mimetype="image/png")
    assert reader.get_text_snippet("x") == ""


def test_missing_entry_returns_empty():
    reader = ZimReader.__new__(ZimReader)
    reader.resolve = lambda path: None
    assert reader.get_text_snippet("does-not-exist") == ""


# ── entry_info() / resolve_range() ──────────────────────────────────────────

def test_entry_info_returns_size_and_mimetype_without_reading_content():
    item = _FakeItem(b"0123456789", "video/mp4")
    reader = _reader_with_archive({"video.mp4": _FakeEntry(item)})
    assert reader.entry_info("video.mp4") == (10, "video/mp4")


def test_entry_info_missing_path_returns_none():
    reader = _reader_with_archive({})
    assert reader.entry_info("nope") is None


def test_entry_info_follows_redirects():
    item = _FakeItem(b"real content", "text/html")
    target = _FakeEntry(item)
    redirect = _FakeEntry(item=None, is_redirect=True, target=target)
    reader = _reader_with_archive({"alias": redirect, "real": target})
    assert reader.entry_info("alias") == (12, "text/html")


def test_resolve_range_returns_exact_byte_slice():
    item = _FakeItem(b"0123456789", "video/mp4")
    reader = _reader_with_archive({"video.mp4": _FakeEntry(item)})
    assert reader.resolve_range("video.mp4", 2, 5) == b"2345"


def test_resolve_range_full_content_matches_resolve():
    """A [0, size-1] range must be byte-identical to what resolve() (the
    non-Range path) would have returned - same underlying content, just
    sliced a different way."""
    content = bytes(range(50))
    item = _FakeItem(content, "application/octet-stream")
    reader = _reader_with_archive({"f": _FakeEntry(item)})
    assert reader.resolve_range("f", 0, len(content) - 1) == content


def test_resolve_range_missing_path_returns_none():
    reader = _reader_with_archive({})
    assert reader.resolve_range("nope", 0, 10) is None
