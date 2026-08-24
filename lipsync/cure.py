"""Команды лечения, которые можно ВЫПОЛНИТЬ на той машине, где они напечатаны."""

from __future__ import annotations

import os

WINDOWS = os.name == "nt"

PY = "python" if WINDOWS else "python3"


def py_snippet(body: str) -> str:
    """Многострочный код на Python -> ОДНА команда, исполнимая в любой оболочке."""
    parts = [ln.strip() for ln in body.strip().splitlines() if ln.strip()]
    return f'{PY} -c "' + "; ".join(parts) + '"'


def mkdir(path) -> str:
    """Создать каталог вместе с родителями, в обеих оболочках."""
    return f'mkdir "{path}"' if WINDOWS else f"mkdir -p {path}"


def download(url: str, dst) -> str:
    """Скачать файл по адресу. `curl` есть и в Windows 10+, и в Unix."""
    return f'curl -sSL -o "{dst}" {url}' if WINDOWS else f"curl -sSL -o {dst} {url}"


def home(sub: str = "") -> str:
    """Домашний каталог в том виде, в каком его поймёт ОБОЛОЧКА, а не Python."""
    base = "%USERPROFILE%" if WINDOWS else "~"
    return f"{base}\\{sub}" if (WINDOWS and sub) else (f"{base}/{sub}" if sub else base)


def set_env(name: str, value: str = "...") -> str:
    """Задать переменную окружения — командой ТОЙ оболочки, где это печатают."""
    if not WINDOWS:
        return f"export {name}={value}"
    return (
        f'$env:{name} = "{value}"   (в этом окне)\n'
        f'  setx {name} "{value}"   (навсегда, подхватится в НОВОМ окне)'
    )
