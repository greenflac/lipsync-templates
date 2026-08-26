"""Command line for the Self-RAG prompt engineer.

    python -m studio.selfrag write  --model veo --text "..." --subject "..." ...
    python -m studio.selfrag eval   [--k 5] [--channels bm25,phrase]
    python -m studio.selfrag report
    python -m studio.selfrag rate   --record-id ... --rating 8 --artifact out/x.mp4
    python -m studio.selfrag cards

Exit codes follow the three outcomes, because a shell script has to be able to
tell them apart: 0 pass, 1 fail, 2 could not measure. Collapsing "could not
measure" into either of the others is how a broken corpus reads as a green
build.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.corpus import load_corpus
from studio.selfrag.evaluate import DEMO_CORPUS_PATH, evaluate, load_gold
from studio.selfrag.facts import FactStore
from studio.selfrag.learn import effects, export_pairs, render as render_effects
from studio.selfrag.monitor import Journal
from studio.selfrag.pipeline import PromptEngineer, PromptRequest
from studio.selfrag.registry import MODEL_CARDS, availability
from studio.selfrag.replay import ReplayBuffer
from studio.selfrag.retrieval import build_corpus_index

EXIT = {PASS: 0, FAIL: 1, UNMEASURED: 2}


def _exit(result: dict) -> int:
    print(f"outcome: {result['outcome']}")
    print(f"note:    {result['note']}")
    return EXIT.get(result["outcome"], 2)


def cmd_write(args: argparse.Namespace) -> int:
    engineer = PromptEngineer(state_path=args.state)
    if engineer.corpus_outcome != PASS:
        print(f"corpus: {engineer.corpus_outcome} — {engineer.corpus_note}", file=sys.stderr)
    request = PromptRequest(
        text=args.text,
        model=args.model,
        mode=args.mode,
        subject=args.subject,
        action=args.action,
        camera=args.camera,
        motion=args.motion,
        audio=args.audio,
        constraints=tuple(c for c in (args.constraint or []) if c),
        duration_seconds=args.duration,
        aspect_ratio=args.aspect,
        tags=tuple(args.tag or []),
        subject_locked=args.subject_locked,
        k=args.k,
    )
    out = engineer.write(request)
    if args.json:
        print(json.dumps(out, indent=2, default=str))
    else:
        print(f"outcome:  {out['outcome']}")
        print(f"prompt:   {out['prompt']}")
        if out["negative_prompt"]:
            print(f"negative: {out['negative_prompt']}")
        if out["parameters"]:
            print(f"params:   {out['parameters']}")
        print(f"note:     {out['note']}")
        if out["examples"]:
            print("\nprecedents used:")
            for example in out["examples"]:
                print(
                    f"  [{example['score']:.5f}] {example['record_id']} "
                    f"({example['model']}, rated {example['rating']}) "
                    f"{example['prompt'][:80]}"
                )
        if out["findings"]:
            print("\nfindings:")
            for finding in out["findings"]:
                print(f"  {finding['severity']:<10} {finding['rule']}: {finding['message']}")
                if finding["fix"]:
                    print(f"             fix: {finding['fix']}")
    engineer.close()
    return EXIT.get(out["outcome"], 2)


def cmd_eval(args: argparse.Namespace) -> int:
    # The gate evaluates the COMMITTED fixture unless told otherwise, and that
    # is the whole point. It used to fall back to the configured corpus paths,
    # so the moment an operator dropped their own 4593-row corpus on disk the
    # CI gate started scoring the fixture's gold set against a corpus the gold
    # set knows nothing about, and went red (OBSERVED 2026-08-26). A gate whose
    # verdict depends on an uncommitted local file is not a gate.
    #
    # Measuring a real corpus is a separate and deliberate act: pass --corpus.
    # It needs its own gold set, because a gold set written for one corpus
    # measures nothing about another.
    source = Path(args.corpus) if args.corpus else DEMO_CORPUS_PATH
    load = load_corpus(paths=[source])
    gold = load_gold(Path(args.gold)) if args.gold else load_gold()
    index = build_corpus_index(load.get("records") or [])
    channels = tuple(args.channels.split(",")) if args.channels else None
    result = evaluate(index, gold, k=args.k, channels=channels)
    if args.json:
        print(json.dumps(result, indent=2, default=str))
        return EXIT.get(result["outcome"], 2)
    print(f"corpus:      {load['outcome']} — {load['note']}")
    print(f"channels:    {result.get('channels')}")
    print(f"recall@{args.k}:    {result.get('recall_at_k')}")
    print(f"precision@{args.k}: {result.get('precision_at_k')}")
    print(f"abstention:  {result.get('abstention_rate')} over {result.get('negatives')} controls")
    print(
        f"counts:      checked {result['checked']}, violations {result['violations']}, "
        f"could not measure {result['unmeasured']}"
    )
    index.close()
    return _exit(result)


def cmd_report(args: argparse.Namespace) -> int:
    journal = Journal(path=args.state)
    report = journal.report()
    if args.json:
        print(json.dumps(report, indent=2, default=str))
    else:
        print(journal.render(report))
    journal.close()
    return EXIT.get(report["outcome"], 2)


def cmd_rate(args: argparse.Namespace) -> int:
    buffer = ReplayBuffer(path=args.state)
    result = buffer.record(
        record_id=args.record_id,
        prompt=args.prompt,
        model=args.model,
        outcome=args.outcome,
        rating=args.rating,
        note=args.note,
        artifact=args.artifact,
    )
    buffer.close()
    return _exit(result)


def cmd_cards(args: argparse.Namespace) -> int:
    for model_id in sorted(MODEL_CARDS):
        card = MODEL_CARDS[model_id]
        state = availability(model_id)
        print(f"{model_id:<16} {state['outcome']:<18} {card.media:<6} {card.status}")
        print(f"  skeleton    {' -> '.join(card.skeleton)}")
        if card.i2v_skeleton:
            print(f"  i2v         {' -> '.join(card.i2v_skeleton)}")
        duration = (
            "n/a (still image)"
            if card.media == "image"
            else (
                f"max {card.max_seconds}s"
                if card.max_seconds is not None
                else "max duration NOT SOURCED"
            )
        )
        print(
            f"  limits      {duration}, {', '.join(card.resolutions) or 'resolution NOT SOURCED'}"
            f", audio {card.audio}, negative prompt {card.negative_prompt}"
        )
        print(f"  confidence  {card.confidence} ({len(card.sources)} source(s))")
        if state["note"]:
            print(f"  note        {state['note']}")
        print()
    return 0


def cmd_facts(args: argparse.Namespace) -> int:
    store = FactStore()
    if args.model:
        attributes = store.attributes(args.model) + store.attributes("*")
        if not attributes:
            print(f"nothing recorded about {args.model!r}. Known: {', '.join(store.models())}")
            return 2
        worst = 0
        for attribute in sorted(set(attributes)):
            for owner in (args.model, "*"):
                claim = store.claims(owner, attribute)
                if claim["outcome"] == UNMEASURED and not claim["claims"]:
                    continue
                print(f"{owner}.{attribute}  [{claim['outcome']}]")
                for row in claim["claims"]:
                    print(f"    {row['value']}")
                    for src in row["sources"]:
                        age = f", {src['age_days']}d old" if src["age_days"] is not None else ""
                        print(f"      {src['tier']:<10} {src['url']}{age}")
                worst = max(worst, EXIT.get(claim["outcome"], 2))
        return worst
    report = store.audit()
    print(f"facts:     {report['checked']}")
    print(f"contested: {report.get('contested') or 'none'}")
    return _exit(report)


def cmd_learn(args: argparse.Namespace) -> int:
    buffer = ReplayBuffer(path=args.state)
    rows = buffer.training_rows(rated_only=False)
    if args.export:
        result = export_pairs(rows, args.export)
        buffer.close()
        return _exit(result)
    report = effects(rows)
    buffer.close()
    if args.json:
        print(json.dumps(report, indent=2, default=str))
        return EXIT.get(report["outcome"], 2)
    print(render_effects(report))
    return EXIT.get(report["outcome"], 2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m studio.selfrag")
    parser.add_argument("--state", default=None, help="sqlite state file")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    subs = parser.add_subparsers(dest="command", required=True)

    write = subs.add_parser("write", help="write one prompt")
    write.add_argument("--model", required=True)
    write.add_argument("--text", required=True, help="the style, in the user's own words")
    write.add_argument("--mode", default="t2v", choices=("t2i", "t2v", "i2v", "edit"))
    write.add_argument("--subject", default="")
    write.add_argument("--action", default="")
    write.add_argument("--camera", default="")
    write.add_argument("--motion", default="")
    write.add_argument("--audio", default="")
    write.add_argument("--constraint", action="append", help="repeatable")
    write.add_argument("--tag", action="append", help="repeatable")
    write.add_argument("--duration", type=float, default=None)
    write.add_argument("--aspect", default="")
    write.add_argument("--subject-locked", action="store_true")
    write.add_argument("--k", type=int, default=5)
    write.set_defaults(func=cmd_write)

    ev = subs.add_parser("eval", help="score the retriever against the gold set")
    ev.add_argument("--k", type=int, default=5)
    ev.add_argument(
        "--corpus",
        default=None,
        help="a .jsonl to score instead of the committed fixture; needs its own gold set",
    )
    ev.add_argument(
        "--gold",
        default=None,
        help="the gold set for that corpus; a gold set written for one corpus measures "
        "nothing about another",
    )
    ev.add_argument("--channels", default=None, help="comma separated, to run a mutation")
    ev.set_defaults(func=cmd_eval)

    rep = subs.add_parser("report", help="summarise the run journal")
    rep.set_defaults(func=cmd_report)

    rate = subs.add_parser("rate", help="record how a shipped prompt actually did")
    rate.add_argument("--record-id", required=True)
    rate.add_argument("--prompt", required=True)
    rate.add_argument("--model", default="")
    rate.add_argument("--outcome", default=PASS)
    rate.add_argument("--rating", type=int, default=None)
    rate.add_argument("--note", default="")
    rate.add_argument("--artifact", default="", help="path to what was produced")
    rate.set_defaults(func=cmd_rate)

    cards = subs.add_parser("cards", help="print the model registry")
    cards.set_defaults(func=cmd_cards)

    facts = subs.add_parser(
        "facts", help="what is known about a model, who said it, and where they disagree"
    )
    facts.add_argument("--model", default=None, help="omit to audit the whole fact base")
    facts.set_defaults(func=cmd_facts)

    learn = subs.add_parser(
        "learn", help="what the agent's own rated output says about its choices"
    )
    learn.add_argument(
        "--export", default=None, help="write rated (asked -> produced) pairs to this .jsonl"
    )
    learn.set_defaults(func=cmd_learn)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(list(argv) if argv is not None else None)
    try:
        return int(args.func(args))
    except BrokenPipeError:
        # `... | head` closes the pipe early. That is the reader's choice, not
        # an error in the run, and a traceback here would look like one.
        try:
            sys.stdout.close()
        except BrokenPipeError:
            pass
        return 0


if __name__ == "__main__":  # pragma: no cover - the entry point itself
    raise SystemExit(main())
