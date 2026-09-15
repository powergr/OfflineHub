"""
Tests JobTracker's progress/done tracking, in particular that a failure's
plain-English error message (see core/downloader.py's _friendly_error)
actually reaches the job dict the admin UI polls - not just success/failure.
"""

from core.jobs import JobTracker


def test_new_job_starts_at_zero_percent_not_done():
    tracker = JobTracker()
    job_id = tracker.new_job()
    job = tracker.get(job_id)
    assert job == {
        "pct": 0.0, "speed": 0.0, "done": False,
        "success": None, "error": None, "cancelled": False,
    }


def test_progress_cb_updates_job():
    tracker = JobTracker()
    job_id = tracker.new_job()
    tracker.progress_cb(job_id)(42.5, 1200.0)
    job = tracker.get(job_id)
    assert job["pct"] == 42.5
    assert job["speed"] == 1200.0
    assert job["done"] is False


def test_done_cb_success_sets_pct_to_100():
    tracker = JobTracker()
    job_id = tracker.new_job()
    tracker.done_cb(job_id)(True, "/some/path")
    job = tracker.get(job_id)
    assert job["done"] is True
    assert job["success"] is True
    assert job["pct"] == 100.0
    assert job["error"] is None


def test_done_cb_failure_carries_friendly_error_message_through():
    tracker = JobTracker()
    job_id = tracker.new_job()
    tracker.done_cb(job_id)(False, "/some/path", "Not enough disk space to finish this download.")
    job = tracker.get(job_id)
    assert job["done"] is True
    assert job["success"] is False
    assert job["error"] == "Not enough disk space to finish this download."


def test_done_cb_on_success_callback_exception_is_reported_as_failure():
    tracker = JobTracker()
    job_id = tracker.new_job()

    def on_success(path):
        raise ValueError("install step failed")

    tracker.done_cb(job_id, on_success)(True, "/some/path")
    job = tracker.get(job_id)
    assert job["success"] is False
    assert job["error"] == "install step failed"


def test_get_returns_none_for_unknown_job():
    tracker = JobTracker()
    assert tracker.get("does-not-exist") is None


def test_cancel_sets_cancelled_flag_and_the_shared_event():
    tracker = JobTracker()
    job_id = tracker.new_job()
    event = tracker.cancel_event(job_id)
    assert not event.is_set()

    assert tracker.cancel(job_id) is True

    assert tracker.get(job_id)["cancelled"] is True
    assert event.is_set()


def test_cancel_event_returns_the_same_event_every_call():
    tracker = JobTracker()
    job_id = tracker.new_job()
    assert tracker.cancel_event(job_id) is tracker.cancel_event(job_id)


def test_cancel_returns_false_for_unknown_job():
    tracker = JobTracker()
    assert tracker.cancel("does-not-exist") is False


def test_cancel_returns_false_once_job_is_already_done():
    tracker = JobTracker()
    job_id = tracker.new_job()
    tracker.done_cb(job_id)(True, "/some/path")
    assert tracker.cancel(job_id) is False
    assert tracker.get(job_id)["cancelled"] is False


def test_cancelled_flag_survives_the_background_thread_s_own_done_cb():
    """A background job notices cancel_event and calls done_cb(False, ...,
    "Cancelled") itself - the earlier cancel() call's flag must still be
    there afterward, since that's what the admin UI actually checks."""
    tracker = JobTracker()
    job_id = tracker.new_job()
    tracker.cancel(job_id)
    tracker.done_cb(job_id)(False, "", "Cancelled")
    job = tracker.get(job_id)
    assert job["cancelled"] is True
    assert job["done"] is True
    assert job["success"] is False
