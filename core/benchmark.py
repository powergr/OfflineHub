"""
Quick hardware check for the Offline Assistant (plan.md item 35).

Reads RAM, CPU cores and free disk, times a short memory-copy test, and turns
those into a 0-100 score plus a recommended assistant model. Standard library
only: no psutil, no vendor binary.

Why memory speed: on a CPU, generating each word means reading the whole
model from RAM once. So memory bandwidth, more than raw CPU clock, sets how
fast a reply appears.

Honest limits: the score is a rough guide, not a measured tokens-per-second
number. The curve points below are reasoned estimates, not calibrated against
real inference runs. Hard requirements (RAM and disk) come from the catalogue
itself and are reliable. The score only gates the largest model.
"""

import ctypes
import os
import shutil
import sys
import time

_GB = 1024 ** 3

# Model file sizes sit in RAM while answering, plus working memory for the
# conversation. Used only for the "free disk" check, not for RAM.
_DISK_HEADROOM = 1.25


def _interp(x: float, points: list[tuple[float, float]]) -> float:
    """Linear interpolation through (x, y) points sorted by x, clamped at both ends."""
    if x <= points[0][0]:
        return points[0][1]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if x <= x1:
            return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    return points[-1][1]


# (value, points) pairs. Value is total RAM in GB, copy speed in GB/s, cores.
_RAM_CURVE = [(4, 5), (8, 40), (16, 75), (32, 100)]
_BANDWIDTH_CURVE = [(2, 5), (5, 35), (10, 70), (20, 100)]
_CORES_CURVE = [(2, 10), (4, 40), (8, 80), (16, 100)]

_WEIGHTS = {"ram": 0.5, "bandwidth": 0.3, "cores": 0.2}


class _MemoryStatus(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_uint32),
        ("dwMemoryLoad", ctypes.c_uint32),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


def read_memory() -> tuple[int, int]:
    """Returns (total_bytes, available_bytes), or (0, 0) if it cannot be read."""
    try:
        if sys.platform == "win32":
            status = _MemoryStatus()
            status.dwLength = ctypes.sizeof(_MemoryStatus)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
                return 0, 0
            return int(status.ullTotalPhys), int(status.ullAvailPhys)
        page = os.sysconf("SC_PAGE_SIZE")
        return page * os.sysconf("SC_PHYS_PAGES"), page * os.sysconf("SC_AVPHYS_PAGES")
    except (OSError, ValueError, AttributeError):
        return 0, 0


def free_disk_bytes(path: str) -> int:
    """Free bytes on the drive holding `path`, walking up to a folder that exists."""
    probe = os.path.abspath(path)
    while probe and not os.path.exists(probe):
        parent = os.path.dirname(probe)
        if parent == probe:
            break
        probe = parent
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return 0


def measure_copy_speed(size_mb: int = 64, runs: int = 3) -> float:
    """
    Times a plain in-memory copy and returns the best run in GB/s.

    The buffer is filled with real bytes first. A freshly allocated zeroed
    buffer reads from shared zero pages and would give a falsely fast result.
    """
    buf = bytearray(b"\xa5") * (size_mb * 1024 * 1024)
    best = 0.0
    for _ in range(runs):
        start = time.perf_counter()
        copy = bytes(buf)
        elapsed = time.perf_counter() - start
        del copy
        if elapsed > 0:
            best = max(best, (size_mb / 1024) / elapsed)
    return round(best, 2)


def score_hardware(total_ram_gb: float, copy_gbps: float, cores: int) -> dict:
    """Returns {"score": 0-100, "tier": "basic"|"good"|"strong", "parts": {...}}."""
    parts = {
        "ram": _interp(total_ram_gb, _RAM_CURVE),
        "bandwidth": _interp(copy_gbps, _BANDWIDTH_CURVE),
        "cores": _interp(cores, _CORES_CURVE),
    }
    score = round(sum(parts[k] * w for k, w in _WEIGHTS.items()))
    tier = "basic" if score < 35 else "good" if score < 65 else "strong"
    return {"score": score, "tier": tier, "parts": {k: round(v) for k, v in parts.items()}}


def assess_models(
    llm_catalogue: dict, total_ram_gb: float | None, free_disk: int, score: int,
) -> dict:
    """
    Checks every assistant model against this PC.

    Returns {"recommended": key or None,
             "models": {key: {"fits": bool, "blockers": [code, ...]}}}.
    Blocker codes are "ram", "disk" and "score". The recommendation is the
    largest model with no blockers. Pass total_ram_gb=None when RAM could not
    be read: the RAM check is skipped rather than blocking every model.
    """
    models = {}
    for key, item in llm_catalogue.items():
        blockers = []
        if total_ram_gb is not None and total_ram_gb < item.get("min_ram_gb", 0):
            blockers.append("ram")
        if free_disk < item["size"] * _DISK_HEADROOM:
            blockers.append("disk")
        if score < item.get("min_score", 0):
            blockers.append("score")
        models[key] = {"fits": not blockers, "blockers": blockers}

    fitting = [k for k, v in models.items() if v["fits"]]
    recommended = max(fitting, key=lambda k: llm_catalogue[k]["size"]) if fitting else None
    return {"recommended": recommended, "models": models}


def run_benchmark(llm_catalogue: dict, modules_dir: str) -> dict:
    """Runs the whole check and returns one JSON-friendly result."""
    total, available = read_memory()
    cores = os.cpu_count() or 1
    free = free_disk_bytes(modules_dir)
    copy_gbps = measure_copy_speed()

    total_gb = total / _GB
    result = score_hardware(total_gb, copy_gbps, cores)
    result.update({
        "total_ram_gb": round(total_gb, 1),
        "available_ram_gb": round(available / _GB, 1),
        "cores": cores,
        "free_disk_gb": round(free / _GB, 1),
        "copy_gbps": copy_gbps,
    })
    result["ram_known"] = total > 0
    result.update(assess_models(
        llm_catalogue, total_gb if total > 0 else None, free, result["score"],
    ))
    return result
