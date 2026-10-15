"""Вопрос о способности ПО ВСЕЙ БАЗЕ: «какой липсинк держит профиль?»

ЗАЧЕМ (валидатор 5-го круга, 2026-10-15). `model_advice` отвечает о ОДНОЙ
модели, а вопрос заказчика часто о функции: «which lipsync handles profile
faces», «which i2v keeps logos legible», «best open TTS for Russian». Вызывающая
модель угадывала кандидатов по памяти и спрашивала базу о них — то есть база
отвечала только на те имена, которые модель и так помнила, а записанное о
других не всплывало никогда.

ЧТО ДЕЛАЕТ. Берёт модели ФУНКЦИИ (по имени и по строкам «что умеет / что
принимает / что отдаёт»), ищет в их строках СЛОВА ВОПРОСА (с короткими
синонимами), отбрасывает модели, у которых не записано ТРЕБОВАНИЕ («open»,
«russian»), и ранжирует по свидетельству:

    1. есть хорошая новость и нет плохой
    2. есть и хорошая, и плохая
    3. только плохая

внутри — по лучшей ступени хорошей новости (`TIERS`, без числовых весов: та же
доктрина, что у базы — вес приглашает усреднять), числу источников и свежести.

ЧЕСТНЫЕ ПРОБЕЛЫ (Р1). Модели функции, о которых по вопросу не записано ничего,
считаются и называются (`gaps`), а не молчат. Ноль моделей с хорошей новостью —
`could not measure`, а не `pass`: «никто не записал» не равно «никто не умеет».
Находки о КЛАССЕ (`*`, `vendor-*`) — отдельным списком: они о поле, не о модели.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path

from lipsync.fork_identity import PASS, UNMEASURED
from studio.selfrag import attrfamily
from studio.selfrag.facts import TIERS, Fact

#: ФУНКЦИИ: (имя модели, слова в строках-описаниях, имя-исключение).
ФУНКЦИИ: dict[str, tuple[str, tuple[str, ...], str]] = {
    "lipsync": (
        r"lip.?sync|latentsync|musetalk|wav2lip|infinitalk|omnihuman|hallo|sadtalker|"
        r"liveportrait|echomimic|multitalk|hedra|fantasytalking",
        ("lipsync", "lip sync", "lip-sync", "audio-driven", "talking head", "talking-head"),
        r"$^",
    ),
    "i2v": (
        r"i2v|image-to-video|img2vid",
        ("image-to-video", "image to video", "i2v", "first frame"),
        r"lip.?sync",
    ),
    "t2v": (r"t2v|text-to-video", ("text-to-video", "text to video", "t2v"), r"$^"),
    "video": (
        r"veo|kling|sora|wan|seedance|hailuo|runway|ltx|pika|hunyuanvideo|mochi|cogvideo|minimax-h3|"
        r"i2v|t2v",
        ("text-to-video", "image-to-video", "video generation"),
        r"lip.?sync|upscal|music|speech|tts",
    ),
    "tts": (
        r"tts|speech|eleven|xtts|f5|cosyvoice|fish-speech|silero|chatterbox|kokoro|bark|piper|orpheus|"
        r"melotts|indextts|higgs",
        ("text-to-speech", "tts", "speech synthesis"),
        r"music|sound.?effect|speech-to-text|stt|dubbing|voice-changer|sts|avatar|scribe",
    ),
    "image": (
        r"flux|imagen|gpt-image|nano-banana|seedream|sdxl|stable-diffusion|ideogram|recraft|"
        r"qwen-image|hidream|t2i",
        ("text-to-image", "image generation"),
        r"i2v|video|upscal",
    ),
    "upscale": (
        r"upscal|seedvr|topaz|esrgan|starlight",
        ("upscal", "super-resolution", "super resolution"),
        r"$^",
    ),
    "avatar": (
        r"avatar|omnihuman|hedra|heygen|synthesia",
        ("avatar", "talking head", "talking-head"),
        r"$^",
    ),
    "music": (r"music|suno|udio|lyria|stable-audio|musicgen", ("music generation",), r"$^"),
}

#: АТРИБУТЫ-ОПИСАНИЯ: по ним модель узнаётся как модель функции.
ОПИСАНИЯ: frozenset[str] = frozenset(
    {
        "produces_outputs", "accepts_inputs", "modes", "modalities", "modality", "capabilities",
        "positioning", "lipsync", "lipsync_support", "role", "endpoint_purpose", "best_for",
    }
)

#: КОРОТКИЕ СИНОНИМЫ СЛОВ ВОПРОСА. Закрытый список, и он тут ради того, чтобы
#: «profile» нашёл «side profiles» и «rotation», а «logo» — «trademarks».
СИНОНИМЫ: dict[str, tuple[str, ...]] = {
    "profile": ("profile", "side view", "side-view", "rotation", "head turn", "three-quarter", "yaw"),
    "профиль": ("profile", "side view", "rotation", "профил", "поворот"),
    "logo": ("logo", "trademark", "lettering", "typography", "text render", "packaging text"),
    "логотип": ("logo", "trademark", "логотип", "lettering"),
    "legible": ("legible", "readable", "text render", "lettering", "typography"),
    "text": ("text render", "typography", "lettering", "legible", "on-screen text"),
    "hands": ("hand", "finger"),
    "руки": ("hand", "finger", "рук", "пальц"),
}

#: ТРЕБОВАНИЯ — фильтр, а не свидетельство: модель без записанного требования
#: не ранжируется, а считается отдельно (`excluded_by_requirement`).
ТРЕБОВАНИЯ: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    # слово -> (в каких строках искать: семьи атрибутов, какие подстроки значения)
    "open": (("license",), ("apache", "mit", "open weight", "open-weight", "openrail", "bsd", "cc-by", "weights")),
    "russian": (("languages",), ("russian", " ru", "ru,", "(ru", "русск")),
    "english": (("languages",), ("english", " en", "en,", "(en")),
    "spanish": (("languages",), ("spanish", " es", "es,", "(es")),
}
#: Написания требований -> ключ.
ТРЕБОВАНИЯ_СИНОНИМЫ: dict[str, str] = {
    "open": "open", "open weights": "open", "open-weights": "open", "open source": "open",
    "open-source": "open", "открытые веса": "open", "открытая": "open",
    "russian": "russian", "ru": "russian", "русский": "russian", "русского": "russian",
    "english": "english", "en": "english", "spanish": "spanish", "es": "spanish",
}

#: Признаки ПЛОХОЙ новости в значении (знак строки, когда он не объявлен).
_ПЛОХО = re.compile(
    r"\b(no(?=\s+[a-z])|not|fails?|failure|struggl\w*|cannot|can't|poor|smear\w*|mutat\w*|drift\w*|break\w*|"
    r"artifact\w*|artefact\w*|limit\w*|narrow|unsupported)\b|не |плохо|ломает|плыв",
    re.IGNORECASE,
)

#: Сколько свидетельств показывать у модели (счёт печатается целиком).
СВИДЕТЕЛЬСТВ_ПОКАЗАНО = 3
#: Сколько моделей без свидетельства назвать поимённо (счёт — целиком).
ПРОБЕЛОВ_ПОКАЗАНО = 12
#: Слова вопроса, не несущие смысла поиска.
_ПУСТЫЕ = frozenset(
    {
        "which", "what", "best", "the", "a", "an", "for", "of", "and", "or", "with", "that", "is",
        "does", "do", "can", "model", "models", "handles", "handle", "keeps", "keep", "good",
        "какой", "какая", "какие", "лучший", "лучшая", "для", "и", "с", "что", "модель", "держит",
        "lipsync", "i2v", "t2v", "tts", "video", "image", "open", "russian", "faces", "face",
    }
)


def _термины(need: str, terms: str) -> list[str]:
    сырые = [т.strip().lower() for т in re.split(r"[,;]", terms or "") if т.strip()]
    if not сырые:
        сырые = [с for с in re.findall(r"[\w-]{3,}", str(need or "").lower()) if с not in _ПУСТЫЕ]
    out: list[str] = []
    for т in сырые:
        # Синонимы ЗАМЕНЯЮТ слово: «text» сам по себе ловил бы «text-to-video».
        for с in СИНОНИМЫ.get(т, (т,)):
            if с not in out:
                out.append(с)
    return out


def _требования(require: str) -> tuple[list[str], list[str]]:
    """(понятые ключи, непонятые слова). Непонятое — называется, а не глотается."""
    ключи, непонятые = [], []
    for сырое in re.split(r"[,;]", require or ""):
        слово = сырое.strip().lower()
        if not слово:
            continue
        ключ = ТРЕБОВАНИЯ_СИНОНИМЫ.get(слово)
        if ключ:
            if ключ not in ключи:
                ключи.append(ключ)
        else:
            непонятые.append(слово)
    return ключи, непонятые


def _в_функции(имя: str, строки: list[Fact], функция: str) -> bool:
    образец, слова, кроме = ФУНКЦИИ[функция]
    низ = имя.lower()
    if re.search(кроме, низ):
        return False
    if re.search(образец, низ):
        return True
    return any(
        f.attribute in ОПИСАНИЯ and any(с in str(f.value).lower() for с in слова) for f in строки
    )


def _выполнено(требование: str, строки: list[Fact]) -> list[Fact]:
    """Строки, которыми требование записано; пусто — не записано."""
    семьи, подстроки = ТРЕБОВАНИЯ[требование]
    out: list[Fact] = []
    for f in строки:
        if attrfamily.семья_имени(f.attribute) not in семьи and f.attribute not in семьи:
            continue
        низ = f" {str(f.value).lower()} "
        if требование == "open" and re.search(r"proprietary|closed|api only|api-only|no weights", низ):
            continue
        if any(п in низ for п in подстроки):
            out.append(f)
    return out


def _знак(f: Fact) -> str:
    """`bad` или `good`: объявленный знак старше вывода по слову."""
    объявлен = getattr(f, "contra", None)
    if объявлен is True:
        return "bad"
    if объявлен is False:
        return "good"
    # В семье поведения плохи по ИМЕНИ провалы и пределы; сама строка
    # `observed_behaviour` бывает и хорошей («handles side profiles») — её
    # знак читается по значению.
    if attrfamily.семья_имени(f.attribute) == "observed_behaviour" and f.attribute != "observed_behaviour":
        return "bad"
    return "bad" if _ПЛОХО.search(str(f.value)) else "good"


def _строка(f: Fact) -> dict:
    значение = " ".join(str(f.value).split())
    return {
        "attribute": f.attribute,
        "value": значение if len(значение) <= 220 else значение[:219] + "…",
        "tier": f.tier,
        "stated_on": f.stated_on,
        "source_url": f.source_url,
    }


def _ступень(f: Fact) -> int:
    return TIERS.index(f.tier) if f.tier in TIERS else len(TIERS)


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
) -> dict:
    """Модели функции, ранжированные по записанному свидетельству о `need`."""
    англ = lang != "ru"
    функция = str(function or "").strip().lower()
    if функция not in ФУНКЦИИ:
        return {
            "outcome": UNMEASURED,
            "reason": "function_unknown",
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "functions": sorted(ФУНКЦИИ),
            "note": (
                f"function {function!r} is not one of {', '.join(sorted(ФУНКЦИИ))}; nothing was searched"
                if англ
                else f"функция {function!r} не из списка ({', '.join(sorted(ФУНКЦИИ))}); поиск не делался"
            ),
            "ranked": [],
        }
    if facts is None:
        from studio.mcp.advice import store_for

        facts = store_for(path).facts
    по_модели: dict[str, list[Fact]] = {}
    класс: list[Fact] = []
    for f in facts:
        if f.model == "*" or f.model.endswith("-*"):
            класс.append(f)
        else:
            по_модели.setdefault(f.model, []).append(f)
    термины = _термины(need, terms)
    требования, непонятые = _требования(require)

    модели = sorted(m for m, строки in по_модели.items() if _в_функции(m, строки, функция))
    отсеяно: list[str] = []
    ранжировано: list[dict] = []
    без_свидетельства: list[str] = []
    for м in модели:
        строки = по_модели[м]
        по_требованию = [_выполнено(т, строки) for т in требования]
        if not all(по_требованию):
            отсеяно.append(м)
            continue
        найдено = [
            f for f in строки if термины and any(т in f"{f.attribute} {f.value}".lower() for т in термины)
        ]
        if not термины and требования:
            # Вопрос — только требования («open TTS for Russian»): свидетельство —
            # сами строки, которыми требования записаны.
            найдено = list({id(f): f for строки_т in по_требованию for f in строки_т}.values())
        if not найдено:
            без_свидетельства.append(м)
            continue
        хорошие = sorted((f for f in найдено if _знак(f) == "good"), key=_ступень)
        плохие = sorted((f for f in найдено if _знак(f) == "bad"), key=_ступень)
        ранжировано.append(
            {
                "model": м,
                "verdict": (
                    "good_news_only" if хорошие and not плохие else "mixed" if хорошие else "bad_news_only"
                ),
                "best_tier": хорошие[0].tier if хорошие else (плохие[0].tier if плохие else ""),
                "good": [_строка(f) for f in хорошие[:СВИДЕТЕЛЬСТВ_ПОКАЗАНО]],
                "bad": [_строка(f) for f in плохие[:СВИДЕТЕЛЬСТВ_ПОКАЗАНО]],
                "good_total": len(хорошие),
                "bad_total": len(плохие),
                "sources": len({f.source_url for f in найдено}),
                "_ключ": (
                    0 if хорошие and not плохие else 1 if хорошие else 2,
                    _ступень(хорошие[0]) if хорошие else len(TIERS),
                    -len({f.source_url for f in хорошие}),
                ),
                "_свежесть": max((f.stated_on for f in найдено), default=""),
            }
        )
    # Свежее — раньше при равном свидетельстве: сначала вторичный ключ, потом
    # первичный (сортировка устойчива).
    ранжировано.sort(key=lambda r: r["model"])
    ранжировано.sort(key=lambda r: r["_свежесть"], reverse=True)
    ранжировано.sort(key=lambda r: r["_ключ"])
    for r in ранжировано:
        r.pop("_ключ")
        r.pop("_свежесть")
    с_хорошей = [r for r in ранжировано if r["good_total"]]
    о_классе = [
        {"scope": f.model, **_строка(f)}
        for f in класс
        if термины and any(т in f"{f.attribute} {f.value}".lower() for т in термины)
    ][:СВИДЕТЕЛЬСТВ_ПОКАЗАНО * 2]
    показано = ранжировано[: max(1, int(top or 8))]
    итог_pass = bool(с_хорошей)
    if англ:
        нота = (
            f"{len(модели)} model(s) of function {функция!r} in the base; "
            + (f"{len(отсеяно)} dropped for lacking a recorded {', '.join(требования)}; " if требования else "")
            + f"{len(ранжировано)} have rows about {', '.join(термины[:6]) or '(no terms)'}, "
            f"{len(с_хорошей)} of them with good news; {len(без_свидетельства)} have NOTHING recorded on it. "
            + (
                "Ranked by evidence (good news without bad first, then best tier, sources, freshness) — "
                "NOT by quality: a model with no row may be better and simply unmeasured."
                if итог_pass
                else "No model has recorded good news on this, which is a gap in the base, not proof that "
                "none can: search the web and record what you find with record_model_fact."
            )
            + " Before recommending any name, call model_advice on it."
            + (f" Not understood as a requirement (ignored): {', '.join(непонятые)}." if непонятые else "")
        )
    else:
        нота = (
            f"моделей функции {функция!r} в базе: {len(модели)}; "
            + (f"отсеяно без записанного требования ({', '.join(требования)}): {len(отсеяно)}; " if требования else "")
            + f"со строками о {', '.join(термины[:6]) or '(слов нет)'}: {len(ранжировано)}, из них с хорошей "
            f"новостью {len(с_хорошей)}; НИЧЕГО не записано у {len(без_свидетельства)}. "
            + (
                "Порядок — по свидетельству (сначала хорошая новость без плохой, потом ступень, источники, "
                "свежесть), а НЕ по качеству: модель без строки может быть лучше, просто её не мерили."
                if итог_pass
                else "Хорошей новости не записано ни у одной модели — это пробел базы, а не доказательство, "
                "что не умеет никто: поищите в сети и запишите найденное через record_model_fact."
            )
            + " Прежде чем назвать модель, спросите о ней model_advice."
            + (f" Не понято как требование (не учтено): {', '.join(непонятые)}." if непонятые else "")
        )
    return {
        "outcome": PASS if итог_pass else UNMEASURED,
        "reason": "ranked_by_evidence" if итог_pass else ("no_good_news" if ранжировано else "no_evidence"),
        "checked": len(модели),
        "violations": 0,
        "unmeasured": len(без_свидетельства) + (0 if итог_pass else 1),
        "function": функция,
        "terms": термины,
        "require": требования,
        "require_not_understood": непонятые,
        "note": нота,
        "ranked": показано,
        "ranked_total": len(ранжировано),
        "gaps": {
            "models_without_evidence": len(без_свидетельства),
            "examples": без_свидетельства[:ПРОБЕЛОВ_ПОКАЗАНО],
            "excluded_by_requirement": len(отсеяно),
            "excluded_examples": отсеяно[:ПРОБЕЛОВ_ПОКАЗАНО],
        },
        "class_findings": о_классе,
    }


def describe_functions() -> list[str]:
    return sorted(ФУНКЦИИ)


__all__ = ["ФУНКЦИИ", "find", "describe_functions"]
