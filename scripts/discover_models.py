"""Что появилось в мире с прошлого раза: диффом, а не списком.

ЗАЧЕМ

Вопрос владельца был «как покрыть все модели, даже самые новые». Списком —
никак: моделей выходит десятки в неделю. Но у новой модели в первый же день
есть машинный след в индексе, даже когда её страница закрыта политикой или
ещё не написана. Этот скрипт читает индексы и печатает РАЗНИЦУ с нашей базой.

ПОЧЕМУ ИМЕННО ЭТИ КАНАЛЫ

Ровно по той причине, по которой 403-и не убили базу: агент читает первичный
технический артефакт, а не пресс-релиз. Индекс — тот же артефакт, только
перечисляющий.

  * huggingface.co/api/models  — веса появляются здесь в день выкладки, с
    лицензией и карточкой. ПРОВЕРЕНО командой 2026-08-31: 200, и первая же
    выдача содержала `MiniMax-H3`, о котором нас спрашивали и о котором база
    молчала.
  * pypi.org/pypi/<пакет>/json — версия вендорского клиента. Новая версия SDK
    почти всегда означает новую модель в enum. Все 10 пакетов ниже проверены
    командой на существование (правило Ц10), 200 у каждого.

  * api.github.com — НЕ канал в этом окружении. ИЗМЕРЕНО 2026-08-31:
    `HTTP 403, "GitHub access to this repository is not enabled for this
    session"` на `runwayml/sdk-python` и на `openai/openai-python`. Шлюз
    пускает только репозитории, выданные сессии. Записано отрицательным
    результатом (правило И6), а не выкинуто молча: канал рабочий там, где
    доступ выдан, и вернётся сюда без переписывания, если выдадут.

ДВА СПИСКА, А НЕ ОДИН

Новое семейство и новая версия известного семейства — разная работа. Первое
требует классифицировать вендорский хост и завести источник; второе — дочитать
дельту к тому, что уже записано. Свалить их в один список значит потерять
именно то различие, ради которого таблица источников ключуется по семейству.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.selfrag import facts as facts_mod
from studio.selfrag.modelnames import fold  # noqa: E402
from studio.selfrag.source_hosts import FAMILY_SEPARATORS, VENDOR_SOURCES  # noqa: E402

FACTS = Path(__file__).resolve().parents[1] / "studio" / "knowledge" / "model_facts.jsonl"

#: ВЫБРАНО: задачи, на которых живут генеративные модели, которые нас касаются.
#: Каждый тег — отдельный запрос, потому что индекс сортирует по дате внутри
#: тега, и один общий запрос вернул бы только самую многолюдную нишу.
HF_TASKS: tuple[str, ...] = (
    "text-to-video",
    "image-to-video",
    "text-to-image",
    "image-to-image",
    "text-to-speech",
    "any-to-any",
)

#: Сколько свежайших записей брать из каждого тега. ВЫБРАНО 50: индекс
#: отсортирован по дате создания, и 50 на тег покрывает несколько дней даже в
#: самой людной нише, оставаясь одним запросом.
HF_PER_TASK = 50

#: Вендорские клиенты, чья версия — сигнал «перечитай спецификацию». Каждый
#: проверен командой 2026-08-31 (правило Ц10): 200 и непустая версия.
#: Ключ — семейство или вендор, как его знает наша таблица источников.
PYPI_CLIENTS: dict[str, str] = {
    "google-genai": "veo, gemini, imagen",
    "openai": "sora, gpt, dall-e",
    "anthropic": "claude",
    "runwayml": "gen4, aleph, act",
    "fal-client": "хостинг чужих весов — новые модели видно в enum",
    "replicate": "то же, вторая площадка",
    "volcengine-python-sdk": "seedance, omnihuman",
    "dashscope": "wan, qwen",
    "diffusers": "опенсорсные пайплайны",
    "huggingface-hub": "сам индекс",
}

#: ИЗМЕРЕНО 2026-08-31 на первой же живой выдаче: без этого порога канал
#: назвал 129 «новых семейств», и глазами (правило П3) видно, что это личные
#: LoRA и эксперименты — `aros-456bc2b1-VelvetLynx`, `invert-polarity-<uuid>`,
#: `D.kee`. Настоящую новую модель перезаливают и квантуют РАЗНЫЕ люди в первые
#: же сутки; личный эксперимент лежит под одним аккаунтом. Порог по числу
#: РАЗНЫХ загрузчиков — самый дешёвый честный различитель, какой тут есть.
#: ВЫБРАНО 2: единица не фильтрует ничего, тройка съедает медленные ниши вроде
#: text-to-speech. Сторожится тестом в обе стороны (правило Т1).
DISTINCT_UPLOADERS = 2

#: Хвосты, которыми комьюнити метит переупаковку чужих весов. Их снимают перед
#: сверкой, иначе `wan-2.2-gguf` читается как незнакомое имя, а это тот же wan.
NOISE_TOKENS: frozenset[str] = frozenset(
    {
        "gguf",
        "ggml",
        "fp8",
        "fp16",
        "bf16",
        "int8",
        "int4",
        "nf4",
        "4bit",
        "8bit",
        "awq",
        "gptq",
        "onnx",
        "safetensors",
        "diffusers",
        "lora",
        "loras",
        "merge",
        "remix",
        "distill",
        "distilled",
        "quantized",
        "quant",
        "pruned",
        "test",
        "v1",
        "v2",
        "v3",
        "base",
        "pro",
        "turbo",
        "fast",
        "mini",
        "lite",
        "preview",
    }
)


def family_of(model_id: str) -> str:
    """Первый смысловой токен имени — то, чем наша таблица источников ключуется.

    Вынесено отдельной функцией (правило Т5), потому что от неё зависит,
    попадёт находка в «новое семейство» или в «новую версию».
    """
    name = str(model_id or "").strip().lower()
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    for sep in FAMILY_SEPARATORS:
        name = name.replace(sep, " ")
    tokens = [t for t in name.split() if t and t not in NOISE_TOKENS]
    return tokens[0] if tokens else ""


def version_stem(model_id: str) -> str:
    """Имя версии без квантований и переупаковок: чем группировать находки.

    ИЗМЕРЕНО 2026-08-31: без группировки одна модель `MiniMax-H3` дала 15 строк
    из 57 — список читался как поток, а не как список работы. Стем режется по
    первому токену с цифрой: вендор ставит номер версии сразу за именем, а всё
    после него — чужая упаковка (`-fp8`, `-INT4-Diffusers`, `-LoRA`).

    Точка НЕ считается разделителем здесь, в отличие от `family_of`: `ltx-2.5`
    и `ltx-2.3` — разные версии, и склеивать их нельзя.
    """
    name = str(model_id or "").strip().lower()
    if "/" in name:
        name = name.rsplit("/", 1)[-1]
    tokens = [t for t in name.replace("_", "-").split("-") if t]
    kept: list[str] = []
    for token in tokens:
        if token in NOISE_TOKENS and not any(ch.isdigit() for ch in token):
            continue
        kept.append(token)
        if any(ch.isdigit() for ch in token):
            break
    return " ".join(kept[:4])


def as_known(family: str, families: set[str]) -> str:
    """Имя семейства так, как его знает таблица источников. Пусто — не знаем.

    Вендор пишет `flux-2`, комьюнити — `flux2`, и без этой поправки вторая
    форма читается как незнакомое семейство. Цифры снимаются только если
    остаток непустой: `4o` не должен схлопываться в пустую строку.
    """
    if family in families:
        return family
    trimmed = family.rstrip("0123456789.")
    return trimmed if trimmed and trimmed in families else ""


def known_families() -> set[str]:
    """Семейства, у которых уже объявлен вендорский источник."""
    return {name.lower() for name in VENDOR_SOURCES}


def known_models(path: Path | None = None) -> set[str]:
    """Имена моделей, о которых в базе есть хоть один живой факт.

    В СВЁРНУТОМ виде (правило Е1, одно разрешение имени на проект): у
    HuggingFace модель зовётся `Lightricks/LTX-2.3`, а в базе она лежит как
    `ltx-2-3`, и сравнение сырых строк объявляло бы уже известную модель
    находкой. Свёртка одна и та же по обе стороны сравнения.
    """
    rows = facts_mod.load_facts(FACTS if path is None else path)
    return {fold(fact.model) for fact in rows}


def split_findings(
    candidates: list[dict[str, Any]],
    families: set[str],
    models: set[str],
) -> dict[str, list[dict[str, Any]]]:
    """Разложить находки на «новое семейство» и «новая версия известного».

    Чистая функция над разобранным JSON: сеть сюда не заходит, поэтому решение
    достижимо из теста без сети (правило Т4).
    """
    # Свёртка применяется К ОБЕИМ сторонам сравнения и ИМЕННО ЗДЕСЬ, в точке
    # сравнения: свёрнутое ещё раз свёрнутым не портится, а вызывающий, у
    # которого имена сырые, перестаёт зависеть от того, помнил ли он свернуть.
    известные = {fold(m) for m in models}
    fresh_family: dict[str, dict[str, Any]] = {}
    fresh_version: dict[str, dict[str, Any]] = {}
    for row in candidates:
        model_id = str(row.get("id") or "")
        family = family_of(model_id)
        if not family:
            continue
        short = model_id.rsplit("/", 1)[-1].lower()
        if fold(short) in известные or fold(model_id) in известные:
            continue
        settled = as_known(family, families)
        new_family = not settled
        family = settled or family
        bucket = fresh_family if new_family else fresh_version
        key = family if new_family else (version_stem(model_id) or short)
        seen = bucket.setdefault(
            key,
            {
                "family": family,
                "stem": key,
                "examples": [],
                "task": row.get("task", ""),
                "count": 0,
                "uploaders": set(),
            },
        )
        seen["count"] = int(seen["count"]) + 1
        uploaders = seen["uploaders"]
        assert isinstance(uploaders, set)
        uploaders.add(model_id.split("/", 1)[0].lower() if "/" in model_id else model_id.lower())
        if len(seen["examples"]) < 3:
            seen["examples"].append(model_id)

    # Порог применяется ТОЛЬКО к новым семействам. Новая версия известного
    # семейства уже подтверждена вендорским источником, и ждать от неё второго
    # загрузчика значит пропустить её на сутки-двое.
    fresh_family = {
        key: row for key, row in fresh_family.items() if len(row["uploaders"]) >= DISTINCT_UPLOADERS
    }
    for row in list(fresh_family.values()) + list(fresh_version.values()):
        row["uploaders"] = sorted(row["uploaders"])

    def order(row: dict[str, Any]) -> tuple[int, str]:
        return (-int(row["count"]), str(row["family"]))

    return {
        "new_families": sorted(fresh_family.values(), key=order),
        "new_versions": sorted(fresh_version.values(), key=order),
    }


def _get(url: str, timeout: int = 25) -> tuple[str, Any]:
    """Один запрос. Возвращает (состояние, разобранный JSON или None).

    Отказ хоста — это состояние, а не исключение: канал, который не ответил,
    обязан доехать до вердикта третьим исходом, а не обвалить прогон.
    """
    request = urllib.request.Request(url, headers={"User-Agent": "lipsync-studio/discovery"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return "ok", json.loads(response.read())
    except urllib.error.HTTPError as error:
        return f"HTTP {error.code}", None
    except Exception as error:  # noqa: BLE001 — состояние канала, не наша ошибка
        return type(error).__name__, None


def poll_hugging_face(get: Callable[[str], tuple[str, Any]] = _get) -> dict[str, Any]:
    """Свежайшие веса по каждой интересующей задаче."""
    rows: list[dict[str, Any]] = []
    answered, refused = 0, []
    for task in HF_TASKS:
        url = (
            "https://huggingface.co/api/models?sort=createdAt&direction=-1"
            f"&limit={HF_PER_TASK}&filter={task}"
        )
        state, payload = get(url)
        if state != "ok" or not isinstance(payload, list):
            refused.append(f"{task}: {state}")
            continue
        answered += 1
        for entry in payload:
            if isinstance(entry, dict) and entry.get("id"):
                rows.append(
                    {"id": entry["id"], "task": task, "created": entry.get("createdAt", "")}
                )
    return {"candidates": rows, "answered": answered, "refused": refused}


def poll_pypi(get: Callable[[str], tuple[str, Any]] = _get) -> dict[str, Any]:
    """Версия каждого вендорского клиента: сигнал «перечитай спецификацию»."""
    rows: list[dict[str, Any]] = []
    refused: list[str] = []
    for package, why in PYPI_CLIENTS.items():
        state, payload = get(f"https://pypi.org/pypi/{package}/json")
        if state != "ok" or not isinstance(payload, dict):
            refused.append(f"{package}: {state}")
            continue
        info = payload.get("info") or {}
        rows.append({"package": package, "version": info.get("version", ""), "covers": why})
    return {"clients": rows, "answered": len(rows), "refused": refused}


def channels_answered(hf: dict[str, Any], pypi: dict[str, Any]) -> int:
    """Сколько каналов ответили ЦЕЛИКОМ. Считается в одном месте (правило Е1).

    Пока это считалось дважды — в `report` и в ветке `--json` — вторая копия
    осталась со старым, ослабленным правилом и молча возвращала «годно» по
    одной шестой выборки (найдено независимой проверкой 2026-08-31).
    """
    whole = 0
    if int(hf.get("answered") or 0) == len(HF_TASKS):
        whole += 1
    if int(pypi.get("answered") or 0) == len(PYPI_CLIENTS):
        whole += 1
    return whole


def report(hf: dict[str, Any], pypi: dict[str, Any], findings: dict[str, list]) -> int:
    """Напечатать разницу числами и вернуть код возврата с тремя исходами."""
    # Канал считается ответившим, только если ответили ВСЕ его источники.
    # Пока один живой тег из шести засчитывался как живой канал, итог печатал
    # «не смогли 0» строкой выше «не ответили: пять отказов» и выносил вердикт
    # «нового нет» по одной шестой выборки — знаменатель находок съезжал молча
    # (найдено независимой проверкой 2026-08-31). Соседний refill_queue.report
    # тот же случай решает так же: любой молчащий источник — третий исход.
    channels = 2
    answered = channels_answered(hf, pypi)
    print("ЧТО ПОЯВИЛОСЬ С ПРОШЛОГО РАЗА")
    print(f"каналов опрошено {channels}, ответили {answered}, не смогли {channels - answered}")
    print(
        f"huggingface: тегов {len(HF_TASKS)}, ответили {hf['answered']}, записей {len(hf['candidates'])}"
    )
    if hf["refused"]:
        print("  не ответили: " + "; ".join(hf["refused"]))
    print(f"pypi: клиентов {len(PYPI_CLIENTS)}, ответили {pypi['answered']}")
    if pypi["refused"]:
        print("  не ответили: " + "; ".join(pypi["refused"]))

    print(f"\n--- НОВЫЕ СЕМЕЙСТВА ({len(findings['new_families'])}): вендорского источника нет")
    for row in findings["new_families"]:
        print(f"  {row['family']}  (записей {row['count']}, задача {row['task']})")
        print(f"       например: {', '.join(row['examples'])}")

    print(f"\n--- НОВЫЕ ВЕРСИИ ИЗВЕСТНЫХ СЕМЕЙСТВ ({len(findings['new_versions'])})")
    for row in findings["new_versions"]:
        print(
            f"  {row['stem']}  (семейство {row['family']}, задача {row['task']}, "
            f"перезаливок {row['count']})"
        )
        print(f"       например: {row['examples'][0]}")

    print("\n--- ВЕРСИИ ВЕНДОРСКИХ КЛИЕНТОВ")
    for row in pypi["clients"]:
        print(f"  {row['package']:24} {row['version']:12} {row['covers']}")

    if answered == 0:
        print("\nисход: не смогли — ни один индекс не ответил целиком")
        return 2
    if answered < channels:
        print(f"\nисход: не смогли полностью — целиком ответили {answered} из {channels}")
        return 2
    print(f"\nисход: годно — {len(findings['new_families'])} новых семейств к разбору")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="выдать находки машиночитаемо")
    args = parser.parse_args(argv)

    hf = poll_hugging_face()
    pypi = poll_pypi()
    findings = split_findings(hf["candidates"], known_families(), known_models())
    if args.json:
        print(
            json.dumps({"hugging_face": hf, "pypi": pypi, **findings}, ensure_ascii=False, indent=2)
        )
        return 0 if channels_answered(hf, pypi) == 2 else 2
    return report(hf, pypi, findings)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
