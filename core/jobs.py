"""
JobTracker: tracks background download/install progress for the admin UI.

Each job's progress/done callbacks are created per-call via new_job()/
progress_cb(job_id)/done_cb(job_id, ...), so job_id is always a bound
parameter, never a shared loop variable a background thread could see change
out from under it. This is the fix for the old setup wizard's closure bug,
where progress/done callbacks closed over a `for` loop's shared variables.
"""

import threading
import uuid
from typing import Callable


class JobTracker:

    def __init__(self):
        self._jobs: dict[str, dict] = {}
        self._lock = threading.Lock()

    def new_job(self) -> str:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {
                "pct": 0.0, "speed": 0.0, "done": False,
                "success": None, "error": None,
            }
        return job_id

    def progress_cb(self, job_id: str) -> Callable[[float, float], None]:
        def cb(pct: float, speed: float):
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["pct"] = pct
                    self._jobs[job_id]["speed"] = speed
        return cb

    def done_cb(self, job_id: str, on_success: Callable[[str], None] | None = None
                ) -> Callable[[bool, str, str | None], None]:
        def cb(success: bool, path: str, error: str | None = None):
            if success and on_success:
                try:
                    on_success(path)
                except Exception as e:
                    success = False
                    error = str(e)
            with self._lock:
                if job_id in self._jobs:
                    self._jobs[job_id]["done"] = True
                    self._jobs[job_id]["success"] = success
                    self._jobs[job_id]["error"] = error
                    if success:
                        self._jobs[job_id]["pct"] = 100.0
        return cb

    def get(self, job_id: str) -> dict | None:
        with self._lock:
            job = self._jobs.get(job_id)
            return dict(job) if job else None
