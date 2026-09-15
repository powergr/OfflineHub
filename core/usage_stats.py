"""
usage_stats: aggregate, per-module "how many times was this opened" counts.
A school admin can see what students actually use instead of guessing what
to download more of (plan.md Phase 4, item 15).

Deliberately just a single integer per module key - no timestamps, no
per-student identity, no IP addresses, nothing that could be correlated
back to an individual in a school full of minors. A page refresh or
re-open counts again; this is a coarse "interest" signal, not an audit
log, and is never meant to answer "who opened this and when."

Persisted as one small JSON file (counts survive an app restart), written
with a lock around both the in-memory dict and the file write since
several students' requests can land at the same moment.
"""

import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

BASE_DIR = r"C:\OfflineHub"
STATS_PATH = os.path.join(BASE_DIR, "usage_stats.json")


class UsageTracker:

    def __init__(self, path: str = STATS_PATH):
        self._path = path
        self._lock = threading.Lock()
        self._counts: dict[str, int] = self._load()

    def _load(self) -> dict[str, int]:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
            return {str(k): int(v) for k, v in data.items()}
        except Exception:
            return {}

    def _save_locked(self):
        try:
            os.makedirs(os.path.dirname(self._path), exist_ok=True)
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._counts, f, indent=2)
        except Exception:
            logger.exception("Could not persist usage_stats.json")

    def record_open(self, module_key: str):
        with self._lock:
            self._counts[module_key] = self._counts.get(module_key, 0) + 1
            self._save_locked()

    def get_counts(self) -> dict[str, int]:
        with self._lock:
            return dict(self._counts)

    def forget(self, module_key: str):
        """Called when a module is removed, so a stale count doesn't
        reappear (attributed to a since-deleted module) if a differently
        named module later reuses the same folder key."""
        with self._lock:
            if module_key in self._counts:
                del self._counts[module_key]
                self._save_locked()
