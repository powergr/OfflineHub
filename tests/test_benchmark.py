"""
Tests core/benchmark.py (plan.md item 35) and its admin route.

The scoring and model-matching logic is pure, so it is tested with exact
numbers. The hardware readers are checked against the real machine, only for
sanity (positive, plausible), since the true values differ per PC.
"""

import os

import pytest

from core import benchmark
from core.downloader import LLM_CATALOGUE

from test_admin_security import _authed_client, _csrf_token_for, _make_app, isolated_dirs  # noqa: F401

_GB = 1024 ** 3


# ── Pure scoring ──────────────────────────────────────────────────────────────

def test_interp_clamps_below_between_and_above():
    pts = [(4, 10), (8, 50)]
    assert benchmark._interp(1, pts) == 10
    assert benchmark._interp(6, pts) == 30
    assert benchmark._interp(99, pts) == 50


def test_score_is_higher_for_a_stronger_pc():
    weak = benchmark.score_hardware(4, 2, 2)
    strong = benchmark.score_hardware(32, 20, 16)
    assert weak["score"] < 35 and weak["tier"] == "basic"
    assert strong["score"] == 100 and strong["tier"] == "strong"


def test_score_tier_boundaries():
    assert benchmark.score_hardware(8, 5, 4)["tier"] == "good"
    assert 0 <= benchmark.score_hardware(0, 0, 1)["score"] <= 100


# ── Model matching ────────────────────────────────────────────────────────────

_PLENTY_DISK = 500 * _GB


def test_strong_pc_gets_the_largest_model():
    r = benchmark.assess_models(LLM_CATALOGUE, 32, _PLENTY_DISK, 90)
    assert r["recommended"] == "assistant_phi3_medium"


def test_mid_pc_gets_phi4_mini_not_the_slow_large_model():
    r = benchmark.assess_models(LLM_CATALOGUE, 16, _PLENTY_DISK, 72)
    assert r["recommended"] == "assistant_phi4_mini"
    assert r["models"]["assistant_phi3_medium"]["blockers"] == ["ram"]


def test_enough_ram_but_low_score_blocks_the_large_model():
    r = benchmark.assess_models(LLM_CATALOGUE, 32, _PLENTY_DISK, 50)
    assert r["models"]["assistant_phi3_medium"]["blockers"] == ["score"]
    assert r["recommended"] == "assistant_phi4_mini"


def test_small_ram_falls_back_to_phi3_mini():
    r = benchmark.assess_models(LLM_CATALOGUE, 6, _PLENTY_DISK, 40)
    assert r["recommended"] == "assistant_phi3_mini"
    assert "ram" in r["models"]["assistant_phi4_mini"]["blockers"]


def test_tiny_pc_gets_no_recommendation():
    r = benchmark.assess_models(LLM_CATALOGUE, 4, _PLENTY_DISK, 10)
    assert r["recommended"] is None
    assert not any(m["fits"] for m in r["models"].values())


def test_low_disk_blocks_a_model():
    # phi4_mini is 4.9 GB, so 5 GB free is below the 1.25x headroom.
    r = benchmark.assess_models(LLM_CATALOGUE, 16, 5 * _GB, 72)
    assert "disk" in r["models"]["assistant_phi4_mini"]["blockers"]
    assert r["recommended"] == "assistant_phi3_mini"


def test_unknown_ram_does_not_block_every_model():
    r = benchmark.assess_models(LLM_CATALOGUE, None, _PLENTY_DISK, 72)
    assert "ram" not in r["models"]["assistant_phi4_mini"]["blockers"]
    assert r["recommended"] is not None


def test_every_catalogue_model_declares_its_requirements():
    for key, item in LLM_CATALOGUE.items():
        assert item["min_ram_gb"] > 0, key
        assert 0 <= item["min_score"] <= 100, key


# ── Real hardware readers (sanity only) ───────────────────────────────────────

def test_read_memory_returns_plausible_numbers():
    total, available = benchmark.read_memory()
    assert total > 256 * 1024 ** 2
    assert 0 < available <= total


def test_free_disk_walks_up_from_a_missing_folder(tmp_path):
    missing = tmp_path / "does" / "not" / "exist"
    assert benchmark.free_disk_bytes(str(missing)) > 0


def test_measure_copy_speed_is_positive_and_reasonable():
    speed = benchmark.measure_copy_speed(size_mb=8, runs=2)
    assert 0.1 < speed < 1000


def test_run_benchmark_returns_a_complete_json_friendly_result(tmp_path):
    r = benchmark.run_benchmark(LLM_CATALOGUE, str(tmp_path))
    for field in ("score", "tier", "total_ram_gb", "cores", "free_disk_gb",
                  "copy_gbps", "ram_known", "recommended", "models"):
        assert field in r
    assert set(r["models"]) == set(LLM_CATALOGUE)
    assert r["cores"] == (os.cpu_count() or 1)


# ── Admin route ───────────────────────────────────────────────────────────────

def test_route_requires_a_login(isolated_dirs, tmp_path, monkeypatch):
    app, _ = _make_app(isolated_dirs, tmp_path, monkeypatch)
    resp = app.test_client().post("/admin/benchmark/run")
    assert resp.status_code in (302, 303, 401, 403)


def test_route_rejects_a_post_without_the_csrf_token(isolated_dirs, tmp_path, monkeypatch):
    app, _ = _make_app(isolated_dirs, tmp_path, monkeypatch)
    resp = _authed_client(app).post("/admin/benchmark/run")
    assert resp.status_code == 403


def test_route_returns_a_result_for_a_logged_in_admin(isolated_dirs, tmp_path, monkeypatch):
    app, _ = _make_app(isolated_dirs, tmp_path, monkeypatch)
    client = _authed_client(app)
    token = _csrf_token_for(client)

    resp = client.post("/admin/benchmark/run", headers={"X-CSRF-Token": token})

    assert resp.status_code == 200
    body = resp.get_json()
    assert 0 <= body["score"] <= 100
    assert "assistant_phi4_mini" in body["models"]


def test_llm_tab_renders_the_check_button_and_note_slots(isolated_dirs, tmp_path, monkeypatch):
    app, _ = _make_app(isolated_dirs, tmp_path, monkeypatch)
    html = _authed_client(app).get("/admin/modules").get_data(as_text=True)
    assert 'id="bench-btn"' in html
    for key in LLM_CATALOGUE:
        assert f'id="llm-note-{key}"' in html
