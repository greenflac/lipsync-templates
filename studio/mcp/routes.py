"""Reach a vendor's facts without asking anybody to open a door.

THE PROBLEM THIS IS THE ANSWER TO

Every new model brings new hosts, and half of them are refused by the egress
policy. Handling that by adding whitelist entries makes a person the bottleneck
on every model anybody ever ships — a tax with no end. The owner's ruling,
2026-08-28: it should not be necessary to keep adding whitelists; that is an
engineering problem.

It is, and the measurement says it is solvable. MEASURED 2026-08-28, six of
seven vendors whose own documentation host is refused have an OPEN route to the
same statements:

    docs.mistral.ai      refused  ->  huggingface.co/mistralai/...      200
    api.deepseek.com     refused  ->  huggingface.co/deepseek-ai/...    200
    docs.x.ai            refused  ->  huggingface.co/xai-org/...        200
    comfy.org            refused  ->  api.comfy.org/nodes               200
    replicate.com        refused  ->  huggingface.co/api/models         200
    deepmind.google      refused  ->  cloud.google.com/vertex-ai/...    200
    docs.cohere.com      refused  ->  (none found; HF org is gated, 401)

So the door is usually not the only way in. A harvester that tries the open
routes first needs a new whitelist entry only for the vendor that genuinely has
no open route — and that is a computed, small set instead of whatever a crawler
happened to bump into.

THE BUG THIS MODULE EXISTS TO NOT REPEAT

The first attempt derived "is this host open" from `denied_hosts.jsonl` by
treating absence as closed. It reported five families as fully blocked,
including routes through `huggingface.co` — off which DeepSeek had been read
successfully minutes earlier. MEASURED: `huggingface.co`,
`raw.githubusercontent.com`, `github.com`, `cloud.google.com` and
`api.comfy.org` have NO ROW IN THAT LOG AT ALL. It is a DENIAL log: it records
refusals and hosts somebody explicitly noted as open. A host that always worked
and was never remarked on is invisible in it.

Absence of a refusal is not a refusal. `reachability` therefore has three
answers and `unknown` means TRY IT, not give up — the same three-outcome rule
the rest of this package runs on, applied to the network.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio.mcp.fetch import DENIED_PATH, _host
from studio.selfrag import source_hosts

__all__ = [
    "OPEN_HUBS",
    "REACH_OPEN",
    "REACH_REFUSED",
    "REACH_UNKNOWN",
    "ГОРИЗОНТ_ДНЕЙ",
    "просрочен",
    "reachability",
    "routes_for",
    "blocked_families",
]

REACH_OPEN = "open"
REACH_REFUSED = "refused"
REACH_UNKNOWN = "unknown"

#: The hosts that carry most of this base and answer without anybody being
#: asked. Written down rather than inferred, because inferring "open" from the
#: absence of a refusal is the bug in the docstring above — these five have no
#: row in the denial log at all.
#:
#: Each was fetched successfully on the date given. This is a MEASUREMENT with
#: a date, not a permanent property: a hub can go dark.
#:
#: NOTHING RE-PROBES THEM, and saying so is the point. An earlier version of
#: this comment promised that `--check` in `scripts/open_routes.py` would turn
#: the build red when a hub went dark. That script has never existed — review
#: 2026-08-31 went looking for it. A promised gate is worse than no gate: it
#: reads as a guarantee and buys nothing.
#:
#: It is not written now, deliberately. Such a step would have to reach the
#: network on every build, so it would go red on somebody else's outage and
#: teach everyone to ignore it — and the house rule is that a test does not
#: touch the network (T4). The honest guarantee is the DATE on each row: after
#: it, this table is a claim about the past. A harvest that suddenly returns
#: nothing is the real signal, and `reachable_hosts` re-probes on demand when
#: somebody asks.
OPEN_HUBS: dict[str, str] = {
    "huggingface.co": "model cards, the models API, and every lab's own org — MEASURED 2026-08-28",
    "raw.githubusercontent.com": "any public repo's README, LICENSE and docs — MEASURED 2026-08-27",
    "api.comfy.org": "the ComfyUI node registry, 5345 nodes paged — MEASURED 2026-08-27",
    "cloud.google.com": "Vertex AI docs: Veo, Imagen, Gemini — MEASURED 2026-08-28",
    "platform.openai.com": "OpenAI model and API reference — MEASURED 2026-08-27",
    "ai.google.dev": "Gemini API reference — MEASURED 2026-08-27",
    "export.arxiv.org": "the arXiv API — MEASURED 2026-08-27",
    "arxiv.org": "paper abstracts and HTML — MEASURED 2026-08-27",
    "civitai.com": "the community corpus API — MEASURED 2026-08-27",
    "fal.ai": "a portal's model pages, with prices — MEASURED 2026-08-27",
    "wavespeed.ai": "a second portal, same shape — MEASURED 2026-08-27",
    "docs.byteplus.com": "ByteDance's own docs (bytedance.com itself is refused)",
    "docs.bfl.ai": "Black Forest Labs (bfl.ml is refused)",
    "elevenlabs.io": "ElevenLabs docs — MEASURED 2026-08-27",
    "api.klingai.com": "Kling's API, which answers a probe — MEASURED 2026-08-27",
}


#: Через столько дней записанный отказ перестаёт считаться отказом и
#: становится `unknown`, то есть «попробуй».
#:
#: ЗАЧЕМ ГОРИЗОНТ ВООБЩЕ. Отказ записывается один раз и живёт вечно, потому что
#: код после отказа обходит хост стороной и больше никогда его не спрашивает.
#: Политика доступа при этом меняется без нашего ведома: владелец открывает
#: хосты пачками по заявке.
#:
#: ИЗМЕРЕНО 2026-09-02, прощупаны все 214 хостов, чей последний записанный
#: статус — `refused`: 18 из них отвечают сегодня (8.4%), 1 не удалось
#: измерить, 195 закрыты по-прежнему. Среди открывшихся — docs.mistral.ai,
#: docs.cohere.com, api-docs.deepseek.com, docs.bfl.ml, docs.anthropic.com,
#: tongyi.aliyun.com, developer.ideogram.ai, platform.kimi.ai: это ПЕРВОРУЧНЫЕ
#: вендорские источники, ровно те, ради которых в этом модуле написан обход.
#: Первые три названы в шапке модуля как «refused» и обходятся через HF —
#: то есть обход работал по карте, устаревшей на пять дней.
#:
#: ВЫБРАНО 3 дня, и число выведено из этого же измерения: ошибка в 8% набралась
#: за ШЕСТЬ дней, значит горизонт обязан быть короче интервала, на котором
#: ошибка измерена, иначе он узаконивает уже наблюдавшуюся ложь. Цена ошибки в
#: другую сторону мала: просроченный отказ читается как `unknown`, а `unknown`
#: здесь значит «попробуй» — то есть один лишний запрос на хост раз в три дня,
#: и `scripts/reprobe_hosts.py` проставляет свежую дату разом.
ГОРИЗОНТ_ДНЕЙ = 3

#: Дата, с которой строка считается свежей, когда даты в ней нет вовсе.
#: Строки до 2026-08-27 писались без `first_seen`; отсутствие даты — это не
#: свежесть, поэтому такая строка считается ПРОСРОЧЕННОЙ, а не вечной.
БЕЗ_ДАТЫ = ""


def _denial_states(path: Path | None = None) -> dict[str, tuple[str, str]]:
    """host -> (его ПОСЛЕДНИЙ статус, дата этой строки). Чужих хостов нет."""
    states: dict[str, tuple[str, str]] = {}
    target = path or DENIED_PATH
    if not target.is_file():
        return states
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        host, state = str(row.get("host") or ""), str(row.get("state") or "")
        when = str(row.get("first_seen") or row.get("date") or БЕЗ_ДАТЫ)
        if host and state:
            states[host] = (state, when)
    return states


def просрочен(когда: str, *, today: str = "") -> bool:
    """Строка старше горизонта? Нечитаемая дата — просрочена, а не вечна."""
    сегодня = today or date.today().isoformat()
    try:
        было = date.fromisoformat(когда)
        сейчас = date.fromisoformat(сегодня)
    except ValueError:
        return True
    return (сейчас - было).days > ГОРИЗОНТ_ДНЕЙ


def reachability(host: str, *, path: Path | None = None, today: str = "") -> str:
    """`open`, `refused`, or `unknown` — and `unknown` means try it.

    Order matters: a RECORDED refusal wins over this module's hub table, so a
    hub that later goes dark reads as refused the moment the log says so,
    without anybody editing `OPEN_HUBS`.
    """
    name = str(host or "").strip().lower()
    if not name:
        return REACH_UNKNOWN
    recorded, когда = _denial_states(path).get(name, ("", БЕЗ_ДАТЫ))
    if recorded == "refused":
        # Просроченный отказ — это НЕ «открыт»: никто не проверял. Это
        # `unknown`, а `unknown` в этом модуле значит «попробуй».
        return REACH_UNKNOWN if просрочен(когда, today=today) else REACH_REFUSED
    if recorded == "open" or name in OPEN_HUBS:
        return REACH_OPEN
    return REACH_UNKNOWN


def routes_for(model: str, *, path: Path | None = None) -> dict:
    """Where this model's own vendor can be read, best reachable route first.

    Reads `source_hosts.VENDOR_SOURCES`, which already maps a model family to
    the pages its vendor controls — including path-prefixed entries like
    `huggingface.co/deepseek-ai/`, which is precisely an open route to a shut
    vendor. Nothing new has to be maintained here: declaring a vendor's HF org
    for the tier ladder declares its bypass at the same time.

    Three outcomes. `pass` when at least one route is reachable; `fail` when
    every declared route is refused, which is the only case where a whitelist
    entry is genuinely needed; `could not measure` when the family is not
    declared at all — a gap in the table, not a network problem.
    """
    entries = source_hosts.vendor_sources_for(model)
    if not entries:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "model": model,
            "routes": [],
            "note": (
                f"no vendor is declared for {model!r} in source_hosts.VENDOR_SOURCES, so "
                "there is nothing to route to. Declare the family first; that is a table "
                "edit, not an access request."
            ),
        }

    rank = {REACH_OPEN: 0, REACH_UNKNOWN: 1, REACH_REFUSED: 2}
    routes = [
        {
            "entry": entry,
            "host": _host("https://" + entry),
            "reach": reachability(_host("https://" + entry), path=path),
        }
        for entry in entries
    ]
    routes.sort(key=lambda r: (rank.get(r["reach"], 3), r["entry"]))
    usable = [r for r in routes if r["reach"] != REACH_REFUSED]

    if not usable:
        return {
            "outcome": FAIL,
            "checked": len(routes),
            "violations": len(routes),
            "unmeasured": 0,
            "model": model,
            "routes": routes,
            "note": (
                f"every declared route for {model!r} is refused by the policy: "
                + ", ".join(r["host"] for r in routes)
                + ". THIS is a real whitelist request — and the only kind worth making."
            ),
        }
    return {
        "outcome": PASS,
        "checked": len(routes),
        "violations": 0,
        "unmeasured": sum(1 for r in usable if r["reach"] == REACH_UNKNOWN),
        "model": model,
        "routes": routes,
        "note": (
            f"{len(usable)} of {len(routes)} route(s) to {model!r}'s vendor are reachable; "
            f"try {usable[0]['entry']} first"
        ),
    }


def blocked_families(*, path: Path | None = None) -> dict:
    """The families with no reachable vendor route. The honest access request.

    Everything else in the denial log is a door somebody knocked on when
    another one was already open.
    """
    blocked: list[dict] = []
    for family in source_hosts.VENDOR_SOURCES:
        out = routes_for(family, path=path)
        if out["outcome"] == FAIL:
            blocked.append({"family": family, "hosts": [r["host"] for r in out["routes"]]})
    total = len(source_hosts.VENDOR_SOURCES)
    if not blocked:
        return {
            "outcome": PASS,
            "checked": total,
            "violations": 0,
            "unmeasured": 0,
            "blocked": [],
            "note": f"all {total} declared families have at least one reachable route",
        }
    return {
        "outcome": FAIL,
        "checked": total,
        "violations": len(blocked),
        "unmeasured": 0,
        "blocked": blocked,
        "note": (
            f"{len(blocked)} of {total} families have every declared route refused: "
            + ", ".join(b["family"] for b in blocked)
        ),
    }
