"""
Route-level tests for the public portal's PDF endpoints (plan.md item 24),
driven through a real Flask app and test_client(), in-process. The reader
itself is covered by test_pdf_reader.py; this checks the HTTP wiring.
"""

import json

import pytest

from test_admin_security import _default_config, _make_app, isolated_dirs  # noqa: F401
from test_pdf_reader import _make_pdf


def _install_pdf_module(isolated_dirs, folder="handbook"):
    mod_dir = isolated_dirs["modules"] / folder
    (mod_dir / "content").mkdir(parents=True)
    (mod_dir / "manifest.json").write_text(
        json.dumps({"name": "Handbook", "emoji": "X", "type": "pdf", "description": ""}),
        encoding="utf-8",
    )
    pdf_bytes = _make_pdf(["Welcome to school", "Volcano safety drill"])
    (mod_dir / "content" / "handbook.pdf").write_bytes(pdf_bytes)
    return pdf_bytes


def test_pdf_view_serves_the_real_file(isolated_dirs, tmp_path, monkeypatch):
    pdf_bytes = _install_pdf_module(isolated_dirs)
    app, _ = _make_app(isolated_dirs, tmp_path, monkeypatch)

    resp = app.test_client().get("/pdf/handbook")

    assert resp.status_code == 200
    assert resp.mimetype == "application/pdf"
    assert resp.data == pdf_bytes


def test_pdf_search_returns_the_matching_page(isolated_dirs, tmp_path, monkeypatch):
    _install_pdf_module(isolated_dirs)
    app, _ = _make_app(isolated_dirs, tmp_path, monkeypatch)

    resp = app.test_client().get("/pdf/handbook/_search?q=volcano")

    assert resp.status_code == 200
    assert b"/pdf/handbook#page=2" in resp.data


def test_pdf_search_with_no_match_still_renders(isolated_dirs, tmp_path, monkeypatch):
    _install_pdf_module(isolated_dirs)
    app, _ = _make_app(isolated_dirs, tmp_path, monkeypatch)

    resp = app.test_client().get("/pdf/handbook/_search?q=zzzzzz")

    assert resp.status_code == 200
    assert b"#page=" not in resp.data


def test_pdf_routes_404_for_unknown_module(isolated_dirs, tmp_path, monkeypatch):
    app, _ = _make_app(isolated_dirs, tmp_path, monkeypatch)
    client = app.test_client()

    assert client.get("/pdf/nope").status_code == 404
    assert client.get("/pdf/nope/_search?q=x").status_code == 404


@pytest.mark.parametrize("evil", ["..%5C..%5Cwindows", "..", "%2e%2e"])
def test_pdf_routes_refuse_traversal_ids(isolated_dirs, tmp_path, monkeypatch, evil):
    app, _ = _make_app(isolated_dirs, tmp_path, monkeypatch)
    client = app.test_client()

    assert client.get(f"/pdf/{evil}").status_code == 404
    assert client.get(f"/pdf/{evil}/_search?q=x").status_code == 404
