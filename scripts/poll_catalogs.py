#!/usr/bin/env python3
"""Опрос каталогов площадок в studio/knowledge/catalog.jsonl.

    python scripts/poll_catalogs.py              # опросить и переписать каталог
    python scripts/poll_catalogs.py --dry-run    # опросить и НЕ писать

ЧТО ЭТО ЗАПИСЫВАЕТ И ЧЕГО НЕ ЗАПИСЫВАЕТ

Только `studio/knowledge/catalog.jsonl` — индекс со своей схемой. Ни одна строка
отсюда не попадает в `studio/knowledge/model_facts.jsonl`: решение владельца
2026-08-31, каталог — повод прочитать, а не повод записать. Гейт
`scripts/check_catalog.py` проверяет, что это так и осталось.

ДВА КАНАЛА ОТВЕЧАЮТ БЕЗ КЛЮЧА, ЧЕТЫРЕ — НЕТ

ИЗМЕРЕНО 2026-08-31 одной командой на каждый хост:

    https://openrouter.ai/api/v1/models          200, 395 записей
    https://api.deepinfra.com/models/list        200, 368 записей
    https://api.replicate.com/v1/models          HTTP 401
    https://api.together.xyz/v1/models           HTTP 401
    https://artificialanalysis.ai/api/v2/...     HTTP 401
    https://api.wavespeed.ai/api/v3/models       HTTP 401

Четыре последних НЕ пропускаются молча. Молчаливый пропуск — это то самое
сворачивание третьего исхода во второй, за которое на этом проекте уже платили:
«каталогов опрошено 2, не смогли 0» читается как полный обзор рынка, а обзор
неполон на две трети. Они записываются в отчёт как «не смогли, нужен ключ», и
гейт краснеет, если хоть один из них исчезнет из списка незакрытых.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import PASS, UNMEASURED  # noqa: E402

from studio.mcp import catalog as cat  # noqa: E402

POLL_PATH = Path(__file__).resolve().parents[1] / "studio" / "knowledge" / "catalog_poll.json"

OPENROUTER_URL = "https://openrouter.ai/api/v1/models"
DEEPINFRA_URL = "https://api.deepinfra.com/models/list"

#: Каталоги, у которых нет ключа и не будет. Записываются как незакрытый третий
#: исход с наблюдённым кодом — не как отсутствующая строка.
KEYED: dict[str, dict[str, str]] = {
    "replicate": {"url": "https://api.replicate.com/v1/models", "observed": "HTTP 401"},
    "together": {"url": "https://api.together.xyz/v1/models", "observed": "HTTP 401"},
    "artificialanalysis": {
        "url": "https://artificialanalysis.ai/api/v2/data/llms/models",
        "observed": "HTTP 401",
    },
    "wavespeed": {"url": "https://api.wavespeed.ai/api/v3/models", "observed": "HTTP 401"},
}

#: Как называется цена у openrouter -> (единица, условие). Ключи вне таблицы не
#: выдумываются: их число печатается отдельной строкой, чтобы «не разобрали» не
#: превратилось в «этого не было».
OPENROUTER_PRICES: dict[str, tuple[str, str]] = {
    "prompt": ("usd_per_token", "prompt"),
    "completion": ("usd_per_token", "completion"),
    "input_cache_read": ("usd_per_token", "cached prompt"),
    "input_cache_write": ("usd_per_token", "cache write"),
    "image": ("usd_per_image", "image input"),
    "image_output": ("usd_per_image", "image output"),
    "request": ("usd_per_request", "request"),
    "web_search": ("usd_per_request", "web search"),
    "audio": ("usd_per_token", "audio input"),
    "audio_output": ("usd_per_token", "audio output"),
    "input_audio_cache": ("usd_per_token", "cached audio"),
    "input_cache_write_1h": ("usd_per_token", "cache write 1h"),
    "internal_reasoning": ("usd_per_token", "internal reasoning"),
}

#: Ключи openrouter, которые не цены: `overrides` — вложенный объект с
#: переопределениями по провайдеру. Перечислен, чтобы не шуметь в счётчике
#: «не разобрано», который иначе перестанут читать.
OPENROUTER_NOT_PRICES = frozenset({"overrides"})

#: То же для deepinfra. Величины приходят в ЦЕНТАХ и делятся на 100 здесь, в
#: одном месте: разъехавшаяся единица — это цена, отличающаяся в сто раз.
#: `rate_per_*` не берётся сознательно: это множители к тарифу, а не цена.
DEEPINFRA_PRICES: dict[str, tuple[str, str]] = {
    "cents_per_input_token": ("usd_per_token", "input token"),
    "cents_per_output_token": ("usd_per_token", "output token"),
    "cents_per_output_sec": ("usd_per_second", "output second"),
    "cents_per_input_sec": ("usd_per_second", "input second"),
    "cents_per_sec": ("usd_per_second", "second"),
    "cents_per_image_unit": ("usd_per_image", "image unit"),
    "cents_per_frame_unit": ("usd_per_image", "frame unit"),
    "cents_per_input_chars": ("usd_per_character", "input character"),
}

#: Ключи deepinfra, которые заведомо не цены. Перечислены, чтобы не попасть в
#: счётчик «не разобрано» и не создавать ложного шума.
DEEPINFRA_NOT_PRICES = frozenset(
    {
        "discount",
        "discount_ends_at",
        "short",
        "full",
        "table",
        "type",
        "default_width",
        "default_height",
        "default_iterations",
        "default_price_cents",
        "explicit_cache_granularity_tokens",
        "usage_from_cost",
    }
)


def _get(url: str, timeout: int = 30) -> tuple[str, Any]:
    """Один запрос. Отказ — состояние канала, а не исключение прогона."""
    request = urllib.request.Request(url, headers={"User-Agent": "lipsync-studio/catalog"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return "ok", json.loads(response.read())
    except urllib.error.HTTPError as error:
        return f"HTTP {error.code}", None
    except Exception as error:  # noqa: BLE001 — состояние канала
        return type(error).__name__, None


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return None
    return None


def openrouter_record(entry: dict, polled_on: str) -> tuple[dict, int]:
    prices: list[dict] = []
    unparsed = 0
    for key, raw in (entry.get("pricing") or {}).items():
        if key in OPENROUTER_NOT_PRICES:
            continue
        amount = _number(raw)
        mapped = OPENROUTER_PRICES.get(key)
        if mapped is None:
            if amount not in (None, 0.0):
                unparsed += 1
            continue
        if amount is None or amount == 0.0:
            continue
        prices.append({"amount": amount, "unit": mapped[0], "condition": mapped[1]})
    record = {
        "catalog": "openrouter",
        "name": str(entry.get("id", "")),
        "polled_on": polled_on,
        "prices": prices,
        "deprecated": bool(entry.get("deprecated")),
        "source_url": OPENROUTER_URL,
    }
    slug = entry.get("canonical_slug")
    if slug:
        record["catalog_id"] = str(slug)
    modality = ((entry.get("architecture") or {}).get("modality")) or ""
    if modality:
        record["modality"] = str(modality)
    context = entry.get("context_length")
    if isinstance(context, int):
        record["context_length"] = context
    expires = entry.get("expiration_date")
    if expires:
        record["expiration_date"] = str(expires)
    return record, unparsed


def deepinfra_record(entry: dict, polled_on: str) -> tuple[dict, int]:
    prices: list[dict] = []
    unparsed = 0
    for key, raw in (entry.get("pricing") or {}).items():
        if key in DEEPINFRA_NOT_PRICES or key.startswith("rate_per_"):
            continue
        amount = _number(raw)
        mapped = DEEPINFRA_PRICES.get(key)
        if mapped is None:
            if amount not in (None, 0.0):
                unparsed += 1
            continue
        if amount is None or amount == 0.0:
            continue
        # Центы делятся на сто здесь, и результат подрезается до 12 значащих
        # цифр: 8e-05/100 в двоичной плавающей даёт 8.000000000000001e-07, и
        # такой хвост в цене читается как измеренная точность, которой нет.
        usd = float(f"{amount / 100.0:.12g}")
        prices.append({"amount": usd, "unit": mapped[0], "condition": mapped[1]})
    deprecated_at = entry.get("deprecated")
    record = {
        "catalog": "deepinfra",
        "name": str(entry.get("model_name", "")),
        "polled_on": polled_on,
        "prices": prices,
        "deprecated": bool(deprecated_at),
        "source_url": DEEPINFRA_URL,
    }
    declared = entry.get("type")
    if declared:
        record["declared_type"] = str(declared)
    reported = entry.get("reported_type")
    if reported:
        record["modality"] = str(reported)
    context = entry.get("max_tokens")
    if isinstance(context, int):
        record["context_length"] = context
    if isinstance(deprecated_at, (int, float)) and not isinstance(deprecated_at, bool):
        record["deprecated_on"] = (
            datetime.fromtimestamp(float(deprecated_at), tz=timezone.utc).date().isoformat()
        )
    successor = entry.get("replaced_by")
    if successor:
        # Правило П4: преемник — РЕКОМЕНДАЦИЯ ПЛОЩАДКИ, и имя площадки едет
        # рядом с ним навсегда. Живой пример 2026-08-31:
        # meta-llama/Llama-3.2-1B-Instruct -> google/gemma-4-31B-it — пара
        # через чужого вендора. Это заявление продавца о замене товара, а не
        # заявление автора модели о преемнике; в атрибут «преемник» базы фактов
        # такое не превращается никогда.
        record["replaced_by"] = {"name": str(successor), "said_by": "deepinfra"}
    return record, unparsed


def poll_openrouter(get: Callable[[str], tuple[str, Any]] = _get) -> dict[str, Any]:
    state, payload = get(OPENROUTER_URL)
    if state != "ok" or not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return {"catalog": "openrouter", "state": state, "records": [], "unparsed": 0}
    records, unparsed = [], 0
    polled_on = _today()
    for entry in payload["data"]:
        if isinstance(entry, dict) and entry.get("id"):
            record, missed = openrouter_record(entry, polled_on)
            records.append(record)
            unparsed += missed
    return {"catalog": "openrouter", "state": "ok", "records": records, "unparsed": unparsed}


def poll_deepinfra(get: Callable[[str], tuple[str, Any]] = _get) -> dict[str, Any]:
    state, payload = get(DEEPINFRA_URL)
    if state != "ok" or not isinstance(payload, list):
        return {"catalog": "deepinfra", "state": state, "records": [], "unparsed": 0}
    records, unparsed = [], 0
    polled_on = _today()
    for entry in payload:
        if isinstance(entry, dict) and entry.get("model_name"):
            record, missed = deepinfra_record(entry, polled_on)
            records.append(record)
            unparsed += missed
    return {"catalog": "deepinfra", "state": "ok", "records": records, "unparsed": unparsed}


def keyed_channels() -> list[dict[str, str]]:
    """Каналы, закрытые ключом. Третий исход с причиной, а не пустое место."""
    return [
        {
            "catalog": name,
            "state": UNMEASURED,
            "reason": "нужен ключ",
            "observed": meta["observed"],
            "url": meta["url"],
        }
        for name, meta in sorted(KEYED.items())
    ]


def summarise(polls: list[dict[str, Any]], records: list[dict]) -> dict[str, Any]:
    """Числа, которые печатаются и сохраняются. Считаются один раз (правило Е1)."""
    checked = len(records)
    rejected = 0
    admitted = 0
    unjudgeable = 0
    by_rule: dict[str, int] = {}
    for record in records:
        verdict = cat.classify(record)
        if verdict["verdict"] == cat.REJECT:
            rejected += 1
            by_rule[verdict["rule"]] = by_rule.get(verdict["rule"], 0) + 1
        elif verdict["verdict"] == cat.ADMIT:
            admitted += 1
        else:
            unjudgeable += 1
    open_channels = [p for p in polls if p["state"] == "ok"]
    return {
        "polled_on": _today(),
        "channels": [
            {
                "catalog": p["catalog"],
                "state": p["state"],
                "records": len(p["records"]),
                "unparsed_price_keys": p["unparsed"],
            }
            for p in polls
        ],
        "keyed_out": keyed_channels(),
        "checked": checked,
        "admitted": admitted,
        "rejected": rejected,
        "unmeasured": unjudgeable,
        "by_rule": by_rule,
        "channels_answered": len(open_channels),
        "channels_asked": len(polls),
    }


def report(summary: dict[str, Any], wrote: int | None) -> int:
    print("ОПРОС КАТАЛОГОВ")
    asked = summary["channels_asked"] + len(summary["keyed_out"])
    answered = summary["channels_answered"]
    print(f"каналов {asked}, ответили {answered}, не смогли {asked - answered}")
    for channel in summary["channels"]:
        print(
            f"  {channel['catalog']:20} {channel['state']:10} записей {channel['records']:4}"
            f"  цен не разобрано {channel['unparsed_price_keys']}"
        )
    for channel in summary["keyed_out"]:
        print(f"  {channel['catalog']:20} не смогли  {channel['reason']} ({channel['observed']})")
    print(
        f"\nпроверено {summary['checked']}, отсеяно {summary['rejected']}, "
        f"пропущено {summary['admitted']}, не смогли {summary['unmeasured']}"
    )
    for rule, count in sorted(summary["by_rule"].items()):
        print(f"  отсеяно правилом {rule}: {count}")
    if wrote is not None:
        print(f"записано в {cat.CATALOG_PATH}: {wrote} строк")
    if answered == 0:
        print(f"\nисход: {UNMEASURED} — ни один открытый каталог не ответил")
        return 2
    if answered < summary["channels_asked"]:
        print(f"\nисход: {UNMEASURED} — ответили {answered} из {summary['channels_asked']}")
        return 2
    if summary["rejected"] == 0:
        print(f"\nисход: {UNMEASURED} — ни одна запись не отсеяна, прибор не шевельнулся")
        return 2
    if summary["admitted"] == 0:
        print(f"\nисход: {UNMEASURED} — не пропущено ничего, это не строгость")
        return 2
    print(f"\nисход: {PASS} — каталог обновлён; в базу фактов из него не идёт ничего")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="опросить и не писать файлы")
    args = parser.parse_args(argv)

    polls = [poll_openrouter(), poll_deepinfra()]
    records = [r for poll in polls for r in poll["records"]]
    summary = summarise(polls, records)
    wrote = None
    if not args.dry_run and records:
        wrote = cat.write_catalog(records)
        POLL_PATH.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    return report(summary, wrote)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
