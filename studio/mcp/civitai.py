"""Collect prompt-and-result pairs from Civitai, from the endpoint that has them.

WHY THIS EXISTS, AND WHY IT NEARLY DID NOT

This project has never had prompts paired with the results they produced: the
corpus holds prompts we ran and prompts a gallery published, and in both cases
the image and the wording live apart. Civitai has both, uploaded by the person
who ran the generation.

Two earlier sessions planned this collector around `/api/v1/images`, on the
belief that it returns prompts with results. MEASURED 2026-08-27, it does not:
300 images sampled across three pages returned `meta: null` 300 times, and so
did `?postId=`, `?sort=Newest` and `?sort=Most Reactions`. That endpoint has
been stripped.

The pairs are on a different endpoint, and the difference is not documented
anywhere this environment can reach — it was found by walking the API:

    /api/v1/models          paginated; each model carries its versions and,
                            per image, `hasMeta` and `hasPositivePrompt`
                            FLAGS -- but `meta` itself is null. MEASURED:
                            0 of 1754 nested images carried it.

    /api/v1/model-versions/{id}
                            the same images WITH `meta` populated. MEASURED:
                            60 of 63 carried a prompt, and the keys are stable
                            (prompt, negativePrompt, seed, steps, sampler,
                            cfgScale, Size, Model).

So the walk is: list models, take their version ids, and fetch each version.
The listing is what makes that affordable rather than blind — `hasPositivePrompt`
says in advance which versions are worth a request.

RIGHTS

Every row carries `provenance` and `rights`, like every other collected row in
this knowledge base, so the material stays identifiable wherever the file
travels and an exact removal stays possible if asked for. The basis is the
owner's, recorded in `studio/knowledge/PROVENANCE.md`; this module stamps it
and does not decide it.

The output file is NOT committed. `.gitignore` carries it for the same reason
it carries `gallery_prompts.jsonl`: this repository is public and its LICENCE
clause 2(d) asserts rights over "the prompts ... contained here", which would
be a claim over other people's work. Publishing it is a decision somebody takes
explicitly, not something `git add -A` can do by accident.

WHAT THIS MODULE DOES NOT DO

It does not judge a prompt, score it, or feed it to the retriever. It writes
rows. Whether they are good enough to vote on is `knowledge.py`'s question and
that module has an owner.
"""

from __future__ import annotations

import json
import time
import urllib.parse
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio.mcp import fetch

__all__ = [
    "DEFAULT_OUTPUT_PATH",
    "MAX_NSFW_LEVEL",
    "MIN_PROMPT_WORDS",
    "PARAMETER_KEYS",
    "PROVENANCE_PREFIX",
    "REQUIRED_ROW_FIELDS",
    "collect",
    "pairs_from_version",
    "version_refs",
]

DEFAULT_OUTPUT_PATH = Path(__file__).resolve().parents[1] / "knowledge" / "civitai_prompts.jsonl"

MODELS_URL = "https://civitai.com/api/v1/models"
VERSION_URL = "https://civitai.com/api/v1/model-versions/{id}"

#: CHOSEN, and stamped per row rather than per file. One Civitai uploader is
#: one author, so the provenance is the uploader and not the platform: the
#: retriever's `MAX_PER_PROVENANCE` exists so a single SOURCE cannot fill an
#: answer, and tagging ten thousand rows by ten thousand people as one source
#: would cap this whole corpus at two records — which is exactly the defect
#: already recorded against the gallery rows. The platform is still recoverable
#: from the prefix, so a removal request naming Civitai matches every row.
PROVENANCE_PREFIX = "civitai:"

#: A row without wording is not a row. Below this it is a parse failure or a
#: tag-soup fragment, not a short prompt.
MIN_PROMPT_WORDS = 3

#: CHOSEN. Civitai's browsing levels rise 1 (PG), 2 (PG-13), 4 (R), 8 (X),
#: 16 (XXX). This is a commercial creator service, so the two safe rungs are
#: kept and everything above is dropped — and the number dropped is REPORTED,
#: never silently discarded, because "we collected 4000 rows" reads very
#: differently from "we collected 4000 and threw 9000 away".
MAX_NSFW_LEVEL = 2

#: The image levels this collector will keep, as the bitmask Civitai uses for
#: a MODEL. On a model, `nsfwLevel` is not a rating but a bitmask of every rung
#: its published images span: 3 is 1|2, 31 is 1|2|4|8|16. So a model at 31
#: publishes XXX material even though individual images of it may be rated PG.
#:
#: This exists because the image gate cannot see the checkpoint. MEASURED by
#: looking at a collected row rather than at its metrics (house rule P3): a row
#: passed the image ceiling at level 2 while its model was named "NSFW MASTER"
#: and carried nsfwLevel 31. The model's own `nsfw` BOOLEAN said False for it,
#: so the boolean is not the signal — the bitmask is.
ALLOWED_MODEL_LEVELS = 3

#: The generation parameters worth keeping, MEASURED over a real sample: each
#: was present on 60 of the 60 images that had a prompt, except clipSkip (38).
#: Anything else on `meta` is tool-specific (ADetailer, Hires) and belongs to
#: the uploader's workflow rather than to the prompt.
PARAMETER_KEYS: tuple[str, ...] = (
    "seed",
    "steps",
    "sampler",
    "cfgScale",
    "Size",
    "Model",
    "clipSkip",
)

#: No row leaves this module without these. A file that travels without its
#: origin is a file whose origin gets forgotten.
REQUIRED_ROW_FIELDS: tuple[str, ...] = (
    "prompt",
    "image_url",
    "source_url",
    "harvested",
    "provenance",
    "rights",
)

#: Politeness, not a limit Civitai publishes. Civitai's terms bind automated
#: access to "any applicable rate limits" without naming one, so this is a
#: CHOSEN floor on the interval between requests rather than a measured
#: ceiling. It is a parameter so a caller with a published limit can raise it,
#: and it is never zero by default: a collector that hammers an API it has
#: permission to use loses the permission.
DEFAULT_DELAY_SECONDS = 1.0


def _words(text: str) -> int:
    return len(str(text or "").split())


def version_refs(models_payload: Any) -> list[dict]:
    """Which model versions are worth fetching, and what the listing knows.

    Pure: give it the parsed body of `/api/v1/models` and it returns one row
    per version, carrying the fields the version endpoint does NOT repeat.
    `creator` is the important one — it is on the model and absent from the
    version, and it is what the provenance is built from.

    `images_claiming_prompt` comes from the listing's `hasPositivePrompt`
    flags. It is the listing's claim, not a reading: a version claiming none is
    skipped without a request, and a version claiming some may still return
    none.
    """
    refs: list[dict] = []
    if not isinstance(models_payload, dict):
        return refs
    for model in models_payload.get("items") or []:
        if not isinstance(model, dict):
            continue
        creator = (
            (model.get("creator") or {}) if isinstance(model.get("creator"), dict) else {}
        ).get("username")
        for version in model.get("modelVersions") or []:
            if not isinstance(version, dict) or version.get("id") is None:
                continue
            images = [im for im in (version.get("images") or []) if isinstance(im, dict)]
            refs.append(
                {
                    "version_id": version.get("id"),
                    "model_name": str(model.get("name") or ""),
                    "creator": str(creator or ""),
                    "base_model": str(version.get("baseModel") or ""),
                    "model_nsfw_level": model.get("nsfwLevel"),
                    "images_claiming_prompt": sum(
                        1 for im in images if im.get("hasPositivePrompt")
                    ),
                }
            )
    return refs


def _next_page(models_payload: Any) -> str:
    if not isinstance(models_payload, dict):
        return ""
    meta = models_payload.get("metadata")
    return str((meta or {}).get("nextPage") or "") if isinstance(meta, dict) else ""


def pairs_from_version(version_payload: Any, ref: dict, harvested: str, rights: str) -> dict:
    """The prompt-and-result pairs on one model version. Three outcomes.

    Pure, so it is tested without the network. Returns the house judging dict
    plus `rows`, and the counts say what happened to everything that did not
    become a row:

    * `no_prompt` — the image carried no wording, or too little to be one
    * `too_explicit` — above `MAX_NSFW_LEVEL`

    An answered version with zero usable images is `could not measure`, never
    `pass`. That distinction is the whole reason this returns a dict: the
    endpoint answering and the endpoint being useful are different facts, and
    the day Civitai strips `meta` from this endpoint too, a collector that
    reported `pass` on an empty harvest would hide it.
    """
    images = []
    if isinstance(version_payload, dict):
        images = [im for im in (version_payload.get("images") or []) if isinstance(im, dict)]

    rows: list[dict] = []
    no_prompt = 0
    too_explicit = 0
    for image in images:
        meta = image.get("meta")
        meta = meta if isinstance(meta, dict) else {}
        prompt = str(meta.get("prompt") or "").strip()
        if _words(prompt) < MIN_PROMPT_WORDS:
            no_prompt += 1
            continue
        level = image.get("nsfwLevel")
        if not isinstance(level, int) or level > MAX_NSFW_LEVEL:
            too_explicit += 1
            continue
        url = str(image.get("url") or "").strip()
        if not url:
            no_prompt += 1
            continue
        rows.append(
            {
                "prompt": prompt,
                "negative_prompt": str(meta.get("negativePrompt") or "").strip(),
                "image_url": url,
                "width": image.get("width"),
                "height": image.get("height"),
                "nsfw_level": level,
                "parameters": {k: meta[k] for k in PARAMETER_KEYS if k in meta},
                "model_name": str(ref.get("model_name") or ""),
                "base_model": str(ref.get("base_model") or ""),
                "version_id": ref.get("version_id"),
                "source_url": VERSION_URL.format(id=ref.get("version_id")),
                "harvested": harvested,
                "provenance": PROVENANCE_PREFIX + str(ref.get("creator") or "unknown"),
                "rights": rights,
            }
        )

    checked = len(images)
    if not checked:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": f"version {ref.get('version_id')} answered with no images at all",
            "rows": [],
            "no_prompt": 0,
            "too_explicit": 0,
        }
    if not rows:
        return {
            "outcome": UNMEASURED,
            "checked": checked,
            "violations": 0,
            "unmeasured": checked,
            "note": (
                f"version {ref.get('version_id')}: {checked} image(s) and none usable — "
                f"{no_prompt} without wording, {too_explicit} above the nsfw ceiling"
            ),
            "rows": [],
            "no_prompt": no_prompt,
            "too_explicit": too_explicit,
        }
    return {
        "outcome": PASS,
        "checked": checked,
        "violations": 0,
        "unmeasured": no_prompt + too_explicit,
        "note": (
            f"version {ref.get('version_id')}: {len(rows)} pair(s) of {checked} image(s); "
            f"{no_prompt} without wording, {too_explicit} above the nsfw ceiling"
        ),
        "rows": rows,
        "no_prompt": no_prompt,
        "too_explicit": too_explicit,
    }


def _publishes_above_ceiling(ref: dict) -> bool:
    """Does this model publish anything above `MAX_NSFW_LEVEL`?

    Reads the model's `nsfwLevel` BITMASK, not its `nsfw` boolean: MEASURED,
    the boolean was False on a model named "NSFW MASTER" whose bitmask was 31.
    An absent or non-integer level is treated as above the ceiling — an unrated
    checkpoint is unrated, not safe.
    """
    level = ref.get("model_nsfw_level")
    if not isinstance(level, int):
        return True
    return bool(level & ~ALLOWED_MODEL_LEVELS)


def _one_model_at_a_time(refs: Sequence[dict]) -> list[dict]:
    """Reorder versions so a capped run touches many models, not one.

    The listing arrives grouped: every version of model A, then every version
    of model B. Fetching in that order with any ceiling collects one author —
    OBSERVED on the first real run, where `max_versions=6` produced 29 pairs
    from a single uploader, because the most-downloaded model alone has more
    than six versions. `summarise` said so, which is what it is for.

    A corpus of one author is not a corpus of the community, and the retriever
    admits only two records per provenance anyway, so 27 of those 29 rows could
    never have reached a vote.

    So: round-robin by model. Order within a model is preserved, and a run with
    no ceiling collects exactly the same set — only the ORDER changes, which is
    what makes this safe to apply always rather than only when capped.
    """
    by_model: dict[str, list[dict]] = {}
    for ref in refs:
        by_model.setdefault(f"{ref.get('creator')}/{ref.get('model_name')}", []).append(ref)
    ordered: list[dict] = []
    queues = list(by_model.values())
    while queues:
        queues = [queue for queue in queues if queue]
        for queue in queues:
            ordered.append(queue.pop(0))
        queues = [queue for queue in queues if queue]
    return ordered


def _incomplete(row: dict) -> list[str]:
    """Which mandatory origin fields this row is missing. Empty means none."""
    return [name for name in REQUIRED_ROW_FIELDS if not str(row.get(name) or "").strip()]


def _existing_urls(path: Path) -> set[str]:
    """Image URLs already collected, so a re-run adds rather than duplicates."""
    if not path.is_file():
        return set()
    seen: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        url = str(row.get("image_url") or "")
        if url:
            seen.add(url)
    return seen


def collect(
    *,
    harvested: str,
    rights: str,
    pages: int = 1,
    per_page: int = 20,
    sort: str = "Most Downloaded",
    base_model: str = "",
    safe_models_only: bool = False,
    max_versions: int | None = None,
    path: Path | None = None,
    delay_seconds: float = DEFAULT_DELAY_SECONDS,
    fetcher: Callable[..., dict] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
) -> dict:
    """Walk the API and append what it gives. Three outcomes, counts beside them.

    :param harvested: the ISO date to stamp. Passed in rather than read from
        the clock so a run is reproducible and a test is not date-dependent.
    :param rights: the basis this collection stands on, stamped per row. Passed
        in because it is the owner's to state and this module's to record.
    :param base_model: one Civitai base-model family, e.g. "Flux.1 D",
        "Flux.1 S", "Wan Video 14B t2v", "Qwen". Empty collects whatever the
        sort surfaces, which MEASURED is the Stable Diffusion checkpoint
        ecosystem: a 750-pair harvest by Most Downloaded produced 368 SD 1.5,
        127 SDXL and **zero** rows on any family this project targets. Civitai
        hosts weights, so the closed API models this project uses are barely
        there; the open-weight ones — Flux, Wan, Qwen — are, and only a filter
        reaches them.

        MEASURED and worth knowing: the filter is CASE-SENSITIVE and a name it
        does not recognise returns `200` with an empty list rather than an
        error, so "Flux.1 D" works and "flux.1 d" silently collects nothing.
        That is why an empty harvest under a filter says so in its note.

        One family per run: repeated `baseModels` parameters are ignored by the
        API and only the first is honoured (MEASURED). Loop in the caller.
    :param safe_models_only: skip models whose own `nsfwLevel` bitmask reaches
        above `MAX_NSFW_LEVEL`, not just images that do. Default False, and the
        count is REPORTED either way — the knob has a counter beside it and the
        counter is not optional (house rule P1). The image gate already keeps
        every collected image at PG or PG-13; this is about whose checkpoint
        the wording came from, which is a judgement about the product rather
        than about the data, and therefore the owner's to make with the number
        in front of them.
    :param max_versions: a hard ceiling on requests, so a mistyped page count
        cannot turn into a thousand calls against somebody else's API.
    :param fetcher: injected so the tests never reach the network (house rule
        T4 — a test that needs the web goes red when somebody else's site does).

    A version claiming no prompts in the listing is SKIPPED without a request.
    That is the only reason walking two endpoints is affordable, and the number
    skipped is reported so the saving is visible rather than assumed.
    """
    get = fetcher or fetch.fetch
    target = path or DEFAULT_OUTPUT_PATH
    already = _existing_urls(target)

    url = f"{MODELS_URL}?limit={int(per_page)}&sort={urllib.parse.quote(sort)}"
    if base_model:
        url += "&baseModels=" + urllib.parse.quote(base_model)
    refs: list[dict] = []
    listings = 0
    for _ in range(max(0, int(pages))):
        if not url:
            break
        answer = get(
            url, why_wanted="collect prompt-and-result pairs from Civitai", max_bytes=3_000_000
        )
        if answer.get("outcome") != PASS:
            if not refs:
                return {
                    "outcome": FAIL,
                    "checked": listings,
                    "violations": 1,
                    "unmeasured": 0,
                    "note": f"the model listing did not answer: {answer.get('note')}",
                    "written": 0,
                    "rows": [],
                }
            break
        try:
            payload = json.loads(answer.get("text") or "")
        except ValueError:
            return {
                "outcome": FAIL,
                "checked": listings,
                "violations": 1,
                "unmeasured": 0,
                "note": "the model listing answered with something that is not JSON",
                "written": 0,
                "rows": [],
            }
        listings += 1
        refs.extend(version_refs(payload))
        url = _next_page(payload)
        if url:
            sleeper(delay_seconds)

    wanted = [ref for ref in refs if ref["images_claiming_prompt"] > 0]
    from_explicit_models = [ref for ref in wanted if _publishes_above_ceiling(ref)]
    if safe_models_only:
        wanted = [ref for ref in wanted if not _publishes_above_ceiling(ref)]
    worth_it = _one_model_at_a_time(wanted)
    skipped = len(refs) - len(worth_it)
    if max_versions is not None:
        worth_it = worth_it[: max(0, int(max_versions))]

    rows: list[dict] = []
    no_prompt = 0
    too_explicit = 0
    refused = 0
    for index, ref in enumerate(worth_it):
        if index:
            sleeper(delay_seconds)
        answer = get(
            VERSION_URL.format(id=ref["version_id"]),
            why_wanted="collect prompt-and-result pairs from Civitai",
            max_bytes=3_000_000,
        )
        if answer.get("outcome") != PASS:
            refused += 1
            continue
        try:
            payload = json.loads(answer.get("text") or "")
        except ValueError:
            refused += 1
            continue
        found = pairs_from_version(payload, ref, harvested, rights)
        no_prompt += int(found["no_prompt"])
        too_explicit += int(found["too_explicit"])
        rows.extend(found["rows"])

    fresh = []
    bad: list[str] = []
    for row in rows:
        missing = _incomplete(row)
        if missing:
            bad.append(f"{row.get('image_url', '?')}: {', '.join(missing)}")
            continue
        if row["image_url"] in already:
            continue
        already.add(row["image_url"])
        fresh.append(row)

    if bad:
        # Never written, and never silently dropped either: a row that lost its
        # origin is the one thing this file must not contain, and a collector
        # that discards it quietly is how it comes to contain one anyway.
        return {
            "outcome": FAIL,
            "checked": len(rows),
            "violations": len(bad),
            "unmeasured": 0,
            "note": (
                f"{len(bad)} row(s) came out without their origin fields and NOTHING "
                f"was written: {bad[0]}"
            ),
            "written": 0,
            "rows": [],
        }

    if fresh:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as handle:
            for row in fresh:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")

    explicit_note = (
        f"{len(from_explicit_models)} of them from models that publish above the "
        f"ceiling themselves"
        + (
            " and were SKIPPED"
            if safe_models_only
            else " and were KEPT (--safe-models-only skips them)"
        )
    )
    detail = (
        f"{listings} listing page(s), {len(refs)} version(s) seen, {skipped} skipped as "
        f"claiming no prompt or above the model ceiling, {len(worth_it)} fetched, "
        f"{refused} refused; {explicit_note}; "
        f"{len(rows)} pair(s) parsed, {len(rows) - len(fresh)} already held, "
        f"{no_prompt} image(s) without wording, {too_explicit} above the nsfw ceiling"
    )
    if not rows:
        return {
            "outcome": UNMEASURED,
            "checked": len(worth_it),
            "violations": 0,
            "unmeasured": max(1, len(worth_it)),
            "note": (
                "the API answered and produced no pairs at all. "
                + (
                    f"The base-model filter {base_model!r} may simply match nothing: it "
                    "is case-sensitive and an unrecognised name returns an empty list "
                    "with 200 rather than an error (MEASURED). Check the spelling "
                    "against a family Civitai actually lists. "
                    if base_model
                    else "That is the shape the /api/v1/images endpoint already has, so "
                    "check whether this one has been stripped too before assuming a bug "
                    "here. "
                )
                + detail
            ),
            "written": 0,
            "rows": [],
        }
    return {
        "outcome": PASS,
        "checked": len(worth_it),
        "violations": 0,
        "unmeasured": no_prompt + too_explicit,
        "note": f"{len(fresh)} new pair(s) written to {target}. " + detail,
        "written": len(fresh),
        "rows": fresh,
    }


def summarise(rows: Sequence[dict] | Iterable[dict]) -> dict:
    """What a collected file holds, by provenance. For a human, before use."""
    rows = list(rows)
    by_provenance: dict[str, int] = {}
    for row in rows:
        key = str(row.get("provenance") or "")
        by_provenance[key] = by_provenance.get(key, 0) + 1
    if not rows:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "nothing collected yet",
            "by_provenance": {},
        }
    return {
        "outcome": PASS,
        "checked": len(rows),
        "violations": 0,
        "unmeasured": 0,
        "note": (
            f"{len(rows)} pair(s) from {len(by_provenance)} uploader(s); "
            f"the largest holds {max(by_provenance.values())}"
        ),
        "by_provenance": by_provenance,
    }
