"""
ContentRegistry: tracks installed modules' in-process handles and status.

Replaces the old ServiceManager. Nothing here is a subprocess anymore: ZIM
modules are read in-process via libzim, mbtiles modules are read in-process
via sqlite, and LLM modules are read in-process via onnxruntime-genai. This
class exists to hold those open handles (so they're opened once, not per
request) and to report status to the admin UI.
"""

import threading
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ModuleEntry:
    name:   str
    kind:   str            # "zim" | "mbtiles" | "llm"
    status: str = "loaded"  # loaded | error | unloaded
    handle: Any = None      # ZimReader | None (mbtiles goes through TileServer) | LLMEngine
    error:  str | None = None


class ContentRegistry:

    def __init__(self):
        self._modules: dict[str, ModuleEntry] = {}
        self._lock = threading.Lock()

    # ── Registration ──────────────────────────────────────────────────────────

    def register(self, name: str, kind: str, handle: Any = None):
        with self._lock:
            self._modules[name] = ModuleEntry(name=name, kind=kind, handle=handle)

    def mark_error(self, name: str, message: str):
        with self._lock:
            entry = self._modules.get(name)
            if entry:
                entry.status = "error"
                entry.error = message
            else:
                self._modules[name] = ModuleEntry(
                    name=name, kind="unknown", status="error", error=message
                )

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_handle(self, name: str) -> Any:
        with self._lock:
            entry = self._modules.get(name)
        return entry.handle if entry else None

    def get_status(self, name: str) -> str:
        with self._lock:
            entry = self._modules.get(name)
        return entry.status if entry else "unloaded"

    def all_modules(self) -> dict[str, dict]:
        with self._lock:
            snap = dict(self._modules)
        return {
            name: {"kind": e.kind, "status": e.status, "error": e.error}
            for name, e in snap.items()
        }

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def unload(self, name: str):
        with self._lock:
            entry = self._modules.pop(name, None)
        if entry and entry.handle is not None:
            close = getattr(entry.handle, "close", None)
            if callable(close):
                try:
                    close()
                except Exception:
                    pass

    def unload_all(self):
        with self._lock:
            names = list(self._modules.keys())
        for name in names:
            self.unload(name)
