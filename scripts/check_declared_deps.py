#!/usr/bin/env python3
"""Каждый импортируемый сторонний пакет объявлен в requirements-dev.txt.

    python scripts/check_declared_deps.py --check

ЗАЧЕМ. `imageio-ffmpeg` использовался ЧЕТЫРЬМЯ модулями и не был объявлен
нигде. Локально пакет стоял — он приезжает попутно с чужими зависимостями, —
поэтому и гейт, и зеркало CI были зелёными, а настоящий CI упал на первом же
тесте, которому пакет понадобился (2026-08-31).

ПОЧЕМУ ЗЕРКАЛО CI ЭТОГО НЕ ЛОВИЛО, и это его честный предел: `check_as_ci`
собирает рабочее дерево на HEAD в отдельном worktree и запускает там гейт —
то есть повторяет КОД, который увидит CI, в ЭТОМ окружении. Набор пакетов оно
не воспроизводит и воспроизвести не может: для этого нужна чистая установка по
requirements, а это другая машина. Поэтому проверка нужна отдельная и дешёвая —
сравнение импортов со списком, без установки чего-либо.

Три исхода (Р1): все объявлены / есть необъявленные / нечего проверять.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
REQUIREMENTS = REPO / "requirements-dev.txt"

#: Уже существовавшие на момент появления этой проверки (2026-08-31). Красить
#: гейт на них значило бы заблокировать любой коммит ради чужого долга, а
#: молча их не считать — превратить проверку в украшение. Поэтому список
#: ИМЕНОВАННЫЙ и печатается в отчёте: он виден, он грепается, и каждый НОВЫЙ
#: необъявленный пакет красит сборку.
#:
#: Пять из семи живут в `lipsync/**`, который заморожен (владелец NOBODY в
#: studio/CONTRACTS.md) — их не тронуть по правилу об одном писателе. Два
#: остальных: pyarrow нужен только сборке банка, которая руками запускается, а
#: pydantic приезжает попутно с fastapi и потому локально всегда есть.
KNOWN_UNDECLARED: dict[str, str] = {
    "creative-eval": "lipsync/** заморожен",
    "fal-client": "lipsync/** заморожен",
    "insightface": "lipsync/** заморожен",
    "mediapipe": "lipsync/** заморожен",
    "requests": "lipsync/** заморожен; в scripts/ab_run.py тот же пакет",
    "pyarrow": "нужен только ручной сборке банка, в гейте не участвует",
    "pydantic": "приезжает попутно с fastapi, поэтому локально всегда есть",
}

#: Каталоги, чьи импорты обязаны быть объявлены.
ROOTS = ("studio", "scripts", "lipsync")

#: Пакеты стандартной библиотеки и свои модули проверять не надо. Список
#: своих — по именам каталогов верхнего уровня; стандартную библиотеку даёт
#: сам Python, а не догадка.
OURS = frozenset({"studio", "scripts", "lipsync", "tests"})


def _our_modules() -> frozenset[str]:
    """Свои модули по именам файлов и каталогов, а не по догадке.

    Без этого `read_sources` из `scripts/` читался как пакет с PyPI и попадал
    в нарушения — правдоподобно и неверно.
    """
    names: set[str] = set(OURS)
    for root in ROOTS:
        directory = REPO / root
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.py"):
            names.add(path.stem)
        for path in directory.iterdir():
            if path.is_dir():
                names.add(path.name)
    return frozenset(names)


#: Имя пакета на PyPI не всегда совпадает с именем импорта. Пары названы явно:
#: угадывать по подчёркиваниям значит однажды угадать неверно и промолчать.
IMPORT_TO_PACKAGE = {
    "imageio_ffmpeg": "imageio-ffmpeg",
    "PIL": "pillow",
    "yaml": "pyyaml",
    "dateutil": "python-dateutil",
    "multipart": "python-multipart",
    "sentence_transformers": "sentence-transformers",
}


def declared(text: str) -> set[str]:
    """Имена пакетов из requirements, в нижнем регистре, без версий."""
    out: set[str] = set()
    for line in text.splitlines():
        line = line.split("#")[0].strip()
        if not line:
            continue
        for sep in ("==", ">=", "<=", "~=", "[", ";"):
            line = line.split(sep)[0]
        out.add(line.strip().lower().replace("_", "-"))
    return out


def imported(tree: ast.AST) -> set[str]:
    """Имена, отсутствие которых УРОНИТ код, а не даст ему сказать «не смогли».

    Различаются два импорта, и разница не косметическая:

    ОБЯЗАТЕЛЬНЫЙ — на верхнем уровне модуля, либо внутри функции, но без
    `try/except`. Пакета нет — падает импорт или падает вызов, и никакого
    третьего исхода не остаётся.

    НЕОБЯЗАТЕЛЬНЫЙ — внутри `try`, у которого есть `except`. Так в этом
    репозитории намеренно устроены torch, sentence-transformers и pyarrow:
    отсутствие пакета превращается в честное «не смогли» с кодом ошибки, и
    объявлять его в requirements не нужно.

    Именно эту границу перешёл тест на видео 2026-08-31: импорт стоял внутри
    функции, но без `try`, и CI упал вместо того, чтобы сказать «не смогли».
    """
    guarded: set[ast.AST] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Try):
            for child in node.body:
                for inner in ast.walk(child):
                    guarded.add(inner)

    found: set[str] = set()
    for node in ast.walk(tree):
        if node in guarded:
            continue
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.add(node.module.split(".")[0])
    return found


def undeclared(files: dict[str, str], requirements: str) -> dict[str, list[str]]:
    """Пакет -> файлы, которые его импортируют, для всего необъявленного.

    Вынесено из точки входа (Т5): развилка должна быть достижима тестом без
    файлов на диске.
    """
    have = declared(requirements)
    standard = set(sys.stdlib_module_names)
    ours = _our_modules()
    missing: dict[str, list[str]] = {}
    for name, source in files.items():
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for module in imported(tree):
            if module in standard or module in ours or module.startswith("_"):
                continue
            package = IMPORT_TO_PACKAGE.get(module, module).lower().replace("_", "-")
            if package not in have:
                missing.setdefault(package, []).append(name)
    return {k: sorted(v) for k, v in sorted(missing.items())}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)

    files: dict[str, str] = {}
    for root in ROOTS:
        for path in sorted((REPO / root).rglob("*.py")):
            files[str(path.relative_to(REPO))] = path.read_text(encoding="utf-8")

    if not files or not REQUIREMENTS.is_file():
        print(f"\nпроверено 0\nнарушений 0\nне смогли 1\n\n{UNMEASURED}: нечего сверять")
        return 2

    found = undeclared(files, REQUIREMENTS.read_text(encoding="utf-8"))
    missing = {k: v for k, v in found.items() if k not in KNOWN_UNDECLARED}
    old = {k: v for k, v in found.items() if k in KNOWN_UNDECLARED}

    for package, where in missing.items():
        print(f"  НЕ ОБЪЯВЛЕН {package}: {', '.join(where[:3])}{' …' if len(where) > 3 else ''}")
    for package in sorted(old):
        print(f"  (давний, до правила: {package} — {KNOWN_UNDECLARED[package]})")

    outcome = FAIL if missing else PASS
    print(f"\nпроверено {len(files)}\nнарушений {len(missing)}\nне смогли {len(old)}")
    print(
        f"\n{outcome}: "
        + (
            f"{len(missing)} НОВЫХ пакет(ов) импортируются и не объявлены"
            if missing
            else f"{len(files)} файлов: новых необъявленных нет, давних {len(old)}"
        )
    )
    if not args.check:
        return 0
    return {PASS: 0, FAIL: 1, UNMEASURED: 2}[outcome]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
