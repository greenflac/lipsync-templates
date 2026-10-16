"""Вопрос о способности ПО ВСЕЙ БАЗЕ: «какой липсинк держит профиль?»

ЗАЧЕМ (валидатор 5-го круга, 2026-10-15). `model_advice` отвечает о ОДНОЙ
модели, а вопрос заказчика часто о работе: «which lipsync handles profile
faces», «which i2v keeps logos legible», «best open TTS for Russian».
Вызывающая модель угадывала кандидатов по памяти и спрашивала базу о них, и
записанное о других не всплывало никогда.

ШЕСТОЙ КРУГ (2026-10-15, валидатор v5, 14 вопросов `find_models`). Первая
версия держала СВОЙ список из девяти «функций» с регулярками по имени и
описанию и выводила ЗНАК строки по словарю слов. Обе вещи врали:

* `bria-video-background-removal-v3` считался липсинком — в его описании стоит
  «talking heads»;
* «Non-commercial use ONLY» шло хорошей новостью на «music for commercial
  use», «may yield suboptimal results» — хорошей (слова из списка плохих там
  нет), цены — хорошей новостью о способности;
* «best open Russian TTS» называло Silero, F5-RU и Chatterbox пробелами: их
  лицензия CC BY-NC — открытые веса, но не из списка «apache/mit»;
* `minimax-h3` с `fps = "24"` выигрывал «интерполяцию до 60/120 fps» —
  присутствием слова, а не значением.

ЧТО ТЕПЕРЬ.

1. ОБЛАСТЬ — работы реестра (`studio/endpoints.py`, `build().by_function`, 22
   работы). `function` принимает любую работу реестра и её слова
   (`endpoints.JOB_WORDS`, словарь владеет реестр); широкое слово («video»)
   уточняется работой, названной в самом вопросе. Своего списка здесь нет.
2. ЗНАК СТРОКИ — только ОБЪЯВЛЕННЫЙ (`знак`): поле `contra` записи, имя
   атрибута из `factaxis.CONTRA_ATTRIBUTES` (только «плохо»), или значение,
   прочитанное ПО АТРИБУТУ против ограничения вопроса (язык в списке языков,
   лицензия против заявленного применения, предел длительности и частоты
   кадров числом). Строка без объявленного знака — «информация», НИКОГДА не
   хорошая новость. Цена — никогда не свидетельство способности.
3. УСЛОВИЯ («профиль», «логотип читается», «руки») — через
   `attrfamily.УСЛОВИЯ`: имена атрибутов (`pose_range`, `text_rendering`),
   бенчмарк условия (`VTR-Bench`, число читается со своей единицей) и строки
   о провале, назвавшие то же условие (`pipeline.themes_in`). Тем же правилом
   (`condition_state`) плановщик отодвигает кандидата с плохой новостью на
   заявленном условии (Е1: правило одно).

ПОРЯДОК (без числовых весов — та же доктрина, что у базы):

    0. только хорошая новость
    1. только информация (знака никто не объявил)
    2. и хорошая, и плохая
    3. только плохая

Плохая новость ниже молчания — это правило ЗАЯВЛЕННОГО УСЛОВИЯ: модель, о
которой записан провал на профиле, хуже модели, о которой не записано ничего
(валидатор w19). Внутри ступени — подтверждённые требования, ступень
источника хорошей новости, число бенчмарка, источники, свежесть.

ЧЕСТНЫЕ ПРОБЕЛЫ (Р1). Модели области, о которых по вопросу не записано
ничего, считаются и называются (`gaps`). Ноль моделей с хорошей новостью —
`could not measure`, а не `pass`. Находки о КЛАССЕ (`*`, `vendor-*`) —
отдельным списком.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Sequence
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio import brief_spec as bs
from studio import endpoints as ep
from studio import factaxis as fa
from studio import hardneed as hn
from studio import l10n
from studio import pipeline as pl
from studio.selfrag import attrfamily
from studio.selfrag.facts import TIERS, Fact
from studio.selfrag.modelnames import fold

# --- знак строки -----------------------------------------------------------------

GOOD = "good"
BAD = "bad"
INFO = "informational"

#: Откуда знак: объявлен записью (`contra`), объявлен именем атрибута
#: (`CONTRA_ATTRIBUTES` — только плохое), прочитан по атрибуту против
#: ограничения вопроса, или не объявлен вовсе.
POLARITY_DECLARED = "declared"
POLARITY_ATTRIBUTE = "attribute"
POLARITY_CONSTRAINT = "constraint"
POLARITY_NONE = "none"

#: Ступени модели в выдаче (меньше — выше). КОНСТАНТА-РЕШЕНИЕ: «только
#: информация» ВЫШЕ «и хорошая, и плохая» — плохая новость на заявленном
#: условии отодвигает модель ниже молчания (валидатор w19, см. док-строку).
VERDICT_ORDER: dict[str, int] = {
    "good_news_only": 0,
    "informational_only": 1,
    "mixed": 2,
    "bad_news_only": 3,
}

#: Бенчмарки условий: имя (нижний регистр) -> (образец числа, имя метрики,
#: меньше ли — лучше). Число читается со СВОЕЙ единицей, а не присутствием.
BENCHMARK_METRICS: dict[str, tuple[str, str, bool]] = {
    "vtr-bench": (r"\bwer\s*([0-9]*\.?[0-9]+)", "WER", True),
}


#: КОДЫ ЯЗЫКОВ, которыми пишут СПИСКИ языков (`ar, da, de, …, ru`), — у
#: нормализатора BCP-47 плановщика (`brief_spec.CODE_TO_LANGUAGE` и
#: `EXTRA_LANGUAGE_FORMS`), а не своим списком (Е1). Седьмой круг (валидатор
#: v7, f07/f10): здесь жил свой словарь из 18 кодов, и `kk`, `kazakh`, `he`,
#: `hebrew` уходили в `require_not_understood` — плановщик те же теги
#: принимал. Читаются только в строке-списке (`LANGUAGE_LIST_MIN` кодов через
#: запятую): «it» в английской фразе — местоимение, а не итальянский.
def _коды_языков() -> frozenset[str]:
    return frozenset(bs.CODE_TO_LANGUAGE) | frozenset(bs.EXTRA_LANGUAGE_FORMS)


def язык_слова(слово: str) -> str:
    """Язык, названный словом вопроса: имя базы («russian») или тег BCP-47 («kk»).

    Пусто — не язык. Порядок: имена базы (`pipeline.languages_in`, рус. и
    англ.), формы вне словаря базы (`brief_spec.languages_in_text`), тег или
    имя через `brief_spec.language_tag`. Язык вне словаря базы остаётся ТЕГОМ:
    о нём ничего не записано, и это «не измерено», а не «не понято».
    """
    низ = _норм(слово)
    if not низ:
        return ""
    имена = sorted(pl.languages_in(низ))
    if имена:
        return имена[0]
    теги = bs.languages_in_text(низ)
    if теги:
        return bs.language_name(теги[0])
    тег = bs.language_tag(низ)
    if not тег:
        return ""
    имя = bs.language_name(тег)
    # Язык вне словаря базы — ПЕРВИЧНЫЙ подтег: «kk-KZ» ищется как «kk».
    return имя if имя != тег else тег.split("-")[0].lower()


LANGUAGE_LIST_MIN = 3

#: Сколько свидетельств показывать у модели (счёт печатается целиком).
СВИДЕТЕЛЬСТВ_ПОКАЗАНО = 3
#: Сколько моделей без свидетельства назвать поимённо (счёт — целиком).
ПРОБЕЛОВ_ПОКАЗАНО = 12

#: Слова вопроса, не несущие смысла поиска.
_ПУСТЫЕ = frozenset(
    {
        "which",
        "what",
        "best",
        "the",
        "a",
        "an",
        "for",
        "of",
        "and",
        "or",
        "with",
        "that",
        "is",
        "does",
        "do",
        "can",
        "model",
        "models",
        "handles",
        "handle",
        "keeps",
        "keep",
        "good",
        "without",
        "renders",
        "render",
        "use",
        "one",
        "many",
        "across",
        "from",
        "into",
        "to",
        "какой",
        "какая",
        "какие",
        "лучший",
        "лучшая",
        "лучше",
        "всего",
        "для",
        "и",
        "с",
        "что",
        "модель",
        "модели",
        "держит",
        "faces",
        "face",
        "лицо",
        "лица",
        "open",
        "weights",
        "commercial",
        "cheap",
        "cheapest",
        "no",
        "not",
        "extra",
    }
)

#: ТРЕБОВАНИЯ — фильтр, а не ранжирование: нарушенное убирает модель с
#: причиной, подтверждённое — хорошая новость, незаписанное — названо.
REQ_OPEN = "open"
REQ_COMMERCIAL = "commercial"
#: Написания требований -> ключ (языки — отдельно, по `pipeline.LANGUAGE_FORMS`).
ТРЕБОВАНИЯ_СИНОНИМЫ: dict[str, str] = {
    "open": REQ_OPEN,
    "open weights": REQ_OPEN,
    "open-weights": REQ_OPEN,
    "open source": REQ_OPEN,
    "open-source": REQ_OPEN,
    "открытые веса": REQ_OPEN,
    "открытая": REQ_OPEN,
    "commercial": REQ_COMMERCIAL,
    "commercial use": REQ_COMMERCIAL,
    "коммерческое": REQ_COMMERCIAL,
    "коммерция": REQ_COMMERCIAL,
}
#: Требования, при которых НЕЗАПИСАННОЕ отсеивает, а не ранжирует ниже.
#: КОНСТАНТА-РЕШЕНИЕ (седьмой круг, валидатор v7 f18): «open» без записи о
#: весах — не «прошла», а «неизвестно»; такая модель в выдаче выглядела
#: открытой. Отсеянные по незаписанному названы списком `excluded_unknown`.
REQUIRE_RECORDED: frozenset[str] = frozenset({REQ_OPEN})
_ОТКРЫТО_В_ВОПРОСЕ = re.compile(r"\bopen[- ]?(?:weights?|source)\b|\bopen\b|открыт", re.I)
_КОММЕРЦИЯ_В_ВОПРОСЕ = re.compile(r"(?<!non-)(?<!non )\bcommercial|коммерч", re.I)


def _норм(текст: object) -> str:
    return " ".join(str(текст or "").lower().split())


def _фраза_в(фраза: str, текст: str) -> bool:
    """Фраза целиком (по границе слова) в тексте."""
    ф = _норм(фраза)
    # Русская фраза — основой: «удаление объект» ловит «удаление объектов».
    хвост = r"\w*" if re.search(r"[а-яё]$", ф) else ""
    return (
        bool(ф) and re.search(rf"(?<![\w-]){re.escape(ф)}{хвост}(?![\w])", _норм(текст)) is not None
    )


# --- возможности, правки, память, кадры (седьмой круг) ------------------------------

#: ВОЗМОЖНОСТЬ, спрошенная фразой: (фразы вопроса, атрибуты, где она записана,
#: образец «да», образец «нет»). Седьмой круг (валидатор v7, f05): на «t2v с
#: нативным звуком» строки `audio_output` Veo и Kling («native audio switch:
#: schema field generate_audio (default true)») шли «информацией», и ответ
#: был `could not measure`. Значение читается ПО АТРИБУТУ против спрошенного,
#: как язык и длительность. Это СПОСОБНОСТЬ по схеме или странице вендора, а
#: не применимость — так и подписывается (`why`).
CAP_NATIVE_AUDIO = "native_audio"
ВОЗМОЖНОСТИ: dict[str, dict] = {
    CAP_NATIVE_AUDIO: {
        "фразы": (
            "native audio",
            "native sound",
            "generates audio",
            "generate audio",
            "audio generation",
            "with audio",
            "synced audio",
            "synchronized audio",
            "joint audio",
            "нативный звук",
            "нативным звуком",
            "со звуком",
            "генерирует звук",
        ),
        "атрибуты": ("audio_output", "native_audio", "generate_audio", "audio_generation"),
        "нет": r"^\s*(?:no|none|false|нет)\b|\bno (?:native )?audio\b|without audio|silent only|без звука",
        "да": r"native audio|generate_audio|joint audio|synchroni[sz]ed audio|audio track|audio on\b"
        r"|with audio|audio\+video|^\s*(?:yes|true|да)\b",
    },
}

#: ПРАВКА ВИДЕО, спрошенная фразой -> под-работа реестра (`endpoints.EDIT_INTENTS`).
#: Свидетельство — ИДЕНТИФИКАТОР эндпоинта, НАЗВАВШИЙ правку
#: (`endpoints.edit_named`: `fal-ai/ltx-2.3-quality/clean-plate`): это каталог
#: и схема, то есть СПОСОБНОСТЬ, а не применимость (валидатор v7, f16).
ПРАВКИ_В_ВОПРОСЕ: dict[str, tuple[str, ...]] = {
    ep.EDIT_REMOVE_OBJECT: (
        "object removal",
        "remove object",
        "remove objects",
        "remove an object",
        "remove the object",
        "inpainting",
        "inpaint",
        "clean plate",
        "clean-plate",
        "удаление объект",
        "удалить объект",
        "убрать объект",
    ),
    ep.EDIT_REPLACE_SKY: ("sky replacement", "replace the sky", "replace sky", "замена неба"),
    ep.EDIT_RELIGHT: ("relight", "relighting", "переосвещ", "underexposed", "exposure fix"),
    ep.EDIT_DAY_TO_NIGHT: ("day to night", "day-to-night", "night to day", "день в ночь"),
    ep.EDIT_STABILISE: ("stabilise", "stabilize", "stabilization", "stabilisation", "стабилиз"),
    ep.EDIT_REFRAME: ("reframe", "reframing", "outpaint", "outpainting"),
}
POLARITY_CATALOG = "catalog"

#: Слова, при которых число ГБ в вопросе — ПАМЯТЬ GPU, а не размер файла.
_ПАМЯТЬ_КОНТЕКСТ = re.compile(
    r"vram|gpu|видеопамят|видеокарт|graphics card|\bcard\b|runs? on|run it on|запуска|памят", re.I
)
_ГБ = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:gb|гб|gib)\b", re.I)
_GPU = re.compile(r"\b(rtx\s*a?\s*\d{4}|l40s|l4|a100|h100|h200)\b", re.I)


def _память(текст: str, *, требование: bool = False) -> float | None:
    """Память GPU, названная текстом, ГБ: «12GB VRAM», «RTX 3060»; None — не названа.

    В тексте вопроса ГБ читаются только рядом со словами о памяти или запуске
    (`_ПАМЯТЬ_КОНТЕКСТ`); в `require` («12gb», «vram 12») — всегда.
    """
    низ = _норм(текст)
    м = _ГБ.search(низ)
    if м and (требование or _ПАМЯТЬ_КОНТЕКСТ.search(низ)):
        return float(м.group(1))
    if требование:
        м = re.fullmatch(r"vram\s*[:=<]*\s*(\d{1,3}(?:\.\d+)?)", низ)
        if м:
            return float(м.group(1))
    g = _GPU.search(низ)
    if g:
        return hn.GPU_VRAM_GB.get(hn.gpu_key(g.group(1)))
    return None


#: Частота ИСХОДНОГО ролика, если вопрос её назвал («from 24 to 120 fps»,
#: «30fps footage to 120»): меньшее из двух чисел fps. Множитель интерполяции
#: (`frame_multiplier`) судится только против неё; не названа — информация с
#: порогом, а не выдуманный исходник.
def _исходные_кадры(текст: str) -> float | None:
    числа = [float(ч) for ч in re.findall(r"(\d{2,3})\s*(?:fps|к/с|кадр)", текст)]
    м = re.search(r"(?:from|с|из)\s+(\d{2,3})\s*(?:fps)?\s*(?:to|до|в|->|→)\s*(\d{2,3})", текст)
    if м:
        return float(м.group(1))
    if len(set(числа)) >= 2:
        return min(числа)
    return None


#: Атрибут МНОЖИТЕЛЯ частоты (интерполяция: «up to 4x input fps»).
FRAME_MULTIPLIER_ATTRIBUTE = "frame_multiplier"


# --- вопрос ----------------------------------------------------------------------


class Вопрос:
    """Разобранный вопрос: семьи атрибутов, условия, слова, требования, числа."""

    def __init__(self, need: str, terms: str, require: str, conditions: Iterable[str] = ()) -> None:
        self.need = str(need or "")
        сырые = [т.strip().lower() for т in re.split(r"[,;]", terms or "") if т.strip()]
        #: Слова взяты из `need` (а не названы `terms`): тогда свободное слово
        #: ищется, только если вопрос не понят ни семьёй, ни условием, ни
        #: требованием — иначе «речи» из «для русской речи» тянуло бы в ответ
        #: любую строку, где стоит слово «речь».
        из_вопроса = not сырые
        if из_вопроса:
            сырые = [
                с
                for с in re.findall(r"[\w-]{3,}", _норм(need))
                if с not in _ПУСТЫЕ and not pl.languages_in(с)
            ]
        текст = _норм(f"{need} {terms}")
        self.семьи: list[str] = []
        self.условия: list[str] = []
        self.слова: list[str] = []
        self.цена_спрошена = False
        # Условия, названные фразой, — по всему тексту вопроса.
        for фраза in attrfamily.УСЛОВИЯ_СИНОНИМЫ:
            if " " in фраза and re.search(rf"(?<!\w){re.escape(фраза)}(?!\w)", текст):
                у = attrfamily.условие(фраза)
                if у not in self.условия:
                    self.условия.append(у)
        #: Возможности (`ВОЗМОЖНОСТИ`) и правки (`ПРАВКИ_В_ВОПРОСЕ`), названные фразой.
        self.возможности: list[str] = [
            к
            for к, правило in ВОЗМОЖНОСТИ.items()
            if any(_фраза_в(ф, текст) for ф in правило["фразы"])
        ]
        self.правки: list[str] = [
            п for п, фразы in ПРАВКИ_В_ВОПРОСЕ.items() if any(_фраза_в(ф, текст) for ф in фразы)
        ]
        занято = [ф for к in self.возможности for ф in ВОЗМОЖНОСТИ[к]["фразы"]] + [
            ф for п in self.правки for ф in ПРАВКИ_В_ВОПРОСЕ[п]
        ]
        for т in [*сырые, *[str(c) for c in conditions]]:
            if _память(текст) is not None and (
                _память(т, требование=True) is not None or т == "vram"
            ):
                # Память понята числом (`Вопрос.память`), в строках не ищется.
                continue
            if any(_фраза_в(ф, т) or _фраза_в(т, ф) for ф in занято):
                # Слово уже понято возможностью или правкой — в строках не ищется.
                continue
            у = attrfamily.условие(т)
            if у:
                if у not in self.условия:
                    self.условия.append(у)
                continue
            if ep.job_words(т) and т not in ("song",):
                # Слово РАБОТЫ («lipsync», «interpolation») задаёт область, а не
                # ищется в строках: иначе каждая строка о липсинке — «довод».
                continue
            с = attrfamily.семья(т)
            if с == "price" or т in ("cheap", "cheapest", "дешёвый", "дешево"):
                self.цена_спрошена = True
                continue
            if с:
                if с not in self.семьи:
                    self.семьи.append(с)
                continue
            if т not in _ПУСТЫЕ and т not in self.слова:
                self.слова.append(т)
        # Требования: из `require` и из самого вопроса.
        self.требования: list[str] = []
        self.языки: list[str] = []
        self.непонятые: list[str] = []
        #: Память GPU, названная вопросом («runs on 12GB», «RTX 3060»), ГБ.
        self.память: float | None = _память(текст)
        for сырое in re.split(r"[,;]", require or ""):
            слово = сырое.strip().lower()
            if not слово:
                continue
            ключ = ТРЕБОВАНИЯ_СИНОНИМЫ.get(слово)
            язык = "" if ключ else язык_слова(слово)
            память = _память(слово, требование=True)
            if ключ:
                self._требование(ключ)
            elif память is not None:
                self.память = память
            elif язык:
                if язык not in self.языки:
                    self.языки.append(язык)
            else:
                self.непонятые.append(слово)
        if _КОММЕРЦИЯ_В_ВОПРОСЕ.search(текст) and not re.search(r"non-?commercial", текст):
            self._требование(REQ_COMMERCIAL)
        if _ОТКРЫТО_В_ВОПРОСЕ.search(_норм(need)):
            self._требование(REQ_OPEN)
        for язык in [
            *sorted(pl.languages_in(текст)),
            *[bs.language_name(т) for т in bs.languages_in_text(текст)],
        ]:
            if язык not in self.языки:
                self.языки.append(язык)
        if self.память is not None and "hardware" not in self.семьи:
            self.семьи.append("hardware")
        if self.языки and "languages" not in self.семьи:
            self.семьи.append("languages")
        # Числа со своими единицами. Длительность — ограничение, только когда
        # вопрос спрашивает о ДЛИНЕ прогона (семья `max_seconds` названа: «long»,
        # «duration», «in one go»): в «cheapest 1 minute of 1080p» минута —
        # сколько купить, а не предел модели.
        if re.search(
            r"in one (?:go|run|take)|single (?:run|take|generation)|за один|без склейки", текст
        ):
            if "max_seconds" not in self.семьи:
                self.семьи.append("max_seconds")
        self.секунды = _секунды(текст) if "max_seconds" in self.семьи else None
        self.кадров = _кадров(текст)
        if self.кадров is not None and "frame_rate" not in self.семьи:
            self.семьи.append("frame_rate")
        self.исходные_кадры = _исходные_кадры(текст)
        if из_вопроса and (
            self.семьи
            or self.условия
            or self.требования
            or self.языки
            or self.возможности
            or self.правки
        ):
            self.слова = []

    def _требование(self, ключ: str) -> None:
        if ключ not in self.требования:
            self.требования.append(ключ)

    @property
    def пусто(self) -> bool:
        return not (
            self.семьи
            or self.условия
            or self.слова
            or self.требования
            or self.языки
            or self.возможности
            or self.правки
        )

    @property
    def только_требования(self) -> bool:
        """Спрошены ли ТОЛЬКО требования (веса, лицензия, язык) — без предмета.

        Тогда подтверждённое требование и есть ответ («open-weights background
        removal»). Если предмет есть (память, звук, условие, длина), лицензия —
        фильтр, а не довод: валидатор v7, f18 — «i2v на 12GB» ранжировался
        лицензией, а память не читалась вовсе.
        """
        предмет = [с for с in self.семьи if с not in ("languages", "license")]
        return not (предмет or self.условия or self.слова or self.возможности or self.правки)

    def описание(self) -> list[str]:
        return [
            *[f"family:{с}" for с in self.семьи],
            *[f"condition:{у}" for у in self.условия],
            *[f"capability:{к}" for к in self.возможности],
            *[f"edit:{п}" for п in self.правки],
            *([f"vram<={self.память:g}GB"] if self.память is not None else []),
            *self.слова,
        ]


def _секунды(текст: str) -> float | None:
    """Длительность, названная вопросом («5 minutes», «90 s»); None — не названа."""
    лучшее: float | None = None
    for м in re.finditer(
        r"(\d+(?:\.\d+)?)\s*(minutes?|mins?|минут\w*|мин|seconds?|secs?|s|сек\w*|с)(?![\w])", текст
    ):
        число = float(м.group(1))
        секунд = число * 60 if м.group(2).startswith(("min", "мин")) else число
        лучшее = секунд if лучшее is None else max(лучшее, секунд)
    return лучшее


def секунд_в_строке(атрибут: str, значение: str) -> float | None:
    """Предел длительности из ОДНОЙ строки семьи `max_seconds`, в секундах.

    Числа с единицей старше голого числа; голое — только диапазон («2 to 15»)
    или число В НАЧАЛЕ значения (имя атрибута уже назвало единицу). НАЙДЕНО
    2026-10-15: общий разборщик читал «5 exactly, … MP4 H.264» как 264 с —
    кодек становился пределом модели.
    """
    низ = _норм(значение)
    множитель = 0.001 if атрибут.endswith("_ms") else 1.0
    с_единицей = [
        float(м.group(1)) * (60.0 if м.group(2).startswith(("min", "мин")) else 1.0)
        for м in re.finditer(
            r"(\d+(?:\.\d+)?)\s*(minutes?|mins?|минут\w*|seconds?|secs?|s|сек\w*)(?![\w.])", низ
        )
    ]
    if с_единицей:
        return max(с_единицей)
    диапазон = re.search(r"(\d+(?:\.\d+)?)\s*(?:to|-|–|до)\s*(\d+(?:\.\d+)?)", низ)
    if диапазон:
        return float(диапазон.group(2)) * множитель
    начало = re.match(r"\s*(\d+(?:\.\d+)?)(?![\w.])", низ)
    if начало:
        return float(начало.group(1)) * множитель
    return None


def _кадров(текст: str) -> float | None:
    """Частота кадров, названная вопросом («60/120 fps»): наибольшая; None — нет."""
    м = re.search(r"((?:\d+\s*/\s*)*\d+)\s*fps", текст)
    if not м:
        return None
    return max(float(ч) for ч in re.findall(r"\d+", м.group(1)))


# --- знак ------------------------------------------------------------------------


def _языки_строки(значение: str) -> frozenset[str]:
    """Языки, которые строка НАЗЫВАЕТ: имена и (в строке-списке) коды BCP-47.

    Имена — словарь базы и формы вне его (`brief_spec.languages_in_text`:
    «Kazakh», «Hebrew»); коды — у нормализатора BCP-47 (`_коды_языков`).
    """
    низ = _норм(значение)
    имена = set(pl.languages_in(низ)) | {bs.language_name(т) for т in bs.languages_in_text(низ)}
    коды = re.findall(r"(?<![\w-])([a-z]{2,3})(?:-[a-z]{2})?(?![\w-])", низ)
    известные = _коды_языков()
    if sum(1 for к in коды if к in известные) >= LANGUAGE_LIST_MIN or re.search(
        r"\(\s*[a-z]{2}\s*\)", низ
    ):
        имена |= {bs.language_name(к) for к in коды if к in известные}
    return frozenset(имена)


def _fps_строки(значение: str, атрибут: str) -> list[float]:
    низ = _норм(значение)
    числа = [float(ч) for ч in re.findall(r"(\d+(?:\.\d+)?)\s*fps", низ)]
    if (
        not числа
        and attrfamily.семья_имени(атрибут) == "frame_rate"
        and атрибут in ("fps", "frame_rate")
    ):
        числа = [float(ч) for ч in re.findall(r"\d+(?:\.\d+)?", низ)]
    return числа


def знак(f: Fact, вопрос: Вопрос | None = None) -> tuple[str, str, str]:
    """(знак, откуда знак, почему). Строка без объявленного знака — информация.

    Порядок — от объявленного к прочитанному: поле `contra` записи старше всего
    (Е2, как в `factaxis.is_contra`); имя атрибута о провале объявляет ТОЛЬКО
    плохое; значение читается по АТРИБУТУ и только против ограничения, которое
    вопрос назвал (язык, длительность, частота кадров). Цена не свидетельство.
    """
    if f.contra is not None:
        return (BAD if f.contra else GOOD), POLARITY_DECLARED, "polarity declared with the record"
    if fa.is_contra(f):
        return BAD, POLARITY_ATTRIBUTE, f"attribute {f.attribute} records where it breaks"
    семья = attrfamily.семья_имени(f.attribute)
    if семья == "price":
        return INFO, POLARITY_NONE, "price is not evidence of capability"
    if вопрос is not None:
        for к in вопрос.возможности:
            правило = ВОЗМОЖНОСТИ[к]
            if f.attribute in правило["атрибуты"]:
                низ = _норм(f.value)
                if re.search(правило["нет"], низ):
                    return BAD, POLARITY_CONSTRAINT, f"{f.attribute} says no {к}"
                if re.search(правило["да"], низ):
                    return (
                        GOOD,
                        POLARITY_CONSTRAINT,
                        f"{f.attribute} records {к} ({f.tier}) — capability by schema/vendor, "
                        "not measured applicability",
                    )
        if f.attribute == FRAME_MULTIPLIER_ATTRIBUTE and вопрос.кадров is not None:
            м = re.search(r"(\d+(?:\.\d+)?)\s*[x×]", _норм(f.value))
            if м:
                множитель = float(м.group(1))
                if вопрос.исходные_кадры is not None:
                    итог = вопрос.исходные_кадры * множитель
                    if итог >= вопрос.кадров:
                        return (
                            GOOD,
                            POLARITY_CONSTRAINT,
                            f"x{множитель:g} of {вопрос.исходные_кадры:g} fps = {итог:g} fps >= asked {вопрос.кадров:g}",
                        )
                    return (
                        BAD,
                        POLARITY_CONSTRAINT,
                        f"x{множитель:g} of {вопрос.исходные_кадры:g} fps = {итог:g} fps < asked {вопрос.кадров:g}",
                    )
                return (
                    INFO,
                    POLARITY_NONE,
                    f"x{множитель:g} of the source: reaches {вопрос.кадров:g} fps only from a source of "
                    f">= {вопрос.кадров / множитель:g} fps — name the source fps to check",
                )
        if семья == "languages" and вопрос.языки:
            есть = _языки_строки(f.value)
            нужные = [я for я in вопрос.языки if я in есть]
            if нужные:
                return GOOD, POLARITY_CONSTRAINT, f"languages list {', '.join(нужные)}"
            if есть and pl.exclusive_language(f.value):
                return (
                    BAD,
                    POLARITY_CONSTRAINT,
                    f"exclusive language list without {', '.join(вопрос.языки)}",
                )
        if семья == "max_seconds" and вопрос.секунды is not None:
            предел = секунд_в_строке(f.attribute, f.value)
            if предел is not None:
                if предел >= вопрос.секунды:
                    return (
                        GOOD,
                        POLARITY_CONSTRAINT,
                        f"limit {предел:g} s >= asked {вопрос.секунды:g} s",
                    )
                return BAD, POLARITY_CONSTRAINT, f"limit {предел:g} s < asked {вопрос.секунды:g} s"
        if семья == "frame_rate" and вопрос.кадров is not None:
            числа = _fps_строки(f.value, f.attribute)
            if числа:
                if max(числа) >= вопрос.кадров:
                    return (
                        GOOD,
                        POLARITY_CONSTRAINT,
                        f"{max(числа):g} fps >= asked {вопрос.кадров:g}",
                    )
                return BAD, POLARITY_CONSTRAINT, f"{max(числа):g} fps < asked {вопрос.кадров:g}"
    return INFO, POLARITY_NONE, "no polarity declared"


def _метрика(f: Fact, условия: Sequence[str]) -> tuple[str, float, str, bool] | None:
    """(бенчмарк, число, метрика, меньше-лучше), если строка — бенчмарк условия."""
    низ = _норм(f.value)
    for у in условия:
        for имя in attrfamily.УСЛОВИЯ.get(у, {}).get("бенчмарки", ()):
            if имя in низ and имя in BENCHMARK_METRICS:
                образец, метрика, меньше = BENCHMARK_METRICS[имя]
                м = re.search(образец, низ)
                if м:
                    return имя, float(м.group(1)), метрика, меньше
    return None


def _об_условии(f: Fact, у: str) -> bool:
    """Говорит ли строка об условии: именем атрибута, бенчмарком или провалом при нём."""
    if attrfamily.об_условии(у, f.attribute):
        return True
    правило = attrfamily.УСЛОВИЯ.get(у, {})
    низ = _норм(f.value)
    if any(б in низ for б in правило.get("бенчмарки", ())):
        return True
    # Строка с ОБЪЯВЛЕННЫМ знаком (провал по имени атрибута или поле `contra`)
    # относится к условию, если называет его тему — тем же правилом, каким
    # валидатор узнаёт «провал при другом условии» (`pipeline.themes_in`).
    if f.contra is not None or fa.is_contra(f):
        return правило.get("тема", "") in pl.themes_in(f"{f.attribute} {f.value}")
    return False


def _относится(f: Fact, вопрос: Вопрос) -> bool:
    if attrfamily.семья_имени(f.attribute) == "price":
        return False
    if any(f.attribute in ВОЗМОЖНОСТИ[к]["атрибуты"] for к in вопрос.возможности):
        return True
    if f.attribute == FRAME_MULTIPLIER_ATTRIBUTE and "frame_rate" in вопрос.семьи:
        return True
    if attrfamily.семья_имени(f.attribute) in вопрос.семьи:
        return True
    if any(_об_условии(f, у) for у in вопрос.условия):
        return True
    текст = f"{f.attribute} {f.value}".lower()
    return any(с in текст for с in вопрос.слова)


def condition_state(rows: Sequence[Fact], условия: Sequence[str]) -> tuple[int, str, list[dict]]:
    """Свидетельство модели по ЗАЯВЛЕННЫМ условиям: (ступень, нота, строки).

    Ступени `CONDITION_POSITIVE` < `CONDITION_UNKNOWN` < `CONDITION_NEGATIVE`:
    хоть одна плохая новость на заявленном условии — отрицательно (она не
    перевешивается похвалой вендора); иначе хоть одна хорошая — за; иначе не
    записано. Зовут это `find` и плановщик (Е1).
    """
    if not условия:
        return CONDITION_UNKNOWN, "", []
    за: list[tuple[str, Fact, str]] = []
    против: list[tuple[str, Fact, str]] = []
    for f in rows:
        for у in условия:
            if not _об_условии(f, у):
                continue
            з, откуда, _ = знак(f)
            if з == GOOD:
                за.append((у, f, откуда))
            elif з == BAD:
                против.append((у, f, откуда))
    if против:
        у, f, _ = sorted(против, key=lambda t: _ступень(t[1]))[0]
        return (
            CONDITION_NEGATIVE,
            f"against — {у}: {f.attribute} = «{_коротко(f.value, 120)}» ({f.tier}, {f.source_url})",
            [_строка(ф, BAD, о) for _, ф, о in против],
        )
    if за:
        у, f, _ = sorted(за, key=lambda t: _ступень(t[1]))[0]
        return (
            CONDITION_POSITIVE,
            f"for — {у}: {f.attribute} = «{_коротко(f.value, 120)}» ({f.tier}, {f.source_url})",
            [_строка(ф, GOOD, о) for _, ф, о in за],
        )
    return CONDITION_UNKNOWN, f"nothing recorded on {', '.join(условия)}", []


#: Ступени по заявленному условию. КОНСТАНТЫ-РЕШЕНИЯ: «не записано» — между
#: «за» и «против» (плохая новость хуже молчания на ЗАЯВЛЕННОМ условии).
CONDITION_POSITIVE = 0
CONDITION_UNKNOWN = 1
CONDITION_NEGATIVE = 2


def conditions_of(terms: Iterable[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """Свободные слова условий -> (условия `attrfamily.УСЛОВИЯ`, непонятые слова)."""
    понятые: list[str] = []
    непонятые: list[str] = []
    for т in terms:
        у = attrfamily.условие(str(т))
        if у:
            if у not in понятые:
                понятые.append(у)
            continue
        # Фраза («side-profile actor shot») — по составляющим синонимам.
        найдено = [
            attrfamily.условие(ф)
            for ф in attrfamily.УСЛОВИЯ_СИНОНИМЫ
            if re.search(rf"(?<![\w-]){re.escape(ф)}(?![\w])", _норм(т))
        ]
        if найдено:
            for у in найдено:
                if у not in понятые:
                    понятые.append(у)
        elif str(т).strip():
            непонятые.append(str(т).strip())
    return tuple(понятые), tuple(непонятые)


# --- требования -------------------------------------------------------------------


def _требование(
    ключ: str, строки: Sequence[Fact], семья: Sequence[tuple[str, Sequence[Fact]]], модель: str
) -> tuple[str, str, list[Fact]]:
    """(исход PASS/FAIL/UNMEASURED, почему, строки-основания) одного требования."""
    лицензии = [f for f in строки if attrfamily.семья_имени(f.attribute) == "license"]
    if ключ == REQ_OPEN:
        state, нота = hn.weights_state(строки, семья)
        опора = лицензии or [
            f for _, rows in семья for f in rows if attrfamily.семья_имени(f.attribute) == "license"
        ]
        if state in (hn.WEIGHTS_YES, hn.WEIGHTS_FAMILY):
            return PASS, f"open weights: {нота}", опора[:1]
        if state == hn.WEIGHTS_NO:
            return FAIL, f"closed: {нота}", опора[:1]
        return UNMEASURED, "weights not recorded", []
    if ключ == REQ_COMMERCIAL:
        свои = list(строки) + [
            f for _, rows in семья for f in rows if attrfamily.семья_имени(f.attribute) == "license"
        ]
        проба = pl.probe_licence(
            pl.Step(name="find", model=модель, requirement="", use=pl.USE_COMMERCIAL), свои
        )
        опора = [f for f in свои if attrfamily.семья_имени(f.attribute) == "license"]
        if проба.outcome == PASS:
            return PASS, f"licence permits commercial use: {проба.note}", опора[:1]
        if проба.fired:
            return FAIL, f"licence forbids commercial use: {проба.note}", опора[:1]
        return UNMEASURED, проба.note, []
    return UNMEASURED, "requirement not understood", []


# --- поиск -----------------------------------------------------------------------


def _коротко(значение: object, n: int) -> str:
    """Не длиннее `n` знаков — по фразе или слову (`l10n.clip`), а не посреди слова."""
    return l10n.clip(значение, n)


def _строка(f: Fact, sign: str, polarity: str, why: str = "") -> dict:
    return {
        "attribute": f.attribute,
        "value": _коротко(f.value, 220),
        "tier": f.tier,
        "stated_on": f.stated_on,
        "source_url": f.source_url,
        "sign": sign,
        "polarity": polarity,
        **({"why": why} if why else {}),
    }


def _строка_памяти(rows: Sequence[Fact]) -> Fact | None:
    """Строка, из которой `hardneed.vram_need` взял число памяти (для показа)."""
    лучшая: tuple[float, Fact] | None = None
    for f in rows:
        if not re.search(r"vram|gpu_memory|min_gpu_mem", f.attribute, re.I):
            continue
        for м in hn._GB.finditer(f.value):
            x = float(м.group(1))
            if 1 <= x <= 200 and (лучшая is None or x < лучшая[0]):
                лучшая = (x, f)
    return лучшая[1] if лучшая else None


def _строка_каталога(узел: ep.Endpoint, rows: Sequence[Fact]) -> Fact | None:
    """Строка, несущая ИДЕНТИФИКАТОР эндпоинта: каталог площадки или адрес схемы."""
    for f in rows:
        if f.attribute == "availability" and any(i in str(f.value) for i in узел.ids):
            return f
    for f in rows:
        if any(i in (f.source_url or "") for i in узел.ids):
            return f
    return None


def _ступень(f: Fact) -> int:
    return TIERS.index(f.tier) if f.tier in TIERS else len(TIERS)


def scope(function: str, need: str, terms: str = "") -> tuple[tuple[str, ...], str]:
    """(работы реестра, как поняты). Пусто — работа не понята ни из `function`, ни из вопроса."""
    работы, широкое = ep.jobs_of_word(function)
    в_вопросе = ep.job_words(f"{need} {terms}")
    if работы and not широкое:
        return работы, f"function {function!r}"
    if в_вопросе:
        # Широкое слово (`video`) или непонятое — уточняется ПЕРВОЙ работой,
        # названной в вопросе («background removal for video» — удаление фона).
        return в_вопросе[:1], (
            f"function {function!r} narrowed by the question to {в_вопросе[0]}"
            if работы
            else f"function {function!r} not a registry job; the question names {в_вопросе[0]}"
        )
    if работы:
        return работы, f"function {function!r} (broad: {', '.join(работы)})"
    return (), ""


def find(
    need: str,
    function: str = "",
    terms: str = "",
    require: str = "",
    top: int = 8,
    *,
    facts: Iterable[Fact] | None = None,
    path: Path | None = None,
    lang: str = "en",
    conditions: Iterable[str] = (),
) -> dict:
    """Модели работы, ранжированные по ОБЪЯВЛЕННОМУ свидетельству о `need`."""
    англ = lang != "ru"
    работы, как = scope(function, need, terms)
    if not работы:
        return {
            "outcome": UNMEASURED,
            "reason": "function_unknown",
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "functions": list(ep.FUNCTIONS),
            "note": (
                f"function {function!r} is not a registry job ({', '.join(ep.FUNCTIONS)}) and the "
                "question names none; nothing was searched"
                if англ
                else f"функция {function!r} — не работа реестра ({', '.join(ep.FUNCTIONS)}), и вопрос "
                "ни одной не называет; поиск не делался"
            ),
            "ranked": [],
        }
    if facts is None:
        from studio.mcp.advice import store_for

        facts = store_for(path).facts
    facts = list(facts)
    реестр = ep.build(facts)
    по_ключу: dict[str, list[Fact]] = {}
    класс: list[Fact] = []
    for f in facts:
        if f.model == "*" or f.model.endswith("-*"):
            класс.append(f)
        else:
            по_ключу.setdefault(fold(f.model), []).append(f)
    вопрос = Вопрос(need, terms, require, conditions)

    узлы = {у.key: у for р in работы for у in реестр.by_function.get(р, [])}
    модели = sorted(узлы.values(), key=lambda у: у.model)
    отсеяно: list[dict] = []
    #: Отсеяны, потому что требование НЕ ЗАПИСАНО (веса при `open`): не
    #: «прошли», но и не «нарушили» — названы отдельным списком (валидатор v7).
    неизвестно: list[dict] = []
    ранжировано: list[dict] = []
    без_свидетельства: list[str] = []
    for у in модели:
        свои = по_ключу.get(у.key, [])
        семья = []
        if у.family and fold(у.family) in по_ключу:
            семья = [(у.family, по_ключу[fold(у.family)])]
        строки = свои + [f for _, rows in семья for f in rows]
        требования: dict[str, dict] = {}
        опоры: list[tuple[Fact, str]] = []
        нарушено = ""
        не_записано = ""
        for ключ in вопрос.требования:
            исход, почему, основания = _требование(ключ, свои, семья, у.model)
            требования[ключ] = {"outcome": исход, "why": _коротко(почему, 200)}
            if исход == FAIL and not нарушено:
                нарушено = f"{ключ}: {_коротко(почему, 160)}"
            if исход == UNMEASURED and ключ in REQUIRE_RECORDED and not не_записано:
                не_записано = f"{ключ}: {_коротко(почему, 160)}"
            if исход == PASS:
                опоры += [(f, почему) for f in основания]
        if нарушено:
            отсеяно.append({"model": у.model, "why": нарушено})
            continue
        if не_записано:
            неизвестно.append({"model": у.model, "why": не_записано})
            continue
        if вопрос.память is not None:
            нужно, откуда, оценка = hn.vram_need(строки)
            положение = hn.vram_state(нужно, оценка, вопрос.память)
            if положение == hn.VRAM_OVER:
                отсеяно.append(
                    {
                        "model": у.model,
                        "why": f"vram: needs >= {нужно:.3g} GB, asked {вопрос.память:g} GB — "
                        f"{_коротко(откуда, 140)}",
                    }
                )
                continue
            ключ_памяти = f"vram<={вопрос.память:g}GB"
            if положение == hn.VRAM_FITS:
                требования[ключ_памяти] = {"outcome": PASS, "why": _коротко(откуда, 200)}
                опора = _строка_памяти(строки)
                if опора is not None:
                    опоры_памяти = [(опора, f"needs {нужно:.3g} GB <= {вопрос.память:g} GB")]
                else:
                    опоры_памяти = []
            else:
                требования[ключ_памяти] = {
                    "outcome": UNMEASURED,
                    "why": _коротко(откуда, 200)
                    + ("; a parameter-count estimate is only a lower bound" if оценка else ""),
                }
                опоры_памяти = []
        else:
            опоры_памяти = []
        найдено = [f for f in строки if _относится(f, вопрос)]
        с_знаком = []
        for f in найдено:
            з, откуда, почему = знак(f, вопрос)
            с_знаком.append((f, з, откуда, почему))
        уже = {id(f) for f, *_ in с_знаком}
        # Память, прочитанная против спрошенной, — хорошая новость о предмете.
        for f, почему in опоры_памяти:
            с_знаком = [t for t in с_знаком if t[0] is not f]
            с_знаком.append((f, GOOD, POLARITY_CONSTRAINT, почему))
            уже.add(id(f))
        # Правка, НАЗВАННАЯ идентификатором эндпоинта, — способность по каталогу.
        for п in вопрос.правки:
            if ep.not_an_edit(у):
                continue
            опора = _строка_каталога(у, свои)
            if опора is None:
                continue
            if п in ep.edit_named(у):
                с_знаком.append(
                    (
                        опора,
                        GOOD,
                        POLARITY_CATALOG,
                        f"endpoint id names {п} ({', '.join(у.ids[:2]) or у.model}): capability by "
                        "catalog/schema, not measured applicability",
                    )
                )
            elif п in ep.edit_intents(у):
                с_знаком.append(
                    (
                        опора,
                        INFO,
                        POLARITY_NONE,
                        f"instruction edit ({', '.join(у.ids[:2]) or у.model}): may do {п} by prompt; "
                        "the id does not name it",
                    )
                )
            уже.add(id(опора))
        # Подтверждённое требование — хорошая новость, прочитанная по атрибуту, —
        # только когда спрошены ОДНИ требования (`Вопрос.только_требования`).
        for f, почему in опоры:
            if id(f) not in уже and вопрос.только_требования:
                с_знаком.append((f, GOOD, POLARITY_CONSTRAINT, _коротко(почему, 160)))
                уже.add(id(f))
        if вопрос.языки:
            # Язык — требование тоже: модель, чей список языков ИСКЛЮЧИТЕЛЕН
            # («English only») и нужного не содержит, отсеивается.
            списки = [f for f in строки if attrfamily.семья_имени(f.attribute) == "languages"]
            есть = (
                frozenset().union(*[_языки_строки(f.value) for f in списки])
                if списки
                else frozenset()
            )
            нет = [я for я in вопрос.языки if я not in есть]
            if нет and any(pl.exclusive_language(f.value) for f in списки):
                отсеяно.append(
                    {
                        "model": у.model,
                        "why": f"languages: {', '.join(нет)} not in an exclusive list",
                    }
                )
                continue
            for я in вопрос.языки:
                требования[я] = {
                    "outcome": PASS if я in есть else UNMEASURED,
                    "why": "listed" if я in есть else "not listed in any recorded languages row",
                }
        if not с_знаком:
            без_свидетельства.append(у.model)
            continue
        хорошие = sorted((t for t in с_знаком if t[1] == GOOD), key=lambda t: _ступень(t[0]))
        плохие = sorted((t for t in с_знаком if t[1] == BAD), key=lambda t: _ступень(t[0]))
        прочие = sorted((t for t in с_знаком if t[1] == INFO), key=lambda t: _ступень(t[0]))
        вердикт = (
            "good_news_only"
            if хорошие and not плохие
            else "mixed"
            if хорошие
            else "bad_news_only"
            if плохие
            else "informational_only"
        )
        метрики = [м for f, *_ in с_знаком if (м := _метрика(f, вопрос.условия))]
        лучшая_метрика = (
            sorted(метрики, key=lambda м: м[1] if м[3] else -м[1])[0] if метрики else None
        )
        неподтверждено = sum(1 for в in требования.values() if в["outcome"] != PASS)
        опорные = хорошие or прочие or плохие
        ранжировано.append(
            {
                "model": у.model,
                "orderable": у.orderable,
                "jobs": [р for р in у.functions if р in работы],
                "verdict": вердикт,
                "best_tier": опорные[0][0].tier if опорные else "",
                "good": [_строка(f, з, о, п) for f, з, о, п in хорошие[:СВИДЕТЕЛЬСТВ_ПОКАЗАНО]],
                "bad": [_строка(f, з, о, п) for f, з, о, п in плохие[:СВИДЕТЕЛЬСТВ_ПОКАЗАНО]],
                "informational": [
                    _строка(f, з, о, п) for f, з, о, п in прочие[:СВИДЕТЕЛЬСТВ_ПОКАЗАНО]
                ],
                "good_total": len(хорошие),
                "bad_total": len(плохие),
                "informational_total": len(прочие),
                "requirements": требования,
                **(
                    {"metric": f"{лучшая_метрика[0]} {лучшая_метрика[2]} {лучшая_метрика[1]:g}"}
                    if лучшая_метрика
                    else {}
                ),
                "sources": len({t[0].source_url for t in с_знаком}),
                "_ключ": (
                    неподтверждено,
                    VERDICT_ORDER[вердикт],
                    _ступень(хорошие[0][0]) if хорошие else len(TIERS),
                    (лучшая_метрика[1] if лучшая_метрика[3] else -лучшая_метрика[1])
                    if лучшая_метрика
                    else float("inf"),
                    -len({t[0].source_url for t in хорошие}),
                ),
                "_свежесть": max((t[0].stated_on or "" for t in с_знаком), default=""),
            }
        )
    ранжировано.sort(key=lambda r: r["model"])
    ранжировано.sort(key=lambda r: r["_свежесть"], reverse=True)
    ранжировано.sort(key=lambda r: r["_ключ"])
    for r in ранжировано:
        r.pop("_ключ")
        r.pop("_свежесть")
    с_хорошей = [r for r in ранжировано if r["good_total"]]
    о_классе = [
        {"scope": f.model, **_строка(f, *знак(f, вопрос)[:2])}
        for f in класс
        if not вопрос.пусто and _относится(f, вопрос)
    ][: СВИДЕТЕЛЬСТВ_ПОКАЗАНО * 2]
    показано = ранжировано[: max(1, int(top or 8))]
    итог_pass = bool(с_хорошей)
    спрошено = ", ".join(вопрос.описание()[:6]) or (
        "(requirements only)" if англ else "(только требования)"
    )
    требования_все = [
        *вопрос.требования,
        *вопрос.языки,
        *([f"vram<={вопрос.память:g}GB"] if вопрос.память is not None else []),
    ]
    if англ:
        нота = (
            f"scope: {как} -> {', '.join(работы)}; {len(модели)} endpoint(s) of that job in the registry; "
            + (
                f"{len(отсеяно)} dropped for violating {', '.join(требования_все)}; "
                if требования_все
                else ""
            )
            + (
                f"{len(неизвестно)} dropped because the requirement is NOT RECORDED for them "
                f"(excluded_unknown — not proof they fail it); "
                if неизвестно
                else ""
            )
            + f"{len(ранжировано)} have rows about {спрошено}, {len(с_хорошей)} of them with good news "
            "(declared polarity or a value read against your constraint); "
            f"{len(без_свидетельства)} have NOTHING recorded on it. "
            + (
                "Ranked by evidence (good news only, then informational, then mixed, then bad), not by "
                "quality: a model with no row may be better and simply unmeasured."
                if итог_pass
                else "No model has declared good news on this — a gap in the base, not proof that none "
                "can: search the web and record what you find with record_model_fact (with contra)."
            )
            + (
                " Price is not capability: ask plan_pipeline or model_advice for cost."
                if вопрос.цена_спрошена
                else ""
            )
            + " Before recommending any name, call model_advice on it."
            + (
                f" Not understood as a requirement (ignored): {', '.join(вопрос.непонятые)}."
                if вопрос.непонятые
                else ""
            )
        )
    else:
        нота = (
            f"область: {как} -> {', '.join(работы)}; эндпоинтов этой работы в реестре: {len(модели)}; "
            + (
                f"отсеяно за нарушение ({', '.join(требования_все)}): {len(отсеяно)}; "
                if требования_все
                else ""
            )
            + (
                f"отсеяно, потому что требование у них НЕ ЗАПИСАНО: {len(неизвестно)} "
                "(excluded_unknown — не доказательство, что не проходят); "
                if неизвестно
                else ""
            )
            + f"со строками о {спрошено}: {len(ранжировано)}, из них с хорошей новостью {len(с_хорошей)} "
            "(объявленный знак или значение, прочитанное против вашего ограничения); "
            f"НИЧЕГО не записано у {len(без_свидетельства)}. "
            + (
                "Порядок — по свидетельству (только хорошая, потом информация, потом смешанная, потом "
                "плохая), а НЕ по качеству: модель без строки может быть лучше, просто её не мерили."
                if итог_pass
                else "Объявленной хорошей новости нет ни у одной модели — это пробел базы, а не "
                "доказательство, что не умеет никто: поищите и запишите через record_model_fact (с contra)."
            )
            + (
                " Цена — не способность: стоимость спросите у plan_pipeline или model_advice."
                if вопрос.цена_спрошена
                else ""
            )
            + " Прежде чем назвать модель, спросите о ней model_advice."
            + (
                f" Не понято как требование (не учтено): {', '.join(вопрос.непонятые)}."
                if вопрос.непонятые
                else ""
            )
        )
    return {
        "outcome": PASS if итог_pass else UNMEASURED,
        "reason": "ranked_by_evidence"
        if итог_pass
        else ("no_good_news" if ранжировано else "no_evidence"),
        "checked": len(модели),
        "violations": 0,
        "unmeasured": len(без_свидетельства) + (0 if итог_pass else 1),
        "function": работы[0] if len(работы) == 1 else list(работы),
        "scope": как,
        "terms": вопрос.описание(),
        "conditions": list(вопрос.условия),
        "require": требования_все,
        "require_not_understood": вопрос.непонятые,
        "note": нота,
        "ranked": показано,
        "ranked_total": len(ранжировано),
        "gaps": {
            "models_without_evidence": len(без_свидетельства),
            "examples": без_свидетельства[:ПРОБЕЛОВ_ПОКАЗАНО],
            "excluded_by_requirement": len(отсеяно),
            "excluded_examples": отсеяно[:ПРОБЕЛОВ_ПОКАЗАНО],
            "excluded_unknown": len(неизвестно),
            "excluded_unknown_examples": неизвестно[:ПРОБЕЛОВ_ПОКАЗАНО],
        },
        "class_findings": о_классе,
    }


def describe_functions() -> list[str]:
    return list(ep.FUNCTIONS)


__all__ = [
    "BAD",
    "CONDITION_NEGATIVE",
    "CONDITION_POSITIVE",
    "CONDITION_UNKNOWN",
    "GOOD",
    "INFO",
    "condition_state",
    "conditions_of",
    "describe_functions",
    "find",
    "scope",
    "знак",
]
