import json
import os
import sqlite3
import zipfile

import pytest

import core.module_manager as module_manager
from core.module_manager import ModuleManager
from core.registry import ContentRegistry


def _make_mbtiles(path: str, fmt: str):
    """Writes a minimal real .mbtiles (sqlite) file with a metadata table
    declaring the given format ("pbf" for vector, "png"/"jpg" for raster) -
    the real thing _detect_mbtiles_format() reads, unlike a plain bytes file."""
    conn = sqlite3.connect(path)
    conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    conn.execute("INSERT INTO metadata VALUES ('format', ?)", (fmt,))
    conn.commit()
    conn.close()


def _make_pdf_bytes(text: str = "Hello World") -> bytes:
    """A minimal, real, single-page PDF (raw PDF syntax) - open_module()
    actually opens a "pdf" install via real pypdf, which a plain bytes
    fixture isn't valid input for, unlike the mbtiles/zim fakes above."""
    stream = f"BT /F1 24 Tf 72 700 Td ({text}) Tj ET".encode()
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /Resources << /Font << /F1 5 0 R >> >> "
        b"/MediaBox [0 0 612 792] /Contents 4 0 R >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
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
def mgr():
    return ModuleManager(ContentRegistry())


class _FakeZimReader:
    """Stands in for the real libzim-backed ZimReader - install_from_download
    always writes a "type": "zim" manifest, and open_module() actually opens
    it via libzim, which real test fixture bytes aren't a valid file for.
    The existing zip-install test dodges this by using type "mbtiles"
    instead; install_from_download has no such option, so these tests
    monkeypatch ZimReader itself instead."""

    def __init__(self, path):
        self.path = path


@pytest.fixture
def fake_zim(monkeypatch):
    monkeypatch.setattr(module_manager, "ZimReader", _FakeZimReader)


def _make_zip(tmp_path, name, entries: dict[str, bytes]) -> str:
    """entries maps in-zip member name -> file content."""
    zip_path = str(tmp_path / name)
    with zipfile.ZipFile(zip_path, "w") as zf:
        for member_name, data in entries.items():
            zf.writestr(member_name, data)
    return zip_path


# ── install_from_raw_file ────────────────────────────────────────────────────

def test_install_raw_mbtiles_file(isolated_dirs, mgr, tmp_path):
    src = tmp_path / "London.mbtiles"
    src.write_bytes(b"fake mbtiles bytes")

    mgr.install_from_raw_file(str(src))

    mod_dir = isolated_dirs["modules"] / "London"
    manifest = json.loads((mod_dir / "manifest.json").read_text())
    assert manifest["type"] == "mbtiles"
    assert manifest["format"] == "raster"  # not a real sqlite file, so this is the safe default
    assert (mod_dir / "content" / "London.mbtiles").exists()


def test_install_raw_mbtiles_file_detects_real_vector_format_regardless_of_filename():
    """Regression test: a real vector .mbtiles used to get tagged "raster"
    whenever its filename didn't happen to contain the word "vector," which
    made the portal request the wrong tile endpoint and render a blank map.
    The manifest's format must come from the file's own metadata table."""
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "some_map.mbtiles")
        _make_mbtiles(path, "pbf")
        assert module_manager._detect_mbtiles_format(path) == "vector"


def test_detect_mbtiles_format_raster_from_real_metadata():
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        path = os.path.join(tmp, "vector_named_but_actually_raster.mbtiles")
        _make_mbtiles(path, "png")
        assert module_manager._detect_mbtiles_format(path) == "raster"


def test_install_raw_pdf_file(isolated_dirs, mgr, tmp_path):
    src = tmp_path / "Volcanoes Worksheet.pdf"
    src.write_bytes(_make_pdf_bytes("All about volcanoes"))

    mgr.install_from_raw_file(str(src))

    mod_dir = isolated_dirs["modules"] / "Volcanoes Worksheet"
    manifest = json.loads((mod_dir / "manifest.json").read_text())
    assert manifest["type"] == "pdf"
    assert manifest["emoji"] == "📄"
    assert (mod_dir / "content" / "Volcanoes Worksheet.pdf").exists()


def test_install_raw_pdf_file_opens_successfully_and_is_searchable(isolated_dirs, mgr, tmp_path):
    """install_from_raw_file() calls open_module(), which for type "pdf"
    eagerly opens it via get_pdf_reader() - confirms that actually succeeds
    against a real PDF, not just that the manifest looks right."""
    src = tmp_path / "notes.pdf"
    src.write_bytes(_make_pdf_bytes("A lesson about volcanoes"))

    mgr.install_from_raw_file(str(src))

    assert mgr.registry.get_status("notes") != "error"
    reader = mgr.get_pdf_reader("notes")
    assert reader.search("volcanoes")


def test_install_raw_file_rejects_unsupported_extension(isolated_dirs, mgr, tmp_path):
    src = tmp_path / "notes.txt"
    src.write_text("hello")
    with pytest.raises(ValueError, match="Unsupported file type"):
        mgr.install_from_raw_file(str(src))


def test_install_raw_file_rejects_duplicate_name(isolated_dirs, mgr, tmp_path):
    src1 = tmp_path / "vikidia.mbtiles"
    src1.write_bytes(b"one")
    mgr.install_from_raw_file(str(src1))

    src2 = tmp_path / "vikidia.mbtiles"
    src2.write_bytes(b"two")
    with pytest.raises(FileExistsError):
        mgr.install_from_raw_file(str(src2))


# ── install_from_zip ─────────────────────────────────────────────────────────

def test_install_from_zip_happy_path(isolated_dirs, mgr, tmp_path):
    manifest = {"name": "Test Map", "emoji": "🗺️", "type": "mbtiles", "format": "vector"}
    zip_path = _make_zip(tmp_path, "pack.zip", {
        "manifest.json": json.dumps(manifest).encode(),
        "content/test.mbtiles": b"fake tiles",
    })

    mgr.install_from_zip(zip_path)

    mod_dir = isolated_dirs["modules"] / "Test Map"
    assert (mod_dir / "content" / "test.mbtiles").exists()
    assert mgr.registry.get_status("Test Map") == "loaded"


def test_install_from_zip_missing_manifest_raises(isolated_dirs, mgr, tmp_path):
    zip_path = _make_zip(tmp_path, "pack.zip", {"content/test.mbtiles": b"data"})
    with pytest.raises(FileNotFoundError):
        mgr.install_from_zip(zip_path)


def test_install_from_zip_rejects_unknown_type(isolated_dirs, mgr, tmp_path):
    manifest = {"name": "Bad", "emoji": "x", "type": "not_a_real_type"}
    zip_path = _make_zip(tmp_path, "pack.zip", {"manifest.json": json.dumps(manifest).encode()})
    with pytest.raises(ValueError, match="Unknown module type"):
        mgr.install_from_zip(zip_path)


def test_install_from_zip_rejects_path_traversal(isolated_dirs, mgr, tmp_path):
    """
    Regression test for a real zip-slip vulnerability: a crafted ZIP whose
    member name escapes the extraction directory (e.g. "../../evil.txt")
    used to be extracted by zipfile.extractall() with no path checking at
    all. Manual Install accepts uploads from any device on the hotspot, so
    this is a real attack surface, not a theoretical one.

    A file planted one level above tmp_path is the canary: if it exists
    after the call, the escape succeeded and the fix has regressed.
    """
    manifest = {"name": "Evil", "emoji": "x", "type": "mbtiles", "format": "vector"}
    canary = tmp_path.parent / "escaped_evil.txt"
    if canary.exists():
        canary.unlink()

    zip_path = _make_zip(tmp_path, "evil.zip", {
        "manifest.json": json.dumps(manifest).encode(),
        "../escaped_evil.txt": b"if you can read this, zip-slip is back",
    })

    with pytest.raises(ValueError, match="escapes the destination folder"):
        mgr.install_from_zip(zip_path)

    assert not canary.exists()
    assert not (isolated_dirs["modules"] / "Evil").exists()


def test_install_from_zip_rejects_absolute_path_member(isolated_dirs, mgr, tmp_path):
    """os.path.join() silently discards the first argument when the second
    is absolute, which is exactly how an absolute-path zip member escapes
    the destination folder too - a separate case from "../" traversal."""
    manifest = {"name": "Evil2", "emoji": "x", "type": "mbtiles", "format": "vector"}
    zip_path = _make_zip(tmp_path, "evil2.zip", {"manifest.json": json.dumps(manifest).encode()})

    # zipfile.writestr won't write a literal absolute path portably, so
    # rewrite the member name directly at the ZipInfo level instead.
    with zipfile.ZipFile(zip_path, "a") as zf:
        info = zipfile.ZipInfo(os.path.splitdrive(str(tmp_path))[0] + r"\evil_absolute.txt")
        zf.writestr(info, b"escaped via absolute path")

    with pytest.raises(ValueError, match="escapes the destination folder"):
        mgr.install_from_zip(zip_path)


# ── install_from_download / install_map_from_download (source_url + replace) ──

def test_install_from_download_records_source_url(isolated_dirs, fake_zim, mgr, tmp_path):
    downloaded = tmp_path / "wikipedia_en_mini.zim"
    downloaded.write_bytes(b"fake zim data")
    item = {"name": "Wikipedia (English, Mini)", "emoji": "📚",
            "description": "...", "url": "https://example.test/wikipedia_2026-01.zim"}

    mgr.install_from_download("wikipedia_en_mini", item, str(downloaded))

    manifest = json.loads((isolated_dirs["modules"] / "wikipedia_en_mini" / "manifest.json").read_text())
    assert manifest["source_url"] == "https://example.test/wikipedia_2026-01.zim"


def test_install_from_download_rejects_duplicate_without_replace(isolated_dirs, fake_zim, mgr, tmp_path):
    downloaded = tmp_path / "a.zim"
    downloaded.write_bytes(b"data")
    item = {"name": "X", "emoji": "x", "description": "", "url": "https://example.test/a.zim"}
    mgr.install_from_download("mykey", item, str(downloaded))

    with pytest.raises(FileExistsError):
        mgr.install_from_download("mykey", item, str(downloaded))


def test_install_from_download_replace_true_swaps_content_and_source_url(isolated_dirs, fake_zim, mgr, tmp_path):
    old_file = tmp_path / "old.zim"
    old_file.write_bytes(b"old content")
    old_item = {"name": "X", "emoji": "x", "description": "", "url": "https://example.test/old.zim"}
    mgr.install_from_download("mykey", old_item, str(old_file))

    new_file = tmp_path / "new.zim"
    new_file.write_bytes(b"new content, much bigger than before")
    new_item = {"name": "X", "emoji": "x", "description": "", "url": "https://example.test/new.zim"}
    mgr.install_from_download("mykey", new_item, str(new_file), replace=True)

    mod_dir = isolated_dirs["modules"] / "mykey"
    manifest = json.loads((mod_dir / "manifest.json").read_text())
    assert manifest["source_url"] == "https://example.test/new.zim"
    assert not (mod_dir / "content" / "old.zim").exists()
    assert (mod_dir / "content" / "new.zim").read_bytes() == b"new content, much bigger than before"


def test_install_map_from_download_records_source_url(isolated_dirs, mgr, tmp_path):
    downloaded = tmp_path / "map_uk.mbtiles"
    downloaded.write_bytes(b"fake tiles")
    item = {"name": "Map: UK", "emoji": "🗺️", "description": "...",
            "url": "https://example.test/map_uk.mbtiles"}

    mgr.install_map_from_download("map_uk", item, str(downloaded))

    manifest = json.loads((isolated_dirs["modules"] / "map_uk" / "manifest.json").read_text())
    assert manifest["source_url"] == "https://example.test/map_uk.mbtiles"
    assert manifest["type"] == "mbtiles"


def test_install_map_from_download_replace_true_swaps_content(isolated_dirs, mgr, tmp_path):
    old_file = tmp_path / "old.mbtiles"
    old_file.write_bytes(b"old tiles")
    old_item = {"name": "Map", "emoji": "x", "description": "", "url": "https://example.test/old.mbtiles"}
    mgr.install_map_from_download("mapkey", old_item, str(old_file))

    new_file = tmp_path / "new.mbtiles"
    new_file.write_bytes(b"new tiles")
    new_item = {"name": "Map", "emoji": "x", "description": "", "url": "https://example.test/new.mbtiles"}
    mgr.install_map_from_download("mapkey", new_item, str(new_file), replace=True)

    mod_dir = isolated_dirs["modules"] / "mapkey"
    manifest = json.loads((mod_dir / "manifest.json").read_text())
    assert manifest["source_url"] == "https://example.test/new.mbtiles"
    assert not (mod_dir / "content" / "old.mbtiles").exists()


# ── list_modules ──────────────────────────────────────────────────────────────

def test_list_modules_skips_corrupt_manifest(isolated_dirs, mgr):
    good_dir = isolated_dirs["modules"] / "good"
    good_dir.mkdir()
    (good_dir / "manifest.json").write_text(json.dumps({"name": "Good", "type": "zim"}))

    bad_dir = isolated_dirs["modules"] / "bad"
    bad_dir.mkdir()
    (bad_dir / "manifest.json").write_text("{not valid json")

    results = dict(mgr.list_modules())
    assert "good" in results
    assert "bad" not in results


def test_list_modules_reconstructs_manifest_for_pdf_only_folder(isolated_dirs, mgr, tmp_path):
    """Regression coverage for the has_llm_content fallback: a folder with
    real content but no manifest used to only distinguish mbtiles/zim from
    "everything else", so a PDF-only folder (real content, no mbtiles, no
    zim) would have been wrongly reconstructed as type "llm"."""
    mod_dir = isolated_dirs["modules"] / "my_upload"
    content_dir = mod_dir / "content"
    content_dir.mkdir(parents=True)
    (content_dir / "worksheet.pdf").write_bytes(_make_pdf_bytes("Some content"))

    results = dict(mgr.list_modules())

    assert results["my_upload"]["type"] == "pdf"
    manifest = json.loads((mod_dir / "manifest.json").read_text())
    assert manifest["type"] == "pdf"


def test_list_modules_empty_when_dir_missing(isolated_dirs, mgr, monkeypatch):
    import core.module_manager as module_manager
    monkeypatch.setattr(module_manager, "MODULES_DIR", str(isolated_dirs["modules"] / "nope"))
    assert mgr.list_modules() == []


# ── install_extracted_map (self-serve country maps) ─────────────────────────

def test_install_extracted_map_uses_country_prefixed_key(isolated_dirs, mgr, tmp_path):
    src = tmp_path / "country_fr.mbtiles"
    _make_mbtiles(str(src), "pbf")

    key = mgr.install_extracted_map("FR", "France", str(src))

    assert key == "country_fr"
    mod_dir = isolated_dirs["modules"] / "country_fr"
    manifest = json.loads((mod_dir / "manifest.json").read_text())
    assert manifest["type"] == "mbtiles"
    assert manifest["format"] == "vector"
    assert manifest["iso"] == "FR"
    assert manifest["source"] == "protomaps_daily_build"
    assert (mod_dir / "content" / "country_fr.mbtiles").exists()


def test_install_extracted_map_does_not_collide_with_curated_map_france(isolated_dirs, mgr, tmp_path):
    """Regression guard: the hand-curated MAPS_CATALOGUE key for France is
    "map_france" - a self-serve extraction of France must land at a
    distinct "country_fr" key, never overwriting or colliding with it."""
    curated = tmp_path / "map_france.mbtiles"
    curated.write_bytes(b"curated pack")
    mgr.install_map_from_download(
        "map_france", {"name": "Map: France", "emoji": "x", "description": "", "url": "https://example.test/x"},
        str(curated),
    )

    extracted = tmp_path / "self_serve_fr.mbtiles"
    _make_mbtiles(str(extracted), "pbf")
    mgr.install_extracted_map("FR", "France", str(extracted))

    assert (isolated_dirs["modules"] / "map_france").exists()
    assert (isolated_dirs["modules"] / "country_fr").exists()


def test_install_extracted_map_refuses_when_already_installed(isolated_dirs, mgr, tmp_path):
    src = tmp_path / "country_fr.mbtiles"
    _make_mbtiles(str(src), "pbf")
    mgr.install_extracted_map("FR", "France", str(src))

    src2 = tmp_path / "country_fr_again.mbtiles"
    _make_mbtiles(str(src2), "pbf")
    with pytest.raises(FileExistsError):
        mgr.install_extracted_map("FR", "France", str(src2))


# ── remove ────────────────────────────────────────────────────────────────────

def test_remove_deletes_folder_and_unregisters(isolated_dirs, mgr, tmp_path):
    src = tmp_path / "phet.mbtiles"
    src.write_bytes(b"data")
    mgr.install_from_raw_file(str(src))

    mod_dir = isolated_dirs["modules"] / "phet"
    assert mod_dir.exists()
    assert mgr.registry.get_status("phet") == "loaded"

    mgr.remove("phet")

    assert not mod_dir.exists()
    assert mgr.registry.get_status("phet") == "unloaded"


def test_remove_rejects_traversal_folder(isolated_dirs, mgr, tmp_path):
    outside = tmp_path / "secret"
    outside.mkdir()
    with pytest.raises(ValueError):
        mgr.remove("..\\secret")
    assert outside.exists()


# ── _resolve_module_dir (path traversal) ────────────────────────────────────
# Regression coverage: get_pdf_reader/get_zim_reader/get_llm_engine used to
# os.path.join(MODULES_DIR, folder, ...) with no check at all. On Windows, a
# folder value containing backslashes (legal inside a single Flask URL path
# segment, since only "/" is a real URL separator) resolves as real path
# components once it reaches the filesystem - reachable from the fully
# public, unauthenticated portal blueprint.

def test_resolve_module_dir_allows_a_real_module_name(isolated_dirs):
    real = isolated_dirs["modules"] / "wikipedia_en_mini"
    real.mkdir()
    resolved = module_manager._resolve_module_dir("wikipedia_en_mini")
    assert os.path.realpath(resolved) == os.path.realpath(str(real))


def test_resolve_module_dir_rejects_dotdot_traversal(isolated_dirs, tmp_path):
    outside = tmp_path / "secret"
    outside.mkdir()
    with pytest.raises(ValueError):
        module_manager._resolve_module_dir(os.path.join("..", "secret"))


def test_resolve_module_dir_rejects_backslash_smuggled_traversal(isolated_dirs, tmp_path):
    """The exact Windows-specific exploit shape from the security review:
    a single URL path segment containing literal backslashes."""
    outside = tmp_path / "secret"
    outside.mkdir()
    with pytest.raises(ValueError):
        module_manager._resolve_module_dir("..\\secret")


def test_resolve_module_dir_rejects_absolute_path(isolated_dirs, tmp_path):
    outside = tmp_path / "secret"
    outside.mkdir()
    with pytest.raises(ValueError):
        module_manager._resolve_module_dir(str(outside))


def test_get_pdf_reader_rejects_traversal_folder(isolated_dirs, mgr):
    with pytest.raises(ValueError):
        mgr.get_pdf_reader("..\\..\\Windows")


def test_get_zim_reader_rejects_traversal_folder(isolated_dirs, mgr):
    with pytest.raises(ValueError):
        mgr.get_zim_reader("..\\..\\Windows")


def test_get_manifest_returns_none_for_traversal_folder(isolated_dirs, mgr):
    assert mgr.get_manifest("..\\..\\Windows") is None


# ── get_llm_engine concurrency ──────────────────────────────────────────────

def test_get_llm_engine_serializes_concurrent_loads_of_different_modules(isolated_dirs, mgr, monkeypatch):
    """Regression test: two threads requesting two different LLM modules at
    once used to both pass the "existing is None" check before either
    recorded which module was loaded, so both loaded a full model
    concurrently - defeating the single-resident-model design. With the
    lock, exactly one load must happen at a time."""
    import threading
    import time

    active_loads = []
    max_concurrent = [0]
    load_lock = threading.Lock()

    class FakeEngine:
        def __init__(self, path):
            self.path = path

        def load(self):
            with load_lock:
                active_loads.append(1)
                max_concurrent[0] = max(max_concurrent[0], len(active_loads))
            time.sleep(0.05)  # simulate real multi-GB model load time
            with load_lock:
                active_loads.pop()

    import core.llm_engine as llm_engine_module
    monkeypatch.setattr(llm_engine_module, "LLMEngine", FakeEngine)

    for name in ("assistant_a", "assistant_b"):
        mod_dir = isolated_dirs["modules"] / name / "content"
        mod_dir.mkdir(parents=True)

    results = {}

    def load_one(name):
        results[name] = mgr.get_llm_engine(name)

    t1 = threading.Thread(target=load_one, args=("assistant_a",))
    t2 = threading.Thread(target=load_one, args=("assistant_b",))
    t1.start()
    t2.start()
    t1.join(timeout=5)
    t2.join(timeout=5)

    assert max_concurrent[0] == 1, "two models were loaded into memory at the same time"
    # Only one model ends up resident, matching the documented invariant.
    assert mgr._llm_loaded_module in ("assistant_a", "assistant_b")
