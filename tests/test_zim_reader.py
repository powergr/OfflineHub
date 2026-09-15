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
