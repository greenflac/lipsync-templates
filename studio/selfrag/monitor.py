"""A journal of every run, and a report that refuses to flatter itself.

The report's job is to be readable by somebody deciding whether to trust the
agent this week. Two rules shape it:

* Every rate is printed with the denominator it came from. "92% pass" over 13
  runs is not the same claim as over 1300, and a percentage alone hides which
  one you are looking at.
* Runs that could not be measured are their own column, never merged into
  either passes or failures. A week where the corpus was missing looks, in a
  two-column report, exactly like a week where everything was refused — and
  those need opposite responses.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.db import connect, lock_for, state_path

__all__ = ["RunRecord", "Journal"]


@dataclass(frozen=True)
class RunRecord:
    """One end-to-end pipeline run, as it is stored."""

    run_id: str
    model: str
    mode: str
    outcome: str
    checked: int = 0
    violations: int = 0
    unmeasured: int = 0
    rounds: int = 0
    cached: bool = False
    retrieved: int = 0
    rewrite_step: int = 0
    confidence: float = 0.0
    latency_ms: float = 0.0
    rules: Sequence[str] = ()
    note: str = ""


class Journal:
    """Append-only storage for run records, plus the report over them."""

    def __init__(self, *, path: str | None = None) -> None:
        self.path = path or str(state_path())
        self._conn: sqlite3.Connection = connect(self.path)
        self._lock = lock_for(state_path() if path is None else Path(path))

    def append(self, run: RunRecord) -> None:
        """Store one run. Never updates: the journal is the evidence."""
        with self._lock, self._conn:
            self._conn.execute(
                "INSERT INTO runs(run_id, model, mode, outcome, checked, violations,"
                " unmeasured, rounds, cached, retrieved, rewrite_step, confidence,"
                " latency_ms, rules, note, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    run.run_id,
                    run.model,
                    run.mode,
                    run.outcome,
                    run.checked,
                    run.violations,
                    run.unmeasured,
                    run.rounds,
                    int(run.cached),
                    run.retrieved,
                    run.rewrite_step,
                    run.confidence,
                    run.latency_ms,
                    json.dumps(list(run.rules)),
                    run.note,
                    datetime.now(timezone.utc).isoformat(timespec="seconds"),
                ),
            )

    def report(self, *, limit: int = 1000) -> dict:
        """Summarise the last `limit` runs. Three outcomes.

        `could not measure` is the honest verdict when the journal is empty:
        a system nobody has run is not a healthy system, and reporting 100%
        pass over zero runs is the exact mistake the house rule names.
        """
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM runs ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        total = len(rows)
        if total == 0:
            return {
                "outcome": UNMEASURED,
                "checked": 0,
                "violations": 0,
                "unmeasured": 1,
                "note": "the journal is empty: nothing has run, which is not the same as healthy",
                "runs": 0,
            }

        passes = sum(1 for r in rows if r["outcome"] == PASS)
        fails = sum(1 for r in rows if r["outcome"] == FAIL)
        unknown = sum(1 for r in rows if r["outcome"] == UNMEASURED)
        cached = sum(1 for r in rows if r["cached"])
        abstained = sum(1 for r in rows if r["retrieved"] == 0)
        widened = sum(1 for r in rows if r["rewrite_step"] > 0)
        rounds = [int(r["rounds"]) for r in rows if r["rounds"]]
        latencies = sorted(float(r["latency_ms"]) for r in rows)
        confidences = [float(r["confidence"]) for r in rows if r["retrieved"]]

        rule_counts: dict[str, int] = {}
        for row in rows:
            for name in json.loads(row["rules"] or "[]"):
                rule_counts[name] = rule_counts.get(name, 0) + 1

        by_model: dict[str, dict[str, int]] = {}
        for row in rows:
            bucket = by_model.setdefault(row["model"], {PASS: 0, FAIL: 0, UNMEASURED: 0})
            bucket[row["outcome"]] = bucket.get(row["outcome"], 0) + 1

        def percentile(values: Sequence[float], fraction: float) -> float:
            if not values:
                return 0.0
            position = min(len(values) - 1, int(round(fraction * (len(values) - 1))))
            return round(values[position], 2)

        # The report's own verdict. A run population that is mostly unmeasured
        # is not a passing population however few outright failures it has.
        if unknown > passes:
            outcome, note = (
                UNMEASURED,
                f"{unknown} of {total} runs could not be measured, more than the {passes} "
                "that passed: the instrument is the problem, not the prompts",
            )
        elif fails > passes:
            outcome, note = (
                FAIL,
                f"{fails} of {total} runs failed, more than the {passes} that passed",
            )
        else:
            outcome, note = PASS, f"{passes} of {total} runs passed"

        return {
            "outcome": outcome,
            "checked": total,
            "violations": fails,
            "unmeasured": unknown,
            "note": note,
            "runs": total,
            "passed": passes,
            "failed": fails,
            "could_not_measure": unknown,
            "cache_hits": cached,
            "cache_hit_rate": round(cached / total, 4),
            "abstained": abstained,
            "abstention_rate": round(abstained / total, 4),
            "query_widened": widened,
            "mean_rounds": round(sum(rounds) / len(rounds), 3) if rounds else 0.0,
            "latency_ms_p50": percentile(latencies, 0.50),
            "latency_ms_p95": percentile(latencies, 0.95),
            "mean_confidence": round(sum(confidences) / len(confidences), 4)
            if confidences
            else 0.0,
            "rule_hits": dict(sorted(rule_counts.items(), key=lambda kv: (-kv[1], kv[0]))),
            "by_model": by_model,
        }

    def render(self, report: dict | None = None) -> str:
        """The report as text a person reads in a terminal."""
        data = report if report is not None else self.report()
        if data["runs"] == 0:
            return f"outcome: {data['outcome']}\n{data['note']}\n"
        lines = [
            f"outcome: {data['outcome']} — {data['note']}",
            "",
            f"runs                {data['runs']}",
            f"  passed            {data['passed']}",
            f"  failed            {data['failed']}",
            f"  not measurable    {data['could_not_measure']}",
            "",
            f"cache hits          {data['cache_hits']}/{data['runs']} "
            f"({data['cache_hit_rate']:.1%})",
            f"abstained           {data['abstained']}/{data['runs']} "
            f"({data['abstention_rate']:.1%})   <- no usable precedent found",
            f"query widened       {data['query_widened']}/{data['runs']}",
            f"mean reflect rounds {data['mean_rounds']}",
            f"mean confidence     {data['mean_confidence']}",
            f"latency ms p50/p95  {data['latency_ms_p50']} / {data['latency_ms_p95']}",
        ]
        if data["rule_hits"]:
            lines += ["", "rules fired (most often first):"]
            lines += [f"  {name:<24} {count}" for name, count in data["rule_hits"].items()]
        if data["by_model"]:
            lines += ["", "by model:"]
            for model, bucket in sorted(data["by_model"].items()):
                lines.append(
                    f"  {model:<18} pass {bucket.get(PASS, 0):<4}"
                    f" fail {bucket.get(FAIL, 0):<4}"
                    f" not-measurable {bucket.get(UNMEASURED, 0)}"
                )
        return "\n".join(lines) + "\n"

    def close(self) -> None:
        """Close the connection. Idempotent."""
        with self._lock:
            self._conn.close()
