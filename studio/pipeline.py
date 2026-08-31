"""Валидатор-2: принимает ПАЙПЛАЙН, а не факт.

ЗАЧЕМ ЭТОТ МОДУЛЬ СУЩЕСТВУЕТ

`studio/factaxis.py` умеет выносить исход по ОДНОМУ шагу: закрыто ли его
требование применимостью или только вендорской схемой. Этого мало. План — это
последовательность, и ломается она чаще всего НЕ внутри шага, а между шагами:
выход шага N не является допустимым входом шага N+1, и ни один посшаговый
вердикт этого не видит, потому что каждый шаг по отдельности безупречен.

Блюпринт (`docs/BLUEPRINT_MODELS.md`, П4 «Валидатор-2») требует: у валидатора
НЕТ исхода «работает». Три исхода (Р1) — `не годно` с названной причиной,
`годно` (точнее: не опровергнут) и `не смогли`. Здесь это соблюдено буквально:
исход шага берётся у `factaxis.step_verdict` и НЕ пересчитывается вторым
способом (Е1), а классы провала пайплайна добавляются поверх.

СЕМЬ КЛАССОВ ПРОВАЛА, И ПОЧЕМУ ИМЕННО ЭТИ СЕМЬ

Отбор — не вкусовой. Класс попадает в список, только если у него есть ОРАКУЛ,
который работает здесь: без сети (Т4), на том, что уже лежит в базе фактов, и
умеющий сказать «не смогли» вместо догадки. Блюпринт называет свои семь; три
из них переименованы или заменены, и каждая замена названа вслух.

    1. `нет_модели`     — про модель шага в базе нет НИ ОДНОГО утверждения.
       Блюпринт называет этот класс «имени не существует». Переименован по
       тому, что оракул реально меряет (Е2): без сети доказать несуществование
       имени в мире нельзя, а «база о ней не знает» — проверяемое утверждение.
       Поэтому и исход у класса третий, а не `не годно`: незнание базы не есть
       свидетельство против модели.

    2. `разрыв`         — шаг требует артефакта, которого не производит ни один
       предыдущий шаг и которого нет во входах плана (`requires ⊆ produces`).
       Из блюпринта дословно. Единственный класс, который вообще невозможно
       увидеть посшаговым валидатором, — ради него всё и затевалось.

    3. `применимость`   — требование шага закрыто ТОЛЬКО схемой вендора («API
       принимает такой вход» вместо «результат держится»), либо, наоборот,
       применимость наблюдалась и она отрицательная. Оракул — целиком чужой:
       `factaxis.step_verdict`, вызванный как есть. Второго счётчика той же
       развилки здесь нет намеренно: развилка, посчитанная дважды, — самый
       частый дефект этой ветки, он ловился тремя заходами подряд.

    4. `лицензия`       — лицензия модели запрещает заявленное применение.
       Из блюпринта дословно, и правило дома Ц5 требует того же. Канал
       HuggingFace уже поймал форму, ради которой класс существует: у LTX-Video
       четыре файла лицензий, два из них research-only, и прочитавший один
       ошибается в любую сторону.

    5. `цена`           — даже НИЖНЯЯ известная граница цены выше заложенного
       бюджета. Из блюпринта дословно. Нижняя, а не средняя: превышение снизу
       — единственное утверждение о цене, которое нельзя опровергнуть более
       дешёвым тарифом, о котором мы не знаем.

    6. `устарел`        — модель снята площадкой, или самое свежее утверждение
       о ней старше порога. Блюпринта в этом месте нет; класс взят из того, что
       ИЗМЕРЕНО на живом срезе каталогов: 138 записей из 368 у одной площадки
       помечены `deprecated`, и пять снятых имён уже лежат в базе законно, из
       вендорских источников. Шаг на снятой модели — не гипотеза.

    7. `противоречие`   — два источника расходятся в решающем атрибуте одной
       модели. Блюпринта здесь тоже нет; класс взят из записанной истории
       проекта: «15 секунд», «10 секунд» и «3 минуты» об одной модели, и чужая
       сводка, уверенно назвавшая «до 5 минут», то есть не совпавшая ни с одним
       источником. Исход у класса ТРЕТИЙ: выбрать сторону за человека — это и
       есть то самое уплощение.

ЧЕГО В СПИСКЕ НЕТ И ПОЧЕМУ (И6, отрицательный результат тоже записывается)

    * «существует, но не принимает такой вход» — свёрнуто в `применимость`:
      вход, который API не принимает, — это ровно отсутствие схемы, а схемы у
      нас и так меряются `factaxis`. Отдельный класс был бы вторым счётчиком.
    * «недоступно здесь: хост закрыт, ключа нет» — оракул требует либо сети
      (Т4 запрещает в тестах), либо реестра доступности, а `advise()` уже
      называет отсутствие в реестре третьим исходом. Второй такой счётчик
      нарушил бы Е1. Класс НЕ реализован, и это записано, а не забыто.

ТРИ ИСХОДА ВЕЗДЕ (Р1)

У оракула — `годно` / `не годно` / `не смогли`, и четвёртое состояние «не
заявлено» (шаг не назвал бюджета — сравнивать не с чем) считается ОТДЕЛЬНО и
не подмешивается ни к одному из трёх: ноль нарушений при нуле отработавших
оракулов не есть успех (Р2).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio import factaxis as fa
from studio.selfrag.facts import Fact

__all__ = [
    "AMBIENT_ARTEFACTS",
    "BUDGET_TOLERANCE",
    "CLASSES",
    "CLASS_APPLICABILITY",
    "CLASS_CONTRADICTION",
    "CLASS_GAP",
    "CLASS_LICENCE",
    "CLASS_NO_MODEL",
    "CLASS_OUTCOME",
    "CLASS_PRICE",
    "CLASS_STALE",
    "CONTRADICTION_ATTRIBUTES",
    "Control",
    "DEFAULT_CONTROLS_PATH",
    "DEPRECATION_MARKERS",
    "FORBIDDING_LICENCE_MARKERS",
    "KIND_HEALTHY",
    "KIND_MUTANT",
    "LICENCE_MARKERS",
    "MIN_FACTS_PER_MODEL",
    "PRICE_MARKERS",
    "PRODUCES_LOOKBACK",
    "Pipeline",
    "Probe",
    "STALE_AFTER_DAYS",
    "Step",
    "USE_COMMERCIAL",
    "USE_RESEARCH",
    "classes_fired",
    "facts_for",
    "load_controls",
    "outcome_of",
    "parse_pipeline",
    "pipeline_report",
    "render",
    "rows_in",
    "step_report",
]

CLASS_NO_MODEL = "нет_модели"
CLASS_GAP = "разрыв"
CLASS_APPLICABILITY = "применимость"
CLASS_LICENCE = "лицензия"
CLASS_PRICE = "цена"
CLASS_STALE = "устарел"
CLASS_CONTRADICTION = "противоречие"

#: Семь классов. Порядок — порядок опроса и порядок печати; он же порядок
#: приоритета: `нет_модели` первым, потому что при пустой базе остальные
#: фактовые оракулы не могут отработать и обязаны сказать это, а не назвать
#: свой класс за компанию.
CLASSES: tuple[str, ...] = (
    CLASS_NO_MODEL,
    CLASS_GAP,
    CLASS_APPLICABILITY,
    CLASS_LICENCE,
    CLASS_PRICE,
    CLASS_STALE,
    CLASS_CONTRADICTION,
)

#: Исход, который класс несёт, когда он сработал. КОНСТАНТА-РЕШЕНИЕ, ВЫБРАНО:
#: три класса из семи несут третий исход, и это не осторожность, а разбор.
#: `нет_модели` — незнание базы не есть свидетельство против модели;
#: `противоречие` — выбрать сторону за человека значит повторить ту самую
#: чужую сводку, не совпавшую ни с одним источником; `применимость` берёт свой
#: исход у `factaxis.step_verdict` и потому здесь отсутствует физически.
CLASS_OUTCOME: dict[str, str] = {
    CLASS_NO_MODEL: UNMEASURED,
    CLASS_GAP: FAIL,
    CLASS_LICENCE: FAIL,
    CLASS_PRICE: FAIL,
    CLASS_STALE: FAIL,
    CLASS_CONTRADICTION: UNMEASURED,
}

USE_COMMERCIAL = "коммерческое"
USE_RESEARCH = "исследование"

#: Сколько утверждений о модели должно быть в базе, чтобы шаг считался
#: опирающимся на знание. ВЫБРАНО = 1: граница между «база знает хоть что-то»
#: и «база не знает ничего» — единственная, которую можно защитить, не выдумав
#: порога достаточности. Любое число больше единицы было бы порогом качества,
#: поданным как порог существования.
MIN_FACTS_PER_MODEL = 1

#: Артефакты, доступные ЛЮБОМУ шагу без того, чтобы их кто-то произвёл: это
#: вход самого плана, а не выход шага. ВЫБРАНО по разбору настоящих брифов
#: владельца: селфи клиента и текст брифа приходят снаружи всегда.
AMBIENT_ARTEFACTS: frozenset[str] = frozenset({"бриф", "селфи", "референс"})

#: На сколько шагов назад смотрит проверка `requires ⊆ produces`.
#: ВЫБРАНО = 0, что здесь означает «на все предыдущие»: план — это не цепочка
#: труб, шаг 3 законно берёт кадр, сделанный шагом 1, и сужение до одного шага
#: назад отвергло бы здоровый план с перемычкой.
PRODUCES_LOOKBACK = 0

#: Куски имени атрибута, по которым строка опознаётся как строка О ЛИЦЕНЗИИ.
#: Куски, а не полные имена, по той же причине, что и в `factaxis`: имён много
#: (`license`, `license_file`, `licence_note`, `лицензия`), форма одна.
LICENCE_MARKERS: tuple[str, ...] = ("license", "licence", "лиценз")

#: Формулировки, при которых лицензия ЗАПРЕЩАЕТ коммерческое применение.
#: ВЫБРАНО по текстам лицензий, которые канал HuggingFace уже принёс в этот
#: репозиторий. Список закрытый и короткий намеренно: широкий список ловил бы
#: слово внутри разрешительной лицензии и красил бы здоровое.
FORBIDDING_LICENCE_MARKERS: tuple[str, ...] = (
    "non-commercial",
    "noncommercial",
    "non commercial",
    "research only",
    "research-only",
    "research purposes",
    "cc-by-nc",
    "некоммерч",
)

#: Куски имени атрибута, по которым строка опознаётся как строка О ЦЕНЕ.
#: Совпадает по форме со SCHEMA_MARKERS в `factaxis`, но НЕ импортируется
#: оттуда: там это признак рода факта, здесь — признак того, что из строки
#: можно достать число долларов. Одинаковые списки, разные вопросы.
PRICE_MARKERS: tuple[str, ...] = ("price", "cost", "цена", "стоимост")

#: Доля превышения бюджета, которая ещё считается попаданием в бюджет.
#: ВЫБРАНО = 0.0: бюджет назван человеком в долларах, и «чуть-чуть дороже» —
#: это решение владельца денег, а не валидатора. Ноль здесь означает «сравнение
#: строгое», и он сторожится мутацией в обе стороны.
BUDGET_TOLERANCE = 0.0

#: Через сколько дней самое свежее утверждение о модели перестаёт годиться в
#: опору плана. ВЫБРАНО = 180 из наблюдения этого проекта: лимиты моделей
#: меняются месячным темпом (это записано первым абзацем инструкции сервера),
#: полгода — шесть таких тактов. Не ИЗМЕРЕНО: замера скорости устаревания у
#: нас нет, и подать это число как измеренное значило бы заморозить его.
STALE_AFTER_DAYS = 180

#: Формулировки, которыми площадка или вендор объявляют модель снятой.
#: ВЫБРАНО по живому срезу каталогов 2026-08-31, где `deprecated` пришло на
#: 138 записях из 368 у одной площадки.
DEPRECATION_MARKERS: tuple[str, ...] = (
    "deprecated",
    "retired",
    "sunset",
    "end of life",
    "end-of-life",
    "discontinued",
    "снят",
)

#: Атрибуты, расхождение в которых ПЕРЕВОРАЧИВАЕТ решение по шагу, а значит
#: обязано останавливать план третьим исходом. ВЫБРАНО коротким списком, и это
#: важнее длины: на живой базе одна страница законно даёт два значения одного
#: атрибута (`seedance2-video.com`: `12` и `4 to 15`), поэтому широкий список
#: превратил бы «противоречие» в шум и обучил бы читателя его игнорировать.
CONTRADICTION_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "max_seconds",
        "max_duration_seconds",
        "license",
        "licence",
        "max_resolution",
        "price_per_second_usd",
    }
)

KIND_MUTANT = "мутант"
KIND_HEALTHY = "чужак"

DEFAULT_CONTROLS_PATH = Path(__file__).with_name("knowledge") / "pipeline_controls.jsonl"

_NUMBER = re.compile(r"[-+]?\d+(?:[.,]\d+)?")


@dataclass(frozen=True)
class Step:
    """Один шаг: модель плюс требование, которое шаг обязан выдержать."""

    name: str
    model: str
    requirement: str
    requires: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    budget_usd: float | None = None
    use: str = USE_COMMERCIAL


@dataclass(frozen=True)
class Pipeline:
    """Последовательность шагов. Исход пайплайна — слабейшее звено, не среднее."""

    name: str
    steps: tuple[Step, ...] = ()


@dataclass(frozen=True)
class Probe:
    """Что один оракул сказал об одном шаге.

    Четыре состояния, и четвёртое — не исход, а его отсутствие:

    * `applicable=False` — шагу нечего проверять этим оракулом (бюджет не
      заявлен). В счётчики не идёт вообще: подмешать его к `годно` значило бы
      выдать непроверенное за проверенное;
    * `fired=True` — класс сработал, `outcome` берётся из `CLASS_OUTCOME`;
    * `fired=False, outcome=PASS` — оракул отработал и класса не нашёл;
    * `fired=False, outcome=UNMEASURED` — оракул не смог отработать.
    """

    klass: str
    applicable: bool
    fired: bool
    outcome: str
    note: str


@dataclass(frozen=True)
class Control:
    """Одна контрольная подача: сломанный пайплайн или здоровый чужак."""

    id: str
    kind: str
    pipeline: Pipeline
    facts: tuple[Fact, ...]
    today: str
    expect_classes: tuple[str, ...] = ()
    expect_outcome: str = ""
    why: str = ""


def _norm(value: str) -> str:
    return " ".join(value.split()).strip().lower()


def facts_for(model: str, facts: Iterable[Fact]) -> list[Fact]:
    """Все утверждения об одной модели. Имя сравнивается так же, как везде."""
    имя = _norm(model)
    return [f for f in facts if _norm(f.model) == имя]


def _has_marker(text: str, markers: Sequence[str]) -> str:
    low = _norm(text)
    for m in markers:
        if m in low:
            return m
    return ""


def _price_of(value: str) -> float | None:
    """Число долларов из прозы о цене. `None` — из строки числа не достать."""
    m = _NUMBER.search(value)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", "."))
    except ValueError:
        return None


def _age_days(fact: Fact, today: date) -> int | None:
    if not fact.stated_on:
        return None
    try:
        return (today - date.fromisoformat(fact.stated_on)).days
    except ValueError:
        return None


def probe_no_model(step: Step, свои: Sequence[Fact]) -> Probe:
    """База знает о модели шага хоть что-нибудь?"""
    if len(свои) < MIN_FACTS_PER_MODEL:
        return Probe(
            CLASS_NO_MODEL,
            True,
            True,
            CLASS_OUTCOME[CLASS_NO_MODEL],
            f"о модели {step.model} в базе {len(свои)} утверждений при пороге "
            f"{MIN_FACTS_PER_MODEL}: опереть шаг не на что",
        )
    return Probe(CLASS_NO_MODEL, True, False, PASS, f"утверждений о модели: {len(свои)}")


def probe_gap(step: Step, earlier: Sequence[Step]) -> Probe:
    """Есть ли у шага всё, что он требует: `requires ⊆ produces` плюс входы плана.

    Единственный оракул, которому факты не нужны вовсе, и единственный, который
    невозможно получить посшаговым валидатором: он смотрит НА ГРАНИЦУ.
    """
    видимые = earlier if PRODUCES_LOOKBACK <= 0 else earlier[-PRODUCES_LOOKBACK:]
    доступно = {_norm(a) for a in AMBIENT_ARTEFACTS}
    for предыдущий in видимые:
        доступно.update(_norm(a) for a in предыдущий.produces)
    нет = [a for a in step.requires if _norm(a) not in доступно]
    if нет:
        return Probe(
            CLASS_GAP,
            True,
            True,
            CLASS_OUTCOME[CLASS_GAP],
            f"шаг требует {', '.join(нет)}: ни один предыдущий шаг этого не производит "
            f"и во входах плана этого нет",
        )
    return Probe(CLASS_GAP, True, False, PASS, f"вход шага закрыт: требуется {len(step.requires)}")


def probe_applicability(step: Step, свои: Sequence[Fact], overrides: dict | None = None) -> Probe:
    """Исход шага БЕРЁТСЯ у `factaxis.step_verdict` и не пересчитывается (Е1).

    Ветки, печатающей «годно» по одной колонке способности, здесь нет — потому
    что её нет там, а второй такой развилки в репозитории не заводится.
    """
    вердикт = fa.step_verdict(step.name, step.requirement, fa.mark_all(свои, overrides))
    исход = вердикт["outcome"]
    if исход == PASS:
        return Probe(CLASS_APPLICABILITY, True, False, PASS, вердикт["note"])
    return Probe(CLASS_APPLICABILITY, True, True, исход, вердикт["note"])


def probe_licence(step: Step, свои: Sequence[Fact]) -> Probe:
    """Разрешает ли лицензия ЗАЯВЛЕННОЕ применение, а не применение вообще."""
    строки = [f for f in свои if _has_marker(f.attribute, LICENCE_MARKERS)]
    if not строки:
        return Probe(
            CLASS_LICENCE,
            True,
            False,
            UNMEASURED,
            "о лицензии модели в базе нет ни строки: разрешено ли применение — не смогли",
        )
    if step.use == USE_RESEARCH:
        return Probe(
            CLASS_LICENCE,
            True,
            False,
            PASS,
            f"применение заявлено как {USE_RESEARCH}: {len(строки)} строк(и) лицензии его не режут",
        )
    for f in строки:
        маркер = _has_marker(f.value, FORBIDDING_LICENCE_MARKERS)
        if маркер:
            return Probe(
                CLASS_LICENCE,
                True,
                True,
                CLASS_OUTCOME[CLASS_LICENCE],
                f"лицензия {step.model} содержит «{маркер}», а применение заявлено как "
                f"{step.use} ({f.source_url})",
            )
    return Probe(
        CLASS_LICENCE, True, False, PASS, f"лицензий прочитано: {len(строки)}, запрета нет"
    )


def probe_price(step: Step, свои: Sequence[Fact]) -> Probe:
    """Дороже ли бюджета САМАЯ ДЕШЁВАЯ известная цена."""
    if step.budget_usd is None:
        return Probe(
            CLASS_PRICE, False, False, PASS, "бюджет шага не заявлен — сравнивать не с чем"
        )
    цены = [(f, _price_of(f.value)) for f in свои if _has_marker(f.attribute, PRICE_MARKERS)]
    известные = [(f, c) for f, c in цены if c is not None]
    if not известные:
        return Probe(
            CLASS_PRICE,
            True,
            False,
            UNMEASURED,
            f"бюджет заявлен ({step.budget_usd}), а цены в базе нет ни одной разбираемой",
        )
    факт, нижняя = min(известные, key=lambda пара: пара[1])
    потолок = step.budget_usd * (1.0 + BUDGET_TOLERANCE)
    if нижняя > потолок:
        return Probe(
            CLASS_PRICE,
            True,
            True,
            CLASS_OUTCOME[CLASS_PRICE],
            f"нижняя известная цена {нижняя} выше потолка {потолок} "
            f"({факт.attribute}, {факт.source_url})",
        )
    return Probe(
        CLASS_PRICE, True, False, PASS, f"нижняя известная цена {нижняя} при потолке {потолок}"
    )


def probe_stale(step: Step, свои: Sequence[Fact], today: date) -> Probe:
    """Снята ли модель, и не старше ли порога самое свежее утверждение о ней."""
    for f in свои:
        маркер = _has_marker(f.value, DEPRECATION_MARKERS) or _has_marker(
            f.attribute, DEPRECATION_MARKERS
        )
        if маркер:
            return Probe(
                CLASS_STALE,
                True,
                True,
                CLASS_OUTCOME[CLASS_STALE],
                f"модель объявлена снятой («{маркер}», {f.source_url})",
            )
    возрасты = [d for d in (_age_days(f, today) for f in свои) if d is not None]
    if not возрасты:
        return Probe(
            CLASS_STALE,
            True,
            False,
            UNMEASURED,
            "ни одно утверждение о модели не несёт даты: свежесть не смогли",
        )
    свежайшее = min(возрасты)
    if свежайшее > STALE_AFTER_DAYS:
        return Probe(
            CLASS_STALE,
            True,
            True,
            CLASS_OUTCOME[CLASS_STALE],
            f"самому свежему утверждению о модели {свежайшее} дней при пороге {STALE_AFTER_DAYS}",
        )
    return Probe(
        CLASS_STALE,
        True,
        False,
        PASS,
        f"свежайшему утверждению {свежайшее} дн. из {STALE_AFTER_DAYS}",
    )


def probe_contradiction(step: Step, свои: Sequence[Fact]) -> Probe:
    """Расходятся ли источники в решающем атрибуте.

    Не голосует, не усредняет и не берёт свежее: именно эти три способа один
    раз уже превратили три разных ответа в четвёртый, которого не давал никто.
    """
    по_атрибуту: dict[str, set[str]] = {}
    for f in свои:
        имя = _norm(f.attribute)
        if имя in CONTRADICTION_ATTRIBUTES:
            по_атрибуту.setdefault(имя, set()).add(_norm(f.value))
    спорные = sorted(имя for имя, значения in по_атрибуту.items() if len(значения) > 1)
    if спорные:
        первый = спорные[0]
        стороны = sorted(по_атрибуту[первый])
        return Probe(
            CLASS_CONTRADICTION,
            True,
            True,
            CLASS_OUTCOME[CLASS_CONTRADICTION],
            f"источники расходятся в {первый}: {' / '.join(стороны)} — сторона не выбирается",
        )
    return Probe(
        CLASS_CONTRADICTION,
        True,
        False,
        PASS,
        f"решающих атрибутов сверено: {len(по_атрибуту)}, расхождений нет",
    )


def step_report(
    step: Step,
    facts: Sequence[Fact],
    earlier: Sequence[Step] = (),
    today: date | None = None,
    overrides: dict | None = None,
) -> dict:
    """Все семь оракулов по одному шагу и сведённый исход шага.

    Порядок опроса — порядок `CLASSES`, и первый класс особый: при пустой базе
    фактовые оракулы физически не могут отработать, и они докладывают об этом
    третьим исходом вместо того, чтобы называть свой класс за компанию. Иначе
    один посеянный дефект зажигал бы четыре класса, и «назван тот самый» стало
    бы неотличимо от «названо всё подряд».
    """
    сегодня = today or date.today()
    свои = facts_for(step.model, facts)
    пробы = [probe_no_model(step, свои), probe_gap(step, earlier)]
    if пробы[0].fired:
        for k in (CLASS_APPLICABILITY, CLASS_LICENCE, CLASS_PRICE, CLASS_STALE):
            пробы.append(Probe(k, False, False, PASS, "база о модели молчит — оракулу не на чем"))
        пробы.append(
            Probe(
                CLASS_CONTRADICTION, False, False, PASS, "база о модели молчит — расходиться нечему"
            )
        )
    else:
        пробы.append(probe_applicability(step, свои, overrides))
        пробы.append(probe_licence(step, свои))
        пробы.append(probe_price(step, свои))
        пробы.append(probe_stale(step, свои, сегодня))
        пробы.append(probe_contradiction(step, свои))

    порядок = {k: i for i, k in enumerate(CLASSES)}
    пробы.sort(key=lambda p: порядок[p.klass])
    работавшие = [p for p in пробы if p.applicable]
    сработали = [p for p in работавшие if p.fired]
    нарушения = [p for p in сработали if p.outcome == FAIL]
    не_смогли = [p for p in работавшие if not p.fired and p.outcome == UNMEASURED] + [
        p for p in сработали if p.outcome == UNMEASURED
    ]

    if нарушения:
        исход = FAIL
    elif не_смогли:
        исход = UNMEASURED
    else:
        исход = PASS

    return {
        "step": step.name,
        "model": step.model,
        "requirement": step.requirement,
        "outcome": исход,
        "classes": [p.klass for p in сработали],
        "checked": len(работавшие),
        "violations": len(нарушения),
        "unmeasured": len(не_смогли),
        "not_declared": len(пробы) - len(работавшие),
        "probes": [
            {
                "class": p.klass,
                "applicable": p.applicable,
                "fired": p.fired,
                "outcome": p.outcome,
                "note": p.note,
            }
            for p in пробы
        ],
    }


def pipeline_report(
    pipeline: Pipeline,
    facts: Sequence[Fact],
    today: date | None = None,
    overrides: dict | None = None,
) -> dict:
    """Исход пайплайна — СЛАБЕЙШЕЕ звено, вычисленное, а не написанное рядом.

    Пустой пайплайн — третий исход, а не `годно`: ноль нарушений при нуле
    проверенных шагов не есть успех (Р2).
    """
    шаги = []
    for i, шаг in enumerate(pipeline.steps):
        шаги.append(step_report(шаг, facts, pipeline.steps[:i], today, overrides))

    checked = sum(s["checked"] for s in шаги)
    violations = sum(s["violations"] for s in шаги)
    unmeasured = sum(s["unmeasured"] for s in шаги)
    классы: list[str] = []
    for s in шаги:
        классы.extend(k for k in s["classes"] if k not in классы)

    if not шаги:
        исход = UNMEASURED
        нота = "в пайплайне нет ни одного шага — проверять нечего"
    elif any(s["outcome"] == FAIL for s in шаги):
        исход = FAIL
        нота = f"слабейшее звено: {_первый(шаги, FAIL)}"
    elif any(s["outcome"] == UNMEASURED for s in шаги):
        исход = UNMEASURED
        нота = f"слабейшее звено: {_первый(шаги, UNMEASURED)}"
    else:
        исход = PASS
        нота = f"{len(шаги)} шаг(ов) не опровергнуты ни одним из {len(CLASSES)} классов"

    return {
        "pipeline": pipeline.name,
        "outcome": исход,
        "classes": классы,
        "checked": checked,
        "violations": violations,
        "unmeasured": unmeasured if шаги else 1,
        "not_declared": sum(s["not_declared"] for s in шаги),
        "note": нота,
        "steps": шаги,
    }


def _первый(шаги: Sequence[dict], исход: str) -> str:
    for s in шаги:
        if s["outcome"] == исход:
            классы = ", ".join(s["classes"]) or "класс не назван"
            return f"{s['step']} — {классы}"
    return "не найдено"


def classes_fired(report: dict) -> tuple[str, ...]:
    """Какие классы назвал валидатор. Кортеж, а не множество: порядок печатный."""
    return tuple(report.get("classes", ()))


def outcome_of(report: dict) -> str:
    return str(report.get("outcome", UNMEASURED))


def render(report: dict) -> str:
    """Печать с числами Р2 рядом с исходом, всегда — и на `годно` тоже."""
    строки = [
        f"пайплайн: {report['pipeline']}",
        f"исход: {fa.OUTCOME_WORDS.get(report['outcome'], report['outcome'])} — {report['note']}",
        f"классы: {', '.join(report['classes']) or 'ни один из семи не сработал'}",
        (
            f"проверено {report['checked']}, нарушений {report['violations']}, "
            f"не смогли {report['unmeasured']}, не заявлено {report['not_declared']}"
        ),
    ]
    for s in report["steps"]:
        строки.append(
            f"  шаг {s['step']} [{s['model']}]: "
            f"{fa.OUTCOME_WORDS.get(s['outcome'], s['outcome'])}"
            f" — {', '.join(s['classes']) or 'чисто'}"
        )
        for p in s["probes"]:
            знак = "!" if p["fired"] else ("?" if p["outcome"] == UNMEASURED else ".")
            if not p["applicable"]:
                знак = "-"
            строки.append(f"    {знак} {p['class']}: {p['note']}")
    return "\n".join(строки)


def _strings(value: object) -> tuple[str, ...]:
    """Список строк из строки данных. Не список — пусто, а не половина списка."""
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(str(a) for a in value)


def _rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [r for r in value if isinstance(r, Mapping)]


def parse_step(row: Mapping[str, object]) -> Step:
    """Шаг из строки данных. Не разбираемый бюджет — `None`, а не ноль.

    Ноль здесь был бы худшим из возможных значений: он читается как «бесплатно»
    и превратил бы опечатку в самый строгий бюджет из всех.
    """
    бюджет = row.get("budget_usd")
    return Step(
        name=str(row.get("name", "")),
        model=str(row.get("model", "")),
        requirement=str(row.get("requirement", "")),
        requires=_strings(row.get("requires")),
        produces=_strings(row.get("produces")),
        budget_usd=float(бюджет) if isinstance(бюджет, (int, float)) else None,
        use=str(row.get("use", USE_COMMERCIAL)),
    )


def parse_pipeline(row: Mapping[str, object]) -> Pipeline:
    return Pipeline(
        name=str(row.get("name", "")),
        steps=tuple(parse_step(s) for s in _rows(row.get("steps"))),
    )


def _parse_fact(row: Mapping[str, object]) -> Fact:
    return Fact(
        model=str(row.get("model", "")),
        attribute=str(row.get("attribute", "")),
        value=str(row.get("value", "")),
        source_url=str(row.get("source_url", "")),
        tier=str(row.get("tier", "")),
        stated_on=str(row.get("stated_on", "")),
        witnessed=str(row.get("witnessed", "")),
    )


def load_controls(path: Path = DEFAULT_CONTROLS_PATH) -> list[Control]:
    """Контрольный набор из файла. Негодная строка ПРОПУСКАЕТСЯ здесь и ловится гейтом.

    Молча пропущенная строка — это контроль, который человек считает стоящим,
    а его нет; поэтому рядом живёт `rows_in`, и гейт сравнивает два числа.
    """
    if not path.is_file():
        return []
    набор: list[Control] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("kind") not in (KIND_MUTANT, KIND_HEALTHY):
            continue
        if not row.get("id") or not isinstance(row.get("pipeline"), dict):
            continue
        ожидаемые = tuple(str(k) for k in (row.get("expect_classes") or ()))
        if any(k not in CLASSES for k in ожидаемые):
            continue
        if row.get("expect_outcome") not in (PASS, FAIL, UNMEASURED):
            continue
        набор.append(
            Control(
                id=str(row["id"]),
                kind=str(row["kind"]),
                pipeline=parse_pipeline(row["pipeline"]),
                facts=tuple(_parse_fact(f) for f in _rows(row.get("facts"))),
                today=str(row.get("today", "")),
                expect_classes=ожидаемые,
                expect_outcome=str(row["expect_outcome"]),
                why=str(row.get("why", "")),
            )
        )
    return набор


def rows_in(path: Path = DEFAULT_CONTROLS_PATH) -> int:
    """Сколько строк данных в файле контроля, годных и негодных вместе."""
    if not path.is_file():
        return 0
    return sum(
        1
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("//")
    )
