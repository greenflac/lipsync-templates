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
    ASPECT_TOLERANCE,
    FAILURES,
    LONG_FORM_S,
    NATIVE_ASPECTS,
    NOTES,
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
#: A transparent background asked for — in `spec.conditions` or, as a delivery
#: format, in the brief's own words (the format is not a spec field: «transparent
#: background for our website» is what the customer says, and a caller filling
#: the spec has nowhere else to put it).
ALPHA = re.compile(
    r"transparen|\balpha[- ]?channel|\bwith alpha\b|\bwebm\b|prores ?4444|прозрачн|альфа-?канал", re.I
)
#: A 3D deliverable named — in `spec.conditions` or, as a delivery format, in the brief's words.
MESH = re.compile(r"\bglb\b|\bgltf\b|\busdz\b|\b3d[- ]?(?:model|mesh|asset)|\bmesh\b|3d-модел|3d модел|\bсетк", re.I)
#: The customer asks to animate the brought art itself (a visualiser, not an audiogram).
ANIMATE_ART = re.compile(r"animat|motion|move|оживи|оживл|анимир|движени", re.I)
#: Exact text named in `spec.conditions` (besides a logo): a wordmark, a headline, lettering.
TEXT_EXACT = re.compile(r"\btext\b|lettering|typograph|headline|wordmark|надпис|текст", re.I)
#: Edits of the customer's footage that are a mask and a composite (`spec.edit`).
MASK_EDITS: frozenset[str] = frozenset({"remove-object", "replace-object", "replace-sky"})
#: Speech-driven video steps: a long one is made in segments.
SPEECH_VIDEO_STEPS: frozenset[str] = frozenset({"говорящий_аватар", "липсинк"})
#: Steps that move lips on footage with several faces.
LIP_STEPS: frozenset[str] = frozenset({"липсинк"})
#: Steps whose output is speech in a language (a regional variety matters there).
SPEECH_STEPS: frozenset[str] = frozenset(
    {"озвучка", "дубляж", "клонирование_голоса", "говорящий_аватар", "видео_со_звуком"}
)
#: Steps that make a generated frame (an aspect outside the native set is a crop).
FRAME_MAKERS: frozenset[str] = IMAGE_GENERATORS | VIDEO_GENERATORS | {"оборот_360"}
#: Tasks whose deliverable carries captions burned in at assembly.
CAPTION_TASKS: frozenset[str | None] = frozenset({"cut-to-shorts", "captions"})

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
NOTE_MATTE = (
    "фон снимается в каждом кадре в альфа-канал (видео-маттинг) — на выходе прозрачность",
    "the background is removed per frame to an alpha channel (video matting) — the output is transparent",
)
NOTE_LYRICS = (
    "вокал ВАШЕГО трека расшифровывается с метками слов — по ним выравнивается текст песни",
    "the vocals of YOUR track are transcribed with word timestamps — the lyrics are aligned to them",
)
NOTE_AUDIOGRAM_CAPTIONS = (
    "расшифровка ВАШЕЙ записи с таймингами — для субтитров аудиограммы",
    "timed transcript of YOUR recording — for the audiogram's captions",
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
ASSEMBLY_ALPHA = (
    "ролик с альфа-каналом кодируется в WebM (VP9 с альфой) для сайта или ProRes 4444 для монтажа — 0 usd",
    "the matted clip is encoded with alpha: WebM (VP9 alpha) for the web or ProRes 4444 for editing — 0 usd",
)
ASSEMBLY_LYRICS = (
    "строки текста ставятся по меткам слов и анимируются типографикой (ffmpeg / After Effects) — 0 usd",
    "the lyric lines are placed on the word timestamps and animated as typography (ffmpeg / After Effects) — 0 usd",
)
ASSEMBLY_MESH_RENDER = (
    "ролик-оборот рендерится из 3D-модели (Blender) — 0 usd",
    "the turntable clip is rendered from the 3D model (Blender) — 0 usd",
)
ASSEMBLY_AUDIOGRAM = (
    "волна звука (ffmpeg showwaves) и субтитры ложатся поверх ВАШЕЙ обложки — 0 usd",
    "the waveform (ffmpeg showwaves) and the captions are laid over YOUR cover art — 0 usd",
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


def wants_alpha(spec: "bs.Spec", text: str = "") -> bool:
    """A transparent background asked for: `spec.conditions`, or the brief's own words."""
    return any(ALPHA.search(str(у)) for у in (*spec.conditions, text))


def wants_mesh(spec: "bs.Spec", text: str = "") -> bool:
    """A 3D model asked for: `spec.conditions`, or the brief's own words."""
    return any(MESH.search(str(у)) for у in (*spec.conditions, text))


def rewrite(spec: "bs.Spec", route: "bs.Маршрут", text: str = "") -> Applied:
    """Recipes of the job classes this spec belongs to, applied to its route.

    :param text: the brief's words — read ONLY for a delivery format the spec has
        no field for (a transparent background); every other decision is spec's.
    """
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

    # --- music visualiser: audiogram over brought art, lyrics -----------------------
    # Round 9. A visualiser over the customer's own cover art (an audiogram) is
    # assembly: the waveform and the captions move, the art does not — the route
    # animated the art (image-to-video, ~$2.7 for 45 s) for what ffmpeg showwaves
    # does at 0 usd. Animating the art stays one condition away.
    if (
        spec.task == "music-visualiser"
        and "photo" in inputs
        and "оживление" in steps
        and not any(ANIMATE_ART.search(у) or SCENES.search(у) for у in spec.conditions)
    ):
        if acc.prior("audiogram", "audiogram_static_art"):
            steps = [s for s in steps if s != "оживление"]
            notes.pop("оживление", None)
            if spec.language_tags and "расшифровка" not in steps:
                steps = ["расшифровка", *steps]
                notes["расшифровка"] = NOTE_AUDIOGRAM_CAPTIONS[0]
            acc.assembly.append(ASSEMBLY_AUDIOGRAM)
    # A lyric video: the customer's words (a text input) are timed to the vocals.
    if spec.task == "music-visualiser" and "script" in inputs and "audio" in inputs and "расшифровка" not in steps:
        if acc.prior("lyric_video", "lyrics_alignment"):
            steps = ["расшифровка", *steps]
            notes["расшифровка"] = NOTE_LYRICS[0]
            acc.assembly.append(ASSEMBLY_LYRICS)

    # --- 3D model of a product -----------------------------------------------------
    # Round 9: «interactive 3D model of our chair (GLB) from 6 photos» was planned
    # as a turntable VIDEO — a clip is not a mesh.
    if spec.task == "turntable" and "оборот_360" in steps and wants_mesh(spec, text):
        if acc.prior("product_3d", "mesh_reconstruction"):
            steps = _replace_step(steps, "оборот_360", "модель_3d")
            notes.pop("оборот_360", None)
            if "video" in outputs:
                acc.assembly.append(ASSEMBLY_MESH_RENDER)

    # --- transparent background ---------------------------------------------------
    # Round 9. No generator renders alpha: «transparent background for our
    # website» got one image-to-video step and an opaque MP4.
    if (
        "video" in outputs
        and wants_alpha(spec, text)
        and "удаление_фона_видео" not in steps
        and any(s in VIDEO_GENERATORS for s in steps)
    ):
        if acc.prior("alpha_delivery", "alpha_matte"):
            maker = max(i for i, s in enumerate(steps) if s in VIDEO_GENERATORS)
            steps = [*steps[: maker + 1], "удаление_фона_видео", *steps[maker + 1 :]]
            notes["удаление_фона_видео"] = NOTE_MATTE[0]
            acc.assembly.append(ASSEMBLY_ALPHA)

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


def requirement_frame(
    op_name: str, asked: tuple[int, int] | None, spec: "bs.Spec"
) -> tuple[int, int] | None:
    """The frame a generator is RANKED against when its class prior applies.

    Round-8 integration: the planner's order-requirement key ("frame native")
    asks every candidate for the ordered frame. Above the class maximum (8K
    video, 8K stills) no generator can meet it, so every candidate tied at
    "unknown" and price alone decided -- a 1080p generator beat a native-4K
    one, and the upscale step then started from 1080p. With the prior on, the
    requirement is the class maximum at the ordered aspect: the generator is
    chosen for the largest native frame, and the upscale (added by the same
    prior) covers the rest. Prior off, or the frame within the class: the
    ordered frame, unchanged.
    """
    found = frame_prior(op_name, asked, spec)
    if asked is None or found is None or not found[1]:
        return asked
    cap = T2I_NATIVE_MAX_MP if found[0].id == "t2i_native_max" else T2V_NATIVE_MAX_MP
    k = (cap / _mp(asked)) ** 0.5
    # Snap to a multiple of 8, the way real frames are sized: T2V_NATIVE_MAX_MP
    # is a rounded megapixel figure, and 8K scaled by it came out 3841x2160 —
    # one pixel wider than 4K, so every native-4K generator read as "below".
    return (int(round(asked[0] * k / 8)) * 8, int(round(asked[1] * k / 8)) * 8)


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
    (
        NOTE_CLONE,
        NOTE_OWN_LIPSYNC,
        NOTE_ENDCARD_FOOTAGE,
        NOTE_LOOPS,
        NOTE_V2A,
        NOTE_ONE_REFERENCE,
        NOTE_MATTE,
        NOTE_LYRICS,
        NOTE_AUDIOGRAM_CAPTIONS,
    )
)


# --- production notes (round 9) --------------------------------------------------------


def _ratio(aspect: str | None) -> float | None:
    """W:H as a number: «2.39:1» -> 2.39, «16:9» -> 1.78; None when unreadable."""
    m = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*[:x/]\s*(\d+(?:\.\d+)?)\s*", str(aspect or ""))
    if not m or float(m.group(2)) == 0:
        return None
    return float(m.group(1)) / float(m.group(2))


def native_aspect(aspect: str | None) -> bool | None:
    """Is the ordered aspect one a generator renders natively? None — no aspect or unreadable."""
    r = _ratio(aspect)
    if r is None:
        return None
    return any(abs(r - n) / n <= ASPECT_TOLERANCE for n in NATIVE_ASPECTS)


def _photo_count(spec: "bs.Spec") -> int:
    """How many images the customer brought (an image input without a count is one)."""
    return sum(int(з.get("count") or 1) for з in spec.input_items if з.get("kind") == "photo")


def _speakers(spec: "bs.Spec") -> int:
    return max(len(spec.people), spec.characters or 0)


def _regional_tags(spec: "bs.Spec") -> list[str]:
    """Language tags that name a region (`ar-EG`, `pt-BR`, `es-419`): a variety, not only a language."""
    out = []
    for тег in spec.language_tags:
        части = str(тег).split("-")
        if len(части) >= 2 and re.fullmatch(r"[A-Za-z]{2}|\d{3}", части[1]):
            out.append(str(тег))
    return out


def note_ids(
    spec: "bs.Spec",
    steps: Sequence[str],
    *,
    text: str = "",
    applied: "Applied | None" = None,
) -> list[tuple[str, dict[str, str]]]:
    """Which production notes this plan carries, with the fields of their wording.

    One rule per job class or condition — never per brief. `steps` are the plan's
    final operation names (an assembly-only plan has none).
    """
    names = set(steps)
    inputs = set(spec.inputs)
    outputs = set(spec.outputs)
    priors = set(applied.priors) if applied is not None else set()
    seconds = spec.duration_s or bs.source_seconds(spec)
    out: list[tuple[str, dict[str, str]]] = []
    if "музыка" in names:
        out.append(("music_licence", {}))
    if spec.open_weights or spec.self_host:
        out.append(("weights_licence", {}))
    if any(з.get("kind") == "audio" and з.get("owned") is False for з in spec.input_items):
        out.append(("song_rights", {}))
    if names & SPEECH_VIDEO_STEPS and seconds and seconds > LONG_FORM_S:
        out.append(("long_form_segmented", {"seconds": f"{seconds:g}"}))
    if set(spec.edit) & MASK_EDITS:
        out.append(("mask_composite", {}))
    if "reframe" in spec.edit:
        out.append(("crop_track", {"aspect": str(spec.aspect or "")}))
    if names & FRAME_MAKERS and native_aspect(spec.aspect) is False:
        r = _ratio(spec.aspect) or 1.0
        out.append(("aspect_crop", {"aspect": str(spec.aspect), "native": "16:9" if r >= 1 else "9:16"}))
    if "EU" in spec.jurisdiction and names:
        out.append(("ai_act_label", {}))
    if names & LIP_STEPS and _speakers(spec) >= 2:
        out.append(("multi_speaker", {"speakers": str(_speakers(spec))}))
    if (
        any(LOGO.search(у) or TEXT_EXACT.search(у) for у in spec.conditions)
        and not priors & {"logo_overlay", "logo_image_is_endcard"}
    ):
        out.append(("logo_text_composited", {}))
    if "оборот_360" in names and _photo_count(spec) <= 1:
        out.append(("unseen_side", {}))
    if spec.task in CAPTION_TASKS and ("text" in outputs or spec.task == "captions"):
        out.append(("captions_burned", {}))
    if names & SPEECH_STEPS and (теги := _regional_tags(spec)):
        out.append(("regional_variety", {"tags": ", ".join(теги)}))
    if "lyrics_alignment" in priors:
        out.append(("lyric_alignment", {}))
    if "alpha_matte" in priors or ("video" in outputs and wants_alpha(spec, text)):
        out.append(("alpha_delivery", {}))
    if applied is not None and applied.free_route:
        out.append(("self_host_route", {}))
    if "audiogram_static_art" in priors:
        out.append(("waveform_layer", {}))
    if "модель_3d" in names:
        out.append(("mesh_route", {}))
    return out


def notes(
    spec: "bs.Spec",
    steps: Sequence[str],
    english: bool,
    *,
    text: str = "",
    applied: "Applied | None" = None,
) -> list[dict]:
    """The plan's `production_notes` rows in the answer's language."""
    rows: list[dict] = []
    for nid, fields in note_ids(spec, steps, text=text, applied=applied):
        n = NOTES[nid]
        if "aspect" in fields and not fields["aspect"]:
            fields = {**fields, "aspect": "the new aspect" if english else "новый формат"}
        rows.append(
            {
                "id": nid,
                "says": (n.en if english else n.ru).format(**fields),
                "tag": n.tag if english else TAG_RU[n.tag],
                "sources": [{"model": s.model, "attribute": s.attribute, "url": s.url} for s in n.sources],
            }
        )
    return rows
