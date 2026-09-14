"""
single_instance — OS-level guard against a second OfflineHub process
running at the same time.

Confirmed live this session: nothing stopped a second launch, and two
processes sharing the same C:\\OfflineHub\\config.json and the same port
8000 (Windows' SO_REUSEADDR lets a second process bind an already-
listening port without erroring, unlike POSIX) raced on both - each holds
its own in-memory config loaded at its own startup, and independently
overwrites config.json whenever any settings route saves, so whichever
process saves last silently wins. That's how the admin password ended up
reset to a value nobody entered on purpose: two setup/settings flows ran
against two different in-memory configs pointed at the same file.

A named Windows Mutex is used rather than a lock/PID file because the OS
releases it automatically the instant the process exits *or crashes* - a
stale PID file left behind by a hard crash would otherwise permanently
block every future launch until someone finds and deletes it by hand.
"""

import ctypes
import logging

logger = logging.getLogger(__name__)

_ERROR_ALREADY_EXISTS = 183
_MUTEX_NAME = "OfflineHub_SingleInstance_Mutex"

# Holds the handle for the process's lifetime - it's the OS-level handle,
# not this Python reference, that other processes' CreateMutexW calls see,
# but keeping a reference prevents anything from closing it early.
_handle = None


def acquire(name: str = _MUTEX_NAME) -> bool:
    """
    Returns True if this process now owns the lock (first instance), False
    if another process already holds it. Safe to call more than once in
    the same process - only the first successful acquisition is kept.
    """
    global _handle

    try:
        handle = ctypes.windll.kernel32.CreateMutexW(None, False, name)
    except Exception:
        logger.exception("Could not check for another running instance - allowing this one to start.")
        return True

    if not handle:
        # CreateMutexW failed for an unrelated reason (e.g. access denied).
        # Fail open rather than blocking every future launch over an OS
        # error that has nothing to do with a real second instance.
        logger.warning("CreateMutexW returned no handle - allowing this instance to start unguarded.")
        return True

    if ctypes.windll.kernel32.GetLastError() == _ERROR_ALREADY_EXISTS:
        ctypes.windll.kernel32.CloseHandle(handle)
        return False

    _handle = handle
    return True
