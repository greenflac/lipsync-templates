"""Батч поверх сквозного стенда: матрица драйвинг x стиль x личность."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

from .fork_identity import FAIL, PASS, UNMEASURED
from .fork_video import EXIT_BY_OUTCOME

from . import fork_e2e as E


OWNER_MATRIX = (5, 5, 2)

MODES = ("full", "cover")

MAX_STREAK = 3

NAME_SEP = "__"

BALANCE_ENV = "FAL_BALANCE_USD"


def live_balance() -> float | None:
    """Остаток на счету fal в долларах, либо `None` — «не смогли узнать»."""
    import os  # noqa: PLC0415

    raw = os.environ.get(BALANCE_ENV)
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def copy_clip(src, dst) -> tuple:
    """Готовый ролик -> отдельный файл с говорящим именем. `(путь, причина)`."""
    s = Path(src)
    if not s.is_file():
        return None, f"ролика {s} нет на диске: забирать нечего"
    if s.stat().st_size <= 0:
        return None, f"ролик {s} пустой (0 Б)"
    try:
        Path(dst).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(str(s), str(dst))
    except OSError as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return str(dst), None


def cell_name(driving, style, person) -> str:
    """`драйвинг__стиль__личность` — имя ролика, читаемое без отчёта."""
    return NAME_SEP.join(Path(str(p)).stem for p in (driving, style, person))


def cells(drivings, styles, persons, *, mode: str = "full") -> list:
    """Список ячеек матрицы по режиму покрытия. Неизвестный режим — отказ."""
    if mode not in MODES:
        raise ValueError(f"режим {mode!r} неизвестен, есть {list(MODES)}")
    axes = {"драйвингов": list(drivings), "стилей": list(styles), "личностей": list(persons)}
    empty = [k for k, v in axes.items() if not v]
    if empty:
        raise ValueError(f"пустые оси матрицы: {empty}; заказывать нечего")
    dr, st, pe = axes["драйвингов"], axes["стилей"], axes["личностей"]
    out = []
    if mode == "full":
        for d in dr:
            for s in st:
                for p in pe:
                    out.append((d, s, p))
    else:
        for i in range(max(len(dr), len(st), len(pe))):
            out.append((dr[i % len(dr)], st[i % len(st)], pe[i % len(pe)]))
    return [
        {"driving": d, "style": s, "person": p, "name": cell_name(d, s, p), "index": i + 1}
        for i, (d, s, p) in enumerate(out)
    ]


def plan_cost(n: int) -> float:
    """Цена n ячеек. Цена одного вызова ИМПОРТИРУЕТСЯ из стенда."""
    return round(int(n) * E.KLING_PRICE_USD, 4)


def afford(n: int, balance) -> dict:
    """Хватит ли денег на n ячеек. ТРИ исхода, и два из них НЕ пускают батч."""
    need = plan_cost(n)
    try:
        have = None if balance is None else float(balance)
    except (TypeError, ValueError):
        have = None
    if have is None:
        return {
            "outcome": UNMEASURED,
            "need": need,
            "have": None,
            "short": None,
            "note": (
                f"остаток счёта неизвестен: заказ на ${need} "
                f"({n} ячеек по ${E.KLING_PRICE_USD}) не начат. "
                f"Задай {BALANCE_ENV} или подставь свой прибор баланса"
            ),
        }
    if have + 1e-9 < need:
        short = round(need - have, 4)
        return {
            "outcome": FAIL,
            "need": need,
            "have": round(have, 4),
            "short": short,
            "note": (
                f"НЕ ХВАТАЕТ ${short}: заказ {n} ячеек по "
                f"${E.KLING_PRICE_USD} стоит ${need}, на счету "
                f"${round(have, 4)}. Батч НЕ начат: потратить половину "
                f"и встать посередине хуже, чем не начинать"
            ),
        }
    return {
        "outcome": PASS,
        "need": need,
        "have": round(have, 4),
        "short": 0.0,
        "note": (
            f"хватает: заказ ${need} ({n} ячеек по "
            f"${E.KLING_PRICE_USD}), на счету ${round(have, 4)}, "
            f"останется ${round(have - need, 4)}"
        ),
    }


def _cell_line(cell: dict) -> str:
    """Строка ячейки: вердикт и числа РЯДОМ с ним."""
    t = cell.get("totals") or {}
    return (
        f"[{cell['outcome']:<18}] ячейка {cell['index']:>2} "
        f"{cell['name']:<46} проверено {t.get('checked', 0)}, "
        f"нарушений {t.get('violations', 0)}, не смогли "
        f"{t.get('unmeasured', 0)} | {cell.get('note', '')}"
    )


def run_batch(
    *,
    drivings,
    styles,
    persons,
    mode: str = "full",
    first: int = 0,
    last: int = 0,
    windows=None,
    out_dir="work/batch",
    balance=None,
    cell_runner=None,
    collect=None,
    max_streak: int = MAX_STREAK,
    endpoint: str = None,
    log=None,
    **cell_kwargs,
) -> dict:
    """Весь батч: деньги -> ячейки по одной -> сводка. Возвращает свод."""
    runner = E.run if cell_runner is None else cell_runner
    take = copy_clip if collect is None else collect
    get_balance = live_balance if balance is None else balance
    where = Path(out_dir)
    clips_dir = where / "clips"
    wins = dict(windows or {})

    grid = cells(drivings, styles, persons, mode=mode)
    n = len(grid)
    full_n = len(drivings) * len(styles) * len(persons)
    E.say(
        f"батч: матрица {len(drivings)}x{len(styles)}x{len(persons)}, режим "
        f"«{mode}» -> {n} ячеек (полный крест дал бы {full_n}); цена "
        f"${E.KLING_PRICE_USD} за ячейку, заказ ${plan_cost(n)}",
        log=log,
    )

    ep = E.KLING_ENDPOINT if endpoint is None else endpoint
    E.refuse_pro(ep)

    before = get_balance()
    money = afford(n, before)
    E.say(
        f"[{money['outcome']:<18}] деньги до старта{'':<28} "
        f"нужно ${money['need']}, есть "
        f"{'?' if money['have'] is None else '$' + str(money['have'])} | "
        f"{money['note']}",
        log=log,
    )
    if money["outcome"] != PASS:
        E.say(f"ИТОГ: {money['outcome']} — батч НЕ НАЧАТ, заказов 0, потрачено $0.0", log=log)
        return {
            "outcome": money["outcome"],
            "mode": mode,
            "planned": n,
            "attempted": 0,
            "passed": 0,
            "failed": 0,
            "unmeasured": 0,
            "money": money,
            "balance_before": money["have"],
            "balance_after": None,
            "spent_expected": 0.0,
            "spent_actual": None,
            "cells": [],
            "clips": [],
            "stopped_early": False,
            "exit_code": EXIT_BY_OUTCOME[money["outcome"]],
        }

    done, streak, stopped = [], 0, False
    for cell in grid:
        if stopped:
            cell = dict(
                cell,
                outcome=UNMEASURED,
                totals={},
                clip=None,
                launched=False,
                note=(f"не запускалась: батч остановлен после {max_streak} неудач подряд"),
            )
            done.append(cell)
            E.say(_cell_line(cell), log=log)
            continue
        cell = dict(cell, launched=True)
        cell_dir = where / "cells" / cell["name"]
        win = wins.get(str(cell["driving"]), (first, last))
        try:
            got = runner(
                client_photo=cell["person"],
                style_ref=cell["style"],
                driving=cell["driving"],
                first=win[0],
                last=win[1],
                out_dir=str(cell_dir),
                log=log,
                **cell_kwargs,
            )
        except Exception as exc:  # noqa: BLE001
            cell.update(
                outcome=UNMEASURED,
                totals={},
                clip=None,
                note=f"прогон обвалился: {type(exc).__name__}: {exc}",
            )
        else:
            reply = got if isinstance(got, dict) else {}
            outcome = reply.get("outcome")
            if outcome not in (PASS, FAIL, UNMEASURED):
                cell.update(
                    outcome=UNMEASURED,
                    totals={},
                    clip=None,
                    note=(f"прогон ответил {type(got).__name__} без вердикта: судить нечем"),
                )
            else:
                note = f"встал на «{reply.get('stopped_at', '?')}»"
                clip, why = None, None
                if outcome == PASS:
                    clip, why = take(cell_dir / "final_9x16.mp4", clips_dir / f"{cell['name']}.mp4")
                    if clip is None:
                        outcome = UNMEASURED
                        note = f"вердикт «{PASS}», но ролика нет: {why}"
                    else:
                        note = f"ролик {clip}"
                cell.update(outcome=outcome, totals=reply.get("totals") or {}, clip=clip, note=note)
        done.append(cell)
        E.say(_cell_line(cell), log=log)
        streak = 0 if cell["outcome"] == PASS else streak + 1
        if streak >= max_streak:
            stopped = True
            E.say(
                f"ОСТАНОВ: {streak} неудач подряд при пороге {max_streak} — "
                f"это уже не плохая пара, а поломка; дальше жгли бы по "
                f"${E.KLING_PRICE_USD} за ячейку",
                log=log,
            )

    attempted = sum(1 for c in done if c.get("launched"))
    passed = sum(1 for c in done if c["outcome"] == PASS)
    failed = sum(1 for c in done if c["outcome"] == FAIL)
    unmeasured = sum(1 for c in done if c["outcome"] == UNMEASURED)
    after = get_balance()
    spent_expected = plan_cost(attempted)
    spent_actual = (
        None if (before is None or after is None) else round(float(before) - float(after), 4)
    )
    outcome = E.verdict(passed + failed, failed, unmeasured)

    for c in done:
        E.say(f"      · {c['name']}: {c['outcome']} — {c.get('note', '')}", log=log)
    E.say(
        f"ИТОГ: {outcome} | годно {passed}, не годно {failed}, не смогли "
        f"{unmeasured} из {len(grid)} ячеек (запущено {attempted}) | "
        f"потрачено фактически "
        f"{'не смогли посчитать' if spent_actual is None else '$' + str(spent_actual)}"
        f" при ожидаемых ${spent_expected} | баланс "
        f"{before} -> {after} | роликов "
        f"{sum(1 for c in done if c.get('clip'))}",
        log=log,
    )
    return {
        "outcome": outcome,
        "mode": mode,
        "planned": len(grid),
        "attempted": attempted,
        "passed": passed,
        "failed": failed,
        "unmeasured": unmeasured,
        "money": money,
        "balance_before": before,
        "balance_after": after,
        "spent_expected": spent_expected,
        "spent_actual": spent_actual,
        "cells": done,
        "clips": [c["clip"] for c in done if c.get("clip")],
        "stopped_early": stopped,
        "exit_code": EXIT_BY_OUTCOME[outcome],
    }


def main(argv=None) -> int:
    """Тонкая точка входа: разбор аргументов и вызов `run_batch`."""
    import argparse  # noqa: PLC0415

    ap = argparse.ArgumentParser(description="батч сквозного стенда")
    ap.add_argument("--driving", action="append", required=True)
    ap.add_argument("--style", action="append", required=True)
    ap.add_argument("--person", action="append", required=True)
    ap.add_argument("--mode", default="full", choices=list(MODES))
    ap.add_argument("--window", required=True, help="первый:последний, напр. 100:199")
    ap.add_argument("--out", default="work/batch")
    a = ap.parse_args(argv)
    first, last = E.parse_window(a.window)
    got = run_batch(
        drivings=a.driving,
        styles=a.style,
        persons=a.person,
        mode=a.mode,
        first=first,
        last=last,
        out_dir=a.out,
    )
    return got["exit_code"]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
