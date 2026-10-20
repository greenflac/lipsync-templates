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

THE RULE (one rule; round 15: `spec.live` decides when the caller fills it, the words are the
fallback):
    spec.live is true — or, absent, the brief or spec.conditions names real time / live / streaming / low latency
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

#: LIVE-SYSTEM words (round 14): a live stream / call / broadcast / live dubbing / an
#: interactive or conversational avatar. One of these alone is live work. "live" counts
#: only next to a live-system noun ("live AI avatar" — up to two words between) or after
#: a speaking verb ("answers customers live").
LIVE = re.compile(
    r"\blive[- ]?(?:stream\w*|dub\w*|translat\w*|interpret\w*|chat|conversation\w*"
    r"|call\w*|caption\w*|subtitl\w*|broadcast\w*|q&a|session\w*|meeting\w*|webinar\w*|zoom)"
    r"|\blive (?:[\w-]+ ){0,2}avatar\w*"
    r"|(?:answer\w*|respond\w*|talk\w*|reply\w*|chat\w*|speak\w*|translat\w*|dub\w*) (?:\w+ ){0,3}live\b"
    r"|\bstreaming avatar|interactive avatar|conversational avatar|on a (?:video )?call|\bvideo[- ]?call\w*"
    r"|\b(?:joins?|joining|in|into|during) (?:our |the |a |my )?(?:zoom|teams|google meet)\b|\bon[- ]air\b"
    r"|в прямом эфире|прям\w+ эфир\w*|онлайн-перевод\w*|синхронн\w+ перевод\w*|видеозвонк\w*|созвон\w*"
    r"|живо\w* (?:перевод\w*|дубляж\w*|аватар\w*|диалог\w*|общени\w*)|стрим\w*|интерактивн\w+ аватар\w*"
    # Integration of round 14: the same live-broadcast / live-stream / video-call nouns in the
    # other brief languages (ko, ja, zh, es, pt, de, fr) — a live broadcast is live work in any
    # language, not only when an English speed word sits in the conditions.
    r"|라이브 ?(?:방송|스트리밍|스트림)|생방송|실시간 ?(?:방송|스트리밍|스트림)|화상 ?통화"
    r"|生配信|ライブ配信|生放送|ビデオ通話|直播|视频通话|視訊通話"
    r"|transmisi[oó]n en (?:vivo|directo)|videollamada\w*|transmiss[aã]o ao vivo|videochamada\w*"
    r"|live-?übertragung\w*|videoanruf\w*|videotelefonat\w*|diffusion en direct|appel vidéo",
    re.I,
)
#: SPEED words (round 14): real time / low latency / latency. Alone they describe a FAST
#: system — on-device or low-latency speech synthesis is an ordinary TTS plan (the latency
#: is a ranking condition, printed among the unmeasured requirements). They make the work
#: live only when the brief is INTERACTIVE (someone is answered in session) and a face is
#: rendered (`FACE_TASKS` / a video output).
SPEED = re.compile(
    r"real[- ]?time|\bin real time\b|low[- ]latency|\blatency\b|реальн\w* времен\w*|задержк\w*"
    r"|실시간|リアルタイム|实时|實時|tiempo real|tempo real|echtzeit|temps réel",
    re.I,
)
#: Someone is answered IN SESSION: visitors, viewers, callers, a conversation.
INTERACTIVE = re.compile(
    r"\b(?:answer\w*|respond\w*|repl(?:y|ies|ying)|talk\w* (?:with|to)|chat\w* with|convers\w*|interact\w*)\b"
    r"|\b(?:visitors?|viewers?|callers?|attendees?|participants?)\b|\bin (?:the |a )?session\b|\bdialog\w*"
    r"|отвеча\w*|разговарива\w*|общает\w*|собеседник\w*|зрител\w*|посетител\w*|в сесси\w*|диалог\w*|интерактив\w*",
    re.I,
)
#: Kept for callers that read one pattern: either kind of word.
REALTIME = re.compile(f"{LIVE.pattern}|{SPEED.pattern}", re.I)
#: Tasks that render a FACE: a speed word with an interactive brief is live only for these
#: (or with a video output) — a fast TTS voice for a bot is still a TTS plan.
FACE_TASKS: frozenset[str | None] = frozenset({"avatar", "lipsync", "dub-translate"})
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


def _said(pattern: re.Pattern[str], clean: str) -> bool:
    return any(not _negated(clean, m.start()) for m in pattern.finditer(clean))


def asked(text: str, face: bool = True) -> bool:
    """A live / real-time system is asked for in these words (not negated, not live-action).

    A live-system word is enough; a speed word ("real time", "low latency") only with an
    interactive brief and a rendered face (`face`).
    """
    t = " ".join(str(text or "").split())
    clean = NOT_LIVE.sub(" ", t)
    if _said(LIVE, clean):
        return True
    return face and _said(SPEED, clean) and bool(INTERACTIVE.search(clean))


def _spec_field(spec: Mapping[str, Any] | None, name: str) -> Any:
    return spec.get(name) if isinstance(spec, Mapping) else None


def _outputs(spec: Mapping[str, Any] | None) -> set[str]:
    """Output kinds of a raw spec: strings, or objects {kind, loop?, tileable?} (round 15)."""
    raw = _spec_field(spec, "outputs") or ()
    if isinstance(raw, (str, Mapping)):
        raw = [raw]
    return {str(o.get("kind") if isinstance(o, Mapping) else o) for o in raw}


def applies(brief: str, spec: Mapping[str, Any] | None) -> bool:
    """The order is real-time speaking work: a recorded gap, not a batch plan.

    Round 15 — SPEC FIRST: `spec.live` (true | false) decides whether the system is live, in any
    brief language; the live / speed words below are read only when it is absent. The work must
    still be speaking work (a speaking task or speech among the outputs) for the gap.
    """
    live = _spec_field(spec, "live")
    task = _spec_field(spec, "task")
    tasks = set(task) if isinstance(task, (list, tuple)) else {task}
    outputs = _outputs(spec)
    if isinstance(live, bool):
        return live and (bool(tasks & REALTIME_TASKS) or bool(outputs & SPEAKING_OUTPUTS))
    said = " ".join([str(brief or ""), *(str(c) for c in (_spec_field(spec, "conditions") or ()) if c)])
    if not asked(said, face=bool(tasks & FACE_TASKS) or "video" in outputs):
        return False
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
