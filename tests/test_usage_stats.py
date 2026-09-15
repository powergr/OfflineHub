"""
Tests UsageTracker - aggregate, per-module "how many opens" counts (no
per-student identity, no timestamps - see core/usage_stats.py's own
docstring for why). Uses a tmp_path file for every test so the real
C:\\OfflineHub\\usage_stats.json is never touched.
"""

import json

import pytest

from core.usage_stats import UsageTracker


@pytest.fixture
def tracker(tmp_path):
    return UsageTracker(path=str(tmp_path / "usage_stats.json"))


def test_record_open_starts_a_module_at_one(tracker):
    tracker.record_open("wikipedia_en_mini")
    assert tracker.get_counts() == {"wikipedia_en_mini": 1}


def test_record_open_increments_on_repeat(tracker):
    for _ in range(3):
        tracker.record_open("wikipedia_en_mini")
    assert tracker.get_counts()["wikipedia_en_mini"] == 3


def test_counts_are_independent_per_module(tracker):
    tracker.record_open("wikipedia_en_mini")
    tracker.record_open("wikipedia_en_mini")
    tracker.record_open("assistant_phi3_mini")
    counts = tracker.get_counts()
    assert counts == {"wikipedia_en_mini": 2, "assistant_phi3_mini": 1}


def test_counts_persist_across_a_new_tracker_instance(tmp_path):
    path = str(tmp_path / "usage_stats.json")
    UsageTracker(path=path).record_open("wikipedia_en_mini")

    reloaded = UsageTracker(path=path)
    assert reloaded.get_counts() == {"wikipedia_en_mini": 1}


def test_forget_removes_a_module_count(tracker):
    tracker.record_open("wikipedia_en_mini")
    tracker.record_open("vikidia_en")
    tracker.forget("wikipedia_en_mini")
    assert tracker.get_counts() == {"vikidia_en": 1}


def test_forget_unknown_module_does_not_raise(tracker):
    tracker.forget("never_installed")  # must be a no-op, not an error


def test_get_counts_returns_a_copy_not_the_live_dict(tracker):
    tracker.record_open("wikipedia_en_mini")
    counts = tracker.get_counts()
    counts["wikipedia_en_mini"] = 999
    assert tracker.get_counts()["wikipedia_en_mini"] == 1


def test_corrupt_stats_file_is_treated_as_empty_not_raised(tmp_path):
    path = tmp_path / "usage_stats.json"
    path.write_text("{not valid json")
    tracker = UsageTracker(path=str(path))
    assert tracker.get_counts() == {}


def test_persisted_file_is_valid_json(tracker, tmp_path):
    tracker.record_open("wikipedia_en_mini")
    with open(tracker._path, encoding="utf-8") as f:
        data = json.load(f)
    assert data == {"wikipedia_en_mini": 1}
