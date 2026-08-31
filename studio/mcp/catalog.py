"""Каталог площадки — ИНДЕКС, а не источник фактов.

ЧТО ЭТО И ЧЕМ ОНО НЕ ЯВЛЯЕТСЯ

Каталог площадки (openrouter, deepinfra) перечисляет то, что у неё сегодня
включено. Это повод пойти прочитать вендорскую страницу, а НЕ повод записать
строку в `studio/knowledge/model_facts.jsonl`.

РЕШЕНИЕ ВЛАДЕЛЬЦА 2026-08-31, которое здесь исполняется кодом: массового
импорта каталогов в базу фактов не будет. Симуляция такого импорта дала
применимость 36.6% -> 18.6%, долю tier `portal` 21% -> 60% базы и 476 моделей,
известных только каталогу. Метрика покрытия после этого перестаёт быть прибором:
она мерила бы, сколько строк скачано, а не сколько вопросов закрыто.

Поэтому у каталога СВОЙ файл (`studio/knowledge/catalog.jsonl`) и СВОЯ схема.
Ни одна функция здесь не умеет писать в базу фактов.

ЦЕНЫ ОТДЕЛЬНЫМИ ПОЛЯМИ — И ЗАЧЕМ

В базе фактов цены лежат прозой ("$0.05 per second of 720p video"), и их нельзя
сложить: проверка бюджета по такой базе невозможна. Здесь цена разложена на
`amount` (число), `unit` (за что) и `condition` (при каком условии) — три поля,
а не одна строка. Это единственное, ради чего каталог вообще стоит хранить
машиночитаемо.

ЧЕГО ЗДЕСЬ НЕТ НАМЕРЕННО

Описаний моделей и обложек. Обе площадки отдают многоабзацный маркетинговый
текст; репозиторий публичный, и правило дома — хранить пересказ со ссылкой, а
не чужую прозу. Схема физически не имеет поля, куда её положить.
НЕПРОВЕРЕНО (правило Ц4): условия использования API обеих площадок не читались;
хранятся только фактические перечислимые величины (имя, цена, тип, дата снятия)
и ссылка на эндпоинт, откуда они взяты.

ПОДСАДНЫЕ

Четыре класса записей, которые каталог отдаёт как модели и которые моделями не
являются. Каждый найден глазами в живом ответе 2026-08-31, число рядом —
сколько таких было в срезе. Они существуют не как список для фильтра, а как
негативный контроль гейта: если ни одна из них не отсеялась, гейт ничего не
измерил (правило И5, Р2).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

__all__ = [
    "ADMIT",
    "CATALOG_HOSTS",
    "CATALOG_PATH",
    "EDIT_OP_MARKS",
    "FOREVER_YEAR",
    "GENERATOR_TYPES",
    "REJECT",
    "ROUTER_NAMES",
    "UNJUDGEABLE",
    "audit",
    "classify",
    "leaks",
    "read_catalog",
    "validate",
    "write_catalog",
]

CATALOG_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "catalog.jsonl"
FACTS_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "model_facts.jsonl"

#: Хосты, чей ответ — каталог, а не заявление автора модели. Строка факта с
#: таким источником не может быть сильнее tier `portal` и не имеет права нести
#: подсадную запись.
CATALOG_HOSTS = frozenset({"openrouter.ai", "api.deepinfra.com", "deepinfra.com"})

# --- схема -----------------------------------------------------------------

#: Поля, без которых запись каталога нечитаема. `deprecated` обязателен именно
#: булевым: у deepinfra он приходит unix-меткой, а отсутствие метки значит
#: «живая» — превращать это в None значит потерять третий исход на ровном месте.
REQUIRED: tuple[str, ...] = ("catalog", "name", "polled_on", "prices", "deprecated")

#: Всё, что запись каталога вообще может нести. Схема закрытая: незнакомое поле
#: — это либо чужая проза, которой здесь не место, либо тихо разъехавшийся
#: формат площадки. И то и другое лучше увидеть, чем пронести.
ALLOWED: frozenset[str] = frozenset(
    REQUIRED
    + (
        "catalog_id",
        "modality",
        "declared_type",
        "context_length",
        "deprecated_on",
        "replaced_by",
        "expiration_date",
        "source_url",
    )
)

#: Единицы, в которых площадки называют цену. Список закрытый: неизвестная
#: единица — это число, которое нельзя сложить, то есть ровно то, от чего этот
#: файл отделён от базы фактов.
PRICE_UNITS = frozenset(
    {
        "usd_per_token",
        "usd_per_second",
        "usd_per_image",
        "usd_per_request",
        "usd_per_character",
    }
)


def validate(record: Any) -> list[str]:
    """Что с этой записью не так. Пустой список — запись читается.

    Это НЕ вердикт о годности модели: правильно оформленная запись маршрутизатора
    проходит `validate` и отсеивается в `classify`. Разделено нарочно — иначе
    «мусор в файле» и «не модель» смешались бы в один счётчик.
    """
    problems: list[str] = []
    if not isinstance(record, dict):
        return [f"строка не объект, а {type(record).__name__}"]
    for field in REQUIRED:
        if field not in record:
            problems.append(f"нет обязательного поля {field}")
    unknown = sorted(set(record) - ALLOWED)
    if unknown:
        problems.append("поля вне схемы: " + ", ".join(unknown))
    if "deprecated" in record and not isinstance(record["deprecated"], bool):
        problems.append("deprecated не булев")
    prices = record.get("prices")
    if prices is not None:
        if not isinstance(prices, list):
            problems.append("prices не список")
        else:
            for i, price in enumerate(prices):
                problems.extend(f"prices[{i}]: {p}" for p in _price_problems(price))
    replaced = record.get("replaced_by")
    if replaced is not None:
        if not isinstance(replaced, dict):
            problems.append("replaced_by не объект")
        else:
            # Правило П4: у преемника обязано стоять имя площадки, которая его
            # назвала. Без него пара выглядит заявлением автора модели, а она им
            # не является — см. `classify` ниже.
            for field in ("name", "said_by"):
                if not replaced.get(field):
                    problems.append(f"replaced_by без {field}")
    return problems


def _price_problems(price: Any) -> list[str]:
    if not isinstance(price, dict):
        return [f"не объект, а {type(price).__name__}"]
    out: list[str] = []
    if not isinstance(price.get("amount"), (int, float)) or isinstance(price.get("amount"), bool):
        out.append("amount не число")
    if price.get("unit") not in PRICE_UNITS:
        out.append(f"единица {price.get('unit')!r} вне списка")
    if not price.get("condition"):
        out.append("нет условия (за что платят)")
    return out


# --- вердикт ---------------------------------------------------------------

ADMIT = "повод прочитать"  # запись годна как индекс: можно идти читать вендора
REJECT = "не модель"  # подсадная: до базы фактов не доезжает никогда
UNJUDGEABLE = "не смогли"  # запись нечитаема — третий исход, не «годно»

#: Маршрутизаторы openrouter. ИЗМЕРЕНО 2026-08-31 на живом ответе: у обоих
#: контекст 2 000 000 и цена prompt "-1" — они не модели, а выбор модели.
ROUTER_NAMES = frozenset({"openrouter/auto", "openrouter/auto-beta"})

#: Типы, которые площадка объявляет генеративными. Только внутри них имеет смысл
#: спрашивать «а это точно генератор».
GENERATOR_TYPES = frozenset({"text-to-video", "image-to-video", "text-to-image"})

#: Куски имени, по которым узнаётся операция редактирования, поданная площадкой
#: как `text-to-video`. ИЗМЕРЕНО 2026-08-31: 6 записей из 31 в срезе deepinfra
#: (все Bria/video_*). Они принимают на вход готовое видео и маску; спрашивать у
#: них «сколько секунд генерит» бессмысленно, а база фактов спросит.
EDIT_OP_MARKS: tuple[str, ...] = (
    "eraser",
    "remove_background",
    "mask_by",
    "increase_resolution",
    "foreground_mask",
)

#: Год, с которого дата снятия перестаёт быть датой. ВЫБРАНО: 2090 — заведомо за
#: любым реальным сроком поддержки и заведомо ниже часового 2098.
#: ИЗМЕРЕНО 2026-08-31: у openrouter 4 записи из 6 с непустым expiration_date
#: несут `2098-12-31`, то есть «бессрочно», одетое датой; две оставшиеся —
#: 2026-09-30 и 2026-12-31 — настоящие.
FOREVER_YEAR = 2090


def classify(record: Any) -> dict[str, Any]:
    """Годна ли запись каталога как повод прочитать. Три исхода, не два."""
    problems = validate(record)
    if problems:
        return {"verdict": UNJUDGEABLE, "rule": "схема", "why": "; ".join(problems)}

    name = str(record["name"])
    lowered = name.lower()

    if lowered in {n.lower() for n in ROUTER_NAMES}:
        return {"verdict": REJECT, "rule": "router", "why": f"{name} выбирает модель, а не модель"}
    for price in record["prices"]:
        if price["amount"] < 0:
            return {
                "verdict": REJECT,
                "rule": "router",
                "why": f"цена {price['amount']} за {price['condition']} — метка, а не цена",
            }

    if record["deprecated"] is True:
        when = record.get("deprecated_on") or "дата не названа"
        return {"verdict": REJECT, "rule": "deprecated", "why": f"снята площадкой ({when})"}

    declared = str(record.get("declared_type") or "")
    if declared in GENERATOR_TYPES:
        for mark in EDIT_OP_MARKS:
            if mark in lowered:
                return {
                    "verdict": REJECT,
                    "rule": "edit_op",
                    "why": f"объявлена как {declared}, но '{mark}' — операция над готовым файлом",
                }

    expires = str(record.get("expiration_date") or "")
    if expires:
        year = _year(expires)
        if year is None:
            return {"verdict": UNJUDGEABLE, "rule": "схема", "why": f"дата снятия {expires!r}"}
        if year >= FOREVER_YEAR:
            return {
                "verdict": REJECT,
                "rule": "forever_date",
                "why": f"{expires} — «бессрочно», одетое датой",
            }

    return {"verdict": ADMIT, "rule": "", "why": ""}


def _year(value: str) -> int | None:
    head = value.split("-", 1)[0]
    return int(head) if head.isdigit() and len(head) == 4 else None


# --- чтение и запись -------------------------------------------------------


def read_catalog(path: Path | None = None) -> tuple[list[dict], list[str]]:
    """Записи и битые строки, раздельно. Битая строка — третий исход, не ноль."""
    target = path or CATALOG_PATH
    if not target.exists():
        return [], [f"нет файла {target}"]
    rows: list[dict] = []
    broken: list[str] = []
    for number, line in enumerate(target.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        try:
            rows.append(json.loads(stripped))
        except json.JSONDecodeError as error:
            broken.append(f"строка {number}: {error.msg}")
    return rows, broken


HEADER = (
    "// Каталоги площадок как ИНДЕКС. Это НЕ факты о моделях: у фактов свой\n"
    "// файл model_facts.jsonl и своя схема. Запись здесь — повод пойти\n"
    "// прочитать вендора, а не заявление вендора. См. studio/mcp/catalog.py.\n"
    "//\n"
    "// Пишется scripts/poll_catalogs.py. Правится только им.\n"
)


def write_catalog(records: Iterable[dict], path: Path | None = None) -> int:
    target = path or CATALOG_PATH
    lines = [json.dumps(r, ensure_ascii=False, sort_keys=True) for r in records]
    target.write_text(HEADER + "\n".join(lines) + "\n", encoding="utf-8")
    return len(lines)


# --- гейт ------------------------------------------------------------------


def _norm(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def _fact_rows(path: Path) -> tuple[list[dict], list[str]]:
    rows: list[dict] = []
    broken: list[str] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        try:
            row = json.loads(stripped)
        except json.JSONDecodeError as error:
            broken.append(f"model_facts строка {number}: {error.msg}")
            continue
        if isinstance(row, dict):
            rows.append(row)
    return rows, broken


def _host(url: str) -> str:
    rest = url.split("://", 1)[-1]
    return rest.split("/", 1)[0].split("@")[-1].split(":")[0].lower()


def leaks(catalog_rows: list[dict], fact_rows: list[dict], rejected: dict[str, dict]) -> list[dict]:
    """Какие подсадные всё-таки доехали до базы фактов.

    ДВА ПРАВИЛА, И ОНИ РАЗНЫЕ. Совпадение имени само по себе не улика: пять
    записей deepinfra, помеченных `deprecated`, носят имена, о которых база
    ЗАКОННО знает из вендорских источников (ИЗМЕРЕНО 2026-08-31 —
    Wan2.1-T2V-1.3B, sd3.5-medium, chatterbox и ещё две). Красить гейт на них
    значит наказывать за правильно прочитанного вендора.

    Поэтому:
      * подсадная считается доехавшей, если строка факта О НЕЙ пришла С ХОСТА
        КАТАЛОГА — тогда её принёс именно импорт индекса;
      * маршрутизатор — доехавшим при любом источнике: `openrouter/auto` не
        модель ни по чьей версии, и факта о нём не бывает в принципе.
    """
    routers = {_norm(n) for n in ROUTER_NAMES}
    found: list[dict] = []
    for row in fact_rows:
        if row.get("withdrawn"):
            continue
        model = str(row.get("model", ""))
        key = _norm(model)
        source = str(row.get("source_url", ""))
        if key in routers:
            found.append({"model": model, "rule": "router", "source_url": source})
            continue
        hit = rejected.get(key)
        if hit and _host(source) in CATALOG_HOSTS:
            found.append({"model": model, "rule": hit["rule"], "source_url": source})
    return found


def audit(catalog_path: Path | None = None, facts_path: Path | None = None) -> dict[str, Any]:
    """Полный вердикт по каталогу и по тому, что из него утекло.

    Три исхода. «Ноль утечек» при нуле проверенных записей — НЕ успех (правило
    Р2), и «ноль отсеянных» тоже не успех: гейт, который ничего не отсёк, ничего
    и не измерил. Обратный контроль тоже здесь (И5): если не пропущено НИ ОДНОЙ
    записи, гейт выродился в «ничего не пропускать» и это тоже третий исход.
    """
    catalog_file = catalog_path or CATALOG_PATH
    facts_file = facts_path or FACTS_PATH
    rows, broken = read_catalog(catalog_file)

    admitted: list[dict] = []
    rejected: dict[str, dict] = {}
    by_rule: dict[str, int] = {}
    unjudgeable: list[str] = list(broken)
    for row in rows:
        verdict = classify(row)
        if verdict["verdict"] == ADMIT:
            admitted.append(row)
        elif verdict["verdict"] == REJECT:
            by_rule[verdict["rule"]] = by_rule.get(verdict["rule"], 0) + 1
            rejected[_norm(str(row.get("name", "")))] = {
                "name": row.get("name"),
                "rule": verdict["rule"],
                "why": verdict["why"],
            }
        else:
            unjudgeable.append(f"{row.get('name', '?')}: {verdict['why']}")

    if not facts_file.exists():
        return {
            "outcome": UNMEASURED,
            "checked": len(rows),
            "rejected": len(rejected),
            "admitted": len(admitted),
            "unmeasured": len(unjudgeable) + 1,
            "by_rule": by_rule,
            "leaks": [],
            "note": f"нет базы фактов {facts_file}: сравнивать не с чем",
        }
    fact_rows, fact_broken = _fact_rows(facts_file)
    unjudgeable.extend(fact_broken)
    found = leaks(rows, fact_rows, rejected)

    base = {
        "checked": len(rows),
        "admitted": len(admitted),
        "rejected": len(rejected),
        "unmeasured": len(unjudgeable),
        "by_rule": by_rule,
        "problems": unjudgeable,
        "leaks": found,
        "facts_read": len(fact_rows),
    }
    if found:
        names = ", ".join(f"{leak['model']} ({leak['rule']})" for leak in found)
        return {**base, "outcome": FAIL, "note": f"подсадные доехали до базы фактов: {names}"}
    if not rows:
        return {**base, "outcome": UNMEASURED, "note": "каталог пуст: ничего не проверено"}
    if not rejected:
        return {
            **base,
            "outcome": UNMEASURED,
            "note": (
                "ни одна запись не отсеяна — прибор не шевельнулся; "
                "подсадные обязаны быть в срезе, иначе гейт ничего не измеряет"
            ),
        }
    if not admitted:
        return {
            **base,
            "outcome": UNMEASURED,
            "note": (
                "не пропущено ни одной записи — это не строгость, а «ничего не "
                "пропускать»: обратный контроль не сработал"
            ),
        }
    return {
        **base,
        "outcome": PASS,
        "note": (
            f"проверено {len(rows)}, отсеяно {len(rejected)}, пропущено {len(admitted)}, "
            f"не смогли {len(unjudgeable)}; в базу фактов не доехало ничего"
        ),
    }


# --- контрольный набор -----------------------------------------------------

#: Прибор, проверенный на входах, где он ОБЯЗАН сказать «нет», и на входах, где
#: он обязан промолчать (правило И5). Живёт здесь, а не в тестах и не в
#: скрипте-гейте, ровно по правилу Е1: набор нужен обоим, и разъехавшиеся копии
#: были бы двумя разными приборами. Каждая строка — сокращённая, но НАСТОЯЩАЯ
#: запись из ответа площадки 2026-08-31.
CONTROL_SET: tuple[tuple[dict, str, str, str], ...] = (
    (
        {
            "catalog": "openrouter",
            "name": "openrouter/auto",
            "polled_on": "2026-08-31",
            "context_length": 2000000,
            "prices": [{"amount": -1.0, "unit": "usd_per_token", "condition": "prompt"}],
            "deprecated": False,
        },
        REJECT,
        "router",
        "маршрутизатор: контекст 2 000 000 и цена -1 — он выбирает модель, а не является ею",
    ),
    (
        {
            "catalog": "openrouter",
            "name": "openrouter/auto-beta",
            "polled_on": "2026-08-31",
            "prices": [{"amount": -1.0, "unit": "usd_per_token", "condition": "prompt"}],
            "deprecated": False,
        },
        REJECT,
        "router",
        "второй маршрутизатор той же площадки",
    ),
    (
        {
            "catalog": "openrouter",
            "name": "openrouter/fusion",
            "polled_on": "2026-08-31",
            "prices": [{"amount": -1.0, "unit": "usd_per_token", "condition": "prompt"}],
            "deprecated": False,
        },
        REJECT,
        "router",
        "имени в списке нет, но цена -1 выдаёт маршрутизатор: правило ловит класс, а не список",
    ),
    (
        {
            "catalog": "deepinfra",
            "name": "allenai/olmOCR-7B-1025",
            "polled_on": "2026-08-31",
            "declared_type": "text-generation",
            "prices": [{"amount": 1.4e-07, "unit": "usd_per_token", "condition": "input token"}],
            "deprecated": True,
            "deprecated_on": "2026-05-07",
            "replaced_by": {"name": "google/gemma-4-31B-it", "said_by": "deepinfra"},
        },
        REJECT,
        "deprecated",
        "снята площадкой; преемник назван ПЛОЩАДКОЙ и через чужого вендора — рекомендация продавца",
    ),
    (
        {
            "catalog": "deepinfra",
            "name": "Bria/video_eraser",
            "polled_on": "2026-08-31",
            "declared_type": "text-to-video",
            "prices": [{"amount": 0.05, "unit": "usd_per_second", "condition": "output second"}],
            "deprecated": False,
        },
        REJECT,
        "edit_op",
        "помечена text-to-video, но принимает готовое видео и маску — не генератор",
    ),
    (
        {
            "catalog": "openrouter",
            "name": "z-ai/glm-5.3",
            "polled_on": "2026-08-31",
            "prices": [{"amount": 6e-07, "unit": "usd_per_token", "condition": "prompt"}],
            "deprecated": False,
            "expiration_date": "2098-12-31",
        },
        REJECT,
        "forever_date",
        "2098-12-31 — «бессрочно», одетое датой; записать это как дату снятия значит соврать",
    ),
    (
        {
            "catalog": "deepinfra",
            "name": "Wan-AI/Wan2.6-T2V",
            "polled_on": "2026-08-31",
            "declared_type": "text-to-video",
            "modality": "text-to-video",
            "prices": [{"amount": 0.04, "unit": "usd_per_second", "condition": "output second"}],
            "deprecated": False,
        },
        ADMIT,
        "",
        "ОБРАТНЫЙ КОНТРОЛЬ: живой генератор видео обязан пройти, иначе гейт — просто «ничего не пропускать»",
    ),
    (
        {
            "catalog": "openrouter",
            "name": "z-ai/glm-4.5",
            "polled_on": "2026-08-31",
            "prices": [{"amount": 3.2e-07, "unit": "usd_per_token", "condition": "prompt"}],
            "deprecated": False,
            "expiration_date": "2026-12-31",
        },
        ADMIT,
        "",
        "ОБРАТНЫЙ КОНТРОЛЬ: настоящая дата снятия не должна отсекаться заодно с часовой",
    ),
    (
        {
            "catalog": "deepinfra",
            "name": "Bria/video_eraser",
            "polled_on": "2026-08-31",
            "declared_type": "text-to-video",
            "prices": [{"amount": 0.05, "unit": "центы за секунду", "condition": "output second"}],
            "deprecated": False,
        },
        UNJUDGEABLE,
        "схема",
        "цена в единице вне списка: третий исход, а не «годно» и не «подсадная»",
    ),
)


def control_report() -> dict[str, Any]:
    """Прогнать контрольный набор. `нарушений` — расхождение прибора с ожиданием."""
    checked = violations = 0
    lines: list[str] = []
    for record, want_verdict, want_rule, why in CONTROL_SET:
        got = classify(record)
        checked += 1
        ok = got["verdict"] == want_verdict and (not want_rule or got["rule"] == want_rule)
        if not ok:
            violations += 1
            lines.append(
                f"[РАСХОЖДЕНИЕ] {record['name']}: ждали {want_verdict}/{want_rule or '-'}, "
                f"получили {got['verdict']}/{got['rule'] or '-'} — {why}"
            )
        else:
            lines.append(f"[ok] {record['name']}: {want_verdict} {want_rule}".rstrip())
    outcome = FAIL if violations else (PASS if checked else UNMEASURED)
    return {"outcome": outcome, "checked": checked, "violations": violations, "lines": lines}
