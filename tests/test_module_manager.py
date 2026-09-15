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

    mgr.remove(str(mod_dir))

    assert not mod_dir.exists()
    assert mgr.registry.get_status("phet") == "unloaded"
