"""
TileServer — serves raster/vector tiles directly from .mbtiles (SQLite) files.

MBTiles spec: https://github.com/mapbox/mbtiles-spec
TMS y-axis convention: y_tms = (2^z - 1) - y_xyz
"""

import glob
import gzip
import os
import sqlite3
from functools import lru_cache

MODULES_DIR = r"C:\OfflineHub\modules"


class TileServer:
    """
    Reads from any .mbtiles file found inside MODULES_DIR.
    Caches open database connections per file to avoid per-request overhead.
    """

    def __init__(self):
        self._connections: dict[str, sqlite3.Connection] = {}

    # ── Public ────────────────────────────────────────────────────────────────

    def get_tile(self, module: str, z: int, x: int, y: int) -> bytes | None:
        """
        Fetch a single tile from the named module's .mbtiles file.
        Returns raw tile bytes or None if not found.
        """
        conn = self._get_connection(module)
        if conn is None:
            return None

        # MBTiles uses TMS y-axis (origin at bottom-left); XYZ tiles
        # (used by Leaflet / browsers) have origin at top-left.
        y_tms = (2 ** z - 1) - y

        try:
            cursor = conn.execute(
                "SELECT tile_data FROM tiles "
                "WHERE zoom_level = ? AND tile_column = ? AND tile_row = ?",
                (z, x, y_tms)
            )
            row = cursor.fetchone()
        except sqlite3.Error:
            return None

        if not row:
            return None

        tile_data: bytes = row[0]

        # Vector tiles are often gzip-compressed inside .mbtiles
        if _is_gzipped(tile_data):
            try:
                tile_data = gzip.decompress(tile_data)
            except Exception:
                pass

        return tile_data

    def metadata(self, module: str) -> dict:
        """Return the metadata table as a dict (name, format, bounds…)."""
        conn = self._get_connection(module)
        if conn is None:
            return {}
        try:
            rows = conn.execute("SELECT name, value FROM metadata").fetchall()
            return dict(rows)
        except sqlite3.Error:
            return {}

    # ── Connection pool ───────────────────────────────────────────────────────

    def _get_connection(self, module: str) -> sqlite3.Connection | None:
        if module in self._connections:
            return self._connections[module]

        mbtiles_path = self._find_mbtiles(module)
        if not mbtiles_path:
            return None

        try:
            # check_same_thread=False: Flask serves tiles from multiple threads
            conn = sqlite3.connect(mbtiles_path, check_same_thread=False)
            self._connections[module] = conn
            return conn
        except sqlite3.Error:
            return None

    def _find_mbtiles(self, module: str) -> str | None:
        pattern = os.path.join(MODULES_DIR, module, "**", "*.mbtiles")
        files   = glob.glob(pattern, recursive=True)
        return files[0] if files else None

    def close_all(self):
        for conn in self._connections.values():
            try:
                conn.close()
            except Exception:
                pass
        self._connections.clear()


def _is_gzipped(data: bytes) -> bool:
    return data[:2] == b"\x1f\x8b"