"""
ZimReader: reads a .zim file in-process via libzim, replacing the old
kiwix-serve.exe subprocess. No port, no process, no vendor binary.

libzim API used here (verified against libzim 3.13.0 on Windows/cp314):
  Archive(path) -> .has_main_entry, .main_entry, .has_fulltext_index,
                    .get_entry_by_path(path), .has_entry_by_path(path)
  Entry         -> .path, .title, .is_redirect, .get_redirect_entry(), .get_item()
  Item          -> .path, .mimetype, .content (memoryview), .size
  Searcher(archive).search(Query().set_query(text)) -> Search
  Search        -> .getEstimatedMatches(), .getResults(start, count) -> iterable of paths
  SuggestionSearcher(archive).suggest(text) -> SuggestionSearch (same .getResults shape)
"""

import html
import re

from libzim.reader import Archive
from libzim.search import Query, Searcher
from libzim import SuggestionSearcher

_MAX_REDIRECT_HOPS = 10

_SCRIPT_OR_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.S | re.I)
_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


class ZimReader:

    def __init__(self, zim_path: str):
        self._archive = Archive(zim_path)
        self._searcher = Searcher(self._archive) if self._archive.has_fulltext_index else None
        self._suggester = SuggestionSearcher(self._archive)

    @property
    def has_search(self) -> bool:
        return self._searcher is not None

    def main_path(self) -> str | None:
        if not self._archive.has_main_entry:
            return None
        entry = self._archive.main_entry
        entry = self._follow_redirects(entry)
        return entry.path if entry else None

    def resolve(self, path: str) -> tuple[bytes, str] | None:
        """Look up `path` and return (content, mimetype), following redirects."""
        if not self._archive.has_entry_by_path(path):
            return None
        entry = self._archive.get_entry_by_path(path)
        entry = self._follow_redirects(entry)
        if entry is None:
            return None
        item = entry.get_item()
        return bytes(item.content), item.mimetype

    def is_redirect(self, path: str) -> str | None:
        """If `path` is a redirect entry, return the target path, else None."""
        if not self._archive.has_entry_by_path(path):
            return None
        entry = self._archive.get_entry_by_path(path)
        if not entry.is_redirect:
            return None
        return entry.get_redirect_entry().path

    def search(self, query: str, start: int = 0, count: int = 20) -> list[tuple[str, str]]:
        """Returns [(title, path), ...]. Empty if the ZIM has no full-text index."""
        if not self._searcher or not query.strip():
            return []
        search = self._searcher.search(Query().set_query(query))
        results = []
        for path in search.getResults(start, count):
            entry = self._archive.get_entry_by_path(path)
            results.append((entry.title, path))
        return results

    def get_text_snippet(self, path: str, max_chars: int = 600) -> str:
        """
        Plain-text excerpt of an entry's article (HTML tags stripped), for
        use as retrieval-augmented context handed to the LLM - NOT for
        actual article rendering, which uses resolve() directly and serves
        the real HTML. A regex strip is good enough for a short excerpt and
        avoids pulling in an HTML parser dependency just for this.
        """
        result = self.resolve(path)
        if result is None:
            return ""
        content, mimetype = result
        if "html" not in mimetype:
            return ""
        try:
            text = content.decode("utf-8", errors="ignore")
        except Exception:
            return ""
        text = _SCRIPT_OR_STYLE_RE.sub(" ", text)
        text = _TAG_RE.sub(" ", text)
        text = html.unescape(text)
        text = _WHITESPACE_RE.sub(" ", text).strip()
        return text[:max_chars]

    def suggest(self, query: str, count: int = 10) -> list[tuple[str, str]]:
        """Returns [(title, path), ...] for as-you-type suggestions."""
        if not query.strip():
            return []
        suggestion = self._suggester.suggest(query)
        results = []
        for path in suggestion.getResults(0, count):
            entry = self._archive.get_entry_by_path(path)
            results.append((entry.title, path))
        return results

    def close(self):
        self._archive = None
        self._searcher = None
        self._suggester = None

    # ── Internal ──────────────────────────────────────────────────────────────

    def _follow_redirects(self, entry):
        for _ in range(_MAX_REDIRECT_HOPS):
            if not entry.is_redirect:
                return entry
            entry = entry.get_redirect_entry()
        return None
