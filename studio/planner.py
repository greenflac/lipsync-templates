"""Из слов заказчика — ПЛАН, и сразу же через валидатор-2.

ЗАЧЕМ ЭТОТ МОДУЛЬ СУЩЕСТВУЕТ

Владелец описал продукт дословно: «Бот помогает собирать пайплайн на основе
готового креатива и с нуля». В репозитории было две половины и ни одного
моста между ними: `studio/pipeline.py` ПРИНИМАЕТ пайплайн и судит его семью
классами отказа, `studio/mcp/creative.py` разбирает поданный креатив — а
собрать план из брифа не умел никто.

ИЗМЕРЕНО 2026-09-02 до этого модуля (`scripts/planner_baseline.py`, снимок в
`studio/fixtures/planner_baseline_2026-09-02.txt`), восемь настоящих брифов:

    шагов плана ожидается 10, собрано репозиторием 0

и, что важнее, ЕДИНСТВЕННЫЙ существовавший мост «слова задачи -> база»
(`studio/factindex.py`, поданный брифом целиком) для выбора моделей не годен:

    «оживить фото клиента, 10 секунд, он говорит мою озвучку»
        -> sdxl-turbo, krea-2, stable-diffusion-3-medium, sulphur-2-base ...
           восемь имён, из них ни одно не делает липсинк; это картиночные модели
    «нужен пайплайн, который по видеопотоку управляет промышленным
     манипулятором на складе»
        -> исход `pass`, факт про `indextts-2`
    «заменить персонажа в готовом ролике, сохранив цветокор и освещение»
        -> НОЛЬ находок, хотя в базе лежит `wan-animate-replace` дословно об
           этом; бриф по-русски, база по-английски

То есть прибор отвечал ВСЕГДА и отвечал не тем. Планировщик, построенный на
такой подборке, выдал бы уверенный план из картиночных моделей — и это ровно
тот дефект, ради которого в этом доме заведено правило И5.

КАК ЗДЕСЬ ВЫБИРАЕТСЯ КАНДИДАТ, И ПОЧЕМУ НЕ ПОРОГОМ

Порог у поиска крутить бесполезно: `studio/factaxis.py` уже ИЗМЕРИЛ, что веса
верных и ложных подборов перемешаны. Поэтому кандидат отбирается не весом, а
ЯКОРЕМ: у каждой операции студии выписаны термины, которыми эту операцию
называет сама база (`lipsync`, `img2vid`, `text-to-speech`, ...), и моделью-
кандидатом считается та, о которой есть утверждение, СОДЕРЖАЩЕЕ якорный
термин. Второго поиска для этого не заводится (Е1): якоря подаются запросом в
тот же `studio.factindex.FactIndex`, и совпавшие слова печатаются рядом с
кандидатом — их видно, а не подразумевается.

Цена названа вслух (И6): якорь ловит только то, что база написала словами
операции. Модель, которая делает липсинк, но у которой в базе не стоит ни
одного из якорных слов, в кандидаты не попадёт. Это ПРОПУСК, и он честнее
подбора по весу, потому что пропуск виден как «кандидатов нет», а ложный
подбор виден как уверенный план.

ЧТО ЗДЕСЬ НЕ ДЕЛАЕТСЯ НИКОГДА

Не подставляется модель «по умолчанию». Шаг без кандидата остаётся ПУСТЫМ, а
исход всего плана — третий. Пустой шаг честнее выдуманного: выдуманный уходит
в работу и возвращается через неделю.

Не выдумывается цена. Цена берётся у `studio/pipeline.comparable_prices`, то
есть у разборщика `studio/pricing.py` (Е1), и если сравнимой строки нет — в
плане стоит «цена не записана», а не число.

Не заводится второго валидатора. План собирается в `pipeline.Pipeline` и
уходит в `pipeline.pipeline_report` как есть; исход плана здесь НЕ
пересчитывается, а берётся у него.

ТРИ ИСХОДА (Р1), И ГЛАВНЫЙ ИЗ НИХ ТРЕТИЙ

    годно      — план собран, и валидатор-2 его не опроверг;
    не годно   — план собран, и валидатор назвал класс отказа. Возвращается И
                 план, И класс: «не годно» без плана нечего чинить;
    не смогли  — из брифа не выводится ни один шаг (`шаги_не_выведены`), либо
                 у шага нет ни одного кандидата с доказательством
                 (`шаг_без_кандидатов`), либо валидатор сам сказал третье
                 (`план_не_подтверждён`).

ДОКАЗАТЕЛЬСТВО СТОИТ РЯДОМ С КАНДИДАТОМ, А НЕ В КОММЕНТАРИИ

У каждого кандидата печатается, ЧЕМ он выбран: атрибут, значение, ступень
источника (`tier`), дата (`stated_on`) и РОД свидетельства по второй оси
(`studio/factaxis.py`: schema / claim / measurement / witness). Род решает
формулировку: если о модели есть только вендорская схема и проза, у кандидата
стоит `NOT_MEASURED_MARK` — «применимость не измерена», и стоит она в выдаче,
в поле, которое нельзя не прочитать.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Mapping, Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio import factaxis as fa
from studio import pipeline as pl
from studio.factindex import FactIndex
from studio.selfrag.facts import Fact

__all__ = [
    "ARTEFACT_AUDIO",
    "ARTEFACT_BRIEF",
    "ARTEFACT_LIPSYNCED",
    "ARTEFACT_NOISE",
    "ARTEFACT_REFERENCE",
    "ARTEFACT_SELFIE",
    "ARTEFACT_VIDEO",
    "CANDIDATES_SHOWN",
    "CLASS_NAME_MARKER",
    "EVIDENCE_SHOWN",
    "HAVE_VIDEO_CUES",
    "NOT_MEASURED_MARK",
    "NO_PRICE",
    "OPERATIONS",
    "REASONS",
    "REASON_NO_CANDIDATES",
    "REASON_NO_STEPS",
    "REASON_PLAN_REFUSED",
    "REASON_PLAN_STANDS",
    "REASON_PLAN_UNCONFIRMED",
    "Candidate",
    "Evidence",
    "Operation",
    "by_evidence",
    "briefs",
    "candidates_for",
    "cheapest_price",
    "derive",
    "evidence_for",
    "inputs_of",
    "plan",
    "render",
    "rows_in",
    "to_pipeline",
]

# --------------------------------------------------------------------------
# Артефакты. Три первых ИМПОРТИРУЮТСЯ смыслом из `pipeline.AMBIENT_ARTEFACTS`
# (Е1): это вход плана, доступный любому шагу без того, чтобы его кто-то
# произвёл. Сверка ниже не декоративная — она ловит переименование в чужом
# модуле в тот же миг, когда оно случится, а не через отказ на живом брифе.
# --------------------------------------------------------------------------

ARTEFACT_BRIEF = "бриф"
ARTEFACT_SELFIE = "селфи"
ARTEFACT_REFERENCE = "референс"
ARTEFACT_AUDIO = "аудио"
ARTEFACT_VIDEO = "видео"
ARTEFACT_LIPSYNCED = "видео_с_липсинком"
ARTEFACT_NOISE = "фоновый_звук"

_AMBIENT_HERE = (ARTEFACT_BRIEF, ARTEFACT_SELFIE, ARTEFACT_REFERENCE)
_MISSING_AMBIENT = tuple(a for a in _AMBIENT_HERE if a not in pl.AMBIENT_ARTEFACTS)
if _MISSING_AMBIENT:  # pragma: no cover - ловится тестом контракта
    raise ImportError(
        f"валидатор больше не считает входом плана: {', '.join(_MISSING_AMBIENT)}; "
        f"у него {sorted(pl.AMBIENT_ARTEFACTS)}"
    )

#: Пометка на кандидате, о котором база знает ТОЛЬКО способность: вендорскую
#: схему и прозу о качестве. КОНСТАНТА-РЕШЕНИЕ, ВЫБРАНО: формулировка взята из
#: `factaxis.NO_APPLICABILITY` по смыслу, но сказана про КАНДИДАТА, а не про
#: колонку — читатель плана видит имя модели, а не таблицу родов. Это главное
#: правило дома в одной строке: модель без доказательства попадает в план
#: только с этой пометкой, и пометка стоит в выдаче.
NOT_MEASURED_MARK = "применимость не измерена"

#: Что стоит вместо цены, когда сравнимой ценовой строки в базе нет.
#: КОНСТАНТА-РЕШЕНИЕ, ВЫБРАНО: словами, а не числом и не нулём. Ноль читался
#: бы как «бесплатно», а пустое поле — как «дёшево»; и то и другое — выдумка.
NO_PRICE = "цена не записана"

#: Сколько кандидатов показывать на шаг. КОНСТАНТА-РЕШЕНИЕ, ВЫБРАНО = 3: план
#: читает человек, и выбор из трёх — это выбор, а из тридцати двух (столько
#: моделей дают якоря озвучки на живой базе) — список. Первый из трёх и есть
#: выбранный; остальные показаны, чтобы выбор был виден как выбор.
CANDIDATES_SHOWN = 3

#: Сколько строк доказательства печатать у кандидата. КОНСТАНТА-РЕШЕНИЕ,
#: ВЫБРАНО = 3 по той же причине. Числа `applicability`/`capability` рядом
#: считаются по ВСЕМ строкам, а не по показанным (Е3): урезанный список не
#: должен читаться как весь запас.
EVIDENCE_SHOWN = 3

# ЗДЕСЬ БЫЛ ФЛАГ `APPLICABILITY_FIRST = True`, И ЕГО УБРАЛА МУТАЦИЯ (Т1).
# Мутация в обе стороны 2026-09-02: подмена на `False` не покраснила НИ ОДИН
# тест и НИ ОДИН гейт. Разбор показал, почему: флаг включал ключ
# `-int(c.measured)`, а следующий ключ `-c.applicability` даёт ровно тот же
# порядок — одна строка применимости уже обгоняет девяносто девять строк
# способности. То есть флаг был вторым способом узнать известное (Е1), и
# ветвления за ним не стояло. Развилка живёт в `by_evidence` и сторожится
# `ПорядокКандидатов.test_измеренное_впереди_заявленного`.

#: Имя, которое НЕ является моделью: находка о КЛАССЕ («*», «eleven-*»).
#: КОНСТАНТА-РЕШЕНИЕ, ВЫБРАНО по тому, как эти строки записаны в базе
#: (`studio/mcp/advice.py`, `_card_vs_base`): звёздочка — объявленная область
#: находки. Кандидатом такая строка быть не может: шаг плана исполняет
#: конкретная модель, а «*» запустить нельзя.
CLASS_NAME_MARKER = "*"

#: Слова брифа, по которым видео считается УЖЕ ЕСТЬ у заказчика. КОНСТАНТА-
#: РЕШЕНИЕ, ВЫБРАНО по настоящим брифам владельца: «из готового ролика»,
#: «заменить персонажа в готовом ролике». Без этого списка шаг липсинка на
#: готовом креативе получал бы класс `разрыв` — валидатор прав, видео и правда
#: никто не производит, но производить его и не надо: оно вход плана.
HAVE_VIDEO_CUES: tuple[str, ...] = (
    "готов",
    "из ролика",
    "мой ролик",
    "моего ролика",
    "исходник",
    "уже есть видео",
    "уже снят",
)

#: Расширения, по которым поданный креатив считается видео. ИМПОРТИРУЮТСЯ, а
#: не переписываются: список живёт у разборщика креатива (Е1).
try:  # pragma: no cover - подстраховка на случай отсутствия зависимостей разбора
    from studio.mcp.creative import VIDEO_SUFFIXES
except Exception:  # pragma: no cover
    VIDEO_SUFFIXES = frozenset({".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"})

REASON_NO_STEPS = "шаги_не_выведены"
REASON_NO_CANDIDATES = "шаг_без_кандидатов"
REASON_PLAN_REFUSED = "валидатор_отверг"
REASON_PLAN_UNCONFIRMED = "план_не_подтверждён"
REASON_PLAN_STANDS = "план_подтверждён"

#: Весь словарь причин. Список — не украшение: он делает состав причин
#: проверяемым тестом, а не памятью читающего (форма взята у
#: `studio/mcp/advice.py::REASONS`, где она уже оправдала себя).
REASONS: tuple[str, ...] = (
    REASON_NO_STEPS,
    REASON_NO_CANDIDATES,
    REASON_PLAN_REFUSED,
    REASON_PLAN_UNCONFIRMED,
    REASON_PLAN_STANDS,
)


@dataclass(frozen=True)
class Operation:
    """Одна операция студии: чем её зовёт заказчик и чем её зовёт база.

    Два словаря нарочно РАЗНЫЕ, и это главное решение модуля:

    * `cues` — куски слов, которыми операцию называет заказчик. По ним
      операция ВЫВОДИТСЯ из брифа. Русские, потому что бриф русский;
    * `anchors` — термины, которыми ту же операцию называет база фактов. По
      ним ищутся КАНДИДАТЫ. Английские, потому что база английская (ИЗМЕРЕНО
      и записано в `studio/factaxis.py`: русских значений 252 из 1696).

    Слить их в один список значило бы искать модели русскими словами, а это
    ИЗМЕРЕНО и даёт ноль находок на настоящем вопросе владельца.
    """

    name: str
    cues: tuple[str, ...]
    anchors: tuple[str, ...]
    requires: tuple[str, ...]
    produces: tuple[str, ...]
    requirement: str


#: Словарь операций студии. КОНСТАНТА-РЕШЕНИЕ, ВЫБРАНО по восьми настоящим
#: брифам владельца (`studio/fixtures/planner_briefs.jsonl`) — не по
#: соображениям о том, что бывает на свете.
#:
#: ПОРЯДОК ЗДЕСЬ — ПОРЯДОК ШАГОВ В ПЛАНЕ, и он не случайный: всё, что
#: ПРОИЗВОДИТ артефакт, стоит раньше того, что его ТРЕБУЕТ. Иначе валидатор
#: увидел бы `разрыв` на здоровом плане, просто потому что шаги перечислены не
#: в том порядке, — и класс, заведённый ради настоящих разрывов, красил бы шум.
#:
#: `звук_фон` стоит в словаре, зная, что база о нём молчит (ИЗМЕРЕНО
#: 2026-09-02: якоря `foley`, `sound-effects`, `sfx` дают 0 утверждений из
#: 1776). Это не недосмотр, а негативный контроль в живом словаре: операция,
#: которую студия делает, а база не закрывает, обязана давать «не смогли» с
#: НЕПУСТЫМ планом, и без такой строки эта ветка была бы недостижима.
OPERATIONS: tuple[Operation, ...] = (
    Operation(
        name="озвучка",
        cues=("озвучк", "озвуч", "голос", "диктор", "начитк", "voiceover"),
        # `voice`, `speech` и `voiceover` из якорей УБРАНЫ после чтения выдачи
        # (П3, 2026-09-02): по ним в кандидаты на озвучку выходил `flux-3` —
        # видеомодель с речью в кадре, у которой десять строк про `voiceover
        # cue` и `voice direction`. Строки честные, про промпт, а не про синтез
        # речи; десять таких строк перевешивали три строки `elevenlabs-ivc`.
        # Якорь обязан называть ОПЕРАЦИЮ, а не встречаться в разговоре о ней.
        anchors=("tts", "text-to-speech", "text2speech", "voice-cloning", "speech-synthesis"),
        requires=(ARTEFACT_BRIEF,),
        produces=(ARTEFACT_AUDIO,),
        requirement=(
            "речь по тексту заказчика, голос держится всю реплику; "
            "text to speech, voice cloning, speech quality"
        ),
    ),
    Operation(
        name="дубляж",
        cues=("другой язык", "другом языке", "перевод", "дубляж", "локализ", "dub"),
        # `translation`, `multilingual` и `languages` из якорей УБРАНЫ после
        # чтения выдачи (П3, 2026-09-02): по ним в кандидаты на дубляж выходил
        # `cogvideox-5b` — видеомодель, у которой в базе записано «English-only
        # text encoder, non-English prompts must be machine-translated». Строка
        # честная, к дубляжу отношения не имеет. Широкий якорь ловит слово, а
        # не операцию.
        anchors=("dubbing", "dub", "дубляж"),
        requires=(ARTEFACT_REFERENCE,),
        produces=(ARTEFACT_AUDIO,),
        requirement=(
            "речь того же ролика на другом языке, смысл и тайминг держатся; "
            "dubbing, translation, multilingual speech"
        ),
    ),
    Operation(
        name="оживление",
        cues=("оживить", "оживи", "оживл", "фото", "селфи", "портрет", "снимок"),
        anchors=("img2vid", "i2v", "image-to-video", "image2video", "image-to-video-generation"),
        requires=(ARTEFACT_SELFIE,),
        produces=(ARTEFACT_VIDEO,),
        requirement=(
            "лицо клиента не подменяется, движение не разваливает кадр; "
            "image to video, i2v, identity preservation"
        ),
    ),
    Operation(
        name="генерация_видео",
        cues=("с нуля", "сгенерир", "с чистого листа", "from scratch", "снять видео"),
        anchors=("text-to-video", "t2v", "txt2vid", "text2video"),
        requires=(ARTEFACT_BRIEF,),
        produces=(ARTEFACT_VIDEO,),
        requirement=(
            "видео по описанию, длительность и план держатся; "
            "text to video, t2v, duration, resolution"
        ),
    ),
    Operation(
        name="замена_персонажа",
        cues=("заменить персонаж", "замена персонаж", "подменить", "replace character"),
        anchors=("replace", "animate-replace", "character-replacement", "swap"),
        requires=(ARTEFACT_REFERENCE,),
        produces=(ARTEFACT_VIDEO,),
        requirement=(
            "персонаж заменён, цветокор и освещение сцены сохранены; "
            "replace character preserving lighting and colour"
        ),
    ),
    Operation(
        name="звук_фон",
        cues=("фоновые звук", "фоновый звук", "foley", "шумы", "звуковые эффект", "sfx"),
        anchors=("foley", "sound-effects", "sfx", "ambient-sound"),
        requires=(ARTEFACT_BRIEF,),
        produces=(ARTEFACT_NOISE,),
        requirement="фоновые звуки сцены; foley, sound effects, ambience",
    ),
    Operation(
        name="липсинк",
        cues=("липсинк", "lipsync", "губ", "синхрон", "говорит", "произносит", "читает текст"),
        anchors=("lipsync", "lip-sync", "липсинк", "lipsyncing", "talking-head", "lip-syncing"),
        requires=(ARTEFACT_VIDEO, ARTEFACT_AUDIO),
        produces=(ARTEFACT_LIPSYNCED,),
        requirement=(
            "губы держат синхрон всю реплику, лицо не плывёт; "
            "lipsync, lip sync accuracy, talking head"
        ),
    ),
)


@dataclass(frozen=True)
class Evidence:
    """Одна строка доказательства: ЧЕМ кандидат выбран.

    Четыре поля из требования владельца стоят здесь буквально — значение,
    ступень источника, дата и род свидетельства, — и пятое, `matched`, говорит,
    каким якорным словом эта строка вообще попала в подборку.
    """

    attribute: str
    value: str
    tier: str
    stated_on: str
    kind: str
    axis: str
    source_url: str
    matched: tuple[str, ...]


@dataclass(frozen=True)
class Candidate:
    """Одна модель, предложенная на шаг, и весь её счёт доказательств."""

    model: str
    evidence: tuple[Evidence, ...]
    applicability: int
    capability: int
    unresolved: int
    price: str
    #: Сколько утверждений о модели вообще зацепилось за якоря операции.
    #: Печатается и участвует в порядке: одна строка и одиннадцать строк — это
    #: разная степень, с какой база связывает модель с этой работой.
    anchored: int = 0
    #: Несёт ли САМО ИМЯ модели якорный термин (`wan-animate-replace`).
    #: Свидетельство слабое и потому стоит последним ключом порядка — но при
    #: прочих равных оно единственное непроизвольное: до него порядок решался
    #: алфавитом, и на замене персонажа алфавит поднимал `sdxl-lightning`
    #: (картиночная модель, зацепившаяся словом `replace` из куска кода) выше
    #: `wan-animate-replace`, у которой в базе записано «replaces the character
    #: in a reference video, keeping the scene». НАЙДЕНО ЧТЕНИЕМ ВЫДАЧИ,
    #: 2026-09-02 (П3).
    named: bool = False

    @property
    def measured(self) -> bool:
        """Есть ли хоть одна строка применимости. Это и есть развилка пометки."""
        return self.applicability > 0

    @property
    def mark(self) -> str:
        if self.measured:
            return f"применимость измерена: {self.applicability} строк(и)"
        return NOT_MEASURED_MARK


def _norm(text: str) -> str:
    return " ".join(str(text or "").split()).lower()


def derive(brief: str) -> list[Operation]:
    """Какие операции выводятся из брифа. Ни одной — честный ответ.

    Вынесено отдельной функцией из точки входа (Т5): это самая мутирующая
    развилка модуля, и она обязана быть достижима тестом без сборки плана,
    без базы фактов и без валидатора.

    Порядок возвращаемого — порядок `OPERATIONS`, а не порядок слов в брифе:
    план обязан идти от производителей артефактов к их потребителям, а
    заказчик перечисляет как придётся («сделай липсинк под мою озвучку»).
    """
    низ = _norm(brief)
    if not низ:
        return []
    return [op for op in OPERATIONS if any(cue in низ for cue in op.cues)]


def inputs_of(brief: str, creative: str = "") -> frozenset[str]:
    """Какие артефакты у заказчика УЖЕ ЕСТЬ, то есть являются входом плана.

    Развилка вынесена из точки входа (Т5) и решается двумя разными
    свидетельствами, из которых второе сильнее первого:

    * слова брифа («из готового ролика») — заказчик сказал;
    * поданный файл креатива с видеорасширением — заказчик показал.

    Возвращается множество артефактов, а не флаг: план подставит вместо них
    `референс`, который валидатор уже считает входом плана, и напечатает, ЧЕМ
    это решено. Молча укоротить `requires` было бы тем же, что спрятать разрыв.
    """
    есть: set[str] = set()
    if any(cue in _norm(brief) for cue in HAVE_VIDEO_CUES):
        есть.add(ARTEFACT_VIDEO)
    if creative and Path(creative).suffix.lower() in VIDEO_SUFFIXES:
        есть.add(ARTEFACT_VIDEO)
    return frozenset(есть)


def _is_model(name: str) -> bool:
    """Имя конкретной модели, а не области находки о классе."""
    return bool(name.strip()) and CLASS_NAME_MARKER not in name


def evidence_for(
    facts: Sequence[Fact],
    matched: Mapping[int, tuple[str, ...]],
    overrides: dict | None = None,
) -> tuple[list[Evidence], int, int, int]:
    """Строки доказательства с их родом по второй оси, и три счётчика.

    Род БЕРЁТСЯ у `studio/factaxis.py` и не выводится вторым способом (Е1);
    неразмеченная строка считается третьим числом, а не приписывается к
    способности «за компанию».
    """
    строки: list[Evidence] = []
    применимость = способность = не_смогли = 0
    for m in fa.mark_all(facts, overrides):
        ось = fa.axis(m.kind)
        if ось == fa.APPLICABILITY_HEADER:
            применимость += 1
        elif ось == fa.CAPABILITY_HEADER:
            способность += 1
        else:
            не_смогли += 1
        строки.append(
            Evidence(
                attribute=m.fact.attribute,
                value=m.fact.value,
                tier=m.fact.tier,
                stated_on=m.fact.stated_on,
                kind=m.kind,
                axis=ось,
                source_url=m.fact.source_url,
                matched=tuple(matched.get(id(m.fact), ())),
            )
        )
    return строки, применимость, способность, не_смогли


def cheapest_price(facts: Sequence[Fact]) -> str:
    """Самая дешёвая СРАВНИМАЯ цена модели, словами. Нет такой — так и сказано.

    Разбор цены не повторяется здесь ни строкой: и разборщик
    (`studio/pricing.py`), и правило сравнимости (`pipeline.comparable_prices`)
    уже есть, и оба пришли из измеренного дефекта — 45 ценовых строк из 82
    разбирались неверно, когда за число выдавали первое попавшееся.
    """
    сравнимые, прочие = pl.comparable_prices(facts)
    if not сравнимые:
        сколько = len(прочие)
        хвост = f" (несравнимых ценовых строк {сколько})" if сколько else ""
        return f"{NO_PRICE}{хвост}"
    _, дешёвая = min(сравнимые, key=lambda пара: пара[1].amount or 0.0)
    return f"{дешёвая.amount} {pl.BUDGET_UNIT} за {дешёвая.per}"


def by_evidence(c: Candidate) -> tuple:
    """Ключ порядка кандидатов, вынесенный из сортировки (Т5).

    Порядок ключей — это и есть решение модуля о том, что считать доводом, от
    сильного к слабому:

    1. сколько строк ПРИМЕНИМОСТИ: кто-то измерил или запустил. Одна такая
       строка обгоняет любое число вендорских — ради этого различия и заведена
       вторая ось;
    2. сколько утверждений вообще зацепилось за якоря операции: степень, с
       какой база связывает модель именно с этой работой;
    3. несёт ли имя модели якорный термин — слабое свидетельство, но
       непроизвольное, и оно решает ничью вместо алфавита;
    4. сколько строк способности;
    5. имя — чтобы порядок был воспроизводим.

    Цена названа вслух (И6): ключ 1 поднимает кандидата, о котором записано
    отрицательное наблюдение, выше кандидата, о котором не записано ничего.
    Это НЕ ошибка: валидатор увидит отрицательную применимость и скажет «не
    годно», назвав класс, — а «не смогли» на модели, о которой молчат, читатель
    не отличил бы от «годно». Молчание не лучше плохой новости, оно хуже.
    """
    return (-c.applicability, -c.anchored, -int(c.named), -c.capability, c.model)


def candidates_for(
    op: Operation,
    index: FactIndex,
    overrides: dict | None = None,
) -> list[Candidate]:
    """Кандидаты на операцию: модели, о которых база говорит СЛОВАМИ ОПЕРАЦИИ.

    Поиск здесь ровно один и он чужой (Е1): якоря подаются запросом в
    `studio.factindex.FactIndex`. Пол веса снят до нуля НАМЕРЕННО и это не
    ослабление отбора, а перенос его в другое место: запрос состоит ТОЛЬКО из
    якорных терминов, поэтому находится ровно то, что содержит якорь, и слово
    совпадения печатается у каждой строки доказательства. Порог, отделяющий
    случайное пересечение от настоящего, здесь не нужен — его работу делает
    словарь якорей, и он читается глазами, в отличие от числа.

    Пустой список — законный ответ и главная причина существования третьего
    исхода: `звук_фон` даёт его на живой базе.
    """
    попадания = index.search(" ".join(op.anchors), k=len(index.facts) or 1, floor=0.0)
    по_модели: dict[str, list] = {}
    слова: dict[int, tuple[str, ...]] = {}
    for hit in попадания:
        if not _is_model(hit.fact.model):
            continue
        по_модели.setdefault(hit.fact.model, []).append(hit.fact)
        слова[id(hit.fact)] = hit.matched

    найдены: list[Candidate] = []
    for имя, свои in по_модели.items():
        строки, применимость, способность, не_смогли = evidence_for(свои, слова, overrides)
        строки.sort(
            key=lambda e: (e.axis != fa.APPLICABILITY_HEADER, e.stated_on or "", e.attribute)
        )
        свёрнутое = имя.lower()
        найдены.append(
            Candidate(
                model=имя,
                evidence=tuple(строки[:EVIDENCE_SHOWN]),
                applicability=применимость,
                capability=способность,
                unresolved=не_смогли,
                price=cheapest_price(свои),
                anchored=len(свои),
                named=any(якорь.lower() in свёрнутое for якорь in op.anchors),
            )
        )
    найдены.sort(key=by_evidence)
    return найдены


def to_pipeline(
    name: str,
    chosen: Sequence[tuple[Operation, Candidate | None]],
    have: frozenset[str] = frozenset(),
    budget_usd: float | None = None,
    use: str = pl.USE_COMMERCIAL,
) -> pl.Pipeline:
    """Собрать `pipeline.Pipeline` из выбранного. Шаг без кандидата — с пустой моделью.

    Пустая модель не прячется: валидатор увидит `нет_модели` и скажет это сам.
    Подставить сюда что-нибудь «чтобы прошло» — ровно тот запрет, ради
    которого модуль и писался.

    Артефакт, который у заказчика УЖЕ ЕСТЬ, заменяется на `референс` — вход
    плана, который валидатор признаёт таковым. Замена печатается в плане.
    """
    шаги = []
    for op, кандидат in chosen:
        требует = tuple(ARTEFACT_REFERENCE if a in have else a for a in op.requires)
        шаги.append(
            pl.Step(
                name=op.name,
                model=кандидат.model if кандидат else "",
                requirement=op.requirement,
                requires=требует,
                produces=op.produces,
                budget_usd=budget_usd,
                use=use,
            )
        )
    return pl.Pipeline(name=name, steps=tuple(шаги))


def plan(
    brief: str,
    facts: Sequence[Fact] | None = None,
    *,
    creative: str = "",
    budget_usd: float | None = None,
    use: str = pl.USE_COMMERCIAL,
    today: date | None = None,
    overrides: dict | None = None,
    index: FactIndex | None = None,
) -> dict:
    """План из брифа, тут же прогнанный через валидатор-2.

    :param facts: база утверждений. Не задана — берётся живая
        (`studio/knowledge/model_facts.jsonl`), сети при этом нет.
    :param creative: путь к поданному креативу, если он есть. Здесь читается
        только РАСШИРЕНИЕ — разбор пикселей делает `studio/mcp/creative.py`, и
        второго разборщика тут не заводится.

    Числа Р2 печатаются рядом с исходом ВСЕГДА, в том числе на `годно`:
    сколько шагов выведено, у скольких есть кандидат, у скольких кандидат без
    единой строки применимости.
    """
    операции = derive(brief)
    if not операции:
        return {
            "outcome": UNMEASURED,
            "reason": REASON_NO_STEPS,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": (
                "ни одна из операций студии не выводится из этого брифа: "
                f"словарь знает {len(OPERATIONS)} операций, совпало 0. "
                "План не собирается — пустой шаг честнее выдуманного"
            ),
            "brief": brief,
            "steps": [],
            "classes": [],
            "validator": None,
        }

    индекс = index if index is not None else FactIndex(facts=facts) if facts else FactIndex()
    есть = inputs_of(brief, creative)

    выбор: list[tuple[Operation, Candidate | None]] = []
    строки_шагов: list[dict] = []
    без_кандидата = 0
    без_применимости = 0
    for op in операции:
        предложены = candidates_for(op, индекс, overrides)
        лучший = предложены[0] if предложены else None
        выбор.append((op, лучший))
        if лучший is None:
            без_кандидата += 1
        elif not лучший.measured:
            без_применимости += 1
        подменено = sorted(a for a in op.requires if a in есть)
        строки_шагов.append(
            {
                "step": op.name,
                "requirement": op.requirement,
                "anchors": list(op.anchors),
                "requires": list(op.requires),
                "produces": list(op.produces),
                "input_of_plan": подменено,
                "chosen": _candidate_row(лучший),
                "alternatives": [_candidate_row(c) for c in предложены[1:CANDIDATES_SHOWN]],
                "candidates_found": len(предложены),
            }
        )

    трубa = to_pipeline(brief.strip()[:80] or "план", выбор, есть, budget_usd, use)
    отчёт = pl.pipeline_report(трубa, list(индекс.facts), today, overrides)

    if без_кандидата:
        исход, причина = UNMEASURED, REASON_NO_CANDIDATES
        нота = (
            f"шагов выведено {len(операции)}, из них без единого кандидата {без_кандидата}: "
            "модель по умолчанию не подставляется"
        )
    elif отчёт["outcome"] == FAIL:
        исход, причина = FAIL, REASON_PLAN_REFUSED
        нота = f"валидатор-2 отверг план: {отчёт['note']}"
    elif отчёт["outcome"] == UNMEASURED:
        исход, причина = UNMEASURED, REASON_PLAN_UNCONFIRMED
        нота = f"валидатор-2 не смог подтвердить план: {отчёт['note']}"
    else:
        исход, причина = PASS, REASON_PLAN_STANDS
        нота = f"валидатор-2 не опроверг план: {отчёт['note']}"

    return {
        "outcome": исход,
        "reason": причина,
        "checked": отчёт["checked"],
        "violations": отчёт["violations"],
        "unmeasured": отчёт["unmeasured"] + без_кандидата,
        "note": (
            f"{нота}; шагов {len(операции)}, без кандидата {без_кандидата}, "
            f"кандидат без применимости {без_применимости}"
        ),
        "brief": brief,
        "steps": строки_шагов,
        "classes": list(отчёт["classes"]),
        "validator": отчёт,
    }


def _candidate_row(c: Candidate | None) -> dict | None:
    if c is None:
        return None
    return {
        "model": c.model,
        "mark": c.mark,
        "applicability": c.applicability,
        "capability": c.capability,
        "unresolved": c.unresolved,
        "price": c.price,
        "evidence": [
            {
                "attribute": e.attribute,
                "value": e.value,
                "tier": e.tier,
                "stated_on": e.stated_on,
                "kind": e.kind,
                "axis": e.axis,
                "source_url": e.source_url,
                "matched": list(e.matched),
            }
            for e in c.evidence
        ],
    }


def render(итог: dict) -> str:
    """Печать плана. Пометка о неизмеренной применимости — в строке модели.

    Она стоит там нарочно: читатель видит имя модели и решает по этой строке,
    а не по вложенному списку доказательств, до которого он может не дойти.
    """
    строки = [
        f"бриф: {итог['brief']}",
        (
            f"исход: {fa.OUTCOME_WORDS.get(итог['outcome'], итог['outcome'])} "
            f"[{итог['reason']}] — {итог['note']}"
        ),
        f"классы валидатора: {', '.join(итог['classes']) or 'ни один не сработал'}",
        (
            f"проверено {итог['checked']}, нарушений {итог['violations']}, "
            f"не смогли {итог['unmeasured']}"
        ),
    ]
    for s in итог["steps"]:
        выбран = s["chosen"]
        if выбран is None:
            строки.append(
                f"  шаг {s['step']}: КАНДИДАТА НЕТ — база молчит о якорях {', '.join(s['anchors'])}"
            )
            continue
        строки.append(f"  шаг {s['step']}: {выбран['model']} — {выбран['mark']}")
        строки.append(f"      цена: {выбран['price']}")
        if s["input_of_plan"]:
            строки.append(
                f"      вход плана (у заказчика уже есть): {', '.join(s['input_of_plan'])}"
            )
        for e in выбран["evidence"]:
            строки.append(
                f"      чем выбран: {e['attribute']}={e['value'][:70]} "
                f"[{e['tier']}, {e['stated_on'] or 'даты нет'}, {e['kind'] or 'род не выведен'}]"
                f" {e['source_url']}"
            )
        прочие = ", ".join(f"{a['model']} ({a['mark']})" for a in s["alternatives"])
        if прочие:
            строки.append(f"      ещё кандидаты ({s['candidates_found']} всего): {прочие}")
    return "\n".join(строки)


DEFAULT_BRIEFS_PATH = Path(__file__).with_name("fixtures") / "planner_briefs.jsonl"


def briefs(path: Path = DEFAULT_BRIEFS_PATH) -> list[dict]:
    """Контрольный набор брифов. Негодная строка ПРОПУСКАЕТСЯ и ловится гейтом.

    Форма взята у `pipeline.load_controls`: рядом живёт `rows_in`, и гейт
    сравнивает два числа, чтобы молча пропавший контроль был виден.
    """
    if not path.is_file():
        return []
    набор: list[dict] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or not row.get("id") or "brief" not in row:
            continue
        if row.get("expect_outcome") not in (PASS, FAIL, UNMEASURED):
            continue
        if row.get("expect_reason") not in REASONS:
            continue
        набор.append(row)
    return набор


def rows_in(path: Path = DEFAULT_BRIEFS_PATH) -> int:
    """Сколько строк данных в файле контроля, годных и негодных вместе."""
    if not path.is_file():
        return 0
    return sum(
        1
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("//")
    )
