"""
Tests core/blueprints/admin.py's session gate and CSRF protection through a
real Flask app (core.app_factory.create_app) and its test_client() - entirely
in-process (no real socket, no real subprocess, no real background thread),
unlike this session's earlier live end-to-end scripts.

Regression coverage for two real, confirmed vulnerabilities from a full
codebase security review:
  1. "/admin/setup/finish" used to be permanently exempt from all auth
     checks (not just during first-run), letting anyone reset the admin
     password and hotspot credentials at any time with zero credentials.
  2. No CSRF protection existed anywhere - every state-changing admin POST
     (modules/remove, modules/install, settings, hotspot) trusted the
     session cookie alone.
"""

import json
import os

import pytest

import core.app_factory as app_factory_module
import core.downloader as downloader_module
import core.module_manager as module_manager_module
from core.usage_stats import UsageTracker


def _default_config(**overrides) -> dict:
    cfg = {
        "first_run": False,
        "version": "0.0.0-test",
        "admin_password_hash": "original-hash",
        "admin_password_salt": "original-salt",
        "secret_key": "test-secret-key-not-a-real-one",
        "language": "en",
        "hotspot": {"ssid": "OriginalSSID", "password": "OriginalPassword", "enabled": False},
        "portal_port": 8000,
        "autostart": False,
        "modules": {},
    }
    cfg.update(overrides)
    return cfg


@pytest.fixture
def isolated_dirs(tmp_path, monkeypatch):
    modules_dir = tmp_path / "modules"
    downloads_dir = tmp_path / "downloads"
    modules_dir.mkdir()
    downloads_dir.mkdir()
    monkeypatch.setattr(module_manager_module, "MODULES_DIR", str(modules_dir))
    monkeypatch.setattr(downloader_module, "MODULES_DIR", str(modules_dir))
    monkeypatch.setattr(downloader_module, "DOWNLOAD_DIR", str(downloads_dir))
    return {"modules": modules_dir, "downloads": downloads_dir}


def _make_app(isolated_dirs, tmp_path, monkeypatch, config=None):
    # UsageTracker's default `path` argument is bound to the real
    # C:\OfflineHub path at import time - patching the module-level
    # constant afterward doesn't change it, so app_factory's own
    # `UsageTracker()` call site is patched instead to inject a temp path.
    usage_path = str(tmp_path / "usage_stats.json")
    monkeypatch.setattr(app_factory_module, "UsageTracker", lambda: UsageTracker(path=usage_path))

    cfg = config if config is not None else _default_config()
    app = app_factory_module.create_app(cfg, save_config=lambda c: None)
    app.config["TESTING"] = True
    return app, cfg


def _install_fake_module(isolated_dirs, folder: str):
    mod_dir = isolated_dirs["modules"] / folder
    mod_dir.mkdir()
    (mod_dir / "manifest.json").write_text(
        json.dumps({"name": folder, "emoji": "X", "type": "zim", "description": ""}),
        encoding="utf-8",
    )


def _authed_client(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["admin_authed"] = True
    return client


def _csrf_token_for(client) -> str:
    """A GET of any admin page renders csrf_token() into the template,
    which lazily creates and stores it in the session - read it back out
    the same way a real browser would carry it in the hidden form field."""
    client.get("/admin/settings")
    with client.session_transaction() as sess:
        return sess["csrf_token"]


# ── Finding: /admin/setup/finish permanently unauthenticated ────────────────

def test_setup_finish_is_blocked_once_first_run_is_over(isolated_dirs, tmp_path, monkeypatch):
    app, cfg = _make_app(isolated_dirs, tmp_path, monkeypatch, _default_config(first_run=False))
    client = app.test_client()  # deliberately NOT authenticated

    resp = client.post(
        "/admin/setup/finish",
        data={
            "admin_password": "attacker123", "admin_password_confirm": "attacker123",
            "ssid": "PwnedWifi", "hotspot_password": "pwned",
        },
    )

    # Must not succeed as an open admin action - redirected to login/setup,
    # not straight through to modules with a new session.
    assert resp.status_code in (302, 403)
    if resp.status_code == 302:
        assert "/admin/login" in resp.headers["Location"] or "/admin/setup" in resp.headers["Location"]

    # The real point: nothing about the real config was touched.
    assert cfg["admin_password_hash"] == "original-hash"
    assert cfg["hotspot"]["ssid"] == "OriginalSSID"
    assert cfg["hotspot"]["password"] == "OriginalPassword"


def test_setup_finish_still_works_unauthenticated_during_first_run(isolated_dirs, tmp_path, monkeypatch):
    """The fix must not break real first-run onboarding, which legitimately
    has no session yet."""
    app, cfg = _make_app(isolated_dirs, tmp_path, monkeypatch, _default_config(first_run=True))
    client = app.test_client()

    token = _csrf_token_for_setup(client)
    resp = client.post(
        "/admin/setup/finish",
        data={
            "admin_password": "realpassword", "admin_password_confirm": "realpassword",
            "ssid": "SchoolWifi", "hotspot_password": "schoolpass",
            "csrf_token": token,
        },
    )
    assert resp.status_code == 302
    assert cfg["first_run"] is False
    assert cfg["admin_password_hash"] != "original-hash"


def _csrf_token_for_setup(client) -> str:
    client.get("/admin/setup")
    with client.session_transaction() as sess:
        return sess["csrf_token"]


# ── CSRF protection ──────────────────────────────────────────────────────────

def test_state_changing_post_rejected_without_csrf_token(isolated_dirs, tmp_path, monkeypatch):
    app, cfg = _make_app(isolated_dirs, tmp_path, monkeypatch)
    client = _authed_client(app)

    resp = client.post("/admin/services/unload", data={"folder": "whatever"})
    assert resp.status_code == 403


def test_state_changing_post_accepted_with_correct_csrf_token(isolated_dirs, tmp_path, monkeypatch):
    app, cfg = _make_app(isolated_dirs, tmp_path, monkeypatch)
    client = _authed_client(app)
    token = _csrf_token_for(client)

    resp = client.post("/admin/services/unload", data={"folder": "whatever", "csrf_token": token})
    assert resp.status_code == 302  # normal redirect-after-POST, not 403


def test_state_changing_post_rejected_with_wrong_csrf_token(isolated_dirs, tmp_path, monkeypatch):
    app, cfg = _make_app(isolated_dirs, tmp_path, monkeypatch)
    client = _authed_client(app)
    _csrf_token_for(client)  # seed a real token in the session

    resp = client.post("/admin/services/unload", data={"folder": "whatever", "csrf_token": "not-the-real-token"})
    assert resp.status_code == 403


def test_get_requests_are_never_csrf_checked(isolated_dirs, tmp_path, monkeypatch):
    app, cfg = _make_app(isolated_dirs, tmp_path, monkeypatch)
    client = _authed_client(app)
    resp = client.get("/admin/modules")
    assert resp.status_code == 200


# ── Finding: modules/remove accepted any path, modules/install trusted any upload filename ──

def test_modules_remove_rejects_a_folder_that_is_not_actually_installed(isolated_dirs, tmp_path, monkeypatch):
    app, cfg = _make_app(isolated_dirs, tmp_path, monkeypatch)
    client = _authed_client(app)
    token = _csrf_token_for(client)

    outside = tmp_path / "secret_dir"
    outside.mkdir()
    (outside / "keepme.txt").write_text("do not delete", encoding="utf-8")

    resp = client.post(
        "/admin/modules/remove",
        data={"folder": "..\\secret_dir", "csrf_token": token},
    )
    assert resp.status_code == 302
    assert outside.exists()
    assert (outside / "keepme.txt").exists()


def test_modules_remove_deletes_a_real_installed_module(isolated_dirs, tmp_path, monkeypatch):
    app, cfg = _make_app(isolated_dirs, tmp_path, monkeypatch)
    _install_fake_module(isolated_dirs, "real_module")
    client = _authed_client(app)
    token = _csrf_token_for(client)

    resp = client.post(
        "/admin/modules/remove",
        data={"folder": "real_module", "csrf_token": token},
    )
    assert resp.status_code == 302
    assert not (isolated_dirs["modules"] / "real_module").exists()


def test_modules_install_upload_filename_is_sanitized(isolated_dirs, tmp_path, monkeypatch):
    """A crafted upload filename like "../../evil.zim" must not be able to
    write outside the intended temp directory."""
    app, cfg = _make_app(isolated_dirs, tmp_path, monkeypatch)
    client = _authed_client(app)
    token = _csrf_token_for(client)

    import io

    data = {
        "csrf_token": token,
        "file": (io.BytesIO(b"fake zim bytes"), "../../../evil.zim"),
    }
    resp = client.post("/admin/modules/install", data=data, content_type="multipart/form-data")
    assert resp.status_code == 302
    # Whatever happened, it must not have escaped into a folder named
    # "evil.zim" two levels above tempdir - the module either installed
    # cleanly under a sanitized name or failed safely, never traversed.
    import tempfile
    escaped_target = os.path.join(os.path.dirname(os.path.dirname(tempfile.gettempdir())), "evil.zim")
    assert not os.path.exists(escaped_target)
