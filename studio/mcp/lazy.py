"""A module that is imported the first time one of its names is read.

WHY. The server has to answer `initialize` fast on a cold machine: as a
project stdio server in a cloud session it timed out at the client's 30 s
connect limit, and a hosted connector is restarted by every deploy. The
planner (with `endpoints`, `recipes`, `factindex`, `pricing`) and the
capability search are needed by a TOOL CALL, never by the handshake or by
`tools/list`, so `server.py` binds them through `lazy(...)` and the first call
that reads a name pays for the import, once per process.

The proxy forwards attribute writes and deletes too, so `mock.patch.object`
on `server.planner` patches the real module, exactly as it did before.
"""

from __future__ import annotations

import importlib
import threading
from types import ModuleType
from typing import Any

_LOCK = threading.Lock()


class LazyModule(ModuleType):
    """Stands in for `name` until an attribute is read, then is that module."""

    def __init__(self, name: str) -> None:
        super().__init__(name)
        object.__setattr__(self, "_lazy_target", None)

    def _lazy_load(self) -> ModuleType:
        target = object.__getattribute__(self, "_lazy_target")
        if target is None:
            with _LOCK:
                target = object.__getattribute__(self, "_lazy_target")
                if target is None:
                    target = importlib.import_module(object.__getattribute__(self, "__name__"))
                    object.__setattr__(self, "_lazy_target", target)
        return target

    def __getattr__(self, attr: str) -> Any:
        return getattr(self._lazy_load(), attr)

    def __setattr__(self, attr: str, value: Any) -> None:
        setattr(self._lazy_load(), attr, value)

    def __delattr__(self, attr: str) -> None:
        delattr(self._lazy_load(), attr)

    def __dir__(self) -> list[str]:
        return dir(self._lazy_load())

    def __repr__(self) -> str:
        loaded = object.__getattribute__(self, "_lazy_target") is not None
        name = object.__getattribute__(self, "__name__")
        return f"<lazy module {name!r} ({'loaded' if loaded else 'not loaded'})>"


def lazy(name: str) -> Any:
    """`lazy("studio.planner")` in place of `from studio import planner`."""
    return LazyModule(name)


def loaded(module: Any) -> bool:
    """Has this lazy module been imported yet? A real module always has."""
    if isinstance(module, LazyModule):
        return object.__getattribute__(module, "_lazy_target") is not None
    return True
