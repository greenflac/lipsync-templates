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
#: Tag of a production note that rests on a law or regulation (cited in `sources`).
TAG_REGULATION = "regulation"
#: Tag of a production note that rests on a platform's or a delivery outlet's published
#: terms (a loudness spec, a disclosure setting, a vendor's use policy).
TAG_PLATFORM = "platform policy"
#: The tags in Russian (a Russian answer carries no English three-word phrase).
TAG_RU: dict[str, str] = {
    TAG_ENGINEERING: "инженерное допущение",
    TAG_BASE_ROWS: "допущение класса по строкам базы",
    TAG_REGULATION: "норма права",
    TAG_PLATFORM: "правило площадки",
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
#: Round 13: one loop clip serves every ordered version and length (a loop is a
#: SHARED ASSET): when the loop's own length is not named, it is this many seconds
#: (the visualiser's loop clip — one run of a generator).
LOOP_CLIP_S = VISUALISER_LOOP_CLIP_S
#: One recurring host across N shorts: how many reference images are made.
SINGLE_HOST_REFERENCES = 1
#: Speech-driven video (talking avatar, lip sync) longer than this many seconds
#: is made in segments and joined at assembly: avatar and lip-sync endpoints cap
#: one run at seconds to a few minutes (engineering prior; a recorded run limit
#: of the chosen model is printed per step and wins).
LONG_FORM_S = 180
#: Frame aspects video and image generators offer natively (W:H as a ratio).
#: Any other ordered aspect (2.39:1, 1.85:1, 4:1 banners) is generated at the
#: nearest native one and cropped or letterboxed at assembly.
NATIVE_ASPECTS: tuple[float, ...] = (16 / 9, 9 / 16, 1.0, 4 / 3, 3 / 4, 3 / 2, 2 / 3, 4 / 5, 5 / 4, 21 / 9, 9 / 21)
#: How far (relative) an ordered aspect may be from a native one and still count as it.
ASPECT_TOLERANCE = 0.02


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
        "looped to the track's length — not minutes of text-to-video, which does not hear the track anyway "
        "(a music video of distinct scenes: name 'scenes' in conditions)",
        f"визуализатор «в такт» собирается при сборке: доли трека (librosa / aubio) ведут склейки и пульсацию "
        f"поверх {VISUALISER_LOOP_CLIPS} коротких зацикленных клипов по {VISUALISER_LOOP_CLIP_S} с, повторённых "
        "на длину трека — а не минуты t2v, которое трек всё равно не слышит "
        "(клип из разных сцен: «сцены» в conditions)",
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
    Prior(
        "alpha_matte",
        "a transparent background is not something a generator renders: the clip is generated on a plain "
        "background and the background is removed per frame (video matting) to an alpha channel",
        "прозрачный фон генератор не рисует: ролик генерируется на ровном фоне, а фон снимается в каждом кадре "
        "(видео-маттинг) в альфа-канал",
        TAG_ENGINEERING,
    ),
    Prior(
        "lyrics_alignment",
        "a lyric video needs the time of every sung word: the vocals are transcribed with word timestamps and "
        "YOUR lyrics are aligned to them (forced alignment) before the typography is animated",
        "клипу со словами нужно время каждого спетого слова: вокал расшифровывается с метками слов, и ВАШ текст "
        "выравнивается по ним до анимации типографики",
        TAG_ENGINEERING,
    ),
    Prior(
        "mesh_reconstruction",
        "a 3D model (GLB / USDZ / mesh) is an image-to-3D reconstruction from YOUR photos, not a turntable video; "
        "a turntable clip, if wanted, is rendered from the mesh at assembly",
        "3D-модель (GLB / USDZ / сетка) — это реконструкция по ВАШИМ снимкам (image-to-3D), а не видео-оборот; "
        "ролик-оборот, если нужен, рендерится из модели при сборке",
        TAG_ENGINEERING,
    ),
    Prior(
        "audiogram_static_art",
        "an audiogram over YOUR cover art is assembly: the art stays still, the waveform (ffmpeg showwaves) and "
        "the captions move — animating the art is not needed (name 'animate' in conditions to animate it)",
        "аудиограмма поверх ВАШЕЙ обложки — это сборка: обложка неподвижна, движутся волна (ffmpeg showwaves) и "
        "субтитры — оживлять обложку не нужно (чтобы оживить, назовите 'animate' в conditions)",
        TAG_ENGINEERING,
    ),
    Prior(
        "whole_character_replace",
        "a mascot, costumed or cartoon character in place of a person replaces the whole figure (silhouette, body, "
        "motion) from the character reference — a whole-character replacement model (Wan Animate replace class), "
        "not a face swap, which only moves a human face",
        "маскот, ростовая кукла или мультперсонаж вместо человека — замена всей фигуры (силуэт, тело, движение) "
        "по референсу персонажа моделью замены персонажа (класс Wan Animate replace), а не замена лица, которая "
        "переносит только человеческое лицо",
        TAG_BASE_ROWS,
        (
            Source(
                "wan-animate-replace",
                "architecture",
                "https://fal.ai/models/fal-ai/wan/v2.2-14b/animate/replace/api",
                "replaces the character in a reference video, keeping the scene",
            ),
        ),
    ),
    Prior(
        "virtual_try_on",
        "a garment from the customer's product photo worn by a model that does not exist yet: text-to-image makes "
        "the model photo, then a virtual try-on (person image + garment image) puts the garment on it",
        "вещь с фото товара на модели, которой ещё нет: «текст -> картинка» делает снимок модели, затем "
        "виртуальная примерка (снимок человека + снимок вещи) надевает вещь",
        TAG_BASE_ROWS,
        (
            Source(
                "kolors-virtual-try-on",
                "requires_inputs",
                _FAL_OPENAPI + "fal-ai/kling/v1-5/kolors-virtual-try-on",
                "human_image_url and garment_image_url required",
            ),
        ),
    ),
    Prior(
        "print_upscale",
        "a print needs its trim size in pixels at print DPI; where the base does not record the chosen "
        "generator's largest frame, it is taken as about 2048x2048 (4 MP), so a larger print frame gets an "
        "upscale as the LAST step",
        "печати нужен формат в пикселях при печатном DPI; где база не записала наибольший кадр выбранного "
        "генератора, он принят около 2048x2048 (4 Мп), поэтому кадр печати крупнее получает апскейл ПОСЛЕДНИМ "
        "шагом",
        TAG_ENGINEERING,
    ),
)

PRIORS_LIST = (
    *PRIORS_LIST,
    Prior(
        "walkthrough_camera_path",
        "a walkthrough or tour of a place from YOUR photos is a camera path: one image-to-video camera move per "
        "photo (push-in, dolly, pan), joined in walking order — not motion transfer, which copies a performer from "
        "a driving video; with many overlapping photos a 3D gaussian splat fly-through is the alternative",
        "проход или тур по месту из ВАШИХ снимков — это путь камеры: одно движение камеры image-to-video на снимок "
        "(наезд, проезд, панорама), склейка в порядке прохода — а не перенос движения, который повторяет "
        "исполнителя из ведущего видео; при многих перекрывающихся снимках альтернатива — облёт по 3D gaussian splat",
        TAG_ENGINEERING,
    ),
    Prior(
        "drawn_stylised_lipsync",
        "dubbing drawn footage (anime, cartoon) keeps lip sync, on a model that records support for drawn / "
        "stylised 2D faces (photoreal-only models miss drawn mouths or smear the line art); test 5 s first, and "
        "re-time the mouth flaps in the animation project (Rhubarb Lip Sync, Toon Boom / Character Animator auto "
        "lip-sync) where the model fails",
        "дубляж рисованного ролика (аниме, мультфильм) сохраняет липсинк — на модели, у которой записана поддержка "
        "рисованных / стилизованных 2D-лиц (модели только для фотореализма не находят нарисованный рот или "
        "размазывают линии); сначала проверьте 5 с, а там, где модель не справляется, рты переставляются в проекте "
        "анимации (Rhubarb Lip Sync, автолипсинк Toon Boom / Character Animator)",
        TAG_ENGINEERING,
    ),
    Prior(
        "local_dub_chain",
        "a dub that must run on your own machine is a chain of open-weights steps: transcribe (Whisper) -> "
        "translate (NLLB-200 / MADLAD-400 / a local LLM) -> read in the speaker's voice (XTTS-v2 / CosyVoice / "
        "Chatterbox) -> separate and remix (Demucs, ffmpeg); hosted dubbing endpoints do it in one call and are "
        "not local",
        "дубляж, который должен идти на вашей машине, — цепочка открытых весов: расшифровка (Whisper) -> перевод "
        "(NLLB-200 / MADLAD-400 / локальная LLM) -> чтение голосом диктора (XTTS-v2 / CosyVoice / Chatterbox) -> "
        "разделение и сведение (Demucs, ffmpeg); облачные эндпоинты дубляжа делают это одним вызовом и не локальны",
        TAG_ENGINEERING,
    ),
    Prior(
        "loop_reuse",
        "a seamless loop is generated ONCE at its own length and repeated to every ordered version and length at "
        "assembly (ffmpeg -stream_loop); generating each version separately pays N times for the same loop and "
        "the versions stop matching",
        "бесшовная петля генерируется ОДИН раз своей длины и повторяется до каждой заказанной версии и длины при "
        "сборке (ffmpeg -stream_loop); генерировать каждую версию отдельно — платить N раз за ту же петлю, и "
        "версии перестают совпадать",
        TAG_ENGINEERING,
    ),
)

#: Round 15: anonymising bystanders, long ambient loops.
PRIORS_LIST = (
    *PRIORS_LIST,
    Prior(
        "anonymise_face_swap",
        "anonymising bystanders by face swap: every passer-by's face is swapped to ONE generated synthetic face "
        "that resembles nobody (a video face-swap endpoint, priced per second), not a whole-character replacement; "
        "the irreversible alternative is blurring the detected faces at assembly",
        "анонимизация прохожих заменой лица: лицо каждого прохожего меняется на ОДНО сгенерированное синтетическое "
        "лицо, не похожее ни на кого (эндпоинт замены лица в видео, цена за секунду), а не замена персонажа целиком; "
        "необратимая альтернатива — размытие найденных лиц при сборке",
        TAG_ENGINEERING,
    ),
    Prior(
        "anonymise_blur",
        "anonymising bystanders by blur: faces are detected in every frame and blurred or boxed at assembly "
        "(deface / ffmpeg boxblur over tracked boxes) — irreversible anonymisation, no generative model, 0 usd",
        "анонимизация прохожих размытием: лица находятся в каждом кадре и размываются или закрываются плашкой при "
        "сборке (deface / ffmpeg boxblur по трекингу) — необратимая анонимизация, без генеративной модели, 0 usd",
        TAG_ENGINEERING,
    ),
    Prior(
        "ambient_segment_loop",
        "hours of ambience (rain, fire, sleep sounds, a fireplace video) are ONE loopable segment generated once "
        "and repeated with a crossfade at assembly — generating the full length pays for hours of the same thing",
        "часы фона (дождь, огонь, звуки для сна, ролик с камином) — это ОДИН зацикливаемый отрезок, сгенерированный "
        "один раз и повторённый с наплывом при сборке; генерация полной длины — плата за часы одного и того же",
        TAG_ENGINEERING,
    ),
)

#: Round 16: anonymisation by field (pixelation, a voice replaced).
PRIORS_LIST = (
    *PRIORS_LIST,
    Prior(
        "anonymise_pixelate",
        "anonymising faces by pixelation: faces are detected in every frame and pixelated with a coarse block at "
        "assembly (deface / ffmpeg pixelize over tracked boxes) — irreversible, no generative model, 0 usd",
        "анонимизация лиц пикселизацией: лица находятся в каждом кадре и пикселизуются крупным блоком при сборке "
        "(deface / ffmpeg pixelize по трекингу) — необратимо, без генеративной модели, 0 usd",
        TAG_ENGINEERING,
    ),
    Prior(
        "anonymise_voice_replace",
        "anonymising a voice: the speech is transcribed and re-spoken by a DIFFERENT stock TTS voice, laid in "
        "line by line at assembly — never a clone of the speaker and never a dubbing endpoint, which is built to "
        "keep the speaker's timbre",
        "анонимизация голоса: речь расшифровывается и заново читается ДРУГИМ стоковым голосом синтеза, который "
        "кладётся фраза за фразой при сборке, — никогда не клон говорящего и не эндпоинт дубляжа, который сделан, "
        "чтобы сохранить тембр",
        TAG_ENGINEERING,
    ),
)

#: Round 17: the missing routes (`studio/routes_r17.py`).
PRIORS_LIST = (
    *PRIORS_LIST,
    Prior(
        "burned_subtitles_replace",
        "translating footage with burned-in subtitles: the old text is read (a timed transcript of the speech, OCR of "
        "the burned strip for the exact wording), machine-translated, REMOVED by a masked video edit of the subtitle "
        "band, and the new subtitles are burned in at assembly — or delivered as a soft track where the platform "
        "takes one; drawing new text over the old one leaves both",
        "перевод видео со вшитыми субтитрами: старый текст читается (расшифровка речи с таймингами, OCR вшитой строки "
        "для точной формулировки), переводится машинным переводом, УБИРАЕТСЯ правкой по маске полосы субтитров, а "
        "новые субтитры вшиваются при сборке — или сдаются отдельной дорожкой, где площадка её принимает; новый текст "
        "поверх старого оставляет оба",
        TAG_ENGINEERING,
    ),
    Prior(
        "performer_reference_lips",
        "a singer's music video: one performer reference (the performer's own photos, or one generated still) feeds "
        "a reference-to-video clip per performer shot, and lip sync to the track's vocals runs ONLY on the shots where "
        "the performer sings on camera; the other shots are key stills animated image-to-video without lips",
        "клип исполнителя: один референс исполнителя (его фото или один сгенерированный кадр) даёт видео по референсу "
        "на каждый шот с исполнителем, а липсинк к вокалу трека идёт ТОЛЬКО на шотах, где он поёт в кадре; остальные "
        "шоты — ключевые кадры, оживлённые без губ",
        TAG_ENGINEERING,
    ),
    Prior(
        "gaussian_splat_scene",
        "a 3D walkthrough or tour of a real place is a reconstruction — camera poses from overlapping photos or "
        "video frames (COLMAP), a gaussian splat trained on them (gsplat / nerfstudio splatfacto, Apache-2.0) and a "
        "camera path rendered from it; a video model animating the photos invents geometry and is not a 3D tour",
        "3D-тур или облёт реального места — это реконструкция: позы камер по снимкам с перекрытием или кадрам видео "
        "(COLMAP), гауссов сплат, обученный на них (gsplat / nerfstudio splatfacto, Apache-2.0), и путь камеры, "
        "отрендеренный из него; видеомодель, оживляющая снимки, выдумывает геометрию и 3D-туром не является",
        TAG_BASE_ROWS,
        (
            Source(
                "nerfstudio-splatfacto",
                "vram_gb",
                "https://raw.githubusercontent.com/nerfstudio-project/nerfstudio/main/docs/nerfology/methods/splat.md",
                "splatfacto ~6 GB / splatfacto-big ~12 GB, COLMAP initialisation, export .ply",
            ),
            Source(
                "gsplat",
                "licence",
                "https://raw.githubusercontent.com/nerfstudio-project/gsplat/main/LICENSE",
                "Apache-2.0",
            ),
        ),
    ),
    Prior(
        "whole_person_replace",
        "replacing the whole person in the customer's footage (body, costume, identity) is a character-replacement "
        "model (Wan Animate replace class: the source motion, the new character from its reference, priced per "
        "second) — a face swap moves only a face and leaves the body, hair and clothes of the original",
        "замена человека в материале заказчика целиком (тело, костюм, личность) — модель замены персонажа (класс Wan "
        "Animate replace: движение исходника, новый персонаж по референсу, цена за секунду); замена лица переносит "
        "только лицо и оставляет тело, волосы и одежду исходного",
        TAG_BASE_ROWS,
        (
            Source(
                "wan-animate-replace",
                "architecture",
                "https://fal.ai/models/fal-ai/wan/v2.2-14b/animate/replace/api",
                "replaces the character in a reference video, keeping the scene",
            ),
        ),
    ),
    Prior(
        "ugc_shared_references",
        "a UGC batch of product clips reuses a few shared references — one presenter for every clip and one packshot "
        "per product — made once; a still per clip pays N times and the presenter's face drifts between clips",
        "пачка UGC-роликов о товарах держится на нескольких общих референсах — один ведущий на все ролики и по кадру "
        "товара на товар, — сделанных один раз; кадр на каждый ролик — плата N раз, и лицо ведущего плывёт",
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
    "alpha_matte": (("alpha_encode",), ("matte_edge",)),
    "lyrics_alignment": (("captions_burn",), ("lyric_drift",)),
    "audiogram_static_art": (("showwaves", "captions_burn"), ()),
    "mesh_reconstruction": (("mesh_render",), ("unseen_geometry",)),
    "print_upscale": ((), ("upscale_hallucination",)),
    "whole_character_replace": ((), ("character_motion_drift",)),
    "virtual_try_on": ((), ("garment_detail_lost",)),
    "walkthrough_camera_path": (("ffmpeg_concat",), ("walkthrough_warp",)),
    "drawn_stylised_lipsync": ((), ("mouth_flap_timing",)),
    "local_dub_chain": (("extract_audio",), ("clone_accent", "dub_segment_overrun")),
    "loop_reuse": (("ffmpeg_concat",), ("loop_seam",)),
    "anonymise_face_swap": ((), ("missed_faces",)),
    "anonymise_blur": (("deface",), ("missed_faces",)),
    "anonymise_pixelate": (("deface",), ("missed_faces",)),
    "anonymise_voice_replace": (("voice_track_swap",), ("missed_voices", "identifying_words")),
    "ambient_segment_loop": (("ffmpeg_concat",), ("loop_seam",)),
    "burned_subtitles_replace": (("ffmpeg_subtitles",), ("subtitle_ghost",)),
    "performer_reference_lips": (("ffmpeg_concat",), ("mouth_flap_timing",)),
    "gaussian_splat_scene": (("splat_render",), ("splat_floaters",)),
    "whole_person_replace": ((), ("character_motion_drift",)),
    "ugc_shared_references": ((), ()),
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
    Tool("mesh_render", "Blender (Cycles / Eevee)", "render a turntable clip from the mesh",
         "отрендерить ролик-оборот из 3D-модели"),
    Tool("alpha_encode", "ffmpeg libvpx-vp9 / prores_ks", "encode the matted clip with alpha (WebM VP9 or ProRes 4444)",
         "закодировать ролик с альфа-каналом (WebM VP9 или ProRes 4444)"),
)

TOOLS_LIST = (
    *TOOLS_LIST,
    Tool("deface", "deface (ORB-HD) / ffmpeg boxblur", "detect every face per frame and blur or box it",
         "найти каждое лицо в кадре и размыть или закрыть плашкой"),
)
TOOLS_LIST = (
    *TOOLS_LIST,
    Tool("voice_track_swap", "ffmpeg amix / demucs", "lay the new voice line by line over the speech, music and "
         "ambience from a stem separation", "положить новый голос фраза за фразой вместо речи, музыка и атмосфера — "
         "из разделения на стемы"),
)
TOOLS_LIST = (
    *TOOLS_LIST,
    Tool("ffmpeg_subtitles", "ffmpeg subtitles (libass)", "burn the translated subtitles into the picture, or mux a "
         "soft track", "вшить переведённые субтитры в картинку или положить их отдельной дорожкой"),
    Tool("splat_render", "nerfstudio ns-render / SuperSplat", "render the camera path from the trained splat, or "
         "export it for a web viewer", "отрендерить путь камеры из обученного сплата или выгрузить его для "
         "веб-просмотрщика"),
)
TOOLS: dict[str, Tool] = {т.id: т for т in TOOLS_LIST}

# --- failure modes ----------------------------------------------------------------

FAILURES_LIST: tuple[Failure, ...] = (
    Failure("character_motion_drift", "the replaced character slips off the actor's motion (limbs, feet) or the "
            "scene lighting", "заменённый персонаж отстаёт от движения актёра (руки, ноги) или от света сцены",
            "step through the fastest move and the contact points", "пройти по кадрам самое быстрое движение и касания"),
    Failure("garment_detail_lost", "try-on redraws the garment: print, logo, buttons or cut drift from the product",
            "примерка перерисовывает вещь: принт, логотип, пуговицы или крой уходят от товара",
            "compare print and logo with the product photo at 100%", "сверить принт и логотип с фото товара в 100%"),
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
    Failure("matte_edge", "the matte edge fringes or flickers (hair, motion blur)", "край маски с ореолом или мерцает (волосы, смаз)",
            "play the alpha over black and over white", "посмотреть альфу на чёрном и на белом фоне"),
    Failure("unseen_geometry", "geometry the photos never showed is invented (underside, back)",
            "геометрия, которой нет на снимках, выдумана (низ, спина)",
            "turn the mesh to every side the photos did not cover", "повернуть модель всеми сторонами, которых нет на снимках"),
    Failure("lyric_drift", "lyric lines drift off the sung words", "строки текста уезжают от спетых слов",
            "check the first word of every line against the vocal", "сверить первое слово каждой строки с вокалом"),
)

FAILURES_LIST = (
    *FAILURES_LIST,
    Failure("walkthrough_warp", "image-to-video bends walls and door frames or invents rooms past the photo",
            "image-to-video гнёт стены и дверные проёмы или выдумывает комнаты за краем снимка",
            "check verticals and the last frame of every room clip", "проверить вертикали и последний кадр каждого клипа"),
    Failure("mouth_flap_timing", "drawn mouths keep the old language's timing", "нарисованные рты держат тайминг старого языка",
            "watch the longest line with sound", "посмотреть самую длинную реплику со звуком"),
    Failure("dub_segment_overrun", "a translated line runs longer than its original segment",
            "переведённая реплика длиннее своего отрезка оригинала",
            "compare each segment's new length with the original", "сверить длину каждого отрезка с оригиналом"),
)

FAILURES_LIST = (
    *FAILURES_LIST,
    Failure("missed_faces", "face detection misses small, profile or occluded faces, so some bystanders stay "
            "identifiable", "детектор лиц пропускает мелкие, профильные и закрытые лица — часть прохожих остаётся "
            "узнаваемой", "step through crowds, profiles and the frame edges", "пройти по кадрам толпу, профили и края кадра"),
)
FAILURES_LIST = (
    *FAILURES_LIST,
    Failure("missed_voices", "a second voice (an overlap, a laugh, an off-mic remark) stays in the original and "
            "identifies the speaker", "второй голос (наложение, смех, реплика мимо микрофона) остаётся в оригинале и "
            "выдаёт говорящего", "listen to the final track end to end against the transcript",
            "прослушать итоговую дорожку целиком по расшифровке"),
    Failure("identifying_words", "the words themselves identify the speaker (names, places, dates, turns of phrase)",
            "сами слова выдают говорящего (имена, места, даты, обороты)",
            "redact the transcript before synthesis", "вычитать и вычистить расшифровку до синтеза"),
)
FAILURES_LIST = (
    *FAILURES_LIST,
    Failure("subtitle_ghost", "the removed subtitle band leaves a smear or a flicker where the old letters were",
            "на месте убранной полосы субтитров остаётся мазок или мерцание", "step through the band frame by frame "
            "on cuts and on bright backgrounds", "пройти полосу по кадрам на склейках и на светлом фоне"),
    Failure("splat_floaters", "floaters and blur where the capture had few views (ceilings, corners, behind "
            "furniture)", "«облака» и размытие там, где мало ракурсов (потолок, углы, за мебелью)",
            "fly the camera path through every room before delivery", "пролететь путь камеры по каждой комнате до сдачи"),
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
            RecipeStep(
                "апскейл_изображения", "model", "a print frame (trim size x DPI) above the generator's native frame"
            ),
        ),
        ("t2i_native_max", "print_upscale"),
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
            RecipeStep("звук_по_видео", "model", "video-to-audio over YOUR footage"),
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
    Recipe(
        "alpha_delivery",
        "a clip with a transparent background",
        (
            RecipeStep("оживление", "model", "the clip on a plain background"),
            RecipeStep("удаление_фона_видео", "model", "video matting to an alpha channel"),
            RecipeStep("alpha_encode", "tool", "WebM VP9 alpha / ProRes 4444"),
        ),
        ("alpha_matte",),
        ("alpha_encode",),
        ("matte_edge",),
    ),
    Recipe(
        "lyric_video",
        "lyrics animated to the customer's song",
        (
            RecipeStep("расшифровка", "model", "word timestamps of the vocals"),
            RecipeStep("captions_burn", "tool", "the aligned lyrics rendered as typography"),
        ),
        ("lyrics_alignment",),
        ("captions_burn",),
        ("lyric_drift",),
    ),
    Recipe(
        "product_3d",
        "a 3D model of the customer's product from photos",
        (
            RecipeStep("модель_3d", "model", "image-to-3D from every photo"),
            RecipeStep("mesh_render", "tool", "turntable clip from the mesh, when a video is wanted"),
        ),
        ("mesh_reconstruction",),
        ("mesh_render",),
        ("unseen_geometry",),
    ),
    Recipe(
        "audiogram",
        "waveform and captions over the customer's cover art",
        (
            RecipeStep("расшифровка", "model", "captions, when a language is named"),
            RecipeStep("showwaves", "tool", "the waveform layer"),
        ),
        ("audiogram_static_art",),
        ("showwaves", "captions_burn"),
        (),
    ),
)

RECIPES_LIST = (
    *RECIPES_LIST,
    Recipe(
        "character_replacement",
        "a mascot or costumed character replaces a person in the customer's video",
        (RecipeStep("замена_фигуры", "model", "the character reference is not a human face"),),
        ("whole_character_replace",),
        (),
        ("character_motion_drift",),
    ),
    Recipe(
        "virtual_try_on",
        "the customer's garment on a generated model",
        (
            RecipeStep("генерация_изображения", "model", "the model photo, when the customer brings only the garment"),
            RecipeStep("примерка", "model", "model photo + garment photo"),
        ),
        ("virtual_try_on",),
        (),
        ("garment_detail_lost",),
    ),
)

RECIPES_LIST = (
    *RECIPES_LIST,
    Recipe(
        "property_walkthrough",
        "a walkthrough / tour of a place from the customer's photos",
        (
            RecipeStep("оживление", "model", "one camera move per photo"),
            RecipeStep("ffmpeg_concat", "tool", "room clips joined in walking order"),
        ),
        ("walkthrough_camera_path",),
        ("ffmpeg_concat",),
        ("walkthrough_warp",),
    ),
    Recipe(
        "drawn_dub",
        "dubbing anime / cartoon footage",
        (
            RecipeStep("дубляж", "model", "dub of the speech"),
            RecipeStep("липсинк", "model", "lip sync on a model recorded for drawn / stylised faces"),
        ),
        ("drawn_stylised_lipsync",),
        (),
        ("mouth_flap_timing",),
    ),
    Recipe(
        "local_dub",
        "a dub that runs on the customer's own machine",
        (
            RecipeStep("расшифровка", "model", "timed transcript (Whisper)"),
            RecipeStep("клонирование_голоса", "model", "translated text read in the speaker's voice"),
            RecipeStep("extract_audio", "tool", "the speaker's sample from the video"),
        ),
        ("local_dub_chain",),
        ("extract_audio",),
        ("clone_accent", "dub_segment_overrun"),
    ),
    Recipe(
        "shared_loop",
        "one loop reused across several versions or lengths",
        (
            RecipeStep("генерация_видео", "model", "one seamless loop at its own length"),
            RecipeStep("ffmpeg_concat", "tool", "the loop repeated to every version's length"),
        ),
        ("loop_reuse",),
        ("ffmpeg_concat",),
        ("loop_seam",),
    ),
)

RECIPES_LIST = (
    *RECIPES_LIST,
    Recipe(
        "anonymise_bystanders",
        "anonymising passers-by in the customer's footage",
        (
            RecipeStep("генерация_изображения", "model", "one synthetic face that resembles nobody (face-swap route)"),
            RecipeStep("замена_персонажа", "model", "video face swap onto every bystander (face-swap route)"),
            RecipeStep("deface", "tool", "detected faces blurred at assembly (blur route)"),
        ),
        ("anonymise_face_swap", "anonymise_blur", "anonymise_pixelate"),
        ("deface",),
        ("missed_faces",),
    ),
    Recipe(
        "anonymise_voice",
        "anonymising a speaker's voice (a witness, an informant)",
        (
            RecipeStep("расшифровка", "model", "timed transcript, redacted before synthesis"),
            RecipeStep("озвучка", "model", "a different stock voice reads it (never a clone)"),
            RecipeStep("voice_track_swap", "tool", "the new voice laid in line by line at assembly"),
        ),
        ("anonymise_voice_replace",),
        ("voice_track_swap",),
        ("missed_voices", "identifying_words"),
    ),
    Recipe(
        "ambient_loop",
        "a long ambient piece (hours) from one loopable segment",
        (
            RecipeStep("музыка", "model", "one loopable audio segment"),
            RecipeStep("генерация_видео", "model", "one loopable clip"),
            RecipeStep("ffmpeg_concat", "tool", "the segment repeated with a crossfade to the ordered length"),
        ),
        ("ambient_segment_loop",),
        ("ffmpeg_concat",),
        ("loop_seam",),
    ),
)

RECIPES_LIST = (
    *RECIPES_LIST,
    Recipe(
        "burned_subtitles",
        "translating footage whose subtitles are burned into the picture",
        (
            RecipeStep("расшифровка", "model", "timed transcript of the speech (OCR of the burned strip beside it)"),
            RecipeStep("правка_видео", "model", "the old subtitle band removed by a masked edit"),
            RecipeStep("ffmpeg_subtitles", "tool", "the translated subtitles burned in (or a soft track)"),
        ),
        ("burned_subtitles_replace",),
        ("ffmpeg_subtitles",),
        ("subtitle_ghost",),
    ),
    Recipe(
        "performer_music_video",
        "a singer's music video from a performer reference",
        (
            RecipeStep("генерация_изображения", "model", "one performer reference (none when brought) and the key stills of the other shots"),
            RecipeStep("видео_по_референсу", "model", "one clip per performer shot"),
            RecipeStep("липсинк", "model", "lip sync on the performer shots only"),
            RecipeStep("оживление", "model", "the other shots, no lips"),
            RecipeStep("ffmpeg_concat", "tool", "the shots cut to the track"),
        ),
        ("performer_reference_lips",),
        ("ffmpeg_concat",),
        ("mouth_flap_timing",),
    ),
    Recipe(
        "scene_3d",
        "a 3D walkthrough / tour of a real place",
        (
            RecipeStep("реконструкция_3d", "model", "a gaussian splat from the overlapping photos / video frames"),
            RecipeStep("splat_render", "tool", "the camera path rendered, or the splat exported for a viewer"),
        ),
        ("gaussian_splat_scene",),
        ("splat_render",),
        ("splat_floaters",),
    ),
    Recipe(
        "whole_person_replacement",
        "the whole person in the customer's footage replaced (body, costume, identity)",
        (
            RecipeStep("генерация_изображения", "model", "the new character's reference, when none is brought"),
            RecipeStep("замена_фигуры", "model", "character replacement on the source motion"),
        ),
        ("whole_person_replace",),
        (),
        ("character_motion_drift",),
    ),
    Recipe(
        "ugc_product_batch",
        "a batch of UGC clips about a few products",
        (RecipeStep("генерация_изображения", "model", "one shared presenter and one packshot per product"),),
        ("ugc_shared_references",),
        (),
        (),
    ),
)

RECIPES: dict[str, Recipe] = {р.id: р for р in RECIPES_LIST}

# --- production notes (round 9) -----------------------------------------------------
#
# WHY. A recipe prior CHANGES the plan where the base is silent; a production note
# changes nothing in the steps but says what a senior engineer says next to them:
# whose licence decides commercial use, that a removal is a mask and a composite,
# that 2.39:1 is a crop, that an EU publication is labelled. The round-9 expert
# set measured notes as the weakest dimension (22 of 44 missing): the plan was
# right and silent. Each note has its trigger in `apply.notes` (one rule per job
# class or condition, never per brief), its wording in both answer languages, and
# a tag: `engineering prior`, or `regulation` with the text it rests on.


@dataclass(frozen=True)
class Note:
    """A production note: what to know next to the steps. `{x}` fields are filled per plan."""

    id: str
    en: str
    ru: str
    tag: str
    sources: tuple[Source, ...] = ()


_AI_ACT = "https://eur-lex.europa.eu/eli/reg/2024/1689/oj"

NOTES_LIST: tuple[Note, ...] = (
    Note(
        "music_licence",
        "generated music: the licence terms of the chosen service decide commercial use — check that your plan "
        "tier grants a royalty-free commercial licence for streaming and monetised video, and keep the licence "
        "record with the track",
        "сгенерированная музыка: коммерческое использование решают условия лицензии выбранного сервиса — "
        "проверьте, что ваш тариф даёт коммерческую лицензию без роялти для стриминга и монетизированного "
        "видео, и храните лицензию вместе с треком",
        TAG_ENGINEERING,
    ),
    Note(
        "weights_licence",
        "open weights: the licence terms of each chosen checkpoint decide commercial use (some open weights are "
        "non-commercial or revenue-capped) — read the licence of the exact checkpoint before you ship",
        "открытые веса: коммерческое использование решают условия лицензии каждого выбранного чекпойнта "
        "(часть открытых весов — только некоммерческие или с порогом выручки) — прочтите лицензию именно "
        "этого чекпойнта до выпуска",
        TAG_ENGINEERING,
    ),
    Note(
        "song_rights",
        "the song is not yours: publishing it needs the music rights — a licence for the composition and the "
        "recording from the copyright holders, or a track you own or generate; platforms mute or claim "
        "unlicensed songs",
        "песня не ваша: для публикации нужны права на музыку — лицензия правообладателей на произведение и "
        "запись (авторские и смежные права) либо свой или сгенерированный трек; площадки глушат или "
        "забирают ролики с нелицензированной песней",
        TAG_ENGINEERING,
    ),
    Note(
        "long_form_segmented",
        "long form ({seconds} s): a talking-avatar or lip-sync run is capped per call, so the script is split "
        "into segments at sentence boundaries, each segment is generated separately and the segments are joined "
        "at assembly (ffmpeg concat) — same reference image and same voice on every segment",
        "длинный ролик ({seconds} с): прогон говорящего аватара или липсинка ограничен по длине, поэтому текст "
        "делится на отрезки по границам фраз, каждый отрезок генерируется отдельно, и отрезки склеиваются при "
        "сборке (ffmpeg concat) — один и тот же референс и один голос на всех отрезках",
        TAG_ENGINEERING,
    ),
    Note(
        "mask_composite",
        "removal or replacement in your footage is a masked inpaint: a segmentation mask (e.g. SAM 2) tracks the "
        "object or the sky through the shot, only the masked region is regenerated, and it is composited over "
        "the untouched plate — check the mask edge for halo and flicker frame by frame",
        "удаление или замена в вашем видео — это дорисовка по маске: маска сегментации (например, SAM 2) ведёт "
        "объект или небо по всему плану, перерисовывается только область под маской, и она накладывается "
        "поверх нетронутого кадра — край маски проверяется по кадрам на ореол и мерцание",
        TAG_ENGINEERING,
    ),
    Note(
        "crop_track",
        "reframing to {aspect} is a crop that follows the subject (face tracking drives the crop window) at "
        "assembly, 0 usd; generative outpainting is needed only where the crop would cut the subject",
        "перекадрирование в {aspect} — это кадрирование, которое ведёт трекинг лица (окно кадра идёт за "
        "человеком) при сборке, 0 usd; генеративная дорисовка нужна только там, где кадр резал бы человека",
        TAG_ENGINEERING,
    ),
    Note(
        "aspect_crop",
        "{aspect} is not an aspect generators render natively: it is generated at {native} and cropped (or "
        "letterboxed) to {aspect} at assembly — keep the action inside the crop's safe area in the prompt",
        "{aspect} генераторы родным кадром не рисуют: кадр генерируется в {native} и при сборке кадрируется "
        "(или получает чёрные поля) до {aspect} — держите действие внутри безопасной зоны кадрирования",
        TAG_ENGINEERING,
    ),
    Note(
        "ai_act_label",
        "EU AI Act, Art. 50 (applies from 2 August 2026): AI-generated or manipulated video, image and audio must "
        "be disclosed — label the piece as AI-generated where it is published and keep a machine-readable "
        "marking (C2PA content credentials or a watermark)",
        "Регламент ЕС об ИИ (AI Act), ст. 50, действует с 2 августа 2026: созданные или изменённые ИИ видео, "
        "изображения и звук раскрываются — маркировка «создано ИИ» там, где ролик публикуется, и машиночитаемая "
        "отметка (C2PA или водяной знак)",
        TAG_REGULATION,
        (Source("*", "regulation", _AI_ACT, "Regulation (EU) 2024/1689, Article 50: transparency obligations"),),
    ),
    Note(
        "multi_speaker",
        "{speakers} speakers in the shot: the audio is diarized (who speaks when) and the lip sync runs per "
        "active speaker with a face mask, so each speaker's face moves only on their own lines — check that "
        "the listening face stays still",
        "в кадре говорящих {speakers}: звук размечается по говорящим (кто и когда говорит), и липсинк идёт по "
        "активному говорящему с маской лица — каждое лицо двигает губами только на своих репликах; проверьте, "
        "что слушающее лицо неподвижно",
        TAG_ENGINEERING,
    ),
    Note(
        "logo_text_composited",
        "logo and exact text: generative models redraw letterforms, so the true logo or text is composited from "
        "your vector file as an overlay at assembly (tracked onto the product where it moves) and checked "
        "letter for letter on the final frame",
        "логотип и точный текст: генеративные модели перерисовывают буквы, поэтому настоящий логотип или текст "
        "накладывается поверх из вашего векторного файла при сборке (с трекингом на предмет, где он движется) "
        "и сверяется буква в букву на финальном кадре",
        TAG_ENGINEERING,
    ),
    Note(
        "unseen_side",
        "one photo shows one side: the back and the hidden sides are unseen, and the model invents them "
        "(hallucinated seams, logos, buttons) — for an accurate 360° bring photos of every side or go through a "
        "3D reconstruction",
        "один снимок показывает одну сторону: обратная и скрытые стороны не видны, и модель их выдумывает (швы, "
        "логотипы, кнопки) — для точного оборота на 360° нужны снимки со всех сторон или реконструкция в 3D",
        TAG_ENGINEERING,
    ),
    Note(
        "captions_burned",
        "captions are burned in at assembly from the timed transcript (ffmpeg subtitles, styled for the "
        "platform), 0 usd — proofread the transcript before burning",
        "субтитры вжигаются при сборке по расшифровке с таймингами (ffmpeg subtitles, оформление под "
        "площадку), 0 usd — вычитайте расшифровку до вжигания",
        TAG_ENGINEERING,
    ),
    Note(
        "regional_variety",
        "{tags}: a regional variety (dialect, accent) is not the language itself — models record language "
        "support, not the dialect; choose a voice that speaks that variety and have a native listener of it "
        "check the result",
        "{tags}: региональный вариант (диалект, акцент) — это не сам язык: у моделей записана поддержка языка, "
        "а не диалекта; выберите голос, который говорит именно на нём, и дайте результат послушать носителю",
        TAG_ENGINEERING,
    ),
    Note(
        "lyric_alignment",
        "lyrics are aligned to the vocals at word level: the transcription's word timestamps place each line of "
        "YOUR lyrics, and the animated typography is rendered from those timestamps at assembly",
        "слова песни выравниваются по вокалу пословно: временные метки слов из расшифровки ставят каждую строку "
        "ВАШЕГО текста, и анимированная типографика рендерится по этим меткам при сборке",
        TAG_ENGINEERING,
    ),
    Note(
        "alpha_delivery",
        "transparent background: generators output opaque video, so the background is removed per frame and "
        "the clip is delivered with an alpha channel — WebM (VP9 with alpha) for the web, ProRes 4444 for "
        "editing; MP4 / H.264 carries no alpha",
        "прозрачный фон: генераторы отдают непрозрачное видео, поэтому фон снимается в каждом кадре, и ролик "
        "отдаётся с альфа-каналом — WebM (VP9 с альфой) для сайта, ProRes 4444 для монтажа; MP4 / H.264 "
        "прозрачность не несёт",
        TAG_ENGINEERING,
    ),
    Note(
        "self_host_route",
        "a 0 budget: self-host the open weights on your own GPU (or a free one) — run it locally with ComfyUI "
        "or diffusers; you pay in hardware and time, not per call",
        "бюджет 0: открытые веса запускаются локально на своей видеокарте (или на бесплатной) — ComfyUI или "
        "diffusers; платите железом и временем, а не за вызов",
        TAG_ENGINEERING,
    ),
    Note(
        "waveform_layer",
        "the waveform (ffmpeg showwaves) and the captions are laid over YOUR cover art at assembly, 0 usd — "
        "no generated motion is needed for an audiogram",
        "волна звука (ffmpeg showwaves) и субтитры ложатся поверх ВАШЕЙ обложки при сборке, 0 usd — "
        "генерируемое движение аудиограмме не нужно",
        TAG_ENGINEERING,
    ),
    Note(
        "mesh_route",
        "a 3D model is an image-to-3D reconstruction (TRELLIS, Hunyuan3D, Tripo class) exported as GLB; a "
        "turntable video, if wanted, is rendered from the mesh (Blender) at assembly, 0 usd — check the back "
        "and the underside of the mesh against your photos",
        "3D-модель — это реконструкция «изображение -> 3D» (класс TRELLIS, Hunyuan3D, Tripo) с выгрузкой в GLB; "
        "видео-оборот, если нужен, рендерится из модели (Blender) при сборке, 0 usd — сверьте спину и низ "
        "модели с вашими снимками",
        TAG_ENGINEERING,
    ),
    # --- round 10: delivery conditions (`studio/recipes/delivery.py`) ---------------
    Note(
        "print_resolution",
        "print: pixels = trim size x {dpi} DPI{size} — {frame}; a generator renders 1-4 MP natively, so a smaller "
        "native frame is upscaled as the last step (a faithful upscaler, not a creative one) and the file is "
        "delivered at {dpi} DPI in the printer's colour profile (CMYK conversion and bleed at prepress)",
        "печать: пикселей = формат x {dpi} DPI (точек на дюйм){size} — {frame}; генератор рисует родным кадром "
        "1-4 Мп, поэтому меньший родной кадр поднимается апскейлом последним шагом (точным, не творческим), "
        "а файл отдаётся с {dpi} DPI в профиле типографии (перевод в CMYK и вылеты — на допечатке)",
        TAG_ENGINEERING,
    ),
    Note(
        "deinterlace",
        "tape or interlaced source: deinterlace FIRST (ffmpeg bwdif or yadif in field mode, QTGMC for the best "
        "result), crop the head-switching noise at the bottom edge, and only then denoise, restore or upscale — "
        "restoration and upscale models are trained on progressive frames and turn combing into jagged edges",
        "плёнка VHS или чересстрочный источник: СНАЧАЛА деинтерлейс (ffmpeg bwdif или yadif по полям, QTGMC для "
        "лучшего результата), срезать шум переключения головок у нижнего края, и только потом шумодав, "
        "реставрация или апскейл — модели учились на прогрессивных кадрах и превращают гребёнку в рваные края",
        TAG_ENGINEERING,
    ),
    Note(
        "eight_k_detail",
        "8K (7680x4320): no model renders or recovers real 8K detail — the upscaler invents plausible texture "
        "(hallucinated detail) above what the source holds; real detail stays that of the source. Check faces, "
        "text and fine patterns at 100 % on the target screen, and keep the native master",
        "8K (7680x4320): настоящих деталей 8K не рисует и не восстанавливает ни одна модель — апскейл придумывает "
        "правдоподобную текстуру сверх того, что есть в исходнике, а настоящая детализация остаётся исходной. "
        "Проверьте лица, текст и мелкие узоры в 100 % на целевом экране и сохраните родной мастер",
        TAG_ENGINEERING,
    ),
    Note(
        "interp_artifacts",
        "{fps} fps by interpolation: most frames are invented between real ones, so fast motion, occlusions and "
        "thin structures (wings, spokes, hair, on-screen text) ghost, warp and morph — check the result frame "
        "by frame; a source shot at high frame rate is the only artefact-free slow motion",
        "{fps} кадров/с интерполяцией: большая часть кадров придумана между настоящими, поэтому быстрое движение, "
        "перекрытия и тонкие детали (крылья, спицы, волосы, текст на экране) дают артефакты — двоение, "
        "искажение и «плавление»; проверьте результат по кадрам — без артефактов замедление даёт только съёмка "
        "с высокой частотой",
        TAG_ENGINEERING,
    ),
)

NOTES: dict[str, Note] = {н.id: н for н in NOTES_LIST}
