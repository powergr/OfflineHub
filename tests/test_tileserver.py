"""
Tests core/tileserver.py's connection-cache lifecycle: close()/close_all().

Regression coverage for a real bug: ModuleManager.remove() used to never
release a map module's cached sqlite connection before deleting its files,
so rmtree() hit a Windows PermissionError on the still-open .mbtiles file
whenever that map had ever been viewed. Uses a real temporary sqlite file
(TileServer opens real sqlite3.Connections, not something worth faking) so
close() closing the real connection is genuinely exercised, not assumed.
"""

import os
import sqlite3

import pytest

from core.tileserver import TileServer
import core.tileserver as tileserver_module


@pytest.fixture
def server(tmp_path, monkeypatch):
    modules_dir = tmp_path / "modules"
    mod_dir = modules_dir / "map_test" / "content"
    mod_dir.mkdir(parents=True)
    db_path = mod_dir / "map_test.mbtiles"
    conn = sqlite3.connect(str(db_path))
    conn.execute("CREATE TABLE metadata (name TEXT, value TEXT)")
    conn.commit()
    conn.close()

    monkeypatch.setattr(tileserver_module, "MODULES_DIR", str(modules_dir))
    return TileServer(), str(db_path)


def test_close_closes_and_forgets_the_cached_connection(server):
    ts, db_path = server
    ts.metadata("map_test")  # opens and caches a real connection
    assert "map_test" in ts._connections

    ts.close("map_test")
    assert "map_test" not in ts._connections

    # The real point: nothing still holds the file open, so it can be
    # renamed/deleted immediately afterward - mirrors what rmtree() needs.
    os.rename(db_path, db_path + ".moved")


def test_close_is_a_noop_for_a_module_never_opened(server):
    ts, _db_path = server
    ts.close("never_opened")  # must not raise


def test_close_all_clears_every_cached_connection(server):
    ts, _db_path = server
    ts.metadata("map_test")
    assert ts._connections

    ts.close_all()
    assert ts._connections == {}
