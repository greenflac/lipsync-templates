"""Load the prompt+result corpus, from wherever it actually is.

Why this module exists at all: `studio/knowledge.py` reads its two biggest
corpora from absolute paths on one developer's machine
(`/home/user/cyclerunner/...`). On a fresh clone of this repository those
directories do not exist, the index builds with 12 core entries and 0
examples, and `retrieve` answers "could not measure" for every query
(MEASURED 2026-08-26, see docs/SELFRAG_REVIEW.md). A corpus loader that
silently returns an empty list when its input is missing turns a broken
deployment into a quiet one.

So: paths are repo-relative or environment-supplied, never absolute to one
machine; a missing corpus is reported as `could not measure`, never as an
empty success; and a row that cannot be parsed is counted, not dropped in
silence.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

__all__ = [
    "CORPUS_ENV",
    "DEFAULT_CORPUS_PATHS",
    "RATING_MAX",
    "RATING_MIN",
    "CorpusRecord",
    "corpus_paths",
    "load_corpus",
    "parse_row",
    "read_jsonl",
]

# The repository root, found from this file. Everything else hangs off it, so
# the loader works from any working directory — including a cron job's.
REPO_ROOT = Path(__file__).resolve().parents[2]

# Colon-separated list of extra .jsonl corpora. The deployment names its own
# data; the code does not name one developer's home directory.
CORPUS_ENV = "STUDIO_CORPUS_PATHS"

# Searched in order, all optional. The first is the path the product brief
# names; the second is where this repo's harvester was told to write.
DEFAULT_CORPUS_PATHS: tuple[Path, ...] = (
    REPO_ROOT / "corpus" / "prompts.jsonl",
    REPO_ROOT / "studio" / "knowledge" / "gallery_prompts.jsonl",
)

# The rating scale the corpus format documents: 1..10.
RATING_MIN = 1
RATING_MAX = 10

# A row with no prompt is not a corpus record, whatever else it carries.
REQUIRED_FIELDS: tuple[str, ...] = ("prompt",)

# Longest prompt we will index. CHOSEN: a row past this is a pasted document,
# not a prompt, and it would dominate every lexical ranking it appears in.
PROMPT_MAX_CHARS = 4000

_WS = re.compile(r"\s+")


@dataclass(frozen=True)
class CorpusRecord:
    """One prompt that was actually run, and how it went.

    `rating` is None when the corpus did not say. None is not zero: an
    unrated record is unmeasured, and the replay buffer treats it as such.
    """

    record_id: str
    prompt: str
    result: str = ""
    model: str = ""
    tags: tuple[str, ...] = ()
    rating: int | None = None
    source: str = ""
    extra: dict[str, Any] = field(default_factory=dict, compare=False)

    @property
    def text(self) -> str:
        """The text retrieval matches against: the prompt plus its tags."""
        return " ".join((self.prompt, *self.tags)).strip()


def _clean(value: Any) -> str:
    """Collapse whitespace in anything stringable; None becomes empty."""
    if value is None:
        return ""
    return _WS.sub(" ", str(value)).strip()


def _tags(value: Any) -> tuple[str, ...]:
    """Normalise a tags field that may be a list, a string, or absent."""
    if value is None:
        return ()
    if isinstance(value, str):
        parts: Iterable[str] = value.replace(";", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        parts = [str(v) for v in value]
    else:
        return ()
    seen: list[str] = []
    for part in parts:
        tag = _clean(part).lower()
        if tag and tag not in seen:
            seen.append(tag)
    return tuple(seen)


def _rating(value: Any) -> tuple[int | None, str | None]:
    """Read a 1..10 rating. Returns (rating, problem); both are never set."""
    if value is None or value == "":
        return None, None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, f"rating {value!r} is not a number"
    if not RATING_MIN <= number <= RATING_MAX:
        return None, f"rating {number} is outside {RATING_MIN}..{RATING_MAX}"
    return int(round(number)), None


def parse_row(row: Any, *, source: str, line_no: int) -> tuple[CorpusRecord | None, str | None]:
    """Turn one decoded JSON row into a record, or say why it is not one.

    Exactly one of the two return slots is filled. A row that is dropped is
    always dropped with a reason attached, so the loader can report a count of
    unreadable rows instead of a shorter list than the file.

    >>> rec, why = parse_row({"prompt": "a  rooftop", "rating": 9}, source="s", line_no=1)
    >>> rec.prompt, rec.rating, why
    ('a rooftop', 9, None)
    >>> parse_row({"result": "nice"}, source="s", line_no=2)[1]
    "s:2 has no 'prompt' field"
    """
    if not isinstance(row, dict):
        return None, f"{source}:{line_no} is a JSON {type(row).__name__}, not an object"
    for name in REQUIRED_FIELDS:
        if not _clean(row.get(name)):
            return None, f"{source}:{line_no} has no {name!r} field"

    prompt = _clean(row.get("prompt"))
    if len(prompt) > PROMPT_MAX_CHARS:
        return None, f"{source}:{line_no} prompt is {len(prompt)} chars, cap is {PROMPT_MAX_CHARS}"

    rating, problem = _rating(row.get("rating"))
    if problem is not None:
        return None, f"{source}:{line_no} {problem}"

    known = {"prompt", "result", "model", "tags", "rating", "id"}
    record = CorpusRecord(
        record_id=_clean(row.get("id")) or f"{source}:{line_no}",
        prompt=prompt,
        result=_clean(row.get("result")),
        model=_clean(row.get("model")).lower(),
        tags=_tags(row.get("tags")),
        rating=rating,
        source=source,
        extra={k: v for k, v in row.items() if k not in known},
    )
    return record, None


def read_jsonl(path: Path) -> Iterator[tuple[int, Any, str | None]]:
    """Yield (line_no, decoded, error) for every non-blank line of a .jsonl.

    Decode errors are yielded, not raised: one malformed line in a harvested
    corpus must not cost the other ten thousand.
    """
    with path.open(encoding="utf-8") as handle:
        for line_no, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("//"):
                continue
            try:
                yield line_no, json.loads(stripped), None
            except ValueError as exc:
                yield line_no, None, f"{path.name}:{line_no} is not JSON: {exc}"


def corpus_paths(*, extra: Sequence[Path] | None = None) -> list[Path]:
    """Every corpus path this deployment is configured to read, in order.

    The environment variable comes first: a deployment that names its own data
    should not have that data outranked by a default.
    """
    paths: list[Path] = []
    raw = os.environ.get(CORPUS_ENV, "")
    for piece in raw.split(os.pathsep):
        piece = piece.strip()
        if piece:
            paths.append(Path(piece).expanduser())
    paths.extend(DEFAULT_CORPUS_PATHS)
    if extra:
        paths.extend(extra)
    out: list[Path] = []
    for path in paths:
        if path not in out:
            out.append(path)
    return out


def load_corpus(*, paths: Sequence[Path] | None = None) -> dict:
    """Read every configured corpus into records, and say what happened.

    Three outcomes, and the middle one is the point:

    * `pass` — at least one record was read.
    * `fail` — files existed and every row in them was unreadable.
    * `could not measure` — no configured corpus file exists. This is NOT an
      empty corpus. A caller that treats it as one ships an agent with no
      examples and no warning, which is exactly the failure this module was
      written after.

    :param paths: corpora to read; the configured ones if omitted.
    :returns: the studio judging dict plus `records`, `files`, `missing`.

    >>> out = load_corpus(paths=[])
    >>> out["outcome"]
    'could not measure'
    """
    search = list(paths) if paths is not None else corpus_paths()
    records: list[CorpusRecord] = []
    problems: list[str] = []
    files: list[str] = []
    missing: list[str] = []
    seen_ids: set[str] = set()

    for path in search:
        if not path.is_file():
            missing.append(str(path))
            continue
        files.append(str(path))
        for line_no, row, error in read_jsonl(path):
            if error is not None:
                problems.append(error)
                continue
            record, why = parse_row(row, source=path.name, line_no=line_no)
            if record is None:
                problems.append(why or "unreadable row")
                continue
            if record.record_id in seen_ids:
                problems.append(f"{record.record_id} is a duplicate id: kept the first")
                continue
            seen_ids.add(record.record_id)
            records.append(record)

    checked = len(records) + len(problems)
    if not files:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": len(missing),
            "note": (
                f"no corpus file exists; looked in {len(missing)}: "
                f"{', '.join(missing) or 'nowhere'}. This is not an empty corpus."
            ),
            "records": [],
            "files": [],
            "missing": missing,
            "problems": [],
        }
    if not records:
        return {
            "outcome": FAIL,
            "checked": checked,
            "violations": len(problems),
            "unmeasured": len(missing),
            "note": f"{len(files)} corpus file(s) read, every one of {checked} rows unreadable",
            "records": [],
            "files": files,
            "missing": missing,
            "problems": problems[:20],
        }
    return {
        "outcome": PASS,
        "checked": checked,
        "violations": len(problems),
        "unmeasured": len(missing),
        "note": f"{len(records)} records from {len(files)} file(s), {len(problems)} rows unreadable",
        "records": records,
        "files": files,
        "missing": missing,
        "problems": problems[:20],
    }
