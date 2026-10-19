"""Real-time / live work is a different product class: a recorded gap, not a batch plan (round 13).

WHY. The round-13 hidden set found "an interactive avatar that answers visitors live"
and "live dubbing of our webinar" answered with a spec question (no duration) or,
with a duration, a batch plan priced per rendered second. Every endpoint the planner
selects renders a CLIP: a talking-avatar or lip-sync model takes seconds to minutes
per second of output, and a dubbing endpoint takes the whole file. A live avatar or a
live interpreter is a STREAMING system — speech recognition, a language model, speech
synthesis and a face renderer chained under a latency budget of a few hundred
milliseconds, billed per minute of session. Pricing it as hours of rendered clips is
the wrong product at the wrong price.

THE RULE (one rule):
    the brief or spec.conditions names real time / live / streaming / low latency
    (not negated, not "live-action", not "real-time strategy")
    AND the work is speech or a speaking face (avatar, lip sync, dub, voice, captions,
    or speech among the outputs)                                      -> recorded gap

The answer lists what the BASE records for real-time use (a latency figure, a
"real-time" positioning, a realtime build of a model) — or says that none is
recorded — and never a batch price.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

#: Live / real-time / streaming words. "live" counts only next to a live-system noun or
#: after a speaking verb ("answers customers live").
REALTIME = re.compile(
    r"real[- ]?time|\bin real time\b|\blive[- ]?(?:stream\w*|dub\w*|translat\w*|interpret\w*|chat|conversation\w*"
    r"|call\w*|avatar\w*|caption\w*|subtitl\w*|broadcast\w*|q&a|session\w*|meeting\w*|webinar\w*|zoom)"
    r"|(?:answer\w*|respond\w*|talk\w*|reply\w*|chat\w*|speak\w*|translat\w*|dub\w*) (?:\w+ ){0,3}live\b"
    r"|\bstreaming avatar|interactive avatar|low[- ]latency|\blatency\b|conversational avatar|on a (?:video )?call"
    r"|реальн\w* времен\w*|в прямом эфире|прям\w+ эфир\w*|онлайн-перевод\w*|синхронн\w+ перевод\w*"
    r"|живо\w* (?:перевод\w*|дубляж\w*|аватар\w*|диалог\w*|общени\w*)|стрим\w*|задержк\w*|интерактивн\w+ аватар\w*",
    re.I,
)
#: Not a live system: shot footage, a game genre, a rendered preview.
NOT_LIVE = re.compile(
    r"live[- ]action|real[- ]time strategy|real[- ]time render\w*|\brts\b|live footage|live recording"
    r"|recorded live|live concert|live performance|живая съёмк\w*|запис\w* (?:прямого )?эфир\w*",
    re.I,
)
#: A live word preceded by one of these within `NEGATION_WINDOW` words is not asked for.
NEGATION = re.compile(r"^(?:no|not|without|never|needn't|don't|doesn't|isn't|не|нет|без|ненужн\w*)$", re.I)
#: DECISION CONSTANT (T1): words before a live word searched for a negation ("does not need to be real
#: time" — 4; a wider window reads an unrelated "no" earlier in the sentence).
NEGATION_WINDOW = 4
#: Work that a live system does: speech in, speech or a speaking face out.
REALTIME_TASKS: frozenset[str | None] = frozenset(
    {"avatar", "lipsync", "dub-translate", "voice-clone", "transcribe", "captions"}
)
#: Outputs that make the work a speaking one even when the task is not named.
SPEAKING_OUTPUTS: frozenset[str] = frozenset({"speech"})

#: Attributes of a recorded fact that speak about live use.
REALTIME_ATTRIBUTES: frozenset[str] = frozenset({"latency", "realtime_dubbing"})
#: A model id that names a realtime build, or a positioning that says real-time / streaming.
REALTIME_MODEL = re.compile(r"realtime|real-time|conversational|streaming", re.I)
REALTIME_VALUE = re.compile(r"real[- ]?time|streaming", re.I)
#: How many recorded options the answer lists (the strongest first).
OPTIONS_SHOWN = 8

REASON_NOT_SUPPORTED = "работа_не_поддерживается"

WHY = (
    "работа в реальном времени (живой аватар, живой дубляж) — другой класс продукта: потоковая система "
    "(распознавание речи -> языковая модель -> синтез речи -> рендер лица) с бюджетом задержки в сотни "
    "миллисекунд и оплатой за минуту сеанса; модели плана рендерят КЛИПЫ (секунды и минуты на секунду "
    "ролика), и цена часов отрендеренного видео была бы ценой не того продукта",
    "real-time work (a live avatar, live dubbing) is a different product class: a streaming system "
    "(speech recognition -> language model -> speech synthesis -> face renderer) under a latency budget of a "
    "few hundred milliseconds, billed per session minute; the planner's models render CLIPS (seconds to "
    "minutes per second of output), and a price for hours of rendered video would be the price of the wrong "
    "product",
)
INSTEAD = (
    "нужен потоковый сервис интерактивных аватаров или синхронного перевода (класс HeyGen Interactive Avatar, "
    "Tavus, D-ID Agents — в базе не записаны, цен нет) или своя потоковая цепочка из моделей с записанной "
    "задержкой (ниже); заранее записанный ролик с тем же аватаром или дубляж записи — обычный план: уберите "
    "«в реальном времени» и назовите длительность",
    "use a streaming interactive-avatar or live-interpretation service (the HeyGen Interactive Avatar, Tavus, "
    "D-ID Agents class — not recorded in the base, no prices), or build a streaming chain from models with a "
    "recorded latency (below); a pre-rendered clip with the same avatar, or a dub of the recording, is an "
    "ordinary plan: drop 'real time' and give the duration",
)
NONE_RECORDED = (
    "в базе не записано ни одного варианта для работы в реальном времени (ни задержки, ни потокового режима)",
    "no real-time option is recorded in the base (no latency figure, no streaming mode)",
)


def _negated(text: str, start: int) -> bool:
    before = re.findall(r"[\w'’-]+", text[:start].lower())[-NEGATION_WINDOW:]
    return any(NEGATION.match(w) for w in before)


def asked(text: str) -> bool:
    """A live / real-time system is asked for in these words (not negated, not live-action)."""
    t = " ".join(str(text or "").split())
    clean = NOT_LIVE.sub(" ", t)
    return any(not _negated(clean, m.start()) for m in REALTIME.finditer(clean))


def _spec_field(spec: Mapping[str, Any] | None, name: str) -> Any:
    return spec.get(name) if isinstance(spec, Mapping) else None


def applies(brief: str, spec: Mapping[str, Any] | None) -> bool:
    """The order is real-time speaking work: a recorded gap, not a batch plan."""
    said = [str(brief or ""), *(str(c) for c in (_spec_field(spec, "conditions") or ()) if c)]
    if not any(asked(s) for s in said):
        return False
    task = _spec_field(spec, "task")
    tasks = set(task) if isinstance(task, (list, tuple)) else {task}
    outputs = {str(o) for o in (_spec_field(spec, "outputs") or ())}
    return bool(tasks & REALTIME_TASKS) or bool(outputs & SPEAKING_OUTPUTS)


def options(facts: Sequence[Any]) -> list[dict[str, str]]:
    """What the base records for real-time use: one row per model, the strongest fact first."""
    rows: dict[str, dict[str, str]] = {}
    for f in facts:
        model, attr, value = str(f.model), str(f.attribute), str(f.value)
        if model == "*":
            continue
        strong = attr in REALTIME_ATTRIBUTES
        weak = attr == "positioning" and REALTIME_VALUE.search(value) or REALTIME_MODEL.search(model)
        if not (strong or weak):
            continue
        row = {"model": model, "attribute": attr, "value": value[:160], "source": str(f.source_url)}
        if model not in rows or (strong and rows[model]["attribute"] not in REALTIME_ATTRIBUTES):
            rows[model] = row
    ranked = sorted(rows.values(), key=lambda r: (r["attribute"] not in REALTIME_ATTRIBUTES, r["model"]))
    return ranked[:OPTIONS_SHOWN]


def gap(brief: str, english: bool, facts: Sequence[Any] | None = None) -> dict:
    """The answer: a recorded gap with the real-time options the base knows (or that it knows none)."""
    if facts is None:
        from studio.selfrag.facts import load_facts

        facts = load_facts()
    found = options(facts)
    i = 1 if english else 0
    known = (
        "; ".join(f"{r['model']}: {r['attribute']} {r['value']}" for r in found) if found else NONE_RECORDED[i]
    )
    head = "NOT SUPPORTED" if english else "НЕ ПОДДЕРЖИВАЕТСЯ"
    recorded = "real-time options recorded in the base" if english else "в базе для реального времени записано"
    return {
        "summary": f"{head}: {WHY[i]}. {INSTEAD[i]}. {recorded}: {known}",
        "outcome": "could not measure" if english else "не смогли",
        "reason": REASON_NOT_SUPPORTED,
        "checked": 0,
        "violations": 0,
        "unmeasured": 1,
        "note": WHY[i],
        "gap": {
            "job": "real-time",
            "recorded": True,
            "why": WHY[i],
            "instead": INSTEAD[i],
            "realtime_options": found,
            "realtime_options_note": "" if found else NONE_RECORDED[i],
        },
        "question": None,
        "brief": brief,
        "steps": [],
        "classes": [],
        "pipeline_price": {},
        "что_дальше": INSTEAD[i],
    }
