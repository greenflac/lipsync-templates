"""Provide remedy commands that can actually be executed on the machine where they are printed."""

from __future__ import annotations

import os

WINDOWS = os.name == "nt"


def mkdir(path) -> str:
    """Return a command that creates a directory with its parents, in either shell.

    Example:
        >>> mkdir("/tmp/x")  # on a POSIX machine
        'mkdir -p /tmp/x'
    """
    return f'mkdir "{path}"' if WINDOWS else f"mkdir -p {path}"


def download(url: str, dst) -> str:
    """Return a command that downloads a file from a URL.

    `curl` ships with both Windows 10+ and every Unix, which is why it, and not
    wget or PowerShell, is what gets printed.

    Example:
        >>> download("https://h/m.bin", "/tmp/m.bin")  # on a POSIX machine
        'curl -sSL -o /tmp/m.bin https://h/m.bin'
    """
    return f'curl -sSL -o "{dst}" {url}' if WINDOWS else f"curl -sSL -o {dst} {url}"


def home(sub: str = "") -> str:
    """Return the home directory in the form the shell understands, not Python.

    Example:
        >>> home(".mediapipe")  # on a POSIX machine
        '~/.mediapipe'
    """
    base = "%USERPROFILE%" if WINDOWS else "~"
    return f"{base}\\{sub}" if (WINDOWS and sub) else (f"{base}/{sub}" if sub else base)


def set_env(name: str, value: str = "...") -> str:
    """Return a command that sets an environment variable, in the shell where it is printed.

    Example:
        >>> set_env("POLLINATIONS_API_KEY", "sk_...")  # on a POSIX machine
        'export POLLINATIONS_API_KEY=sk_...'
    """
    if not WINDOWS:
        return f"export {name}={value}"
    return (
        f'$env:{name} = "{value}"   (this window only)\n'
        f'  setx {name} "{value}"   (permanent, picked up in a new window)'
    )
