"""Recipe table: one recipe per job class, with the engineering priors a senior
GenAI engineer applies before looking at any single endpoint.

WHY (round 8). The fact base holds VENDOR facts per endpoint; the planner read
the base's silence as neutral: «60 fps asked, the base records no frame rate
for wan-3.0-t2v — not added on silence», «8K still: no upscale step added — the
base's silence is no reason to pay». An engineer does not read silence as
neutral when the class has a known shape: no text-to-image model renders 8K
natively, text-to-video ships at 24–30 fps, generated wordmarks misspell. The
recipe layer holds those class-level priors, each with its sources (rows of
this base that support it) or the explicit tag `engineering prior`, and the
planner applies them ONLY where the base is silent — a recorded fact about the
chosen model always wins — and states every applied prior as an assumption the
caller can switch off with `spec.priors = {"<id>": false}`.

This module is DATA only (no imports from the planner), so `brief_spec` can
validate `spec.priors` against `PRIORS` without an import cycle. The logic that
applies it lives in `studio/recipes/apply.py`.

DECISION CONSTANTS (T1: mutated both ways by `scripts/mutate_recipes.py`):
`T2I_NATIVE_MAX_MP`, `T2V_NATIVE_MAX_MP`, `T2V_NATIVE_FPS_MAX`,
`VISUALISER_LOOP_CLIPS`, `VISUALISER_LOOP_CLIP_S`, `SINGLE_HOST_REFERENCES`.
"""

from __future__ import annotations

from dataclasses import dataclass

#: Tag of a prior that rests on practice, not on a row of this base.
TAG_ENGINEERING = "engineering prior"
#: Tag of a prior generalised from recorded rows of this base (cited in `sources`).
TAG_BASE_ROWS = "class prior from base rows"
#: The tags in Russian (a Russian answer carries no English three-word phrase).
TAG_RU: dict[str, str] = {
    TAG_ENGINEERING: "инженерное допущение",
    TAG_BASE_ROWS: "допущение класса по строкам базы",
}

# --- decision constants ---------------------------------------------------------

#: Largest still a text-to-image model renders natively, in megapixels: 4096x4096
#: (`seedream-4.0` up to 4096x4096, `gpt-image-2` 3840:2160, `flux-2` 4 MP,
#: `gen4_image` 1920:1080 in this base). 8K (7680x4320 = 33.2 MP) is above it -> upscale last.
T2I_NATIVE_MAX_MP = 16.8
#: Largest frame a video generator renders natively, megapixels: 3840x2160 (4K
#: tiers: `kling-3.0-4k`, `veo-3.1` "4k"). 8K video is above it -> upscale last.
T2V_NATIVE_MAX_MP = 8.3
#: Highest frame rate a video generator ships at (24 measured on Kling 3.0,
#: 24 on Wan 2.2 and MiniMax H3, 30 fixed on Wan 2.7). Above it -> interpolate.
T2V_NATIVE_FPS_MAX = 30
#: Beat-reactive visualiser: how many short loopable clips are generated, and
#: how long each is. The track's length is reached by looping and cutting on
#: beats at assembly, not by minutes of text-to-video.
VISUALISER_LOOP_CLIPS = 4
VISUALISER_LOOP_CLIP_S = 8
#: One recurring host across N shorts: how many reference images are made.
SINGLE_HOST_REFERENCES = 1


@dataclass(frozen=True)
class Source:
    """A row of this base that supports a class prior (model, attribute, url, what it says)."""

    model: str
    attribute: str
    url: str
    says: str


@dataclass(frozen=True)
class Prior:
    id: str
    en: str
    ru: str
    tag: str
    sources: tuple[Source, ...] = ()
    #: Free tools the prior brings into the plan (`TOOLS` ids).
    tools: tuple[str, ...] = ()
    #: Failure modes to check when the prior is applied (`FAILURES` ids).
    failures: tuple[str, ...] = ()


@dataclass(frozen=True)
class Tool:
    """Free, deterministic tool (0 usd, not a model)."""

    id: str
    name: str
    en: str
    ru: str


@dataclass(frozen=True)
class Failure:
    """Known failure mode of the class and what to check on the output."""

    id: str
    en: str
    ru: str
    check_en: str
    check_ru: str


@dataclass(frozen=True)
class RecipeStep:
    """One step of the decomposition: a planner operation or a free tool, and when it is used."""

    what: str
    kind: str  # "model" | "tool"
    when: str


@dataclass(frozen=True)
class Recipe:
    id: str
    title: str
    steps: tuple[RecipeStep, ...]
    priors: tuple[str, ...]
    tools: tuple[str, ...]
    failures: tuple[str, ...]


# --- priors ---------------------------------------------------------------------

_FAL_OPENAPI = "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id="

PRIORS_LIST: tuple[Prior, ...] = (
    Prior(
        "t2i_native_max",
        "text-to-image models render natively up to about 2K-4K (4096x4096 at most); none renders 8K "
        "natively, so the still is generated at native size and upscaled as the LAST step",
        "модели «текст -> картинка» рисуют родным кадром до 2K-4K (не больше 4096x4096); 8K не рисует ни "
        "одна, поэтому кадр генерируется в родном размере и поднимается апскейлом ПОСЛЕДНИМ шагом",
        TAG_BASE_ROWS,
        (
            Source(
                "seedream-4.0",
                "max_resolution",
                _FAL_OPENAPI + "fal-ai/bytedance/seedream/v4/text-to-image",
                "total pixels up to 4096x4096",
            ),
            Source("gpt-image-2", "max_resolution", "https://docs.dev.runwayml.com/openapi.json", "3840:2160"),
            Source("flux-2", "max_resolution", "https://docs.bfl.ai/release-notes.md", "up to 4MP output"),
            Source("gen4_image", "max_resolution", "https://docs.dev.runwayml.com/openapi.json", "1920:1080"),
        ),
    ),
    Prior(
        "t2v_native_max",
        "video generators render natively up to 4K (3840x2160) at most; a larger frame is reached by an "
        "upscale step after generation",
        "видеогенераторы рисуют родным кадром не больше 4K (3840x2160); кадр крупнее даёт апскейл после генерации",
        TAG_BASE_ROWS,
        (Source("veo-3.1-i2v", "resolution_enum", _FAL_OPENAPI + "fal-ai/veo3.1/image-to-video", "720p, 1080p, 4k"),),
    ),
    Prior(
        "t2v_fps_native",
        "video generators ship at 24-30 fps; 50/60/120 fps is reached by frame interpolation (RIFE / FILM) "
        "after generation, not by the generator",
        "видеогенераторы отдают 24-30 fps; 50/60/120 fps даёт интерполяция кадров (RIFE / FILM) после "
        "генерации, а не сам генератор",
        TAG_BASE_ROWS,
        (
            Source(
                "kling-3.0",
                "fps",
                "https://storage.googleapis.com/falserverless/example_outputs/kling-v3/standard-t2v/out.mp4",
                "24 fps measured",
            ),
            Source("wan-2.2-t2v-a14b", "fps", "https://huggingface.co/Wan-AI/Wan2.2-T2V-A14B-Diffusers", "24"),
            Source("minimax-h3", "fps", "https://huggingface.co/MiniMaxAI/MiniMax-H3", "24"),
            Source("wan-2.7-i2v", "frame_rate", "https://help.aliyun.com/zh/model-studio/video-generation", "30fps fixed"),
        ),
    ),
    Prior(
        "logo_overlay",
        "generated letters misspell and warp: the customer's logo / wordmark is composited from their own "
        "file as an overlay or end card at assembly (ffmpeg overlay), and the generated footage carries no text",
        "сгенерированные буквы путаются и плывут: логотип заказчика накладывается из ЕГО файла оверлеем или "
        "финальной карточкой при сборке (ffmpeg overlay), а в генерируемом видео текста нет",
        TAG_ENGINEERING,
    ),
    Prior(
        "logo_image_is_endcard",
        "the image you bring with a legible-logo condition is taken as the LOGO: it is composited as the end "
        "card, not animated; the ad footage is generated without text",
        "снимок, принесённый с условием «логотип читается», принят за ЛОГОТИП: он ложится финальной карточкой, "
        "а не оживляется; рекламные кадры генерируются без текста",
        TAG_ENGINEERING,
    ),
    Prior(
        "foley_v2a",
        "foley for an existing picture is video-to-audio (MMAudio, HunyuanVideo-Foley, ThinkSound): the model "
        "watches YOUR footage and lands steps and creaks on the frames; text-to-sound-effects does not see the "
        "picture and needs every hit spotted by hand",
        "шумы под готовую картинку — это «видео -> звук» (MMAudio, HunyuanVideo-Foley, ThinkSound): модель "
        "смотрит ВАШ ролик и попадает шагами и скрипом в кадры; «текст -> эффект» картинки не видит, и каждый "
        "удар расставляется руками",
        TAG_ENGINEERING,
    ),
    Prior(
        "film_damage_not_blur",
        "archive film damage (scratches, dust, flicker, grain) is removed by dust/scratch removal, deflicker "
        "and temporal denoise; a deblur/sharpen model is the wrong tool and sharpens the scratches",
        "повреждения плёнки (царапины, пыль, мерцание, зерно) снимают удаление пыли и царапин, дефликер и "
        "временной шумодав; модель «deblur / резкость» — не тот инструмент: она делает царапины резче",
        TAG_ENGINEERING,
    ),
    Prior(
        "restore_colourise_upscale_order",
        "order of operations: restore -> colourise -> upscale -> interpolate; restoration and colourisation run "
        "at SOURCE resolution (cheaper, and colour models are trained at <=1080p), the upscale comes after them",
        "порядок работ: реставрация -> раскраска -> апскейл -> интерполяция; реставрация и раскраска идут в "
        "кадре ИСХОДНИКА (дешевле, и модели цвета учены на <=1080p), апскейл — после них",
        TAG_ENGINEERING,
    ),
    Prior(
        "visualiser_loops",
        f"a beat-reactive visualiser is made at assembly: the track's beats (librosa / aubio) drive cuts and "
        f"pulses over {VISUALISER_LOOP_CLIPS} short loopable generated clips of {VISUALISER_LOOP_CLIP_S} s, "
        "looped to the track's length — not minutes of text-to-video, which does not hear the track anyway",
        f"визуализатор «в такт» собирается при сборке: доли трека (librosa / aubio) ведут склейки и пульсацию "
        f"поверх {VISUALISER_LOOP_CLIPS} коротких зацикленных клипов по {VISUALISER_LOOP_CLIP_S} с, повторённых "
        "на длину трека — а не минуты t2v, которое трек всё равно не слышит",
        TAG_ENGINEERING,
    ),
    Prior(
        "zero_budget_self_host",
        "a 0 budget excludes every hosted API (all bill per call): the free route is open weights on your own "
        "or a free GPU, plus free tools; it costs hardware and time instead of money",
        "бюджет 0 исключает любой платный API (каждый берёт за вызов): бесплатный путь — открытые веса на "
        "своём или бесплатном GPU и бесплатные инструменты; платите железом и временем, а не деньгами",
        TAG_ENGINEERING,
    ),
    Prior(
        "voice_sample_clone",
        "your recording plus a text is a voice SAMPLE: the text is read in that voice (voice cloning), and the "
        "cloned speech drives the picture — the recording itself is not the soundtrack",
        "ваша запись вместе с текстом — это ОБРАЗЕЦ голоса: текст читается этим голосом (клонирование), и "
        "клонированная речь ведёт картинку — сама запись дорожкой не становится",
        TAG_ENGINEERING,
    ),
    Prior(
        "own_video_likeness",
        "you bring a video of the person: their own footage is lip-synced to the new speech (avatar from their "
        "video), and their voice is cloned from the same recording — no new face is generated and no stock voice "
        "is used",
        "вы принесли видео человека: губы двигаются на ЕГО видео под новую речь (аватар из его записи), а голос "
        "клонируется из той же записи — нового лица не генерируется и стокового голоса нет",
        TAG_ENGINEERING,
    ),
    Prior(
        "single_reference",
        f"one recurring host = {SINGLE_HOST_REFERENCES} reference image reused by every short, not one "
        "independent image per short (the face would drift between them)",
        f"один и тот же ведущий = {SINGLE_HOST_REFERENCES} референс на все ролики, а не своя картинка на "
        "каждый (лицо разъезжалось бы между ними)",
        TAG_ENGINEERING,
    ),
)

#: Tools and failure checks each prior brings (kept apart from the wording above).
_PRIOR_TOOLS_FAILURES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "t2i_native_max": ((), ("upscale_hallucination",)),
    "t2v_native_max": ((), ("upscale_hallucination",)),
    "t2v_fps_native": ((), ("interpolation_ghosting",)),
    "logo_overlay": (("ffmpeg_overlay",), ("misspelled_wordmark",)),
    "logo_image_is_endcard": (("ffmpeg_overlay",), ("misspelled_wordmark",)),
    "foley_v2a": (("ffmpeg_amix", "loudnorm"), ("foley_off_sync",)),
    "film_damage_not_blur": (("deflicker", "descratch"), ("restore_smears_detail",)),
    "restore_colourise_upscale_order": ((), ("colour_flicker", "upscale_hallucination")),
    "visualiser_loops": (("beat_track", "ffmpeg_concat", "showwaves"), ("loop_seam",)),
    "zero_budget_self_host": ((), ("self_host_vram",)),
    "voice_sample_clone": ((), ("clone_accent",)),
    "own_video_likeness": (("extract_audio",), ("clone_accent", "own_footage_occlusion")),
    "single_reference": ((), ("reference_drift",)),
}
PRIORS_LIST = tuple(
    Prior(п.id, п.en, п.ru, п.tag, п.sources, *_PRIOR_TOOLS_FAILURES[п.id]) for п in PRIORS_LIST
)
PRIORS: dict[str, Prior] = {п.id: п for п in PRIORS_LIST}

# --- free tools -------------------------------------------------------------------

TOOLS_LIST: tuple[Tool, ...] = (
    Tool("ffmpeg_overlay", "ffmpeg overlay", "composite the customer's logo / end card over the last frames",
         "наложить логотип / финальную карточку заказчика на последние кадры"),
    Tool("ffmpeg_xfade", "ffmpeg xfade", "crossfade the generated motion into the true logo for the final hold",
         "перетечь из сгенерированного движения в настоящий логотип на финальной паузе"),
    Tool("vidstab", "ffmpeg vidstab", "stabilise footage before any model step", "стабилизация до шагов-моделей"),
    Tool("ffmpeg_concat", "ffmpeg concat", "join clips / loop a clip to the track's length",
         "склеить клипы / зациклить клип на длину трека"),
    Tool("captions_burn", "ffmpeg subtitles", "burn captions from the timed transcript",
         "вжечь субтитры по расшифровке с таймингами"),
    Tool("loudnorm", "ffmpeg loudnorm", "normalise the final mix loudness (EBU R128)",
         "выровнять громкость финального сведения (EBU R128)"),
    Tool("ffmpeg_amix", "ffmpeg amix", "mix the foley under the original sound", "свести шумы под исходный звук"),
    Tool("beat_track", "librosa / aubio", "find beats and onsets of the track to drive cuts and pulses",
         "найти доли и атаки трека, чтобы вести склейки и пульсацию"),
    Tool("showwaves", "ffmpeg showwaves / showspectrum", "waveform or spectrum layer that truly follows the audio",
         "слой волны или спектра, который действительно следует звуку"),
    Tool("deflicker", "ffmpeg deflicker", "remove exposure flicker of archive film", "снять мерцание экспозиции старой плёнки"),
    Tool("descratch", "VapourSynth DeScratch / RemoveDirt", "remove dust and vertical scratches frame by frame",
         "убрать пыль и вертикальные царапины по кадрам"),
    Tool("extract_audio", "ffmpeg -vn", "take the voice sample out of the customer's video",
         "вынуть образец голоса из видео заказчика"),
)

TOOLS: dict[str, Tool] = {т.id: т for т in TOOLS_LIST}

# --- failure modes ----------------------------------------------------------------

FAILURES_LIST: tuple[Failure, ...] = (
    Failure("upscale_hallucination", "generative upscalers invent texture (waxy skin, fake foliage detail)",
            "генеративный апскейл выдумывает фактуру (восковая кожа, лишние детали листвы)",
            "compare a 100% crop against the native render", "сравнить кроп 100% с родным кадром"),
    Failure("interpolation_ghosting", "interpolation ghosts and warps on fast motion and occlusions",
            "интерполяция двоит и гнёт быстрые движения и перекрытия",
            "step through the fastest second frame by frame", "пройти по кадрам самую быструю секунду"),
    Failure("misspelled_wordmark", "generated wordmark misspelled or warped", "сгенерированный логотип с ошибкой или поплыл",
            "final frame shows the customer's own logo file, letter for letter",
            "в финальном кадре — файл логотипа заказчика, буква в букву"),
    Failure("foley_off_sync", "foley hits land off the visible contact", "удар шума не попадает в видимое касание",
            "check footsteps and door against the frames they belong to", "сверить шаги и дверь с их кадрами"),
    Failure("restore_smears_detail", "restoration smears faces and fine detail along with the grain",
            "реставрация смазывает лица и мелкие детали вместе с зерном",
            "compare faces before / after on a still", "сравнить лица до / после на стоп-кадре"),
    Failure("colour_flicker", "colourisation flickers between frames and shots", "цвет мерцает между кадрами и планами",
            "watch a static shot for hue drift", "смотреть статичный план на дрейф оттенка"),
    Failure("loop_seam", "visible seam where the clip loops", "виден шов там, где клип зацикливается",
            "watch the loop point at full speed", "посмотреть точку петли на скорости"),
    Failure("clone_accent", "a cloned voice speaking another language carries accent or loses timbre",
            "клон голоса на другом языке несёт акцент или теряет тембр",
            "native listener checks the new-language line", "носитель слушает фразу на новом языке"),
    Failure("own_footage_occlusion", "lip sync breaks where the face turns away or a hand covers the mouth",
            "липсинк ломается, где лицо отвёрнуто или рот закрыт рукой",
            "pick a frontal stretch of the recording", "взять фронтальный отрезок записи"),
    Failure("reference_drift", "the host's face drifts between shorts", "лицо ведущего разъезжается между роликами",
            "same reference file on every short", "один и тот же файл референса на каждом ролике"),
    Failure("self_host_vram", "open weights do not fit the free GPU", "открытые веса не помещаются в бесплатный GPU",
            "check VRAM of the weights against the card", "сверить память весов с картой"),
)

FAILURES: dict[str, Failure] = {ф.id: ф for ф in FAILURES_LIST}

# --- recipes (one per job class) --------------------------------------------------

RECIPES_LIST: tuple[Recipe, ...] = (
    Recipe(
        "still_image",
        "text-to-image still",
        (
            RecipeStep("генерация_изображения", "model", "always, at the model's native size"),
            RecipeStep("апскейл_изображения", "model", f"asked frame > {T2I_NATIVE_MAX_MP} MP and the base is silent"),
        ),
        ("t2i_native_max",),
        (),
        ("upscale_hallucination",),
    ),
    Recipe(
        "generated_clip",
        "generated video clip",
        (
            RecipeStep("генерация_видео", "model", "always (or оживление from a brought image)"),
            RecipeStep("апскейл", "model", f"asked frame > {T2V_NATIVE_MAX_MP} MP and the base is silent"),
            RecipeStep("интерполяция_кадров", "model", f"asked fps > {T2V_NATIVE_FPS_MAX} and the base is silent; last"),
        ),
        ("t2v_native_max", "t2v_fps_native"),
        (),
        ("upscale_hallucination", "interpolation_ghosting"),
    ),
    Recipe(
        "brand_mark",
        "logo / legible text in a generated piece",
        (
            RecipeStep("генерация_видео", "model", "ad footage without text, when the brought image is the logo"),
            RecipeStep("ffmpeg_overlay", "tool", "always: the logo comes from the customer's file"),
            RecipeStep("ffmpeg_xfade", "tool", "animated logo sting: crossfade into the true logo"),
        ),
        ("logo_overlay", "logo_image_is_endcard"),
        ("ffmpeg_overlay", "ffmpeg_xfade"),
        ("misspelled_wordmark",),
    ),
    Recipe(
        "foley_for_picture",
        "sound effects / foley for the customer's video",
        (
            RecipeStep("звук_фон", "model", "video-to-audio over YOUR footage"),
            RecipeStep("ffmpeg_amix", "tool", "mix under the original sound"),
            RecipeStep("loudnorm", "tool", "final loudness"),
        ),
        ("foley_v2a",),
        ("ffmpeg_amix", "loudnorm"),
        ("foley_off_sync",),
    ),
    Recipe(
        "archive_restoration",
        "archive film restoration / colourisation",
        (
            RecipeStep("deflicker", "tool", "flicker named or archive film"),
            RecipeStep("descratch", "tool", "scratches / dust"),
            RecipeStep("реставрация", "model", "temporal denoise / restore at source resolution"),
            RecipeStep("раскраска", "model", "colourise asked: after restoration, at source resolution"),
            RecipeStep("апскейл", "model", "asked frame above the source: after colourisation"),
            RecipeStep("интерполяция_кадров", "model", "asked fps above the source: last"),
        ),
        ("film_damage_not_blur", "restore_colourise_upscale_order"),
        ("deflicker", "descratch"),
        ("restore_smears_detail", "colour_flicker", "upscale_hallucination"),
    ),
    Recipe(
        "music_visualiser",
        "beat-reactive music visualiser",
        (
            RecipeStep("генерация_видео", "model", f"{VISUALISER_LOOP_CLIPS} loopable clips x {VISUALISER_LOOP_CLIP_S} s"),
            RecipeStep("beat_track", "tool", "beats of YOUR track"),
            RecipeStep("ffmpeg_concat", "tool", "loop and cut on beats to the track's length"),
            RecipeStep("showwaves", "tool", "optional waveform / spectrum layer"),
        ),
        ("visualiser_loops",),
        ("beat_track", "ffmpeg_concat", "showwaves"),
        ("loop_seam",),
    ),
    Recipe(
        "zero_budget",
        "no money at all",
        (RecipeStep("self-host", "tool", "open weights on your own / a free GPU"),),
        ("zero_budget_self_host",),
        (),
        ("self_host_vram",),
    ),
    Recipe(
        "customer_likeness",
        "the customer's own person: their video / photo / voice",
        (
            RecipeStep("extract_audio", "tool", "voice sample from their video"),
            RecipeStep("клонирование_голоса", "model", "their recording + a text: read the text in their voice"),
            RecipeStep("липсинк", "model", "their video: lips moved on their own footage"),
            RecipeStep("говорящий_аватар", "model", "their photo: the photo speaks"),
        ),
        ("voice_sample_clone", "own_video_likeness"),
        ("extract_audio",),
        ("clone_accent", "own_footage_occlusion"),
    ),
    Recipe(
        "single_host_series",
        "one recurring host across several shorts",
        (
            RecipeStep("генерация_изображения", "model", f"{SINGLE_HOST_REFERENCES} reference of the host"),
            RecipeStep("говорящий_аватар", "model", "every short from that one reference"),
        ),
        ("single_reference",),
        (),
        ("reference_drift",),
    ),
)

RECIPES: dict[str, Recipe] = {р.id: р for р in RECIPES_LIST}
