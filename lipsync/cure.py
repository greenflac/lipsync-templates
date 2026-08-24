"""Provide remedy commands that can actually be executed on the machine where they are printed."""

from __future__ import annotations

import os

WINDOWS = os.name == "nt"

PY = "python" if WINDOWS else "python3"


def py_snippet(body: str) -> str:
    """Turn multi-line Python code into a single command runnable in any shell."""
    parts = [ln.strip() for ln in body.strip().splitlines() if ln.strip()]
    return f'{PY} -c "' + "; ".join(parts) + '"'


def mkdir(path) -> str:
    """Return a command that creates a directory with its parents, in either shell."""
    return f'mkdir "{path}"' if WINDOWS else f"mkdir -p {path}"


def download(url: str, dst) -> str:
    """Return a command that downloads a file from a URL. `curl` exists on both Windows 10+ and Unix."""
    return f'curl -sSL -o "{dst}" {url}' if WINDOWS else f"curl -sSL -o {dst} {url}"


def home(sub: str = "") -> str:
    """Return the home directory in the form the shell understands, not Python."""
    base = "%USERPROFILE%" if WINDOWS else "~"
    return f"{base}\\{sub}" if (WINDOWS and sub) else (f"{base}/{sub}" if sub else base)


def set_env(name: str, value: str = "...") -> str:
    """Return a command that sets an environment variable, in the shell where it is printed."""
    if not WINDOWS:
        return f"export {name}={value}"
    return (
        f'$env:{name} = "{value}"   (this window only)\n'
        f'  setx {name} "{value}"   (permanent, picked up in a new window)'
    )
