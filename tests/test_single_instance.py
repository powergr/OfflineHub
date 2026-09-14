"""
Tests single_instance.acquire()'s Windows named-mutex guard. Calling
CreateMutexW twice for the same name - even from the same process - is the
real mechanism a second OfflineHub process launch is detected by, so
exercising that within one test process is a faithful test of the actual
cross-process codepath, not a simulation of it. Each test uses its own
unique mutex name so tests never interfere with each other or with a real
running OfflineHub instance's "OfflineHub_SingleInstance_Mutex".
"""

import uuid

from core.single_instance import acquire


def _unique_name() -> str:
    return f"OfflineHubTest_{uuid.uuid4().hex}"


def test_first_acquire_succeeds():
    assert acquire(_unique_name()) is True


def test_second_acquire_of_same_name_fails():
    name = _unique_name()
    assert acquire(name) is True
    assert acquire(name) is False


def test_different_names_do_not_interfere():
    assert acquire(_unique_name()) is True
    assert acquire(_unique_name()) is True
