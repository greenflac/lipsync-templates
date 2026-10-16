"""How the planner consumes the recipe table (`studio/recipes/table.py`).

Three entry points, one per place the planner decides:

* `rewrite(spec, route)` — BEFORE selection: the route built from the spec is
  rewritten by the job class (voice sample -> clone, own video -> lip sync on it,
  logo image -> end card, one host -> one reference, visualiser -> short loops,
  archive -> no deblur), and the free tools of the class go to assembly.
* `frame_prior` / `fps_prior` — AFTER selection, where the base is SILENT about
  the chosen model's frame or frame rate: the class prior fills the silence
  (upscale / interpolation step) instead of a note «not added on silence». A
  recorded fact about the model is decided by the planner before these are asked
  and always wins.
* `order(names)` — order of operations: voice clone first; restore -> colourise
  -> upscale -> interpolate.

Every applied prior is returned by id so the plan states it (with its tag and
sources) as an assumption; `spec.priors = {"<id>": false}` switches it off, and
the plan then lists it as overridden.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, replace
from typing import Callable, Mapping, Sequence

from studio import brief_spec as bs
from studio.recipes.table import (
    FAILURES,
    PRIORS,
    RECIPES,
    SINGLE_HOST_REFERENCES,
    TAG_RU,
    T2I_NATIVE_MAX_MP,
    T2V_NATIVE_FPS_MAX,
    T2V_NATIVE_MAX_MP,
    TOOLS,
    VISUALISER_LOOP_CLIP_S,
    VISUALISER_LOOP_CLIPS,
    Prior,
)

#: Planner operations that MAKE a still / a clip (not a pass over a brought one).
IMAGE_GENERATORS: frozenset[str] = frozenset({"генерация_изображения", "редактирование_изображения"})
VIDEO_GENERATORS: frozenset[str] = frozenset({"генерация_видео", "оживление", "видео_по_референсу", "говорящий_аватар"})
#: Steps that consume speech.
SPEECH_CONSUMERS: frozenset[str] = frozenset({"говорящий_аватар", "липсинк"})
#: Order of operations over footage (rank; lower first). Upscale of a still ranks with video upscale.
CHAIN_RANK: dict[str, int] = {
    "реставрация": 1,
    "раскраска": 2,
    "апскейл": 3,
    "апскейл_изображения": 3,
    "интерполяция_кадров": 4,
}
#: Steps placed before everything: they need only the customer's sample.
FIRST_STEPS: tuple[str, ...] = ("клонирование_голоса",)
#: A logo / wordmark named in `spec.conditions`.
LOGO = re.compile(r"\blogo|wordmark|brand[ -]?mark|логотип", re.I)
#: Tasks where a logo condition means «the brand mark is composited»: the piece is made here.
LOGO_TASKS: frozenset[str | None] = frozenset({None, "generate", "animate"})
#: A music video of distinct scenes named in `spec.conditions`: not a loop visualiser.
SCENES = re.compile(r"scene|story|narrative|music video|сцен|сюжет|клип", re.I)
#: Blur named by the caller: then a deblur model IS the tool.
BLUR = re.compile(r"blur|расфокус|размыт|смаз", re.I)
#: Restoration models ranked last on archive film unless blur is named.
DEBLUR_MODELS = r"deblur|sharpen"
#: The planner's name of the video artefact (`planner.ARTEFACT_VIDEO`).
ARTEFACT_VIDEO = "видео"

NOTE_CLONE = (
    "голос — клон по ВАШЕЙ записи: текст читается этим голосом",
    "the voice is cloned from YOUR recording: the text is read in that voice",
)
NOTE_OWN_LIPSYNC = (
    "губы двигаются на ВАШЕМ видео человека под новую речь — нового лица не генерируется",
    "the lips move on YOUR video of the person to the new speech — no new face is generated",
)
NOTE_ENDCARD_FOOTAGE = (
    "рекламные кадры без текста; ваш снимок — логотип, он ложится финальной карточкой при сборке",
    "ad footage without text; your image is the logo and goes on as the end card at assembly",
)
NOTE_LOOPS = (
    f"{VISUALISER_LOOP_CLIPS} зацикливаемых клипа по {VISUALISER_LOOP_CLIP_S} с; длину трека даёт сборка",
    f"{VISUALISER_LOOP_CLIPS} loopable clips of {VISUALISER_LOOP_CLIP_S} s; assembly reaches the track's length",
)
NOTE_V2A = (
    "«видео -> звук»: модель смотрит ВАШ ролик (MMAudio, HunyuanVideo-Foley)",
    "video-to-audio: the model watches YOUR footage (MMAudio, HunyuanVideo-Foley)",
)
NOTE_ONE_REFERENCE = (
    f"{SINGLE_HOST_REFERENCES} референс ведущего на все ролики",
    f"{SINGLE_HOST_REFERENCES} reference of the host for every short",
)

ASSEMBLY_LOGO = (
    "логотип накладывается из ВАШЕГО файла (ffmpeg overlay) финальной карточкой — буква в букву; "
    "сгенерированный текст в кадр не идёт — 0 usd",
    "the logo is composited from YOUR file (ffmpeg overlay) as the end card — letter for letter; no "
    "generated lettering is used — 0 usd",
)
ASSEMBLY_LOGO_STING = (
    "финальная пауза: сгенерированное движение перетекает (ffmpeg xfade) в настоящий логотип из ВАШЕГО файла — 0 usd",
    "final hold: the generated motion crossfades (ffmpeg xfade) into the true logo from YOUR file — 0 usd",
)
ASSEMBLY_FOLEY = (
    "шумы сводятся под исходный звук (ffmpeg amix), громкость — ffmpeg loudnorm — 0 usd",
    "the foley is mixed under the original sound (ffmpeg amix), loudness by ffmpeg loudnorm — 0 usd",
)
ASSEMBLY_LOOPS = (
    f"{VISUALISER_LOOP_CLIPS} клипа по {VISUALISER_LOOP_CLIP_S} с зацикливаются и режутся по долям трека "
    "(ffmpeg concat) на всю его длину — 0 usd",
    f"the {VISUALISER_LOOP_CLIPS} clips of {VISUALISER_LOOP_CLIP_S} s are looped and cut on the track's beats "
    "(ffmpeg concat) to its full length — 0 usd",
)
ASSEMBLY_FILM = (
    "до модели, на исходнике: мерцание — ffmpeg deflicker, пыль и царапины — VapourSynth DeScratch / "
    "RemoveDirt — 0 usd",
    "before the model, on the source: flicker — ffmpeg deflicker, dust and scratches — VapourSynth DeScratch / "
    "RemoveDirt — 0 usd",
)
ASSEMBLY_EXTRACT = (
    "образец голоса вынимается из ВАШЕГО видео (ffmpeg -vn) — 0 usd",
    "the voice sample is taken out of YOUR video (ffmpeg -vn) — 0 usd",
)


@dataclass(frozen=True)
class Applied:
    """What the recipes did to one plan."""

    route: "bs.Маршрут"
    recipes: tuple[str, ...] = ()
    priors: tuple[str, ...] = ()
    overridden: tuple[str, ...] = ()
    tools: tuple[str, ...] = ()
    failures: tuple[str, ...] = ()
    #: op -> (seconds priced, seconds of one run).
    step_seconds: Mapping[str, tuple[float, float]] = field(default_factory=dict)
    #: op -> artefact a candidate should take as input (ranked first).
    prefer_input: Mapping[str, str] = field(default_factory=dict)
    #: op -> regex of model names ranked last.
    avoid: Mapping[str, str] = field(default_factory=dict)
    #: (ru, en) assembly reasons — free tools, 0 usd.
    assembly: tuple[tuple[str, str], ...] = ()
    #: 0 budget: the plan offers the open-weights route.
    free_route: bool = False


def enabled(spec: "bs.Spec", prior_id: str) -> bool:
    """A prior is on unless `spec.priors[id]` is false."""
    return (spec.priors or {}).get(prior_id, True) is not False


class _Acc:
    """Accumulator: recipes and priors in the order met, without repeats."""

    def __init__(self, spec: "bs.Spec") -> None:
        self.spec = spec
        self.recipes: list[str] = []
        self.priors: list[str] = []
        self.overridden: list[str] = []
        self.assembly: list[tuple[str, str]] = []
        self.tools: list[str] = []

    def prior(self, recipe: str, prior_id: str) -> bool:
        """Matched: True when the prior is on (and records it), False when switched off."""
        if recipe not in self.recipes:
            self.recipes.append(recipe)
        if not enabled(self.spec, prior_id):
            if prior_id not in self.overridden:
                self.overridden.append(prior_id)
            return False
        if prior_id not in self.priors:
            self.priors.append(prior_id)
        return True


def _replace_step(steps: list[str], old: str, new: str) -> list[str]:
    return list(dict.fromkeys(new if s == old else s for s in steps))


def rewrite(spec: "bs.Spec", route: "bs.Маршрут") -> Applied:
    """Recipes of the job classes this spec belongs to, applied to its route."""
    acc = _Acc(spec)
    steps = list(route.шаги)
    notes = dict(route.пометки)
    counts = dict(route.штук)
    step_seconds: dict[str, tuple[float, float]] = {}
    prefer: dict[str, str] = {}
    avoid: dict[str, str] = {}
    inputs = set(spec.inputs)
    outputs = set(spec.outputs)
    tasks = {spec.task, *spec.then_tasks}
    free = False

    # --- customer likeness: their recording, their video -----------------------
    if spec.task == "avatar" and "video" in inputs and "photo" not in inputs and "говорящий_аватар" in steps:
        if acc.prior("customer_likeness", "own_video_likeness"):
            steps = _replace_step(steps, "говорящий_аватар", "липсинк")
            notes.pop("говорящий_аватар", None)
            notes["липсинк"] = NOTE_OWN_LIPSYNC[0]
            if "audio" not in inputs:
                steps = ["клонирование_голоса", *steps]
                notes["клонирование_голоса"] = NOTE_CLONE[0]
                acc.assembly.append(ASSEMBLY_EXTRACT)
    if (
        "audio" in inputs
        and "script" in inputs
        and ("speech" in outputs or spec.task == "avatar")
        and "клонирование_голоса" not in steps
        and (set(steps) & SPEECH_CONSUMERS or "озвучка" in steps)
    ):
        if acc.prior("customer_likeness", "voice_sample_clone"):
            steps = ["клонирование_голоса", *(s for s in steps if s != "озвучка")]
            notes["клонирование_голоса"] = NOTE_CLONE[0]

    # --- one recurring host -----------------------------------------------------
    if (
        (spec.characters == 1 or len(spec.people) == 1)
        and (spec.shots or 0) >= 2
        and not inputs & {"photo", "video"}
        and "video" in outputs
        and set(steps) & {"говорящий_аватар", "оживление", "видео_по_референсу"}
    ):
        if acc.prior("single_host_series", "single_reference"):
            counts["генерация_изображения"] = SINGLE_HOST_REFERENCES
            notes.setdefault("генерация_изображения", NOTE_ONE_REFERENCE[0])

    # --- logo / wordmark ----------------------------------------------------------
    # Only where the piece is MADE (generate / animate): a logo printed on a brought
    # product (turntable of packshots) stays on the product and is not overlaid.
    if spec.task in LOGO_TASKS and "video" in outputs and any(LOGO.search(у) for у in spec.conditions):
        if (
            spec.task in (None, "generate")
            and "photo" in inputs
            and "оживление" in steps
            and acc.prior("brand_mark", "logo_image_is_endcard")
        ):
            steps = _replace_step(steps, "оживление", "генерация_видео")
            notes.pop("оживление", None)
            notes["генерация_видео"] = NOTE_ENDCARD_FOOTAGE[0]
        if acc.prior("brand_mark", "logo_overlay"):
            if spec.task == "animate":
                acc.assembly.append(ASSEMBLY_LOGO_STING)
                acc.tools.append("ffmpeg_xfade")
            else:
                acc.assembly.append(ASSEMBLY_LOGO)

    # --- foley for the customer's picture ---------------------------------------
    if "sfx" in outputs and "video" in inputs and "звук_фон" in steps:
        if acc.prior("foley_for_picture", "foley_v2a"):
            prefer["звук_фон"] = ARTEFACT_VIDEO
            notes["звук_фон"] = NOTE_V2A[0]
            acc.assembly.append(ASSEMBLY_FOLEY)

    # --- archive film ---------------------------------------------------------------
    if tasks & {"restore", "colorize"}:
        blur = any(BLUR.search(у) for у in (*spec.conditions, *spec.edit))
        if "реставрация" in steps and not blur and acc.prior("archive_restoration", "film_damage_not_blur"):
            avoid["реставрация"] = DEBLUR_MODELS
            acc.assembly.append(ASSEMBLY_FILM)
        if len(set(steps) & set(CHAIN_RANK)) >= 2:
            acc.prior("archive_restoration", "restore_colourise_upscale_order")

    # --- beat-reactive visualiser -----------------------------------------------
    if spec.task == "music-visualiser" and not any(SCENES.search(у) for у in spec.conditions):
        maker = next((s for s in steps if s in VIDEO_GENERATORS), None)
        if maker is not None and acc.prior("music_visualiser", "visualiser_loops"):
            step_seconds[maker] = (float(VISUALISER_LOOP_CLIPS * VISUALISER_LOOP_CLIP_S), float(VISUALISER_LOOP_CLIP_S))
            notes[maker] = NOTE_LOOPS[0]
            acc.assembly.append(ASSEMBLY_LOOPS)

    # --- zero budget ------------------------------------------------------------------
    # Own GPU already named — the plan is on the free route; nothing to add.
    if not spec.self_host and (
        (spec.budget_amount is not None and spec.budget_amount <= 0)
        or (spec.budget_amount is None and spec.budget_usd is not None and spec.budget_usd <= 0)
    ):
        free = acc.prior("zero_budget", "zero_budget_self_host")

    if tasks & {"restore", "colorize"} or steps != list(route.шаги):
        steps = order(steps)
    new_route = replace(route, шаги=tuple(steps), пометки=notes, штук=counts)
    return Applied(
        route=new_route,
        recipes=tuple(acc.recipes),
        priors=tuple(acc.priors),
        overridden=tuple(acc.overridden),
        tools=tuple(dict.fromkeys((*_tools_of(acc.priors), *acc.tools))),
        failures=_failures_of(acc.priors),
        step_seconds=step_seconds,
        prefer_input=prefer,
        avoid=avoid,
        assembly=tuple(dict.fromkeys(acc.assembly)),
        free_route=free,
    )


def _tools_of(priors: Sequence[str]) -> tuple[str, ...]:
    """Free tools the applied priors bring."""
    return tuple(dict.fromkeys(t for p in priors for t in PRIORS[p].tools))


def _failures_of(priors: Sequence[str]) -> tuple[str, ...]:
    """Failure modes to check for the applied priors."""
    return tuple(dict.fromkeys(f for p in priors for f in PRIORS[p].failures))


def _mp(frame: tuple[int, int]) -> float:
    return frame[0] * frame[1] / 1e6


def frame_prior(op_name: str, asked: tuple[int, int] | None, spec: "bs.Spec") -> tuple[Prior, bool] | None:
    """The class prior for a SILENT frame at a generator step: (prior, on) or None.

    Only a generator's class has a native maximum; a pass over a brought clip
    (lip sync, edit) carries its input's frame and is not judged here.
    """
    if asked is None:
        return None
    if op_name in IMAGE_GENERATORS and _mp(asked) > T2I_NATIVE_MAX_MP:
        prior = PRIORS["t2i_native_max"]
    elif op_name in VIDEO_GENERATORS and _mp(asked) > T2V_NATIVE_MAX_MP:
        prior = PRIORS["t2v_native_max"]
    else:
        return None
    return prior, enabled(spec, prior.id)


def fps_prior(op_name: str, asked: float | None, spec: "bs.Spec") -> tuple[Prior, bool] | None:
    """The class prior for a SILENT frame rate at a generator step: (prior, on) or None."""
    if not asked or op_name not in VIDEO_GENERATORS or asked <= T2V_NATIVE_FPS_MAX:
        return None
    prior = PRIORS["t2v_fps_native"]
    return prior, enabled(spec, prior.id)


def order(names: Sequence[str]) -> list[str]:
    """Order of operations: `FIRST_STEPS` in front; the chain steps re-sorted in their own slots.

    Steps outside the chain keep their places: only the slots the chain
    occupies are refilled in `CHAIN_RANK` order (stable).
    """
    first = [n for n in FIRST_STEPS if n in names]
    rest = [n for n in names if n not in first]
    slots = [i for i, n in enumerate(rest) if n in CHAIN_RANK]
    chain = sorted((rest[i] for i in slots), key=lambda n: CHAIN_RANK[n])
    for i, n in zip(slots, chain):
        rest[i] = n
    return [*first, *rest]


#: Names of endpoints that do the job a preferred-input prior asks for (searched in the registry
#: when the chosen model does not take that input).
HINT_MODELS: dict[str, str] = {"звук_фон": r"mmaudio|foley|thinksound|video-to-audio|(?:^|-)v2a(?:-|$)"}


def unmet(applied: Applied, chosen: Mapping[str, str | None], registry: object, english: bool) -> list[dict]:
    """Steps where the prior asked for a model taking an input, and the chosen one does not.

    P1: the prior is not reported as satisfied on silence — the chosen model's
    recorded inputs decide; with none recorded the row says so.
    """
    rows: list[dict] = []
    for step, artefact in applied.prefer_input.items():
        model = chosen.get(step)
        if model is None:
            continue
        node = registry.get(model)  # type: ignore[attr-defined]
        inputs = tuple(node.inputs) if node is not None else ()
        if artefact in inputs:
            continue
        pattern = HINT_MODELS.get(step, "")
        known = (
            sorted(
                n.model
                for n in registry.by_key.values()  # type: ignore[attr-defined]
                if artefact in n.inputs and re.search(pattern, n.model, re.I)
            )
            if pattern
            else []
        )
        rows.append(
            {
                "step": step,
                "model": model,
                "outcome": "fail" if inputs else "could not measure",
                "note": (
                    f"the chosen {model} "
                    + (f"takes {', '.join(inputs)}, not {artefact}" if inputs else "records no inputs")
                    + "; the recipe asks for a model that watches the footage"
                    + (
                        f"; in the base but not listed for this step by the registry: {', '.join(known)}"
                        if known
                        else ""
                    )
                    if english
                    else f"выбранная {model} "
                    + (f"принимает {', '.join(inputs)}, а не {artefact}" if inputs else "входов не записала")
                    + "; рецепт просит модель, которая смотрит ролик"
                    + (f"; в базе есть, но реестр не ставит на этот шаг: {', '.join(known)}" if known else "")
                ),
            }
        )
    return rows


def block(
    applied: Applied,
    post_priors: Sequence[str],
    post_overridden: Sequence[str],
    steps: Sequence[str],
    english: bool,
    label: Callable[[str, bool], str],
    free_route: Mapping[str, object] | None = None,
    not_met: Sequence[Mapping[str, object]] = (),
) -> dict | None:
    """The plan's `recipe` row in the answer's language; None when no recipe matched."""
    priors = list(dict.fromkeys((*applied.priors, *post_priors)))
    overridden = list(dict.fromkeys((*applied.overridden, *post_overridden)))
    recipes = list(applied.recipes)
    for p in (*post_priors, *post_overridden):
        r = next(r for r in RECIPES.values() if p in r.priors).id
        if r not in recipes:
            recipes.append(r)
    if not recipes:
        return None
    failures = list(_failures_of(priors))
    row: dict = {
        "classes": recipes,
        "priors_applied": [
            {
                "id": p,
                "says": PRIORS[p].en if english else PRIORS[p].ru,
                "tag": PRIORS[p].tag if english else TAG_RU[PRIORS[p].tag],
                "sources": [{"model": s.model, "attribute": s.attribute, "url": s.url} for s in PRIORS[p].sources],
            }
            for p in priors
        ],
        "priors_overridden": overridden,
        "tools": [
            {"name": TOOLS[t].name, "does": TOOLS[t].en if english else TOOLS[t].ru, "price": "0 usd"}
            for t in dict.fromkeys((*applied.tools, *_tools_of(post_priors)))
        ],
        "order": [{"step": s, "label": label(s, english)} for s in steps],
        "check": [
            {
                "failure": FAILURES[f].en if english else FAILURES[f].ru,
                "look": FAILURES[f].check_en if english else FAILURES[f].check_ru,
            }
            for f in failures
        ],
        "how_to_override": (
            "spec.priors={'<id>': false} switches a prior off; a fact recorded about the chosen model always "
            "wins over a prior"
            if english
            else "spec.priors={'<id>': false} выключает допущение; записанный о выбранной модели факт всегда "
            "старше допущения"
        ),
    }
    if free_route:
        row["free_route"] = dict(free_route)
    if not_met:
        row["prior_not_met"] = [dict(r) for r in not_met]
    return row


def assumption(prior_id: str, english: bool) -> str:
    """The prior as an assumption line of `understood_as`."""
    p = PRIORS[prior_id]
    if english:
        return f"prior {p.id} ({p.tag}): {p.en}; pass spec.priors={{'{p.id}': false}} to switch it off"
    return f"допущение {p.id} ({TAG_RU[p.tag]}): {p.ru}; выключить — spec.priors={{'{p.id}': false}}"


#: Route notes of the recipes, Russian -> English (`brief_spec.note_en`).
NOTES_EN: dict[str, str] = dict(
    (NOTE_CLONE, NOTE_OWN_LIPSYNC, NOTE_ENDCARD_FOOTAGE, NOTE_LOOPS, NOTE_V2A, NOTE_ONE_REFERENCE)
)
