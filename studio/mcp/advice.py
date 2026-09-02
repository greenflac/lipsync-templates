"""Answer "can this model do that", and let the web refresh the answer.

WHAT THIS ADDS TO WHAT ALREADY EXISTED

`registry.py` holds one conservative answer per attribute, because a prompt
assembler needs one number. `facts.py` holds every answer anybody gave, with
its tier and its date, and reports `fail` when they disagree instead of
voting. Neither is reachable from a conversation, and neither can be updated
without a commit. This module joins them into one answer and opens the one
door that lets the base grow: `record`.

THE REFRESH PATH, AND THE MEASUREMENT THAT FORCED IT

This process cannot fetch the web. MEASURED 2026-08-27 on this machine:
`docs.bfl.ai`, `arxiv.org` and `kling.ai` all answer CONNECT 403 through the
egress proxy, and going around a policy-closed host is forbidden (Ц3). What is
NOT refused is the assistant's own search tool, in the conversation where the
owner is already standing.

So the refresh is a two-step the assistant performs in the open: search the
web, then call `record` with the value, the URL, the tier and the date the
source stated it. Nothing is written without those four. A claim with no URL
cannot be checked later, and a claim with no date cannot go stale — and a
claim that cannot go stale is the one that quietly rots.

WHAT THIS REFUSES TO DO

It never resolves a contradiction. When two sources disagree the answer is
`fail` with both sides shown, because the flattening is the bug: asked how
long one Kling 3.0 generation runs, the sources say 15s and 10s and "3
minutes", and a third-party summary of those same sources confidently reported
"up to 5 minutes", which matches none of them.

It never promotes a claim by repetition. Ten blogs quoting each other are one
source, and `facts.py` enforces that; this module only reports it.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date
from pathlib import Path
from typing import Any

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio.selfrag import attrfamily, registry, source_hosts
from studio.selfrag.facts import (
    DEFAULT_FACTS_PATH,
    STALE_AFTER_DAYS,
    TIERS,
    TIER_BENCHMARK,
    TIER_BLOG,
    TIER_OPERATOR,
    TIER_PAPER,
    TIER_PORTAL,
    TIER_VENDOR,
    Fact,
    FactStore,
    claim_key,
    load_facts,
)

__all__ = [
    "advise",
    "brief",
    "claims_found",
    "gap_reason",
    "REASONS",
    "record",
    "withdraw",
    "stale",
    "TIERS",
    "IDENTITY_TIERS",
    "MUTABLE_FIELDS",
    "store_for",
]

#: The rungs decided by whose page it is, and therefore never taken on trust
#: from a caller. Everything else in `TIERS` describes how the fact was
#: obtained, which the URL cannot know.
#: CHOSEN. How many class-level findings ride along with a model's answer.
#: 170 of them stand after the 2026-08-27 verification pass; a caller reading
#: an answer needs the strongest few and the count of the rest, not all of
#: them. Not measured — measure it when somebody reports the answer is thin.
CLASS_FINDINGS_SHOWN = 12

#: ПОЧЕМУ ответ такой, машиночитаемо и рядом с нотой.
#:
#: Заведено 2026-09-02, потому что три РАЗНЫХ положения дел печатались одним
#: исходом `could not measure` и одинаково читались: имени нет в базе вовсе;
#: имя набрано с опечаткой, а база держит соседнее; модель база знает, а
#: спрошенного атрибута про неё никто не записывал. Пользователь получал
#: «не смогли» и не мог понять, искать ли источник, переспросить ли другим
#: именем или спросить другой атрибут. Нота это иногда объясняла словами;
#: слова нельзя ни сгруппировать, ни сосчитать.
REASON_NO_MODEL_NAMED = "no_model_named"
REASON_MODEL_UNKNOWN = "model_unknown"
REASON_NAME_MAYBE_MISTYPED = "name_maybe_mistyped"
REASON_NOTHING_RECORDED = "nothing_recorded"
REASON_ATTRIBUTE_UNKNOWN = "attribute_unknown"
REASON_SOURCES_BLOG_ONLY = "sources_blog_only"
REASON_SOURCES_DISAGREE = "sources_disagree"
REASON_MODEL_UNUSABLE = "model_unusable"
REASON_ANSWERED = "answered"

#: Весь словарь причин. Список — не украшение: он делает состав причин
#: проверяемым тестом, а не памятью читающего.
REASONS: tuple[str, ...] = (
    REASON_NO_MODEL_NAMED,
    REASON_MODEL_UNKNOWN,
    REASON_NAME_MAYBE_MISTYPED,
    REASON_NOTHING_RECORDED,
    REASON_ATTRIBUTE_UNKNOWN,
    REASON_SOURCES_BLOG_ONLY,
    REASON_SOURCES_DISAGREE,
    REASON_MODEL_UNUSABLE,
    REASON_ANSWERED,
)


def claims_found(claims: object) -> int:
    """Сколько записанных источников стоит за этими утверждениями.

    ОДНО место, где считается «сколько нашлось» (правило Е1): отсюда это берёт
    и вердикт `advise`, и журнал вопросов через `misses.evidence`. Пока число
    считали порознь, вердикт мог сказать «нечем ответить» о том же ответе, в
    котором журнал видел свидетельство, — и именно это расхождение стоило
    пяти сессий сбора (ИЗМЕРЕНО 2026-09-02 на живой базе: 999 пар
    «модель.атрибут» из 1236 имели утверждение с исходом `pass` и получали от
    `advise` исход `could not measure`).

    Считается `checked` каждого утверждения — число НАЙДЕННЫХ источников, а не
    число опрошенных атрибутов: `advise("flux-2", "выдуманный-атрибут")`
    возвращает `checked 2` при нуле найденного.
    """
    if not isinstance(claims, dict):
        return 0
    found = 0
    for verdict in claims.values():
        if isinstance(verdict, dict):
            found += int(verdict.get("checked") or 0)
    return found


def gap_reason(claims: object) -> str:
    """Почему на вопрос нечем ответить: не записано ничего или всё на нижней ступени.

    Развилка вынесена функцией (правило Т5): от неё зависит, что пользователь
    сделает дальше — пойдёт искать источник вообще или пойдёт искать источник
    ПОКРЕПЧЕ блога, а это разная работа.
    """
    return REASON_SOURCES_BLOG_ONLY if claims_found(claims) else REASON_ATTRIBUTE_UNKNOWN


IDENTITY_TIERS: tuple[str, ...] = (TIER_VENDOR, TIER_PORTAL, TIER_BLOG)

# The ladder is IMPORTED, never restated. It was restated here until
# 2026-08-27, and the copy went stale the moment `probe` was added to the real
# one: `record` refused the tier its own module had just introduced, saying it
# "is not one of vendor, benchmark, paper, blog". Two lists of the same thing
# are one list and one bug waiting.


#: Прочитанная база, ключ — файл И ЕГО СОСТОЯНИЕ. Не срок жизни и не флаг:
#: кэш, который может отстать от файла, ломает обещание «`record` виден сразу»,
#: и отладка такого расхождения дороже всего, что кэш сэкономил.
#:
#: ЗАЧЕМ. ИЗМЕРЕНО 2026-09-02: `scripts/check_headline.py` задаёт 1182 вопроса
#: и на каждый перечитывает файл в 1833 строки — 43 секунды при 85 у всей
#: сборки. Продукту это стоит того же: `plan_pipeline` спрашивает базу по разу
#: на кандидата.
_ПРОЧИТАННОЕ: dict[tuple[str, int, int], FactStore] = {}


def store_for(path: Path | None = None) -> FactStore:
    """A fact store read fresh from disk, so a `record` is visible immediately.

    Кэшируется по (путь, время изменения в наносекундах, размер). Файл
    изменился хоть на байт — ключ другой, и база читается заново; поэтому
    «свежесть» здесь не обещание, а следствие ключа. Файла нет — читаем как
    прежде, без кэша: у отсутствующего файла нет состояния, по которому его
    можно отличить от появившегося.
    """
    файл = Path(path or DEFAULT_FACTS_PATH)
    try:
        снимок = файл.stat()
    except OSError:
        return FactStore(load_facts(файл))
    ключ = ключ_снимка(файл, снимок)
    готовое = _ПРОЧИТАННОЕ.get(ключ)
    if готовое is None:
        готовое = FactStore(load_facts(файл))
        # Один ключ на файл: держать историю состояний незачем, а память за
        # длинный прогон она съедает (1833 строки на снимок).
        for прежний in [к for к in _ПРОЧИТАННОЕ if к[0] == str(файл)]:
            _ПРОЧИТАННОЕ.pop(прежний, None)
        _ПРОЧИТАННОЕ[ключ] = готовое
    return готовое


def snapshot_size(снимок: Any) -> int:
    """Размер из `stat`. Отдельной функцией, чтобы подменяться в тесте (Т5)."""
    return int(снимок.st_size)


def ключ_снимка(файл: Path, снимок: Any) -> tuple[str, int, int]:
    """Ключ кэша: путь, время изменения в наносекундах И РАЗМЕР.

    Вынесено отдельной функцией (Т5), потому что размер в ключе иначе
    недостижим тестом: любая настоящая правка файла сдвигает и время, так что
    ключ различался бы и без размера, и мутант «время без размера» проходил
    молча. Здесь его видно.

    Размер нужен на файловых системах, округляющих время: две правки в один
    такт часов дали бы один ключ и ответ по прежней базе.
    """
    return (str(файл), int(снимок.st_mtime_ns), snapshot_size(снимок))


def _spread_by_attribute(facts: list[Fact]) -> list[Fact]:
    """Round-robin across attributes, keeping each attribute's own order.

    Sorting by tier alone hands the caller twelve `metric_blind_spot` rows and
    no failure mode, every time, for every model — OBSERVED 2026-08-27: the
    first twelve of 170 came back as one tier and two attributes, so the cap
    was choosing by alphabet rather than by usefulness. Taking one of each in
    turn means the twelve that are shown cover what there is.
    """
    buckets: dict[str, list[Fact]] = {}
    for fact in facts:
        buckets.setdefault(fact.attribute, []).append(fact)
    out: list[Fact] = []
    while buckets:
        for attribute in list(buckets):
            out.append(buckets[attribute].pop(0))
            if not buckets[attribute]:
                del buckets[attribute]
    return out


#: Card field -> the fact-base attribute that answers the same question. Only
#: fields a harvested claim can actually contradict; a skeleton or a parameter
#: map has no counterpart in the base and is not compared.
CARD_MIRRORS: tuple[tuple[str, str], ...] = (
    ("max_seconds", "max_seconds"),
    ("fps", "fps"),
    ("resolutions", "max_resolution"),
    ("aspect_ratios", "aspect_ratio"),
    ("audio", "audio"),
)


def _says_the_same(card_value: object, recorded: str) -> bool:
    """Does a recorded claim carry what the card states?

    Numbers first, because a card holds `8.0` and a harvest holds `"8"`, and a
    substring test calls those two a contradiction — OBSERVED the moment this
    check was first run, on veo-3.1.max_seconds, where card and base agree.
    A boolean card field is matched the same way rather than by its repr.
    """
    text = str(recorded).strip().lower()
    try:
        return float(str(card_value)) == float(text)
    except (TypeError, ValueError):
        pass
    if isinstance(card_value, bool):
        return text in (("true", "yes") if card_value else ("false", "no"))
    needle = str(card_value).strip().lower()
    return bool(needle) and needle in text


def _card_vs_base(card: object, store: FactStore, name: str) -> list[dict]:
    """Where the registry card and the recorded claims tell different stories.

    THE DEFECT THIS EXISTS FOR, found by a blind evaluation on 2026-08-27.
    Asked whether sora-2 could be used as a reference arm, the card answered
    that its "duration, resolution and fps limits could not be sourced at
    all" — `max_seconds=None`, `resolutions=()` — while the claims layer of
    the SAME answer held `max_seconds` 20 and `max_resolution` 1280x720 /
    720x1280, both read off OpenAI's own page. A caller who reads the card
    first, which is what a card is for, walks away believing nothing is known.

    Two shapes are reported and they are not the same complaint:

    * `card is silent`  — the card says unknown and the base knows. The card
      is behind; nothing is wrong, but the caller must not be told "unknown".
    * `card contradicts` — the card asserts a value and the base's sources say
      another. That is a real disagreement and it is NEVER resolved here.

    Reported, never merged. The card is one conservative answer for a prompt
    assembler and the base is every answer anybody gave; making one overwrite
    the other silently is how the assembler starts lying with confidence.
    """
    if card is None:
        return []
    out: list[dict] = []
    for field_name, attribute in CARD_MIRRORS:
        stated = getattr(card, field_name, None)
        verdict = store.claims(name, attribute)
        if verdict["outcome"] != PASS:
            continue
        values = verdict.get("values") or []
        empty = stated is None or stated == () or stated == ""
        if empty:
            out.append(
                {
                    "field": field_name,
                    "attribute": attribute,
                    "shape": "card is silent",
                    "card": stated,
                    "base": values,
                    "note": (
                        f"the card leaves {field_name} unset while the base holds "
                        f"{len(values)} recorded value(s). The card is behind the base."
                    ),
                }
            )
            continue
        wanted = stated if isinstance(stated, tuple) else (stated,)
        if any(_says_the_same(one, v) for one in wanted for v in values):
            continue
        out.append(
            {
                "field": field_name,
                "attribute": attribute,
                "shape": "card contradicts",
                "card": stated,
                "base": values,
                "note": (
                    f"the card states {field_name}={stated!r} and no recorded source says "
                    "so. Neither is corrected here; both are shown."
                ),
            }
        )
    return out


def _card_as_dict(card: object) -> dict | None:
    """Карточка реестра в виде обычного словаря. `None` остаётся `None`.

    Кортежи разворачиваются в списки: JSON кортежей не знает, а разница между
    «поле пустое» и «поля нет» здесь значащая, поэтому пустое поле остаётся
    пустым списком, а не исчезает.
    """
    if card is None:
        return None
    if isinstance(card, dict):
        return card
    if not dataclasses.is_dataclass(card) or isinstance(card, type):
        return {"repr": str(card)}
    готово: dict = {}
    for поле in dataclasses.fields(card):
        значение = getattr(card, поле.name)
        готово[поле.name] = list(значение) if isinstance(значение, tuple) else значение
    return готово


def advise(model: str, attribute: str = "", *, path: Path | None = None) -> dict:
    """What is known about one model, and how much of it is worth believing.

    :param attribute: one attribute to focus on (`max_seconds`, `resolution`,
        ...). Empty means "everything recorded about this model".
    :returns: the house judging dict plus `availability` (the registry's
        conservative answer), `claims` (every recorded value with its source),
        `failure_modes` (known ways it breaks, each with its fix) and
        `contested` (the attributes whose sources disagree).

    Three outcomes, and the middle one is the point: an unknown model is
    `could not measure`, never `fail`. Not knowing is a gap in this base, not
    a defect in the model, and the two must never print the same.
    """
    name = str(model or "").strip()
    if not name:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "reason": REASON_NO_MODEL_NAMED,
            "note": "no model was named, so nothing was looked up",
            "availability": None,
            "claims": {},
            "failure_modes": [],
            "class_findings": [],
            "contested": [],
        }

    store = store_for(path)
    live = registry.availability(name)
    # Разрешение имени — одно на весь проект (`studio/selfrag/modelnames.py`),
    # и здесь оно спрашивается, а не повторяется. До 2026-09-02 эта строка
    # сравнивала сырое написание с сырым: `flux-2-klein-9b` и
    # `flux.2-klein-9b` — одна модель в двух карманах, и спросивший первым
    # получал 2 атрибута из 6 при исходе `pass`.
    resolution = store.resolve(name)
    known_here = bool(resolution.names)

    # СПРОШЕННОЕ СЛОВО РАЗВОРАЧИВАЕТСЯ В ЗАПИСАННЫЕ ИМЕНА. ИЗМЕРЕНО
    # 2026-09-02: цена записана у 79 моделей, а на вопрос `price` отвечали 7
    # — у остальных 72 она лежит под `price_per_minute`,
    # `price_per_second_usd`, `price_per_image_usd` и ещё пятнадцатью именами.
    # Ответ «nothing is recorded» при записанном факте гонит спросившего
    # искать заново то, что уже лежит; правила разворота и его негативный
    # контроль — в `studio/selfrag/attrfamily.py`.
    if attribute:
        attributes = attrfamily.expand(attribute, store.attributes(name))
        # Не нашлось родственников — спрашиваем ровно то, что спросили, чтобы
        # ветка `attribute_unknown` ниже сработала как прежде (Р1).
        attributes = attributes or [attribute]
    else:
        attributes = store.attributes(name)
    asked_as = attrfamily.как_отвечено(attribute, attributes) if attribute else ""
    claims: dict[str, dict] = {}
    contested: list[str] = []
    for attr in attributes:
        verdict = store.claims(name, attr)
        claims[attr] = verdict
        if verdict["outcome"] == FAIL:
            contested.append(attr)

    failures = [
        {
            "value": fact.value,
            "fix": fact.fix,
            "source_url": fact.source_url,
            "tier": fact.tier,
            "stated_on": fact.stated_on,
        }
        for fact in store.failure_modes(name)
    ]

    # Findings about the CLASS, in their own list and never folded into the
    # per-model answer. They were recorded with `*` (the field) or
    # `<family>-*` (one vendor's line) as the model, which is the honest scope
    # and meant nothing ever returned them: every query starts with a model
    # name. MEASURED 2026-08-27, 26 such rows were in the base and reachable
    # by nobody.
    #
    # Separate rather than merged, because "said about the class" and
    # "measured on this model" are different claims and a reader has to be
    # able to tell them apart. They also never vote in a contradiction.
    card_vs_base = _card_vs_base(live.get("card"), store, name)

    # КАРТОЧКА ОТДАЁТСЯ СЛОВАРЁМ, А НЕ PYTHON-ОБЪЕКТОМ. Найдено чтением
    # собственной выдачи (П3, 2026-09-02): в ответе стояло
    #     "card": "ModelCard(model_id='kling-3.0', media='video', status=...)"
    # — то есть `repr()` датакласса, засунутый в поле JSON сериализатором
    # сервера (`default=str`). Потребитель не может прочесть из него ни одного
    # поля, не разбирая строку регулярками, а любой другой потребитель
    # (`json.dumps` без `default`) на этом объекте прямо падает.
    #
    # Преобразуется ОДИН раз и здесь, ниже по коду `live` уходит в шесть
    # разных ответов (Е1: одно знание — одно место).
    live = dict(live)
    live["card"] = _card_as_dict(live.get("card"))

    # The registry's note names the seven models it holds cards for, and it
    # reads as the whole of what is known. It is not: the fact base holds 205
    # ids. A blind evaluation asked about `omnihuman-1.5` and came away
    # reporting that "the fact base contains no dedicated lip-sync model",
    # having been shown a list of seven (OBSERVED 2026-08-27). So when the
    # registry misses, the base's own nearest ids go out beside it.
    if live.get("card") is None:
        near = store.near(name)
        if near:
            live = dict(live)
            live["note"] = (
                str(live.get("note", ""))
                + f" The FACT BASE is a different and much larger set: it holds "
                f"{store.model_count()} ids, among them {', '.join(near)}."
            )

    every_class_fact = _spread_by_attribute(
        sorted(
            store.class_claims(name),
            key=lambda f: (TIERS.index(f.tier) if f.tier in TIERS else len(TIERS), f.attribute),
        )
    )
    class_findings = [
        {
            "scope": fact.model,
            "attribute": fact.attribute,
            "value": fact.value,
            "fix": fact.fix,
            "source_url": fact.source_url,
            "tier": fact.tier,
            "stated_on": fact.stated_on,
        }
        for fact in every_class_fact[:CLASS_FINDINGS_SHOWN]
    ]
    # The denominator travels with the list (rule R2). 170 class facts stand
    # for most models after the 2026-08-27 verification pass, and returning
    # all of them would bury the model's own answer under statements about the
    # field. Strongest tier first, and the count of what was left out — a
    # silent truncation reads as "that is all there is".
    class_findings_note = (
        f"{len(class_findings)} of {len(every_class_fact)} findings about the class, "
        "strongest tier first. These were said about the field or about a vendor's "
        "line, NOT measured on this model."
    )

    if live["card"] is None and not known_here:
        # Соседние имена идут В ЭТУ ноту, а не только в `availability`. Ветка
        # писала свою ноту с нуля и теряла подсказку, добавленную выше, —
        # ПОЙМАНО на живом вопросе владельца 2026-08-31: он спросил про
        # `h3-max`, база держала `minimax-h3-max` с двадцатью одним атрибутом,
        # и верхняя нота отвечала «нет ни в реестре, ни в базе». Формально про
        # эту строку — верно; по существу — нет, и читают именно её.
        neighbours = store.near(name)
        # Два РАЗНЫХ положения дел, и до 2026-09-02 они печатались одинаково:
        # база не знает такого имени вовсе — и база знает соседнее имя, то
        # есть спрашивавший, вероятнее всего, опечатался. Первое лечится
        # поиском источника, второе — повторным вопросом. Нота их различала
        # словами, ответ — ничем.
        hint = (
            f" The base does hold {', '.join(neighbours)} — if that is the same "
            "model under another name, ask again by that id."
            if neighbours
            else ""
        )
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": (
                f"{name!r} is in neither the registry nor the fact base under "
                "that exact name. Nothing was checked, which is not the same as "
                "nothing being wrong. Search the web and call `record` to put it "
                "there." + hint
            ),
            "reason": REASON_NAME_MAYBE_MISTYPED if neighbours else REASON_MODEL_UNKNOWN,
            "near": list(neighbours),
            "availability": live,
            "claims": {},
            # The class findings come back even here. They are true of the
            # field, not of this name, so an unknown model does not make them
            # less true — and the outcome stays `could not measure` with
            # `checked` at 0, so nothing reads as having been verified.
            "failure_modes": [],
            "class_findings": class_findings,
            "class_findings_total": len(every_class_fact),
            "class_findings_note": class_findings_note,
            "card_vs_base": card_vs_base,
            "contested": [],
        }

    checked = len(claims) + (1 if live["card"] is not None else 0)
    if live["outcome"] == FAIL:
        return {
            "outcome": FAIL,
            "checked": checked,
            "violations": 1,
            "unmeasured": len(contested),
            "reason": REASON_MODEL_UNUSABLE,
            "note": f"the model itself is unusable: {live['note']}",
            "availability": live,
            "claims": claims,
            "failure_modes": failures,
            "class_findings": class_findings,
            "class_findings_total": len(every_class_fact),
            "class_findings_note": class_findings_note,
            "card_vs_base": card_vs_base,
            "contested": contested,
        }

    if contested:
        return {
            "outcome": FAIL,
            "checked": checked,
            "violations": len(contested),
            "unmeasured": 0,
            "note": (
                f"sources disagree on {', '.join(contested)}. Every side is "
                "returned with its URL and its date; nothing here votes, "
                "averages or takes the newest."
            ),
            "reason": REASON_SOURCES_DISAGREE,
            "availability": live,
            "claims": claims,
            "failure_modes": failures,
            "class_findings": class_findings,
            "class_findings_total": len(every_class_fact),
            "class_findings_note": class_findings_note,
            "card_vs_base": card_vs_base,
            "contested": contested,
        }

    if not claims:
        return {
            "outcome": UNMEASURED,
            "checked": checked,
            "violations": 0,
            "unmeasured": 1,
            "note": (
                f"the registry has a card for {name!r} but the fact base holds no "
                "claim about it, so there is nothing to cite. " + str(live["note"])
            ),
            "reason": REASON_NOTHING_RECORDED,
            "known_attributes": list(store.attributes(name)),
            "availability": live,
            "claims": {},
            "failure_modes": failures,
            "class_findings": class_findings,
            "class_findings_total": len(every_class_fact),
            "class_findings_note": class_findings_note,
            "card_vs_base": card_vs_base,
            "contested": [],
        }

    unmeasured = sum(1 for v in claims.values() if v["outcome"] == UNMEASURED)

    # ДВЕ ОСИ, И ОНИ БОЛЬШЕ НЕ ПОДМЕНЯЮТ ДРУГ ДРУГА.
    #
    # Здесь стояло `live["outcome"] == UNMEASURED or ...`, и из-за этого
    # вердикт о ЗНАНИИ выносился по реестру ДОСТУПНОСТИ. В реестре семь имён;
    # в базе фактов 466. ИЗМЕРЕНО 2026-09-02 на живой базе до правки: 457
    # моделей из 466 получали `could not measure` при непустом свидетельстве,
    # а по парам «модель.атрибут» — 999 из 1236 при утверждении с исходом
    # `pass`. Пользователь получал «не знаю» поверх готового ответа вендора:
    # `seedance-2.5.max_seconds` вернуло `could not measure` со значением
    # `'30'` из вендорского источника в руках.
    #
    # Доступность не исчезла и не должна: она отдельная ось («знаем ли мы»
    # против «можно ли этим воспользоваться») и по-прежнему едет целиком в
    # `availability`, а её собственный вердикт называется в ноте. Она НЕ
    # выносит вердикт о знании — но остаётся видимой, и `fail` от неё
    # (модель снята с обслуживания) выше по функции по-прежнему главнее
    # всего: платить за 404 нельзя, даже зная про модель всё.
    axis = f" Availability is a SEPARATE axis, and it says {live['outcome']!r}: {live['note']}"
    if unmeasured == len(claims):
        why = gap_reason(claims)
        gap_note = (
            f"nothing is recorded about {'.'.join(filter(None, (name, attribute)))}"
            if why == REASON_ATTRIBUTE_UNKNOWN
            else (
                f"{unmeasured} of {len(claims)} attribute(s) rest on blog-tier or "
                "stale sources only, and repetition is not corroboration"
            )
        )
        return {
            "outcome": UNMEASURED,
            "checked": checked,
            "violations": 0,
            "unmeasured": max(unmeasured, 1),
            "note": (
                f"{gap_note}. The model itself IS in the fact base, so this is a "
                "gap in what was recorded, not an unknown name." + axis
            ),
            "reason": why,
            # Что о модели ЕСТЬ. Без этого «не смогли» на опечатку в атрибуте
            # неотличимо от «не смогли» на настоящий пробел, и спрашивавшему
            # нечем сделать следующий шаг.
            "known_attributes": list(store.attributes(name)),
            "availability": live,
            "claims": claims,
            "failure_modes": failures,
            "class_findings": class_findings,
            "class_findings_total": len(every_class_fact),
            "class_findings_note": class_findings_note,
            "card_vs_base": card_vs_base,
            "contested": [],
        }

    return {
        "outcome": PASS,
        "checked": checked,
        "violations": 0,
        "unmeasured": unmeasured,
        "note": (
            f"{len(claims)} attribute(s) answered from {claims_found(claims)} recorded "
            f"source(s), {unmeasured} of them only weakly."
            # Разворот спрошенного слова называется в ноте, а не только в
            # ключах: читают ноту, и «спросил price — получил price_per_minute»
            # обязано быть видно там же, где ответ.
            + (f" ВНИМАНИЕ: {asked_as}" if asked_as else "")
            + axis
        ),
        "reason": REASON_ANSWERED,
        "asked_as": asked_as,
        "availability": live,
        "claims": claims,
        "failure_modes": failures,
        "class_findings": class_findings,
        "class_findings_total": len(every_class_fact),
        "class_findings_note": class_findings_note,
        "card_vs_base": card_vs_base,
        "contested": [],
    }


def record(
    model: str,
    attribute: str,
    value: str,
    source_url: str,
    tier: str,
    stated_on: str,
    *,
    note: str = "",
    fix: str = "",
    read_directly: bool | None = None,
    witnessed: str = "",
    path: Path | None = None,
) -> dict:
    """Write one web finding into the fact base, with who said it and when.

    Every argument up to `stated_on` is required and none may be blank. A claim
    without a URL cannot be re-checked; a claim without a date cannot go stale;
    a claim without a tier would let a blog outrank a vendor document.

    :param tier: one of `TIERS`, but only three of them are yours to choose.

        `probe`, `paper` and `benchmark` say HOW the fact was obtained — the
        API was asked, a venue published a method — and no URL can tell anyone
        that, so you state them and they are taken as stated.

        `vendor`, `portal` and `blog` say WHOSE PAGE IT IS, and that is decided
        from the URL by `source_hosts.classify`, not by you. Passing one that
        the URL contradicts is refused rather than quietly corrected: a caller
        who believes `docs.example.com` is the vendor for this model and is
        wrong needs to find out, and a caller who is right needs the table
        updated. Silently overriding either would put the ladder back where it
        was on 2026-08-27, when `blog` held nine vendor pages.
    :param read_directly: True if you opened the page (or the API answered
        you), False if you know it only through somebody else's summary. Leave
        it None when you did not record it — that is a third state and it is
        not the same as False.
    :param stated_on: ISO date the SOURCE stated it, not today's date. Writing
        today's date for an old article is how a stale claim looks fresh.

    :returns: three outcomes. A rejected claim is `fail` and is not written.

    RECORDING SOMETHING ALREADY RECORDED IS AN UPDATE, NOT A SECOND SOURCE.
    A claim is `(model, attribute, value, source_url)`, and this appends a row
    that supersedes any earlier one with that key — which is how a fact known
    through a summary becomes one somebody opened, without the page counting
    twice. An append that would change nothing is skipped, so a script that
    replays a reading pass can be re-run without growing the file.

    If the page turns out not to say what was recorded, this is the wrong
    door: `withdraw` is, and it takes a reason.
    """
    fields = {
        "model": str(model or "").strip(),
        "attribute": str(attribute or "").strip(),
        "value": str(value or "").strip(),
        "source_url": str(source_url or "").strip(),
        "tier": str(tier or "").strip().lower(),
        "stated_on": str(stated_on or "").strip(),
    }
    missing = [name for name, text in fields.items() if not text]
    if missing:
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": len(missing),
            "unmeasured": 0,
            "note": (
                "nothing was written: " + ", ".join(missing) + " is required. "
                "A claim missing any of these cannot be re-checked later."
            ),
            "written": None,
        }

    if fields["tier"] not in TIERS:
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": 1,
            "unmeasured": 0,
            "note": f"tier {fields['tier']!r} is not one of {', '.join(TIERS)}",
            "written": None,
        }

    # Тир `operator` стоит третьим сверху — выше статьи и выше бенчмарка, — и
    # платит за это единственным условием: сказать, ЧТО ИМЕННО было запущено и
    # что вышло. Без этого запись отвергается, а не просто весит меньше.
    # «Модель держит текст» — мнение; «подали кадр с текстом, отрисованным
    # Pillow, текст дошёл без искажений» — факт, который кто-то может пойти и
    # опровергнуть. Ярлык нужен ровно затем, чтобы одно отличалось от другого.
    if fields["tier"] == TIER_OPERATOR and not str(witnessed).strip():
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": 1,
            "unmeasured": 0,
            "note": (
                "ничего не записано: тир operator требует поля witnessed — что "
                "запущено и что вышло, в наблюдаемых словах. Вывод без "
                "наблюдения это мнение, а тир для мнений уже есть, он "
                "называется blog"
            ),
            "written": None,
        }

    # У наблюдения оператора страницы нет и быть не может, поэтому требование
    # http-ссылки к нему не применяется: `source_url` несёт его собственную
    # отметку — дату разговора, номер задачи, путь к файлу.
    if fields["tier"] != TIER_OPERATOR and not fields["source_url"].startswith(
        ("http://", "https://")
    ):
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": 1,
            "unmeasured": 0,
            "note": f"source_url {fields['source_url']!r} is not a URL",
            "written": None,
        }

    # Who owns the page is read off the URL; how the fact was obtained is not.
    if fields["tier"] in IDENTITY_TIERS:
        owner = source_hosts.classify(
            fields["model"],
            fields["source_url"],
            vendor_tier=TIER_VENDOR,
            portal_tier=TIER_PORTAL,
            blog_tier=TIER_BLOG,
        )
        if owner != fields["tier"]:
            return {
                "outcome": FAIL,
                "checked": len(fields),
                "violations": 1,
                "unmeasured": 0,
                "note": (
                    f"tier {fields['tier']!r} does not match the URL: "
                    f"{source_hosts.host_of(fields['source_url']) or 'that host'} is "
                    f"{owner!r} for {fields['model']}. The URL decides the rung. If "
                    f"this host really is {fields['tier']} for this model, add it to "
                    "studio/selfrag/source_hosts.py and record again."
                ),
                "written": None,
            }

    try:
        stated = date.fromisoformat(fields["stated_on"])
    except ValueError:
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": 1,
            "unmeasured": 0,
            "note": f"stated_on {fields['stated_on']!r} is not an ISO date (YYYY-MM-DD)",
            "written": None,
        }
    if stated > date.today():
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": 1,
            "unmeasured": 0,
            "note": f"stated_on {fields['stated_on']} is in the future",
            "written": None,
        }

    # Annotated because `read_directly` is the one non-string value in the row;
    # without it the whole dict widens and `row["model"]` stops being a str.
    row: dict[str, str | bool | None] = {
        **fields,
        "note": str(note or ""),
        "fix": str(fix or ""),
        "read_directly": None if read_directly is None else bool(read_directly),
        "witnessed": str(witnessed or ""),
    }
    target = path or DEFAULT_FACTS_PATH
    key = claim_key(fields["model"], fields["attribute"], fields["value"], fields["source_url"])
    before = {claim_key(f.model, f.attribute, f.value, f.source_url): f for f in load_facts(target)}
    standing = before.get(key)
    unchanged = standing is not None and _same_claim(standing, row)

    if not unchanged:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    after = store_for(target).claims(fields["model"], fields["attribute"])
    if unchanged:
        what = "already stood exactly like this, so nothing was appended"
    elif standing is None:
        what = "written as a new claim"
    else:
        what = f"supersedes the row that stood before it ({_diff(standing, row)})"
    return {
        "outcome": PASS,
        "checked": len(fields),
        "violations": 0,
        "unmeasured": 0,
        "note": (
            f"{what}. {row['model']}.{row['attribute']} now stands at "
            f"{after['outcome']!r} across {after.get('checked', 0)} source(s)."
        ),
        "written": None if unchanged else row,
        "superseded": None if standing is None else _as_row(standing),
        "claims_now": after,
    }


def _as_row(fact: Fact) -> dict:
    """A stored fact in the shape `record` writes, so the two can be compared."""
    return {
        "model": fact.model,
        "attribute": fact.attribute,
        "value": fact.value,
        "source_url": fact.source_url,
        "tier": fact.tier,
        "stated_on": fact.stated_on,
        "note": fact.note,
        "fix": fact.fix,
        "read_directly": fact.read_directly,
    }


#: What `record` may change about a standing claim. Model, attribute, value and
#: URL are excluded because changing one of those makes it a different claim.
MUTABLE_FIELDS: tuple[str, ...] = ("tier", "stated_on", "note", "fix", "read_directly")


def _same_claim(standing: Fact, row: dict) -> bool:
    """True when appending `row` would tell a reader nothing new."""
    return all(_as_row(standing)[name] == row.get(name) for name in MUTABLE_FIELDS)


def _diff(standing: Fact, row: dict) -> str:
    """Name the fields the new row changes, so the caller sees what moved."""
    was = _as_row(standing)
    moved = [f"{n}: {was[n]!r} -> {row.get(n)!r}" for n in MUTABLE_FIELDS if was[n] != row.get(n)]
    return "; ".join(moved) if moved else "nothing"


def withdraw(
    model: str,
    attribute: str,
    value: str,
    source_url: str,
    reason: str,
    *,
    path: Path | None = None,
) -> dict:
    """Take back a claim its own source does not make, and say why.

    The door for the thing this base was built wrong around: a claim recorded
    from somebody's summary, whose page, once opened, says nothing of the sort.
    MEASURED 2026-08-27, the day the vendor hosts were unblocked: `wavespeed.ai/`
    was cited for what Veo 3.1 is best for and the page does not contain the
    string "Veo" at all.

    Deleting the line would be the obvious move and it is the wrong one — it
    loses the fact that anybody believed this, and the next research pass
    re-derives it from the same summary. So the withdrawal is APPENDED, carries
    its reason, and `load_facts` drops the claim from what the base asserts
    while the file keeps the argument.

    :param reason: required, and not decorative. "wrong" tells the next reader
        nothing; "the page does not mention Veo" tells them what was checked.
    :returns: three outcomes. Withdrawing a claim nobody recorded is
        `could not measure`, never `pass` — a caller who misspelled the model
        would otherwise be told their withdrawal worked.
    """
    fields = {
        "model": str(model or "").strip(),
        "attribute": str(attribute or "").strip(),
        "value": str(value or "").strip(),
        "source_url": str(source_url or "").strip(),
        "reason": str(reason or "").strip(),
    }
    missing = [name for name, text in fields.items() if not text]
    if missing:
        return {
            "outcome": FAIL,
            "checked": len(fields),
            "violations": len(missing),
            "unmeasured": 0,
            "note": (
                "nothing was withdrawn: " + ", ".join(missing) + " is required. "
                "A withdrawal names the exact claim it takes back and says why."
            ),
            "withdrawn": None,
        }

    target = path or DEFAULT_FACTS_PATH
    key = claim_key(fields["model"], fields["attribute"], fields["value"], fields["source_url"])
    standing = {
        claim_key(f.model, f.attribute, f.value, f.source_url): f for f in load_facts(target)
    }
    if key not in standing:
        return {
            "outcome": UNMEASURED,
            "checked": 1,
            "violations": 0,
            "unmeasured": 1,
            "note": (
                f"no claim {fields['model']}.{fields['attribute']} = {fields['value']!r} "
                f"from {fields['source_url']} stands in the base, so nothing was "
                "withdrawn. Check the model, the attribute, the exact value and the "
                "exact URL: all four identify a claim."
            ),
            "withdrawn": None,
        }

    row: dict[str, str | bool] = {
        "model": fields["model"],
        "attribute": fields["attribute"],
        "value": fields["value"],
        "source_url": fields["source_url"],
        "withdrawn": True,
        "note": fields["reason"],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    after = store_for(target).claims(fields["model"], fields["attribute"])
    return {
        "outcome": PASS,
        "checked": 1,
        "violations": 0,
        "unmeasured": 0,
        "note": (
            f"withdrawn: {fields['reason']} — {fields['model']}.{fields['attribute']} "
            f"now stands at {after['outcome']!r} across {after.get('checked', 0)} source(s)."
        ),
        "withdrawn": row,
        "claims_now": after,
    }


#: Тиры, у которых дата — это ДАТА ПУБЛИКАЦИИ, а не срок годности. Статья и
#: бенчмарк опубликованы однажды и говорят одно и то же всегда; «поищи в сети и
#: запиши, что найдёшь» для них — работа, которую нельзя сделать.
#:
#: ИЗМЕРЕНО 2026-09-02: из 49 строк, объявленных протухшими, 21 (20 статей и
#: 1 бенчмарк) именно такая, то есть 43% очереди — работа впустую. Остальные
#: 28 — цены площадок и вендорские спеки, и они протухают по-настоящему.
PUBLISHED_TIERS: frozenset[str] = frozenset({TIER_PAPER, TIER_BENCHMARK})


#: Сколько источников назвать поимённо в краткой выдаче. ВЫБРАНО 1: у краткой
#: формы одна работа — дать СРАВНИМЫЕ величины по кандидатам, а разбор
#: источников делается по полной выдаче того кандидата, который прошёл отбор.
КРАТКО_ИСТОЧНИКОВ = 1


def brief(model: str, attribute: str = "", *, path: Path | None = None) -> dict:
    """Та же выдача, но в размере, который не съедает ответ пользователю.

    ЗАЧЕМ. ИЗМЕРЕНО 2026-09-02: полный ответ по `minimax-h3` — 23 751 символ,
    около 10 тысяч токенов, и почти весь объём в двух местах: `claims` 17 214
    и `class_findings` 4 394. Инструкция сервера велит спросить базу о КАЖДОМ
    кандидате перед сравнением — это правильное правило, но пять кандидатов
    стоят 30–50 тысяч токенов, и на сам ответ места остаётся мало.

    Краткая форма — ВИД на полную, а не второй ответ (Е1): она строится из неё
    же, поэтому разойтись они не могут. Выбрасывается только то, что нужно для
    РАЗБОРА одного кандидата, и остаётся то, что нужно для СРАВНЕНИЯ многих:
    исход, причина, значения, лучшая ступень, спорность, свежесть и число
    источников.

    Что НЕ выбрасывается ни при каких условиях: третий исход и его причина,
    отметка о споре источников и колонка применимости. Ради экономии нельзя
    терять ровно то, чем этот инструмент отличается от памяти модели.
    """
    полный = advise(model, attribute, path=path)
    кратко: dict = {
        ключ: полный[ключ]
        for ключ in (
            "outcome",
            "checked",
            "violations",
            "unmeasured",
            "reason",
            "note",
            # Разворот спрошенного слова едет и в краткую форму: именно она
            # стоит по умолчанию у `model_advice`, и потерять в ней «спросили
            # price, ответили price_per_minute» значит вернуть дефект туда,
            # где его читают чаще всего.
            "asked_as",
        )
        if ключ in полный
    }
    доступность = полный.get("availability") or {}
    кратко["availability"] = {
        "outcome": доступность.get("outcome"),
        "note": доступность.get("note"),
    }
    сжатые: dict = {}
    for атрибут, разбор in (полный.get("claims") or {}).items():
        источники = [
            и for строка in (разбор.get("claims") or []) for и in (строка.get("sources") or [])
        ]
        сжатые[атрибут] = {
            "outcome": разбор.get("outcome"),
            "values": разбор.get("values")
            or [строка.get("value") for строка in (разбор.get("claims") or [])],
            "best_tier": min(
                (строка.get("best_tier", "") for строка in (разбор.get("claims") or [])),
                key=lambda t: TIERS.index(t) if t in TIERS else len(TIERS),
                default="",
            ),
            "sources": len(источники),
            "newest": max((str(и.get("stated_on") or "") for и in источники), default=""),
            "read_first_hand": any(и.get("read_directly") for и in источники),
            "example_url": ([и.get("url") for и in источники] or [""])[:КРАТКО_ИСТОЧНИКОВ],
        }
    кратко["claims"] = сжатые
    кратко["failure_modes"] = [
        строка.get("value") if isinstance(строка, dict) else строка
        for строка in (полный.get("failure_modes") or [])
    ]
    кратко["contested"] = полный.get("contested")
    кратко["class_findings_total"] = полный.get("class_findings_total")
    кратко["class_findings_note"] = полный.get("class_findings_note")
    кратко["full_answer"] = (
        "это КРАТКАЯ форма: разбор источников, ноты и находки о классе лежат в "
        "полной выдаче — позовите тот же инструмент без `brief`"
    )
    return кратко


def stale(*, days: int = STALE_AFTER_DAYS, path: Path | None = None) -> dict:
    """Which claims are old enough to need a fresh look on the web.

    A claim with no date is counted as unmeasured, not as fresh. That is the
    whole reason `record` insists on a date.
    """
    facts = load_facts(path or DEFAULT_FACTS_PATH)
    if not facts:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "the fact base is empty: there is nothing to age",
            "stale": [],
            "undated": [],
        }

    old: list[dict] = []
    undated: list[dict] = []
    published: list[dict] = []
    for fact in facts:
        age = fact.age_days
        row = {
            "model": fact.model,
            "attribute": fact.attribute,
            "value": fact.value,
            "source_url": fact.source_url,
            "tier": fact.tier,
            "stated_on": fact.stated_on,
            "age_days": age,
        }
        if age is None:
            undated.append(row)
        elif age > days:
            # ДАТА ПУБЛИКАЦИИ — НЕ ИЗНОС. Найдено чтением выдачи (П3,
            # 2026-09-02): из 49 «протухших» строк 21 оказалась СТАТЬЁЙ или
            # бенчмарком, и первая — arXiv:2103.00020 от 2021 года. Статья
            # сегодня говорит ровно то же, что и в день публикации; «поищи в
            # сети и запиши, что найдёшь» для неё — работа, которую нельзя
            # сделать. А очередь, где такой работы 43%, читается по диагонали,
            # и вместе с ней по диагонали читаются 28 строк, которые ДЕЙСТВИТЕЛЬНО
            # протухли: цены площадок и вендорские спеки.
            #
            # Не выброшено, а ОТДЕЛЕНО: статья 2021 года о модели, которая с тех
            # пор изменилась, вводит в заблуждение по-настоящему. Но лечится это
            # не перечитыванием статьи, а измерением модели, и в ноте сказано
            # именно так.
            (published if fact.tier in PUBLISHED_TIERS else old).append(row)

    old.sort(key=lambda row: -(row["age_days"] or 0))
    published.sort(key=lambda row: -(row["age_days"] or 0))
    if old or undated:
        return {
            "outcome": FAIL,
            "checked": len(facts),
            "violations": len(old),
            "unmeasured": len(undated),
            "note": (
                f"{len(old)} claim(s) older than {days} days and {len(undated)} "
                f"with no date at all, out of {len(facts)} checked. Search the "
                "web for these and call `record` with what you find. "
                f"Separately, {len(published)} claim(s) rest on a PUBLISHED "
                "source (paper or benchmark) older than that: a paper does not "
                "rot, so re-reading it changes nothing. If one of those models "
                "has moved since, the answer is a fresh measurement of the "
                "model, not a fresh reading of the paper."
            ),
            "stale": old,
            "undated": undated,
            "published_and_old": published,
        }

    return {
        "outcome": PASS,
        "checked": len(facts),
        "violations": 0,
        "unmeasured": 0,
        "note": (
            f"all {len(facts)} claim(s) are within {days} days"
            + (
                f"; {len(published)} rest on a published source older than that, "
                "which is a date and not decay"
                if published
                else ""
            )
        ),
        "stale": [],
        "undated": [],
        "published_and_old": published,
    }
