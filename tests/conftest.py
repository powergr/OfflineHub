"""
Shared pytest fixtures.

core/module_manager.py and core/downloader.py hardcode C:\\OfflineHub as
their base directory (MODULES_DIR / DOWNLOAD_DIR are computed once, at
import time). Tests must never touch that real directory, so every test
that installs/downloads anything uses the `isolated_dirs` fixture below,
which monkeypatches those module-level constants to a pytest tmp_path for
the duration of the test.
"""

import pytest


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    modules_dir = tmp_path / "modules"
    downloads_dir = tmp_path / "downloads"
    modules_dir.mkdir()
    downloads_dir.mkdir()

    import core.downloader as downloader
    import core.module_manager as module_manager

    monkeypatch.setattr(module_manager, "MODULES_DIR", str(modules_dir))
    monkeypatch.setattr(downloader, "MODULES_DIR", str(modules_dir))
    monkeypatch.setattr(downloader, "DOWNLOAD_DIR", str(downloads_dir))

    return {"modules": modules_dir, "downloads": downloads_dir}
