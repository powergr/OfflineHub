"""
Tests core/pdf_reader.py against real, small, hand-built PDFs (raw PDF
syntax, no PDF-writing library needed) rather than a fake object - unlike
ZimReader's tests, pypdf actually parses real PDF file structure, so there's
no equivalent of mocking libzim's documented Archive/Entry/Item shape here.
No network calls: every fixture PDF is built in-process.
"""

import os

import pytest

from core.pdf_reader import PdfReader


def _make_pdf(pages_text: list[str]) -> bytes:
    """Builds a minimal, valid multi-page PDF with real extractable text."""
    objects = []
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages_text)))
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages_text)} >>".encode())

    for i, text in enumerate(pages_text):
        page_obj_num = 3 + 2 * i
        content_obj_num = page_obj_num + 1
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 {3 + 2 * len(pages_text)} 0 R >> >> "
            f"/MediaBox [0 0 612 792] /Contents {content_obj_num} 0 R >>".encode()
        )
        stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode()
        objects.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")

    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for i, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"

    xref_start = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode()
    out += b"0000000000 65535 f \n"
    for off in offsets[1:]:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF".encode()
    return bytes(out)


@pytest.fixture
def two_page_pdf(tmp_path):
    path = tmp_path / "test.pdf"
    path.write_bytes(_make_pdf(["Hello World from page one", "A second page about volcanoes"]))
    return str(path)


def test_reads_page_count(two_page_pdf):
    reader = PdfReader(two_page_pdf)
    assert reader.page_count == 2


def test_search_finds_matching_page_case_insensitively(two_page_pdf):
    reader = PdfReader(two_page_pdf)
    results = reader.search("VOLCANOES")
    assert results == [(2, "A second page about volcanoes")]


def test_search_returns_1_indexed_page_numbers(two_page_pdf):
    reader = PdfReader(two_page_pdf)
    results = reader.search("Hello")
    assert results[0][0] == 1


def test_search_no_match_returns_empty_list(two_page_pdf):
    reader = PdfReader(two_page_pdf)
    assert reader.search("dinosaurs") == []


def test_search_empty_query_returns_empty_list(two_page_pdf):
    reader = PdfReader(two_page_pdf)
    assert reader.search("") == []
    assert reader.search("   ") == []


def test_search_matches_across_multiple_pages(tmp_path):
    path = tmp_path / "multi.pdf"
    path.write_bytes(_make_pdf(["apples and oranges", "more apples here", "nothing relevant"]))
    reader = PdfReader(str(path))
    results = reader.search("apples")
    assert [page for page, _snippet in results] == [1, 2]


def test_search_respects_max_results(tmp_path):
    path = tmp_path / "many.pdf"
    path.write_bytes(_make_pdf([f"keyword page {i}" for i in range(10)]))
    reader = PdfReader(str(path))
    results = reader.search("keyword", max_results=3)
    assert len(results) == 3


def test_path_is_the_real_file_for_send_file(two_page_pdf):
    """portal.py's pdf_view route serves reader.path directly via
    send_file() - it must be the real on-disk path, not a copy."""
    reader = PdfReader(two_page_pdf)
    assert reader.path == two_page_pdf
    assert os.path.exists(reader.path)


def test_close_clears_page_text():
    reader = PdfReader.__new__(PdfReader)
    reader._pages_text = ["some text"]
    reader.close()
    assert reader._pages_text == []
