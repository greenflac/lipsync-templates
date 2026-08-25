"""Background jobs with four terminal states, one of which is `unknown`.

`unknown` is the reason this module exists. A generation call that got no
answer is neither a success nor a failure: the provider may have taken the
money and produced the clip anyway. Folding that case into "failed" refunds a
user who was actually served; folding it into "done" hands out nothing and
charges for it. So it stays a third outcome and asks for a human.

To make the manual review possible at all, the provider request id is written
into the job record BEFORE the call leaves the process. An id minted after the
answer never exists for the calls that go silent — exactly the calls that need
one.

The engine call is a parameter (`runner`), never an import: tests inject a
stub, so no test can reach the network by forgetting a patch.
"""

from __future__ import annotations

import threading
import time
import uuid
from typing import Any, Callable

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
UNKNOWN = "unknown"

TERMINAL_STATES = (DONE, FAILED, UNKNOWN)

KINDS = ("frame", "video")

# The state a settled job reports alongside its outcome. `unknown` maps to
# UNMEASURED and not to FAIL, which is the whole point of the third state.
_OUTCOME_BY_STATE = {
    QUEUED: UNMEASURED,
    RUNNING: UNMEASURED,
    DONE: PASS,
    FAILED: FAIL,
    UNKNOWN: UNMEASURED,
}

Runner = Callable[..., dict]
Settler = Callable[[dict], None]

_LOCK = threading.RLock()
_JOBS: dict[str, dict] = {}


class ProviderSilent(Exception):
    """Raised by a runner that got no answer: the money may already be gone.

    A runner raises this instead of a plain exception when it cannot tell
    whether the provider did the work — a timeout, a dropped connection, a
    reply it could not parse.
    """


def new_request_id(session_id: str, kind: str, attempt: int) -> str:
    """Mint the provider request id that is stored before the call is made."""
    return f"{session_id}:{kind}:{attempt}:{uuid.uuid4().hex[:12]}"


def _record(job_id: str) -> dict | None:
    with _LOCK:
        job = _JOBS.get(job_id)
        return dict(job) if job is not None else None


def _write(job_id: str, **fields: Any) -> dict:
    with _LOCK:
        job = _JOBS[job_id]
        job.update(fields)
        return dict(job)


def _settle(job_id: str, on_settle: Settler | None) -> None:
    """Hand the settled record to the caller's compensator, never crashing the thread."""
    if on_settle is None:
        return
    record = _record(job_id)
    if record is None:
        return
    try:
        on_settle(record)
    except Exception as exc:  # noqa: BLE001 - a broken compensator must not hide the job
        _write(job_id, settle_error=f"{type(exc).__name__}: {exc}")


def _execute(job_id: str, runner: Runner, payload: dict, on_settle: Settler | None) -> None:
    """Run one job to a terminal state. Every exit path writes a state."""
    _write(job_id, state=RUNNING, started_at=time.time())
    record = _record(job_id) or {}
    try:
        result = runner(request_id=record.get("request_id"), **payload)
    except ProviderSilent as exc:
        _write(
            job_id,
            state=UNKNOWN,
            finished_at=time.time(),
            note=(
                f"the provider did not answer ({exc}); the request may have been "
                f"charged and served. Needs a human, not a retry"
            ),
        )
        _settle(job_id, on_settle)
        return
    except Exception as exc:  # noqa: BLE001 - any runner failure is the job's failure
        _write(
            job_id,
            state=FAILED,
            finished_at=time.time(),
            note=f"{type(exc).__name__}: {exc}",
        )
        _settle(job_id, on_settle)
        return

    # A runner may also *report* silence instead of raising it: an answer whose
    # own outcome is "could not measure" is the same third case.
    if isinstance(result, dict) and result.get("outcome") == UNMEASURED:
        _write(
            job_id,
            state=UNKNOWN,
            result=result,
            finished_at=time.time(),
            note=str(result.get("note") or "the runner could not tell whether the work happened"),
        )
    elif isinstance(result, dict) and result.get("outcome") == FAIL:
        _write(
            job_id,
            state=FAILED,
            result=result,
            finished_at=time.time(),
            note=str(result.get("note") or "the runner reported a failure"),
        )
    else:
        _write(
            job_id,
            state=DONE,
            result=result,
            finished_at=time.time(),
            note="finished",
        )
    _settle(job_id, on_settle)


def submit(
    session_id: str,
    kind: str,
    *,
    runner: Runner | None = None,
    payload: dict | None = None,
    attempt: int = 1,
    on_settle: Settler | None = None,
    request_id: str | None = None,
) -> str:
    """Queue one generation job and return its job id.

    Args:
        session_id: the session the job belongs to.
        kind: "frame" (cheap) or "video" (expensive).
        runner: the callable that does the work; it is given `request_id` plus
            `payload` as keyword arguments. Required — there is no default
            that reaches a provider, so a test cannot fall through to one.
        payload: keyword arguments handed to the runner.
        attempt: which attempt this is; part of the idempotency key upstream.
        on_settle: called once with the finished record, for compensation.
        request_id: provider request id; minted here when not supplied, and
            always written to the record before the runner is called.

    Example:
        >>> job_id = submit("s1", "frame", runner=lambda **kw: {"image": "a.png"})
        >>> wait(job_id)["state"]
        'done'
    """
    if kind not in KINDS:
        raise ValueError(f"unknown job kind {kind!r}; expected one of {KINDS}")
    if runner is None:
        raise ValueError("submit needs a runner: the engine call is injected, never imported")

    job_id = uuid.uuid4().hex
    record = {
        "job_id": job_id,
        "session_id": session_id,
        "kind": kind,
        "attempt": int(attempt),
        "state": QUEUED,
        "result": None,
        "note": "queued",
        # Written before the call, so a silent provider still leaves a handle
        # the operator can quote when asking what happened to the money.
        "request_id": request_id or new_request_id(session_id, kind, attempt),
        "created_at": time.time(),
        "started_at": None,
        "finished_at": None,
    }
    with _LOCK:
        _JOBS[job_id] = record

    thread = threading.Thread(
        target=_execute,
        args=(job_id, runner, dict(payload or {}), on_settle),
        name=f"job-{kind}-{job_id[:8]}",
        daemon=True,
    )
    thread.start()
    with _LOCK:
        _JOBS[job_id]["thread"] = thread
    return job_id


def attempts(session_id: str, kind: str) -> int:
    """Count the jobs of this kind already submitted for a session.

    The attempt number is derived from the jobs that exist rather than kept in
    a second counter: two places holding one number drift, and this one ends up
    inside an idempotency key. After a restart the count starts from zero again,
    which re-uses a key and therefore *replays* an old charge instead of making
    a new one — the safe direction: nobody is billed twice.
    """
    with _LOCK:
        return sum(
            1 for job in _JOBS.values() if job["session_id"] == session_id and job["kind"] == kind
        )


def status(job_id: str) -> dict:
    """Report a job's state, its three-outcome verdict and its result.

    An id nobody submitted is UNMEASURED, not a failure: the caller asked
    about something this process never saw.

    Example:
        >>> status("no-such-job")["state"]
        'unknown'
    """
    record = _record(job_id)
    if record is None:
        return {
            "job_id": job_id,
            "state": UNKNOWN,
            "outcome": UNMEASURED,
            "result": None,
            "request_id": None,
            "note": f"no job {job_id!r} in this process: nothing to report, not a failure",
        }
    record.pop("thread", None)
    record["outcome"] = _OUTCOME_BY_STATE[record["state"]]
    return record


def wait(job_id: str, *, timeout: float = 5.0) -> dict:
    """Block until the job settles and return its status; for tests and shutdown."""
    with _LOCK:
        thread = _JOBS.get(job_id, {}).get("thread")
    if thread is not None:
        thread.join(timeout)
    return status(job_id)


def reset() -> None:
    """Drop every remembered job. Test hygiene, never called by the web layer."""
    with _LOCK:
        _JOBS.clear()
