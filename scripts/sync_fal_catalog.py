#!/usr/bin/env python3
"""Синхронизация с каталогом fal.ai: что продаётся, что принимает, сколько стоит.

    python scripts/sync_fal_catalog.py            # dry-run: что было бы записано
    python scripts/sync_fal_catalog.py --apply    # записать через advice.record
    python scripts/sync_fal_catalog.py --check    # офлайн: связность записанного

ЗАЧЕМ

`ingest_portal.py` и `ingest_schema.py` читают портал по словам «lipsync,
avatar, talking» и по списку эндпоинтов, названному руками. Студии нужен
весь медийный ряд — видео, видео со звуком, изображение, речь, музыка,
апскейл, — и тот, кто сравнивает кандидатов, обязан знать, что на портале
есть сегодня, по какой цене и что эндпоинт берёт на вход.

КАТАЛОГ — ПОВОД ПРОЧИТАТЬ, А НЕ ПОВОД ЗАПИСАТЬ (решение владельца 2026-08-31,
`studio/mcp/catalog.py`, гейт `check_catalog.py`). Поэтому:

  * каталог (`api.fal.ai/v1/models`) только перечисляет эндпоинты и в базу
    фактов не пишется НИ ОДНОЙ строкой — это индекс;
  * записывается только то, что сказано на СТРАНИЦЕ эндпоинта
    (`fal.ai/models/<id>`: статус, цена словами портала, единица биллинга) и в
    его OpenAPI (`fal.ai/api/openapi/...`), то есть прочитанное;
  * и только для семейств, о которых студию спрашивают (`СЕМЕЙСТВА`), а не для
    всех ~1500 эндпоинтов. Полный обход печатается в dry-run как разница
    «есть на портале / нет в базе» — очередь на чтение, а не на запись.

ИМЯ МОДЕЛИ. Эндпоинт `fal-ai/veo3.1/fast/image-to-video` — это вариант
`veo-3.1-fast-i2v` семьи `veo-3.1`. Один эндпоинт — одно имя, потому что у
разных эндпоинтов одной семьи разные цены и входы, и под одним именем они
читались бы как «источники расходятся» (`FactStore._by_venue`: одна площадка,
два значения — спор). Порядок разрешения:

  1. эндпоинт уже стоит в базе (по адресу его страницы или схемы) — берётся
     то имя, под которым он записан (Е1: одно имя на эндпоинт);
  2. иначе имя строится по таблице семейств и проходит слой имён
     (`advice.каноническое_имя`), как любой record;
  3. эндпоинт вне таблицы — имя из адреса (`modelnames.from_portal_id`), и в
     ноте строки так и сказано.

ТИР решает адрес (`source_hosts.classify`), а не скрипт. Цена из pricing API
в базу не пишется: она только сверяется с ценой на странице, расхождение
печатается. (До 2026-10-15 `api.fal.ai` не числился в таблице хостов вовсе;
с тех пор он `portal`, как `fal.ai`, — но писать ли его цену отдельной
строкой рядом с ценой страницы, это решение не этой правки.)

ИДЕМПОТЕНТНОСТЬ. record с тем же (модель, атрибут, значение, адрес) — это
обновление, а не вторая строка; в тот же день повтор не дописывает ничего.
Если ЭТОТ ЖЕ адрес раньше говорил другое значение (цена поменялась), прежнее
утверждение отзывается (`advice.withdraw`) с причиной, иначе одна площадка
говорила бы два значения разом.

ТРИ ИСХОДА (Р1): 0 годно / 1 не годно / 2 не смогли.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import dataclasses
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any, Callable, Iterable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402
from scripts import ingest_portal, ingest_schema  # noqa: E402
from studio.selfrag import modelnames, source_hosts  # noqa: E402

КАТАЛОГ = "https://api.fal.ai/v1/models?limit=100{курсор}"
ЦЕНЫ = "https://api.fal.ai/v1/models/pricing?{запрос}"
СТРАНИЦА = ingest_portal.СТРАНИЦА
СХЕМА = ingest_schema.СХЕМА

#: Категории каталога, которые студия считает медийными. Остальные (llm,
#: vision, 3d, training, speech-to-text) к выбору генератора не относятся.
МЕДИА: frozenset[str] = frozenset(
    {
        "text-to-image",
        "image-to-image",
        "image-to-video",
        "text-to-video",
        "video-to-video",
        "text-to-audio",
        "text-to-speech",
        "audio-to-video",
        "speech-to-video",
        "audio-to-audio",
    }
)

#: Куски пути, после которых эндпоинт — не модель, а надстройка: обучение,
#: LoRA-вариант той же модели, стилевой пресет. Их цена и вход совпадают с
#: базовой моделью или говорят о другом продукте.
НЕ_МОДЕЛЬ: frozenset[str] = frozenset({"lora", "trainer", "styles", "realtime"})

#: Как площадка называет режим — как его пишет база (`veo-3.1-i2v`,
#: `kling-3.0-pro-i2v`). Неизвестный кусок остаётся как есть.
РЕЖИМЫ: dict[str, str] = {
    "text-to-video": "t2v",
    "image-to-video": "i2v",
    "reference-to-video": "r2v",
    "first-last-frame-to-video": "flf2v",
    "keyframes-to-video": "keyframes",
    "audio-to-video": "a2v",
    "video-to-video": "v2v",
    "extend-video": "extend",
    "edit-video": "edit-video",
    "edit-image": "edit",
    "text-to-audio": "t2a",
    "image-to-image": "edit",
    "video-edit": "edit-video",
    "text-to-image": "t2i",
    "text-to-speech": "tts",
}

#: Режимы, которые у чисто картиночной (или чисто речевой) семьи — сама
#: модель, а не вариант: база пишет `nano-banana-pro`, а не `...-t2i`.
БАЗОВЫЙ_РЕЖИМ: frozenset[str] = frozenset({"text-to-image", "text-to-speech"})


@dataclass(frozen=True)
class Семья:
    """Префикс пути эндпоинта (без `fal-ai/`) -> id семьи в базе."""

    путь: tuple[str, ...]
    имя: str
    #: True — семья делает один вид медиа, и базовый режим не пишется в имя.
    однородная: bool = False
    #: Чего портал не говорит и что поэтому не угадывается (версия, ревизия).
    оговорка: str = ""


#: СЕМЕЙСТВА, О КОТОРЫХ СПРАШИВАЮТ. Список закрытый: это ровно перечень
#: пробелов, названных валидатором продукта 2026-10-14, плюс апскейлеры. Длинный
#: префикс стоит раньше короткого (`h3-max-turbo` раньше `h3-max`).
СЕМЕЙСТВА: tuple[Семья, ...] = (
    Семья(("veo3.1",), "veo-3.1"),
    Семья(("kling-video", "ai-avatar", "v2"), "kling-video-ai-avatar-v2", True),
    Семья(("kling-video", "v3"), "kling-3.0"),
    Семья(("kling-video", "o3"), "kling-video-o3"),
    Семья(("bytedance", "seedance-2.0"), "seedance-2.0"),
    Семья(("bytedance", "seedance-2.5"), "seedance-2.5"),
    Семья(("minimax", "h3-max-turbo"), "minimax-h3-max-turbo"),
    Семья(("minimax", "h3-max"), "minimax-h3-max"),
    Семья(("minimax", "h3"), "minimax-h3"),
    Семья(("minimax", "hailuo-2.3-fast"), "minimax-hailuo-2.3-fast"),
    Семья(("minimax", "hailuo-2.3"), "minimax-hailuo-2.3"),
    Семья(("minimax", "speech-2.6-hd"), "minimax-speech-2.6-hd", True),
    Семья(("minimax", "speech-2.6-turbo"), "minimax-speech-2.6-turbo", True),
    Семья(("minimax", "speech-2.8-hd"), "minimax-speech-2.8-hd", True),
    Семья(("minimax", "speech-2.8-turbo"), "minimax-speech-2.8-turbo", True),
    Семья(("wan", "v2.6"), "wan-2.6"),
    Семья(("wan", "v2.7"), "wan-2.7"),
    Семья(("alibaba", "wan-3.0-prime"), "wan-3.0-prime"),
    Семья(("alibaba", "wan-3.0"), "wan-3.0"),
    Семья(
        ("alibaba", "happy-horse"),
        "happy-horse",
        оговорка="версию эндпоинта без номера портал не называет («Happy Horse»), имя оставлено по адресу",
    ),
    Семья(("ltx-2.3-22b",), "ltx-2.3-22b"),
    Семья(("ltx-2.3-quality",), "ltx-2.3-quality"),
    Семья(("ltx-2.3",), "ltx-2.3"),
    Семья(("lightricks", "ltx-2.5"), "ltx-2.5"),
    Семья(("openai", "gpt-image-2.5", "flare"), "gpt-image-2.5-flare", True),
    Семья(("openai", "gpt-image-2.5", "sunburst"), "gpt-image-2.5-sunburst", True),
    Семья(("openai", "gpt-image-2"), "gpt-image-2", True),
    Семья(("nano-banana-2",), "nano-banana-2", True),
    Семья(("nano-banana-pro",), "nano-banana-pro", True),
    Семья(("google", "nano-banana-2.1"), "nano-banana-2.1", True),
    Семья(("google", "nano-banana-2-lite"), "nano-banana-2-lite", True),
    Семья(("flux-2-pro",), "flux-2-pro", True),
    Семья(("flux-2-max",), "flux-2-max", True),
    Семья(("flux-2-flex",), "flux-2-flex", True),
    Семья(("blackforestlabs", "flux-3"), "flux-3"),
    Семья(("bytedance", "seedream", "v5"), "seedream-5", True),
    Семья(("bytedance", "seedream", "v4.5"), "seedream-4.5", True),
    Семья(
        ("google", "gemini-omni-flash"),
        "gemini-omni-flash",
        оговорка="эндпоинт без номера версии портал называет просто «Gemini Omni Flash»",
    ),
    Семья(
        ("xai", "grok-imagine-video"),
        "xai-grok-imagine-video",
        оговорка="эндпоинт без номера версии портал называет просто «Grok Imagine Video»",
    ),
    Семья(("bytedance", "omnihuman", "v1.5"), "omnihuman-1.5", True),
    Семья(("infinitalk",), "infinitalk", True),
    Семья(("sync-lipsync",), "sync-lipsync", True),
    Семья(("latentsync",), "latentsync", True),
    Семья(("veed", "lipsync"), "veed-lipsync", True),
    Семья(("veed", "fabric-1.0"), "veed-fabric-1.0"),
    Семья(("heygen", "v3", "lipsync"), "heygen-v3-lipsync", True),
    Семья(("heygen", "avatar4"), "heygen-avatar4"),
    Семья(("elevenlabs", "tts", "eleven-v3"), "eleven_v3", True),
    Семья(("elevenlabs", "text-to-dialogue", "eleven-v3"), "eleven-v3-dialogue", True),
    Семья(("elevenlabs", "music"), "elevenlabs-music", True),
    Семья(("elevenlabs", "sound-effects"), "elevenlabs-sound-effects", True),
    Семья(("chatterbox", "text-to-speech", "multilingual"), "chatterbox-multilingual", True),
    Семья(
        ("seedvr", "upscale"),
        "seedvr2-upscale",
        True,
        оговорка="портал пишет seedvr; что это SeedVR2 — по семейству в базе (seedvr2-3b/7b), не по странице",
    ),
    Семья(("topaz", "upscale"), "topaz-upscale", True),
    # 2026-10-15, раунд 5: семьи, которые планировщик ВЫБИРАЕТ, а цены у них в
    # базе нет (hunyuan, правка nano-banana). Длинный префикс раньше короткого:
    # `hunyuan-video-v1.5` раньше `hunyuan-video`.
    #
    # ФОН, ИНТЕРПОЛЯЦИЯ, КОЛОРИЗАЦИЯ И ДУБЛЯЖ СЮДА НАРОЧНО НЕ ВЗЯТЫ. Их обход
    # пишет входы/выходы из схемы, а планировщик (на 2026-10-15) выбирает
    # кандидата по виду входа и выхода и не знает этих операций: с такими
    # строками BiRefNet встал на «генерацию изображения», а дубляж ElevenLabs —
    # на «озвучку» (бриф «Photo of our founder…» из l10n_battery). Их цены и
    # доступность записаны разово (2026-10-15), входы/выходы отозваны с
    # причиной. Вернуть семьи сюда — вместе с операциями в планировщике.
    Семья(("hunyuan-video-v1.5",), "hunyuanvideo-1.5"),
    Семья(("hunyuan-video-image-to-video",), "hunyuanvideo-i2v", True),
    Семья(("hunyuan-video",), "hunyuan-video"),
    Семья(("nano-banana", "edit"), "nano-banana-edit", True),
)

#: Апскейлеры ловятся по слову в пути, а не списком: их на портале больше
#: дюжины от разных вендоров, и вопрос «чем увеличить» задают про все.
АПСКЕЙЛ = re.compile(r"upscal|super-?resolution", re.I)

ПЛОЩАДКИ = ("fal-ai", "fal")

#: Кусок пути, который называет ступень или версию, а не операцию.
ВЕРСИЯ = re.compile(r"^v\d+(?:\.\d+)*$")
СТУПЕНЬ = re.compile(
    r"^(?:v\d+(?:\.\d+)*|fast|lite|pro|standard|mini|turbo|max|flash|us|4k|hd|draft|master)$"
)


def звенья(эндпоинт: str) -> list[str]:
    """Путь эндпоинта без префикса площадки."""
    куски = [к for к in str(эндпоинт or "").strip().strip("/").split("/") if к]
    if куски and куски[0] in ПЛОЩАДКИ:
        куски = куски[1:]
    return куски


def семья_эндпоинта(эндпоинт: str) -> Семья | None:
    куски = звенья(эндпоинт)
    for с in СЕМЕЙСТВА:
        if tuple(куски[: len(с.путь)]) == с.путь:
            return с
    return None


def в_охвате(эндпоинт: str, категория: str) -> bool:
    """Эндпоинт из тех, о которых спрашивают, и он — модель, а не надстройка."""
    if категория not in МЕДИА:
        return False
    куски = звенья(эндпоинт)
    if any(к in НЕ_МОДЕЛЬ for к in куски):
        return False
    return семья_эндпоинта(эндпоинт) is not None or bool(АПСКЕЙЛ.search(эндпоинт))


def имя_по_таблице(эндпоинт: str, категория: str = "") -> tuple[str, str]:
    """(имя-кандидат, нота). Нота непуста, когда имя взято из адреса или есть оговорка."""
    с = семья_эндпоинта(эндпоинт)
    if с is None:
        return (
            modelnames.from_portal_id(эндпоинт),
            "имя взято из адреса эндпоинта: семья в таблице не названа",
        )
    хвост: list[str] = []
    for кусок in звенья(эндпоинт)[len(с.путь) :]:
        if с.однородная and кусок in БАЗОВЫЙ_РЕЖИМ:
            continue
        # Номер версии в пути (`v1.5`, `v2`) пишется как в базе: `-v1.5`.
        хвост.append(РЕЖИМЫ.get(кусок, кусок))
    # ГОЛЫЙ ЭНДПОИНТ МНОГОРЕЖИМНОЙ СЕМЬИ (`fal-ai/veo3.1` — это text-to-video,
    # `fal-ai/veo3.1/fast` — тоже) получает режим из категории: иначе схема
    # одного режима легла бы на всю семью, и «принимает: текст» читалось бы как
    # «картинку не берёт». Только когда в хвосте одни ступени и версии: у
    # `ltx-2.3-quality/deblur` своё имя операции, и `-v2v` к нему ничего не
    # добавит.
    режим = РЕЖИМЫ.get(категория, "")
    if not с.однородная and режим and all(СТУПЕНЬ.match(к) for к in хвост):
        хвост.append(режим)
    оговорка = с.оговорка if not any(ВЕРСИЯ.match(к) for к in хвост) else ""
    return "-".join([с.имя, *хвост]), оговорка


def эндпоинт_из_адреса(url: str) -> str:
    """Какой эндпоинт fal назван в адресе строки базы. Пусто — не fal."""
    адрес = str(url or "")
    м = re.search(r"[?&]endpoint_id=([^&#\s]+)", адрес)
    if м and "fal.ai/" in адрес:
        return м.group(1).strip("/")
    м = re.match(r"https?://fal\.ai/models/([^?#\s]+)", адрес)
    if м:
        return м.group(1).strip("/")
    return ""


def имена_в_базе(факты: Iterable[Any]) -> dict[str, str]:
    """Эндпоинт -> имя, под которым он уже записан. Чаще встречающееся — первым."""
    счёт: dict[str, dict[str, int]] = {}
    for ф in факты:
        э = эндпоинт_из_адреса(str(getattr(ф, "source_url", "")))
        if э:
            по_имени = счёт.setdefault(э, {})
            по_имени[ф.model] = по_имени.get(ф.model, 0) + 1
    return {э: max(имена.items(), key=lambda п: (п[1], п[0]))[0] for э, имена in счёт.items()}


Разрешитель = Callable[[str], tuple[str, str]]


def разрешить_имя(
    эндпоинт: str, известные: dict[str, str], разрешитель: Разрешитель, категория: str = ""
) -> tuple[str, bool, str]:
    """(имя, new_model, нота). Порядок — в докстроке модуля."""
    кандидат, нота = имя_по_таблице(эндпоинт, категория)
    с = семья_эндпоинта(эндпоинт)
    корень = разрешитель(с.имя)[0] if с is not None and not с.однородная else ""
    известное = известные.get(эндпоинт, "")
    # Шаг 1, с одним исключением: эндпоинт, записанный когда-то под ИМЕНЕМ
    # ВСЕЙ СЕМЬИ (`fal-ai/veo3.1` -> `veo-3.1`), этим именем не продолжается —
    # иначе вход одного режима так и лёг бы на всю семью.
    if известное and известное != корень:
        return известное, False, ""
    имя, отказ = разрешитель(кандидат)
    if not отказ:
        return имя, False, нота
    # Слой имён отказал: имя совпало с известным только через соседа. Это
    # вариант эндпоинта, а не опечатка — у соседа другой путь на портале
    # (иначе сработал бы шаг 1). Пишется как новая модель, и это сказано.
    return (
        кандидат,
        True,
        (нота + "; " if нота else "")
        + "слой имён назвал соседа, но у этого эндпоинта свой путь на портале — записан как отдельный вариант",
    )


# --- сеть --------------------------------------------------------------------

Ответ = dict[str, Any]
Получатель = Callable[[str, dict[str, str] | None], Ответ]


def получатель_по_умолчанию(url: str, заголовки: dict[str, str] | None) -> Ответ:
    from studio.mcp import fetch

    return fetch.fetch(
        url,
        why_wanted="каталог и цены fal.ai для базы моделей студии",
        max_bytes=3_000_000,
        headers=заголовки,
    )


def спросить(
    получатель: Получатель,
    url: str,
    заголовки: dict[str, str] | None = None,
    *,
    пауза: float = 1.0,
    повторов: int = 4,
) -> Ответ:
    """Один запрос с повтором на 429 и на обрыв. Отказ политики не повторяется."""
    ответ: Ответ = {}
    for попытка in range(повторов + 1):
        ответ = получатель(url, заголовки)
        if ответ.get("outcome") == PASS or ответ.get("denied"):
            return ответ
        статус = ответ.get("status")
        if статус is not None and статус != 429:
            return ответ
        if попытка < повторов:
            time.sleep(пауза * (2**попытка))
    return ответ


def схема(
    получатель: Получатель, эндпоинт: str, *, пауза: float = 0.3
) -> tuple[str, dict[str, Any] | None]:
    """OpenAPI эндпоинта, разобранный так же, как у `ingest_schema` (Е1).

    Свой запрос, а не `ingest_schema.спросить`: тот ходит в сеть напрямую, а
    здесь весь обход идёт через один получатель — его подменяет тест.
    """
    ответ = спросить(получатель, СХЕМА.format(эндпоинт=эндпоинт), пауза=пауза)
    if ответ.get("outcome") != PASS:
        return UNMEASURED, None
    try:
        разобрано = json.loads(str(ответ.get("text") or ""))
    except ValueError:
        return FAIL, None
    вход = ingest_schema.схема_входа(разобрано) if isinstance(разобрано, dict) else None
    if вход is None:
        return FAIL, None
    вход = dict(вход)
    вход["_выход"] = ingest_schema.схема_выхода(разобрано) or {}
    return PASS, вход


def каталог(получатель: Получатель, пауза: float = 0.2) -> tuple[list[dict[str, Any]], str]:
    """Весь каталог. Вторым — причина неполноты (пусто — прочитан весь)."""
    модели: list[dict[str, Any]] = []
    курсор = ""
    for _ in range(200):
        ответ = спросить(
            получатель, КАТАЛОГ.format(курсор=f"&cursor={курсор}" if курсор else ""), пауза=пауза
        )
        if ответ.get("outcome") != PASS:
            return модели, f"каталог оборвался после {len(модели)}: {ответ.get('note')}"
        try:
            тело = json.loads(str(ответ.get("text") or ""))
        except ValueError:
            return модели, "каталог ответил не JSON"
        модели.extend(тело.get("models") or [])
        if not тело.get("has_more"):
            return модели, ""
        курсор = str(тело.get("next_cursor") or "")
        time.sleep(пауза)
    return модели, "каталог не кончился за 200 страниц"


def цены_api(
    получатель: Получатель, эндпоинты: list[str], ключ: str, пауза: float = 1.0
) -> tuple[dict[str, dict[str, Any]], int]:
    """Цены pricing API пачками; пачка с несуществующим id делится пополам.

    Ключ идёт только в заголовок и нигде не печатается.
    """
    if not ключ:
        return {}, len(эндпоинты)
    заголовки = {"Authorization": f"Key {ключ}"}
    цены: dict[str, dict[str, Any]] = {}
    не_смогли = 0
    очередь = [эндпоинты[i : i + 40] for i in range(0, len(эндпоинты), 40)]
    while очередь:
        пачка = очередь.pop(0)
        запрос = "&".join(f"endpoint_id={э}" for э in пачка)
        ответ = спросить(получатель, ЦЕНЫ.format(запрос=запрос), заголовки, пауза=пауза)
        time.sleep(пауза)
        if ответ.get("outcome") == PASS:
            try:
                for р in json.loads(str(ответ.get("text") or "")).get("prices") or []:
                    цены[str(р.get("endpoint_id"))] = р
            except ValueError:
                не_смогли += len(пачка)
            continue
        if ответ.get("status") == 404 and len(пачка) > 1:
            середина = len(пачка) // 2
            очередь[:0] = [пачка[:середина], пачка[середина:]]
            continue
        не_смогли += len(пачка)
    return цены, не_смогли


#: Поля страницы модели, которые читаются. Страница — Next.js, данные лежат в
#: экранированном JSON внутри скрипта; берутся только перечислимые поля.
_ПОЛЕ_СТРОКИ = r'\\"{имя}\\":\\"((?:[^\\\\]|\\\\.)*?)\\"(?=[,}}\]])'
_ПОЛЕ_ЛОГИЧЕСКОЕ = r'\\"{имя}\\":(true|false)'
_БИЛЛИНГ = re.compile(
    r'\\"publicEndpointBilling\\":\{\\"endpoint\\":\\"([^"\\]+)\\",'
    r'\\"billing_unit\\":\\"([^"\\]*)\\",\\"price\\":([0-9.eE+-]+)'
)


def _строка(страница: str, имя: str) -> str:
    """Строковое поле из дважды экранированного JSON страницы (JS поверх JSON)."""
    м = re.search(_ПОЛЕ_СТРОКИ.format(имя=re.escape(имя)), страница)
    if not м:
        return ""
    текст = м.group(1)
    for _ in range(2):
        try:
            текст = str(json.loads('"' + текст + '"'))
        except ValueError:
            break
    return текст


def разобрать_страницу(страница: str, эндпоинт: str) -> dict[str, Any]:
    """Статус, цена словами портала и единица биллинга со страницы эндпоинта."""
    out: dict[str, Any] = {}
    for имя in ("status", "pricingInfoOverride", "category"):
        out[имя] = _строка(страница, имя)
    for имя in ("deprecated", "removed", "hidePricing"):
        м = re.search(_ПОЛЕ_ЛОГИЧЕСКОЕ.format(имя=re.escape(имя)), страница)
        out[имя] = None if not м else м.group(1) == "true"
    out["billing"] = None
    for м in _БИЛЛИНГ.finditer(страница):
        if м.group(1) == эндпоинт:
            out["billing"] = {"unit": м.group(2), "price": float(м.group(3))}
            break
    return out


# --- находки -----------------------------------------------------------------

#: Единица биллинга портала -> «за что» в имени атрибута, которое понимает
#: `studio/pricing.py` (`unit_and_per` читает имя, а не текст).
ЗА_ЧТО: dict[str, str] = {
    "seconds": "second",
    "second": "second",
    "images": "image",
    "image": "image",
    "megapixels": "megapixel",
    "minutes": "minute",
    "videos": "generation",
    "requests": "generation",
    "generations": "generation",
    # «units» НАРОЧНО НЕ ЗДЕСЬ (2026-10-15, независимый валидатор). Здесь стояло
    # `"units": "run"`, и 43 строки базы читались «за прогон»: `gpt-image-2.5-
    # flare` «$1 per unit» выходил долларом за картинку, хотя та же модель у fal
    # стоит $0.04 за кадр 1920x1080. «Unit» у fal — единица тарификации, которую
    # страница не раскрывает (токены, мегапиксели, доли прогона), а не прогон.
    # Незнакомая единица уходит в `price_unit_usd` с подписью «billing unit
    # 'units'», и `studio/pricing.py` честно не находит «за что» (третий исход).
    "1000 characters": "1000_chars",
    "characters": "1000_chars",
}


@dataclass
class Находка:
    модель: str
    атрибут: str
    значение: str
    url: str
    нота: str
    new_model: bool = False


@dataclass
class Отчёт:
    эндпоинтов: int = 0
    медийных: int = 0
    в_охвате: int = 0
    страниц: int = 0
    схем: int = 0
    не_смогли: list[str] = field(default_factory=list)
    расхождения_цен: list[str] = field(default_factory=list)
    находки: list[Находка] = field(default_factory=list)
    вне_базы: list[str] = field(default_factory=list)


def атрибут_цены_биллинга(единица: str) -> str:
    за = ЗА_ЧТО.get(единица.strip().lower(), "")
    return f"price_unit_{за}_usd" if за else "price_unit_usd"


def находки_страницы(
    модель: str, эндпоинт: str, категория: str, разбор: dict[str, Any], api: dict[str, Any] | None
) -> tuple[list[Находка], str]:
    """Находки со страницы эндпоинта; вторым — расхождение с pricing API."""
    url = СТРАНИЦА.format(идентификатор=эндпоинт)
    out: list[Находка] = []
    статус = str(разбор.get("status") or "")
    состояние = []
    if разбор.get("deprecated"):
        состояние.append("deprecated")
    if разбор.get("removed"):
        состояние.append("removed")
    значение = f"on fal.ai as {эндпоинт} ({категория}); listing status {статус or 'not stated'}"
    if состояние:
        значение += "; marked " + " and ".join(состояние)
    out.append(
        Находка(
            модель,
            "availability",
            значение,
            url,
            "страница эндпоинта fal.ai: status/deprecated/removed",
        )
    )

    текст = ingest_portal.цена(
        {
            "hidePricing": разбор.get("hidePricing"),
            "pricingInfoOverride": разбор.get("pricingInfoOverride"),
        }
    )
    if текст:
        out.append(
            Находка(
                модель,
                ingest_portal.атрибут_цены(текст),
                текст,
                url,
                "цена словами страницы эндпоинта fal.ai (pricingInfoOverride)",
            )
        )
    расхождение = ""
    биллинг = разбор.get("billing")
    # Нулевая цена биллинга — не «бесплатно»: у эндпоинтов с оплатой за
    # compute-секунды страница отдаёт 0, а pricing API — настоящую ставку
    # (ИЗМЕРЕНО 2026-10-14: fal-ai/creative-upscaler, 0 против 0.00125).
    if биллинг and not разбор.get("hidePricing") and float(биллинг["price"]) > 0:
        единица = str(биллинг["unit"])
        цена = float(биллинг["price"])
        сверка = "pricing API не спрошен"
        if api is not None:
            цена_api = float(api.get("unit_price") or -1)
            единица_api = str(api.get("unit") or "")
            if abs(цена_api - цена) < 1e-9 and единица_api == единица:
                сверка = f"pricing API согласен ({цена_api:g} USD / {единица_api})"
            else:
                сверка = f"pricing API говорит иначе: {цена_api:g} / {единица_api}"
                расхождение = (
                    f"{эндпоинт}: страница {цена:g}/{единица}, API {цена_api:g}/{единица_api}"
                )
        out.append(
            Находка(
                модель,
                атрибут_цены_биллинга(единица),
                f"${цена:g} per {единица.rstrip('s') if единица.endswith('s') else единица}"
                + ("" if ЗА_ЧТО.get(единица.lower()) else f" (billing unit {единица!r})"),
                url,
                f"единица биллинга со страницы эндпоинта fal.ai (publicEndpointBilling); {сверка}",
            )
        )
    return out, расхождение


#: Поля схемы, по которым узнаётся включаемый звук на выходе. Только имена,
#: увиденные в живых схемах 2026-10-14 (`generate_audio` у Veo/Seedance/Kling).
ПОЛЯ_ЗВУКА: tuple[str, ...] = ("generate_audio", "enable_audio", "with_audio", "audio_enabled")
ПОЛЯ_ОПОР = re.compile(r"^(reference_)?image_urls$|^reference_image_urls$|^elements$", re.I)


def находки_схемы(модель: str, эндпоинт: str, вход: dict[str, Any]) -> list[Находка]:
    """Находки OpenAPI: то, что пишет `ingest_schema`, плюс звук, негатив, опоры."""
    url = СХЕМА.format(эндпоинт=эндпоинт)
    out = [
        Находка(модель, атрибут, значение, url, нота)
        for _имя, атрибут, значение, _u, нота in ingest_schema.заявки(эндпоинт, вход)
    ]
    поля: dict[str, Any] = вход.get("properties") or {}
    нота = f"OpenAPI входа эндпоинта {эндпоинт}"
    if "negative_prompt" in поля:
        out.append(
            Находка(
                модель,
                "negative_prompt",
                "accepted — the endpoint schema has a negative_prompt field",
                url,
                нота,
            )
        )
    for имя in ПОЛЯ_ЗВУКА:
        if имя in поля:
            по_умолчанию = (поля.get(имя) or {}).get("default")
            out.append(
                Находка(
                    модель,
                    "audio_output",
                    f"native audio switch: schema field {имя}"
                    + ("" if по_умолчанию is None else f" (default {json.dumps(по_умолчанию)})"),
                    url,
                    нота,
                )
            )
            break
    for имя, тело in поля.items():
        if ПОЛЯ_ОПОР.match(имя) and isinstance(тело, dict) and тело.get("maxItems"):
            out.append(
                Находка(
                    модель,
                    "max_reference_images",
                    f"{тело['maxItems']} (schema field {имя} maxItems)",
                    url,
                    нота,
                )
            )
            break
    длительность = поля.get("duration") or {}
    if isinstance(длительность, dict) and not длительность.get("enum"):
        мин, макс = длительность.get("minimum"), длительность.get("maximum")
        if мин is not None and макс is not None:
            out.append(
                Находка(
                    модель,
                    "duration_range_seconds",
                    f"{мин}–{макс} (schema field duration)",
                    url,
                    нота,
                )
            )
    пропорции = (поля.get("aspect_ratio") or {}).get("enum")
    if пропорции:
        out.append(
            Находка(модель, "aspect_ratio_enum", ", ".join(str(п) for п in пропорции), url, нота)
        )
    return out


def собрать(
    получатель: Получатель,
    разрешитель: Разрешитель,
    известные: dict[str, str],
    ключ: str,
    *,
    дополнительно: dict[str, str] | None = None,
    пауза: float = 0.3,
    предел: int = 0,
) -> Отчёт:
    """Обход: каталог -> охват -> страница и схема каждого эндпоинта охвата."""
    отчёт = Отчёт()
    модели, неполнота = каталог(получатель, пауза=пауза)
    if неполнота:
        отчёт.не_смогли.append(неполнота)
    отчёт.эндпоинтов = len(модели)
    категории: dict[str, str] = {}
    for м in модели:
        э = str(м.get("endpoint_id") or "")
        к = str((м.get("metadata") or {}).get("category") or "")
        if э:
            категории[э] = к
    отчёт.медийных = sum(1 for к in категории.values() if к in МЕДИА)
    отчёт.вне_базы = sorted(
        э for э, к in категории.items() if к in МЕДИА and э not in известные and not в_охвате(э, к)
    )
    охват = sorted(э for э, к in категории.items() if в_охвате(э, к))
    for э, к in (дополнительно or {}).items():
        if э not in категории:
            охват.append(э)
            категории[э] = к
    if предел:
        охват = охват[:предел]
    отчёт.в_охвате = len(охват)

    цены, без_цены = цены_api(получатель, охват, ключ, пауза=1.0 if пауза > 0 else 0.0)
    if без_цены:
        отчёт.не_смогли.append(f"pricing API не ответил о {без_цены} эндпоинтах")

    for э in охват:
        модель, новая, нота_имени = разрешить_имя(э, известные, разрешитель, категории.get(э, ""))
        страница = спросить(получатель, СТРАНИЦА.format(идентификатор=э), пауза=пауза)
        time.sleep(пауза)
        находки: list[Находка] = []
        if страница.get("outcome") == PASS:
            отчёт.страниц += 1
            разбор = разобрать_страницу(str(страница.get("text") or ""), э)
            категория = категории.get(э) or str(разбор.get("category") or "")
            с_цены, расхождение = находки_страницы(модель, э, категория, разбор, цены.get(э))
            находки.extend(с_цены)
            if расхождение:
                отчёт.расхождения_цен.append(расхождение)
        else:
            отчёт.не_смогли.append(f"страница {э}: {страница.get('note')}")
        исход, вход = схема(получатель, э, пауза=пауза)
        if исход == PASS and вход is not None:
            отчёт.схем += 1
            находки.extend(находки_схемы(модель, э, вход))
        else:
            отчёт.не_смогли.append(f"схема {э}: {исход}")
        for н in находки:
            н.new_model = новая
            if нота_имени:
                н.нота = f"{н.нота}; {нота_имени}"
        отчёт.находки.extend(находки)
    return отчёт


# --- запись ------------------------------------------------------------------


#: Метки ноты, по которым строка узнаётся как строка ЭТОГО канала (или его
#: соседа `ingest_schema`, чью находку он повторяет той же функцией). Только
#: такие строки канал вправе отозвать при пересинхронизации: чужую строку с того
#: же адреса он не трогает, а о споре с ней сообщает.
МЕТКИ_КАНАЛА: tuple[str, ...] = (
    "страница эндпоинта fal.ai",
    "цена словами страницы эндпоинта fal.ai",
    "единица биллинга со страницы эндпоинта fal.ai",
    "OpenAPI входа эндпоинта",
)


def _хост(url: str) -> str:
    return source_hosts.host_of(url)


def спор_с_базой(имя: str, н: Находка, стоят: list[Any]) -> tuple[list[Any], str]:
    """(свои устаревшие строки — к отзыву, причина отказа записать).

    Отказ — когда та же площадка уже говорит об этой модели и атрибуте ДРУГОЕ
    значение строкой чужого канала или с другого адреса: две строки одной
    площадки с разными значениями `FactStore` читает как спор источников, и
    запись испортила бы ответ, а не дополнила его.
    """
    from studio.selfrag.facts import _same_answer

    к_отзыву: list[Any] = []
    for ф in стоят:
        if ф.model != имя or ф.attribute != н.атрибут or ф.value == н.значение:
            continue
        if _хост(ф.source_url) != _хост(н.url):
            continue
        свой = ф.source_url == н.url and str(ф.note or "").startswith(МЕТКИ_КАНАЛА)
        if свой:
            к_отзыву.append(ф)
            continue
        if not _same_answer([ф.value, н.значение]):
            return [], f"спор с {ф.source_url} ({ф.value[:60]!r})"
    return к_отзыву, ""


def записать(находки: list[Находка], сегодня: str, путь: Path | None = None) -> dict[str, Any]:
    """Через advice.record. Тир — по адресу; своё прежнее значение того же адреса отзывается."""
    from studio.mcp import advice
    from studio.selfrag.facts import load_facts

    def база() -> list[Any]:
        return load_facts(путь) if путь else load_facts()

    итог: dict[str, Any] = {"записано": 0, "не_изменилось": 0, "отозвано": 0, "отказано": 0}
    по_атрибутам: dict[str, int] = {}
    причины: dict[str, int] = {}
    споры: list[str] = []
    новые_модели: set[str] = set()
    факты = база()
    до = {ф.model for ф in факты}
    for н in находки:
        тир = source_hosts.classify(
            н.модель, н.url, vendor_tier="vendor", portal_tier="portal", blog_tier="blog"
        )
        имя, отказ_имени = advice.каноническое_имя(н.модель, путь, new_model=н.new_model)
        if отказ_имени:
            итог["отказано"] += 1
            причины[отказ_имени[:100]] = причины.get(отказ_имени[:100], 0) + 1
            continue
        к_отзыву, спор = спор_с_базой(имя, н, факты)
        if спор:
            итог["отказано"] += 1
            споры.append(f"{имя}.{н.атрибут} = {н.значение[:50]!r}: {спор}")
            continue
        for ф in к_отзыву:
            ответ = advice.withdraw(
                ф.model,
                ф.attribute,
                ф.value,
                ф.source_url,
                f"пересинхронизация {сегодня}: этот же адрес теперь говорит {н.значение[:120]!r}",
                path=путь,
            )
            if ответ.get("outcome") == PASS:
                итог["отозвано"] += 1
        ответ = advice.record(
            н.модель,
            н.атрибут,
            н.значение,
            н.url,
            тир,
            сегодня,
            note=н.нота,
            read_directly=True,
            new_model=н.new_model,
            path=путь,
        )
        if ответ.get("outcome") != PASS:
            итог["отказано"] += 1
            причина = str(ответ.get("note") or "")[:100]
            причины[причина] = причины.get(причина, 0) + 1
            continue
        if ответ.get("written") is None:
            итог["не_изменилось"] += 1
            continue
        итог["записано"] += 1
        факты = база()
        по_атрибутам[н.атрибут] = по_атрибутам.get(н.атрибут, 0) + 1
        записанная = str((ответ.get("written") or {}).get("model") or "")
        if записанная and записанная not in до:
            новые_модели.add(записанная)
    итог["по_атрибутам"] = по_атрибутам
    итог["причины"] = причины
    итог["споры"] = споры
    итог["новые_модели"] = sorted(новые_модели)
    return итог


# --- офлайн-проверка ------------------------------------------------------------

ПРИЗНАК_НОТЫ = "страница эндпоинта fal.ai"


def проверить_собранное(факты: Any = None) -> dict[str, Any]:
    """Офлайн: строки этого канала связны. Сети здесь нет.

    Нарушения: тир строки не тот, что даёт адрес; дата не ISO; флаг чтения не
    True; один адрес страницы говорит о модели и атрибуте два значения разом
    (прежнее значение обязано быть отозвано).
    """
    from studio.selfrag.facts import load_facts

    строки = [
        ф
        for ф in (load_facts() if факты is None else факты)
        if str(ф.note or "").startswith(ПРИЗНАК_НОТЫ)
        or (str(ф.note or "").startswith("единица биллинга со страницы эндпоинта fal.ai"))
    ]
    if not строки:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "в базе нет ни одной строки этого канала — проверять нечего",
        }
    нарушения: list[str] = []
    значения: dict[tuple[str, str, str], set[str]] = {}
    for ф in строки:
        тир = source_hosts.classify(
            ф.model, ф.source_url, vendor_tier="vendor", portal_tier="portal", blog_tier="blog"
        )
        if ф.tier != тир:
            нарушения.append(f"{ф.model}.{ф.attribute}: тир {ф.tier!r}, адрес даёт {тир!r}")
        try:
            date.fromisoformat(str(ф.stated_on))
        except ValueError:
            нарушения.append(f"{ф.model}.{ф.attribute}: дата {ф.stated_on!r} не ISO")
        if ф.read_directly is not True:
            нарушения.append(f"{ф.model}.{ф.attribute}: страница не помечена прочитанной")
        значения.setdefault((ф.model, ф.attribute, ф.source_url), set()).add(ф.value)
    for (модель, атрибут, url), набор in sorted(значения.items()):
        if len(набор) > 1:
            нарушения.append(f"{модель}.{атрибут}: {url} говорит {len(набор)} значения разом")
    return {
        "outcome": FAIL if нарушения else PASS,
        "checked": len(строки),
        "violations": len(нарушения),
        "unmeasured": 0,
        "note": f"строк канала {len(строки)}, моделей {len({ф.model for ф in строки})}"
        + ("\n  " + "\n  ".join(нарушения[:10]) if нарушения else ""),
    }


# --- вход ----------------------------------------------------------------------

#: Эндпоинты, которых публичный каталог НЕ ПЕРЕЧИСЛЯЕТ (статус `unlisted` на
#: странице), но которые работают и продаются. ИЗМЕРЕНО 2026-10-14: ни одного
#: `veo3.1` в 1506 строках каталога, а pricing API и страница отвечают по
#: каждому из этих путей.
НЕПЕРЕЧИСЛЕННЫЕ: dict[str, str] = {
    "fal-ai/veo3.1": "text-to-video",
    "fal-ai/veo3.1/fast": "text-to-video",
    "fal-ai/veo3.1/lite": "text-to-video",
    "fal-ai/veo3.1/image-to-video": "image-to-video",
    "fal-ai/veo3.1/fast/image-to-video": "image-to-video",
    "fal-ai/veo3.1/lite/image-to-video": "image-to-video",
    "fal-ai/veo3.1/reference-to-video": "image-to-video",
    "fal-ai/veo3.1/first-last-frame-to-video": "image-to-video",
    "fal-ai/veo3.1/fast/first-last-frame-to-video": "image-to-video",
}


def сохранить_отчёт(отчёт: Отчёт, путь: Path) -> None:
    """Находки и счётчики обхода — в JSON, чтобы запись шла без второго обхода."""
    тело = dataclasses.asdict(отчёт)
    путь.write_text(json.dumps(тело, ensure_ascii=False, indent=1), encoding="utf-8")


def прочитать_отчёт(путь: Path) -> Отчёт:
    тело = json.loads(путь.read_text(encoding="utf-8"))
    находки = [Находка(**н) for н in тело.pop("находки", [])]
    return Отчёт(**тело, находки=находки)


def имя_как_в_базе(кандидат: str, путь: Path | None = None) -> tuple[str, str]:
    """Разрешитель записи: слой имён, а при отказе «по соседу» — сосед, если он
    отличается от кандидата ТОЛЬКО приставкой вендора.

    ЗАЧЕМ. `FactStore.canonical` выбирает написание группы по числу строк, и
    второе написание одной модели (`speech-2.6-hd` рядом с
    `minimax-speech-2.6-hd`) делает запись неидемпотентной: каноническое имя
    группы переключается, как только строк у второго написания становится
    больше. ВОСПРОИЗВЕДЕНО 2026-10-14 повторным прогоном импорта LiteLLM: 4
    строки дописаны под другим написанием. Поэтому второе написание не
    заводится вовсе, если сосед — та же модель с вендором впереди.
    """
    from studio.mcp import advice

    имя, отказ = advice.каноническое_имя(кандидат, путь)
    if not отказ:
        return имя, ""
    база = advice.store_for(путь)
    сосед = база.canonical(кандидат) or база.resolve(кандидат).canonical
    свёртка = modelnames.fold(modelnames.strip_vendor(кандидат))
    if сосед and modelnames.fold(modelnames.strip_vendor(сосед)) == свёртка:
        return сосед, ""
    return кандидат, отказ


def _разрешитель_базы(кандидат: str) -> tuple[str, str]:
    return имя_как_в_базе(кандидат)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--apply", action="store_true", help="записать находки через advice.record")
    parser.add_argument("--check", action="store_true", help="без сети: связность записанного")
    parser.add_argument(
        "--limit", type=int, default=0, help="не больше N эндпоинтов охвата (отладка)"
    )
    parser.add_argument("--today", default=date.today().isoformat(), help="дата прочтения (ISO)")
    parser.add_argument("--save", type=Path, help="сохранить находки обхода в JSON (для просмотра)")
    parser.add_argument(
        "--from",
        dest="source",
        type=Path,
        help="не ходить в сеть: взять находки из сохранённого JSON",
    )
    args = parser.parse_args(argv)

    if args.check:
        итог = проверить_собранное()
        print(итог["note"])
        print(
            f"\nпроверено {итог['checked']}\nнарушений {итог['violations']}\nне смогли {итог['unmeasured']}"
        )
        return 0 if итог["outcome"] == PASS else (1 if итог["outcome"] == FAIL else 2)

    from studio.selfrag.facts import load_facts

    if args.source:
        отчёт = прочитать_отчёт(args.source)
    else:
        отчёт = собрать(
            получатель_по_умолчанию,
            _разрешитель_базы,
            имена_в_базе(load_facts()),
            os.environ.get("FAL_KEY", ""),
            дополнительно=НЕПЕРЕЧИСЛЕННЫЕ,
            предел=args.limit,
        )
    if args.save:
        сохранить_отчёт(отчёт, args.save)
    print(
        f"каталог: эндпоинтов {отчёт.эндпоинтов}, медийных {отчёт.медийных}, в охвате "
        f"{отчёт.в_охвате}; страниц прочитано {отчёт.страниц}, схем {отчёт.схем}"
    )
    print(f"медийных вне охвата и вне базы (очередь на чтение): {len(отчёт.вне_базы)}")
    по_атрибутам: dict[str, int] = {}
    for н in отчёт.находки:
        по_атрибутам[н.атрибут] = по_атрибутам.get(н.атрибут, 0) + 1
    print(
        f"находок {len(отчёт.находки)}: "
        + ", ".join(f"{а} {ч}" for а, ч in sorted(по_атрибутам.items()))
    )
    for р in отчёт.расхождения_цен[:20]:
        print(f"  цена: {р}")
    for п in отчёт.не_смогли[:20]:
        print(f"  не смогли: {п}")
    if args.apply:
        итог = записать(отчёт.находки, args.today)
        print(
            f"записано {итог['записано']}, не изменилось {итог['не_изменилось']}, "
            f"отозвано прежних {итог['отозвано']}, отказано {итог['отказано']}"
        )
        for а, ч in sorted(итог["по_атрибутам"].items()):
            print(f"  {а}: {ч}")
        print(f"новых моделей: {len(итог['новые_модели'])}")
        for причина, ч in sorted(итог["причины"].items(), key=lambda п: -п[1]):
            print(f"  отказ x{ч}: {причина}")
    else:
        for н in отчёт.находки[:60]:
            print(f"  {н.модель[:34]:36} {н.атрибут:24} {н.значение[:60]}")
        print("(dry-run: ничего не записано; --apply пишет)")
    print(f"\nпроверено {отчёт.в_охвате}\nнарушений 0\nне смогли {len(отчёт.не_смогли)}")
    if not отчёт.эндпоинтов:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
