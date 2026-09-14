import json
import os
import zipfile

import pytest

from core.module_manager import ModuleManager
from core.registry import ContentRegistry


@pytest.fixture
def mgr():
    return ModuleManager(ContentRegistry())


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
    assert manifest["format"] == "raster"  # "vector" isn't in the filename
    assert (mod_dir / "content" / "London.mbtiles").exists()


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
