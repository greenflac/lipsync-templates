"""The studio web layer: sessions, uploads, style, and the two paid generations.

Two rules shape every handler here.

Money moves in one order: charge, then call, then compensate when the call
failed. The idempotency key is `session_id:kind:attempt`, so a retried request
never charges twice and a compensating refund can be tied to the charge it
undoes.

The expensive call is guarded by *server* state. The consent that unlocks the
video is recorded only after the frame job actually finished, and the video
handler reads that record — a client that simply claims consent gets a refusal,
because a claim is not evidence.

Everything the layer depends on (store, ledger, style extraction, photo intake,
the engine runners) arrives through `Deps`, so the tests run the whole path
without a network and without the sibling modules being finished.
"""

from __future__ import annotations

import shutil
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio import jobs, templates

# CHOSEN by the owner (studio/CONTRACTS.md): the frame costs cents, the video
# costs ~$0.70 of real money. Imported from nowhere else on purpose — this is
# the one place the studio prices its two calls.
FRAME_CREDITS = 1
VIDEO_CREDITS = 10

# The stages a session moves through. They live in `store.stage`, the only
# column the store keeps for progress, and they are the studio's memory of what
# the user has actually been shown — the video guard reads this, never the body
# of the request that asks for a video.
STAGE_SELFIE = "selfie"
STAGE_STYLED = "styled"
STAGE_FRAME_RUNNING = "frame_running"
STAGE_FRAME_SHOWN = "frame_shown"
STAGE_CONSENTED = "consented"
STAGE_VIDEO_RUNNING = "video_running"
STAGE_DONE = "done"
STAGE_REVIEW = "needs_review"

STUDIO_DIR = Path(__file__).resolve().parent
DEFAULT_UPLOADS = STUDIO_DIR / "uploads"
DEFAULT_STATIC = STUDIO_DIR / "static"

# HTTP codes carrying the three outcomes: a refusal the user can fix (400/402/409)
# is not the same answer as "we could not find out" (503), and neither is a 500.
HTTP_BAD_INPUT = 400
HTTP_NO_CREDITS = 402
HTTP_NOT_FOUND = 404
HTTP_GUARD = 409
HTTP_UNMEASURED = 503

PLACEHOLDER_HTML = (
    "<!doctype html><meta charset='utf-8'><title>studio</title>"
    "<h1>studio</h1><p>The interface is not built yet. The API is up: "
    "<code>GET /api/templates</code>.</p>"
)


def _default_store() -> Any:
    """Import the session store late, so this module loads before it is written."""
    from studio import store  # noqa: PLC0415

    return store


def _default_ledger() -> Any:
    """Import the credit journal late, for the same reason as the store."""
    from studio import ledger  # noqa: PLC0415

    return ledger


def _default_style() -> Any:
    """Import the style extractor late, for the same reason as the store."""
    from studio import style  # noqa: PLC0415

    return style


def _default_photo_intake() -> Callable[..., dict]:
    """Return the frozen engine's photo acceptance; the studio never re-implements it."""
    from lipsync.fork_intake import photo_intake  # noqa: PLC0415

    return photo_intake


def _no_runner(**_: Any) -> dict:
    """Refuse to generate when no runner was injected: silence beats a surprise bill."""
    raise RuntimeError(
        "no generation runner is configured; the engine call is injected, never implicit"
    )


@dataclass
class Deps:
    """Everything the handlers call out to. Tests replace these with stubs."""

    store: Any = None
    ledger: Any = None
    style: Any = None
    photo_intake: Callable[..., dict] | None = None
    frame_runner: Callable[..., dict] = _no_runner
    video_runner: Callable[..., dict] = _no_runner
    uploads_dir: Path = field(default_factory=lambda: DEFAULT_UPLOADS)
    static_dir: Path = field(default_factory=lambda: DEFAULT_STATIC)

    def resolved(self) -> Deps:
        """Fill in the real modules for whatever the caller left unset."""
        if self.store is None:
            self.store = _default_store()
        if self.ledger is None:
            self.ledger = _default_ledger()
        if self.style is None:
            self.style = _default_style()
        if self.photo_intake is None:
            self.photo_intake = _default_photo_intake()
        return self


class SessionIn(BaseModel):
    """Body of `POST /api/session`."""

    user_id: str


class StyleIn(BaseModel):
    """Body of `POST /api/style`."""

    session_id: str
    text: str


class SessionRef(BaseModel):
    """Body of the endpoints that only need to name a session."""

    session_id: str


class FrameIn(BaseModel):
    """Body of `POST /api/frame`: a session plus the motion template picked."""

    session_id: str
    template_id: str


def _fail(status: int, note: str, **extra: Any) -> JSONResponse:
    """Answer a refusal in the shape every handler uses."""
    return JSONResponse({"outcome": FAIL, "note": note, **extra}, status_code=status)


def _unmeasured(note: str, **extra: Any) -> JSONResponse:
    """Answer "could not find out" — never a 500, never a quiet success."""
    return JSONResponse({"outcome": UNMEASURED, "note": note, **extra}, status_code=HTTP_UNMEASURED)


def _by_outcome(status_for_fail: int, verdict: dict, note: str) -> JSONResponse:
    """Turn a three-outcome verdict from another module into the matching answer."""
    if verdict.get("outcome") == UNMEASURED:
        return _unmeasured(f"{note}: {verdict.get('note', '')}".strip(": "))
    return _fail(status_for_fail, f"{note}: {verdict.get('note', '')}".strip(": "), verdict=verdict)


def spec_object(deps: Deps, spec: Any) -> Any:
    """Rehydrate a StyleSpec that came back from the store as plain JSON.

    The store keeps the spec as JSON, so what comes back is a mapping; the
    prompt builder wants the dataclass. Rebuilding it here keeps the spec in
    one place (the store) instead of caching a second copy of the prompt.
    """
    if not isinstance(spec, dict):
        return spec
    factory = getattr(deps.style, "StyleSpec", None)
    if factory is None:
        return spec
    fields = dict(spec)
    if "palette" in fields:
        fields["palette"] = tuple(fields["palette"])
    return factory(**fields)


def _remember(deps: Deps, session_id: str, **fields: Any) -> dict:
    """Write session fields and hand back the store's verdict, whatever its shape."""
    verdict = deps.store.update(session_id, **fields)
    return verdict if isinstance(verdict, dict) else {"outcome": PASS}


def charge_and_start(
    deps: Deps,
    session: dict,
    *,
    kind: str,
    credits: int,
    runner: Callable[..., dict],
    payload: dict,
    stage_running: str,
    stage_done: str,
    stage_back: str,
) -> JSONResponse:
    """Charge, launch the job, and arrange the compensation — in that order.

    The charge lands before the call so a crash between the two leaves a charge
    with no work (visible, refundable) rather than work with no charge
    (invisible, unbilled). The refund is a compensating journal entry keyed to
    the charge, and it is written only for a job that *failed*: a job that ended
    `unknown` may have been served, and is left for a human.

    Args:
        deps: injected collaborators.
        session: the session record, already loaded.
        kind: "frame" or "video".
        credits: what this call costs.
        runner: the engine call; receives `request_id` plus `payload`.
        payload: keyword arguments for the runner.
        stage_running: stage written while the job runs.
        stage_done: stage written when the job finishes cleanly.
        stage_back: stage restored when the job failed and was refunded.

    Example:
        >>> callable(charge_and_start)
        True
    """
    session_id = session["session_id"]
    attempt = jobs.attempts(session_id, kind) + 1
    key = f"{session_id}:{kind}:{attempt}"
    charged = deps.ledger.charge(
        session["user_id"], credits, key=key, reason=f"{kind} generation, attempt {attempt}"
    )
    if charged.get("outcome") != PASS:
        # A short balance is the user's to fix, an unreachable journal is ours.
        # Neither may let the paid call go out.
        return _by_outcome(HTTP_NO_CREDITS, charged, f"{kind} not started, nothing was charged")

    # ПОВТОР КЛЮЧА — НЕ ОПЛАТА, И ОТВЕТ ВЫВОДИТСЯ ИЗ ТОГО, ЧТО ИСПОЛНИЛОСЬ (Е2).
    # `charge` на уже записанном ключе честно отвечает `pass` и ставит
    # `duplicate: True`: журнал ПОВТОРЯЕТ прежнюю строку и НИЧЕГО не списывает.
    # ИЗМЕРЕНО 2026-09-05: баланс 100 -> 90 после первого списания и 90 после
    # второго с тем же ключом, `delta` в обоих ответах -10. Здесь этот ответ
    # читался как «списали» — и наверх уходило `"charged": credits` рядом с
    # запущенной ПЛАТНОЙ генерацией, за которую не заплатил никто.
    #
    # Ключ повторяется, когда `jobs.attempts` начал счёт заново: реестр задач
    # живёт в памяти процесса, и перезапуск обнуляет номер попытки. То есть это
    # НЕ отказ пользователю и НЕ его вина — это потерянное нами состояние, по
    # которому нельзя решить, шла эта попытка уже или нет. Третий исход, а не
    # первые два: запускать работу под чужой оплаченной строкой нельзя, но и
    # объявлять её неудачей — врать в другую сторону.
    if charged.get("duplicate"):
        return _by_outcome(
            HTTP_GUARD,
            {
                "outcome": UNMEASURED,
                "checked": 0,
                "unmeasured": 1,
                "note": (
                    f"ключ {key!r} уже записан в журнале: списания НЕ БЫЛО, "
                    f"баланс {charged.get('balance')} не изменился. Это значит, что "
                    f"номер попытки начался заново (реестр задач живёт в памяти и "
                    f"обнуляется при перезапуске), и по нему нельзя решить, шла эта "
                    f"попытка уже или нет. {kind} НЕ запущен — платная работа под "
                    f"чужой оплаченной строкой не начинается. Нужен человек: "
                    f"посмотреть в журнале строку {key!r}"
                ),
            },
            f"{kind} not started, nothing was charged",
        )

    def compensate(record: dict) -> None:
        """Give the credits back for a failed job; leave an `unknown` one alone."""
        if record["state"] == jobs.FAILED:
            deps.ledger.refund(
                session["user_id"],
                credits,
                key=f"{key}:refund",
                reason=f"{kind} generation failed: {record.get('note', '')}"[:200],
            )
            _remember(deps, session_id, stage=stage_back)
            return
        if record["state"] == jobs.UNKNOWN:
            # The provider may have done the work and taken the money. A refund
            # here hands out free clips; a failure charges for nothing. Park the
            # session where a human has to look at it.
            _remember(deps, session_id, stage=STAGE_REVIEW)
            return
        _remember(deps, session_id, stage=stage_done)

    # The stage is written BEFORE the job starts: the job settles on another
    # thread and writes the stage itself, so a stage written afterwards would
    # sometimes land on top of the finished one and lose the result.
    _remember(deps, session_id, stage=stage_running)
    job_id = jobs.submit(
        session_id,
        kind,
        runner=runner,
        payload=payload,
        attempt=attempt,
        on_settle=compensate,
    )
    _remember(deps, session_id, last_job_id=job_id)
    return JSONResponse(
        {
            "outcome": PASS,
            "job_id": job_id,
            "kind": kind,
            "charged": credits,
            "idempotency_key": key,
            "balance": charged.get("balance"),
            "note": f"{kind} generation started",
        }
    )


def frame_state(session: dict) -> dict:
    """Judge whether a first frame was produced and shown: three outcomes.

    The stage says which step the session reached; while the frame job is in
    flight the job registry is the fresher witness, so the verdict is taken
    from the job that actually ran rather than from the stage written first.

    Example:
        >>> frame_state({"stage": "styled", "last_job_id": None})["outcome"]
        'fail'
    """
    stage = str(session.get("stage") or "")
    job_id = session.get("last_job_id")
    if stage == STAGE_REVIEW:
        return {
            "outcome": UNMEASURED,
            "checked": 1,
            "violations": 0,
            "unmeasured": 1,
            "note": "the last job ended unknown; this session is waiting for a human",
        }
    if stage in (STAGE_FRAME_SHOWN, STAGE_CONSENTED, STAGE_VIDEO_RUNNING, STAGE_DONE):
        return {
            "outcome": PASS,
            "checked": 1,
            "violations": 0,
            "unmeasured": 0,
            "note": "a first frame was generated and shown",
        }
    if stage == STAGE_FRAME_RUNNING:
        state = jobs.status(str(job_id)) if job_id else {"state": jobs.QUEUED}
        if state["state"] == jobs.DONE:
            return {
                "outcome": PASS,
                "checked": 1,
                "violations": 0,
                "unmeasured": 0,
                "note": "the first frame job finished",
            }
        if state["state"] == jobs.FAILED:
            return {
                "outcome": FAIL,
                "checked": 1,
                "violations": 1,
                "unmeasured": 0,
                "note": "the first frame job failed; generate a frame the user can look at",
            }
        return {
            "outcome": UNMEASURED,
            "checked": 1,
            "violations": 0,
            "unmeasured": 1,
            "note": f"the first frame job is {state['state']}: nothing was shown yet",
        }
    return {
        "outcome": FAIL,
        "checked": 1,
        "violations": 1,
        "unmeasured": 0,
        "note": "no first frame was generated for this session; there is nothing to agree to",
    }


def consent_state(session: dict) -> dict:
    """Judge whether this session may buy a video, from stored state only.

    PASS demands two separate facts on the server: a frame job that finished,
    and a consent recorded *after* it. What the request body claims is not one
    of the inputs.

    Example:
        >>> consent_state({"stage": "frame_shown"})["outcome"]
        'fail'
    """
    frame = frame_state(session)
    if frame["outcome"] != PASS:
        return frame
    стадия = str(session.get("stage"))
    # ОДНО СОГЛАСИЕ — ОДНО ВИДЕО (исправлено 2026-09-05 по независимому аудиту).
    #
    # Здесь пропускались стадии `consented`, `video_running` И `done`, и это
    # значило, что одно согласие открывает НЕОГРАНИЧЕННОЕ число платных
    # генераций. Прогон: кадр -> согласие -> три подряд POST /api/video: все три
    # по 200, раннер вызван трижды, баланс 99 -> 69.
    #
    # Второе и третье видео шли ещё и БЕЗ ОДОБРЕННОГО КАДРА: кадр берётся из
    # `last_job_id`, а после первого видео там уже видео-джоба, и в payload
    # `frame` приходил None. Человек платил за генерацию, которой не показывали
    # то, на что он соглашался.
    #
    # Двойной клик в интерфейсе — обычное дело, и он не должен стоить денег.
    if стадия == STAGE_VIDEO_RUNNING:
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": (
                "видео по этому согласию УЖЕ идёт: одно согласие оплачивает одно "
                "видео, второй запуск — это второй счёт заказчику"
            ),
        }
    if стадия == STAGE_DONE:
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": (
                "видео по этому согласию УЖЕ сделано: завершённая работа не есть "
                "разрешение начать новую — нужен новый кадр и новое согласие"
            ),
        }
    if стадия != STAGE_CONSENTED:
        return {
            "outcome": FAIL,
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": "the user has not agreed to the paid video for this frame",
        }
    return {
        "outcome": PASS,
        "checked": 1,
        "violations": 0,
        "unmeasured": 0,
        "note": "the frame was shown and the user agreed to it",
    }


def save_upload(upload: UploadFile, uploads_dir: Path) -> Path:
    """Put an uploaded file on disk under a name of ours, never the client's."""
    uploads_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(upload.filename or "").suffix.lower()
    # The client's filename is data, not a path: naming the file ourselves
    # removes traversal and collisions in one move.
    safe_suffix = suffix if suffix in (".jpg", ".jpeg", ".png", ".webp") else ".bin"
    target = uploads_dir / f"{uuid.uuid4().hex}{safe_suffix}"
    with target.open("wb") as handle:
        shutil.copyfileobj(upload.file, handle)
    return target


def create_app(deps: Deps | None = None) -> FastAPI:
    """Build the studio API around a set of collaborators.

    Args:
        deps: injected store, ledger, style, intake and runners. Omitted, the
            real modules are imported when the first request needs them.

    Example:
        >>> create_app(Deps()).title
        'lipsync studio'
    """
    d = (deps or Deps()).resolved()
    app = FastAPI(title="lipsync studio")

    def load(session_id: str) -> dict | None:
        return d.store.get(session_id)

    def prompt_for(session: dict) -> str:
        return str(d.style.build_prompt(spec_object(d, session["style_spec"])))

    @app.post("/api/session")
    def post_session(body: SessionIn) -> JSONResponse:
        """Open a session for a user and hand back its id."""
        session_id = d.store.create_session(body.user_id)
        return JSONResponse({"outcome": PASS, "session_id": session_id, "note": "session opened"})

    @app.get("/api/templates")
    def get_templates() -> JSONResponse:
        """List the motion templates, including the ones missing from this deploy."""
        verdict = templates.availability()
        return JSONResponse(
            {
                "outcome": verdict["outcome"],
                "templates": templates.catalogue(),
                "availability": verdict,
                "note": verdict["note"],
            }
        )

    @app.post("/api/selfie")
    def post_selfie(session_id: str = Form(...), file: UploadFile = File(...)) -> JSONResponse:
        """Store the client photo and run the engine's photo acceptance on it."""
        session = load(session_id)
        if session is None:
            return _fail(HTTP_NOT_FOUND, f"no session {session_id!r}")
        path = save_upload(file, d.uploads_dir)
        assert d.photo_intake is not None  # resolved() guarantees it
        report = d.photo_intake(str(path))
        outcome = report.get("outcome")
        if outcome == UNMEASURED:
            # The detector was silent. That is not "there is no face in the
            # photo", and telling the user to retake it would be a lie.
            return _unmeasured(
                f"the photo could not be checked: {report.get('note', '')}", report=report
            )
        if outcome != PASS:
            return _fail(
                HTTP_BAD_INPUT,
                f"this photo cannot be used: {report.get('note', '')}",
                report=report,
            )
        written = _remember(d, session_id, selfie_path=str(path), stage=STAGE_SELFIE)
        if written.get("outcome") != PASS:
            return _by_outcome(HTTP_BAD_INPUT, written, "the photo was not remembered")
        return JSONResponse(
            {"outcome": PASS, "selfie_path": str(path), "report": report, "note": "photo accepted"}
        )

    @app.post("/api/style")
    def post_style(body: StyleIn) -> JSONResponse:
        """Turn the user's free text into a StyleSpec and gate it."""
        session = load(body.session_id)
        if session is None:
            return _fail(HTTP_NOT_FOUND, f"no session {body.session_id!r}")
        extracted = d.style.extract(body.text)
        spec = extracted.get("spec")
        if extracted.get("outcome") != PASS or spec is None:
            return _by_outcome(HTTP_BAD_INPUT, extracted, "the style was not accepted")
        gate = d.style.gate_input(spec)
        if gate.get("outcome") != PASS:
            return _by_outcome(HTTP_BAD_INPUT, gate, "the style was refused")
        written = _remember(d, body.session_id, style_spec=spec, stage=STAGE_STYLED)
        if written.get("outcome") != PASS:
            return _by_outcome(HTTP_BAD_INPUT, written, "the style was not remembered")
        return JSONResponse(
            {
                "outcome": PASS,
                "spec": _spec_dict(spec),
                "prompt": d.style.build_prompt(spec),
                "note": "style accepted",
            }
        )

    @app.post("/api/frame")
    def post_frame(body: FrameIn) -> JSONResponse:
        """Charge the cheap price and start the first-frame generation."""
        session = load(body.session_id)
        if session is None:
            return _fail(HTTP_NOT_FOUND, f"no session {body.session_id!r}")
        if not session.get("selfie_path"):
            return _fail(HTTP_GUARD, "no accepted selfie in this session yet")
        if not session.get("style_spec"):
            return _fail(HTTP_GUARD, "no accepted style in this session yet")
        template = templates.get(body.template_id)
        if template is None:
            return _fail(HTTP_BAD_INPUT, f"no motion template {body.template_id!r}")
        _remember(d, body.session_id, template=body.template_id)
        return charge_and_start(
            d,
            {**session, "session_id": body.session_id},
            kind="frame",
            credits=FRAME_CREDITS,
            runner=d.frame_runner,
            payload={
                "photo": session["selfie_path"],
                "prompt": prompt_for(session),
                "template": template,
            },
            stage_running=STAGE_FRAME_RUNNING,
            stage_done=STAGE_FRAME_SHOWN,
            stage_back=STAGE_STYLED,
        )

    @app.post("/api/consent")
    def post_consent(body: SessionRef) -> JSONResponse:
        """Record that the user looked at the finished frame and wants the video."""
        session = load(body.session_id)
        if session is None:
            return _fail(HTTP_NOT_FOUND, f"no session {body.session_id!r}")
        frame = frame_state({**session, "session_id": body.session_id})
        if frame["outcome"] != PASS:
            return _by_outcome(HTTP_GUARD, frame, "consent not recorded")
        _remember(d, body.session_id, stage=STAGE_CONSENTED)
        return JSONResponse({"outcome": PASS, "note": "consent recorded for the shown frame"})

    @app.post("/api/video")
    def post_video(body: SessionRef) -> JSONResponse:
        """Charge the expensive price and start the video — consent checked server-side."""
        session = load(body.session_id)
        if session is None:
            return _fail(HTTP_NOT_FOUND, f"no session {body.session_id!r}")
        gate = consent_state({**session, "session_id": body.session_id})
        if gate["outcome"] != PASS:
            return _by_outcome(HTTP_GUARD, gate, "the paid video was not started")
        template = templates.get(str(session.get("template") or ""))
        if template is None:
            return _fail(HTTP_GUARD, "this session has no motion template")
        frame_job = session.get("last_job_id")
        return charge_and_start(
            d,
            {**session, "session_id": body.session_id},
            kind="video",
            credits=VIDEO_CREDITS,
            runner=d.video_runner,
            payload={
                "photo": session["selfie_path"],
                "prompt": prompt_for(session),
                "template": template,
                "frame": jobs.status(str(frame_job)).get("result") if frame_job else None,
            },
            stage_running=STAGE_VIDEO_RUNNING,
            stage_done=STAGE_DONE,
            stage_back=STAGE_CONSENTED,
        )

    @app.get("/api/job/{job_id}")
    def get_job(job_id: str, session_id: str = "") -> JSONResponse:
        """Report one job's state; an unknown id is reported, not raised.

        ЗАДАЧА ОТДАЁТСЯ ТОЛЬКО В СВОЮ СЕССИЮ. До 2026-09-05 это был
        единственный маршрут, не спрашивавший, чья работа: он отдавал
        `session_id` и РЕЗУЛЬТАТ любому, кто назвал идентификатор задачи.
        Угадать его трудно (uuid4, 122 бита), но «трудно угадать» — не проверка
        доступа, а её отсутствие с оговоркой; идентификатор попадает в логи,
        в адресную строку и в чужую вкладку.

        Не назвали сессию — третий исход, а не отказ и не выдача: мы не знаем,
        свой это спрашивает или чужой, и молча выбрать один из ответов значило
        бы решить за того, кто нас об этом не спрашивал.
        """
        state = jobs.status(job_id)
        state.pop("thread", None)
        if not session_id:
            return _unmeasured(
                f"job {job_id!r}: не сказано, чья это задача — добавьте "
                f"?session_id=…; чужую работу этот маршрут не отдаёт"
            )
        чья = state.get("session_id")
        if чья is not None and чья != session_id:
            return _fail(HTTP_GUARD, f"job {job_id!r} принадлежит другой сессии")
        return JSONResponse(state)

    @app.get("/", response_class=HTMLResponse)
    def get_index() -> HTMLResponse:
        """Serve the interface, or a placeholder while it is still being written."""
        index = d.static_dir / "index.html"
        if index.is_file():
            return HTMLResponse(index.read_text(encoding="utf-8"))
        return HTMLResponse(PLACEHOLDER_HTML)

    return app


def _spec_dict(spec: Any) -> Any:
    """Render a StyleSpec for JSON without assuming which shape it arrived in."""
    if hasattr(spec, "__dataclass_fields__"):
        from dataclasses import asdict  # noqa: PLC0415

        return asdict(spec)
    return spec


# The module-level app is what uvicorn serves; it resolves its real
# collaborators on first use, so importing this module never needs them.
app = create_app()
