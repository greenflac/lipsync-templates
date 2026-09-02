#!/usr/bin/env python3
"""Гейт второй оси: разметка базы по роду факта и исход шага, который ВЫЧИСЛЯЕТСЯ.

    python scripts/check_fact_axis.py --check

ЧТО ЗДЕСЬ СТОРОЖИТСЯ

1. НЕГАТИВНЫЙ КОНТРОЛЬ (И5) — главная проверка. Три контрольных шага собраны
   из НАСТОЯЩИХ строк базы и обязаны дать три РАЗНЫХ исхода: шаг, у которого
   применимость наблюдалась и она отрицательная, — `не годно`; шаг со
   свидетельством оператора — `годно`; шаг, чьё убийственное требование закрыто
   ТОЛЬКО схемой вендора, — `не смогли`. Шагов пять: два добавлены не ради
   исхода, а ради КОНСТАНТ — `degrades_when` в CONTRA_ATTRIBUTES и ступень
   `operator` в WITNESS_TIERS изымались зелёными (Т1), теперь краснеют.
   Прибор, отвечающий одно и то же на все
   пять, меряет не то — и это ровно тот дефект, который на этом проекте уже
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

4. ТРЕБОВАНИЕ УЧАСТВУЕТ В ВЕРДИКТЕ, и это проверяется ПАРОЙ (И5, CONTROL_PAIRS).
   Одни и те же факты подаются дважды: с требованием, которое они закрывают, и
   с требованием, к которому они отношения не имеют. Два РАЗНЫХ исхода —
   условие приёмки. До 2026-09-02 их было один: `step_verdict` принимал
   требование параметром, возвращал эхом и не читал, так что «губы держат
   синхрон» и «вылечить рак» на одном наборе фактов давали один ответ.
   Совпадение исходов внутри пары красит гейт, даже если каждый по отдельности
   совпал с ожиданием.

5. РЕТРИВЕР ОШИБАЕТСЯ, И ЭТО ЧИСЛО (RELEVANCE_CONTROL). Отношение строки к
   требованию решается по словам, значит бывает подобрана строка «про другое,
   но со схожими словами» и пропущена относящаяся, сказанная другими словами.
   16 пар «строка — требование» размечены руками на настоящих строках базы;
   печатаются ложные подборы и пропуски ОТДЕЛЬНО (Е3). Красит гейт только
   ПРОПУСК: он молча превращает `не годно` в `не смогли`, то есть прячет
   известный отказ. Ложный подбор расширяет основание, а не подменяет его,
   и держится под наблюдением числом.
   ИЗМЕРЕНО 2026-09-02: ложных подборов 3 из 16, пропусков 0.

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


def _fact(
    model: str,
    attribute: str,
    value: str,
    url: str,
    tier: str,
    witnessed: str = "",
    note: str = "",
) -> Fact:
    """Строка контроля, скопированная с живой.

    `note` копируется не для красоты: `factindex.haystack` ищет и по нему, а
    значит фикстура без заметки — это ДРУГАЯ строка, чем та, что лежит в базе.
    Контроль, отличающийся от живого входа полем, по которому идёт подбор,
    меряет собственную усечённую копию.
    """
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url=url,
        tier=tier,
        stated_on="2026-08-27",
        witnessed=witnessed,
        note=note,
    )


#: Три шага из НАСТОЯЩИХ строк базы (скопированы вместе с источником и тиром,
#: сокращены только длинные значения). Ожидаемый исход у каждого выписан
#: рядом — и он выписан ЛИТЕРАЛОМ, а не импортом из проверяемого модуля (Т2).
CONTROL_STEPS: tuple[tuple[str, str, tuple[Fact, ...], str], ...] = (
    (
        "липсинк V2V, не задев тех, кто молчит",
        "V2V lipsync не должен уносить тех, кто молчит",
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
        "заранее отрисованный текст должен дойти до результата неискажённым",
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
        "ролик 15 секунд одним прогоном, без склеек",
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
    (
        "надпись в нескольких местах кадра",
        "text rendering не должен разваливаться от числа надписей",
        (
            _fact(
                "flux.1-dev",
                "degrades_when",
                "English text rendering collapses as the number of distinct text REGIONS in one "
                "image grows",
                "https://arxiv.org/html/2508.02324v1",
                "benchmark",
            ),
            _fact(
                "flux.1-dev",
                "max_resolution",
                "2048",
                "https://huggingface.co/black-forest-labs/FLUX.1-dev",
                "vendor",
            ),
        ),
        "fail",
    ),
    (
        "оператор назвал цену за секунду",
        "price per image должна остаться в заложенном",
        (
            # ФОРМА, КОТОРОЙ НА ЖИВОЙ БАЗЕ НЕТ (И6): строк тира `operator` без
            # поля `witnessed` там 0 из 975 на 2026-08-31 — единственная
            # операторская строка несёт наблюдение в себе и размечается
            # правилом 1. Значит ступень `operator` внутри WITNESS_TIERS не
            # сторожится ничем живым: её изъятие проходило гейт зелёным. Шаг
            # существует ровно затем, чтобы её изъятие краснело.
            _fact(
                "nano-banana-edit",
                "price_per_image",
                "0.039",
                "владелец, чат 2026-08-31",
                "operator",
            ),
        ),
        "pass",
    ),
)


#: НЕГАТИВНЫЙ КОНТРОЛЬ ПРИБОРА, и здесь он главный (И5). Одни и те же факты
#: подаются ДВАЖДЫ: с требованием, которое они закрывают, и с требованием, к
#: которому они отношения не имеют. Прибор обязан РАЗЛИЧАТЬ — дать два разных
#: исхода. Совпадение означает, что требование снова не читается, и это ровно
#: тот дефект, который здесь чинили 2026-09-02: `step_verdict` принимал
#: требование параметром, возвращал его эхом и не читал ни разу, отвечая на
#: «губы держат синхрон» и на «вылечить рак» одинаково.
#:
#: Чужое требование — не выдумка ради красного: «вылечить рак» и ПУСТАЯ строка
#: это два разных способа спросить о том, чего база не знает, и оба обязаны
#: давать третий исход, а не провал и не успех. Ожидания — литералы (Т2).
CONTROL_PAIRS: tuple[tuple[str, tuple[Fact, ...], str, str, str, str], ...] = (
    (
        "отрицательное свидетельство: своё требование против чужого",
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
        "V2V lipsync не должен уносить тех, кто молчит",
        "fail",
        "вылечить рак",
        "could not measure",
    ),
    (
        "положительное свидетельство: своё требование против пустого",
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
        "заранее отрисованный текст должен дойти до результата неискажённым",
        "pass",
        "",
        "could not measure",
    ),
)

#: РАЗМЕЧЕННЫЙ РУКАМИ НАБОР ОТНОШЕНИЯ. Ретривер подбирает по словам, а значит
#: умеет подобрать строку «про другое, но со схожими словами» — и умеет
#: пропустить относящуюся, сказанную другими словами. Оба промаха здесь
#: СЧИТАЮТСЯ ЧИСЛОМ, а не объявляются отсутствующими.
#:
#: Строки настоящие, из живой базы (модель, атрибут, тир и источник скопированы;
#: сокращены только длинные значения — но так, чтобы слова, по которым идёт
#: подбор, остались на месте). Метка `относится` проставлена глазами: вопрос
#: «отвечает ли эта строка НА ЭТО требование», а не «про ту же ли она область».
#:
#: Фикстуры с обоих краёв и из середины (Т3): требование, на которое строка
#: отвечает дословно; требование, к которому база не относится вовсе; и
#: середина — строки той же области, отвечающие на СОСЕДНИЙ вопрос.
RELEVANCE_CONTROL: tuple[tuple[str, tuple[tuple[Fact, bool], ...]], ...] = (
    (
        "V2V lipsync не должен уносить тех, кто молчит",
        (
            (
                _fact(
                    "infinitetalk",
                    "failure_mode",
                    "In V2V lipsync the sampler rebuilds the entire frame every step, so people "
                    "who are NOT the audio target visibly drift even when audio cross-attention "
                    "is masked to the target",
                    "https://github.com/kijai/ComfyUI-WanVideoWrapper/issues/2048",
                    "probe",
                ),
                True,
            ),
            (
                # Про ЧИСЛО говорящих, а не про сохранность молчащих. Слово
                # `lipsync` общее, вопрос соседний.
                _fact(
                    "infinitetalk",
                    "limitation",
                    "Speaker count is a hard applicability ceiling, not a smooth degradation: two "
                    "simultaneous speakers lipsync correctly, four produce no lipsync at all.",
                    "https://github.com/kijai/ComfyUI-WanVideoWrapper/issues/1944",
                    "blog",
                ),
                False,
            ),
            (
                # Про размен «форма лица против артикуляции рта», а не про то,
                # что делается с посторонними в кадре. Общее слово — `V2V`.
                _fact(
                    "infinitetalk",
                    "degrades_when",
                    "Preserving an existing face's shape by lowering denoise costs mouth fidelity "
                    "- the two cannot be had together in V2V without external control",
                    "https://github.com/kijai/ComfyUI-WanVideoWrapper/issues/1492",
                    "blog",
                ),
                False,
            ),
            (
                _fact(
                    "infinitetalk",
                    "degrades_when",
                    "Image-to-video holds up for about 1 minute; beyond that colour shift becomes "
                    "pronounced",
                    "https://raw.githubusercontent.com/MeiGen-AI/InfiniteTalk/main/README.md",
                    "vendor",
                ),
                False,
            ),
            (
                _fact(
                    "infinitetalk",
                    "min_vram_gb",
                    "24",
                    "https://github.com/MeiGen-AI/InfiniteTalk",
                    "vendor",
                ),
                False,
            ),
        ),
    ),
    (
        "заранее отрисованный текст должен дойти до результата неискажённым",
        (
            (
                _fact(
                    "nano-banana-edit",
                    "text_rendering",
                    "держит заранее отрисованный текст, поданный картинкой",
                    "владелец, чат 2026-08-31",
                    "operator",
                    witnessed="подан кадр с Pillow-текстом, текст дошёл неискажённым",
                ),
                True,
            ),
            (
                _fact(
                    "nano-banana-edit",
                    "reference_images",
                    "array of image_urls for image-to-image / editing (example passes 2); no "
                    "stated max in schema",
                    "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=fal-ai/nano-banana/edit",
                    "portal",
                ),
                False,
            ),
        ),
    ),
    (
        "ролик 15 секунд одним прогоном, без склеек",
        (
            (
                _fact(
                    "kling-3.0",
                    "max_seconds",
                    "15",
                    "https://ir.kuaishou.com/news-releases/news-release-details/"
                    "kling-ai-launches-30-model-ushering-era-where-everyone-can-be",
                    "vendor",
                ),
                True,
            ),
            (
                # Тоже про потолок длительности: зонд спрашивал API ровно об
                # этом и назвал спор «10 против 15» неразрешённым.
                _fact(
                    "kling-3.0",
                    "probe_cannot_settle_duration",
                    "api.klingai.com rejects duration=1000000 with code 1201 — the refusal names "
                    "NO ceiling, so the probe route cannot decide between the blog's 10 and the "
                    "vendor's 15.",
                    "https://api.klingai.com/v1/videos/text2video",
                    "probe",
                    note="Settling 10 vs 15 needs a paid generation.",
                ),
                True,
            ),
            (
                _fact(
                    "kling-3.0",
                    "failure_mode",
                    "face likeness drifts under Motion Control",
                    "https://aividpipeline.com/blog/kling-3-0-motion-control-guide-2026",
                    "blog",
                ),
                False,
            ),
            (
                _fact(
                    "kling-3.0",
                    "max_resolution",
                    "4K, and Kling's own developer site markets it as a native render",
                    "https://kling.ai/release-notes",
                    "vendor",
                ),
                False,
            ),
        ),
    ),
    (
        "text rendering не должен разваливаться от числа надписей",
        (
            (
                _fact(
                    "flux.1-dev",
                    "degrades_when",
                    "English text rendering collapses as the number of distinct text REGIONS in "
                    "one image grows: CVTG-2K word accuracy 0.6089 at 2 regions -> 0.4316 at 5",
                    "https://arxiv.org/html/2508.02324v1",
                    "benchmark",
                ),
                True,
            ),
            (
                # Про КИТАЙСКИЙ длинный текст, а не про число областей. Слова
                # `text` и `rendering` общие, измеряется другое.
                _fact(
                    "flux.1-dev",
                    "limitation",
                    "Chinese long-text rendering is effectively zero: LongText-Bench-ZH 0.005 "
                    "against 0.607 on the English split.",
                    "https://arxiv.org/html/2508.02324v1",
                    "benchmark",
                ),
                False,
            ),
            (
                _fact(
                    "flux.1-dev",
                    "limitation",
                    "Not usable for anything requiring factual correctness about the world (real "
                    "people, real places, real products, diagrams that must be true).",
                    "https://huggingface.co/black-forest-labs/FLUX.1-dev",
                    "vendor",
                ),
                False,
            ),
        ),
    ),
    (
        # Край диапазона: требование, к которому база не относится ничем.
        "вылечить рак",
        (
            (
                _fact(
                    "infinitetalk",
                    "failure_mode",
                    "In V2V lipsync the sampler rebuilds the entire frame every step, so people "
                    "who are NOT the audio target visibly drift",
                    "https://github.com/kijai/ComfyUI-WanVideoWrapper/issues/2048",
                    "probe",
                ),
                False,
            ),
            (
                _fact(
                    "nano-banana-edit",
                    "text_rendering",
                    "держит заранее отрисованный текст, поданный картинкой",
                    "владелец, чат 2026-08-31",
                    "operator",
                    witnessed="подан кадр с Pillow-текстом, текст дошёл неискажённым",
                ),
                False,
            ),
        ),
    ),
)


def pair_results() -> list[dict]:
    """Пары «своё требование / чужое требование» на ОДНИХ И ТЕХ ЖЕ фактах (И5)."""
    out = []
    for имя, факты, своё, ждём_своё, чужое, ждём_чужое in CONTROL_PAIRS:
        размечено = fa.mark_all(факты)
        свой = fa.step_verdict(имя, своё, размечено)
        чужой = fa.step_verdict(имя, чужое, размечено)
        out.append(
            {
                "name": имя,
                "own_requirement": своё,
                "own_expected": ждём_своё,
                "own_got": свой["outcome"],
                "alien_requirement": чужое,
                "alien_expected": ждём_чужое,
                "alien_got": чужой["outcome"],
                "own_note": свой["note"],
                "alien_note": чужой["note"],
            }
        )
    return out


def pair_verdict(results: list[dict]) -> dict:
    """Прибор обязан РАЗЛИЧАТЬ, а не просто краснеть.

    Три условия, и ни одно не выводится из остальных: своё требование дало
    ожидаемый исход, чужое дало ожидаемый, и эти два исхода РАЗНЫЕ. Третье —
    то самое, чего не было: пока требование не читалось, оба исхода совпадали
    при любых ожиданиях, выписанных рядом.
    """
    if not results:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "пар нет — различает ли прибор требования, не проверено ничем",
            "problems": [],
        }
    беды: list[str] = []
    for r in results:
        if r["own_got"] != r["own_expected"]:
            беды.append(
                f"{r['name']}: на своём требовании ожидался {r['own_expected']}, "
                f"вышло {r['own_got']}"
            )
        if r["alien_got"] != r["alien_expected"]:
            беды.append(
                f"{r['name']}: на чужом требовании ожидался {r['alien_expected']}, "
                f"вышло {r['alien_got']}"
            )
        if r["own_got"] == r["alien_got"]:
            беды.append(
                f"{r['name']}: требование не участвует в вердикте — своё и чужое дали "
                f"один исход {r['own_got']}"
            )
    return {
        "outcome": FAIL if беды else PASS,
        "checked": len(results) * 2,
        "violations": len(беды),
        "unmeasured": 0,
        "note": (
            "; ".join(беды)
            if беды
            else f"{len(results)} пар(ы): своё и чужое требование дали разные исходы"
        ),
        "problems": беды,
    }


def relevance_results() -> list[dict]:
    """Сколько раз ретривер подобрал чужое и сколько раз пропустил своё."""
    out = []
    for требование, строки in RELEVANCE_CONTROL:
        размечено = fa.mark_all([f for f, _ in строки])
        относятся, _ = fa.relates(требование, размечено)
        подобрано = {id(m.fact) for m in относятся}
        for m, ожидалось in zip(размечено, [ждём for _, ждём in строки]):
            out.append(
                {
                    "requirement": требование,
                    "model": m.fact.model,
                    "attribute": m.fact.attribute,
                    "tier": m.fact.tier,
                    "expected": ожидалось,
                    "got": id(m.fact) in подобрано,
                }
            )
    return out


def relevance_verdict(results: list[dict]) -> dict:
    """Ложные подборы и пропуски — числом (Р2), а не словом «бывают».

    Красным считается только ПРОПУСК относящейся строки: пропущенное
    свидетельство молча превращает `не годно` в `не смогли`, то есть прячет
    известный отказ. Ложный подбор печатается числом и держится под наблюдением:
    он расширяет основание, а не подменяет его, и на этом наборе ни один из
    ложных не менял исход шага. Свернуть оба в одно число значило бы потерять
    разницу между «прибор поверил лишнему» и «прибор не увидел своего».
    """
    if not results:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "набор отношения пуст — ретривер не проверен ничем",
            "false_pickups": 0,
            "misses": 0,
            "problems": [],
        }
    ложные = [r for r in results if r["got"] and not r["expected"]]
    пропуски = [r for r in results if r["expected"] and not r["got"]]
    беды = [
        f"пропущена относящаяся строка {r['model']}.{r['attribute']} на требовании "
        f"«{r['requirement']}»"
        for r in пропуски
    ]
    return {
        "outcome": FAIL if беды else PASS,
        "checked": len(results),
        "violations": len(беды),
        "unmeasured": 0,
        "false_pickups": len(ложные),
        "misses": len(пропуски),
        "note": (
            "; ".join(беды)
            if беды
            else (
                f"{len(results)} размеченных руками пар: ложных подборов {len(ложные)}, "
                f"пропусков {len(пропуски)}"
            )
        ),
        "problems": беды,
    }


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
            else f"{len(results)} контрольных шагов дали три разных исхода, каждый — ожидаемый"
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

    шаги = control_results()
    контроль = control_verdict(шаги)
    for r in шаги:
        знак = "ok " if r["expected"] == r["got"] else "БЕДА"
        print(f"  {знак} {r['step']}: {fa.OUTCOME_WORDS.get(r['got'], r['got'])}")

    пары = pair_results()
    парный = pair_verdict(пары)
    print("\n  негативный контроль: одни факты, своё требование против чужого")
    for r in пары:
        знак = (
            "ok "
            if r["own_got"] == r["own_expected"]
            and r["alien_got"] == r["alien_expected"]
            and r["own_got"] != r["alien_got"]
            else "БЕДА"
        )
        print(
            f"  {знак} {r['name']}:\n"
            f"        своё «{r['own_requirement']}» -> "
            f"{fa.OUTCOME_WORDS.get(r['own_got'], r['own_got'])}\n"
            f"        чужое «{r['alien_requirement']}» -> "
            f"{fa.OUTCOME_WORDS.get(r['alien_got'], r['alien_got'])}"
        )
    for беда in парный["problems"]:
        print(f"  БЕДА {беда}")

    отношение = relevance_verdict(relevance_results())
    print(
        f"\n  отношение строки к требованию: размечено руками {отношение['checked']}, "
        f"ложных подборов {отношение['false_pickups']}, пропусков {отношение['misses']}"
    )
    for беда in отношение["problems"]:
        print(f"  БЕДА {беда}")

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

    части = (контроль, парный, отношение, база)
    checked = sum(ч["checked"] for ч in части)
    violations = sum(ч["violations"] for ч in части)
    unmeasured = sum(ч["unmeasured"] for ч in части)
    print(f"\nпроверено {checked}\nнарушений {violations}\nне смогли {unmeasured}")

    if any(ч["outcome"] == UNMEASURED for ч in части):
        outcome = UNMEASURED
    elif violations:
        outcome = FAIL
    else:
        outcome = PASS
    print(
        f"\n{outcome}: {контроль['note']} | {парный['note']} | {отношение['note']} | {база['note']}"
    )

    if not args.check:
        return 0
    return {PASS: 0, FAIL: 1, UNMEASURED: 2}[outcome]


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
