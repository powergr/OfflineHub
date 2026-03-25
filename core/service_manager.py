"""
ServiceManager — tracks, health-checks, and controls all background processes.
"""

import socket
import threading
import time
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ServiceEntry:
    name:       str
    process:    object          # subprocess.Popen or None (virtual)
    port:       int
    status:     str = "running" # running | stopped | error
    virtual:    bool = False    # True = no process, just a port reservation
    restart_fn: Callable | None = None


class ServiceManager:

    def __init__(self):
        self._services: dict[str, ServiceEntry] = {}
        self._lock = threading.Lock()

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, name: str, process, port: int,
                 restart_fn: Callable | None = None):
        with self._lock:
            self._services[name] = ServiceEntry(
                name=name, process=process, port=port,
                status="running", restart_fn=restart_fn
            )

    def register_virtual(self, name: str, port: int):
        """Register a service that is served by the Flask app (no subprocess)."""
        with self._lock:
            self._services[name] = ServiceEntry(
                name=name, process=None, port=port,
                status="running", virtual=True
            )

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_status(self, name: str) -> str:
        with self._lock:
            entry = self._services.get(name)
        if entry is None:
            return "stopped"
        if entry.virtual:
            return "running"
        if entry.process is None:
            return "stopped"
        if entry.process.poll() is None:
            return "running"
        return "stopped"

    def get_port(self, name: str) -> int | None:
        with self._lock:
            entry = self._services.get(name)
        return entry.port if entry else None

    def all_services(self) -> dict[str, dict]:
        with self._lock:
            snap = dict(self._services)
        result = {}
        for name, entry in snap.items():
            result[name] = {
                "port":   entry.port,
                "status": self.get_status(name),
            }
        return result

    # ── Control ───────────────────────────────────────────────────────────────

    def stop(self, name: str):
        with self._lock:
            entry = self._services.get(name)
            
        if entry and entry.process and entry.process.poll() is None:
            try:
                # On Windows, skip the polite terminate() and kill it instantly
                # for a lightning-fast app shutdown.
                entry.process.kill()
                entry.process.wait(timeout=1)
            except Exception:
                pass
                
        with self._lock:
            self._services.pop(name, None)

    def restart(self, name: str):
        with self._lock:
            entry = self._services.get(name)
        if entry and entry.restart_fn:
            self.stop(name)
            entry.restart_fn()

    def stop_all(self):
        with self._lock:
            names = list(self._services.keys())
        for name in names:
            try:
                self.stop(name)
            except Exception:
                pass

    # ── Health check ──────────────────────────────────────────────────────────

    def health_check_all(self):
        """
        Ping every service's port. If a process has died and a restart
        function is registered, call it automatically.
        """
        with self._lock:
            snap = dict(self._services)

        for name, entry in snap.items():
            if entry.virtual:
                continue
            alive = _port_open("127.0.0.1", entry.port)
            if not alive:
                # Mark stopped
                with self._lock:
                    if name in self._services:
                        self._services[name].status = "error"
                # Auto-restart if handler provided
                if entry.restart_fn:
                    try:
                        entry.restart_fn()
                    except Exception:
                        pass


def _port_open(host: str, port: int) -> bool:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex((host, port)) == 0
    except Exception:
        return False