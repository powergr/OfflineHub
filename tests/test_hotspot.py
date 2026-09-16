"""
Tests core/hotspot.py's HotspotManager.stop() guard: it must skip the real
subprocess work (a powershell.exe WinRT call plus a netsh call, each with
its own multi-second timeout) when the hotspot was never started. Before
this fix, stop() ran unconditionally, so main.py's quit_app() paid that
real cost on every single Quit regardless of whether hotspot was ever
enabled - confirmed against a real app log showing "Quit requested" with
no matching hotspot config enabled, and the process taking close to the
25-second watchdog window to actually exit.
"""

from unittest.mock import patch

from core.hotspot import HotspotManager, _ps_single_quoted


def _mgr():
    return HotspotManager({"hotspot": {"ssid": "Test", "password": "testpass123"}})


def test_stop_is_noop_when_never_started():
    mgr = _mgr()
    assert mgr.is_running() is False
    with patch("subprocess.run") as run:
        mgr.stop()
    run.assert_not_called()


def test_stop_runs_real_work_when_running():
    mgr = _mgr()
    mgr._running = True
    with patch("subprocess.run") as run:
        mgr.stop()
    assert run.called
    assert mgr.is_running() is False


def test_stop_after_stop_is_noop():
    mgr = _mgr()
    mgr._running = True
    with patch("subprocess.run"):
        mgr.stop()
    assert mgr.is_running() is False
    with patch("subprocess.run") as run:
        mgr.stop()
    run.assert_not_called()


# ── PowerShell injection (_ps_single_quoted) ────────────────────────────────
# Regression coverage: _try_winrt() used to f-string the hotspot SSID/
# password straight into a single-quoted PowerShell string literal with no
# escaping - a password containing a single quote could break out of it and
# inject arbitrary PowerShell, run by this already-elevated app.

def test_ps_single_quoted_escapes_a_lone_quote():
    assert _ps_single_quoted("it's") == "it''s"


def test_ps_single_quoted_escapes_a_full_injection_attempt():
    payload = "x'; Start-Process calc; '"
    escaped = _ps_single_quoted(payload)
    # The escaped value must be safe to drop straight into '...' - no
    # unescaped single quote can remain anywhere in it.
    assert "'" not in escaped.replace("''", "")


def test_ps_single_quoted_leaves_ordinary_text_unchanged():
    assert _ps_single_quoted("MySchoolWifi123") == "MySchoolWifi123"


def test_try_winrt_script_uses_the_escaped_password(monkeypatch):
    """The escaping helper existing isn't enough on its own - confirm
    _try_winrt() actually calls it for both the ssid and the password
    rather than interpolating the raw values."""
    import subprocess

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["script"] = cmd[-1]

        class _Result:
            stdout = "OK"
            returncode = 0

        return _Result()

    monkeypatch.setattr(subprocess, "run", fake_run)

    mgr = _mgr()
    mgr._try_winrt("School'; evil; '", "pass'word")

    script = captured["script"]
    assert "$cfg.Ssid = 'School''; evil; '''" in script
    assert "$cfg.Passphrase = 'pass''word'" in script
