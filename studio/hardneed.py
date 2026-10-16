"""ЖЁСТКИЕ ТРЕБОВАНИЯ ЗАКАЗЧИКА К ОТБОРУ: свой GPU, цель, нативный кадр.

ЗАЧЕМ МОДУЛЬ (2026-10-15, независимый валидатор, раунд 4). Отбор кандидатов
знал бюджет, кадр креатива, длительность и лицензию — и не знал, ГДЕ модель
будет работать и ЧТО заказчик ставит выше цены:

* «self-host on one RTX 4090, 1080p 5s» выбирал `kling-3.0` — модель без
  открытых весов, которую на своём GPU не запустить вовсе;
* «4K … quality over price» ставил первым `kling-3.0` без цены и без тарифа в
  4K, хотя `kling-3.0-4k-t2v` отдаёт 4K сам.

Это ОГРАНИЧЕНИЯ, а не доводы о модели, и поэтому они живут фильтром и одним
полем ключа, а не весом среди доводов (как бюджет и запрет на вход).

ВХОД — ПРОСТЫЕ ЗНАЧЕНИЯ (`Hard`), а не бриф. Бриф читает `from_brief` здесь
же, но разбор брифа — чужая работа (`planner` cue-листы); структурированная
спецификация (`spec`: self_host {gpu, vram_gb}, objective, jurisdiction,
resolution) подаётся в `from_spec` и перекрывает прочитанное из брифа. Так
фильтры не зависят от того, откуда пришло значение.

ТРИ ИСХОДА (Р1) у каждой оси: веса есть / нет / не записано; VRAM влезает /
не влезает / не записано; кадр родной / ниже / не записано. «Не записано» не
превращается ни в «да», ни в «нет»: при жёстком требовании оно не проходит
фильтр весов (запускать нечего, пока веса не найдены) и проходит фильтр VRAM
с пометкой (веса есть, а сколько памяти им нужно — никто не сказал).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Mapping, Sequence

from studio.selfrag.facts import Fact
from studio.l10n import clip

# --------------------------------------------------------------------------
# ЗНАЧЕНИЯ ТРЕБОВАНИЙ
# --------------------------------------------------------------------------

OBJECTIVE_CHEAPEST = "cheapest"
OBJECTIVE_BALANCED = "balanced"
OBJECTIVE_QUALITY = "quality"
OBJECTIVES: tuple[str, ...] = (OBJECTIVE_CHEAPEST, OBJECTIVE_BALANCED, OBJECTIVE_QUALITY)


@dataclass(frozen=True)
class Hard:
    """Жёсткие требования к отбору — простые значения, откуда бы они ни пришли.

    :param self_host: модель будет запущена на СВОЁМ (арендованном) GPU —
        нужны открытые веса, а цена шага — время GPU, а не тариф API.
    :param gpu: имя GPU (`rtx-4090`), по нему ищется ставка аренды.
    :param vram_gb: память GPU; не названа, но назван GPU — берётся из
        `GPU_VRAM_GB`.
    :param objective: `cheapest` / `balanced` / `quality` или пусто.
    :param jurisdiction: юрисдикции заказчика (`EU`, …) или None — не названа.
    :param resolution: короткая сторона заказанного кадра или None.
    """

    self_host: bool = False
    #: Нужны открытые веса (лицензия «open source/open weights»), даже если
    #: запуск — через API. `self_host` их подразумевает.
    open_weights: bool = False
    gpu: str | None = None
    vram_gb: float | None = None
    objective: str = ""
    jurisdiction: tuple[str, ...] | None = None
    #: Страны, названные заказчиком ({DE: EU} -> ("DE",)): лицензии судят по
    #: блоку (`jurisdiction`), а печатается страна рядом с ним.
    countries: tuple[str, ...] = ()
    resolution: int | None = None
    #: Свой Mac (Apple silicon): `vram_gb` у него нет — есть единая память
    #: (`unified_memory_gb`), и запуск идёт не на CUDA (девятый круг).
    apple_silicon: bool = False
    unified_memory_gb: float | None = None
    #: Своя машина БЕЗ GPU (десятый круг): Raspberry Pi, мини-ПК, сервер на CPU.
    #: Видеопамяти нет — отбор ранжирует по записанному запуску на ARM / CPU
    #: (`cpu_state`), а не по VRAM.
    cpu_only: bool = False
    #: Откуда взято каждое значение: «бриф» / «spec» — печатается рядом.
    sources: tuple[tuple[str, str], ...] = field(default=())

    @property
    def weights_required(self) -> bool:
        return self.self_host or self.open_weights

    @property
    def active(self) -> bool:
        return self.weights_required or self.objective == OBJECTIVE_QUALITY

    def row(self) -> dict:
        return {
            "self_host": self.self_host,
            "open_weights": self.weights_required,
            "gpu": self.gpu,
            "vram_gb": self.vram_gb,
            "objective": self.objective,
            "jurisdiction": list(self.jurisdiction) if self.jurisdiction else None,
            "countries": list(self.countries),
            "resolution": self.resolution,
            **(
                {"apple_silicon": True, "unified_memory_gb": self.unified_memory_gb}
                if self.apple_silicon
                else {}
            ),
            **({"cpu_only": True} if self.cpu_only else {}),
            "sources": dict(self.sources),
        }


#: Память распространённых GPU, ГБ. КОНСТАНТА-ТАБЛИЦА: паспортные значения
#: карт, а не замер; бриф или spec с числом `vram_gb` перекрывают её.
GPU_VRAM_GB: dict[str, float] = {
    "rtx-3060": 12.0,
    "rtx-3080": 10.0,
    "rtx-3090": 24.0,
    "rtx-4070": 12.0,
    "rtx-4080": 16.0,
    "rtx-4090": 24.0,
    "rtx-5090": 32.0,
    "rtx-a5000": 24.0,
    "rtx-a6000": 48.0,
    "l4": 24.0,
    "l40s": 48.0,
    "a100": 80.0,
    "h100": 80.0,
    "h200": 141.0,
}

#: Как бриф называет запуск на своём GPU. Слова — о МЕСТЕ запуска; GPU,
#: названный по имени («on one RTX 4090»), — тоже запуск на своём.
SELF_HOST_CUES: tuple[str, ...] = (
    r"self[- ]?host",
    r"run (?:it )?(?:locally|on (?:my|our) (?:own )?(?:gpu|machine|server|hardware))",
    r"on[- ]prem",
    r"\brunpod\b",
    r"на сво(?:ём|ем|их|ей) (?:gpu|видеокарт\w*|сервер\w*|железе)",
    r"локально",
)

#: Как бриф требует ОТКРЫТЫХ ВЕСОВ — без указания, где запускать.
OPEN_WEIGHTS_CUES: tuple[str, ...] = (
    r"open[- ]weights?",
    r"open[- ]source",
    r"открыт\w* вес",
    r"открыт\w* исходн",
    r"open[- ]source|опенсорс",
)

#: «Качество важнее цены». Только явные формы: одно слово «quality» в брифе —
#: это описание кадра («high quality product shot»), а не цель отбора.
QUALITY_CUES: tuple[str, ...] = (
    r"quality over (?:price|cost)",
    r"quality (?:first|matters more)",
    r"best (?:possible )?quality",
    r"highest quality",
    r"price (?:is )?(?:no|not an?) (?:object|issue|concern)",
    r"regardless of (?:price|cost)",
    r"качеств\w* важнее (?:цены|денег|бюджета)",
    r"максимальн\w* качеств",
    r"лучше(?:е|го)? качеств",
    r"цена не важна",
)

#: Размер памяти, названный словами: «24 GB», «24gb VRAM», «24 ГБ».
_VRAM_IN_TEXT = re.compile(r"(\d{1,3}(?:\.\d+)?)\s*(?:gb|гб|gib)\b", re.I)
_GPU_IN_TEXT = re.compile(
    r"\b(?:(?:nvidia|geforce)\s+)?(rtx\s*a?\s*\d{4}|rtx\s*a\d{4}|l40s|l4|a100|h100|h200)\b", re.I
)


def gpu_key(name: str) -> str:
    """`RTX 4090` -> `rtx-4090`; `A100` -> `a100`; `RTX A6000` -> `rtx-a6000`."""
    низ = re.sub(r"\s+", "", str(name or "").lower())
    м = re.match(r"rtx(a?)(\d{4})$", низ)
    if м:
        return f"rtx-{м.group(1)}{м.group(2)}"
    return низ


def from_brief(brief: str) -> Hard:
    """Что бриф говорит о свой-GPU и о цели. Юрисдикцию и кадр читают не здесь."""
    низ = str(brief or "").lower()
    свой = any(re.search(r, низ) for r in SELF_HOST_CUES)
    веса = any(re.search(r, низ) for r in OPEN_WEIGHTS_CUES)
    gpu_м = _GPU_IN_TEXT.search(низ)
    gpu = gpu_key(gpu_м.group(1)) if gpu_м else None
    vram_м = _VRAM_IN_TEXT.search(низ)
    vram = float(vram_м.group(1)) if vram_м and (свой or gpu) else None
    # Память без имени GPU («self-host, 24 GB»): запуск свой, карта не названа.
    if vram is None and gpu:
        vram = GPU_VRAM_GB.get(gpu)
    # GPU назван — запуск свой, даже если слова self-host нет («on one RTX 4090»).
    свой = свой or gpu is not None
    цель = OBJECTIVE_QUALITY if any(re.search(r, низ) for r in QUALITY_CUES) else ""
    источники = tuple(
        (k, "бриф")
        for k, v in (
            ("self_host", свой),
            ("open_weights", веса),
            ("gpu", gpu),
            ("vram_gb", vram),
            ("objective", цель),
        )
        if v
    )
    return Hard(
        self_host=свой, open_weights=веса, gpu=gpu, vram_gb=vram, objective=цель, sources=источники
    )


def from_spec(spec: Mapping | None, base: Hard | None = None) -> Hard:
    """Наложить структурированную спецификацию на прочитанное из брифа.

    Поля spec: `self_host` (bool или {gpu, vram_gb}), `objective`,
    `jurisdiction` (строка или список), `resolution` (короткая сторона или
    `1080p`/`4k`). Названное в spec перекрывает бриф: его назвали явно.
    """
    base = base or Hard()
    if not spec:
        return base
    поля: dict = {}
    источники = dict(base.sources)
    свой = spec.get("self_host")
    if isinstance(свой, Mapping):
        поля["self_host"] = True
        if свой.get("cpu_only") or (свой.get("gpu") and CPU_ONLY.search(str(свой["gpu"]))):
            поля["cpu_only"] = True
        if свой.get("gpu"):
            поля["gpu"] = gpu_key(str(свой["gpu"]))
        if свой.get("vram_gb") is not None:
            поля["vram_gb"] = float(свой["vram_gb"])
        elif поля.get("gpu") and base.vram_gb is None:
            поля["vram_gb"] = GPU_VRAM_GB.get(поля["gpu"])
    elif свой is not None:
        поля["self_host"] = bool(свой)
    цель = spec.get("objective")
    if цель:
        if цель not in OBJECTIVES:
            raise ValueError(f"objective {цель!r}: ждём одно из {OBJECTIVES}")
        поля["objective"] = цель
    юр = spec.get("jurisdiction")
    if юр:
        блоки, страны = jurisdiction_codes([юр] if isinstance(юр, str) else list(юр))
        поля["jurisdiction"] = блоки or None
        поля["countries"] = страны
    кадр = spec.get("resolution")
    if кадр:
        поля["resolution"] = resolution_side(кадр)
    for k in поля:
        источники[k] = "spec"
    return replace(base, **поля, sources=tuple(sorted(источники.items())))


def jurisdiction_codes(названия: Sequence[str]) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(блоки, страны) из кодов или имён: «DE» -> EU/DE, «EU» -> EU, «Germany» -> EU/DE.

    Разбор имён — у `pipeline` (Е1): здесь только коды, остальное — ему.
    """
    from studio import pipeline as pl

    блоки: set[str] = set()
    страны: set[str] = set()
    for н in названия:
        код = str(н).strip().upper()
        if код in pl.COUNTRIES:
            страны.add(код)
            блоки.add(pl.COUNTRIES[код][0])
        elif код in pl.JURISDICTIONS:
            блоки.add(код)
        else:
            блоки |= set(pl.jurisdictions_in(str(н)))
            страны |= set(pl.countries_in(str(н)))
    return tuple(sorted(блоки)), tuple(sorted(страны))


def resolution_side(значение: object) -> int | None:
    """Короткая сторона: 1080, «1080p», «4k», (1920, 1080)."""
    if isinstance(значение, (tuple, list)) and len(значение) == 2:
        return int(min(значение))
    if isinstance(значение, (int, float)):
        return int(значение)
    низ = str(значение).strip().lower()
    if низ in ("4k", "uhd", "2160p"):
        return 2160
    м = re.match(r"(\d{3,4})p?$", низ)
    return int(м.group(1)) if м else None


# --------------------------------------------------------------------------
# ВЕСА
# --------------------------------------------------------------------------

WEIGHTS_YES = "веса открыты"
WEIGHTS_FAMILY = "веса открыты у семьи, у варианта не записаны"
WEIGHTS_NO = "весов нет: только API"
WEIGHTS_UNKNOWN = "о весах не записано"

#: Порядок: чем больше, тем хуже. Для поля ключа.
WEIGHTS_ORDER: dict[str, int] = {
    WEIGHTS_YES: 0,
    WEIGHTS_FAMILY: 1,
    WEIGHTS_UNKNOWN: 2,
    WEIGHTS_NO: 3,
}

#: Хосты, где лежат САМИ ВЕСА (карточка модели, репозиторий). Тот же список,
#: что у `planner.WEIGHTS_HOSTS`, — там он судит, о весах ли лицензия.
WEIGHTS_HOSTS: tuple[str, ...] = ("huggingface.co", "github.com", "raw.githubusercontent.com")

_NO_WEIGHTS = re.compile(
    r"not released as open weights|api[- ]only|closed[- ]weights|no open weights|proprietary|веса не (?:открыты|опубликованы)",
    re.I,
)
_LICENCE_ATTR = re.compile(r"licen[cs]e|лиценз", re.I)


def _repo_page(url: str) -> bool:
    """Страница РЕПОЗИТОРИЯ, а не поиск по каталогу (`/api/models?author=`)."""
    u = str(url or "")
    return any(h in u for h in WEIGHTS_HOSTS) and "/api/models?" not in u


def weights_own(rows: Sequence[Fact]) -> tuple[str, str]:
    """Веса по СВОИМ строкам модели: да / нет / не записано и откуда."""
    for f in rows:
        if (
            f.attribute == "open_weights" or _LICENCE_ATTR.search(f.attribute)
        ) and _NO_WEIGHTS.search(f.value):
            return WEIGHTS_NO, f"{f.attribute} = «{f.value[:80]}» ({f.source_url})"
    for f in rows:
        if f.attribute == "open_weights" and re.match(r"\s*(yes|true|да)\b", f.value, re.I):
            return WEIGHTS_YES, f"{f.attribute} = «{f.value[:80]}» ({f.source_url})"
    for f in rows:
        if _LICENCE_ATTR.search(f.attribute) and _repo_page(f.source_url):
            return WEIGHTS_YES, f"лицензия весов «{clip(f.value, 60)}» на странице весов ({f.source_url})"
    return WEIGHTS_UNKNOWN, "ни лицензии на странице весов, ни строки open_weights"


def weights_state(
    rows: Sequence[Fact], family: Sequence[tuple[str, Sequence[Fact]]] = ()
) -> tuple[str, str]:
    """Веса модели: свои строки, затем — семья (ПЕРЕНОС, а не факт).

    :param family: [(имя родителя, его строки)] от ближнего к дальнему.
    """
    своё, нота = weights_own(rows)
    if своё != WEIGHTS_UNKNOWN:
        return своё, нота
    for имя, строки in family:
        их, их_нота = weights_own(строки)
        if их == WEIGHTS_YES:
            return WEIGHTS_FAMILY, (
                f"веса семьи {имя}: {их_нота}; что этот вариант — опубликованный чекпойнт, "
                "в базе НЕ записано"
            )
        if их == WEIGHTS_NO:
            return WEIGHTS_NO, f"семья {имя}: {их_нота}"
    return WEIGHTS_UNKNOWN, нота


# --------------------------------------------------------------------------
# ПАМЯТЬ GPU
# --------------------------------------------------------------------------

VRAM_FITS = "влезает в память GPU"
VRAM_OVER = "НЕ влезает в память GPU"
VRAM_UNKNOWN = "сколько памяти нужно — не записано"
VRAM_ORDER: dict[str, int] = {VRAM_FITS: 0, VRAM_UNKNOWN: 1, VRAM_OVER: 2}

#: Байт на параметр для НИЖНЕЙ границы памяти по числу параметров: FP8.
#: КОНСТАНТА-РЕШЕНИЕ: веса в FP8 — наименьшее, что вендоры публикуют сами
#: (LTX-2: fp8 и fp4; 4-битные — сообщество). Граница нижняя: если даже веса
#: в FP8 больше карты, модель на ней не запустить без выгрузки слоёв, о
#: которой вендор не сказал. Выше границы — «не записано», а не «влезает».
BYTES_PER_PARAM_FLOOR = 1.0

_VRAM_ATTR = re.compile(r"vram|gpu_memory|min_gpu_mem", re.I)
#: Число в строке памяти — не хвост слова: «--t5_cpu» не «5 ГБ» (седьмой круг,
#: валидатор v7 f18: `wan-2.2-ti2v-5b` с «24 (e.g. RTX 4090) … --t5_cpu»
#: читалась как «нужно 5 ГБ»).
_GB = re.compile(r"(?<![\w.])(\d{1,3}(?:\.\d+)?)\s*(?:gb|гб)?", re.I)
_PARAMS = re.compile(r"(\d{1,4}(?:\.\d+)?)\s*(?:b\b|billion|млрд)", re.I)
_PARAMS_RAW = re.compile(r"\b(\d{1,3}(?:,\d{3}){3,})\b")


def vram_need(rows: Sequence[Fact]) -> tuple[float | None, str, bool]:
    """Сколько памяти GPU нужно модели: (ГБ, откуда, оценка ли это).

    Записанный предел (`min_vram_gb`, `vram`) — наименьшее число строки: вендор
    называет несколько режимов (с выгрузкой и без), и запуск с выгрузкой — тоже
    запуск. Нет записи — нижняя граница по числу параметров (FP8), помеченная
    как оценка.
    """
    числа: list[tuple[float, Fact]] = []
    for f in rows:
        if not _VRAM_ATTR.search(f.attribute):
            continue
        for м in _GB.finditer(f.value):
            x = float(м.group(1))
            if 1 <= x <= 200:
                числа.append((x, f))
    if числа:
        x, f = min(числа, key=lambda п: п[0])
        return x, f"{f.attribute} = «{f.value[:90]}» ({f.source_url})", False
    for f in rows:
        if "parameter_count" not in f.attribute:
            continue
        сырое = _PARAMS_RAW.search(f.value)
        if сырое:
            миллиарды = int(сырое.group(1).replace(",", "")) / 1e9
        else:
            словами = _PARAMS.search(f.value)
            if not словами:
                continue
            миллиарды = float(словами.group(1))
        гб = миллиарды * BYTES_PER_PARAM_FLOOR
        return (
            гб,
            f"ОЦЕНКА снизу: {миллиарды:.1f}B параметров × {BYTES_PER_PARAM_FLOOR:g} байт (FP8) = {гб:.0f} ГБ "
            f"одних весов ({f.attribute}, {f.source_url}); числа VRAM вендор не назвал",
            True,
        )
    return None, "ни предела VRAM, ни числа параметров не записано", False


def vram_state(need: float | None, estimate: bool, have: float | None) -> str:
    """Влезает ли: по записи — да/нет; по оценке снизу — только «нет» решается."""
    if have is None or need is None:
        return VRAM_UNKNOWN
    if need > have:
        return VRAM_OVER
    return VRAM_UNKNOWN if estimate else VRAM_FITS


# --------------------------------------------------------------------------
# СВОЙ MAC: ЗАПУСК НА APPLE SILICON
# --------------------------------------------------------------------------

APPLE_GPU = "запуск на GPU Mac (MPS / MLX / Metal / Core ML) записан"
APPLE_CPU = "на Mac записан только запуск на CPU"
APPLE_UNKNOWN = "запуск на Mac не записан"
APPLE_ORDER: dict[str, int] = {APPLE_GPU: 0, APPLE_CPU: 1, APPLE_UNKNOWN: 2}

#: Слова, которыми запись называет ускоренный запуск на Mac. Тот же словарь,
#: что `planner.APPLE_RUNTIME` (строка `apple_silicon` в выдаче шага).
_APPLE_GPU_WORDS = re.compile(r"\bmps\b|\bmlx\b|\bmetal\b|core ?ml|apple neural engine", re.I)
#: Запись о Mac, где сказан запуск на процессоре (официальный скрипт без ветки
#: `mps`: `cuda if available else cpu`). Медленно, но запускается.
_APPLE_CPU_WORDS = re.compile(r"\bcpu\b", re.I)
_APPLE_ATTR = re.compile(r"apple|mac|mps|mlx|metal|coreml", re.I)


def apple_state(rows: Sequence[Fact]) -> tuple[str, str]:
    """Запускается ли модель на своём Mac — по СВОИМ строкам. Три исхода (Р1).

    ДЕВЯТЫЙ КРУГ. На «M1 MacBook Air 8 GB» выбиралась `qwen-image` (20B), на
    «M2 Pro, липсинк» — модель, о запуске которой на Mac не записано ничего,
    хотя у соседей записан MPS или хотя бы CPU. Ускоренный запуск (MPS, MLX,
    Metal, Core ML) по записи старше записанного CPU, тот — старше молчания.
    Строка о CPU считается только в атрибуте о Mac: «CPU int8» в описании
    CUDA-модели — не про Mac.
    """
    for f in rows:
        if _APPLE_GPU_WORDS.search(f"{f.attribute} {f.value}") and not re.search(
            r"no mps|без mps|not supported", f.value, re.I
        ):
            return APPLE_GPU, f"{f.attribute} = «{f.value[:90]}» ({f.source_url})"
    for f in rows:
        if _APPLE_ATTR.search(f.attribute) and _APPLE_CPU_WORDS.search(f.value):
            return APPLE_CPU, f"{f.attribute} = «{f.value[:90]}» ({f.source_url})"
    return APPLE_UNKNOWN, "ни MPS/MLX/Metal/Core ML, ни CPU-запуска на Mac не записано"


# --------------------------------------------------------------------------
# СВОЯ МАШИНА БЕЗ GPU: RASPBERRY PI, МИНИ-ПК (десятый круг)
# --------------------------------------------------------------------------

#: Признак машины без GPU в имени «GPU» из spec или брифа. КОНСТАНТА-РЕШЕНИЕ:
#: одноплатники (Raspberry Pi, Orange Pi), «CPU only», «no GPU», мини-ПК. Jetson
#: сюда НЕ входит — у него CUDA.
CPU_ONLY = re.compile(
    r"raspberry|\b(?:rpi|pi ?[2-5]|orange ?pi|rock ?pi)\b|\bcpu[- ]?only\b|\bonly cpu\b|\bno gpu\b|\bwithout (?:a )?gpu\b"
    r"|\bnone\b.*\bcpu\b|\bcpu\b.*\bnone\b|^\s*cpu\s*$|\bmini ?pc\b|\bintel nuc\b|без (?:gpu|видеокарт\w*)"
    r"|только (?:на )?(?:cpu|процессор\w*)|одноплат\w*|малин\w*",
    re.I,
)

CPU_ARM = "запуск на ARM (Raspberry Pi и т.п.) записан"
CPU_YES = "запуск на CPU записан"
CPU_UNKNOWN = "запуск без GPU не записан"
CPU_NO = "записано: без GPU не запускается (или не для CPU)"
#: Порядок: записанный ARM старше записанного CPU, тот — старше молчания;
#: запись «не для CPU» — последней (не отсев: заказчик может взять ПК с GPU).
CPU_ORDER: dict[str, int] = {CPU_ARM: 0, CPU_YES: 1, CPU_UNKNOWN: 2, CPU_NO: 3}

#: Атрибуты, которыми база записывает запуск без GPU: `arm_inference`,
#: `cpu_inference`. Значение начинается с «yes» / «no» (или «not»), дальше —
#: подробности источника.
_CPU_ATTRS = ("arm_inference", "cpu_inference")
_YES = re.compile(r"\s*(?:yes|да)\b", re.I)
_NO = re.compile(r"\s*(?:no|not|нет|не)\b", re.I)


def cpu_state(rows: Sequence[Fact]) -> tuple[str, str]:
    """Запускается ли модель без GPU — по СВОИМ строкам `arm_inference` / `cpu_inference`."""
    for f in rows:
        if f.attribute == "arm_inference" and _YES.match(f.value):
            return CPU_ARM, f"{f.attribute} = «{f.value[:90]}» ({f.source_url})"
    for f in rows:
        if f.attribute == "cpu_inference" and _YES.match(f.value):
            return CPU_YES, f"{f.attribute} = «{f.value[:90]}» ({f.source_url})"
    for f in rows:
        if f.attribute in _CPU_ATTRS and _NO.match(f.value):
            return CPU_NO, f"{f.attribute} = «{f.value[:90]}» ({f.source_url})"
    return CPU_UNKNOWN, "ни запуска на ARM, ни на CPU не записано"


# --------------------------------------------------------------------------
# ЦЕНА СВОЕГО ЗАПУСКА: GPU-секунды × ставка аренды
# --------------------------------------------------------------------------

#: Имя «модели», под которым в базе лежит ставка аренды GPU у площадки.
RATE_MODEL_PREFIX = "runpod-"
RATE_ATTRIBUTE = "gpu_price_per_hour_usd"
RUNTIME_ATTRIBUTE = "gpu_seconds_per_clip"
ESTIMATE_MARK = "ОЦЕНКА"

_USD_H = re.compile(r"(\d+(?:\.\d+)?)\s*usd\s*/\s*h", re.I)
_RUNTIME = re.compile(r"(\d+(?:\.\d+)?)\s*GPU-s\s+per\s+(?:(\d+(?:\.\d+)?)\s*s\s+clip|run)", re.I)


@dataclass(frozen=True)
class GpuRate:
    low: float
    high: float
    source: str


def gpu_rate(facts: Sequence[Fact], gpu: str | None) -> GpuRate | None:
    """Ставка аренды GPU из базы: самая дешёвая и самая дорогая за час."""
    if not gpu:
        return None
    имя = RATE_MODEL_PREFIX + gpu
    for f in reversed(list(facts)):
        if f.model == имя and f.attribute == RATE_ATTRIBUTE:
            ставки = [float(x) for x in _USD_H.findall(f.value)]
            if ставки:
                return GpuRate(min(ставки), max(ставки), f"{f.value[:90]} ({f.source_url})")
    return None


@dataclass(frozen=True)
class GpuTime:
    seconds: float
    clip_seconds: float | None
    source: str


#: Режим, названный в строке времени: время чужого режима ценой шага не становится.
_MODE_WORDS: dict[str, re.Pattern[str]] = {
    "t2v": re.compile(r"text-to-video|\bt2v\b", re.I),
    "i2v": re.compile(r"image-to-video|\bi2v\b", re.I),
    "v2v": re.compile(r"video-to-video|\bv2v\b|upscal|restor", re.I),
}


def gpu_time(rows: Sequence[Fact], mode: str = "") -> GpuTime | None:
    """Записанное время GPU на клип (или на прогон, если длина клипа не сказана).

    :param mode: режим шага (`t2v`, `i2v`, `v2v`). Строка, назвавшая ДРУГОЙ
        режим, не берётся: 75 с на 480p image-to-video у HunyuanVideo-1.5 —
        не цена генерации по тексту. Строка без режима годится для любого.
    """
    for f in rows:
        if f.attribute != RUNTIME_ATTRIBUTE:
            continue
        названы = {m for m, r in _MODE_WORDS.items() if r.search(f.value)}
        if mode and названы and mode not in названы:
            continue
        м = _RUNTIME.search(f.value)
        if м:
            return GpuTime(
                float(м.group(1)),
                float(м.group(2)) if м.group(2) else None,
                f"{f.value[:100]} ({f.source_url})",
            )
    return None


@dataclass(frozen=True)
class SelfHostCost:
    low: float
    high: float
    formula: str


def self_host_cost(t: GpuTime, rate: GpuRate, seconds: float | None) -> SelfHostCost:
    """Цена шага на своём GPU: GPU-секунды × ставка. Всегда ОЦЕНКА.

    Время записано на клип длиной N секунд — масштабируется на длину ролика
    линейно (допущение, названное в расчёте). На «прогон» без длины — один
    прогон на каждый такой клип не считается: берётся как есть, и это сказано.
    """
    if t.clip_seconds and seconds:
        gpu_s = t.seconds * seconds / t.clip_seconds
        как = f"{t.seconds:g} GPU-с на клип {t.clip_seconds:g} с × {seconds:g}/{t.clip_seconds:g} (линейно — допущение)"
    else:
        gpu_s = t.seconds
        как = f"{t.seconds:g} GPU-с на прогон (длина клипа в источнике не названа)"
    low = gpu_s * rate.low / 3600.0
    high = gpu_s * rate.high / 3600.0
    return SelfHostCost(
        low,
        high,
        f"{ESTIMATE_MARK}: {как} = {gpu_s:.0f} GPU-с × {rate.low:g}–{rate.high:g} usd/ч ÷ 3600 = "
        f"{low:.2f}–{high:.2f} usd; время: {t.source}; ставка: {rate.source}",
    )


# --------------------------------------------------------------------------
# РОДНОЙ КАДР при цели «качество»
# --------------------------------------------------------------------------

NATIVE_PRICED = "заказанный кадр родной, и тариф к нему есть"
NATIVE_UNPRICED = "кадр родной по записи, но купить его не по чему: цены нет"
NATIVE_UNKNOWN = "родной ли кадр — не записано"
NATIVE_BELOW = "родной кадр НИЖЕ заказанного"
NATIVE_ORDER: dict[str, int] = {
    NATIVE_PRICED: 0,
    NATIVE_UNPRICED: 1,
    NATIVE_UNKNOWN: 2,
    NATIVE_BELOW: 3,
}


def native_state(reaches: bool | None, priced: bool) -> str:
    """:param reaches: True — запись подтверждает кадр, False — запись ниже, None — молчит."""
    if reaches is False:
        return NATIVE_BELOW
    if reaches is None:
        return NATIVE_UNKNOWN
    return NATIVE_PRICED if priced else NATIVE_UNPRICED
