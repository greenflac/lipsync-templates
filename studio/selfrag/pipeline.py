"""The orchestration: request in, graded prompt out, everything recorded.

Order of work, and the order is the design:

    1. is this model callable at all      cheapest, and refuses before payment
    2. is the answer already cached       free, and expires on its own
    3. retrieve, widening only if needed  the only step that touches the corpus
    4. grade the retrieved set            drop it rather than condition on junk
    5. build the spec                     model fills fields, code assembles
    6. reflect: draft, grade, revise      bounded, and the critic is not the writer
    7. journal the run                    with its latency and its rule hits

Steps 1 and 2 are microseconds and come before anything expensive. That
ordering is not tidiness: the expensive step here is a paid generation call
downstream, and a model name nobody verified reaches it as a 404 that was
already billed.

The extractor and the judge are injected callables. Nothing in this module
opens a socket, which is what lets the whole pipeline be tested offline.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, replace
from typing import Callable, Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.knowledge import structure_from_text  # type: ignore[attr-defined]
from studio.selfrag.cache import PromptCache, fingerprint
from studio.selfrag.corpus import CorpusRecord, load_corpus
from studio.selfrag.monitor import Journal, RunRecord
from studio.selfrag.reflect import (
    Finding,
    grade_context,
    grade_draft,
)
from studio.selfrag.registry import availability, card_for
from studio.selfrag.replay import ReplayBuffer
from studio.selfrag.retrieval import (
    CorpusIndex,
    build_corpus_index,
    rating_prior,
    search_with_fallback,
)
from studio.selfrag.spec import (
    GenSpec,
    MODE_T2V,
    assemble,
)
from studio.style import (
    LIGHT_WORDS,
    MOOD_WORDS,
    PALETTE_WORDS,
    TEXTURE_WORDS,
    StyleSpec,
    sanitise_setting,
)

__all__ = ["DEFAULTS", "PromptEngineer", "PromptRequest", "spec_from_text"]

# Values used when the user's text commits to nothing for a field. They are
# named here rather than buried at the call site because a default that fills
# a field the user never mentioned is a claim about their intent, and the
# result must be reported as `could not measure`, never as a clean pass.
# CHOSEN: the most neutral member of each allow-list.
DEFAULTS: dict[str, object] = {
    "palette": ("slate",),
    "light": "soft",
    "texture": "matte",
    "mood": "calm",
}


@dataclass(frozen=True)
class PromptRequest:
    """What a caller asks for, before anything has been retrieved or decided."""

    text: str
    model: str
    mode: str = MODE_T2V
    subject: str = ""
    action: str = ""
    camera: str = ""
    motion: str = ""
    audio: str = ""
    constraints: tuple[str, ...] = ()
    duration_seconds: float | None = None
    aspect_ratio: str = ""
    tags: tuple[str, ...] = ()
    subject_locked: bool = False
    k: int = 5
    extra: dict = field(default_factory=dict, compare=False)


def _first(words: Sequence[str], found: set[str]) -> str:
    """Pick one allow-list word deterministically: allow-list order, not set order."""
    for word in words:
        if word in found:
            return word
    return ""


def spec_from_text(text: str, *, request: PromptRequest) -> dict:
    """Derive a StyleSpec from free text with no model call. Three outcomes.

    Every field the text did not commit to is filled from `DEFAULTS` AND named
    in `defaulted`, and the outcome drops to `could not measure` when that list
    is non-empty. This is the difference between "the user asked for a calm
    mood" and "nobody said, so we picked calm" — the two look identical in the
    finished prompt and must not look identical in the report.

    >>> req = PromptRequest(text="", model="veo")
    >>> spec_from_text("warm amber light, grainy film, nostalgic", request=req)["outcome"]
    'could not measure'
    """
    found = structure_from_text(text)
    palette = tuple(w for w in PALETTE_WORDS if w in found["palette"])[:4]
    light = _first(LIGHT_WORDS, found["light"])
    texture = _first(TEXTURE_WORDS, found["texture"])
    mood = _first(MOOD_WORDS, found["mood"])

    defaulted: list[str] = []
    if not palette:
        palette = tuple(DEFAULTS["palette"])  # type: ignore[arg-type]
        defaulted.append("palette")
    if not light:
        light = str(DEFAULTS["light"])
        defaulted.append("light")
    if not texture:
        texture = str(DEFAULTS["texture"])
        defaulted.append("texture")
    if not mood:
        mood = str(DEFAULTS["mood"])
        defaulted.append("mood")

    spec = StyleSpec(
        palette=palette,
        light=light,
        texture=texture,
        mood=mood,
        setting=sanitise_setting(text)[:60],
    )
    if defaulted:
        return {
            "outcome": UNMEASURED,
            "checked": 4,
            "violations": 0,
            "unmeasured": len(defaulted),
            "note": (
                f"the text committed to no {', '.join(defaulted)}; those fields were "
                f"filled from DEFAULTS and are this module's choice, not the user's"
            ),
            "spec": spec,
            "defaulted": defaulted,
        }
    return {
        "outcome": PASS,
        "checked": 4,
        "violations": 0,
        "unmeasured": 0,
        "note": "every style field came from the user's own words",
        "spec": spec,
        "defaulted": [],
    }


def auto_reviser(spec: GenSpec, findings: Sequence[Finding]) -> GenSpec:
    """Apply the repairs that can be made without guessing at intent.

    Only two kinds of finding are repairable here, and both are repairable
    because the vendor documented a mechanical answer:

    * a real parameter controls what a prose clause is trying to control, so
      the clause moves into the parameter;
    * a documented remedy for a documented drift is a parameter that is simply
      not set yet.

    Everything else — a prompt outside a length band, an action chain that is
    too long — needs a writer. This function does not invent one, and returning
    the spec unchanged is how it says so; `reflect` reads that as "stop".
    """
    updated = spec
    for finding in findings:
        if finding.rule != "parameter_beats_prose":
            continue
        if "camera_fixed" in finding.message and updated.camera:
            extra = dict(updated.extra)
            extra["camera_fixed"] = True
            updated = replace(updated, camera="", extra=extra)
        if "character_orientation" in finding.message:
            extra = dict(updated.extra)
            extra["character_orientation"] = "image"
            updated = replace(updated, extra=extra)
    return updated


class PromptEngineer:
    """The pipeline. Build once per process, call `write` per request."""

    def __init__(
        self,
        *,
        records: Sequence[CorpusRecord] | None = None,
        state_path: str | None = None,
        extractor: Callable[[str], dict] | None = None,
        reviser: Callable[[GenSpec, Sequence[Finding]], GenSpec] | None = auto_reviser,
        rounds: int = 3,
    ) -> None:
        """
        :param records: the corpus. `None` loads it from the configured paths;
            a load that finds no file leaves the engineer usable and honest —
            every run then reports `retrieved 0` rather than pretending.
        :param state_path: sqlite file for cache, replay and journal.
        :param extractor: free text -> `{"outcome", "spec"}`. `None` uses the
            deterministic `spec_from_text`, which needs no model and no network.
        :param reviser: applies findings to a spec between reflect rounds.
        """
        load: dict = (
            {"outcome": PASS, "records": list(records), "note": "records supplied"}
            if records is not None
            else load_corpus()
        )
        self.corpus_outcome: str = str(load["outcome"])
        self.corpus_note: str = str(load["note"])
        self.records: list[CorpusRecord] = list(load.get("records") or [])
        self.index: CorpusIndex = build_corpus_index(self.records)
        self.fingerprint: str = fingerprint(self.records)
        self.cache = PromptCache(path=state_path, fingerprint_value=self.fingerprint)
        self.replay = ReplayBuffer(path=state_path)
        self.journal = Journal(path=state_path)
        self.extractor = extractor
        self.reviser = reviser
        self.rounds = rounds

    # ------------------------------------------------------------- helpers

    def _style_spec(self, request: PromptRequest) -> dict:
        """Get a StyleSpec, from the injected extractor or from the text itself."""
        if self.extractor is None:
            return spec_from_text(request.text, request=request)
        try:
            out = self.extractor(request.text)
        except Exception as exc:  # noqa: BLE001 - an extractor failure is unmeasured
            return {
                "outcome": UNMEASURED,
                "checked": 0,
                "violations": 0,
                "unmeasured": 1,
                "note": f"the extractor raised {type(exc).__name__}: {exc}",
                "spec": None,
                "defaulted": [],
            }
        if not isinstance(out, dict) or not isinstance(out.get("spec"), StyleSpec):
            return {
                "outcome": UNMEASURED,
                "checked": 0,
                "violations": 0,
                "unmeasured": 1,
                "note": "the extractor did not return a StyleSpec: NOT READ, which is not 'no style'",
                "spec": None,
                "defaulted": [],
            }
        return {**out, "defaulted": out.get("defaulted", [])}

    # ---------------------------------------------------------------- main

    def write(self, request: PromptRequest) -> dict:
        """Turn a request into a graded prompt. Three outcomes, and a receipt.

        :returns: the judging dict plus `prompt`, `negative_prompt`,
            `parameters`, `examples`, `findings`, `history`, `stages`. `stages`
            is the receipt: every step's own outcome, so a caller can see
            WHERE a run went wrong rather than only that it did.
        """
        started = time.perf_counter()
        run_id = uuid.uuid4().hex[:12]
        stages: dict[str, dict] = {}
        # The journal records the RESOLVED model id, never the alias the caller
        # typed: a report where "veo", "veo3" and "veo-3.1" are three rows is a
        # report that cannot count how often Veo failed.
        resolved = card_for(request.model)
        model_id = resolved.model_id if resolved is not None else request.model

        # 1. cheapest check first, and before any money is spent.
        avail = availability(request.model)
        stages["availability"] = {"outcome": avail["outcome"], "note": avail["note"]}
        if avail["outcome"] == FAIL:
            return self._finish(
                run_id, request, model_id, started, stages, FAIL, avail["note"], retrieved=0
            )

        # 2. cache.
        cached = self.cache.get(request)
        stages["cache"] = {"outcome": cached["outcome"], "note": cached["note"]}
        if cached["outcome"] == PASS and cached["payload"]:
            payload = dict(cached["payload"])
            payload["stages"] = stages
            payload["cached"] = True
            self.journal.append(
                RunRecord(
                    run_id=run_id,
                    model=model_id,
                    mode=request.mode,
                    outcome=payload.get("outcome", UNMEASURED),
                    checked=int(payload.get("checked", 0)),
                    cached=True,
                    retrieved=len(payload.get("examples") or []),
                    latency_ms=round((time.perf_counter() - started) * 1000, 3),
                    note="served from cache",
                )
            )
            return payload

        # 3. retrieve, widening only when the first try comes back empty.
        found = search_with_fallback(
            request.text,
            index=self.index,
            k=request.k,
            tags=request.tags,
            # The resolved id, not the alias: corpus rows carry "veo-3.1", so
            # searching for "veo" would push every genuinely in-model example
            # into the cross-model penalty band.
            model=model_id,
            boost=self._boost(),
        )
        stages["retrieval"] = {
            "outcome": found["outcome"],
            "note": found["note"],
            "rewrite_step": found.get("rewrite_step", 0),
        }

        # 4. grade what came back; a weak set is dropped, not down-weighted.
        graded = grade_context(found["hits"], rewrite_step=found.get("rewrite_step", 0))
        stages["context"] = {"outcome": graded["outcome"], "note": graded["note"]}
        examples = [
            {
                "record_id": hit.record.record_id,
                "prompt": hit.record.prompt,
                "model": hit.record.model,
                "rating": hit.record.rating,
                "score": hit.score,
                "channels": list(hit.channels),
            }
            for hit in graded["kept"]
        ]

        # 5. the spec. The model fills fields; this code assembles the prompt.
        style = self._style_spec(request)
        stages["extract"] = {"outcome": style["outcome"], "note": style["note"]}
        if style.get("spec") is None:
            return self._finish(
                run_id,
                request,
                model_id,
                started,
                stages,
                UNMEASURED,
                f"no style spec was produced: {style['note']}",
                retrieved=len(examples),
                confidence=graded.get("confidence", 0.0),
                rewrite_step=found.get("rewrite_step", 0),
            )

        spec = GenSpec(
            model=model_id,
            mode=request.mode,
            style=style["spec"],
            subject=request.subject,
            action=request.action,
            camera=request.camera,
            motion=request.motion,
            audio=request.audio,
            constraints=request.constraints,
            duration_seconds=request.duration_seconds,
            aspect_ratio=request.aspect_ratio,
            subject_locked=request.subject_locked,
        )

        # 6. reflect: draft, grade, revise, bounded.
        current = spec
        history: list[dict] = []
        draft: dict = {}
        grade: dict = {}
        for round_no in range(1, max(1, self.rounds) + 1):
            draft = assemble(current)
            grade = grade_draft(current, draft)
            history.append(
                {
                    "round": round_no,
                    "outcome": grade["outcome"],
                    "violations": grade["violations"],
                    "unmeasured": grade["unmeasured"],
                    "note": grade["note"],
                }
            )
            if grade["outcome"] != FAIL or self.reviser is None:
                break
            revised = self.reviser(current, grade.get("findings", []))
            if not isinstance(revised, GenSpec) or revised == current:
                history[-1]["note"] += " | the reviser changed nothing: stopping"
                break
            current = revised
        stages["reflect"] = {"outcome": grade.get("outcome", UNMEASURED), "rounds": len(history)}

        findings = grade.get("findings", [])
        rules_fired = sorted({f.rule for f in findings})

        # The run's own verdict, combining what the prompt says with how much
        # of it could be measured. A draft nothing could grade is not a pass.
        outcome = grade.get("outcome", UNMEASURED)
        note_parts = [grade.get("note", "nothing was graded")]
        if style["outcome"] == UNMEASURED:
            note_parts.append(style["note"])
            if outcome == PASS:
                outcome = UNMEASURED
        if graded["outcome"] != PASS:
            note_parts.append(f"no usable precedent: {graded['note']}")
        if avail["outcome"] == UNMEASURED:
            note_parts.append(avail["note"])
            if outcome == PASS:
                outcome = UNMEASURED

        payload = {
            "outcome": outcome,
            "checked": grade.get("checked", 0),
            "violations": grade.get("violations", 0),
            "unmeasured": grade.get("unmeasured", 0) + int(style["outcome"] == UNMEASURED),
            "note": " | ".join(p for p in note_parts if p),
            "run_id": run_id,
            "prompt": draft.get("prompt"),
            "negative_prompt": draft.get("negative_prompt", ""),
            "parameters": {**draft.get("parameters", {}), **current.extra},
            "slots": draft.get("slots", {}),
            "words": draft.get("words", 0),
            "examples": examples,
            "findings": [
                {"rule": f.rule, "severity": f.severity, "message": f.message, "fix": f.fix}
                for f in findings
            ],
            "history": history,
            "stages": stages,
            "cached": False,
            "confidence": graded.get("confidence", 0.0),
            "rewrite_step": found.get("rewrite_step", 0),
        }

        # Only a prompt that survived grading is worth replaying later. A
        # failed draft is cached too — recomputing a known-bad answer is still
        # a waste — but it is cached AS a failure, outcome and all.
        self.cache.put(request, payload)
        self.journal.append(
            RunRecord(
                run_id=run_id,
                model=model_id,
                mode=request.mode,
                outcome=outcome,
                checked=payload["checked"],
                violations=payload["violations"],
                unmeasured=payload["unmeasured"],
                rounds=len(history),
                cached=False,
                retrieved=len(examples),
                rewrite_step=found.get("rewrite_step", 0),
                confidence=graded.get("confidence", 0.0),
                latency_ms=round((time.perf_counter() - started) * 1000, 3),
                rules=rules_fired,
                note=payload["note"][:400],
            )
        )
        return payload

    async def awrite(self, request: PromptRequest) -> dict:
        """Async wrapper. Everything here is CPU and sqlite, so it runs in a thread.

        This is deliberately a thread offload rather than fake `async def`
        bodies: the work is genuinely synchronous, and marking it `async`
        without moving it off the loop would block the event loop while
        claiming not to.
        """
        import asyncio

        return await asyncio.to_thread(self.write, request)

    # ------------------------------------------------------------ feedback

    def _boost(self) -> Callable[[CorpusRecord], float]:
        """Combine the corpus's own rating with the replay buffer's reports."""
        feedback = self.replay.boost()
        return lambda record: rating_prior(record) * feedback(record)

    def _finish(
        self,
        run_id: str,
        request: PromptRequest,
        model_id: str,
        started: float,
        stages: dict,
        outcome: str,
        note: str,
        *,
        retrieved: int = 0,
        confidence: float = 0.0,
        rewrite_step: int = 0,
    ) -> dict:
        """Journal and return an early exit, with the same shape as a full run."""
        self.journal.append(
            RunRecord(
                run_id=run_id,
                model=model_id,
                mode=request.mode,
                outcome=outcome,
                retrieved=retrieved,
                confidence=confidence,
                rewrite_step=rewrite_step,
                latency_ms=round((time.perf_counter() - started) * 1000, 3),
                note=note[:400],
            )
        )
        return {
            "outcome": outcome,
            "checked": 1,
            "violations": 1 if outcome == FAIL else 0,
            "unmeasured": 1 if outcome == UNMEASURED else 0,
            "note": note,
            "run_id": run_id,
            "prompt": None,
            "negative_prompt": "",
            "parameters": {},
            "slots": {},
            "words": 0,
            "examples": [],
            "findings": [],
            "history": [],
            "stages": stages,
            "cached": False,
            "confidence": confidence,
            "rewrite_step": rewrite_step,
        }

    def close(self) -> None:
        """Release every connection this engineer opened."""
        self.cache.close()
        self.replay.close()
        self.journal.close()
        self.index.close()
