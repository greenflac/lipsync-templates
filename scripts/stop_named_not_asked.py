#!/usr/bin/env python3
"""Хук остановки: назвал модель — покажи, что спрашивал о ней базу.

    # как хук (Claude Code, событие Stop; JSON приходит на stdin)
    python scripts/stop_named_not_asked.py

    # как гейт: негативный контроль в обе стороны
    python scripts/stop_named_not_asked.py --check

    # как прибор: пересчитать ложные срабатывания на живом следе
    python scripts/stop_named_not_asked.py --measure <каталог с *.jsonl>

ПОЧЕМУ ХУК, А НЕ АБЗАЦ. Инструкция сервера требует звать `model_advice` на
каждого сравниваемого кандидата. ИЗМЕРЕНО 2026-09-02 на следе этой сессии:
198 вызовов `model_advice` по 60 именам — и 144 текстовых блока, называющих
имя, по которому в том же файле не звался никто. Правило словами не
исполнялось ничем (Ц7).

ТРИ ИСХОДА (Р1) И ТРИ КОДА ВОЗВРАТА. `0` — годно, останавливаемся молча.
`2` — названо без запроса: Claude Code отдаёт stderr обратно модели и не даёт
закончить ход. `3` — не смогли прочесть след: НЕ блокирует, но и не молчит —
клиент показывает stderr человеку. Третий исход не сворачивается ни в первый
(«тихо, значит чисто»), ни во второй («заблокируем на всякий случай»).

`stop_hook_active` уважается: если ход уже был заблокирован этим хуком и
модель снова просится выйти, второй раз не блокируем — иначе выйдет петля,
которую человек снимет отключением хука, и правила не станет совсем.

Сети здесь нет (Т4). Стоимость: ИЗМЕРЕНО 0.22 с на следе 52 МБ / 16 669 строк
(чтение потоком, `json.loads` только на строках, где встретилось имя
инструмента или текстовый блок) плюс 0.10 с на загрузку 465 имён из базы.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

from studio import named_not_asked as nna  # noqa: E402

REPO = Path(__file__).resolve().parents[1]

#: Контрольный набор: вход, где хук обязан шевельнуться, и входы, где обязан
#: промолчать (И5). Ложные срабатывания — главный риск этого прибора, поэтому
#: негативных случаев здесь большинство, и три из них сняты с живого следа.
CONTROLS = REPO / "studio" / "fixtures" / "named_not_asked_controls.json"

#: Сколько исходов набор обязан различить. ВЫБРАНО 3: `pass`, `fail` и
#: `could not measure`. Третий исход стал достижим ПО ТЕКСТУ ответа, а не
#: только по нечитаемому следу: имя формы `torch-2.4` — это «разобрать не
#: смогли», и свернуть его в «чисто» значит соврать в самую дешёвую сторону.
CONTROL_OUTCOMES_MIN = 3

#: Код возврата, которым Claude Code возвращает stderr модели и запрещает
#: закончить ход. ВЫБРАНО не нами: это контракт хуков Claude Code.
EXIT_BLOCK = 2

#: Код «не смогли»: клиент покажет stderr человеку и НЕ станет блокировать.
EXIT_UNMEASURED = 3


def load_controls(path: Path = CONTROLS) -> list[dict[str, Any]]:
    """Случаи контроля. Отсутствие файла — это «не смогли», а не «годно»."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return list(raw.get("cases") or [])


def run_controls(cases: list[dict[str, Any]], names: list[str]) -> dict[str, Any]:
    """Прогон контроля. Вынесен из main (Т5): развилка обязана быть достижима."""
    if not cases:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "lines": ["контрольного набора нет — сравнивать не с чем"],
        }
    wanted = {"pass": PASS, "fail": FAIL, "unmeasured": UNMEASURED}
    lines: list[str] = []
    wrong = 0
    seen: set[str] = set()
    for case in cases:
        got = nna.judge(str(case["answer"]), list(case.get("asked") or []), names)
        seen.add(got["outcome"])
        expected = wanted[str(case["expect_outcome"])]
        ok = (
            got["outcome"] == expected
            and got["unasked"] == list(case.get("expect_unasked") or [])
            and got["outside_base"] == list(case.get("expect_outside") or [])
            and got["unsure"] == list(case.get("expect_unsure") or [])
        )
        if not ok:
            wrong += 1
            lines.append(
                f"  ПРОВАЛ {case['id']}: ждали {expected} "
                f"не-спрошено={case.get('expect_unasked') or []} "
                f"вне-базы={case.get('expect_outside') or []} "
                f"не-смогли={case.get('expect_unsure') or []}, вышло {got['outcome']} "
                f"{got['unasked']} {got['outside_base']} {got['unsure']}"
            )
        else:
            lines.append(
                f"  ok {case['id']}: {got['outcome']} "
                f"{got['unasked']}{got['outside_base']}{got['unsure']}"
            )
    missing = nna.verdict(REPO / "нет-такого-следа.jsonl")
    if missing["outcome"] != UNMEASURED:
        wrong += 1
        lines.append(f"  ПРОВАЛ нечитаемый след дал {missing['outcome']}, а не «не смогли»")
    else:
        lines.append("  ok нечитаемый след: could not measure, не свёрнут в pass")
    if len(seen) < CONTROL_OUTCOMES_MIN:
        wrong += 1
        lines.append(
            f"  ПРОВАЛ набор различил {len(seen)} исход(а), нужно {CONTROL_OUTCOMES_MIN}: "
            "прибор, отвечающий одинаково на всё, ничего не мерит"
        )
    return {
        "outcome": FAIL if wrong else PASS,
        "checked": len(cases) + 1,
        "violations": wrong,
        "unmeasured": 0,
        "lines": lines,
    }


def measure(directory: Path, names: list[str]) -> dict[str, Any]:
    """Ложные срабатывания на живом следе, числом (П1). Читает только *.jsonl."""
    files = sorted(directory.rglob("*.jsonl"))
    blocks = named_blocks = flagged = 0
    outside_cued = outside_wide = unsure_cued = 0
    raw = nna.name_pattern(names)
    hits: list[str] = []
    for path in files:
        asked: set[str] = set()
        answers: list[str] = []
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if nna.ADVICE_TOOL_SUFFIX not in line and '"text"' not in line:
                    continue
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict) or record.get("type") != "assistant":
                    continue
                for block in (record.get("message") or {}).get("content") or []:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use" and str(block.get("name", "")).endswith(
                        nna.ADVICE_TOOL_SUFFIX
                    ):
                        asked.add(str((block.get("input") or {}).get("model", "")).strip().lower())
                    elif block.get("type") == "text" and (block.get("text") or "").strip():
                        answers.append(str(block["text"]))
        for answer in answers:
            blocks += 1
            got = nna.judge(answer, sorted(asked), names)
            if raw is not None and raw.search(nna.countable_text(answer)):
                named_blocks += 1
            outside_wide += len(nna.classify(answer, names, cued_only=False)["outside"])
            outside_cued += len(got["outside_base"])
            unsure_cued += len(got["unsure"])
            if got["violations"]:
                flagged += 1
                hits.append(
                    f"  {path.name}: не спрошено {got['unasked']}, "
                    f"вне базы {got['outside_base']} :: {answer.strip()[:160]}"
                )
    return {
        "outcome": PASS if files else UNMEASURED,
        "checked": blocks,
        "violations": flagged,
        "unmeasured": 0 if files else 1,
        "named_blocks": named_blocks,
        "outside_cued": outside_cued,
        "outside_wide": outside_wide,
        "unsure_cued": unsure_cued,
        "lines": hits,
    }


def what_to_do(result: dict[str, Any]) -> str:
    """Что именно чинить. Два рода провала лечатся РАЗНЫМИ действиями (Р1).

    Про имя вне базы хук НЕ говорит «такой модели нет»: база собрана нами и
    заведомо неполна, «нет в базе» и «не существует» — разные утверждения, и
    второе мы доказать не можем. Сказать нужно «не смотрел» и пойти смотреть.
    """
    lines: list[str] = []
    if result.get("unasked"):
        lines.append(
            "Позови `model_advice` на каждое из имён, названных без запроса, "
            "или убери их из рекомендации: инструкция сервера требует спрашивать базу "
            "о КАЖДОМ сравниваемом кандидате, а не только о том, который нравится."
        )
    if result.get("outside_base"):
        lines.append(
            "Имена вне базы: НЕ пиши «такой модели нет» — этого мы не знаем, база "
            "заведомо неполна. Напиши «в базе этого нет, я не проверял», проверь имя "
            "поиском (`search_web`/`fetch_url`) ДО того, как советовать, и, если модель "
            "существует, положи найденное обратно через `record_model_fact`. "
            "Существование внешнего имени доказывается командой, а не уверенным тоном."
        )
    if result.get("unsure"):
        lines.append(
            "Разобрать не смогли: если это имена моделей — назови их так, как их пишет "
            "вендор, и позови `model_advice`; если это версии библиотек, они здесь ни при "
            "чём. Ход не остановлен, но и чистым он не считается."
        )
    return "\n".join(lines)


def hook(payload: dict[str, Any]) -> tuple[int, str]:
    """Решение хука по разобранному stdin. Вынесено из main (Т5)."""
    transcript = payload.get("transcript_path")
    result = nna.verdict(Path(transcript) if transcript else None)
    report = nna.render(result)
    if result["outcome"] == UNMEASURED:
        return EXIT_UNMEASURED, report + ("\n" + what_to_do(result) if result.get("unsure") else "")
    if result["outcome"] == FAIL:
        if payload.get("stop_hook_active"):
            return 0, report + " (ход уже был остановлен этим хуком — второй раз не держу)"
        return EXIT_BLOCK, report + "\n" + what_to_do(result)
    return 0, report


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="прогнать контрольный набор")
    parser.add_argument("--measure", type=Path, help="каталог со следами: посчитать срабатывания")
    args = parser.parse_args(argv)

    if args.check:
        try:
            cases = load_controls()
        except (OSError, ValueError) as exc:
            print(f"не смогли: контроль не прочитан: {type(exc).__name__}: {exc}")
            return EXIT_UNMEASURED
        outcome = run_controls(cases, nna.model_names())
        print("\n".join(outcome["lines"]))
        print(
            f"названо-но-не-спрошено: исход {outcome['outcome']}; "
            f"проверено {outcome['checked']}, нарушений {outcome['violations']}, "
            f"не смогли {outcome['unmeasured']}"
        )
        return 0 if outcome["outcome"] == PASS else 1

    if args.measure:
        outcome = measure(args.measure, nna.model_names())
        print("\n".join(outcome["lines"][:20]))
        print(
            f"следы: блоков ответа {outcome['checked']}, "
            f"из них называют имя из базы вообще {outcome['named_blocks']}, "
            f"нарушений в рекомендательной фразе {outcome['violations']}, "
            f"из них имён вне базы {outcome['outside_cued']}; "
            f"имён вне базы БЕЗ фильтра фразы (широкая сеть) {outcome['outside_wide']}, "
            f"разобрать не смогли (в рекомендательной фразе) {outcome['unsure_cued']}, "
            f"следов не прочитано {outcome['unmeasured']}"
        )
        return 0 if outcome["outcome"] == PASS else EXIT_UNMEASURED

    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError as exc:
        print(f"[названо-но-не-спрошено] не смогли разобрать stdin: {exc}", file=sys.stderr)
        return EXIT_UNMEASURED
    code, report = hook(payload if isinstance(payload, dict) else {})
    print(report, file=sys.stderr if code else sys.stdout)
    return code


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
