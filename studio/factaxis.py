"""Вторая ось у факта: ЧЕМ он является, отдельно от того, КТО его сказал.

ЗАЧЕМ ЭТОТ МОДУЛЬ СУЩЕСТВУЕТ

Лестница тиров одномерна и ставит `vendor` первым. Но вендорская страница —
это список параметров, то есть самый CAPABILITY-образный артефакт, какой
бывает. Значит СТРУКТУРА поднимает способность на верх каждого ответа, пока
инструкция сервера ПРОЗОЙ толкает в обратную сторону («схема доказывает
capability, не applicability»). Структура выигрывает у прозы всегда.

ИЗМЕРЕНО 2026-08-31 на живой базе (969 действующих утверждений):

    vendor 501, portal 219, paper 184, benchmark 66, blog 64, probe 13,
    operator 1 — а строк с заполненным `witnessed` ровно 1 из 969.

Ось авторитета отвечает на вопрос «кому верить». Она не отвечает на вопрос
«что именно доказано», и именно второй решает судьбу шага плана.

ЧЕТЫРЕ РОДА ФАКТА

    schema       API принимает такой вход: параметр, лимит, enum, цена
    claim        проза о качестве: «лучшее в классе», «фотореализм»
    measurement  число с НАЗВАННЫМ протоколом (статья с методом, бенчмарк)
    witness      кто-то запустил и описал увиденное (зонд, оператор, практик)

    CAPABILITY   = schema + claim
    APPLICABILITY = measurement + witness

Ось ортогональна авторитету, и это проверяемо на двух настоящих строках:
вендорская проза о качестве — способность при ВЫСШЕМ авторитете; отчёт
практика в обсуждении — применимость при НИЗШЕМ. Ни один тир не определяет
род, и ни один род не определяет тир.

ПОЧЕМУ РАЗМЕТКА ВЫВОДИТСЯ, А НЕ ОБЪЯВЛЯЕТСЯ НАБЛЮДЕНИЕМ

Большая часть выводится механически из тира и имени атрибута. Такая строка
несёт `origin = РАСЧЁТ` (правило И4) и НИКОГДА `ИЗМЕРЕНО`: выведенное число,
поданное как наблюдённое, потом никто не решается тронуть. `ИЗМЕРЕНО` носит
только та строка, у которой наблюдение лежит в самом факте — поле `witnessed`.
Что не вывелось — третий исход `не смогли` (правило Р1), а не догадка.

РОД — ЭТО ЕЩЁ НЕ ОТВЕТ: НУЖНО ТРЕБОВАНИЕ

ИЗМЕРЕНО 2026-09-02, до правки: `step_verdict` принимал требование параметром,
возвращал его эхом и НЕ ЧИТАЛ НИ РАЗУ. На одном наборе фактов об infinitetalk:

    требование='остальные лица в кадре не должны уплывать' -> не годно
    требование='30 секунд, губы держат синхрон'            -> не годно
    требование='вылечить рак'                              -> не годно
    требование=''                                          -> не годно

Исход считался по одним лишь родам собранных строк. То есть прибор отвечал на
вопрос «что вообще известно про модель», а выдавал это за ответ на вопрос
«годится ли она ДЛЯ ЭТОГО» — уверенный ответ без основания.

Теперь строка сначала проходит проверку на ОТНОШЕНИЕ к требованию (`relates`),
и решает это `studio/factindex.py` — прибор поиска фактов словами задачи,
написанный ровно для такого вопроса и до 2026-09-02 не подключённый ни к чему.
Второй ретривер здесь не заводится (Е1).

ЧЕГО ЭТА ОСЬ НЕ УМЕЕТ, СКАЗАНО ВСЛУХ (И6)

Отношение решается СЛОВАМИ, а живая база на 2026-09-02 англоязычна: русских
значений 252 из 1696, а среди строк ПРИМЕНИМОСТИ русских ровно 1. Значит
требование, написанное оператором по-русски, чаще всего не совпадёт ни с одной
английской строкой, и честный исход у него — `не смогли`. Это граница прибора,
а не его настройка: порогом она не лечится (см. `RELEVANCE_FLOOR`), лечится
мостом между языком требования и языком базы, которого в репозитории нет.

Два наблюдения о `studio/factindex.py` — файл читался, но не правился (Ц2),
и обе находки адресованы его владельцу:

1. ИЗМЕРЕНО 2026-09-02: `tokens("the vendor's 15. Narrowing")` даёт `15.` с
   точкой, а не `15` — конечная точка приклеивается к слову. Строка, где число
   стоит в конце предложения, по этому числу не находится. Наблюдено на
   `kling-3.0.probe_cannot_settle_duration`: подбирается она только потому,
   что `15` без точки есть в её `note`.
2. ИЗМЕРЕНО 2026-09-02: `haystack` НЕ включает поле `witnessed`. То есть
   единственное поле, где лежит настоящее наблюдение («запустили и увидели»),
   для поиска невидимо, и строка-свидетельство относится к требованию только
   через своё `value`. Для оси это прямая цена: witness-строка, у которой
   наблюдение записано аккуратно в `witnessed`, а `value` короткое, не будет
   отнесена ни к какому требованию.
3. ИЗМЕРЕНО 2026-09-02: собственный мотивирующий пример модуля не работает.
   `FactIndex().search("заменить персонажа, сохранив цветокор и освещение")`
   на живой базе (1696 строк) возвращает НОЛЬ находок, хотя в докстроке
   `factindex.py` он назван дословным ответом. Причина та же: строка
   `wan-animate-replace` написана по-английски.

ПОЧЕМУ ОТДЕЛЬНЫЙ МОДУЛЬ

`studio/knowledge.py` и `studio/mcp/advice.py` — чужие файлы (Ц2). Ось
считается здесь, поверх `studio/selfrag/facts.Fact`, ничего в базе не меняя.
Цена названа вслух: разметка живёт не рядом с фактом, и её надо звать явно.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio.factindex import SCORE_FLOOR, FactIndex
from studio.measured import ORIGINS
from studio.selfrag.facts import (
    TIER_BENCHMARK,
    TIER_OPERATOR,
    TIER_PAPER,
    TIER_PROBE,
    Fact,
)

__all__ = [
    "APPLICABILITY",
    "APPLICABILITY_HEADER",
    "CAPABILITY",
    "CAPABILITY_HEADER",
    "CONTRA_ATTRIBUTES",
    "DEFAULT_OVERRIDES_PATH",
    "KINDS",
    "KIND_CLAIM",
    "KIND_MEASUREMENT",
    "KIND_SCHEMA",
    "KIND_WITNESS",
    "MEASUREMENT_TIERS",
    "NO_APPLICABILITY",
    "NO_RELEVANCE",
    "QUALITY_ATTRIBUTES",
    "RELEVANCE_FLOOR",
    "SCHEMA_MARKERS",
    "WITNESS_TIERS",
    "Marked",
    "OUTCOME_WORDS",
    "axis",
    "axis_key",
    "load_overrides",
    "rows_in",
    "mark",
    "mark_all",
    "relates",
    "render",
    "step_verdict",
]

KIND_SCHEMA = "schema"
KIND_CLAIM = "claim"
KIND_MEASUREMENT = "measurement"
KIND_WITNESS = "witness"

#: Все четыре рода. Порядок — от самого дешёвого доказательства к самому
#: дорогому, и он же порядок печати.
KINDS: tuple[str, ...] = (KIND_SCHEMA, KIND_CLAIM, KIND_MEASUREMENT, KIND_WITNESS)

#: Две колонки. Разложены константами, а не литералами по коду: их читают в
#: трёх местах, и разъехавшийся литерал на этом проекте уже стоил 1.7 ГБ (Е1).
CAPABILITY: tuple[str, ...] = (KIND_SCHEMA, KIND_CLAIM)
APPLICABILITY: tuple[str, ...] = (KIND_MEASUREMENT, KIND_WITNESS)

CAPABILITY_HEADER = "способность"
APPLICABILITY_HEADER = "применимость"

#: Пустая колонка применимости — это ЗНАЧЕНИЕ, а не отсутствие текста.
#: Рекомендация, напечатанная без второй колонки, читается как рекомендация
#: без оговорки; напечатанная с этой строкой — как то, чем она является.
NO_APPLICABILITY = "нет свидетельства"

#: Тиры, у которых наблюдение встроено в способ добычи факта. `probe` — это
#: вендорский API, спрошенный и ответивший; `operator` — владелец запустил и
#: увидел. Оба взяты ИМЕНАМИ из `facts.py`, а не переписаны строкой (Е1).
WITNESS_TIERS: frozenset[str] = frozenset({TIER_PROBE, TIER_OPERATOR})

#: Тиры, у которых протокол НАЗВАН по определению самой лестницы: `paper` —
#: «with a method somebody can check», `benchmark` — «an independent
#: leaderboard or evaluation with a method» (studio/selfrag/facts.py). Число
#: без названного протокола — не измерение, а цифра.
MEASUREMENT_TIERS: frozenset[str] = frozenset({TIER_PAPER, TIER_BENCHMARK})

#: Атрибуты, отвечающие на вопрос «как это себя ведёт и где ломается». Род
#: такой строки решает ТИР: у статьи и бенчмарка это измерение, у зонда и
#: оператора — свидетельство, у вендора и площадки — проза о качестве.
#: Головные имена взяты по частоте на живой базе 2026-08-31.
QUALITY_ATTRIBUTES: frozenset[str] = frozenset(
    {
        # Отчёт практика о прогоне без названного знака. В CONTRA не входит
        # намеренно: «человек описал, что вышло» не равно «здесь ломается».
        "observed_behaviour",
        "failure_mode",
        "limitation",
        "degrades_when",
        "metric_blind_spot",
        "artifact_taxonomy",
        "holds_identity",
        "benchmark_score",
        "best_for",
        "tradeoff",
        "positioning",
        "adoption",
        "latency",
        "rendering_speed",
        "generation_time",
        "training_time",
        "physics_ceiling",
        "retrieval_quality",
        "voice_consistency",
        "text_rendering",
        "text_rendering_non_latin",
        "upscale_artifacts",
        "evaluation_protocol",
        "expander_evidence",
        "retrieval_grounding",
        "expands_internally",
        "price_relative",
        "speed_range",
        "role",
        "summary_line",
        "capabilities",
    }
)

#: Атрибуты, которые говорят «эта строка про то, что ЛОМАЕТСЯ». Свидетельство
#: или измерение с таким атрибутом идёт ПРОТИВ шага, а не за него: наблюдение
#: бывает отрицательным, и сворачивать его в «применимость есть» значит красить
#: красное зелёным.
CONTRA_ATTRIBUTES: frozenset[str] = frozenset(
    {
        "failure_mode",
        "limitation",
        "degrades_when",
        "metric_blind_spot",
        "artifact_taxonomy",
    }
)

#: Куски имени атрибута, по которым он опознаётся как ФОРМА ВХОДА: то, что
#: API принимает, чем ограничивает и во что оценивает. Список кусков, а не
#: полных имён, потому что имён 269 и хвост длинный: `max_audio_seconds`,
#: `price_per_video_second_usd`, `ratio_enum_image_to_video` — три разных
#: имени одной и той же формы. ВЫБРАНО по разбору всех 269 имён живой базы.
SCHEMA_MARKERS: tuple[str, ...] = (
    "price",
    "cost",
    "max_",
    "_max",
    "min_",
    "_min",
    "limit",
    "enum",
    "range",
    "options",
    "presets",
    "resolution",
    "duration",
    "seconds",
    "frames",
    "fps",
    "frame_rate",
    "aspect",
    "ratio",
    "size",
    "length",
    "license",
    "licence",
    "parameter_count",
    "context_window",
    "tokens",
    "formats",
    "modalit",
    "input",
    "output",
    "accepts_",
    "supported_",
    "parameter",
    "endpoint",
    "api_",
    "availability",
    "status",
    "lifecycle",
    "deprecation",
    "end_of_life",
    "architecture",
    "model_id",
    "vram",
    "concurrency",
    "regions",
    "languages",
    "voices",
    "controls",
)

#: Пустое пересечение с требованием — это ЗНАЧЕНИЕ, а не отсутствие текста, по
#: той же причине, что и `NO_APPLICABILITY`. Исход, напечатанный без этой
#: строки, читается как ответ на заданный вопрос, а он ответ на другой.
NO_RELEVANCE = "ни одна строка не относится к требованию"

#: Ниже этого веса строка не считается ОТНОСЯЩЕЙСЯ к требованию. Не своё число:
#: имя импортировано из `studio/factindex.py` (Е1), где порог и живёт вместе с
#: прибором, который его применяет. Копия здесь дала бы второй способ узнать
#: известное — ровно тот дефект, который на этом проекте стоил 1.7 ГБ.
#:
#: ИЗМЕРЕНО 2026-09-02 на контрольном наборе ниже (RELEVANCE_CONTROL в
#: `scripts/check_fact_axis.py`, настоящие строки живой базы): сдвиг порога не
#: разделяет верные подборы от ложных — их веса перемешаны (верные 0.289…0.687,
#: ложные 0.196…0.429). Значит порог здесь не ручка качества, и крутить его
#: вместо разбора значило бы подгонять число под желаемый ответ.
RELEVANCE_FLOOR = SCORE_FLOOR

DEFAULT_OVERRIDES_PATH = Path(__file__).with_name("knowledge") / "fact_axis.jsonl"


def axis_key(model: str, attribute: str, source_url: str) -> tuple[str, str, str]:
    """Чем ручная разметка находит свой факт: модель, атрибут и СТРАНИЦА.

    Значение факта в ключ НЕ входит, в отличие от `facts.claim_key`, и это
    сознательная разница с ценой. Причина — правило дома: репозиторий хранит
    пересказ со ссылкой, а не чужую прозу, и ключ со значением заставил бы
    копировать формулировку источника во второй файл (заодно нарушив Е1: одно
    знание, одно место). Цена: если одна страница даёт два значения одного
    атрибута — а такое в этой базе ИЗМЕРЕНО, `seedance2-video.com` даёт `12` и
    `4 to 15` на одной странице, — ручная разметка накроет оба. Гейт печатает,
    сколько утверждений накрыла каждая ручная строка, чтобы это было видно, а
    не тихо.
    """
    return (model.strip().lower(), attribute.strip().lower(), source_url.strip())


@dataclass(frozen=True)
class Marked:
    """Один факт с его родом, происхождением разметки и причиной.

    `kind` пустой — третий исход: род не выведен. Пустая строка здесь не
    «неизвестно, наверное schema», а «не смогли», и она печатается числом.
    """

    fact: Fact
    kind: str
    origin: str
    why: str

    @property
    def resolved(self) -> bool:
        return bool(self.kind)


def axis(kind: str) -> str:
    """Колонка рода: способность, применимость или пусто для неразмеченного."""
    if kind in CAPABILITY:
        return CAPABILITY_HEADER
    if kind in APPLICABILITY:
        return APPLICABILITY_HEADER
    return ""


def _schema_shaped(attribute: str) -> bool:
    low = attribute.lower()
    return any(marker in low for marker in SCHEMA_MARKERS)


def mark(
    fact: Fact, overrides: dict[tuple[str, str, str], tuple[str, str, str]] | None = None
) -> Marked:
    """Род одного факта. Три исхода: род, род, и `не смогли` пустым родом.

    Порядок правил — от самого сильного свидетельства к самому слабому, и он
    же порядок чтения:

    1. в самой строке лежит `witnessed` — наблюдение принесено фактом, разметка
       НЕ вычислена, и только здесь `origin` может быть `ИЗМЕРЕНО`;
    2. тир — зонд или оператор: запустили и описали;
    3. атрибут про поведение: статья/бенчмарк дают измерение, все остальные —
       прозу о качестве (протокол не назван, значит это не измерение);
    4. имя атрибута про форму входа — схема;
    5. иначе `не смогли`.
    """
    ключ = axis_key(fact.model, fact.attribute, fact.source_url)
    if overrides and ключ in overrides:
        род, происхождение, почему = overrides[ключ]
        return Marked(fact, род, происхождение, почему)

    if fact.witnessed.strip():
        return Marked(
            fact, KIND_WITNESS, "ИЗМЕРЕНО", "строка несёт witnessed: что запустили и что увидели"
        )
    if fact.tier in WITNESS_TIERS:
        return Marked(
            fact, KIND_WITNESS, "РАСЧЁТ", f"тир {fact.tier}: наблюдение работающей системы"
        )
    if fact.attribute.lower() in QUALITY_ATTRIBUTES:
        if fact.tier in MEASUREMENT_TIERS:
            return Marked(
                fact,
                KIND_MEASUREMENT,
                "РАСЧЁТ",
                f"атрибут о поведении, тир {fact.tier}: протокол назван",
            )
        return Marked(
            fact, KIND_CLAIM, "РАСЧЁТ", f"атрибут о поведении, тир {fact.tier}: протокол не назван"
        )
    if _schema_shaped(fact.attribute):
        return Marked(fact, KIND_SCHEMA, "РАСЧЁТ", "имя атрибута описывает форму входа или лимит")
    return Marked(fact, "", "", "род не выведен ни тиром, ни именем атрибута")


def mark_all(
    facts: Iterable[Fact],
    overrides: dict[tuple[str, str, str], tuple[str, str, str]] | None = None,
) -> list[Marked]:
    """Разметка пачки. Порядок сохраняется: разметка — вид на базу, не сортировка."""
    return [mark(f, overrides) for f in facts]


def load_overrides(
    path: Path = DEFAULT_OVERRIDES_PATH,
) -> dict[tuple[str, str, str], tuple[str, str, str]]:
    """Ручные разметки: то, что вывести нельзя, а прочитать глазами можно.

    Файла нет — пусто, и это не ошибка: третий исход есть у каждой строки и
    без этого файла, отсутствие ручных правок ничего не скрывает. Строка с
    родом или происхождением не из своего списка не принимается молча — она
    пропускается ЗДЕСЬ и ловится гейтом, который сравнивает число строк файла
    с числом принятых.
    """
    if not path.is_file():
        return {}
    найдено: dict[tuple[str, str, str], tuple[str, str, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if row.get("kind") not in KINDS or row.get("origin") not in ORIGINS:
            continue
        if not row.get("model") or not row.get("attribute"):
            continue
        ключ = axis_key(str(row["model"]), str(row["attribute"]), str(row.get("source_url", "")))
        найдено[ключ] = (str(row["kind"]), str(row["origin"]), str(row.get("why", "")))
    return найдено


def rows_in(path: Path = DEFAULT_OVERRIDES_PATH) -> int:
    """Сколько строк данных в файле ручных разметок, годных и негодных вместе.

    Существует ровно затем, чтобы гейт мог увидеть РАЗНИЦУ с `load_overrides`:
    молча пропущенная строка — это разметка, которой человек думает, что она
    есть, а её нет.
    """
    if not path.is_file():
        return 0
    return sum(
        1
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("//")
    )


# DEBT(2026-09-02): `bash scripts/check` красный, и это НЕ починено здесь.
# Правка исхода уронила 7 контрольных подач `scripts/check_pipeline.py` и 6
# тестов `studio/mcp/tests/test_pipeline.py`. Разобрано поимённо: все 13 —
# ИСПРАВЛЕНИЯ, ни одного отката. Все одной формы: шаг требует одного («губы
# совпадают со звуком»), а факты модели говорят о другом (лицензия, цена,
# `holds_identity`), и прежний прибор объявлял такой шаг годным, потому что
# требование не читал. Теперь это `не смогли` — честный третий исход.
# Оба файла и `studio/pipeline.py` — чужие (Ц2, там работает другой агент),
# поэтому правка описана в отчёте, а не сделана молча.
#
# Отдельно: `studio/pipeline.py::probe_applicability` сворачивает `не смогли`
# в `violated=True`, то есть третий исход считается нарушением (нарушение Р1 в
# чужом файле). До этой правки развилка не достигалась — `step_verdict` не
# возвращал `не смогли` на здоровых подачах.


def relates(
    requirement: str, marked: Sequence[Marked], floor: float = RELEVANCE_FLOOR
) -> tuple[list[Marked], list[Marked]]:
    """Делит строки на ОТНОСЯЩИЕСЯ к требованию и прошедшие мимо него.

    Отношение строки к требованию — это РЕШЕНИЕ, а не предположение, и принимает
    его прибор поиска фактов словами задачи (`studio/factindex.py`). Второй
    ретривер здесь не заводится (Е1): тот написан ровно для этого вопроса.

    Индекс строится по ПОДАННЫМ строкам, а не по живой базе, и это выбор с
    ценой. Вес слова у `factindex` — `log(1 + n/df)`, то есть зависит от
    корпуса: на десятке строк редкое слово весит меньше, чем на живой базе, и
    порог отсекает слабее. Взамен прибор не требует живой базы вовсе, а значит
    работает на синтетических подачах контроля и не ходит никуда (Т4).

    Пустое требование — пустой список относящихся. Это не ошибка и не «подходит
    всё»: спросить нечем, и честный ответ у такого вопроса третий.
    """
    if not marked:
        return [], []
    if not str(requirement or "").strip():
        return [], list(marked)
    индекс = FactIndex(facts=[m.fact for m in marked])
    попало = {id(h.fact) for h in индекс.search(requirement, k=len(marked), floor=floor)}
    относятся = [m for m in marked if id(m.fact) in попало]
    мимо = [m for m in marked if id(m.fact) not in попало]
    return относятся, мимо


def step_verdict(
    step: str, requirement: str, marked: Sequence[Marked], floor: float = RELEVANCE_FLOOR
) -> dict:
    """Исход шага ВЫЧИСЛЯЕТСЯ из колонок, и вычисляется ПРО ЭТО требование.

    Требование здесь не эхо. Оно решает, какие строки вообще имеют право
    голоса: строка, не относящаяся к требованию, не закрывает его и не
    опровергает — она про другое. До 2026-09-02 требование принималось
    параметром и не читалось ни разу, и прибор на одном наборе фактов отвечал
    одно и то же на «губы держат синхрон» и на «вылечить рак». Это худший класс
    дефекта: уверенный ответ без основания, потому что отвечал он на вопрос
    «что вообще известно про модель», а выдавал за ответ на «годится ли она ДЛЯ
    ЭТОГО».

    Три исхода (Р1), и главный из них третий:

    * `не годно` — есть строка, ОТНОСЯЩАЯСЯ к требованию, и она отрицательная:
      кто-то запустил или измерил ровно то место, где шаг ломается;
    * `годно` — есть относящаяся строка применимости, и она не отрицательная;
    * `не смогли` — относящихся строк применимости нет. Сюда попадает и шаг,
      чьё убийственное требование закрыто ТОЛЬКО схемой (вендор принимает такой
      вход — это не то же самое, что «результат держится»), и шаг, к
      требованию которого база не относится вовсе. Ветки, печатающей «годно»
      по одной колонке способности, здесь нет физически, и это единственная
      причина существования всего модуля.

    `не относится` печатается ЧИСЛОМ рядом с прочими (Р2): отброшенные строки —
    это то, что прибор знал и не стал считать, и молчать об этом значит выдать
    узкий ответ за полный.
    """
    относятся, мимо = relates(requirement, marked, floor)
    размечено = [m for m in относятся if m.resolved]
    не_смогли = [m for m in относятся if not m.resolved]
    способность = [m for m in размечено if m.kind in CAPABILITY]
    применимость = [m for m in размечено if m.kind in APPLICABILITY]
    против = [m for m in применимость if m.fact.attribute.lower() in CONTRA_ATTRIBUTES]

    if против:
        исход = FAIL
        нота = (
            f"применимость наблюдалась ПО ЭТОМУ требованию и она отрицательная: "
            f"{len(против)} строк(и) о том, где это ломается"
        )
    elif применимость:
        исход = PASS
        нота = f"применимость закрыта {len(применимость)} относящимися строк(ами), не опровергнута"
    else:
        исход = UNMEASURED
        if not marked:
            нота = "нечем закрывать требование: ни одной размеченной строки"
        elif not относятся:
            нота = f"{NO_RELEVANCE}: {len(мимо)} строк(и) про другое"
        elif способность:
            нота = (
                f"{CAPABILITY_HEADER} закрыта {len(способность)} относящимися строк(ами), "
                f"{APPLICABILITY_HEADER}: {NO_APPLICABILITY}"
            )
        else:
            нота = f"относящихся строк {len(относятся)}, но род не выведен ни у одной"

    return {
        "step": step,
        "requirement": requirement,
        "outcome": исход,
        "checked": len(размечено),
        "violations": len(против),
        "unmeasured": len(не_смогли) if размечено else max(len(не_смогли), 1),
        "off_topic": len(мимо),
        "note": нота,
        CAPABILITY_HEADER: [_row(m) for m in способность],
        APPLICABILITY_HEADER: [_row(m) for m in применимость],
    }


#: Как исход называется человеку. Значения — общие для репозитория (Е1):
#: `lipsync.fork_identity`, тот же словарь, что у всех прочих вердиктов.
OUTCOME_WORDS: dict[str, str] = {PASS: "годно", FAIL: "не годно", UNMEASURED: "не смогли"}


def _row(m: Marked) -> dict:
    return {
        "model": m.fact.model,
        "attribute": m.fact.attribute,
        "value": m.fact.value,
        "tier": m.fact.tier,
        "kind": m.kind,
        "origin": m.origin,
        "source_url": m.fact.source_url,
        "why": m.why,
    }


def render(verdict: dict) -> str:
    """Рекомендация ВСЕГДА в две колонки.

    Ветки «напечатать только способность» нет: пустая применимость печатается
    строкой `нет свидетельства`, потому что это её значение. Рекомендация без
    второй колонки читается как рекомендация без оговорки — а оговорка и есть
    то, ради чего вторая ось заводилась.
    """
    строки = [
        f"шаг: {verdict['step']}",
        f"требование: {verdict['requirement']}",
        f"исход: {OUTCOME_WORDS.get(verdict['outcome'], verdict['outcome'])} — {verdict['note']}",
        (
            f"проверено {verdict['checked']}, нарушений {verdict['violations']}, "
            f"не смогли {verdict['unmeasured']}, "
            f"не относится к требованию {verdict.get('off_topic', 0)}"
        ),
    ]
    for заголовок in (CAPABILITY_HEADER, APPLICABILITY_HEADER):
        строки.append(f"{заголовок}:")
        колонка = verdict.get(заголовок) or []
        строки.extend(
            f"  [{r['kind']}/{r['origin']}] {r['model']}.{r['attribute']} = {r['value']}"
            f"  ({r['tier']}, {r['source_url']})"
            for r in колонка
        )
        if not колонка:
            строки.append(f"  {NO_APPLICABILITY}")
    return "\n".join(строки)
