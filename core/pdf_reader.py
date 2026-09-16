"""
PdfReader: reads a teacher-uploaded .pdf file in-process via pypdf, for the
"upload your own material" module type (plan.md Phase 6, item 24).

pypdf is pure Python (confirmed: its wheel is py3-none-any, no native
extension), so it bundles into a Nuitka build the same low-risk way `pmtiles`
already does - no vendor binary involved.

Unlike ZimReader, this has no "render the page" responsibility at all. The
raw PDF file is served directly to the browser (core/blueprints/portal.py's
pdf_view route) and rendered by the browser's own built-in PDF viewer, which
every major browser already ships. This class's only job is text extraction
for search: every page's text is pulled once at open time (matching how a
ZIM's own full-text index is already built once, not per query) and kept in
memory for a simple case-insensitive substring search.
"""

from pypdf import PdfReader as _PypdfReader

_SNIPPET_RADIUS = 60


class PdfReader:

    def __init__(self, pdf_path: str):
        self.path = pdf_path
        reader = _PypdfReader(pdf_path)
        self.page_count = len(reader.pages)
        self._pages_text: list[str] = []
        for page in reader.pages:
            try:
                text = page.extract_text() or ""
            except Exception:
                # A single malformed/image-only page must not break the
                # whole document - it just contributes no searchable text.
                text = ""
            self._pages_text.append(text)

    def search(self, query: str, max_results: int = 20) -> list[tuple[int, str]]:
        """
        Returns [(page_number, snippet), ...] for pages whose text contains
        `query` (case-insensitive substring match). Good enough for a
        handful of teacher-uploaded documents - this is not meant to scale
        to a large document library the way a real search engine would.
        Page numbers are 1-based, matching how PDF viewers display them.
        """
        query = query.strip().lower()
        if not query:
            return []
        results = []
        for i, text in enumerate(self._pages_text):
            idx = text.lower().find(query)
            if idx == -1:
                continue
            start = max(0, idx - _SNIPPET_RADIUS)
            end = idx + len(query) + _SNIPPET_RADIUS
            snippet = text[start:end].strip()
            results.append((i + 1, snippet))
            if len(results) >= max_results:
                break
        return results

    def close(self):
        self._pages_text = []
