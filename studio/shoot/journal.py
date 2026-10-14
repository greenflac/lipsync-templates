"""Журнал производства: всё, что сделано с роликом, — строкой, из которой потом собирается постмортем.

ЗАЧЕМ. Владелец, 2026-10-07: «документировать всё, что делаешь, чтобы потом
можно было постмортем собирать пайплайн под массовый контент». Массовый
контент — это вопрос «сколько стоит годный план и где теряются попытки», а на
него отвечают только числа по каждой попытке: сколько GPU-секунд, какой сид,
какой промпт, что сказал QA, что сказал владелец, какое правило из этого
выросло. Память агента и чат такими числами не являются.

ПОЭТОМУ ЖУРНАЛ ПИШЕТ ПАЙПЛАЙН, А НЕ ДИСЦИПЛИНА. `render` и `qa` из
`python -m studio.shoot` дописывают свои строки сами. Руками пишутся только
решения, замечания владельца и разборы инцидентов — то, чего машина не знает.

ЗАМЕЧАНИЕ ВЛАДЕЛЬЦА НЕ ОСТАЁТСЯ БЕЗ РАЗБОРА. Каждый отзыв владельца с исходом
«не годно» обязан быть назван в поле `from` хотя бы одного инцидента, а у
инцидента есть причина и либо правило в коде (`rule`: файл и символ), либо
явное `no_rule` с основанием. Это ровно то, о чём владелец сказал в тот же
день: «зафиксировать в пайплайне, а не фиксить то, что я заметил».

Журнал — лог, а не таблица: строки не правятся, исправление — новая строка.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

KINDS = ("decision", "render", "qa", "review", "incident", "cost", "note")
STAGES = (
    "brief",
    "script",
    "casting",
    "look",
    "camera",
    "audio",
    "render",
    "edit",
    "delivery",
    "infra",
)
BY = ("owner", "agent", "pipeline")
OUTCOMES = ("годно", "не годно", "не смогли")
REQUIRED = ("id", "ts", "kind", "stage", "by", "summary")
#: Исход обязателен там, где есть что оценивать.
NEEDS_OUTCOME = ("render", "qa", "review")


def problems(ev: dict[str, Any]) -> list[str]:
    """Что не так с одной строкой. Пусто — всё так."""
    rid = str(ev.get("id") or "<без id>")
    out = [f"{rid}: нет поля {f}" for f in REQUIRED if not str(ev.get(f) or "").strip()]
    for name, allowed in (("kind", KINDS), ("stage", STAGES), ("by", BY)):
        v = ev.get(name)
        if v and v not in allowed:
            out.append(f"{rid}: {name}={v!r} не из {allowed}")
    oc = ev.get("outcome")
    if oc and oc not in OUTCOMES:
        out.append(f"{rid}: outcome={oc!r} не из {OUTCOMES}")
    if ev.get("kind") in NEEDS_OUTCOME and not oc:
        out.append(f"{rid}: у {ev.get('kind')} нет исхода")
    if ev.get("kind") == "incident":
        if not str(ev.get("cause") or "").strip():
            out.append(f"{rid}: у инцидента нет причины")
        if not ev.get("rule") and not str(ev.get("no_rule") or "").strip():
            out.append(f"{rid}: у инцидента нет ни правила в коде, ни основания no_rule")
    return out


def check(rows: list[dict[str, Any]]) -> list[str]:
    """Строки по отдельности и связи между ними."""
    out: list[str] = []
    ids = Counter(str(r.get("id")) for r in rows)
    out += [f"{i}: id повторяется {n} раз" for i, n in ids.items() if n > 1]
    for r in rows:
        out += problems(r)
    explained = {str(x) for r in rows if r.get("kind") == "incident" for x in r.get("from", [])}
    for r in rows:
        if r.get("kind") == "review" and r.get("by") == "owner" and r.get("outcome") == "не годно":
            if str(r.get("id")) not in explained:
                out.append(f"{r.get('id')}: замечание владельца без разбора (нет инцидента с from)")
    for r in rows:
        for x in r.get("from", []):
            if str(x) not in ids:
                out.append(f"{r.get('id')}: from ссылается на несуществующее {x}")
    return out


def load(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    if not p.is_file():
        return []
    return [
        json.loads(line)
        for line in p.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("//")
    ]


def append(path: str | Path, ev: dict[str, Any]) -> dict[str, Any]:
    """Дописать строку; id и ts ставятся сами. Кривая строка не пишется."""
    rows = load(path)
    row = dict(ev)
    row.setdefault("ts", datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    if not row.get("id"):
        n = sum(1 for r in rows if r.get("kind") == row.get("kind")) + 1
        row["id"] = f"{row.get('kind')}-{n:03d}"
    bad = problems(row)
    if bad:
        raise ValueError("; ".join(bad))
    with Path(path).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


@dataclass
class Summary:
    """Числа постмортема.

    ДВЕ ЦЕНЫ, А НЕ ОДНА. Под оплачивается за всё время, пока он включён, а
    генерация занимает его частью. НАБЛЮДЕНО 2026-10-07: старый под 4090 —
    $5,90 за 8 ч, из них генерация H3 — 0,71 ч. Для массового контента важна
    именно эта доля: она говорит, что дешевле — быстрый GPU или меньше простоя.
    """

    renders: int = 0
    renders_ok: int = 0
    gpu_s: float = 0.0
    cost_usd: float = 0.0  # по счёту провайдера (строки cost)
    render_cost_usd: float = 0.0  # доля, ушедшая собственно на генерацию
    attempts: dict[str, int] = field(default_factory=dict)
    accepted: dict[str, int] = field(default_factory=dict)
    qa_fail_reasons: Counter[str] = field(default_factory=Counter)
    owner_remarks: int = 0
    rules: list[str] = field(default_factory=list)
    by_stage: Counter[str] = field(default_factory=Counter)


def summarize(rows: list[dict[str, Any]]) -> Summary:
    """Числа для постмортема: цена и выход годного по планам, причины брака."""
    s = Summary()
    att: dict[str, int] = defaultdict(int)
    acc: dict[str, int] = defaultdict(int)
    for r in rows:
        s.by_stage[str(r.get("stage"))] += 1
        if r.get("kind") == "cost":
            s.cost_usd += float(r.get("cost_usd") or 0)
        if r.get("kind") == "render":
            s.render_cost_usd += float(r.get("cost_usd") or 0)
        if r.get("kind") == "render":
            s.renders += 1
            s.gpu_s += float(r.get("gpu_s") or 0)
            if r.get("outcome") == "годно":
                s.renders_ok += 1
            if r.get("shot"):
                att[str(r["shot"])] += 1
        if r.get("kind") == "qa":
            for n in r.get("notes", []):
                s.qa_fail_reasons[str(n).split(":")[0][:60]] += 1
        if r.get("kind") == "review" and r.get("shot") and r.get("outcome") == "годно":
            acc[str(r["shot"])] += 1
        if r.get("kind") == "review" and r.get("by") == "owner":
            s.owner_remarks += 1
        if r.get("kind") == "incident" and r.get("rule"):
            rule = r["rule"]
            s.rules.extend(rule if isinstance(rule, list) else [rule])
    s.attempts, s.accepted = dict(att), dict(acc)
    return s


def render_summary(s: Summary) -> str:
    lines = [
        f"рендеров {s.renders}, с исходом «годно» {s.renders_ok}",
        f"генерация {s.gpu_s / 60:.1f} мин GPU, её доля ${s.render_cost_usd:.2f}; "
        f"счёт провайдера ${s.cost_usd:.2f}"
        + (f" — на генерацию ушло {s.render_cost_usd / s.cost_usd:.0%}" if s.cost_usd else ""),
        f"замечаний владельца {s.owner_remarks}, правил в коде из инцидентов {len(s.rules)}",
    ]
    for shot in sorted(s.attempts):
        lines.append(f"  {shot:20} попыток {s.attempts[shot]}, принято {s.accepted.get(shot, 0)}")
    for why, n in s.qa_fail_reasons.most_common(8):
        lines.append(f"  брак QA ×{n}: {why}")
    return "\n".join(lines)
