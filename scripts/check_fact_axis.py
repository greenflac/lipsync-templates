#!/usr/bin/env python3
"""Гейт второй оси: разметка базы по роду факта и исход шага, который ВЫЧИСЛЯЕТСЯ.

    python scripts/check_fact_axis.py --check

ЧТО ЗДЕСЬ СТОРОЖИТСЯ

1. НЕГАТИВНЫЙ КОНТРОЛЬ (И5) — главная проверка. Три контрольных шага собраны
   из НАСТОЯЩИХ строк базы и обязаны дать три РАЗНЫХ исхода: шаг, у которого
   применимость наблюдалась и она отрицательная, — `не годно`; шаг со
   свидетельством оператора — `годно`; шаг, чьё убийственное требование закрыто
   ТОЛЬКО схемой вендора, — `не смогли`. Прибор, отвечающий одно и то же на все
   три, меряет не то — и это ровно тот дефект, который на этом проекте уже
   стоил прогонов (метрика дала 0.3106 и 0.3072 на кадрах, отличавшихся на 37%
   пикселей). Совпадение исходов красит гейт.

2. ПРОИСХОЖДЕНИЕ РАЗМЕТКИ (И4). Выведенная строка несёт `РАСЧЁТ`. Пометку
   `ИЗМЕРЕНО` имеет право нести только та, у которой наблюдение лежит в самом
   факте (поле `witnessed`) или которую человек проставил руками в
   `studio/knowledge/fact_axis.jsonl`. Выведенное, поданное как наблюдённое, —
   это то, чего потом никто не решается тронуть.

3. РУЧНЫЕ РАЗМЕТКИ не висят в воздухе: каждая строка файла ручных разметок
   обязана попадать в существующее утверждение базы. Осиротевшая строка молча
   не действует, и «разметка есть» означало бы «разметки нет».

ТРИ ИСХОДА (Р1): годно / не годно / не смогли. Третий — когда база пуста, а не
когда в ней нет нарушений. Рядом всегда печатаются `проверено N`,
`нарушений M`, `не смогли K` (Р2). Сети здесь нет (Т4).
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402

from studio import factaxis as fa  # noqa: E402
from studio.factindex import FactIndex  # noqa: E402
from studio.selfrag.facts import Fact, load_facts  # noqa: E402


def _fact(model: str, attribute: str, value: str, url: str, tier: str, witnessed: str = "") -> Fact:
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url=url,
        tier=tier,
        stated_on="2026-08-27",
        witnessed=witnessed,
    )


#: Три шага из НАСТОЯЩИХ строк базы (скопированы вместе с источником и тиром,
#: сокращены только длинные значения). Ожидаемый исход у каждого выписан
#: рядом — и он выписан ЛИТЕРАЛОМ, а не импортом из проверяемого модуля (Т2).
CONTROL_STEPS: tuple[tuple[str, str, tuple[Fact, ...], str], ...] = (
    (
        "липсинк V2V, не задев тех, кто молчит",
        "остальные лица в кадре не должны уплывать",
        (
            _fact(
                "infinitetalk",
                "failure_mode",
                "In V2V lipsync the sampler rebuilds the entire frame every step, so people who "
                "are NOT the audio target visibly drift",
                "https://github.com/kijai/ComfyUI-WanVideoWrapper/issues/2048",
                "probe",
            ),
            _fact(
                "infinitetalk",
                "min_vram_gb",
                "24",
                "https://github.com/MeiGen-AI/InfiniteTalk",
                "vendor",
            ),
        ),
        "fail",
    ),
    (
        "текст на кадре доходит до результата",
        "надпись не должна исказиться",
        (
            _fact(
                "nano-banana-edit",
                "text_rendering",
                "держит заранее отрисованный текст, поданный картинкой",
                "владелец, чат 2026-08-31",
                "operator",
                witnessed=(
                    "на nano-banana-edit подаётся заранее отрисованный Pillow текст поверх "
                    "кадра; текст доходит до результата неискажённым"
                ),
            ),
        ),
        "pass",
    ),
    (
        "пятнадцать секунд одним прогоном",
        "ролик не должен собираться из склеек",
        (
            _fact(
                "kling-3.0",
                "max_seconds",
                "15",
                "https://ir.kuaishou.com/news-releases/news-release-details/"
                "kling-ai-launches-30-model-ushering-era-where-everyone-can-be",
                "vendor",
            ),
            _fact(
                "kling-3.0",
                "max_resolution",
                "4K",
                "https://kling.ai/release-notes",
                "vendor",
            ),
        ),
        "could not measure",
    ),
)


def control_results() -> list[dict]:
    """Исходы контрольных шагов рядом с ожидаемыми. Вынесено из main (Т5)."""
    out = []
    for имя, требование, факты, ожидалось in CONTROL_STEPS:
        вердикт = fa.step_verdict(имя, требование, fa.mark_all(факты))
        out.append(
            {"step": имя, "expected": ожидалось, "got": вердикт["outcome"], "verdict": вердикт}
        )
    return out


def control_verdict(results: list[dict]) -> dict:
    """Различает ли прибор три случая, и те ли, что заявлены.

    Два условия, и оба обязательны: каждый шаг дал ОЖИДАЕМЫЙ исход, и трёх
    разных исходов ровно три. Второе не выводится из первого — оно проверяет
    сам набор: контроль из трёх одинаковых случаев прошёл бы первое условие и
    не измерял бы ничего.
    """
    if not results:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "контрольных шагов нет — прибор не проверен ничем",
            "problems": [],
        }
    беды = [
        f"{r['step']}: ожидался {r['expected']}, вышло {r['got']}"
        for r in results
        if r["expected"] != r["got"]
    ]
    исходы = {r["got"] for r in results}
    if len(исходы) < 3:
        беды.append(f"прибор различает {len(исходы)} исход(а) из трёх: {sorted(исходы)}")
    return {
        "outcome": FAIL if беды else PASS,
        "checked": len(results),
        "violations": len(беды),
        "unmeasured": 0,
        "note": (
            "; ".join(беды)
            if беды
            else "три контрольных шага дали три разных исхода, каждый — ожидаемый"
        ),
        "problems": беды,
    }


def base_verdict(facts: list[Fact], overrides: dict) -> dict:
    """Разметка живой базы: числа по родам и нарушения происхождения (И4)."""
    if not facts:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "база фактов пуста — размечать нечего",
            "kinds": {},
            "problems": [],
        }

    известные = {fa.axis_key(f.model, f.attribute, f.source_url) for f in facts}
    размечено = fa.mark_all(facts, overrides)
    беды: list[str] = []
    for m in размечено:
        ключ = fa.axis_key(m.fact.model, m.fact.attribute, m.fact.source_url)
        ручная = ключ in overrides
        if m.origin == "ИЗМЕРЕНО" and not (ручная or m.fact.witnessed.strip()):
            беды.append(
                f"{m.fact.model}.{m.fact.attribute}: выведенная разметка выдана за наблюдение (И4)"
            )
    for ключ in overrides:
        if ключ not in известные:
            беды.append(
                f"ручная разметка {ключ[0]}.{ключ[1]} не попадает ни в одно утверждение базы"
            )

    роды = Counter(m.kind or "не смогли" for m in размечено)
    решено = [m for m in размечено if m.resolved]
    return {
        "outcome": FAIL if беды else PASS,
        "checked": len(решено),
        "violations": len(беды),
        "unmeasured": len(размечено) - len(решено),
        "note": (
            "; ".join(беды[:5])
            if беды
            else f"{len(решено)} из {len(размечено)} размечено, ручных {len(overrides)}"
        ),
        "kinds": dict(роды),
        "problems": беды,
    }


def step_advice(requirement: str, k: int = 12) -> str:
    """Рекомендация по одному требованию: две колонки и ВЫЧИСЛЕННЫЙ исход.

    Факты достаются словами требования (`studio/factindex.py`), а не именем
    модели: имя пришлось бы угадать заранее, то есть уже иметь ответ. Здесь
    же виден смысл всего пункта — требование, закрытое одной вендорской
    схемой, печатается как `не смогли`, а не как рекомендация.
    """
    индекс = FactIndex()
    факты = [h.fact for h in индекс.search(requirement, k=k)]
    вердикт = fa.step_verdict(requirement, requirement, fa.mark_all(факты, fa.load_overrides()))
    return fa.render(вердикт)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="код возврата 0/1/2")
    parser.add_argument("--step", metavar="ТРЕБОВАНИЕ", help="показать шаг в две колонки")
    args = parser.parse_args(argv)

    if args.step:
        print(step_advice(args.step))
        return 0

    контроль = control_verdict(control_results())
    for r in control_results():
        знак = "ok " if r["expected"] == r["got"] else "БЕДА"
        print(f"  {знак} {r['step']}: {fa.OUTCOME_WORDS.get(r['got'], r['got'])}")

    факты = load_facts()
    overrides = fa.load_overrides()
    база = base_verdict(факты, overrides)

    роды = база["kinds"]
    способность = sum(роды.get(k, 0) for k in fa.CAPABILITY)
    применимость = sum(роды.get(k, 0) for k in fa.APPLICABILITY)
    print(
        "\n  роды: "
        + ", ".join(f"{k} {роды.get(k, 0)}" for k in fa.KINDS)
        + f"\n  {fa.CAPABILITY_HEADER} {способность}, {fa.APPLICABILITY_HEADER} {применимость}"
    )
    for беда in база["problems"][:10]:
        print(f"  БЕДА {беда}")

    checked = контроль["checked"] + база["checked"]
    violations = контроль["violations"] + база["violations"]
    unmeasured = контроль["unmeasured"] + база["unmeasured"]
    print(f"\nпроверено {checked}\nнарушений {violations}\nне смогли {unmeasured}")

    if UNMEASURED in (контроль["outcome"], база["outcome"]):
        outcome = UNMEASURED
    elif violations:
        outcome = FAIL
    else:
        outcome = PASS
    print(f"\n{outcome}: {контроль['note']} | {база['note']}")

    if not args.check:
        return 0
    return {PASS: 0, FAIL: 1, UNMEASURED: 2}[outcome]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
