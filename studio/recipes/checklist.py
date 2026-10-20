"""Engineering checklist (round 11): the notes a senior GenAI production engineer always attaches.

WHY. Rounds 9 and 10 added production notes one at a time, each after an eval
brief missed it (`table.NOTES`, `delivery.py`). The dev set reached 147/150 and
a fresh hidden set scored about half, with NOTES its weakest dimension (39 %):
a rule written for the brief that failed does not cover the next brief of the
same kind. This module is the other way round: it walks every JOB CLASS the
studio plans (image, video, animate, avatar, lip sync, dub, speech, voice clone,
music, sound effects, audio clean-up, image and video edits, restore, colourise,
upscale, frame rate, shorts, 360 and 3D, logo and text, visualiser, series,
utilities, self-host, budget, disclosure) and every COMMON CONDITION (several
voices, singing, slides, right-to-left and CJK scripts, telephony, podcast and
broadcast loudness, long audio, loops, shot transitions, reflective products,
limited animation, archival material, made for kids, edge devices, low VRAM,
licences, 8K, platform safe zones) and writes down what is ALWAYS said next to
such a plan. One rule per job class or condition — never per brief.

HOW A RULE FIRES. A rule names the job codes it belongs to (`JOBS_OF_STEP`,
`JOBS_OF_TASK`: the planner's operations and the spec's task, never a brief id)
and a trigger that reads STRUCTURED spec fields first (`task`, `outputs`,
`languages`/`language_tags`, `people`/`characters`, `shots`, `duration_s`,
`fps`, `aspect`, `resolution`, `inputs`, `self_host`, `jurisdiction`, `edit`).
Only a condition the spec cannot express (telephony, podcast, a loop, a
reflective product, made for kids, …) is read from the words — the brief and
`spec.conditions` — and each such rule names in `spec_field` the field that
would carry it structurally, so the contract can grow without guessing
(`spec_fields_to_add()` lists them).

Each rule has its wording in both answer languages, a tag (`engineering prior`,
`regulation`, `platform policy`) and, where one exists, the source URL.

DECISION CONSTANTS (T1: mutated both ways by `scripts/mutate_round11.py`):
`LONG_AUDIO_S`, `MUSIC_RUN_MAX_S`, `LOW_VRAM_GB`, `BULK_ITEMS`,
`TRANSITION_MIN_SHOTS`, `SERIES_MIN_SHOTS`, `MULTI_VOICE_MIN`, `RTL_LANGS`,
`CJK_LANGS`, `DIACRITIC_LANGS`.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from studio.recipes import delivery
from studio.recipes.table import TAG_ENGINEERING, TAG_PLATFORM, TAG_REGULATION

if TYPE_CHECKING:  # pragma: no cover
    from studio import brief_spec as bs

# --- decision constants ------------------------------------------------------------

#: Speech or transcription longer than this many seconds is made in chunks and
#: stitched: TTS services cap one call at a few thousand characters (about 5
#: minutes of speech), and ASR runs on VAD windows.
LONG_AUDIO_S = 300
#: A music-model run makes up to about 3-4 minutes; a longer track is built in sections.
MUSIC_RUN_MAX_S = 240
#: A self-host card with at most this much VRAM needs offload / quantised weights / tiling.
LOW_VRAM_GB = 12
#: From this many generations (shots, images, items) the job is a batch queue.
BULK_ITEMS = 20
#: From this many shots a video plan has transitions between generated shots.
TRANSITION_MIN_SHOTS = 2
#: From this many shots with a recurring character, identity is locked with a sheet.
SERIES_MIN_SHOTS = 3
#: From this many speakers a speech plan casts one voice per character.
MULTI_VOICE_MIN = 2
#: Right-to-left scripts (primary language subtags): Arabic, Hebrew, Persian, Urdu,
#: Yiddish, Pashto, Sindhi, Uyghur, Dhivehi, Sorani Kurdish.
RTL_LANGS: frozenset[str] = frozenset({"ar", "he", "fa", "ur", "yi", "ps", "sd", "ug", "dv", "ckb"})
#: Chinese, Japanese, Korean typesetting (no spaces to break on, full glyph coverage).
CJK_LANGS: frozenset[str] = frozenset({"zh", "cmn", "yue", "ja", "ko"})
#: Scripts written without short vowels: TTS reads ambiguous words wrongly without diacritics.
DIACRITIC_LANGS: frozenset[str] = frozenset({"ar", "he", "fa", "ur"})

# --- job codes ------------------------------------------------------------------------

#: Planner operation -> job code (the scorer's names, `scripts/eval_plans.STEP_JOB`).
JOBS_OF_STEP: dict[str, str] = {
    "озвучка": "tts",
    "дубляж": "dub",
    "оживление": "i2v",
    "генерация_видео": "t2v",
    "видео_со_звуком": "t2v_audio",
    "замена_персонажа": "char_replace",
    "замена_фигуры": "char_replace",
    "замена_лица_изображения": "face_swap",
    "примерка": "image_edit",
    "звук_фон": "sfx",
    "липсинк": "lipsync",
    "генерация_изображения": "t2i",
    "редактирование_изображения": "image_edit",
    "музыка": "music",
    "апскейл": "upscale_video",
    "апскейл_изображения": "upscale_image",
    "реставрация": "restore",
    "раскраска": "colorize",
    "раскраска_изображения": "colorize",
    "интерполяция_кадров": "interpolate",
    "удаление_фона": "bg_remove_image",
    "удаление_фона_видео": "bg_remove_video",
    "расшифровка": "transcribe",
    "клонирование_голоса": "voice_clone",
    "оборот_360": "turntable",
    "модель_3d": "3d",
    "звук_по_видео": "v2a",
    "правка_видео": "v2v_edit",
    "видео_по_референсу": "r2v",
    "говорящий_аватар": "avatar",
}
#: Spec task -> job code: the deliverable named by the caller, also when the plan
#: has no model step for it (cut-to-shorts, captions are assembly work).
JOBS_OF_TASK: dict[str, str] = {
    "lipsync": "lipsync",
    "dub-translate": "dub",
    "avatar": "avatar",
    "animate": "i2v",
    "face-replace": "char_replace",
    "upscale": "upscale",
    "edit": "image_edit",
    "restore": "restore",
    "remove-background": "bg_remove",
    "interpolate": "interpolate",
    "transcribe": "transcribe",
    "voice-clone": "voice_clone",
    "turntable": "turntable",
    "captions": "captions",
    "video-edit": "v2v_edit",
    "r2v": "series",
    "music-visualiser": "visualiser",
    "sing-photo": "sing",
    "cut-to-shorts": "shorts",
    "colorize": "colorize",
}
#: Job groups the rules name.
VIDEO_GEN = frozenset({"t2v", "i2v", "t2v_audio", "r2v", "avatar", "series"})
FACE_SYNC = frozenset({"lipsync", "avatar", "sing"})
SPEECH_MAKE = frozenset({"tts", "dub", "voice_clone", "t2v_audio"})
UPSCALE = frozenset({"upscale", "upscale_video", "upscale_image"})
STILL_GEN = frozenset({"t2i", "image_edit"})
TEXT_ON_SCREEN = frozenset({"captions", "shorts"})
BG_REMOVE = frozenset({"bg_remove", "bg_remove_image", "bg_remove_video"})

# --- context ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Ctx:
    """What a trigger reads: the parsed spec, the plan's steps and job codes, the words."""

    spec: "bs.Spec"
    steps: frozenset[str]
    jobs: frozenset[str]
    text: str
    priors: frozenset[str] = frozenset()

    @property
    def outputs(self) -> set[str]:
        return set(self.spec.outputs)

    @property
    def visual(self) -> bool:
        """The deliverable is a picture (video or image), or a step makes one."""
        return bool(self.outputs & {"video", "image"}) or bool(
            self.jobs & (VIDEO_GEN | STILL_GEN | FACE_SYNC | TEXT_ON_SCREEN | {"turntable", "visualiser"})
        )

    @property
    def video(self) -> bool:
        return "video" in self.outputs or bool(self.jobs & (VIDEO_GEN | FACE_SYNC | {"shorts", "visualiser"}))

    @property
    def speakers(self) -> int:
        return max(len(self.spec.people), self.spec.characters or 0)

    @property
    def seconds(self) -> float:
        from studio import brief_spec as bs

        return float(self.spec.duration_s or bs.source_seconds(self.spec) or 0.0)

    @property
    def langs(self) -> set[str]:
        """Primary language subtags of the order (tags first, then language names)."""
        from studio import brief_spec as bs

        out = {str(т).split("-")[0].lower() for т in self.spec.language_tags if т}
        for имя in self.spec.languages:
            тег = bs.language_tag(str(имя))
            if тег:
                out.add(тег.split("-")[0].lower())
        return out

    @property
    def self_host(self) -> Mapping[str, Any]:
        sh = self.spec.self_host or {}
        return sh if sh.get("enabled", True) is not False else {}

    def says(self, rx: re.Pattern[str]) -> bool:
        return bool(rx.search(self.text))


def jobs_of(spec: "bs.Spec", steps: Sequence[str]) -> frozenset[str]:
    """Job codes of a plan: its steps, its task and follow-up tasks, and audio outputs."""
    out = {JOBS_OF_STEP[и] for и in steps if и in JOBS_OF_STEP}
    for задача in (spec.task, *spec.then_tasks):
        if задача in JOBS_OF_TASK:
            out.add(JOBS_OF_TASK[str(задача)])
    if "music" in spec.outputs:
        out.add("music")
    if "sfx" in spec.outputs:
        out.add("sfx")
    return frozenset(out)


def context(spec: "bs.Spec", steps: Sequence[str], text: str = "", priors: Sequence[str] = ()) -> Ctx:
    слова = " ".join(
        [str(text or "")]
        + [str(у) for у in spec.conditions]
        + [str(з.get("note") or "") for з in spec.input_items]
    )
    return Ctx(
        spec=spec,
        steps=frozenset(steps),
        jobs=jobs_of(spec, steps),
        text=" ".join(слова.lower().split()),
        priors=frozenset(priors),
    )


# --- words (text fallback only: conditions the spec has no field for) -------------------

W_PROFILE = re.compile(
    r"\bprofile\b|side[- ](?:on|angle|view)|turn(?:s|ing)? (?:the|their|his|her) head|\bbeard|moustache|mustache"
    r"|\bmask(?:ed)?\b|occlu|microphone (?:in front|covers)|hand (?:over|covers) (?:the )?mouth"
    r"|профил|в профиль|бород|усы\b|усами|маск[аеиу]\b|закрыт\w* рот",
    re.I,
)
W_PEOPLE = re.compile(
    r"\b(?:person|people|woman|women|man|men|girl|boy|child|kids?|face|portrait|model|presenter|host|actor|selfie)s?\b"
    r"|человек|люд[еи]|женщин|мужчин|девушк|парен|ребён|ребен|дет[иья]|лиц[оа]\b|портрет|ведущ|актёр|актер|селфи",
    re.I,
)
W_TEXT_IN_FRAME = re.compile(
    r"\btext\b|lettering|typograph|headline|title card|\btitles?\b|caption|subtitle|slogan|wordmark|\blogo"
    r"|надпис|текст|заголов|титр|субтитр|слоган|логотип",
    re.I,
)
W_PRODUCT = re.compile(
    r"\bproducts?\b|packshot|\bsku\b|packag|\blabel\b|e-?commerce|marketplace|amazon listing|\bbottle|\bjar\b"
    r"|товар|упаковк|этикет|маркетплейс|карточк\w* товар|флакон|бутылк",
    re.I,
)
W_REFLECTIVE = re.compile(
    r"chrome|\bglass\b|glassware|transparent(?!\s+(?:background|bg|backdrop))|translucent|glossy|reflective|reflection|mirror|metallic|polished"
    r"|jewel|\bring\b|diamond|\bwatch(?:es)?\b|perfume|\bbottle|crystal|stainless"
    r"|хром|стекл|стеклян|прозрачн(?!\w*\s+фон)|глянц|отраж|зеркал|металлич|полирован|ювелир|кольц|бриллиант|часы|часов\b"
    r"|духи|парфюм|флакон|бутылк|хрустал",
    re.I,
)
W_ANIMATION_TWOS = re.compile(
    r"\banime\b|cartoon|hand-?drawn|\b2d animation|cel animation|on twos|on threes|limited animation|traditional animation"
    r"|аниме|мульт\w*|рисованн\w*|двойками|покадров\w* рисов",
    re.I,
)
W_CINE_FILM = re.compile(
    r"\b8 ?mm\b|super ?8|\b16 ?mm\b|silent film|cine film|home movies? on film|film reel|кинопл[её]нк|\b8-?мм\b|супер ?8"
    r"|\b16-?мм\b|немое кино|любительск\w* кино",
    re.I,
)
W_ARCHIVAL = re.compile(
    r"archiv|historic|vintage|old (?:photo|film|footage|family|video)|grandparent|ww(?:i|ii|1|2)\b|world war|19[0-7]\ds"
    r"|архив|историческ|старин|стар\w+ (?:фото|снимк|плёнк|пленк|видео|кадр)|дедушк|бабушк|войн",
    re.I,
)
W_SINGING = re.compile(
    r"\bsing(?:s|ing)?\b|\bsong\b|\blyrics?\b|vocals?\b|\bkaraoke\b|\bchorus\b|music video|поёт|поет|пою|петь|песн|вокал"
    r"|караоке|припев|клип",
    re.I,
)
W_SLIDES = re.compile(
    r"\bslides?\b|slide ?deck|presentation|powerpoint|keynote deck|screen ?record|screencast|screen capture|\bdemo of (?:the|our) (?:app|ui)"
    r"|\bui\b|dashboard|software walkthrough|слайд|презентац|запис\w* экрана|скринкаст|интерфейс",
    re.I,
)
W_TELEPHONY = re.compile(
    r"\bivr\b|phone (?:line|menu|system|tree)|telephon|call[- ]cent|hold (?:music|message)|on-hold|voicemail|\bpbx\b"
    r"|asterisk|switchboard|автоответ|телефон|колл-?центр|голосов\w+ меню|ожидани\w+ на линии",
    re.I,
)
W_PODCAST = re.compile(r"podcast|подкаст", re.I)
W_BROADCAST = re.compile(
    r"\bbroadcast|\btv (?:spot|commercial|ad|channel|air)|television|on[- ]air|\bairing\b|телеэфир|эфир\w*|телевиз|телеканал"
    r"|рекламн\w+ ролик\w* (?:для|на) тв",
    re.I,
)
W_LOOP = re.compile(
    r"\bloop(?:s|ed|ing|able)?\b|seamless|cinemagraph|endless|repeat(?:s|ing)? forever|зациклен|зацикл|бесшовн|бесконечн\w+ (?:видео|анимац)|луп",
    re.I,
)
W_KIDS = re.compile(
    r"\bkids?\b|children|child(?:ren)?'s|toddler|preschool|nursery|for babies|baby (?:song|video)|made for kids|\bcoppa\b"
    r"|для детей|детск|малыш|дошкольн|ясел|колыбельн",
    re.I,
)
W_EDGE = re.compile(
    r"jetson|\borin\b|xavier|raspberry|\brpi\b|\bpi ?[3-5]\b|orange ?pi|rock ?pi|rk3588|coral|edge (?:device|tpu)|hailo"
    r"|одноплат|малин",
    re.I,
)
W_AUDIO_CLEAN = re.compile(
    r"denois|noise reduc|background noise|remove (?:the )?(?:noise|hum|hiss|echo|reverb)|\bhum\b|\bhiss\b|\becho\b|reverb|muffled"
    r"|clean up (?:the )?(?:audio|sound|voice)|enhance (?:the )?(?:audio|speech|voice)|шумодав|убрать шум|шум\w* (?:на|в) (?:записи|фоне)"
    r"|\bгул\b|шипени|\bэхо\b|реверб|почистить звук|очистить звук|улучшить звук",
    re.I,
)
W_INTERVIEW = re.compile(r"interview|podcast|panel|meeting|conversation|dialogue|интервью|подкаст|встреч|совещани|диалог|беседа", re.I)
W_DIALOGUE = re.compile(
    r"dialogue|conversation|two voices|several voices|multiple voices|characters? (?:talk|speak)|audiobook with voices"
    r"|диалог|разговор|два голоса|несколько голосов|по ролям",
    re.I,
)
W_HDR = re.compile(r"\bhdr\b|dolby vision|hdr10|rec\.? ?2020|bt\.? ?2020|\bhlg\b", re.I)
W_PLATFORM = re.compile(
    r"youtube|tiktok|instagram|\breels?\b|\bshorts\b|linkedin|facebook|vk\b|вконтакте|ютуб|тикток|инстаграм|рилс", re.I
)
W_REALISTIC = re.compile(
    r"photoreal|realistic|lifelike|real person|real people|looks real|deepfake|likeness|фотореал|реалистичн|как настоящ|реальн\w+ человек",
    re.I,
)

# --- the rule --------------------------------------------------------------------------

Trigger = Callable[[Ctx], "Mapping[str, str] | bool | None"]


@dataclass(frozen=True)
class Rule:
    """One checklist line: when it fires, what it says (EN/RU), on what it rests."""

    id: str
    #: Job codes the rule belongs to (empty: a condition of any plan with steps).
    jobs: frozenset[str]
    en: str
    ru: str
    tag: str
    trigger: Trigger
    #: Structured spec fields the trigger reads.
    reads: tuple[str, ...] = ()
    #: Spec field that WOULD carry a condition now read from the words ("" — none needed).
    spec_field: str = ""
    sources: tuple[str, ...] = field(default_factory=tuple)

    def fire(self, ctx: Ctx) -> dict[str, str] | None:
        if self.jobs and not (self.jobs & ctx.jobs):
            return None
        got = self.trigger(ctx)
        if not got:
            return None
        return dict(got) if isinstance(got, Mapping) else {}


def _always(_: Ctx) -> bool:
    return True


# --- triggers (structured fields first; the words only where the spec has no field) ------


def _people_or_text(c: Ctx) -> bool:
    return c.speakers >= 1 or c.says(W_PEOPLE) or c.says(W_TEXT_IN_FRAME)


def _profile(c: Ctx) -> bool:
    return c.says(W_PROFILE)


def _multi_voice(c: Ctx) -> dict[str, str] | None:
    if c.speakers >= MULTI_VOICE_MIN:
        return {"n": str(c.speakers)}
    if c.says(W_DIALOGUE):
        return {"n": "2+"}
    return None


def _clone_or_cloned_dub(c: Ctx) -> bool:
    return "voice_clone" in c.jobs


def _music_long(c: Ctx) -> dict[str, str] | None:
    s = c.seconds
    return {"seconds": f"{s:g}"} if s > MUSIC_RUN_MAX_S else None


def _long_audio(c: Ctx) -> dict[str, str] | None:
    s = c.seconds
    return {"seconds": f"{s:g}"} if s > LONG_AUDIO_S else None


def _sfx_on_video(c: Ctx) -> bool:
    return "video" in c.spec.inputs or "video" in c.outputs


def _audio_clean(c: Ctx) -> bool:
    return bool({"audio", "video"} & set(c.spec.inputs)) and c.says(W_AUDIO_CLEAN)


def _archival(c: Ctx) -> bool:
    return "colorize" in c.jobs or c.says(W_ARCHIVAL)


def _twos(c: Ctx) -> bool:
    return c.says(W_ANIMATION_TWOS)


def _cine(c: Ctx) -> bool:
    return c.says(W_CINE_FILM)


def _vertical(c: Ctx) -> bool:
    return c.video and (str(c.spec.aspect or "").replace(" ", "") == "9:16" or "shorts" in c.jobs)


def _shorts_no_text_output(c: Ctx) -> bool:
    return "text" not in c.outputs


def _turntable_video(c: Ctx) -> bool:
    """A turntable VIDEO is made (not a 3D mesh the route chose instead)."""
    return "оборот_360" in c.steps or ("модель_3d" not in c.steps and "turntable" in c.jobs)


def _reflective(c: Ctx) -> bool:
    return c.says(W_REFLECTIVE)


def _product(c: Ctx) -> bool:
    return "photo" in c.spec.inputs and c.says(W_PRODUCT)


def _rtl_visual(c: Ctx) -> dict[str, str] | None:
    rtl = sorted(c.langs & RTL_LANGS)
    if rtl and (c.visual or c.jobs & {"transcribe", "captions"}):
        return {"langs": ", ".join(rtl)}
    return None


def _rtl_tts(c: Ctx) -> dict[str, str] | None:
    д = sorted(c.langs & DIACRITIC_LANGS)
    return {"langs": ", ".join(д)} if д else None


def _cjk_visual(c: Ctx) -> dict[str, str] | None:
    cjk = sorted(c.langs & CJK_LANGS)
    if cjk and (c.visual or c.jobs & {"transcribe", "captions"}):
        return {"langs": ", ".join(cjk)}
    return None


def _telephony(c: Ctx) -> bool:
    return c.says(W_TELEPHONY)


def _podcast(c: Ctx) -> bool:
    return c.says(W_PODCAST)


def _broadcast(c: Ctx) -> bool:
    return c.says(W_BROADCAST)


def _loop(c: Ctx) -> bool:
    return c.says(W_LOOP)


def _transitions(c: Ctx) -> dict[str, str] | None:
    n = int(c.spec.shots or 0)
    return {"shots": str(n)} if n >= TRANSITION_MIN_SHOTS else None


def _series(c: Ctx) -> bool:
    if "series" in c.jobs or "r2v" in c.jobs:
        return True
    return int(c.spec.shots or 0) >= SERIES_MIN_SHOTS and (c.speakers >= 1 or bool(c.spec.characters))


def _kids(c: Ctx) -> bool:
    return bool(c.steps or c.jobs) and c.says(W_KIDS)


def _realistic_people(c: Ctx) -> bool:
    real = any(п.get("real") is True for п in c.spec.people)
    return (real and bool(c.jobs & (VIDEO_GEN | FACE_SYNC | STILL_GEN | {"char_replace", "voice_clone", "dub", "v2v_edit"}))) or (
        bool(c.jobs & (VIDEO_GEN | STILL_GEN)) and c.says(W_REALISTIC)
    )


def _edge(c: Ctx) -> dict[str, str] | None:
    sh = c.self_host
    gpu = str(sh.get("gpu") or "")
    if sh and (sh.get("platform") == "cpu" or W_EDGE.search(gpu)):
        return {"gpu": gpu or "CPU"}
    if sh and c.says(W_EDGE):
        return {"gpu": gpu or "edge"}
    return None


def _low_vram(c: Ctx) -> dict[str, str] | None:
    vram = c.self_host.get("vram_gb")
    if vram is not None and 0 < float(vram) <= LOW_VRAM_GB:
        return {"vram": f"{float(vram):g}"}
    return None


def _self_host(c: Ctx) -> bool:
    return bool(c.self_host) and bool(c.steps)


def _bulk(c: Ctx) -> dict[str, str] | None:
    n = max(int(c.spec.shots or 0), sum(int(з.get("count") or 0) for з in c.spec.input_items))
    return {"n": str(n)} if n >= BULK_ITEMS else None


def _eight_k(c: Ctx) -> bool:
    return delivery.eight_k(c.spec) and bool(c.steps)


def _diarize(c: Ctx) -> dict[str, str] | None:
    if c.speakers >= MULTI_VOICE_MIN:
        return {"n": str(c.speakers)}
    return {"n": "2+"} if c.says(W_INTERVIEW) else None


#: Recipe priors that already composite the brand mark (then the logo note is not repeated).
LOGO_PRIORS = frozenset({"logo_overlay", "logo_image_is_endcard"})


def _logo_motion(c: Ctx) -> bool:
    if c.priors & LOGO_PRIORS:
        return False
    return bool(c.jobs & {"t2v", "i2v"}) and bool(re.search(r"\blogo|логотип", c.text))


def _platform(c: Ctx) -> bool:
    return c.video and (c.says(W_PLATFORM) or "shorts" in c.jobs)


def _mixed_audio(c: Ctx) -> bool:
    return c.video and bool(c.jobs & {"tts", "music", "sfx", "dub"})


def _many_video_makers(c: Ctx) -> bool:
    makers = c.steps & {"генерация_видео", "оживление", "видео_по_референсу", "говорящий_аватар", "видео_со_звуком", "липсинк"}
    return len(makers) >= 2


def _hdr(c: Ctx) -> bool:
    return c.video and c.says(W_HDR)


def _singing(c: Ctx) -> bool:
    return "sing" in c.jobs or c.says(W_SINGING)


def _slides(c: Ctx) -> bool:
    return c.says(W_SLIDES)


def _translation(c: Ctx) -> dict[str, str] | None:
    if "dub" in c.jobs:
        return {"langs": ", ".join(sorted(c.langs)) or "target"}
    if len(c.langs) >= 2 and c.jobs & (SPEECH_MAKE | {"captions", "shorts", "transcribe", "avatar"}):
        return {"langs": ", ".join(sorted(c.langs))}
    return None


def _speech_steps(c: Ctx) -> bool:
    return bool(c.jobs & {"tts", "dub"}) or ("avatar" in c.jobs and "audio" not in c.spec.inputs)


# --- sources ----------------------------------------------------------------------------

S_EBU_R128 = "https://tech.ebu.ch/publications/r128"
S_CALM = "https://www.fcc.gov/media/policy/loud-commercials"
S_APPLE_PODCAST = "https://podcasters.apple.com/support/893-audio-requirements"
S_G711 = "https://www.itu.int/rec/T-REC-G.711"
S_BIDI = "https://www.unicode.org/reports/tr9/"
S_JLREQ = "https://www.w3.org/TR/jlreq/"
S_NETFLIX_TT = (
    "https://partnerhelp.netflixstudios.com/hc/en-us/articles/215758617-Timed-Text-Style-Guide-General-Requirements"
)
S_YT_SYNTHETIC = "https://support.google.com/youtube/answer/14328491"
S_YT_KIDS = "https://support.google.com/youtube/answer/9528076"
S_COPPA = "https://www.ftc.gov/legal-library/browse/rules/childrens-online-privacy-protection-rule-coppa"
S_TIKTOK_AI = "https://support.tiktok.com/en/using-tiktok/creating-videos/ai-generated-content"
S_C2PA = "https://c2pa.org/specifications/"
S_ELEVEN_POLICY = "https://elevenlabs.io/use-policy"
S_CPML = "https://coqui.ai/cpml"
S_SPOTIFY_LOUD = "https://support.spotify.com/us/artists/article/loudness-normalization/"
S_FFMPEG_FILTERS = "https://ffmpeg.org/ffmpeg-filters.html"
S_DEMUCS = "https://github.com/facebookresearch/demucs"
S_TENSORRT = "https://developer.nvidia.com/tensorrt"
S_BT709 = "https://www.itu.int/rec/R-REC-BT.709"
S_BT2100 = "https://www.itu.int/rec/R-REC-BT.2100"

# --- the checklist ----------------------------------------------------------------------

E, R, P = TAG_ENGINEERING, TAG_REGULATION, TAG_PLATFORM


def _r(
    id: str,
    jobs: Sequence[str],
    en: str,
    ru: str,
    tag: str,
    trigger: Trigger = _always,
    reads: Sequence[str] = ("task", "steps"),
    spec_field: str = "",
    sources: Sequence[str] = (),
) -> Rule:
    return Rule(id, frozenset(jobs), en, ru, tag, trigger, tuple(reads), spec_field, tuple(sources))


RULES_LIST: tuple[Rule, ...] = (
    # --- generate image ---------------------------------------------------------------
    _r(
        "still_variants_seed",
        ["t2i"],
        "still generation: make 4-8 variants per prompt and pick one, then log the model version, seed and "
        "prompt of the kept image — a later checkpoint or another sampler will not reproduce it",
        "генерация изображения: сделайте 4-8 вариантов на промпт и выберите один, затем запишите версию модели, "
        "сид и промпт выбранного кадра — другой чекпойнт или сэмплер его уже не повторит",
        E,
    ),
    _r(
        "still_anatomy_text_check",
        ["t2i", "image_edit"],
        "check hands, eyes, teeth and any lettering at 100 % before delivery — that is where image models fail "
        "most; fix a bad region by masked inpainting, not by regenerating the whole image",
        "проверьте руки, глаза, зубы и любые надписи в масштабе 100 % до сдачи — именно там модели изображений "
        "ошибаются чаще всего; плохой участок правится дорисовкой по маске, а не новой генерацией всего кадра",
        E,
        _people_or_text,
        ("people", "characters"),
    ),
    _r(
        "product_fidelity",
        ["t2i", "image_edit", "i2v", "t2v", "turntable"],
        "product fidelity: keep the real product pixels (cut it out and composite, or pass the photo as a "
        "reference) and check shape, colour and label text against the actual item — generators 'improve' "
        "packaging and redraw labels",
        "точность товара: сохраняйте настоящие пиксели товара (вырезать и наложить или подать фото как референс) "
        "и сверяйте форму, цвет и текст этикетки с настоящим товаром — генераторы «улучшают» упаковку и "
        "перерисовывают этикетки",
        E,
        _product,
        ("inputs",),
        "spec.subject = 'product'",
    ),
    # --- generate video / animate -----------------------------------------------------------
    _r(
        "video_takes",
        ["t2v", "i2v", "t2v_audio", "r2v", "series"],
        "video generation needs takes: plan 2-4 generations per kept shot (morphing hands, physics glitches, "
        "drifting faces) — the clip price above counts one take per shot, so keep a reserve in the budget",
        "генерация видео требует дублей: закладывайте 2-4 генерации на каждый оставленный шот (плывущие руки, "
        "сбои физики, дрейф лица) — цена ролика выше считает один дубль на шот, держите запас в бюджете",
        E,
    ),
    _r(
        "i2v_first_frame",
        ["i2v"],
        "the photo becomes the first frame: crop it to the delivery aspect and resolution BEFORE animating "
        "(outpaint it if it is too narrow) — cropping after animation loses resolution and cuts the motion",
        "фото становится первым кадром: кадрируйте его под формат и разрешение сдачи ДО оживления (дорисуйте "
        "края, если узко) — кадрирование после оживления теряет разрешение и режет движение",
        E,
    ),
    _r(
        "shot_continuity",
        ["t2v", "i2v", "r2v", "t2v_audio", "series"],
        "{shots} shots: hard cuts are made at assembly; for a continuous move generate shot N+1 from the last "
        "frame of shot N (first/last-frame conditioning), and keep the character reference, wardrobe, palette "
        "and light direction identical across shots",
        "шотов {shots}: жёсткие склейки делаются при сборке; для непрерывного перехода следующий шот "
        "генерируется от последнего кадра предыдущего (условие первого и последнего кадра), а референс "
        "персонажа, одежда, палитра и направление света одинаковы во всех шотах",
        E,
        _transitions,
        ("shots",),
    ),
    _r(
        "frame_rate_conform",
        [],
        "clips from different models arrive at different frame rates (24, 25, 30 fps): conform every shot to "
        "one delivery rate at assembly before cutting, otherwise motion judders at the joins",
        "ролики разных моделей приходят с разной частотой кадров (24, 25, 30): приведите все шоты к одной "
        "частоте сдачи при сборке до монтажа, иначе на стыках движение дёргается",
        E,
        _many_video_makers,
        ("steps",),
    ),
    _r(
        "seamless_loop",
        ["t2v", "i2v", "music", "visualiser", "t2v_audio", "turntable"],
        "seamless loop: make the last frame meet the first (first/last-frame conditioning, or crossfade the "
        "tail into the head) and watch the join at full speed; for audio, cut the loop on a bar line at zero "
        "crossings",
        "бесшовный цикл: последний кадр должен сходиться с первым (условие первого и последнего кадра или "
        "наплыв хвоста в начало), стык проверяется на полной скорости; звук режется по границе такта в нуле "
        "волны",
        E,
        _loop,
        (),
        "spec.delivery.loop = true",
        (S_FFMPEG_FILTERS,),
    ),
    _r(
        "logo_motion_vector",
        ["t2v", "i2v"],
        "an animated logo is made from the vector file (After Effects, Lottie or Blender) or composited over "
        "the generated motion — generative video distorts the mark from frame to frame",
        "анимированный логотип делается из векторного файла (After Effects, Lottie или Blender) или "
        "накладывается поверх сгенерированного движения — генеративное видео искажает знак от кадра к кадру",
        E,
        _logo_motion,
        ("conditions",),
    ),
    _r(
        "character_sheet",
        [],
        "a recurring character is locked with a reference sheet (front, three-quarter, profile; fixed outfit "
        "and palette) and the same reference images, LoRA or seed in every episode — compare identity side by "
        "side across episodes",
        "повторяющийся персонаж фиксируется листом референсов (анфас, три четверти, профиль; одна одежда и "
        "палитра) и одними и теми же референсами, LoRA или сидом во всех сериях — сверяйте лицо бок о бок "
        "между сериями",
        E,
        _series,
        ("task", "shots", "characters", "people"),
    ),
    # --- avatar / lip sync / singing -----------------------------------------------------
    _r(
        "avatar_reference_photo",
        ["avatar", "sing"],
        "reference photo for a talking avatar: frontal or three-quarter, even light, mouth closed, nothing over "
        "the face, the face at least ~512 px tall — a profile, sunglasses or a hand at the mouth break the "
        "mouth region",
        "фото для говорящего аватара: анфас или три четверти, ровный свет, рот закрыт, ничего не закрывает "
        "лицо, лицо не меньше ~512 px по высоте — профиль, тёмные очки или рука у рта ломают область рта",
        E,
    ),
    _r(
        "lipsync_face_crop",
        ["lipsync"],
        "lip sync runs on a face crop (typically 256-512 px): the face is detected and tracked, the mouth "
        "region is regenerated, and the crop is blended back onto the full-resolution plate with a feathered "
        "mask — check the seam, teeth and chin line at 100 %; a face under ~100 px syncs poorly",
        "липсинк работает на вырезке лица (обычно 256-512 px): лицо находится и ведётся трекингом, область рта "
        "перерисовывается, и вырезка вклеивается обратно в кадр полного разрешения по мягкой маске — проверьте "
        "шов, зубы и линию подбородка в 100 %; лицо меньше ~100 px синхронизируется плохо",
        E,
    ),
    _r(
        "lipsync_hard_faces",
        ["lipsync", "avatar", "sing", "dub"],
        "profile, occluded or bearded mouths are the hardest case for lip-sync models: test a 5 s piece "
        "first; frontal, well-lit shots sync best",
        "лицо в профиль, закрытый или бородатый рот — самый трудный случай для липсинка: сначала проверьте "
        "отрезок в 5 с; лучше всего синхронизируются фронтальные хорошо освещённые планы",
        E,
        _profile,
        ("conditions",),
    ),
    _r(
        "singing_vocal_stem",
        ["sing", "lipsync", "avatar"],
        "singing: isolate the vocal stem first (source separation) and drive the face with the vocal only, "
        "then lay the full mix back — models trained on speech mis-shape long held vowels and fast phrases, "
        "so check the chorus",
        "пение: сначала отделите дорожку вокала (разделение источников) и ведите лицо только по вокалу, затем "
        "верните полный микс — модели, обученные на речи, искажают долгие гласные и быстрые фразы; проверьте "
        "припев",
        E,
        _singing,
        ("task",),
        "spec.audio_content = 'song'",
        (S_DEMUCS,),
    ),
    _r(
        "slides_screen_real",
        [],
        "slides and screen content stay real: composite the actual slides or screen capture as a layer "
        "(picture-in-picture beside the presenter) instead of generating them — generators garble text and "
        "upscalers smear interface fonts; export slides at the delivery resolution",
        "слайды и содержимое экрана остаются настоящими: накладывайте сами слайды или запись экрана слоем "
        "(картинка в картинке рядом с ведущим), а не генерируйте их — генераторы коверкают текст, апскейл "
        "размывает шрифты интерфейса; выгружайте слайды в разрешении сдачи",
        E,
        _slides,
        (),
        "spec.inputs[].kind = 'slides' | 'screen-recording'",
    ),
    # --- speech: tts, dub, voice clone ------------------------------------------------------
    _r(
        "tts_pronunciation",
        ["tts", "dub", "avatar"],
        "check names, brands, numbers, dates and abbreviations in the voiced take: fix them with a "
        "pronunciation dictionary, SSML phonemes or a respelling in the script; render at 44.1/48 kHz and keep "
        "the WAV master",
        "проверьте в озвучке имена, бренды, числа, даты и сокращения: исправляются словарём произношений, "
        "фонемами SSML или переписанным написанием в тексте; рендер 44,1/48 кГц, мастер хранится в WAV",
        E,
        _speech_steps,
        ("task", "inputs"),
    ),
    _r(
        "voice_casting",
        ["tts", "dub", "avatar", "t2v_audio"],
        "{n} voices: cast one fixed voice per character, render each line with that voice separately, and "
        "assemble the dialogue on a timeline (pauses, overlaps) — one voice reading every part is the common "
        "failure",
        "голосов {n}: на каждого персонажа один закреплённый голос, каждая реплика рендерится этим голосом "
        "отдельно, а диалог собирается на таймлайне (паузы, перебивки) — один голос на все роли — частая ошибка",
        E,
        _multi_voice,
        ("people", "characters"),
    ),
    _r(
        "rtl_tts_diacritics",
        ["tts", "dub", "avatar", "t2v_audio", "voice_clone"],
        "{langs}: these scripts are written without short vowels, so TTS guesses ambiguous words — add "
        "diacritics (tashkeel / niqqud) or a phonetic respelling on names and ambiguous words, and have a native "
        "speaker check the take",
        "{langs}: эти письменности пишутся без кратких гласных, и синтез речи угадывает неоднозначные слова — "
        "расставьте огласовки (ташкиль, никуд) или фонетическое написание на именах и неоднозначных словах и "
        "дайте послушать носителю",
        E,
        _rtl_tts,
        ("languages", "language_tags"),
    ),
    _r(
        "dub_time_fit",
        ["dub"],
        "translated speech runs longer than the source (often 10-30 % from English into Russian, German or "
        "Spanish): the translation is time-fitted line by line to the original timing (shorter wording or a "
        "speed of at most ~1.15x) so lips and cuts still match",
        "переведённая речь длиннее исходной (часто на 10-30 % с английского на русский, немецкий, испанский): "
        "перевод подгоняется по времени построчно к исходному таймингу (короче формулировка или ускорение не "
        "больше ~1,15x), чтобы губы и склейки совпадали",
        E,
    ),
    _r(
        "dub_music_effects",
        ["dub"],
        "dubbing keeps the original music and effects: separate dialogue from the background (source "
        "separation, e.g. Demucs), replace only the voice, and remix it over the original music-and-effects bed",
        "дубляж сохраняет исходную музыку и шумы: диалог отделяется от фона (разделение источников, например "
        "Demucs), заменяется только голос, и он сводится поверх исходной подложки музыки и шумов",
        E,
        sources=(S_DEMUCS,),
    ),
    _r(
        "translation_review",
        [],
        "translation ({langs}): machine translation is reviewed by a native speaker before it is voiced or "
        "burned in — names, numbers, brand terms (keep a glossary) and the form of address",
        "перевод ({langs}): машинный перевод вычитывает носитель до озвучки или вжигания — имена, числа, "
        "термины бренда (держите глоссарий) и форма обращения",
        E,
        _translation,
        ("languages", "language_tags", "task"),
    ),
    _r(
        "voice_clone_consent",
        ["voice_clone"],
        "a voice clone needs the speaker's documented consent (the voice services' terms require it) and a "
        "clean sample: 1-3 min of one speaker, no music, no reverb, no noise",
        "клон голоса требует подтверждённого согласия владельца голоса (этого требуют условия сервисов) и "
        "чистого образца: 1-3 минуты одного говорящего, без музыки, без эха, без шума",
        P,
        _clone_or_cloned_dub,
        ("task", "steps"),
        sources=(S_ELEVEN_POLICY,),
    ),
    _r(
        "voice_licence",
        ["tts", "voice_clone", "dub"],
        "voice licence: commercial use of a stock or cloned voice depends on the service plan, and some open TTS "
        "weights are non-commercial (e.g. XTTS-v2 under the Coqui Public Model License) — check the voice's "
        "terms for ads and monetised video",
        "лицензия голоса: коммерческое использование готового или клонированного голоса зависит от тарифа "
        "сервиса, а часть открытых весов синтеза речи — только некоммерческие (например, XTTS-v2 по лицензии "
        "Coqui CPML) — проверьте условия голоса для рекламы и монетизированного видео",
        P,
        sources=(S_CPML,),
    ),
    _r(
        "long_audio_chunks",
        ["tts", "transcribe", "dub"],
        "long audio ({seconds} s): speech is rendered in chunks at paragraph boundaries with the same voice "
        "settings and stitched at pauses with short crossfades (10-50 ms) — listen for level and tone jumps at "
        "every join; transcription runs on voice-activity segments",
        "длинный звук ({seconds} с): речь рендерится кусками по границам абзацев с одними настройками голоса и "
        "склеивается в паузах короткими наплывами (10-50 мс) — слушайте скачки громкости и тембра на каждом "
        "стыке; расшифровка идёт по отрезкам с речью",
        E,
        _long_audio,
        ("duration_s", "inputs"),
        sources=(S_FFMPEG_FILTERS,),
    ),
    # --- audio delivery -----------------------------------------------------------------------
    _r(
        "telephony_audio",
        [],
        "telephony delivery: 8 kHz mono, 16-bit PCM or G.711 mu-law / A-law WAV — resample from the 44.1/48 kHz "
        "master with a low-pass (anti-aliasing), and check intelligibility in the 300-3400 Hz phone band "
        "(sibilants and low voices suffer)",
        "доставка в телефонию: 8 кГц моно, 16-битный PCM или WAV G.711 mu-law / A-law — пересэмплируйте из "
        "мастера 44,1/48 кГц с фильтром низких частот (против алиасинга) и проверьте разборчивость в полосе "
        "телефона 300-3400 Гц (страдают шипящие и низкие голоса)",
        P,
        _telephony,
        (),
        "spec.delivery.platform = 'telephony'",
        (S_G711,),
    ),
    _r(
        "podcast_loudness",
        [],
        "podcast master: -16 LUFS integrated (stereo; about -19 for mono), true peak at most -1 dBTP, dialogue "
        "denoised and levelled; MP3 128-192 kbps or AAC at 44.1 kHz",
        "мастер подкаста: -16 LUFS интегрально (стерео; около -19 для моно), истинный пик не выше -1 dBTP, "
        "речь очищена от шума и выровнена; MP3 128-192 кбит/с или AAC 44,1 кГц",
        P,
        _podcast,
        (),
        "spec.delivery.platform = 'podcast'",
        (S_APPLE_PODCAST, S_FFMPEG_FILTERS),
    ),
    _r(
        "broadcast_loudness",
        [],
        "broadcast master: EBU R128 -23 LUFS +-0.5 LU, true peak at most -1 dBTP (US: ATSC A/85 -24 LKFS under "
        "the CALM Act); deliver the channel's closed captions and file spec as well",
        "мастер для эфира: EBU R128 -23 LUFS +-0,5 LU, истинный пик не выше -1 dBTP (США: ATSC A/85 -24 LKFS по "
        "закону CALM); плюс скрытые субтитры и формат файла, которые требует канал",
        R,
        _broadcast,
        (),
        "spec.delivery.platform = 'broadcast'",
        (S_EBU_R128, S_CALM),
    ),
    _r(
        "audio_mix_48k",
        [],
        "mix generated audio at 48 kHz (the video standard): voices and music often arrive at 22.05-44.1 kHz — "
        "resample before mixing, set the music under the voice (ducking) and leave -1 dBTP headroom",
        "сводите сгенерированный звук на 48 кГц (стандарт видео): голос и музыка часто приходят в 22,05-44,1 "
        "кГц — пересэмплируйте до сведения, приглушайте музыку под голосом и оставьте запас -1 dBTP",
        E,
        _mixed_audio,
        ("outputs", "steps"),
    ),
    _r(
        "audio_cleanup_chain",
        [],
        "audio clean-up order: hum notch (50/60 Hz) -> broadband denoise -> de-reverb -> de-ess -> levelling "
        "and loudness; push denoise gently — over-processing gives 'underwater' artefacts on the voice; keep "
        "the untouched original",
        "порядок чистки звука: режекция гула (50/60 Гц) -> широкополосный шумодав -> подавление эха -> "
        "де-эссер -> выравнивание и громкость; шумодав мягко — пережатый голос звучит «из-под воды»; "
        "оригинал хранится нетронутым",
        E,
        _audio_clean,
        ("inputs",),
        "spec.task = 'audio-cleanup' (or spec.edit = ['denoise-audio'])",
    ),
    # --- music / sfx / visualiser --------------------------------------------------------------
    _r(
        "music_to_length",
        ["music"],
        "generated music is made to length: ask for the exact duration and tempo (BPM), cut on bar lines and "
        "fade the end; ask for stems if the service gives them, so the mix can duck under a voice",
        "сгенерированная музыка делается в размер: задайте точную длительность и темп (BPM), режьте по "
        "границам тактов и уводите конец в затухание; берите стемы, если сервис их отдаёт, чтобы музыку можно "
        "было приглушить под голос",
        E,
    ),
    _r(
        "music_sections",
        ["music", "visualiser"],
        "a {seconds} s track is longer than one music-model run (about 3-4 min): build it in sections "
        "(intro, verse, chorus) with the same prompt and style, extend from the previous section where the "
        "model supports it, and join on a downbeat with a 1-2 bar crossfade",
        "трек на {seconds} с длиннее одного прогона музыкальной модели (около 3-4 минут): соберите его частями "
        "(вступление, куплет, припев) с одним промптом и стилем, продлевайте от предыдущей части, где модель "
        "это умеет, и склеивайте на сильную долю наплывом в 1-2 такта",
        E,
        _music_long,
        ("duration_s",),
    ),
    _r(
        "music_master_loudness",
        ["music"],
        "master the track for where it plays: streaming services normalise to about -14 LUFS integrated with a "
        "true peak at most -1 dBTP — export a 48 kHz / 24-bit WAV master and a loudness-normalised copy",
        "мастеринг под площадку: стриминги нормализуют громкость примерно к -14 LUFS интегрально при "
        "истинном пике не выше -1 dBTP — выгрузите мастер WAV 48 кГц / 24 бит и копию с нормализованной "
        "громкостью",
        P,
        sources=(S_SPOTIFY_LOUD,),
    ),
    _r(
        "sfx_layers",
        ["sfx"],
        "sound effects are generated one effect per call and placed on the edit timeline at the picture's hit "
        "points, layered and kept as separate stems — one generated 'whole soundscape' cannot be re-timed",
        "звуковые эффекты генерируются по одному на вызов и ставятся на таймлайн монтажа в точки удара по "
        "изображению, слоями и отдельными стемами — один сгенерированный «весь фон» уже не перетаймить",
        E,
    ),
    _r(
        "sfx_sync_check",
        ["sfx"],
        "video-to-audio models put a sound near, not exactly on, the hit: check impacts and footsteps frame by "
        "frame and nudge them on the timeline at assembly",
        "модели «видео в звук» ставят звук рядом с ударом, а не точно на него: проверьте удары и шаги по "
        "кадрам и сдвиньте их на таймлайне при сборке",
        E,
        _sfx_on_video,
        ("inputs", "outputs"),
    ),
    # --- edits ---------------------------------------------------------------------------------
    _r(
        "image_edit_masked",
        ["image_edit"],
        "a local image edit is masked: only the masked region is regenerated and the rest stays pixel-identical — "
        "compare before and after at 100 % for colour shift and texture drift at the mask edge",
        "локальная правка изображения идёт по маске: перерисовывается только область под маской, остальное "
        "остаётся пиксель в пиксель — сравните до и после в 100 % на сдвиг цвета и текстуры у края маски",
        E,
    ),
    _r(
        "video_edit_temporal",
        ["v2v_edit", "char_replace"],
        "video-to-video edits flicker and drift between frames: edit only the shot or segment that needs it, "
        "check temporal consistency at full speed, and cut it back into the untouched original",
        "правки «видео в видео» мерцают и плывут между кадрами: правьте только тот шот или отрезок, который "
        "нужно, проверяйте устойчивость во времени на полной скорости и вклеивайте обратно в нетронутый "
        "оригинал",
        E,
    ),
    _r(
        "face_swap_match",
        ["char_replace"],
        "face or character replacement: match light direction and skin tone, and expect breaks where hands, "
        "hair or glasses cross the face and on profile turns — check those frames one by one",
        "замена лица или персонажа: совпадение направления света и тона кожи, а сбои ждите там, где руки, "
        "волосы или очки пересекают лицо, и на поворотах в профиль — проверьте эти кадры по одному",
        E,
    ),
    # --- restore / colourise / upscale / fps ---------------------------------------------------
    _r(
        "restore_chain",
        ["restore"],
        "restoration order: deinterlace (tape) -> stabilise -> deflicker -> dust and scratch removal -> denoise "
        "-> face restoration -> upscale -> colour grade; face restoration changes identity, so compare faces "
        "with the source",
        "порядок реставрации: деинтерлейс (кассета) -> стабилизация -> устранение мерцания -> пыль и царапины "
        "-> шумодав -> восстановление лиц -> апскейл -> цветокоррекция; восстановление лиц меняет черты, "
        "сверяйте лица с исходником",
        E,
    ),
    _r(
        "restore_grain",
        ["restore", "colorize", "upscale", "upscale_video"],
        "restoration strips film grain and leaves a plastic look: re-add light grain at the end for archival "
        "material, and keep the untouched scan as the master",
        "реставрация снимает плёночное зерно и даёт «пластиковую» картинку: для архивного материала добавьте "
        "лёгкое зерно в конце и храните нетронутый скан как мастер",
        E,
        _archival,
        ("task",),
        "spec.source.era = 'archival'",
    ),
    _r(
        "archival_ai_disclosure",
        ["colorize", "restore"],
        "AI-altered archival material (colourised, restored, faces enhanced) is labelled as such where it is "
        "published — 'colourised / restored with AI': the colours and recovered detail are a model's guess, "
        "not a record",
        "архивный материал, изменённый ИИ (раскрашен, отреставрирован, лица восстановлены), помечается так там, "
        "где публикуется, — «раскрашено / восстановлено ИИ»: цвета и детали — догадка модели, а не документ",
        P,
        _archival,
        ("task",),
        "spec.source.era = 'archival'",
        (S_YT_SYNTHETIC,),
    ),
    _r(
        "colorize_reference",
        ["colorize"],
        "colourisation guesses colours: uniforms, flags, brand colours and skin tones need reference images or "
        "a colour note per object, and the result is checked against them",
        "раскраска угадывает цвета: форма, флаги, фирменные цвета и тон кожи требуют референсов или цветовой "
        "пометки на каждый объект, и результат сверяется с ними",
        E,
    ),
    _r(
        "upscale_faithful",
        ["upscale", "upscale_video", "upscale_image"],
        "an upscaler invents texture: use a faithful (low-creativity) setting for faces, text and products and a "
        "creative one only for textures; upscale by an integer factor (2x / 4x) and downscale to the delivery "
        "frame",
        "апскейл придумывает текстуру: для лиц, текста и товара — точный режим (низкая творческость), "
        "творческий — только для фактур; увеличивайте в целое число раз (2x / 4x) и уменьшайте до кадра сдачи",
        E,
    ),
    _r(
        "interp_scene_cuts",
        ["interpolate"],
        "interpolate per shot: across a scene cut the interpolator morphs two shots into a blended frame — "
        "split at cuts (scene detection) first, interpolate each shot, then join",
        "интерполяция идёт по шотам: на склейке интерполятор смешивает два плана в «плавленый» кадр — "
        "сначала разрежьте по склейкам (детекция сцен), интерполируйте каждый шот, затем склейте",
        E,
        sources=(S_FFMPEG_FILTERS,),
    ),
    _r(
        "interp_limited_animation",
        ["interpolate", "upscale", "upscale_video"],
        "animation drawn on twos or threes holds each drawing for 2-3 frames: interpolating it morphs between "
        "drawings and destroys the held-pose timing — drop held duplicates first (ffmpeg mpdecimate) and "
        "interpolate only where you want in-betweens, or leave limited animation as it is",
        "рисованная анимация «двойками» или «тройками» держит каждый рисунок 2-3 кадра: интерполяция "
        "плавит рисунки друг в друга и ломает выдержку поз — сначала уберите повторы (ffmpeg mpdecimate) и "
        "интерполируйте только там, где нужны промежуточные фазы, или оставьте ограниченную анимацию как есть",
        E,
        _twos,
        (),
        "spec.style = 'limited-animation'",
        (S_FFMPEG_FILTERS,),
    ),
    _r(
        "cine_film_speed",
        ["interpolate", "restore", "upscale", "upscale_video", "colorize"],
        "8 mm, Super 8 and silent film run at 16-18 fps: set the true speed first (otherwise people walk fast), "
        "then interpolate or retime to 24/25 fps",
        "8 мм, Super 8 и немое кино сняты на 16-18 кадров/с: сначала выставьте настоящую скорость (иначе "
        "люди ходят быстро), затем интерполируйте или перетаймируйте до 24/25 кадров/с",
        E,
        _cine,
        ("inputs",),
        "spec.inputs[].fps",
    ),
    # --- delivery: shorts, platforms, captions, scripts ----------------------------------------
    _r(
        "vertical_safe_zone",
        [],
        "9:16 delivery: the platform interface covers the top ~10 %, the bottom ~20-25 % and a strip on the "
        "right — keep faces, product and burned captions in the centre safe area; the first 1-2 s are the hook",
        "кадр 9:16: интерфейс площадки закрывает верх ~10 %, низ ~20-25 % и полосу справа — держите лица, "
        "товар и вжигаемые субтитры в центральной безопасной зоне; первые 1-2 секунды — крючок",
        P,
        _vertical,
        ("aspect", "task"),
    ),
    _r(
        "shorts_captions",
        ["shorts"],
        "shorts carry burned-in captions (most viewers watch muted): they are burned at assembly from the timed "
        "transcript, 0 usd, after proofreading",
        "в шортсах субтитры вжигаются (большинство смотрит без звука): при сборке по расшифровке с таймингами, "
        "0 usd, после вычитки",
        E,
        _shorts_no_text_output,
        ("task", "outputs"),
    ),
    _r(
        "captions_reading_speed",
        ["captions", "shorts", "transcribe"],
        "captions: at most 2 lines of about 42 characters, a reading speed of about 17-20 characters per second "
        "and at least 1 s on screen; deliver an SRT/VTT sidecar as well as the burned version",
        "субтитры: не больше 2 строк примерно по 42 знака, скорость чтения около 17-20 знаков в секунду и не "
        "меньше 1 с на экране; отдайте файл SRT/VTT отдельно и версию с вжитыми субтитрами",
        P,
        sources=(S_NETFLIX_TT,),
    ),
    _r(
        "rtl_typesetting",
        [],
        "right-to-left script ({langs}): captions and on-screen text need bidirectional shaping (libass with "
        "HarfBuzz/FriBidi) — Arabic letters join, numbers and Latin words stay left-to-right inside the line; "
        "check line order and punctuation on the final frame and mirror the layout",
        "письмо справа налево ({langs}): субтитры и текст в кадре требуют двунаправленной вёрстки (libass с "
        "HarfBuzz/FriBidi) — арабские буквы соединяются, числа и латиница внутри строки идут слева направо; "
        "проверьте порядок строк и пунктуацию на финальном кадре и отзеркальте раскладку",
        E,
        _rtl_visual,
        ("languages", "language_tags", "outputs"),
        sources=(S_BIDI,),
    ),
    _r(
        "cjk_typesetting",
        [],
        "CJK text ({langs}): there are no spaces to break on — break lines by the kinsoku rules (no closing "
        "punctuation at a line start), use a font with full glyph coverage (Noto CJK class), keep about "
        "13-16 characters per line, and render text as an overlay (generators draw fake characters)",
        "текст CJK ({langs}): пробелов для переноса нет — переносите по правилам кинсоку (закрывающая "
        "пунктуация не начинает строку), берите шрифт с полным набором знаков (класс Noto CJK), около 13-16 "
        "знаков в строке, и текст накладывайте слоем (генераторы рисуют несуществующие иероглифы)",
        E,
        _cjk_visual,
        ("languages", "language_tags", "outputs"),
        sources=(S_JLREQ,),
    ),
    _r(
        "platform_encode",
        [],
        "upload encode: H.264 High profile, yuv420p, constant frame rate, AAC 48 kHz, faststart; stay within "
        "the platform's length and file-size limits",
        "кодирование для загрузки: H.264 High, yuv420p, постоянная частота кадров, AAC 48 кГц, faststart; в "
        "пределах длины и размера файла, которые допускает площадка",
        E,
        _platform,
        ("task", "outputs"),
        "spec.delivery.platform = 'youtube' | 'tiktok' | 'instagram' | …",
    ),
    _r(
        "hdr_delivery",
        [],
        "HDR: generators output SDR (Rec.709); an HDR deliverable is an up-conversion (inverse tone mapping), "
        "not real HDR — grade it on an HDR monitor, tag BT.2100 PQ or HLG at encode, and keep the SDR master",
        "HDR: генераторы отдают SDR (Rec.709); сдача в HDR — это преобразование вверх (обратный тон-маппинг), "
        "а не настоящий HDR — грейдинг на HDR-мониторе, метки BT.2100 PQ или HLG при кодировании, мастер SDR "
        "сохраняется",
        E,
        _hdr,
        ("outputs",),
        "spec.delivery.dynamic_range = 'hdr'",
        (S_BT709, S_BT2100),
    ),
    _r(
        "eight_k_master",
        [],
        "8K delivery: master in a 10-bit intermediate (ProRes 422 HQ or DNxHR HQX — tens of GB per minute) and "
        "deliver HEVC or AV1 10-bit; confirm the target player decodes 8K",
        "сдача в 8K: мастер в 10-битном промежуточном кодеке (ProRes 422 HQ или DNxHR HQX — десятки ГБ на "
        "минуту), выдача в HEVC или AV1 10 бит; убедитесь, что целевой плеер декодирует 8K",
        E,
        _eight_k,
        ("resolution", "aspect"),
    ),
    # --- product 360 / 3D -------------------------------------------------------------------
    _r(
        "turntable_closes",
        ["turntable"],
        "the turn must close: the last frame meets the first, constant angular speed, the product centred on its "
        "axis — check wobble and size 'breathing' across the turn; web 360 viewers take 24-36 frames per turn",
        "оборот должен замыкаться: последний кадр сходится с первым, скорость вращения постоянна, товар по "
        "центру оси — проверьте качание и «дыхание» размера по всему обороту; веб-просмотрщики 360 берут 24-36 "
        "кадров на оборот",
        E,
        _turntable_video,
        ("task", "steps"),
    ),
    _r(
        "reflective_surfaces",
        ["turntable", "3d", "t2v", "i2v", "t2i", "image_edit"],
        "reflective or transparent surfaces: reflections and refraction are where generators fail (reflections "
        "do not move with the turn, glass loses what is behind it, chrome warps) — light on a neutral studio "
        "environment, check reflections through the whole move, and use a 3D render for exact optics",
        "отражающие или прозрачные поверхности: отражения и преломление — слабое место генераторов (отражение "
        "не поворачивается вместе с предметом, стекло теряет то, что за ним, хром гнётся) — нейтральное "
        "студийное окружение, проверка отражений на всём движении, для точной оптики — 3D-рендер",
        E,
        _reflective,
        (),
        "spec.subject.material = 'reflective' | 'transparent'",
    ),
    _r(
        "mesh_cleanup",
        ["3d"],
        "generated meshes are dense triangle soup with lighting baked into the texture: decimate or retopologise "
        "for real time, check UVs and normals, and relight with PBR maps before use in a game or AR",
        "сгенерированные сетки плотные, из треугольников, со светом, запечённым в текстуру: прорядите или "
        "сделайте ретопологию для реального времени, проверьте развёртку и нормали и переосветите с картами "
        "PBR перед игрой или AR",
        E,
    ),
    # --- utilities ------------------------------------------------------------------------------
    _r(
        "asr_review",
        ["transcribe", "captions", "shorts"],
        "speech recognition mishears names, numbers and jargon: pass a vocabulary (initial prompt) with the "
        "names and proofread before publishing; word timestamps drift over music and crosstalk",
        "распознавание речи путает имена, числа и жаргон: передайте словарь (начальный промпт) с именами и "
        "вычитайте до публикации; метки времени слов съезжают на музыке и при перебивках",
        E,
    ),
    _r(
        "diarization",
        ["transcribe", "captions"],
        "{n} speakers: diarization (who speaks when) runs alongside recognition, and the speaker labels are "
        "checked by ear at every change of speaker",
        "говорящих {n}: разметка по говорящим (кто и когда говорит) идёт вместе с распознаванием, а метки "
        "говорящих проверяются на слух на каждой смене",
        E,
        _diarize,
        ("people", "characters"),
    ),
    _r(
        "matte_edges",
        ["bg_remove", "bg_remove_image", "bg_remove_video"],
        "background removal: check hair, fur, motion blur and semi-transparent edges at 100 % on a contrasting "
        "colour; stills go out as PNG or WebP with alpha (JPEG has no transparency)",
        "удаление фона: проверьте волосы, мех, смаз и полупрозрачные края в 100 % на контрастном цвете; "
        "картинки отдаются в PNG или WebP с альфой (JPEG прозрачность не несёт)",
        E,
    ),
    # --- self-host / budget / batch -----------------------------------------------------------
    _r(
        "self_host_gpu_time",
        [],
        "your own hardware: the API cost of each self-hosted step is 0 usd, so the plan price counts no call; "
        "the GPU time per step is a separate estimate (with what the same run would cost on a rented GPU) — "
        "electricity and your own time are not in the price",
        "своё железо: цена API у каждого шага на своём GPU — 0 usd, и цена плана вызовов не считает; время GPU "
        "на шаг — отдельная оценка (и сколько тот же прогон стоил бы на арендованном GPU) — электричество и "
        "ваше время в цену не входят",
        E,
        _self_host,
        ("self_host",),
    ),
    _r(
        "low_vram",
        [],
        "{vram} GB VRAM: load with CPU offload (model or sequential), FP8 or GGUF-quantised weights, VAE tiling "
        "and fewer frames or a lower resolution per run; expect slower runs and compare the quantised output "
        "with the full-precision one",
        "{vram} ГБ видеопамяти: загрузка с выгрузкой на CPU (модельной или последовательной), веса FP8 или "
        "GGUF, тайлинг VAE и меньше кадров или ниже разрешение за прогон; прогоны медленнее, а результат "
        "квантованной модели сверяется с полной точностью",
        E,
        _low_vram,
        ("self_host.vram_gb",),
    ),
    _r(
        "edge_device",
        [],
        "edge device ({gpu}): quantise to INT8/FP16 and export to the device runtime (TensorRT on Jetson, ONNX "
        "Runtime or TFLite on an ARM CPU), keep the models small (Piper-class TTS, whisper tiny/base), and "
        "measure latency and real-time factor on the device — video generation is minutes per clip there, not "
        "real time",
        "устройство на краю сети ({gpu}): квантование в INT8/FP16 и экспорт в среду устройства (TensorRT на "
        "Jetson, ONNX Runtime или TFLite на ARM), маленькие модели (синтез речи класса Piper, whisper tiny/base), "
        "задержку и отношение к реальному времени меряйте на устройстве — генерация видео там идёт минутами "
        "на ролик, не в реальном времени",
        E,
        _edge,
        ("self_host.gpu", "self_host.cpu_only"),
        sources=(S_TENSORRT,),
    ),
    _r(
        "batch_queue",
        [],
        "{n} generations: run them as a batch queue with concurrency limits, retries and idempotent file names; "
        "make and approve a sample of 3-5 first, then run the rest with the same settings and seed policy",
        "генераций {n}: запускайте пакетной очередью с ограничением параллельности, повторами и устойчивыми "
        "именами файлов; сначала сделайте и утвердите образец из 3-5, затем остальное с теми же настройками "
        "и правилом сидов",
        E,
        _bulk,
        ("shots", "inputs"),
    ),
    # --- disclosure / audience ----------------------------------------------------------------
    _r(
        "synthetic_people_disclosure",
        [],
        "realistic AI-made or altered people, voices or events are disclosed where they are published (YouTube "
        "'altered or synthetic content' setting, TikTok 'AI-generated' label), and the file keeps its content "
        "credentials (C2PA) — outside the EU too",
        "реалистичные люди, голоса или события, созданные или изменённые ИИ, раскрываются там, где публикуются "
        "(настройка YouTube об изменённом или синтетическом контенте, метка TikTok «создано ИИ»), а файл "
        "сохраняет учётные данные контента (C2PA) — и вне ЕС тоже",
        P,
        _realistic_people,
        ("people",),
        "spec.style = 'photoreal'",
        (S_YT_SYNTHETIC, S_TIKTOK_AI, S_C2PA),
    ),
    _r(
        "made_for_kids",
        [],
        "made for kids: on YouTube the video or channel is set 'made for kids' (COPPA): no personalised ads, "
        "comments off; keep the content age-appropriate and do not imitate known children's characters",
        "для детей: на YouTube ролик или канал отмечается «для детей» (закон COPPA): без персональной рекламы, "
        "комментарии выключены; содержание по возрасту и без подражания известным детским персонажам",
        R,
        _kids,
        (),
        "spec.audience = 'children'",
        (S_COPPA, S_YT_KIDS),
    ),
)

# =========================================================================================
# ROUND 12: THE LONG TAIL OF PROFESSIONAL CAVEATS
# =========================================================================================
#
# WHY. On fresh unseen briefs the round-11 checklist carried about 81 % of the notes
# a post-production supervisor adds; the misses were not job classes but DELIVERY
# TARGETS and DOMAINS (a DCP, a broadcast master, an audiobook for ACX, a listing
# photo, a political ad, an AMD card). One rule per delivery target or domain, the
# same contract as above: structured fields first (`fps`, `duration_s`, `languages`,
# `people[].claim / deceased / minor / public_figure`, `jurisdiction`,
# `self_host.platform`, `aspect`, `task`), words only where the spec has no field —
# and then `spec_field` names the field that would carry it.
#
# DECISION CONSTANTS (T1: mutated both ways by `scripts/mutate_round12_checklist.py`):
# `GLYPH_RISK_LANGS`, `INDIC_LANGS`, `SEA_LANGS`, `LOCL_LANGS`, `DCP_FPS`,
# `SOCIAL_SHORT_MAX_S`, `NON_NVIDIA_PLATFORMS`.

#: Non-Latin alphabets where generators substitute Latin look-alikes or invent letters
#: (Cyrillic, Greek, Armenian, Georgian): on-screen text in them is overlaid, not generated.
GLYPH_RISK_LANGS: frozenset[str] = frozenset(
    {"ru", "uk", "be", "bg", "sr", "mk", "kk", "ky", "tg", "mn", "el", "hy", "ka"}
)
#: Brahmic scripts of South Asia: conjuncts and vowel signs need complex shaping.
INDIC_LANGS: frozenset[str] = frozenset(
    {"hi", "mr", "ne", "sa", "bn", "as", "pa", "gu", "or", "ta", "te", "kn", "ml", "si"}
)
#: South-East Asian scripts written without spaces between words (dictionary line breaking).
SEA_LANGS: frozenset[str] = frozenset({"th", "lo", "km", "my"})
#: Cyrillic languages whose letterforms differ from Russian (OpenType `locl`).
LOCL_LANGS: frozenset[str] = frozenset({"bg", "sr", "mk"})
#: Frame rates a DCI DCP carries (2K at 24 or 48, 4K at 24).
DCP_FPS: frozenset[int] = frozenset({24, 48})
#: Shorts and Reels take a vertical video up to 3 minutes; a longer one is a regular video.
SOCIAL_SHORT_MAX_S = 180
#: Self-host platforms that are not CUDA (`spec.self_host.platform`).
NON_NVIDIA_PLATFORMS: frozenset[str] = frozenset({"rocm", "xpu", "apple-silicon"})

W_CINEMA = re.compile(
    r"\bdcp\b|digital cinema|cinema (?:release|screening|projection|ad|advert|spot|trailer)|theatrical|movie theat"
    r"|\bcinemas\b|\bfor (?:the )?cinema\b|film festival|festival screening|big screen|кинотеатр|кинопоказ|кинопрокат|кинофестивал"
    r"|больш\w+ экран",
    re.I,
)
W_STREAMING = re.compile(
    r"netflix|prime video|disney\+|\bhbo\b|apple tv\+|\bimf\b|streaming (?:platform|service|deliver)|\bott\b"
    r"|кинопоиск|\bokko\b|стриминг\w* (?:платформ|сервис)",
    re.I,
)
W_LOCALISE = re.compile(
    r"locali[sz]|international version|foreign (?:version|market)|\bm&e\b|music and effects|\bdme\b|локализ"
    r"|международн\w* верси|иностранн\w* рын",
    re.I,
)
W_REAL_ESTATE = re.compile(
    r"real[- ]estate|realtor|property listing|listing photo|virtual(?:ly)? stag|home staging|\bmls\b"
    r"|(?:apartment|house|flat|home) for sale|недвижим|риелтор|риэлтор|квартир\w* (?:на|для) продаж"
    r"|объявлени\w* о продаже|стейджинг",
    re.I,
)
W_RETOUCH = re.compile(
    r"retouch|\bslim(?:mer|ming)?\b|thinner|reshape (?:the )?(?:body|waist|face)|smooth(?:er)? (?:the )?skin"
    r"|skin smoothing|beauty filter|airbrush|flawless skin|perfect skin|ретуш|стройн|похуд|тоньше|разглад\w* кож"
    r"|фильтр\w* красоты|идеальн\w+ кож",
    re.I,
)
W_AD = re.compile(
    r"\bads?\b|advert|commercial|campaign|billboard|\bpromo|marketing|sponsored|реклам|баннер|билборд|промо"
    r"|кампани",
    re.I,
)
W_COSMETIC = re.compile(
    r"cosmetic|skin ?care|mascara|foundation|lipstick|serum|\bcream|tanning|self-tan|beauty product|anti-?ag"
    r"|wrinkle|косметик|крем|сыворотк|тушь|помад|тональн|автозагар|морщин|уход\w* за кож",
    re.I,
)
W_BEFORE_AFTER = re.compile(r"before (?:and|&|/) after|before-after|до и после|до/после", re.I)
W_FRANCE = re.compile(r"\bfrance\b|\bfrench\b|\bparis\b|франц|париж", re.I)
W_POLITICAL = re.compile(
    r"politic|election|candidate|ballot|referendum|vote for|voters?\b|\bsuper ?pac\b|политич|выбор(?:ы|ах|ов)\b"
    r"|предвыбор|кандидат|голосуй|референдум|агитац",
    re.I,
)
W_OUTBOUND = re.compile(
    r"robocall|outbound (?:calls?|calling|dial\w*)|auto-?dial|cold call|(?:phone )?calls? to (?:our |the )?(?:customers|clients|subscribers|leads)"
    r"|phone calls? (?:to|reminding|for) "
    r"|автообзвон|обзвон|исходящ\w+ звон|звонк\w+ клиентам",
    re.I,
)
W_VOICE_BOT = re.compile(
    r"voice ?bot|voice assistant|voice agent|conversational|\bai agent|talks? (?:to|with) callers|answers? (?:the )?calls"
    r"|голосов\w+ (?:бот|ассистент|помощник|агент)|робот\w* оператор|отвеча\w+ на звонки",
    re.I,
)
W_GAME = re.compile(
    r"video ?games?|game (?:audio|sound|music|sfx|asset|trailer|dev|level|soundtrack)|\bin-?game\b|\bwwise\b|\bfmod\b"
    r"|\bunity\b|unreal engine|\bgamedev|indie game|для (?:нашей |моей |мобильной )?игры|игров\w+ (?:звук|музык|эффект|ассет|саундтрек)"
    r"|геймдев",
    re.I,
)
W_AUDIOBOOK = re.compile(r"audio ?books?|\bacx\b|audible|аудиокниг", re.I)
W_DISTRIBUTION = re.compile(
    r"distrokid|tunecore|cd ?baby|ditto music|onerpm|release (?:it |the track |my track |the song |my song |a single )?on "
    r"(?:spotify|apple music|streaming)|(?:upload|put) (?:it |the track |my track )?(?:on|to) (?:spotify|apple music)"
    r"|music distribut|\bisrc\b|дистрибуц|выпустить (?:трек|песню|сингл|альбом)|релиз на (?:spotify|стриминг)"
    r"|выложить (?:трек |песню )?на (?:spotify|стриминг)",
    re.I,
)
W_MONETISE = re.compile(r"content ?id|monetis|monetiz|монетиз", re.I)
W_STOCK = re.compile(
    r"stock (?:footage|music|photos?|videos?|images?|clips?|tracks?)|shutterstock|getty|istock|adobe stock|pond5"
    r"|envato|artlist|epidemic sound|storyblocks|стоков\w*|сток\w* (?:видео|музык|фото)|фотобанк",
    re.I,
)
W_SELL_STOCK = re.compile(
    r"sell (?:\w+ ){0,2}(?:on|to|as|via) (?:stock|shutterstock|adobe stock|getty)|stock contributor"
    r"|upload (?:them |it )?to (?:adobe stock|shutterstock|getty)|продава\w* (?:на|в) (?:сток|фотобанк)"
    r"|для продажи на (?:сток|фотобанк)|на стоки",
    re.I,
)
W_MARKETPLACE = re.compile(
    r"amazon|marketplace|маркетплейс|wildberries|\bozon\b|\betsy\b|\bebay\b",
    re.I,
)
W_A11Y = re.compile(
    r"accessib|\bwcag\b|\ba11y\b|\bada\b|section 508|\bdeaf\b|hard of hearing|blind (?:viewers|users|people)"
    r"|visually impaired|\bsdh\b|audio description|public sector|government|e-?learning|online course"
    r"|доступн\w+ (?:сред|для)|глух|слабослыш|незрячи|слабовидящ|тифлокомментар|инклюзив|госучрежд|онлайн-?курс",
    re.I,
)
W_FLASH = re.compile(
    r"strob|\bflash(?:es|ing)?\b|flicker(?:ing)? effect|glitch|epilep|стробоскоп|вспышк|мигани|глитч|эпилеп",
    re.I,
)
W_NEWS = re.compile(
    r"\bnews\b|newsroom|journalis|reportage|documentary|breaking|новост|репортаж|журналист|документальн", re.I
)
W_VFX = re.compile(
    r"\bvfx\b|\bnuke\b|\baces\b|\bexr\b|\bplates?\b for|post-?house|composit(?:e|ing|or)|\bcg\b integration"
    r"|композитинг|\bвфх\b|в нюк",
    re.I,
)
W_EDITORIAL = re.compile(
    r"premiere pro|davinci|resolve|\bavid\b|final cut|\bedl\b|\baaf\b|fcpxml|(?:our|the) editor will"
    r"|монтажёр|монтажер|в монтажке|проект\w* монтаж",
    re.I,
)
W_HEALTH = re.compile(
    r"medic(?:al|ine)|pharma|\bdrugs?\b|supplement|\bclinic|doctor|physician|dentist|health claim|\bcures?\b"
    r"|лекарств|фарм|\bбад\b|клиник|врач|доктор|медицин|лечени|стоматолог",
    re.I,
)
W_FINANCE = re.compile(
    r"crypto|bitcoin|forex|trading app|\binvest|\bloans?\b|credit card|mortgage|insurance|крипт|биткоин|форекс"
    r"|трейдинг|инвест|кредит|ипотек|займ|страхов",
    re.I,
)
W_APP_STORE = re.compile(r"app store|app preview|google play|play store|превью приложени|в магазин\w* приложений", re.I)
W_SPONSORED = re.compile(
    r"sponsored|influencer|paid partnership|brand deal|#ad\b|\bugc\b|affiliate|блогер|инфлюенс|спонсор"
    r"|рекламн\w+ интеграци|интеграци\w+ (?:у|в) блог",
    re.I,
)
W_COVER = re.compile(r"thumbnail|cover (?:frame|image)|обложк|превью ролик|миниатюр", re.I)


# --- round-12 triggers ---------------------------------------------------------------------


def _cinema(c: Ctx) -> bool:
    return c.video and c.says(W_CINEMA)


def _dcp_fps(c: Ctx) -> dict[str, str] | None:
    fps = c.spec.fps
    if _cinema(c) and fps is not None and int(fps) not in DCP_FPS:
        return {"fps": str(fps)}
    return None


def _broadcast_video(c: Ctx) -> bool:
    return c.video and c.says(W_BROADCAST)


def _broadcast_speech(c: Ctx) -> bool:
    return _broadcast_video(c) and (bool(c.jobs & (SPEECH_MAKE | FACE_SYNC | {"captions"})) or "speech" in c.outputs)


def _broadcast_rate(c: Ctx) -> bool:
    return _broadcast_video(c) and bool(c.jobs & VIDEO_GEN)


def _streaming(c: Ctx) -> bool:
    return c.video and c.says(W_STREAMING)


def _localise(c: Ctx) -> bool:
    if not c.video:
        return False
    return "dub" in c.jobs or (len(c.langs) >= 2 and bool(c.jobs & SPEECH_MAKE)) or c.says(W_LOCALISE)


def _dub_text(c: Ctx) -> bool:
    return "dub" in c.jobs


def _twos_made(c: Ctx) -> bool:
    return bool(c.jobs & VIDEO_GEN) and c.says(W_ANIMATION_TWOS)


def _twos_upscale(c: Ctx) -> bool:
    return bool(c.jobs & UPSCALE) and c.says(W_ANIMATION_TWOS)


def _gen_text_langs(c: Ctx, langs: frozenset[str]) -> dict[str, str] | None:
    hit = sorted(c.langs & langs)
    if hit and c.jobs & (VIDEO_GEN | STILL_GEN) and c.says(W_TEXT_IN_FRAME):
        return {"langs": ", ".join(hit)}
    return None


def _glyph_risk(c: Ctx) -> dict[str, str] | None:
    return _gen_text_langs(c, GLYPH_RISK_LANGS)


def _text_langs(c: Ctx, langs: frozenset[str]) -> dict[str, str] | None:
    hit = sorted(c.langs & langs)
    if hit and (c.visual or c.jobs & {"transcribe", "captions"}):
        return {"langs": ", ".join(hit)}
    return None


def _indic(c: Ctx) -> dict[str, str] | None:
    return _text_langs(c, INDIC_LANGS)


def _sea(c: Ctx) -> dict[str, str] | None:
    return _text_langs(c, SEA_LANGS)


def _locl(c: Ctx) -> dict[str, str] | None:
    return _text_langs(c, LOCL_LANGS)


def _real_estate(c: Ctx) -> bool:
    return bool(c.jobs & (STILL_GEN | VIDEO_GEN | {"v2v_edit"})) and c.says(W_REAL_ESTATE)


def _retouch_ad(c: Ctx) -> bool:
    return bool(c.jobs & (STILL_GEN | VIDEO_GEN | {"v2v_edit", "char_replace"})) and c.says(W_RETOUCH) and c.says(W_AD)


def _retouch_france(c: Ctx) -> bool:
    return _retouch_ad(c) and c.says(W_FRANCE)


def _cosmetic_ad(c: Ctx) -> bool:
    return bool(c.jobs & (STILL_GEN | VIDEO_GEN | {"v2v_edit"})) and c.says(W_COSMETIC) and c.says(W_AD)


def _before_after(c: Ctx) -> bool:
    return bool(c.steps or c.jobs) and c.says(W_BEFORE_AFTER)


def _claim(c: Ctx, kind: str) -> bool:
    return any(п.get("claim") == kind for п in c.spec.people)


def _political(c: Ctx) -> bool:
    return bool(c.steps or c.jobs) and (_claim(c, "political") or c.says(W_POLITICAL))


def _political_us(c: Ctx) -> bool:
    return _political(c) and "US" in c.spec.jurisdiction


def _robocall(c: Ctx) -> bool:
    return bool(c.jobs & SPEECH_MAKE) and c.says(W_OUTBOUND)


def _voice_bot(c: Ctx) -> bool:
    return bool(c.jobs & SPEECH_MAKE) and c.says(W_VOICE_BOT)


def _platform_of(c: Ctx) -> str:
    sh = c.self_host
    return str(sh.get("platform") or "") if sh else ""


def _backend(c: Ctx, platform: str) -> dict[str, str] | None:
    if c.steps and _platform_of(c) == platform and platform in NON_NVIDIA_PLATFORMS:
        return {"gpu": str(c.self_host.get("gpu") or platform)}
    return None


def _rocm(c: Ctx) -> dict[str, str] | None:
    return _backend(c, "rocm")


def _xpu(c: Ctx) -> dict[str, str] | None:
    return _backend(c, "xpu")


def _mps(c: Ctx) -> dict[str, str] | None:
    return _backend(c, "apple-silicon")


def _game_sfx(c: Ctx) -> bool:
    return "sfx" in c.jobs and c.says(W_GAME)


def _game_music(c: Ctx) -> bool:
    return "music" in c.jobs and c.says(W_GAME)


def _audiobook(c: Ctx) -> bool:
    return bool(c.jobs & {"tts", "voice_clone"}) and c.says(W_AUDIOBOOK)


def _podcast_made(c: Ctx) -> bool:
    return bool(c.jobs & (SPEECH_MAKE | {"music"})) and c.says(W_PODCAST)


def _podcast_ai_voice(c: Ctx) -> bool:
    return bool(c.jobs & SPEECH_MAKE) and c.says(W_PODCAST)


def _distribution(c: Ctx) -> bool:
    return "music" in c.jobs and c.says(W_DISTRIBUTION)


def _monetised_music(c: Ctx) -> bool:
    return "music" in c.jobs and c.says(W_MONETISE)


def _stock_use(c: Ctx) -> bool:
    return bool(c.steps or c.jobs) and c.says(W_STOCK) and not c.says(W_SELL_STOCK)


def _stock_sell(c: Ctx) -> bool:
    return bool(c.jobs & (STILL_GEN | VIDEO_GEN | {"music"})) and c.says(W_SELL_STOCK)


def _print_still(c: Ctx) -> bool:
    return delivery.is_print(c.spec, c.text) and bool(c.jobs & (STILL_GEN | UPSCALE | {"colorize", "restore"}))


def _print_text(c: Ctx) -> bool:
    return _print_still(c) and c.says(W_TEXT_IN_FRAME)


def _short_too_long(c: Ctx) -> dict[str, str] | None:
    s = c.seconds
    if _vertical(c) and c.says(W_PLATFORM) and s > SOCIAL_SHORT_MAX_S:
        return {"seconds": f"{s:g}"}
    return None


def _cover(c: Ctx) -> bool:
    return c.video and c.says(W_PLATFORM) and c.says(W_COVER)


def _social_music_ad(c: Ctx) -> bool:
    return c.video and c.says(W_PLATFORM) and c.says(W_AD) and ("music" in c.jobs or bool(re.search(r"music|музык", c.text)))


def _sponsored(c: Ctx) -> bool:
    return bool(c.steps or c.jobs) and c.says(W_SPONSORED)


def _marketplace_main(c: Ctx) -> bool:
    return bool(c.jobs & (STILL_GEN | BG_REMOVE | {"upscale_image"})) and c.says(W_PRODUCT) and c.says(W_MARKETPLACE)


def _a11y_video(c: Ctx) -> bool:
    return c.video and c.says(W_A11Y)


def _flash(c: Ctx) -> bool:
    return c.video and c.says(W_FLASH)


def _deceased(c: Ctx) -> bool:
    return any(п.get("deceased") is True and п.get("real") is not False for п in c.spec.people) and bool(c.steps or c.jobs)


def _minor(c: Ctx) -> bool:
    return any(п.get("minor") is True for п in c.spec.people) and bool(c.steps or c.jobs)


def _endorsement(c: Ctx) -> bool:
    return any(п.get("claim") == "endorsement" and п.get("real") is True for п in c.spec.people) and bool(c.steps or c.jobs)


def _famous_voice(c: Ctx) -> bool:
    return any(п.get("public_figure") is True for п in c.spec.people) and bool(c.jobs & {"voice_clone", "tts", "dub"})


def _news(c: Ctx) -> bool:
    return bool(c.jobs & (VIDEO_GEN | STILL_GEN | FACE_SYNC | {"v2v_edit", "char_replace"})) and (
        _claim(c, "news") or c.says(W_NEWS)
    )


def _china(c: Ctx) -> bool:
    return "CN" in c.spec.jurisdiction and bool(c.jobs & (VIDEO_GEN | STILL_GEN | FACE_SYNC | SPEECH_MAKE | {"music"}))


def _vfx(c: Ctx) -> bool:
    return c.video and c.says(W_VFX)


def _editorial(c: Ctx) -> bool:
    return c.video and c.says(W_EDITORIAL)


def _health_ad(c: Ctx) -> bool:
    return bool(c.steps or c.jobs) and c.says(W_HEALTH) and c.says(W_AD)


def _finance_ad(c: Ctx) -> bool:
    return bool(c.steps or c.jobs) and c.says(W_FINANCE) and c.says(W_AD)


def _app_preview(c: Ctx) -> bool:
    return c.video and c.says(W_APP_STORE)


# --- round-12 sources ----------------------------------------------------------------------

S_DCI = "https://www.dcimovies.com/specification/"
S_SMPTE_RP200 = "https://pub.smpte.org/doc/rp200/"
S_EBU_R103 = "https://tech.ebu.ch/publications/r103"
S_EBU_R95 = "https://tech.ebu.ch/publications/r095"
S_FCC_CC = "https://www.fcc.gov/consumers/guides/closed-captioning-television"
S_NETFLIX_MIX = (
    "https://partnerhelp.netflixstudios.com/hc/en-us/articles/360001794307-Netflix-Sound-Mix-Specifications-Best-Practices-v1-5"
)
S_NETFLIX_GENAI = "https://www.tvbeurope.com/artificial-intelligence/netflix-publishes-genai-guidance-for-creators"
S_IMF = "https://www.imfug.com/"
S_REAL_ESTATE_NAR = "https://www.nar.realtor/about-nar/governing-documents/the-code-of-ethics"
S_UCPD = "https://eur-lex.europa.eu/eli/dir/2005/29/oj"
S_FR_RETOUCH = "https://cms.law/en/fra/legal-updates/La-mention-photographie-retouchee-obligatoire-a-partir-du-1er-octobre-2017"
S_ASA_FILTERS = "https://www.asa.org.uk/news/the-mis-use-of-social-media-beauty-filters-when-advertising-cosmetic-products.html"
S_EU_POLITICAL = (
    "https://commission.europa.eu/strategy-and-policy/policies/justice-and-fundamental-rights/"
    "democracy-eu-citizenship-anti-corruption/democracy-and-electoral-rights/transparency-and-targeting-political-advertising_en"
)
S_GOOGLE_POLITICAL = "https://support.google.com/adspolicy/answer/6014595"
S_FEC_DISCLAIMER = "https://www.fec.gov/help-candidates-and-committees/advertising-and-disclaimers/"
S_FCC_AI_VOICE = "https://docs.fcc.gov/public/attachments/FCC-24-17A1.pdf"
S_AI_ACT = "https://eur-lex.europa.eu/eli/reg/2024/1689/oj"
S_ROCM_MATRIX = "https://rocm.docs.amd.com/en/latest/compatibility/compatibility-matrix.html"
S_COMFY = "https://raw.githubusercontent.com/comfyanonymous/ComfyUI/master/README.md"
S_TORCH_XPU = "https://docs.pytorch.org/docs/main/notes/get_start_xpu.html"
S_APPLE_MPS = "https://developer.apple.com/metal/pytorch/"
S_WWISE = "https://www.audiokinetic.com/en/library/edge/?source=Help&id=importing_media_files"
S_ACX = "https://help.acx.com/s/article/acx-audio-submission-requirements"
S_APPLE_PODCAST_ART = "https://podcasters.apple.com/support/896-artwork-requirements"
S_APPLE_PODCAST_RULES = "https://podcasters.apple.com/support/891-content-and-subscription-guidelines"
S_ISRC = "https://isrc.ifpi.org/"
S_SPOTIFY_AI = "https://www.digitalmusicnews.com/2025/09/25/spotify-ai-protections-announcement/"
S_CONTENT_ID = "https://support.google.com/youtube/answer/2797370"
S_SHUTTERSTOCK_LICENCE = "https://www.shutterstock.com/license"
S_ADOBE_STOCK_AI = (
    "https://helpx.adobe.com/stock/contributor/submit-your-content/submit-generative-ai-content/"
    "generative-ai-content-guidelines.html"
)
S_ICC = "https://www.color.org/registry/index.xalter"
S_PDFX = "https://www.iso.org/standard/42876.html"
S_SHORTS_3MIN = "https://engadget.com/entertainment/youtube/youtube-shorts-can-now-run-up-to-three-minutes-160002081.html"
S_YT_THUMB = "https://support.google.com/youtube/answer/72431"
S_TIKTOK_CML = "https://ads.tiktok.com/help/article/commercial-music-library"
S_FTC_ENDORSE = "https://www.ftc.gov/business-guidance/resources/ftcs-endorsement-guides-what-people-are-asking"
S_AMAZON_IMAGES = "https://sellercentral.amazon.com/help/hub/reference/external/G1881"
S_WCAG = "https://www.w3.org/TR/WCAG22/"
S_WCAG_AD = "https://www.w3.org/WAI/WCAG22/Understanding/audio-description-prerecorded.html"
S_BT1702 = "https://www.itu.int/rec/R-REC-BT.1702"
S_CA_3344_1 = "https://leginfo.legislature.ca.gov/faces/codes_displaySection.xhtml?lawCode=CIV&sectionNum=3344.1"
S_YT_MINORS = "https://support.google.com/youtube/answer/2801999"
S_FTC_IMPERSONATION = "https://www.ftc.gov/legal-library/browse/rules/impersonation-government-businesses"
S_TN_ELVIS = "https://www.capitol.tn.gov/Bills/113/Bill/SB2096.pdf"
S_CN_LABEL = (
    "https://www.loeb.com/en/insights/publications/2025/03/"
    "chinas-ai-labeling-measures-and-mandatory-national-standards-take-effect-september-1"
)
S_ACES = "https://www.oscars.org/science-technology/sci-tech-projects/aces"
S_CAP_HEALTH = "https://www.asa.org.uk/type/non_broadcast/code_section/12.html"
S_FCA_PROMO = "https://www.fca.org.uk/firms/financial-promotions-adverts"
S_APP_PREVIEW = "https://developer.apple.com/help/app-store-connect/reference/app-preview-specifications"
S_UAX14 = "https://www.unicode.org/reports/tr14/"
S_DEVANAGARI = "https://learn.microsoft.com/en-us/typography/script-development/devanagari"
S_LOCL = "https://learn.microsoft.com/en-us/typography/opentype/spec/features_ko"

RULES_R12: tuple[Rule, ...] = (
    # --- cinema / DCP ----------------------------------------------------------------------
    _r(
        "dcp_master",
        [],
        "cinema delivery is a DCP, not a video file: DCI containers 2K 2048x1080 / 4K 4096x2160 (flat 1998x1080, "
        "scope 2048x858), JPEG 2000 in XYZ colour, 24-bit 48 kHz PCM — build it with a DCP mastering tool and check "
        "it on a cinema projector before the screening",
        "показ в кинотеатре — это DCP, а не видеофайл: контейнеры DCI 2K 2048x1080 / 4K 4096x2160 (flat "
        "1998x1080, scope 2048x858), JPEG 2000 в цвете XYZ, звук PCM 24 бит 48 кГц — соберите его программой "
        "мастеринга DCP и проверьте на кинопроекторе до показа",
        P,
        _cinema,
        ("outputs",),
        "spec.delivery.platform = 'cinema'",
        (S_DCI,),
    ),
    _r(
        "dcp_frame_rate",
        [],
        "{fps} fps is not a DCI DCP rate (2K plays at 24 or 48 fps, 4K at 24): conform to 24 fps before mastering — "
        "25 fps material is usually slowed by 4 % with the audio pitch-corrected, 30 fps is retimed",
        "{fps} кадров/с — не частота DCI DCP (2K идёт на 24 или 48, 4K — на 24): приведите к 24 до мастеринга — "
        "материал 25 кадров/с обычно замедляют на 4 % с коррекцией высоты звука, 30 кадров/с перетаймируют",
        P,
        _dcp_fps,
        ("fps", "outputs"),
        "spec.delivery.platform = 'cinema'",
        (S_DCI,),
    ),
    _r(
        "cinema_sound_reference",
        [],
        "a theatrical mix is set by the calibrated monitoring level (85 dB SPL reference, SMPTE RP 200), not by a "
        "LUFS target: a web-loud mix plays painfully loud in a cinema — mix or check it in a calibrated room",
        "кинотеатральный микс строится по калиброванному уровню прослушивания (опорные 85 дБ SPL, SMPTE RP 200), "
        "а не по цели LUFS: микс «громкий для интернета» в кинозале звучит болезненно громко — сводите или "
        "проверяйте в калиброванной комнате",
        P,
        _cinema,
        ("outputs",),
        "spec.delivery.platform = 'cinema'",
        (S_SMPTE_RP200,),
    ),
    _r(
        "cinema_big_screen_check",
        ["t2v", "i2v", "t2v_audio", "r2v", "series", "upscale", "upscale_video"],
        "a cinema screen magnifies everything: generated video is native 720p-1080p and a 2K/4K DCP of it is an "
        "upscale — review every shot projected at full size for texture swimming, banding and soft faces before "
        "locking the cut",
        "киноэкран увеличивает всё: сгенерированное видео родом из 720p-1080p, и DCP в 2K/4K из него — это "
        "апскейл — просмотрите каждый шот в проекции в полный размер на плавающую текстуру, полосы градиента и "
        "мягкие лица до утверждения монтажа",
        E,
        _cinema,
        ("outputs", "task"),
        "spec.delivery.platform = 'cinema'",
    ),
    # --- broadcast ---------------------------------------------------------------------------
    _r(
        "broadcast_legal_range",
        [],
        "broadcast picture must be legal: EBU R103 limits luma to -1 %..103 % (8-bit 16-235 video range) and RGB "
        "gamut — generated clips are full-range with very saturated colours, so run a legaliser and check on a "
        "waveform scope before delivery",
        "эфирная картинка должна быть «легальной»: EBU R103 ограничивает яркость -1 %..103 % (видеодиапазон "
        "16-235 в 8 битах) и охват RGB — сгенерированные ролики идут в полном диапазоне с очень насыщенными "
        "цветами, поэтому пропустите их через легалайзер и проверьте по осциллографу сигнала до сдачи",
        R,
        _broadcast_video,
        ("outputs",),
        "spec.delivery.platform = 'broadcast'",
        (S_EBU_R103,),
    ),
    _r(
        "broadcast_closed_captions",
        [],
        "broadcast speech needs closed captions in the channel's format: CEA-608/708 embedded in the US (FCC "
        "caption quality rules), EBU-TT / teletext subtitles in Europe — a burned-in caption is not a closed "
        "caption",
        "речь в эфире требует скрытых субтитров в формате канала: CEA-608/708 внутри сигнала в США (правила FCC "
        "о качестве субтитров), EBU-TT или телетекст в Европе — вжитые субтитры скрытыми не считаются",
        R,
        _broadcast_speech,
        ("outputs", "task"),
        "spec.delivery.platform = 'broadcast'",
        (S_FCC_CC,),
    ),
    _r(
        "broadcast_safe_areas",
        [],
        "broadcast graphics stay inside the safe areas (EBU R95: action safe 3.5 %, graphics safe 5 % from each "
        "edge in 16:9, 14:9 protection if the channel asks) — keep supers, logos and phone numbers inside them",
        "графика для эфира — внутри безопасных зон (EBU R95: зона действия 3,5 %, графики 5 % от каждого края в "
        "16:9, защита 14:9, если канал просит) — титры, логотипы и телефоны держите внутри",
        P,
        _broadcast_video,
        ("outputs",),
        "spec.delivery.platform = 'broadcast'",
        (S_EBU_R95,),
    ),
    _r(
        "broadcast_frame_rate",
        [],
        "generated clips come at 24 or 30 fps; a broadcast master runs at the channel's rate (25/50 in Europe, "
        "29.97/59.94 in North America and Japan) — convert with optical-flow retiming or 2:3 pulldown and check "
        "motion cadence; never just relabel the rate",
        "сгенерированные ролики приходят в 24 или 30 кадров/с, а эфирный мастер идёт в частоте канала (25/50 в "
        "Европе, 29,97/59,94 в Северной Америке и Японии) — переводите оптическим потоком или раскладкой 2:3 и "
        "проверяйте плавность движения; простая перемаркировка частоты не годится",
        E,
        _broadcast_rate,
        ("outputs", "steps"),
        "spec.delivery.platform = 'broadcast'",
    ),
    # --- streaming --------------------------------------------------------------------------
    _r(
        "streaming_imf_delivery",
        [],
        "premium streaming delivery (Netflix-class) is an IMF package (SMPTE ST 2067) with a ProRes or JPEG 2000 "
        "master, timed text and audio stems per the platform's spec sheet — confirm the deliverables list before "
        "rendering",
        "сдача на премиальный стриминг (класса Netflix) — пакет IMF (SMPTE ST 2067) с мастером ProRes или "
        "JPEG 2000, субтитрами и звуковыми стемами по спецификации площадки — уточните список материалов до "
        "рендера",
        P,
        _streaming,
        ("outputs",),
        "spec.delivery.platform = 'streaming-premium'",
        (S_IMF,),
    ),
    _r(
        "streaming_dialogue_loudness",
        [],
        "streaming mix: Netflix-class platforms measure dialogue-gated loudness, -27 LKFS +-2 LU (ITU-R BS.1770-1) "
        "with true peaks at most -2 dBTP — not the -14 LUFS of a music service or the -23 LUFS of EBU broadcast",
        "микс для стриминга: площадки класса Netflix меряют громкость по диалогу, -27 LKFS +-2 LU (ITU-R "
        "BS.1770-1), истинный пик не выше -2 dBTP — не -14 LUFS музыкального сервиса и не -23 LUFS эфира EBU",
        P,
        _streaming,
        ("outputs",),
        "spec.delivery.platform = 'streaming-premium'",
        (S_NETFLIX_MIX,),
    ),
    _r(
        "streaming_genai_approval",
        [],
        "studios and streamers now ask to be told about generative AI in a production and want written approval "
        "when it reaches final deliverables, talent likeness or third-party IP — clear the AI shots with the "
        "commissioning platform before delivery",
        "студии и стриминги теперь просят сообщать о генеративном ИИ в производстве и требуют письменного "
        "согласования, когда он попадает в финальные материалы, образ актёра или чужую интеллектуальную "
        "собственность — согласуйте сгенерированные кадры с заказчиком-площадкой до сдачи",
        P,
        _streaming,
        ("outputs",),
        "spec.delivery.platform = 'streaming-premium'",
        (S_NETFLIX_GENAI,),
    ),
    # --- localisation: M&E, forced narratives ---------------------------------------------------
    _r(
        "me_stems_delivery",
        [],
        "localisation deliverable: keep dialogue, music and effects as separate stems (DME) and deliver a fully "
        "filled M&E (music and effects, no dialogue, with effects that were on the dialogue track rebuilt) — "
        "every new language is mixed over it",
        "материалы для локализации: держите диалог, музыку и эффекты отдельными стемами (DME) и отдайте полную "
        "дорожку M&E (музыка и эффекты без речи, с восстановленными шумами, что были на дорожке диалога) — "
        "каждый новый язык сводится поверх неё",
        E,
        _localise,
        ("task", "languages", "language_tags"),
        "spec.delivery.stems = ['dialogue', 'music', 'effects']",
    ),
    _r(
        "forced_narratives",
        ["dub"],
        "on-screen text in the source (signs, captions, inserts) is not dubbed: translate it as forced-narrative "
        "subtitles or replace the graphics per language — list every text moment when you spot the film",
        "текст в кадре исходника (вывески, титры, вставки) дубляж не переводит: переведите его вынужденными "
        "субтитрами или замените графику для каждого языка — составьте список всех таких моментов при "
        "разметке фильма",
        E,
        _dub_text,
        ("task",),
        sources=(S_NETFLIX_TT,),
    ),
    # --- anime / limited animation -------------------------------------------------------------
    _r(
        "anime_on_twos_output",
        [],
        "anime or hand-drawn look: video models render smooth full-rate in-betweens, which reads as 3D or "
        "rotoscope — for the limited-animation feel hold drawings at assembly (keep every 2nd frame and double "
        "it, 12 drawings/s at 24 fps) and keep camera pans at full rate",
        "аниме или рисованный вид: видеомодели дают плавные промежуточные фазы на полной частоте, и это "
        "выглядит как 3D или ротоскоп — для ограниченной анимации держите рисунки при сборке (каждый второй кадр "
        "повторён дважды, 12 рисунков в секунду на 24 кадрах), а панорамы камеры оставьте на полной частоте",
        E,
        _twos_made,
        ("steps",),
        "spec.style = 'limited-animation'",
        (S_FFMPEG_FILTERS,),
    ),
    _r(
        "anime_upscaler",
        [],
        "upscaling anime or flat-colour animation: use an animation-trained model (Real-ESRGAN anime or "
        "Anime4K class) — photo upscalers paint texture and noise into flat colour fields and thicken line art",
        "апскейл аниме или анимации с заливками: берите модель, обученную на анимации (класс Real-ESRGAN anime "
        "или Anime4K), — фото-апскейлеры рисуют фактуру и шум в ровных заливках и утолщают контур",
        E,
        _twos_upscale,
        ("task",),
        "spec.style = 'limited-animation'",
    ),
    # --- text rendering per script --------------------------------------------------------------
    _r(
        "script_text_overlay",
        [],
        "on-screen text in {langs}: generators swap Cyrillic, Greek, Armenian or Georgian letters for Latin "
        "look-alikes or invent letters — generate the picture without text and set the words as an overlay in a "
        "font that covers the script, then proofread on the final frame",
        "текст в кадре на {langs}: генераторы подменяют кириллицу, греческие, армянские или грузинские буквы "
        "похожими латинскими или выдумывают буквы — генерируйте картинку без текста и ставьте слова слоем "
        "шрифтом с поддержкой письменности, затем вычитайте на финальном кадре",
        E,
        _glyph_risk,
        ("languages", "language_tags"),
    ),
    _r(
        "indic_shaping",
        [],
        "{langs}: Brahmic scripts need complex shaping (conjuncts, vowel signs that reorder) — render captions "
        "and overlays with a HarfBuzz-based renderer and a full font (Noto Sans Devanagari / Bengali / Tamil "
        "class); never generate the lettering, and have a native reader check the frame",
        "{langs}: брахмические письменности требуют сложной вёрстки (лигатуры согласных, знаки гласных, меняющие "
        "место) — рендерите субтитры и надписи движком на основе HarfBuzz с полным шрифтом (класс Noto Sans "
        "Devanagari / Bengali / Tamil); надписи не генерируйте и дайте кадр носителю на проверку",
        E,
        _indic,
        ("languages", "language_tags", "outputs"),
        sources=(S_DEVANAGARI,),
    ),
    _r(
        "sea_line_break",
        [],
        "{langs}: these scripts put no spaces between words — caption line breaks need dictionary segmentation "
        "(ICU line breaking), otherwise lines split inside words; check tone marks and stacked vowels on the "
        "final frame",
        "{langs}: в этих письменностях нет пробелов между словами — перенос строк субтитров требует словарной "
        "сегментации (разбиение строк ICU), иначе строки рвутся внутри слов; проверьте тоновые знаки и "
        "надстрочные гласные на финальном кадре",
        E,
        _sea,
        ("languages", "language_tags", "outputs"),
        sources=(S_UAX14,),
    ),
    _r(
        "cyrillic_locl",
        [],
        "{langs}: Bulgarian, Serbian and Macedonian use their own Cyrillic letterforms (the italic b, g, d, p, t "
        "shapes differ from Russian) — set the text language so the font's localised forms (OpenType locl) switch on, "
        "and use a font that has them",
        "{langs}: в болгарском, сербском и македонском свои начертания кириллицы (курсивные б, г, д, п, т "
        "отличаются от русских) — указывайте язык текста, чтобы включились локальные формы шрифта (OpenType "
        "locl), и берите шрифт, где они есть",
        E,
        _locl,
        ("languages", "language_tags", "outputs"),
        sources=(S_LOCL,),
    ),
    # --- real estate ------------------------------------------------------------------------
    _r(
        "virtual_staging_disclosure",
        [],
        "real-estate listing: label virtually staged or AI-altered photos ('virtually staged') and show the "
        "unaltered photo next to them — listing rules (MLS, NAR Code of Ethics 'true picture') and consumer law "
        "(EU UCPD) treat an undisclosed edit as misleading",
        "объявление о недвижимости: виртуально обставленные или изменённые ИИ фото помечаются («виртуальная "
        "расстановка мебели»), и рядом показывается неизменённое фото — правила площадок объявлений (MLS, "
        "этический кодекс NAR) и закон о защите потребителей (UCPD в ЕС) считают нераскрытую правку "
        "вводящей в заблуждение",
        R,
        _real_estate,
        ("task",),
        "spec.domain = 'real-estate'",
        (S_REAL_ESTATE_NAR, S_UCPD),
    ),
    _r(
        "real_estate_permanent_features",
        [],
        "virtual staging may add furniture and decor, but never removes or changes permanent features — cracks, "
        "power lines, the view, room size, fixtures; check every generated room against the real one (walls, "
        "windows and doors where they are)",
        "виртуальная расстановка может добавить мебель и декор, но не убирает и не меняет постоянное — трещины, "
        "провода, вид из окна, размер комнаты, встроенное оборудование; сверяйте каждую сгенерированную комнату "
        "с настоящей (стены, окна и двери на своих местах)",
        R,
        _real_estate,
        ("task",),
        "spec.domain = 'real-estate'",
        (S_UCPD,),
    ),
    # --- retouched advertising -----------------------------------------------------------------
    _r(
        "retouch_label_france",
        [],
        "France: a commercial photo of a model whose silhouette was slimmed or thickened by retouching or AI "
        "must carry the mention 'photographie retouchée' (Public Health Code L.2133-2, decree 2017-738; fine up "
        "to 37,500 EUR or 30 % of the ad spend)",
        "Франция: рекламное фото модели, чью фигуру сделали тоньше или полнее ретушью или ИИ, обязано нести "
        "пометку «photographie retouchée» (Кодекс здравоохранения L.2133-2, декрет 2017-738; штраф до 37 500 "
        "евро или 30 % расходов на рекламу)",
        R,
        _retouch_france,
        ("jurisdiction",),
        "spec.jurisdiction = ['FR'] with spec.domain = 'advertising'",
        (S_FR_RETOUCH,),
    ),
    _r(
        "cosmetic_ad_effect",
        [],
        "cosmetics advertising: retouching, filters or generated skin must not exaggerate what the product does "
        "(UK ASA ruling on beauty filters, 2021; consumer law elsewhere) — show the product's real effect and "
        "keep the unretouched source",
        "реклама косметики: ретушь, фильтры или сгенерированная кожа не должны преувеличивать действие "
        "средства (решение ASA Великобритании о фильтрах красоты, 2021; закон о защите потребителей в других "
        "странах) — показывайте настоящий эффект средства и храните исходник без ретуши",
        R,
        _cosmetic_ad,
        ("task",),
        "spec.domain = 'advertising'",
        (S_ASA_FILTERS,),
    ),
    _r(
        "before_after_genuine",
        [],
        "before/after images must be real and comparable: the same person, light, pose, lens and processing, no "
        "generated or retouched 'after' — a fabricated result is a misleading claim under ad codes and consumer "
        "law",
        "снимки «до и после» должны быть настоящими и сопоставимыми: тот же человек, свет, поза, объектив и "
        "обработка, без сгенерированного или отретушированного «после» — выдуманный результат считается "
        "вводящим в заблуждение по рекламным кодексам и закону о защите потребителей",
        R,
        _before_after,
        (),
        "spec.domain = 'advertising'",
        (S_ASA_FILTERS, S_UCPD),
    ),
    # --- political ads ------------------------------------------------------------------------
    _r(
        "political_ai_disclosure",
        [],
        "political advertising with AI-made or altered people, voices or events is disclosed on the ad itself: "
        "Google and Meta require a synthetic-content disclosure on election ads, EU Regulation 2024/900 requires "
        "a transparency label (fully applicable from 10 October 2025), and many US states regulate election "
        "deepfakes",
        "политическая реклама с людьми, голосами или событиями, созданными или изменёнными ИИ, раскрывает это в "
        "самой рекламе: Google и Meta требуют пометку о синтетическом контенте в предвыборной рекламе, Регламент "
        "ЕС 2024/900 — метку прозрачности (в полной силе с 10 октября 2025), а многие штаты США регулируют "
        "предвыборные дипфейки",
        R,
        _political,
        ("people",),
        "spec.people[].claim = 'political' (or spec.domain = 'political')",
        (S_GOOGLE_POLITICAL, S_EU_POLITICAL),
    ),
    _r(
        "political_paid_for_by",
        [],
        "US political ads carry the 'paid for by' disclaimer (FEC, 11 CFR 110.11) with the sponsor named on "
        "screen and, for candidate ads, the candidate's spoken approval — check state rules on synthetic media "
        "near an election",
        "политическая реклама в США несёт пометку «оплачено» (FEC, 11 CFR 110.11) с названием спонсора на "
        "экране, а реклама кандидата — его голосовое одобрение; проверьте законы штата о синтетических медиа "
        "перед выборами",
        R,
        _political_us,
        ("people", "jurisdiction"),
        sources=(S_FEC_DISCLAIMER,),
    ),
    # --- telephony with synthetic voices -------------------------------------------------------
    _r(
        "fcc_ai_voice_robocall",
        [],
        "outbound calls with a synthetic or cloned voice: under the FCC's 2024 declaratory ruling an AI voice is "
        "an 'artificial voice' under the TCPA — such calls need the called party's prior express consent (written "
        "for marketing), plus identification and an opt-out",
        "исходящие звонки синтетическим или клонированным голосом: по декларативному решению FCC 2024 года "
        "голос ИИ считается «искусственным голосом» по закону TCPA — на такие звонки нужно предварительное явное "
        "согласие абонента (письменное для маркетинга), плюс представление звонящего и возможность отказаться",
        R,
        _robocall,
        ("task",),
        "spec.delivery.platform = 'telephony' with spec.delivery.direction = 'outbound'",
        (S_FCC_AI_VOICE,),
    ),
    _r(
        "voice_bot_disclosure",
        [],
        "a voice bot that talks with people must tell them they are talking to an AI system (EU AI Act Art. 50(1); "
        "California's bot disclosure law for sales and votes) — put it in the first sentence of the greeting",
        "голосовой бот, который разговаривает с людьми, обязан сообщить, что с ними говорит система ИИ "
        "(Регламент ЕС об ИИ, ст. 50(1); калифорнийский закон о раскрытии ботов в продажах и выборах) — "
        "скажите это первой фразой приветствия",
        R,
        _voice_bot,
        ("task",),
        "spec.delivery.platform = 'voice-agent'",
        (S_AI_ACT,),
    ),
    # --- self-host on non-NVIDIA hardware ------------------------------------------------------
    _r(
        "backend_rocm",
        [],
        "AMD GPU ({gpu}): install the PyTorch ROCm build and check the card is on the ROCm support matrix; CUDA-only "
        "parts (flash-attention CUDA wheels, xformers, older bitsandbytes, TensorRT, custom CUDA kernels) fail — "
        "use PyTorch SDPA attention and a ROCm-capable runner (ComfyUI supports AMD); see gpu_backend per step",
        "GPU AMD ({gpu}): ставьте сборку PyTorch для ROCm и проверьте карту по матрице поддержки ROCm; части "
        "только под CUDA (колёса flash-attention для CUDA, xformers, старый bitsandbytes, TensorRT, свои ядра CUDA) "
        "не заработают — берите внимание SDPA из PyTorch и среду с поддержкой ROCm (ComfyUI поддерживает AMD); "
        "смотрите gpu_backend у каждого шага",
        E,
        _rocm,
        ("self_host.platform", "self_host.gpu"),
        sources=(S_ROCM_MATRIX, S_COMFY),
    ),
    _r(
        "backend_intel_xpu",
        [],
        "Intel GPU ({gpu}): install the PyTorch xpu build (torch.xpu, Intel GPU driver and oneAPI runtime) or run "
        "through OpenVINO; CUDA-only kernels and fp8 paths are missing — use SDPA attention and a runner that "
        "supports XPU (ComfyUI does); see gpu_backend per step",
        "GPU Intel ({gpu}): ставьте сборку PyTorch xpu (torch.xpu, драйвер Intel GPU и среда oneAPI) или "
        "запускайте через OpenVINO; ядер только под CUDA и путей fp8 нет — берите внимание SDPA и среду с "
        "поддержкой XPU (ComfyUI её имеет); смотрите gpu_backend у каждого шага",
        E,
        _xpu,
        ("self_host.platform", "self_host.gpu"),
        sources=(S_TORCH_XPU, S_COMFY),
    ),
    _r(
        "backend_apple_mps",
        [],
        "Apple silicon ({gpu}): PyTorch runs on the MPS device (or MLX ports) — fp8 and CUDA kernels are not "
        "available, use bf16/fp16 weights, set PYTORCH_ENABLE_MPS_FALLBACK=1 for missing operators, and expect "
        "video models to run several times slower than on a CUDA card; see apple_silicon per step",
        "Apple silicon ({gpu}): PyTorch идёт на устройстве MPS (или порты на MLX) — fp8 и ядер CUDA нет, берите "
        "веса bf16/fp16, для недостающих операций ставьте PYTORCH_ENABLE_MPS_FALLBACK=1, а видеомодели "
        "работают в разы медленнее, чем на карте с CUDA; смотрите apple_silicon у каждого шага",
        E,
        _mps,
        ("self_host.platform", "self_host.unified_memory_gb"),
        sources=(S_APPLE_MPS,),
    ),
    # --- game audio ---------------------------------------------------------------------------
    _r(
        "game_audio_variations",
        [],
        "game sound effects: make 3-5 variations of each repeating sound (footsteps, hits, UI) so the engine can "
        "randomise them, export mono 48 kHz / 24-bit WAV for 3D-positioned sounds, trim to zero-crossing starts, "
        "and name files by a fixed scheme (category_object_action_01)",
        "звуки для игры: делайте 3-5 вариаций каждого повторяющегося звука (шаги, удары, интерфейс), чтобы движок "
        "их чередовал, выгружайте моно WAV 48 кГц / 24 бит для звуков в 3D-пространстве, обрезайте старт по нулю "
        "волны и называйте файлы по одной схеме (категория_объект_действие_01)",
        E,
        _game_sfx,
        ("outputs",),
        "spec.delivery.platform = 'game-engine'",
        (S_WWISE,),
    ),
    _r(
        "game_music_layers",
        [],
        "game music is interactive: deliver seamless loops cut on bar lines plus stems for vertical layering "
        "(intensity layers) and short stingers/transitions in the same key and tempo — one finished linear track "
        "cannot react to gameplay",
        "музыка для игры интерактивна: отдайте бесшовные петли, нарезанные по тактам, плюс стемы для "
        "вертикальных слоёв (уровни напряжения) и короткие связки в той же тональности и темпе — один готовый "
        "линейный трек не реагирует на игру",
        E,
        _game_music,
        ("outputs",),
        "spec.delivery.platform = 'game-engine'",
        (S_WWISE,),
    ),
    # --- audiobook ------------------------------------------------------------------------------
    _r(
        "acx_audio_specs",
        [],
        "audiobook for ACX/Audible: each file -23 to -18 dB RMS, peaks at most -3 dB, noise floor at most -60 dB RMS, "
        "192 kbps+ CBR MP3 at 44.1 kHz, one chapter per file with 0.5-1 s of room tone at the head and 1-5 s at "
        "the tail",
        "аудиокнига для ACX/Audible: каждый файл от -23 до -18 дБ RMS, пики не выше -3 дБ, шумовой фон не выше "
        "-60 дБ RMS, MP3 CBR от 192 кбит/с при 44,1 кГц, одна глава на файл с 0,5-1 с тишины комнаты в начале и "
        "1-5 с в конце",
        P,
        _audiobook,
        ("outputs",),
        "spec.delivery.platform = 'audiobook'",
        (S_ACX,),
    ),
    _r(
        "audiobook_ai_narration",
        [],
        "synthetic narration and audiobook stores: ACX requires human narration unless Amazon authorised it "
        "(its own Virtual Voice programme), while other stores accept AI narration with a label — check the "
        "store's rule before voicing the whole book",
        "синтетическое чтение и магазины аудиокниг: ACX требует чтения человеком, если Amazon не разрешил иначе "
        "(своя программа Virtual Voice), а другие магазины принимают чтение ИИ с пометкой — проверьте правило "
        "магазина до озвучки всей книги",
        P,
        _audiobook,
        ("outputs",),
        "spec.delivery.platform = 'audiobook'",
        (S_ACX,),
    ),
    # --- podcast ------------------------------------------------------------------------------
    _r(
        "podcast_artwork_metadata",
        [],
        "podcast delivery: show artwork 3000x3000 px (square, RGB, JPEG or PNG), episode title, description and "
        "chapters in the feed/ID3 tags — the audio is only half of what the directory checks",
        "сдача подкаста: обложка шоу 3000x3000 px (квадрат, RGB, JPEG или PNG), название, описание и главы "
        "эпизода в ленте и тегах ID3 — звук лишь половина того, что проверяет каталог",
        P,
        _podcast_made,
        ("outputs",),
        "spec.delivery.platform = 'podcast'",
        (S_APPLE_PODCAST_ART,),
    ),
    _r(
        "podcast_ai_disclosure",
        [],
        "a podcast whose voices or a material part of the audio are AI-generated says so in the show and episode "
        "metadata (Apple Podcasts content guidelines; other hosts have similar rules) — and never uses a synthetic "
        "voice to fabricate a real person's words",
        "подкаст, где голоса или заметная часть звука созданы ИИ, сообщает об этом в метаданных шоу и эпизода "
        "(правила контента Apple Podcasts; у других площадок похожие) — и никогда не вкладывает синтетическим "
        "голосом слова в уста реального человека",
        P,
        _podcast_ai_voice,
        ("task",),
        "spec.delivery.platform = 'podcast'",
        (S_APPLE_PODCAST_RULES,),
    ),
    # --- music distribution --------------------------------------------------------------------
    _r(
        "music_release_metadata",
        [],
        "releasing to streaming services: each track gets an ISRC (the distributor can issue it) and the release "
        "a UPC; deliver 16/24-bit WAV at 44.1 kHz or higher, 3000x3000 px cover art, credits and the explicit flag",
        "выпуск на стриминги: каждому треку нужен ISRC (его может выдать дистрибьютор), релизу — UPC; отдайте "
        "WAV 16/24 бит от 44,1 кГц, обложку 3000x3000 px, авторов и пометку о ненормативной лексике",
        P,
        _distribution,
        ("outputs",),
        "spec.delivery.platform = 'music-distribution'",
        (S_ISRC,),
    ),
    _r(
        "ai_music_distribution",
        [],
        "AI-generated music on streaming services: declare the AI involvement to the distributor (AI credits in "
        "DDEX metadata, as Spotify and its distributors adopted in 2025), make sure the generator's plan grants "
        "commercial rights, and never imitate a real artist's voice — impersonation is removed",
        "музыка, созданная ИИ, на стримингах: укажите дистрибьютору участие ИИ (пометки ИИ в метаданных DDEX, "
        "принятые Spotify и его дистрибьюторами в 2025), убедитесь, что тариф генератора даёт коммерческие права, "
        "и не подражайте голосу реального артиста — такие треки удаляют",
        P,
        _distribution,
        ("outputs",),
        "spec.delivery.platform = 'music-distribution'",
        (S_SPOTIFY_AI,),
    ),
    _r(
        "music_content_id",
        [],
        "generated music and Content ID: do not register a generated track in Content ID unless you hold exclusive "
        "rights to it (other users of the same service may get near-identical output), and expect false claims "
        "against your own video — keep the generation record to dispute them",
        "сгенерированная музыка и Content ID: не регистрируйте сгенерированный трек в Content ID без "
        "исключительных прав на него (у других пользователей того же сервиса может выйти почти то же самое) и "
        "будьте готовы к ложным заявкам на собственное видео — храните запись генерации, чтобы их оспорить",
        P,
        _monetised_music,
        ("outputs",),
        sources=(S_CONTENT_ID,),
    ),
    # --- stock licences ------------------------------------------------------------------------
    _r(
        "stock_licence_scope",
        [],
        "stock footage, photos or music: check the licence tier against the use (standard vs extended for large "
        "print runs, merchandise, broadcast or paid ads), never use 'editorial use only' items in advertising, and "
        "check whether the licence forbids using the item as AI input",
        "стоковые видео, фото или музыка: сверьте уровень лицензии с использованием (стандартная или "
        "расширенная — для больших тиражей, мерча, эфира и платной рекламы), не берите материалы «только для "
        "редакционного использования» в рекламу и проверьте, не запрещает ли лицензия подавать материал в ИИ",
        P,
        _stock_use,
        ("inputs",),
        "spec.inputs[].licence = 'stock'",
        (S_SHUTTERSTOCK_LICENCE,),
    ),
    _r(
        "stock_ai_submission",
        [],
        "selling generated work on stock sites: the rules differ — Adobe Stock accepts it with the 'Created using "
        "generative AI tools' box ticked and no real people, artists or brands in prompts; some agencies accept "
        "no AI content at all — read the agency's policy first",
        "продажа сгенерированного на стоках: правила разные — Adobe Stock принимает такие работы с отметкой "
        "«Created using generative AI tools» и без реальных людей, художников и брендов в промптах; часть "
        "агентств ИИ-контент не принимает вовсе — сначала прочтите правила агентства",
        P,
        _stock_sell,
        ("outputs",),
        sources=(S_ADOBE_STOCK_AI,),
    ),
    # --- print ---------------------------------------------------------------------------------
    _r(
        "print_cmyk_bleed",
        [],
        "print: generators output sRGB — convert to CMYK with the printer's ICC profile (FOGRA39/51, GRACoL) and "
        "soft-proof, because saturated blues, greens and neon go out of gamut; add bleed (3 mm / 0.125 in) and "
        "keep text 3-5 mm inside the trim",
        "печать: генераторы отдают sRGB — переводите в CMYK по ICC-профилю типографии (FOGRA39/51, GRACoL) с "
        "экранной цветопробой, потому что насыщенные синие, зелёные и неон выходят за охват; добавьте вылеты "
        "(3 мм) и держите текст на 3-5 мм внутри обреза",
        E,
        _print_still,
        ("outputs",),
        "spec.delivery.platform = 'print'",
        (S_ICC,),
    ),
    _r(
        "print_vector_text",
        [],
        "print text and logos go out as vectors in a print PDF (PDF/X-1a or PDF/X-4), laid over the generated "
        "image — rasterised small type prints soft and generated lettering is not exact",
        "текст и логотипы для печати идут векторами в печатном PDF (PDF/X-1a или PDF/X-4) поверх сгенерированной "
        "картинки — растровый мелкий шрифт печатается мыльно, а сгенерированные буквы неточны",
        E,
        _print_text,
        ("outputs",),
        "spec.delivery.platform = 'print'",
        (S_PDFX,),
    ),
    # --- social platforms -----------------------------------------------------------------------
    _r(
        "short_form_length_cap",
        [],
        "{seconds} s vertical: YouTube Shorts and Instagram Reels take up to 3 minutes; a longer vertical upload "
        "becomes a regular video (no Shorts shelf) — cut a version of at most 180 s for the short-form feed",
        "вертикальное видео {seconds} с: YouTube Shorts и Instagram Reels берут до 3 минут; более длинная "
        "вертикальная загрузка становится обычным видео (без полки Shorts) — сделайте версию не длиннее 180 с "
        "для ленты коротких видео",
        P,
        _short_too_long,
        ("duration_s", "aspect", "task"),
        "spec.delivery.platform = 'youtube-shorts' | 'reels' | 'tiktok'",
        (S_SHORTS_3MIN,),
    ),
    _r(
        "platform_thumbnail",
        [],
        "thumbnail / cover: YouTube custom thumbnails are 1280x720 (16:9, under 2 MB, JPG/PNG); vertical covers "
        "are 1080x1920 with the key content in the centre crop the grid shows — design it as a still, with text "
        "laid over, not taken from a generated frame",
        "превью и обложка: свои превью YouTube — 1280x720 (16:9, до 2 МБ, JPG/PNG); вертикальные обложки — "
        "1080x1920 с главным в центральной части, которую показывает сетка — делайте её отдельной картинкой с "
        "текстом слоем, а не кадром из генерации",
        P,
        _cover,
        ("outputs",),
        "spec.delivery.platform = 'youtube' | 'tiktok' | 'instagram'",
        (S_YT_THUMB,),
    ),
    _r(
        "social_commercial_music",
        [],
        "music in a brand or paid social post: the platform's general music library is for personal posts only — "
        "use the commercial music library (TikTok Commercial Music Library, Meta Sound Collection) or a track you "
        "hold a commercial licence for",
        "музыка в брендовом или платном посте: общая музыкальная библиотека площадки — только для личных "
        "публикаций — берите коммерческую библиотеку (Commercial Music Library в TikTok, Sound Collection у Meta) "
        "или трек с коммерческой лицензией",
        P,
        _social_music_ad,
        ("outputs",),
        "spec.domain = 'advertising'",
        (S_TIKTOK_CML,),
    ),
    _r(
        "branded_content_disclosure",
        [],
        "paid partnerships and influencer posts are disclosed: the platform's paid-partnership label plus a clear "
        "'ad' / 'sponsored' (FTC Endorsement Guides in the US, ASA/CAP in the UK) — and an AI-generated "
        "'influencer' is disclosed as synthetic as well",
        "платные партнёрства и посты блогеров раскрываются: метка площадки о платном партнёрстве и ясное "
        "«реклама» (руководство FTC об одобрениях в США, ASA/CAP в Великобритании) — а сгенерированный ИИ "
        "«блогер» раскрывается ещё и как синтетический",
        R,
        _sponsored,
        (),
        "spec.domain = 'advertising'",
        (S_FTC_ENDORSE,),
    ),
    # --- e-commerce ---------------------------------------------------------------------------
    _r(
        "marketplace_main_image",
        [],
        "marketplace main image (Amazon class): pure white background RGB 255,255,255, the product filling about "
        "85 % of the frame, at least 1000 px on the longest side for zoom, no text, badges, props or watermark — "
        "generated lifestyle scenes go to the secondary images",
        "главное фото на маркетплейсе (класса Amazon): чисто белый фон RGB 255,255,255, товар занимает около 85 % "
        "кадра, не меньше 1000 px по длинной стороне для зума, без текста, значков, реквизита и водяных знаков — "
        "сгенерированные сцены с товаром идут в дополнительные фото",
        P,
        _marketplace_main,
        ("outputs", "inputs"),
        "spec.delivery.platform = 'marketplace'",
        (S_AMAZON_IMAGES,),
    ),
    # --- accessibility --------------------------------------------------------------------------
    _r(
        "wcag_captions",
        [],
        "accessibility: prerecorded video with speech needs synchronised captions (WCAG 2.2 SC 1.2.2, level A) "
        "with speaker IDs and sound cues for deaf viewers — required for public-sector sites (EU Web "
        "Accessibility Directive, US ADA Title II) and, since June 2025, many EU services (European Accessibility "
        "Act)",
        "доступность: записанное видео с речью требует синхронных субтитров (WCAG 2.2, критерий 1.2.2, уровень A) "
        "с указанием говорящих и звуковыми пометками для глухих зрителей — обязательно для госсайтов (директива "
        "ЕС о доступности веб-сайтов, ADA раздел II в США) и с июня 2025 для многих услуг в ЕС (Европейский акт "
        "о доступности)",
        R,
        _a11y_video,
        ("outputs",),
        "spec.accessibility = ['captions', 'audio-description']",
        (S_WCAG,),
    ),
    _r(
        "audio_description",
        [],
        "information shown only in picture (on-screen text, actions, a product shot) needs audio description for "
        "blind viewers (WCAG 2.2 SC 1.2.5, level AA): write the description into the voice-over pauses or deliver "
        "a described version",
        "то, что показано только картинкой (текст в кадре, действия, показ товара), требует тифлокомментария для "
        "незрячих зрителей (WCAG 2.2, критерий 1.2.5, уровень AA): впишите описание в паузы закадрового текста "
        "или сдайте версию с тифлокомментарием",
        R,
        _a11y_video,
        ("outputs",),
        "spec.accessibility = ['captions', 'audio-description']",
        (S_WCAG_AD,),
    ),
    _r(
        "photosensitive_flashes",
        [],
        "flashing and strobe effects: no more than 3 flashes per second and no saturated-red flashes (WCAG 2.3.1; "
        "broadcasters test with ITU-R BT.1702 / Harding-class analysers) — generated glitch and strobe effects "
        "often fail; test the final render",
        "вспышки и стробоскоп: не больше 3 вспышек в секунду и без насыщенно-красных вспышек (WCAG 2.3.1; "
        "вещатели проверяют по ITU-R BT.1702 анализаторами класса Harding) — сгенерированные глитч- и "
        "строб-эффекты часто не проходят; проверьте финальный рендер",
        R,
        _flash,
        ("outputs",),
        "spec.conditions[] = 'flashing'",
        (S_BT1702, S_WCAG),
    ),
    # --- people: deceased, minors, endorsements, famous voices ------------------------------------
    _r(
        "deceased_likeness",
        [],
        "a deceased real person: post-mortem publicity rights belong to the estate (California Civil Code 3344.1, "
        "70 years; New York's digital-replica law; other countries' personality rights) — get the estate's written "
        "consent and label the recreation",
        "умерший реальный человек: посмертные права на образ принадлежат наследникам (Гражданский кодекс "
        "Калифорнии, 3344.1 — 70 лет; закон Нью-Йорка о цифровых копиях; права личности в других странах) — "
        "получите письменное согласие наследников и пометьте воссоздание",
        R,
        _deceased,
        ("people",),
        sources=(S_CA_3344_1,),
    ),
    _r(
        "minor_on_screen",
        [],
        "a real minor on screen: get a parent's or guardian's written consent, keep the content age-appropriate, "
        "and follow the platform's child-safety rules (on YouTube comments may be restricted on such videos)",
        "реальный несовершеннолетний в кадре: нужно письменное согласие родителя или опекуна, содержание по "
        "возрасту и правила безопасности детей на площадке (на YouTube комментарии к таким роликам могут "
        "отключить)",
        R,
        _minor,
        ("people",),
        sources=(S_YT_MINORS,),
    ),
    _r(
        "fake_endorsement",
        [],
        "a real person endorsing a product needs their written agreement to that exact endorsement: a synthetic "
        "endorsement is deceptive advertising (FTC Act s. 5 and the FTC impersonation rule, 2024; ad codes "
        "elsewhere), and the endorser must actually use the product",
        "реальный человек, одобряющий товар, должен письменно согласиться именно на это одобрение: синтетическое "
        "одобрение — недобросовестная реклама (FTC Act, раздел 5, и правило FTC о выдаче себя за другого, 2024; "
        "рекламные кодексы в других странах), а сам рекомендующий должен пользоваться товаром",
        R,
        _endorsement,
        ("people",),
        sources=(S_FTC_IMPERSONATION, S_FTC_ENDORSE),
    ),
    _r(
        "voice_publicity_rights",
        [],
        "a public figure's voice is protected as part of their likeness (Tennessee ELVIS Act 2024 names the voice "
        "explicitly; right of publicity elsewhere) — synthesising or cloning it for content needs their licence",
        "голос публичного человека защищён как часть его образа (закон Теннесси ELVIS 2024 прямо называет "
        "голос; право на образ в других местах) — синтез или клон для контента требует его лицензии",
        R,
        _famous_voice,
        ("people",),
        sources=(S_TN_ELVIS,),
    ),
    # --- news, China, VFX / editorial handoff, regulated ads, app stores -----------------------------
    _r(
        "news_synthetic_label",
        [],
        "news and documentary: generated or AI-altered footage is never presented as a record — label it on "
        "screen as an AI reconstruction or illustration, keep it apart from real footage, and keep the generation "
        "record",
        "новости и документалистика: сгенерированные или изменённые ИИ кадры никогда не выдаются за запись "
        "событий — помечайте их на экране как реконструкцию или иллюстрацию ИИ, держите отдельно от настоящей "
        "съёмки и храните запись генерации",
        P,
        _news,
        ("people",),
        "spec.domain = 'news'",
        (S_YT_SYNTHETIC, S_C2PA),
    ),
    _r(
        "china_ai_label",
        [],
        "publishing in China: AI-generated text, images, audio and video carry an explicit label (visible or "
        "audible) and an implicit one in the file metadata under the CAC labelling measures (in force since "
        "1 September 2025, standard GB 45438-2025)",
        "публикация в Китае: созданные ИИ текст, изображения, звук и видео несут явную метку (видимую или "
        "звучащую) и скрытую в метаданных файла по правилам маркировки CAC (действуют с 1 сентября 2025, "
        "стандарт GB 45438-2025)",
        R,
        _china,
        ("jurisdiction",),
        sources=(S_CN_LABEL,),
    ),
    _r(
        "vfx_plate_handoff",
        [],
        "VFX handoff: deliver generated shots as EXR or DPX image sequences in the facility's colour pipeline "
        "(ACEScg / ACES2065-1 or the agreed log space), ungraded, with 8-12 frame handles and the generation "
        "settings — an H.264 export cannot be composited cleanly",
        "передача в VFX: сгенерированные шоты отдаются секвенциями EXR или DPX в цветовом конвейере студии "
        "(ACEScg / ACES2065-1 или согласованное лог-пространство), без грейда, с запасом 8-12 кадров и "
        "настройками генерации — экспорт H.264 чисто не скомпозить",
        E,
        _vfx,
        ("outputs",),
        "spec.delivery.platform = 'vfx'",
        (S_ACES,),
    ),
    _r(
        "editorial_handoff",
        [],
        "handing generated clips to an editor: export an intermediate codec (ProRes 422 HQ / DNxHR) at a "
        "constant frame rate, with unique file names, timecode and a shot list (prompt, seed, model) — long-GOP "
        "web files with variable frame rate drift out of sync in the edit",
        "передача роликов монтажёру: выгружайте в промежуточном кодеке (ProRes 422 HQ / DNxHR) с постоянной "
        "частотой кадров, уникальными именами файлов, таймкодом и списком шотов (промпт, сид, модель) — "
        "веб-файлы с длинной группой кадров и переменной частотой расходятся по синхрону в монтаже",
        E,
        _editorial,
        ("outputs",),
        "spec.delivery.platform = 'editorial'",
    ),
    _r(
        "health_ad_claims",
        [],
        "health, medicine or supplement advertising: no generated 'doctor', 'nurse' or patient testimonial "
        "presented as real, and every health claim must be substantiated or authorised (UK CAP Code section 12; "
        "FDA/FTC in the US; EU health-claims register)",
        "реклама здоровья, лекарств или БАД: никаких сгенерированных «врачей», «медсестёр» или отзывов пациентов "
        "под видом настоящих, а каждое заявление о здоровье должно быть доказано или разрешено (раздел 12 "
        "кодекса CAP в Великобритании; FDA/FTC в США; реестр заявлений о здоровье ЕС)",
        R,
        _health_ad,
        (),
        "spec.domain = 'health-advertising'",
        (S_CAP_HEALTH,),
    ),
    _r(
        "financial_promo",
        [],
        "financial products (investment, crypto, credit, insurance): the promotion must be fair, clear and not "
        "misleading with risk warnings (UK FCA financial promotion rules; similar elsewhere), and an AI-made "
        "spokesperson or 'customer' is not presented as real",
        "финансовые продукты (инвестиции, крипта, кредит, страхование): продвижение должно быть честным, ясным и "
        "не вводящим в заблуждение, с предупреждением о рисках (правила FCA Великобритании о финансовой рекламе; "
        "похожие в других странах), а сгенерированный ИИ «представитель» или «клиент» не выдаётся за настоящего",
        R,
        _finance_ad,
        (),
        "spec.domain = 'financial-advertising'",
        (S_FCA_PROMO,),
    ),
    _r(
        "app_preview_specs",
        [],
        "App Store app preview: 15-30 s, the device's exact resolution (e.g. 886x1920 portrait for 6.9-inch "
        "iPhone), and footage captured from the app itself — generated scenes of the app are rejected; Google Play "
        "takes a YouTube link instead",
        "превью приложения в App Store: 15-30 с, точное разрешение устройства (например, 886x1920 вертикально для "
        "iPhone 6,9 дюйма) и кадры, снятые с самого приложения — сгенерированные сцены приложения отклоняют; "
        "Google Play берёт ссылку на YouTube",
        P,
        _app_preview,
        ("outputs",),
        "spec.delivery.platform = 'app-store'",
        (S_APP_PREVIEW,),
    ),
)

RULES_LIST = RULES_LIST + RULES_R12

# --- round 13: expert caveats -------------------------------------------------------------
#
# Structured triggers first (job codes, `spec.edit`, `spec.languages`, `spec.inputs`
# counts, `spec.people[].role`, `spec.claims[].own_brand`); words only where the spec
# has no field, and each such rule names the field in `spec_field`.

#: From this many video inputs the material is multi-camera (angles to sync).
MULTICAM_MIN_INPUTS = 2
#: Longest single generation most video models record (5-15 s; a few reach 20-25 s).
#: The planner prints the CHOSEN model's recorded run limit (`run_limit` on the step).
SINGLE_TAKE_TYPICAL_MAX_S = 15.0
#: Jobs that GENERATE a take from a prompt or a frame (a talking avatar follows its audio, any length).
GENERATED_TAKE_JOBS: frozenset[str] = frozenset({"t2v", "i2v", "t2v_audio", "r2v"})
#: Jobs whose model is trained on real human faces (photoreal mouth / face).
PHOTOREAL_FACE_JOBS: frozenset[str] = frozenset({"lipsync", "avatar", "sing", "char_replace", "dub"})
#: Round 14: from this many GENERATED shots, light named in the brief is a cross-shot consistency job.
RELIGHT_SERIES_MIN_SHOTS = 2
#: Roles of a real person that make them the customer's own staff (`spec.people[].role`).
IN_HOUSE_ROLES: frozenset[str] = frozenset({"employee", "self"})

W_GREEN_SCREEN = re.compile(
    r"green ?screen|blue ?screen|chroma ?key|\bkey(?:ing|ed)? (?:out|it)\b|\bkeyer\b|\bkeying\b|\bdespill"
    r"|хромакей|хрома-?кей|зел[её]н\w* (?:фон|экран)|син\w* (?:фон|экран)|грин ?скрин|кеинг\w*",
    re.I,
)
W_STYLISED_FACE = re.compile(
    r"cartoon|\banime\b|\bmanga\b|\bchibi\b|pixar|\b3d (?:character|avatar|mascot)|\bmascot|stylis|styliz|cel[- ]shad"
    r"|hand-?drawn|\bdrawn\b|illustrat|\bclay(?:mation)?\b|puppet|plush|\btoy\b|\bcomic\b|vtuber|\banimal\b|\bdog\b|\bcat\b"
    r"|мульт\w*|аниме|манга|рисованн\w*|нарисованн\w*|стилизованн\w*|маскот|талисман|3d[- ]персонаж|кукл\w*|пластилин"
    r"|игрушк\w*|комикс|втубер|животн\w*|собак\w*|кошк\w*|\bкот\b",
    re.I,
)
W_TRAINING_DATA = re.compile(
    r"training (?:data|set|images|clips|corpus)|train(?:ing)? (?:a |our |my |an? )?(?:own |custom )?(?:model|lora|classifier|detector|network)"
    r"|fine-?tun\w*|\bdataset|\bdata ?set\b|synthetic data|data augmentation|train(?:ing)? (?:on|with) (?:them|these|it|the (?:images|clips|outputs))"
    r"|(?:to|for|will) (?:train|teach) (?:our|my|a|an|the) (?:own )?(?:\w+ )?(?:model|ai|network|classifier|detector|system)"
    r"|\bfor (?:ml|machine learning|model) training|\bml training|ground[- ]truth (?:set|data)|labell?ed (?:set|data)"
    r"|датасет|дата-?сет|обучающ\w* (?:выборк|данн|набор)|для обучения|обучени\w* (?:модел|нейросет|сет|ии)|дообуч\w*|синтетическ\w* данн"
    r"|(?:учить|обучать|обучить|натренировать|тренировать|научить) (?:\w+ )?(?:нейросет|модел|сет[ьи]|ии\b|классификатор|детектор|алгоритм)"
    r"|на них (?:будем |будут )?(?:учить|обучать|тренировать)|разметк\w* (?:для|под) (?:обучени|модел)",
    re.I,
)
W_RELIGHT = re.compile(
    r"relight\w*|re-light\w*|change (?:the )?light(?:ing)?|lighting change|переосвет\w*|измен\w* (?:свет|освещени)|смен\w* (?:свет|освещени)"
    # Round 14: matching / unifying the light across shots is relighting too.
    r"|(?:match|unify|equali[sz]e|even out|consistent|same|uniform|continuous|harmoni[sz]e)\w* (?:\w+ ){0,3}?(?:light|lighting|illumination)\b"
    r"|(?:light|lighting|illumination) (?:\w+ ){0,3}?(?:match|consistent|the same|uniform|differs|is different|varies|changes between)"
    r"|golden[- ]hour (?:light|lighting|look)|(?:make|turn) (?:it|the scene|the shot|the clip) (?:look )?(?:like )?(?:sunset|golden hour|evening|morning) light"
    r"|(?:одинаков|един|ровн|согласованн|похож)\w* (?:\w+ )?(?:свет|освещени)|(?:свет|освещени)\w* (?:\w+ ){0,3}?(?:одинаков|совпада|разн|отлича|скач|прыга|подогна|выровня)"
    r"|(?:подогна|выровня|уравня|свест)\w* (?:\w+ )?(?:свет|освещени)|свет\w* (?:как|под) (?:в|на) (?:соседн|другом|первом)",
    re.I,
)
W_MULTICAM = re.compile(
    r"multi-?cam\w*|multiple cameras|several cameras|two cameras|three cameras|\b[2-9] cameras|camera angles|several angles"
    r"|\bcam (?:a|b)\b|нескольк\w* камер|дв[еуx]\w* камер|тр[её]х камер|мультикам\w*",
    re.I,
)
W_RTL_NAMED = re.compile(r"arabic|hebrew|persian|farsi|\burdu\b|yiddish|pashto|араб\w*|иврит\w*|фарси|персидск\w*|урду", re.I)
W_BURN_IN = re.compile(
    r"burn(?:ed|t)?[- ]?in|hard-?(?:coded|subs?)|open captions|subtitl\w*|\bcaptions?\b|вшит\w*|вжит\w*|прожечь|субтитр\w*",
    re.I,
)

S_BFL_TERMS = "https://bfl.ai/legal/terms-of-service"
S_FLUX_DEV_LICENCE = "https://raw.githubusercontent.com/black-forest-labs/flux/main/model_licenses/LICENSE-FLUX1-dev"
S_FAL_TERMS = "https://fal.ai/terms"
S_WAN_LICENCE = "https://raw.githubusercontent.com/Wan-Video/Wan2.1/main/README.md"
S_LIBASS = "https://github.com/libass/libass"


def _green_screen(c: Ctx) -> bool:
    return bool(c.steps or c.jobs) and c.says(W_GREEN_SCREEN)


def _stylised_face(c: Ctx) -> bool:
    """A model trained on real faces, asked to work on a drawn / 3D / animal face."""
    return bool(c.jobs & PHOTOREAL_FACE_JOBS) and (c.says(W_STYLISED_FACE) or c.says(W_ANIMATION_TWOS))


def _training_data(c: Ctx) -> bool:
    return bool(c.steps or c.jobs) and c.says(W_TRAINING_DATA)


def _colorize_any(c: Ctx) -> bool:
    return "colorize" in c.jobs


def _relight(c: Ctx) -> bool:
    """Relighting asked: `spec.edit`, the words on an edit step, or (round 14) matching the light across
    several generated shots — the rule is not gated by step type any more, the trigger decides."""
    if not (c.steps or c.jobs):
        return False
    if "relight" in tuple(c.spec.edit or ()):
        return True
    if not c.says(W_RELIGHT):
        return False
    if c.jobs & {"v2v_edit", "image_edit"}:
        return True
    return bool(c.jobs & (VIDEO_GEN | STILL_GEN)) and int(c.spec.shots or 1) >= RELIGHT_SERIES_MIN_SHOTS


def _multicam(c: Ctx) -> dict[str, str] | None:
    видео = [з for з in c.spec.input_items if str(з.get("kind")) == "video"]
    штук = sum(max(1, int(з.get("count") or 1)) for з in видео)
    if штук >= MULTICAM_MIN_INPUTS:
        return {"n": str(штук)}
    if видео and c.says(W_MULTICAM):
        return {"n": "2+"}
    return None


def _rtl_burn_in(c: Ctx) -> dict[str, str] | None:
    rtl = sorted(c.langs & RTL_LANGS)
    if not rtl and c.says(W_RTL_NAMED):
        rtl = ["RTL"]
    текст_в_кадре = bool(c.jobs & (TEXT_ON_SCREEN | {"captions", "transcribe"})) or c.says(W_BURN_IN)
    if rtl and текст_в_кадре and (c.video or "text" in c.outputs or c.says(W_BURN_IN)):
        return {"langs": ", ".join(rtl)}
    return None


def _single_take(c: Ctx) -> dict[str, str] | None:
    """One generated shot longer than a single run of most video models."""
    if not c.jobs & GENERATED_TAKE_JOBS:
        return None
    шот = float(c.spec.per_shot_s or 0) or (float(c.spec.duration_s or 0) if int(c.spec.shots or 1) <= 1 else 0.0)
    if шот > SINGLE_TAKE_TYPICAL_MAX_S:
        return {"seconds": f"{шот:g}"}
    # ЧЕТЫРНАДЦАТЫЙ КРУГ: предел — у ВЫБРАННОЙ модели, а не типичный. Шаг
    # напечатал `run_limit` (дубль длиннее её записанного прогона) — заметка
    # идёт и для дубля короче 15 с (8-секундная Veo на 12-секундном дубле).
    прогон = chosen_run_s(c.priors)
    if прогон:
        шотов = max(1, int(c.spec.shots or 1))
        шот = шот or float(c.spec.duration_s or 0) / шотов
        return {"seconds": f"{шот:g}"} if шот > прогон else None
    return None


def _text_edit(c: Ctx) -> bool:
    return "replace-text" in tuple(c.spec.edit or ())


def _in_house_anchor(c: Ctx) -> bool:
    """A consented real person of the customer's own staff reading news (the claims were decided by the
    people policy before the plan: fabricated news or another broadcaster's brand never reach here)."""
    свои = any(
        п.get("real") is True
        and п.get("consent") == "stated"
        and str(п.get("role") or "") in IN_HOUSE_ROLES
        and п.get("claim") == "news"
        for п in c.spec.people
    )
    return свои and bool(c.steps or c.jobs)


RULES_R13: tuple[Rule, ...] = (
    _r(
        "green_screen_keying",
        [],
        "green / blue screen: key it with a real keyer before any AI step — despill the green on hair, skin and "
        "edges, pull a soft edge matte separately from the solid core matte, and expect motion blur and fine hair "
        "to need a hand-tuned edge (AI background removal does not despill and chatters on blur); light the screen "
        "evenly, use a fast shutter and the least compressed source",
        "зелёный / синий фон: кеинг настоящим кеером до любого шага ИИ — уберите зелёные рефлексы (despill) с "
        "волос, кожи и краёв, снимите мягкую маску краёв отдельно от плотной маски ядра и ждите, что смаз движения "
        "и тонкие волосы потребуют ручной настройки края (удаление фона ИИ рефлексы не убирает и дрожит на "
        "смазе); фон освещается ровно, выдержка короткая, исходник — наименее сжатый",
        E,
        _green_screen,
        ("inputs",),
        "spec.inputs[].keying = 'green-screen'",
        (S_FFMPEG_FILTERS,),
    ),
    _r(
        "stylised_face_photoreal_model",
        sorted(PHOTOREAL_FACE_JOBS),
        "a stylised face (cartoon, anime, 3D character, mascot or animal) on a lip-sync / face-swap / avatar "
        "model trained on real human faces: the face detector may miss it, the mouth comes out smeared or "
        "photoreal, and line art breaks — test 5 s first, prefer a model that records stylised or anime support, "
        "or animate the mouth in the style (viseme mouth shapes on the rig, Live2D, Character Animator)",
        "стилизованное лицо (мультяшное, аниме, 3D-персонаж, маскот или животное) на модели липсинка, замены лица "
        "или аватара, обученной на настоящих лицах: детектор лица может его не найти, рот выходит смазанным или "
        "фотореалистичным, контурные линии рвутся — сначала проверьте 5 с, берите модель, у которой записана "
        "поддержка стилизованных или аниме-лиц, или анимируйте рот в стиле (формы рта по фонемам на риге, Live2D, "
        "Character Animator)",
        E,
        _stylised_face,
        ("people", "characters"),
        "spec.subject.style = 'stylised'",
    ),
    _r(
        "outputs_as_training_data",
        [],
        "generated outputs used as ML training data: each provider's terms decide, per step — the BFL API terms "
        "forbid using Output to train, distill or fine-tune any other AI model; the FLUX.1 [dev] licence forbids "
        "training a model competitive with it; fal's terms forbid using outputs of third-party models it hosts to "
        "train competing models; Apache-2.0 open weights (Wan 2.1) claim no rights over the outputs. Check the "
        "terms of every model in the plan before the data set is built, and log model, version and terms date per "
        "sample",
        "сгенерированное как обучающие данные: решают условия каждого поставщика, по шагам — условия API BFL "
        "запрещают использовать результат для обучения, дистилляции или дообучения любой другой модели ИИ; "
        "лицензия FLUX.1 [dev] запрещает обучать конкурирующую с ней модель; условия fal запрещают обучать "
        "конкурирующие модели на результатах сторонних моделей, которые он размещает; открытые веса под "
        "Apache-2.0 (Wan 2.1) прав на результат не заявляют. Проверьте условия каждой модели плана до сборки "
        "датасета и записывайте модель, версию и дату условий на каждый образец",
        R,
        _training_data,
        (),
        "spec.use = 'training-data'",
        (S_BFL_TERMS, S_FLUX_DEV_LICENCE, S_FAL_TERMS, S_WAN_LICENCE),
    ),
    _r(
        "colorize_plausible_not_true",
        ["colorize"],
        "colourisation is a plausible guess, not historical truth: the model invents colours that look right "
        "(uniforms, flags, cars, skin and sky can be wrong) — disclose it as 'colourised with AI' wherever it is "
        "shown, keep the black-and-white original alongside, and use references or a historian where colour "
        "matters",
        "раскраска — правдоподобная догадка, а не историческая правда: модель придумывает цвета, которые выглядят "
        "верно (форма, флаги, машины, кожа и небо могут быть не теми) — помечайте «раскрашено ИИ» везде, где это "
        "показывают, храните чёрно-белый оригинал рядом и берите референсы или историка там, где цвет важен",
        P,
        _colorize_any,
        ("task", "steps"),
        "",
        (S_YT_SYNTHETIC,),
    ),
    _r(
        "relight_limits",
        [],
        "relighting re-renders shading from an estimate of the shape: it can move the key light and change the "
        "mood, but it cannot recover blown highlights or crushed shadows, it invents speculars and cast shadows, "
        "and strong changes flatten skin texture and flicker over time — keep changes moderate, match the plate's "
        "light for composites, and relight in 3D (depth / normal passes) or reshoot when it must be exact; across "
        "several shots keep the light consistent: one lighting setup (direction, colour temperature, intensity) "
        "and one reference frame or HDRI for every shot, the same model, prompt and seed, and one shared grade "
        "checked with the shots side by side",
        "переосвещение пересчитывает светотень по оценке формы: оно сдвигает ключевой свет и меняет настроение, "
        "но не вернёт пересвеченные света и заваленные тени, придумывает блики и падающие тени, а сильная правка "
        "сглаживает текстуру кожи и мерцает во времени — меняйте умеренно, подгоняйте свет под плейт при "
        "композитинге, а где нужно точно — переосвещение в 3D (проходы глубины и нормалей) или пересъёмка; на "
        "нескольких шотах свет держится одинаковым: одна схема света (направление, цветовая температура, "
        "интенсивность) и одна опорная картинка или HDRI на все шоты, одна модель, промпт и сид, и общий "
        "грейд с проверкой шотов рядом",
        E,
        _relight,
        ("edit",),
    ),
    _r(
        "multicam_sync",
        [],
        "multi-camera material ({n} angles): sync the angles before any AI step — by timecode (jam-synced / LTC), "
        "a clap or slate, or the audio waveform (PluralEyes, Resolve 'sync by audio', Premiere 'synchronize') — "
        "keep one master audio track, and make every AI step keep the frame count and frame rate (no retiming), or "
        "the sync is lost",
        "многокамерный материал ({n} ракурса): синхронизируйте ракурсы до любого шага ИИ — по таймкоду (общий "
        "генератор / LTC), по хлопушке или по форме звуковой волны (PluralEyes, «sync by audio» в Resolve, "
        "«synchronize» в Premiere) — держите одну мастер-дорожку звука и следите, чтобы каждый шаг ИИ сохранял "
        "число кадров и частоту (без перетайминга), иначе синхронизация уйдёт",
        E,
        _multicam,
        ("inputs",),
    ),
    _r(
        "rtl_burn_in",
        [],
        "burning right-to-left subtitles ({langs}) into the picture: render with libass built with HarfBuzz and "
        "FriBidi (ffmpeg 'subtitles' / 'ass' filter) and an embedded font that covers the script — a renderer "
        "without shaping writes disconnected letters in the wrong order; mark punctuation and numbers with "
        "RLM/LRM where the bidi algorithm misplaces them, right-align the lines, and ship a sidecar SRT/VTT too",
        "вжигание субтитров справа налево ({langs}) в картинку: рендер через libass, собранный с HarfBuzz и "
        "FriBidi (фильтр ffmpeg «subtitles» / «ass»), и встроенный шрифт, покрывающий письмо — рендер без "
        "шейпинга пишет несоединённые буквы в обратном порядке; пунктуацию и числа помечайте RLM/LRM там, где "
        "двунаправленный алгоритм их сдвигает, строки выравнивайте вправо и отдавайте ещё и файл SRT/VTT",
        E,
        _rtl_burn_in,
        ("languages", "language_tags", "outputs"),
        "",
        (S_BIDI, S_LIBASS, S_FFMPEG_FILTERS),
    ),
    _r(
        "single_take_limit",
        sorted(GENERATED_TAKE_JOBS),
        "a single {seconds} s take is longer than one generation of most video models (about 5-15 s; the step prints "
        "the chosen model's recorded maximum per run): it is made as several runs joined by extend / last-frame "
        "continuation, and the joins show drift — or the shot is split with a cut",
        "один непрерывный дубль в {seconds} с длиннее одной генерации большинства видеомоделей (около 5-15 с; шаг "
        "печатает записанный максимум выбранной модели на прогон): его делают несколькими прогонами, сшитыми "
        "продлением или продолжением с последнего кадра, и на стыках виден дрейф — или шот режут склейкой",
        E,
        _single_take,
        ("duration_s", "shots", "per_shot_s"),
    ),
    _r(
        "in_house_anchor_disclosure",
        [],
        "your own presenter reading your own newsroom's true news: keep the presenter's written consent to an AI "
        "likeness with its scope and end date, label every item on screen and in the description as made with an "
        "AI-generated presenter (EU AI Act art. 50 deepfake disclosure; platform synthetic-media labels), keep the "
        "newsroom's editorial sign-off on the script, never let the avatar read anything the presenter or the "
        "newsroom did not approve, and attach C2PA content credentials",
        "ваш ведущий читает правдивые новости вашей редакции: храните письменное согласие ведущего на ИИ-образ с "
        "объёмом и сроком, помечайте каждый выпуск в кадре и в описании как сделанный с ИИ-ведущим (статья 50 "
        "AI Act ЕС о раскрытии дипфейков; метки синтетических медиа площадок), сохраняйте редакционное "
        "утверждение текста, не давайте аватару читать то, что ведущий или редакция не одобрили, и прикладывайте "
        "C2PA content credentials",
        R,
        _in_house_anchor,
        ("people", "claims"),
        "",
        (S_AI_ACT, S_YT_SYNTHETIC, S_C2PA),
    ),
    _r(
        "text_edit_in_video",
        ["v2v_edit"],
        "lettering in the shot (a sign, a label, a billboard) is an inpaint / video-edit job with text rendering, "
        "not a character swap: mask the surface, draw the new text into it and check spelling, font and "
        "perspective on every frame — AI edits misspell and drift; for exact typography planar-track the surface "
        "(Mocha / After Effects) and composite the text at assembly",
        "надпись в кадре (вывеска, этикетка, билборд) — правка по маске с отрисовкой текста, а не замена "
        "персонажа: маска поверхности, новый текст внутри неё, а орфографию, шрифт и перспективу проверяйте на "
        "каждом кадре — правки ИИ ошибаются в буквах и плывут; для точной типографики — планарный трекинг "
        "поверхности (Mocha / After Effects) и композитинг текста на монтаже",
        E,
        _text_edit,
        ("edit",),
    ),
)

RULES_LIST = RULES_LIST + RULES_R13

# --- round 14 -----------------------------------------------------------------------------
#
# Expert caveats the round-14 hidden set found missing on natural phrasings
# (structured fields first, then EN/RU cue sets).

#: A prior the planner adds when a step's CHOSEN model records a shorter run than the take
#: (the step carries `run_limit`): the single-take note follows the chosen model, not the typical 15 s.
RUN_OVER_PRIOR = "chosen_model_run_over"
#: The chosen model's recorded run in a step's `run_limit` line (EN and RU wording of `planner.run_limit_line`).
RUN_S_IN_LINE = re.compile(r"(?:is at most|не больше) (\d+(?:\.\d+)?) (?:s|с)\b")


def run_over_priors(lines: "Iterable[object]") -> tuple[str, ...]:
    """Priors for the notes from the steps' `run_limit` lines: `RUN_OVER_PRIOR:<shortest recorded run>`."""
    прогоны = [float(m.group(1)) for л in lines if л and (m := RUN_S_IN_LINE.search(str(л)))]
    return (f"{RUN_OVER_PRIOR}:{min(прогоны):g}",) if прогоны else ()


def chosen_run_s(priors: "Iterable[str]") -> float | None:
    """The chosen model's recorded run carried by `run_over_priors`; None — no step is over its run."""
    for п in priors:
        if str(п).startswith(RUN_OVER_PRIOR + ":"):
            try:
                return float(str(п).split(":", 1)[1])
            except ValueError:
                return None
    return None
#: Claim types that make a synthetic presenter's script news-shaped (`spec.claims[].type`).
PRESENTER_NEWS_TYPES: frozenset[str] = frozenset({"news", "real_event"})
#: Jobs that swap a face (video character replacement, image face swap).
FACE_SWAP_JOBS: frozenset[str] = frozenset({"char_replace", "face_swap"})
#: From this many swapped items the order is a face-swap data set (with or without the words).
FACE_SWAP_DATASET_MIN = 20

W_HOLOGRAM = re.compile(
    r"hologra\w*|pepper'?’?s[- ]ghost|holo[- ]?(?:fan|box|gauze|screen|display|cube|stage)|hypervsn"
    r"|transparent (?:led|oled|lcd|screen|display|film|glass display)|(?:led|oled) (?:film|mesh) (?:screen|display|on (?:the )?glass)"
    r"|(?:3d )?(?:led )?(?:fan|propeller) (?:display|screen)|see-through (?:led|screen|display)|projection (?:gauze|scrim)"
    r"|голограм\w*|голографи\w*|призрак\w* пеппера|голо-?(?:вентилятор|куб|бокс)"
    r"|прозрачн\w* (?:led|oled|lcd|светодиод\w*|экран\w*|дисплей\w*|панел\w*|плёнк\w*|пленк\w*)"
    r"|светодиодн\w* вентилятор|3d[- ]вентилятор",
    re.I,
)
S_GDPR = "https://eur-lex.europa.eu/eli/reg/2016/679/oj"
S_BIPA = "https://www.ilga.gov/legislation/ilcs/ilcs3.asp?ActID=3004&ChapterID=57"


def _hologram(c: Ctx) -> bool:
    """A display where black is transparent: Pepper's ghost, a holo fan, a transparent LED / OLED."""
    return bool(c.steps or c.jobs) and c.visual and c.says(W_HOLOGRAM)


def _synthetic_presenter(c: Ctx) -> bool:
    """A made-up presenter (every `spec.people[].real` false) reading news-shaped content for the
    customer's own outlet (`spec.claims[].own_brand`)."""
    люди = list(c.spec.people)
    if not люди or not all(п.get("real") is False for п in люди):
        return False
    свои = any(
        str(з.get("type") or "").lower() in PRESENTER_NEWS_TYPES and з.get("own_brand") is True
        for з in c.spec.claims
    )
    return bool(c.steps or c.jobs) and свои


def _face_swap_dataset(c: Ctx) -> dict[str, str] | None:
    """Many swapped faces, or swapped faces as training data: biometric consent and licences per identity."""
    if not c.jobs & FACE_SWAP_JOBS:
        return None
    штук = max([int(c.spec.shots or 0)] + [int(з.get("count") or 0) for з in c.spec.input_items])
    if c.says(W_TRAINING_DATA) or штук >= FACE_SWAP_DATASET_MIN:
        return {"n": str(штук) if штук > 1 else "many"}
    return None


RULES_R14: tuple[Rule, ...] = (
    _r(
        "hologram_black_background",
        [],
        "hologram / Pepper's-ghost / holo-fan / transparent LED or OLED display: BLACK is the transparent colour "
        "(the display adds light, black pixels are off) — deliver the subject on true black (RGB 0, full-range "
        "levels, no grain, vignette, haze or glow in the background), not on a green key and not with an alpha "
        "channel unless the player asks for one; key the plate with a matte and composite over 0-black, check the "
        "encoder keeps black at 0 (a limited-range 16-235 file shows a grey glowing box), and light the subject "
        "for the screen: dark clothes, hair and shadows vanish, so add a rim light, lift the darks and avoid "
        "black costumes; keep matte edges clean — a halo reads as a glowing outline",
        "голограмма / «призрак Пеппера» / голо-вентилятор / прозрачный LED- или OLED-экран: ЧЁРНЫЙ — это "
        "прозрачный цвет (экран добавляет свет, чёрные пиксели не горят) — отдавайте объект на чистом чёрном "
        "(RGB 0, полный диапазон, без зерна, виньетки, дымки и свечения на фоне), а не на зелёном фоне и не с "
        "альфа-каналом, если плеер его не просит; вырезайте по маске и кладите на 0-чёрный, проверьте, что "
        "кодировщик держит чёрный в 0 (файл в ограниченном диапазоне 16-235 светится серым прямоугольником), и "
        "светите объект под экран: тёмная одежда, волосы и тени исчезают — нужен контровой свет, поднятые тени и "
        "не чёрные костюмы; края маски чистые — ореол читается светящимся контуром",
        E,
        _hologram,
        ("outputs", "conditions"),
        "spec.display = 'additive' (hologram / transparent LED)",
        (S_FFMPEG_FILTERS, S_BT709),
    ),
    _r(
        "synthetic_presenter_disclosure",
        [],
        "a synthetic presenter for your own programme: label the presenter as AI-generated on screen and in the "
        "description of every item (EU AI Act art. 50 deepfake / AI-content disclosure; platform synthetic-media "
        "labels), make it a NEW face and voice that resembles no real person (no reference photo or voice of "
        "anyone without their consent), use only your own channel's name, logo and graphics — never another "
        "broadcaster's marks or look — keep the newsroom's editorial sign-off on every script (the avatar reads "
        "only approved, true content; nothing invented), and attach C2PA content credentials",
        "синтетический ведущий для вашей собственной программы: помечайте ведущего как созданного ИИ в кадре и в "
        "описании каждого выпуска (статья 50 AI Act ЕС о раскрытии дипфейков и ИИ-контента; метки синтетических "
        "медиа площадок), делайте НОВОЕ лицо и голос, не похожие ни на одного реального человека (без фото или "
        "голоса кого-либо без его согласия), используйте только название, логотип и графику своего канала — "
        "никогда знаки или стиль другого вещателя, — сохраняйте утверждение каждого текста редакцией (аватар "
        "читает только одобренное и правдивое, ничего выдуманного) и прикладывайте C2PA content credentials",
        R,
        _synthetic_presenter,
        ("people", "claims"),
        "",
        (S_AI_ACT, S_YT_SYNTHETIC, S_C2PA),
    ),
    _r(
        "face_swap_dataset_consent",
        [],
        "a face-swap data set ({n} items): faces are biometric data — keep written consent from EVERY identity "
        "whose face is used, covering synthetic derivatives and ML training (GDPR art. 9 explicit consent; "
        "Illinois BIPA written release; no public figures, minors or scraped faces), a licence for every target "
        "photo or clip that allows AI derivatives and training (stock licences often exclude both), a manifest "
        "per item (source, identity, consent id, model, version, terms date), and mark every item as synthetic "
        "so it never leaves the training pipeline as a real photo; the face-swap provider's terms decide whether "
        "its outputs may train a model",
        "датасет с заменой лиц ({n} шт.): лица — биометрические данные; храните письменное согласие КАЖДОГО "
        "человека, чьё лицо используется, на синтетические производные и обучение моделей (явное согласие по "
        "ст. 9 GDPR; письменное разрешение по BIPA штата Иллинойс; без публичных лиц, детей и собранных из сети "
        "лиц), лицензию на каждое целевое фото или клип, разрешающую производные ИИ и обучение (стоковые "
        "лицензии часто исключают и то и другое), манифест на каждый образец (источник, человек, номер согласия, "
        "модель, версия, дата условий) и пометку «синтетическое» на каждом образце, чтобы он не ушёл из "
        "обучения как настоящее фото; можно ли учить модель на результатах, решают условия поставщика замены лиц",
        R,
        _face_swap_dataset,
        ("people", "shots", "inputs"),
        "spec.use = 'training-data'",
        (S_GDPR, S_BIPA, S_FAL_TERMS),
    ),
)

RULES_LIST = RULES_LIST + RULES_R14

# --- round 15 -----------------------------------------------------------------------------
#
# Expert caveats the round-15 hidden set found missing (cover songs, long ambient loops,
# tileable textures, halftone scans, timelapse interpolation, style across an image set,
# no-speech shorts, anonymising passers-by). Structured spec fields first, the words second.
#
# The round-15 spec fields (`spec.loop` / `spec.tileable` from `outputs[].loop|tileable`,
# `spec.consistency`, `people[].speaks`) are read first; a field that is NAMED beats the words
# both ways (false silences the rule whatever the brief says).

#: From this many seconds an ambient / looping deliverable is built from ONE loopable segment
#: repeated at assembly (a 3-hour rain track, an 8-hour fireplace) — never generated end to end.
AMBIENT_LOOP_MIN_S = 1800
#: From this many images (or shots) a set has to hold ONE style.
STYLE_SET_MIN = 3
#: A short without speech: at most this many seconds (longer is a film, not a short).
NO_SPEECH_SHORT_MAX_S = 180

S_COPYRIGHT_OFFICE_MECH = "https://www.copyright.gov/licensing/sec_115.html"
S_YT_COVERS = "https://support.google.com/youtube/answer/6364458"
S_YT_REPETITIVE = "https://support.google.com/youtube/answer/1311392"
S_GIMP_TILE = "https://docs.gimp.org/2.10/en/plug-in-make-seamless.html"
S_IMAGEMAGICK_FFT = "https://imagemagick.org/Usage/fourier/"
S_EDPB_VIDEO = "https://www.edpb.europa.eu/our-work-tools/our-documents/guidelines/guidelines-32019-processing-personal-data-through-video_en"
S_ICO_ANON = "https://ico.org.uk/for-organisations/uk-gdpr-guidance-and-resources/data-sharing/anonymisation/"


def output_flag(spec: "bs.Spec", flag: str) -> bool | None:
    """`outputs[].<flag>` (`spec.loop` / `spec.tileable`): True / False as named, None — not named."""
    v = getattr(spec, flag, None)
    if isinstance(v, bool):
        return v
    for о in getattr(spec, "output_items", None) or ():
        if isinstance(о, Mapping) and isinstance(о.get(flag), bool):
            return bool(о[flag])
    return None


def people_flag(spec: "bs.Spec", key: str) -> list[object]:
    """`people[].<key>` as named (people without the key are skipped)."""
    return [п.get(key) for п in spec.people if isinstance(п, Mapping) and п.get(key) is not None]


def consistency(spec: "bs.Spec") -> set[str]:
    """`spec.consistency` — what must stay the same across the set."""
    return {str(к).lower() for к in (getattr(spec, "consistency", None) or ())}


W_COVER_SONG = re.compile(
    r"\bcover(?:s|ed|ing)? (?:version|song|track)s?\b|\bcover of (?:the |a |an |this |that )?(?:song|track|hit|classic|[\"'“‘«])"
    r"|\b(?:a|our|my|his|her|their|acoustic|piano|rock|jazz|lo-?fi) covers?\b(?! (?:image|art|artwork|photo|picture|frame|letter|page|shot|story))"
    r"|\bcovers? (?:the |a |an )?(?:famous |popular |classic |hit )?(?:song|track|hit|classic|tune)\b|cover band|tribute (?:song|band|version)"
    r"|(?:famous|popular|well-known|known|hit|chart|classic|copyrighted) (?:song|track|tune|single)s?\b"
    r"|\b(?:sing|sings|singing|sang|perform|performs|performing|lip-?sync\w*|to the song|song)\s+[\"“‘«][^\"”’»]{2,60}[\"”’»]"
    r"|\bsing\w*\s+'[^']{3,60}'"
    r"|кавер\w*|перепе\w*|известн\w* (?:песн|трек|хит)\w*|популярн\w* (?:песн|трек|хит)\w*|чуж\w* (?:песн|трек)\w*"
    r"|(?:спо[её]т|по[её]т|исполн\w*|песн\w*|под песню|трек\w*)\s+«[^»]{2,60}»",
    re.I,
)
#: «an original song», «our own jingle» — no third-party composition (unless a cover is named too).
W_OWN_SONG = re.compile(
    r"\boriginal (?:song|track|tune|music|jingle|composition)|\b(?:our|my|his|her|their) own (?:song|track|tune|music|jingle)"
    r"|оригинальн\w* (?:песн|трек|мелоди|музык)\w*|сво\w* (?:песн|трек|мелоди|джингл)\w*|собственн\w* (?:песн|трек)\w*",
    re.I,
)
W_AMBIENT = re.compile(
    r"\bambien(?:t|ce)\b|sleep (?:sounds?|music|track|video|aid)|for sleep(?:ing)?\b|white noise|brown noise|pink noise"
    r"|rain (?:sounds?|ambien\w*)|fireplace|crackling fire|study (?:music|beats|session)|lo-?fi (?:beats|radio|stream|loop)"
    r"|relax(?:ing|ation) (?:music|sounds?|video)|meditation (?:music|sounds?|track|video)|\bfocus music|background (?:loop|ambience)"
    r"|aquarium (?:video|loop)|\byule ?log\b|screensaver|\b\d+(?:[.,]\d+)?\s*(?:-|\s)?(?:hours?|hrs?|h)\s+(?:of|long)\b"
    r"|эмбиент\w*|для сна|белый шум|розовый шум|коричневый шум|звук\w* (?:дождя|леса|океана|моря|камина|природы)|камин\w*"
    r"|медитаци\w*|релакс\w*|для учёбы|для учебы|для концентрации|фонов\w* (?:музык|звук|видео)\w*|\d+\s*час\w* (?:звук|музык|видео)",
    re.I,
)
W_TILEABLE = re.compile(
    r"\btil(?:e|ing|eable|able)\b|tileable|seamless (?:texture|pattern|tile|background pattern|wallpaper|repeat)"
    r"|repeat(?:ing)? pattern|(?:pbr|game|3d) (?:texture|material)s?|surface pattern|textile pattern|fabric print|wallpaper pattern"
    r"|тайл\w*|бесшовн\w* (?:текстур|паттерн|узор|фон|рисун|обо)\w*|повторяющ\w* (?:узор|паттерн|рисун)\w*|текстур\w* для (?:игр|3d)",
    re.I,
)
W_HALFTONE = re.compile(
    r"half-?tone|moir[eé]|newspaper (?:photo|clipping|cutting|scan|image|picture|page|print)|(?:from|in|of) (?:(?:an?|the|old|local|our|my|his|her) ){0,2}(?:newspaper|magazine|book|brochure|catalog(?:ue)?|yearbook|postcard)s?\b"
    r"|magazine (?:photo|scan|page|clipping|cutout|image|picture|print)|printed (?:photo|picture|image|page|brochure)|offset print"
    r"|растр\w*|муар\w*|газетн\w*|из газет\w*|из журнал\w*|журнальн\w* (?:фото|снимк|страниц|вырезк|скан)\w*|из книг\w*|открытк\w*|полиграф\w*|печатн\w* (?:фото|снимк|оттиск)\w*",
    re.I,
)
W_TIMELAPSE = re.compile(
    r"time-?lapse|hyper-?lapse|interval (?:shooting|photos?|camera)|таймлапс\w*|тайм-лапс\w*|гиперлапс\w*|интервальн\w* съ[её]мк\w*",
    re.I,
)
W_STYLE_SET = re.compile(
    r"(?:same|consistent|consistency|unified|uniform|matching|coherent|cohesive|one|single|shared) (?:art |visual |illustration |graphic |brand |colou?r )?(?:style|look)\b"
    r"|style (?:consistency|guide|sheet|reference|lock)|in the same (?:style|look)|look like (?:a|one) (?:set|series|family)|series of illustrations"
    r"|единый стиль|едином стиле|в одном стиле|одинаков\w* стил\w*|единообразн\w*|одн\w* стилистик\w*|един\w* стилистик\w*|стилистически един\w*"
    r"|в общем стиле|один и тот же стиль",
    re.I,
)
W_NO_SPEECH = re.compile(
    r"\bno (?:voice-?over|voiceover|vo|narration|narrator|speech|talking|dialogue|spoken words|words spoken|one speaks|one talks)\b"
    r"|without (?:a |any )?(?:voice-?over|voiceover|narration|narrator|speech|talking|dialogue|spoken words|words)\b|wordless"
    r"|(?:music|text|captions?) only\b|only (?:music|text|captions)\b|nobody (?:speaks|talks)|no-?speech|non-?verbal"
    r"|без (?:слов|голоса|озвучк\w*|диктор\w*|закадров\w*|речи|разговор\w*|текста диктора)|только музык\w*|никто не говорит|без закадра",
    re.I,
)
W_ANONYMISE = re.compile(
    r"anonymi[sz]\w*|de-?identif\w*|blur(?:ring)? (?:out )?(?:the |all )?(?:faces|passers|people|bystanders|pedestrians|crowd|strangers)"
    r"|(?:hide|mask|obscure|pixelate) (?:the |all )?(?:faces|passers|bystanders|pedestrians)|pixelat\w*|face[- ]blur\w*|\bgdpr\b|\bdsgvo\b|\brgpd\b"
    r"|passers-?by|bystanders|(?:replace|swap) (?:the )?faces of (?:the )?(?:passers|people|bystanders|pedestrians|strangers|crowd)"
    r"|анонимиз\w*|обезличи\w*|размы\w* лиц\w*|размытие лиц|скры\w* лиц\w*|замаз\w* лиц\w*|пикселиз\w*|прохож\w*|случайн\w* люд\w*",
    re.I,
)
W_INSERT = re.compile(
    r"\b(?:put|place|insert|add|drop|integrat\w*|composit\w*)\w*\s+(?:[\w'’-]+\s+){0,4}?(?:in(?:to)?|on(?:to)?)\s+"
    r"(?:the |this |our |my |a |an )?(?:[\w'’-]+\s+){0,3}?(?:shot|scene|clip|video|footage|table|shelf|counter|hand|frame|desk|wall)s?\b"
    r"|product placement|virtual (?:product )?placement"
    r"|встав\w*|размест\w* (?:\w+ ){0,3}(?:в|на) |добав\w* (?:\w+ ){0,3}(?:в кадр|в ролик|в видео|в сцену|на стол|на полку)"
    r"|постав\w* (?:\w+ ){0,3}на (?:стол|полку)|продакт[- ]?плейсмент\w*",
    re.I,
)
#: Jobs that start from an existing picture (a halftone scan matters there).
SCAN_JOBS: frozenset[str] = frozenset({"restore", "colorize", "image_edit"}) | UPSCALE
#: Jobs whose deliverable is speech or a talking face (a no-speech short has none of them).
SPEECH_JOBS: frozenset[str] = frozenset({"tts", "dub", "voice_clone", "lipsync", "avatar", "sing"})


def _cover_song(c: Ctx) -> bool:
    """A known (third-party) song is covered or used: a not-owned audio input with singing, or the words."""
    if not (c.steps or c.jobs):
        return False
    if c.says(W_COVER_SONG):
        return True
    чужой_звук = any(з.get("kind") == "audio" and з.get("owned") is False for з in c.spec.input_items)
    return чужой_звук and (bool(c.jobs & {"sing", "lipsync", "music"}) or c.says(W_SINGING)) and not c.says(W_OWN_SONG)


def _ambient_long(c: Ctx) -> dict[str, str] | None:
    """A long ambient / looping deliverable (audio or video), at least `AMBIENT_LOOP_MIN_S`."""
    s = c.seconds
    if s < AMBIENT_LOOP_MIN_S or not (c.steps or c.jobs):
        return None
    if not (c.video or c.jobs & {"music", "sfx"} or c.outputs & {"music", "sfx", "audio"}):
        return None
    петля = output_flag(c.spec, "loop")
    if петля is False:
        return None
    if петля or c.says(W_LOOP) or c.says(W_AMBIENT):
        return {"hours": f"{s / 3600:.3g}"}
    return None


def _tileable(c: Ctx) -> bool:
    тайл = output_flag(c.spec, "tileable")
    if тайл is not None:
        return тайл and bool(c.steps or c.jobs)
    return c.visual and bool(c.steps or c.jobs) and c.says(W_TILEABLE)


def _halftone(c: Ctx) -> bool:
    return bool(c.jobs & SCAN_JOBS) and c.says(W_HALFTONE)


def _timelapse_interp(c: Ctx) -> bool:
    return "interpolate" in c.jobs and c.says(W_TIMELAPSE)


def _style_set(c: Ctx) -> dict[str, str] | None:
    """Several images or shots that must share one style (`spec.consistency` has 'style', or the words)."""
    штук = max(int(c.spec.shots or 0), *(int(з.get("count") or 0) for з in c.spec.input_items), 0)
    if штук < STYLE_SET_MIN or not c.jobs & (STILL_GEN | VIDEO_GEN | {"i2v"}):
        return None
    оси = consistency(c.spec)
    if "style" in оси or (not оси and c.says(W_STYLE_SET)):
        return {"n": str(штук)}
    return None


def _no_speech_short(c: Ctx) -> bool:
    """A short video where nobody speaks: `people[].speaks` all false, or the words."""
    if not c.video or "speech" in c.outputs or c.jobs & SPEECH_JOBS:
        return False
    if c.seconds > NO_SPEECH_SHORT_MAX_S or c.jobs & ({"restore", "colorize", "interpolate"} | UPSCALE):
        return False
    говорят = people_flag(c.spec, "speaks")
    if говорят:
        return all(г is False for г in говорят)
    return c.says(W_NO_SPEECH)


def _anonymise(c: Ctx) -> bool:
    """Faces of bystanders hidden or swapped in the customer's footage (GDPR)."""
    return c.visual and bool(c.steps or c.jobs) and c.says(W_ANONYMISE) and bool(
        re.search(r"anonymi|de-?identif|blur|pixel|hide|mask|obscure|gdpr|dsgvo|rgpd|swap|replac|анонимиз|обезлич|размы|скры|замаз|пиксел|замен", c.text)
    )


def _product_insertion(c: Ctx) -> bool:
    """A product / object placed into the customer's existing shot (`spec.edit_target` = 'object', or the words)."""
    if "v2v_edit" not in c.jobs:
        return False
    цель = str(getattr(c.spec, "edit_target", None) or "").lower()
    if цель:
        return цель == "object" and (c.says(W_INSERT) or c.says(W_PRODUCT))
    return c.says(W_INSERT) and not c.says(W_NOT_AN_OBJECT)


#: Things "added into the video" that are assembly overlays or sound, not an object in the scene.
W_NOT_AN_OBJECT = re.compile(
    r"caption|subtitle|\btext\b|title|lower[- ]third|logo|watermark|music|sound|voice|audio|transition|filter|lut"
    r"|субтитр|титр|текст|логотип|водян\w* знак|музык|звук|голос|переход|фильтр",
    re.I,
)


RULES_R15: tuple[Rule, ...] = (
    _r(
        "cover_song_rights",
        [],
        "a cover or a known song in the video: you need the SYNC licence (the composition set to picture) from the "
        "song's publisher(s) — a mechanical licence covers only an audio-only cover release (in the US the "
        "compulsory section 115 licence), never a video — plus a MASTER-use licence from the label if the "
        "original recording is used; changed lyrics, a translation or a parody need the publisher's approval as a "
        "derivative; find every co-publisher (splits) before release; on YouTube a cover is matched by Content ID "
        "and the publisher may monetise, block or share revenue; TikTok / Instagram libraries clear only personal "
        "use, not ads; an AI voice imitating the original singer adds a likeness / voice claim",
        "кавер или известная песня в ролике: нужна СИНХРОНИЗАЦИОННАЯ лицензия (произведение под картинку) от "
        "издателя(ей) песни — механическая лицензия покрывает только аудиорелиз кавера (в США принудительная "
        "лицензия по разделу 115), а не видео, — плюс лицензия на ФОНОГРАММУ от лейбла, если используется "
        "оригинальная запись; изменённый текст, перевод или пародия требуют согласия издателя как переработка; "
        "найдите всех соиздателей (доли) до выпуска; на YouTube кавер распознаёт Content ID, и издатель может "
        "монетизировать, заблокировать или делить доход; библиотеки TikTok и Instagram покрывают только личные "
        "публикации, не рекламу; ИИ-голос, подражающий исполнителю оригинала, добавляет претензию на голос и образ",
        R,
        _cover_song,
        ("inputs", "conditions"),
        "spec.inputs[].rights = 'third-party-song'",
        (S_COPYRIGHT_OFFICE_MECH, S_YT_COVERS, S_CONTENT_ID),
    ),
    _r(
        "long_ambient_loop",
        [],
        "a long ambient piece (~{hours} h) is NOT generated end to end: generate one loopable segment (a few "
        "minutes of audio, or a 5-20 s clip) — or 2-3 variations to break audible repetition — make the tail "
        "meet the head (crossfade 2-5 s on a zero crossing / matched frames), check the loop point on headphones "
        "and at full speed, then repeat it at assembly (ffmpeg -stream_loop, acrossfade / xfade) — 0 usd; "
        "master to the platform loudness once, and note that YouTube may limit monetisation of repetitive content",
        "длинный фоновый материал (~{hours} ч) НЕ генерируется целиком: сгенерируйте один зацикливаемый отрезок "
        "(несколько минут звука или клип 5-20 с) — или 2-3 вариации, чтобы повтор не был слышен, — сведите "
        "хвост с началом (наплыв 2-5 с в нуле волны / по совпадающим кадрам), проверьте точку петли в наушниках "
        "и на полной скорости, затем повторите отрезок при сборке (ffmpeg -stream_loop, acrossfade / xfade) — "
        "0 usd; громкость под площадку выставляется один раз, а YouTube может ограничить монетизацию "
        "однообразного контента",
        E,
        _ambient_long,
        ("duration_s", "outputs"),
        "spec.outputs[].loop = true",
        (S_FFMPEG_FILTERS, S_YT_REPETITIVE),
    ),
    _r(
        "tileable_texture",
        [],
        "tileable texture: generate with seamless tiling on (circular padding / the 'tiling' option of SD-type "
        "pipelines, or a tile-capable texture model), then CHECK the seam with a 50 % offset (wrap-around) and a "
        "3x3 repeat — fix the cross with an inpaint over the offset seams; keep the light flat and even (no baked "
        "perspective, vanishing lines, directional shadows, vignette or a single dominant feature that repeats "
        "visibly), deliver a power-of-two square (1024 / 2048 / 4096) and derive normal / roughness maps from the "
        "albedo for PBR",
        "бесшовная текстура: генерируйте с включённым тайлингом (круговой паддинг / опция «tiling» в "
        "SD-конвейерах или модель, умеющая тайлы), затем ПРОВЕРЬТЕ шов сдвигом на 50 % (с переносом) и "
        "повтором 3x3 — крест на швах закрывается инпейнтом по сдвинутым швам; свет ровный и плоский (без "
        "перспективы, линий схода, направленных теней, виньетки и одной броской детали, которая заметно "
        "повторяется), сдача — квадрат со стороной степени двойки (1024 / 2048 / 4096), карты нормалей и "
        "шероховатости для PBR выводятся из альбедо",
        E,
        _tileable,
        ("outputs", "conditions"),
        "spec.outputs[].tileable = true",
        (S_GIMP_TILE,),
    ),
    _r(
        "descreen_halftone",
        [],
        "a print scan (newspaper, magazine, book, postcard) carries a halftone dot screen: DESCREEN it before any "
        "restoration or upscale — an upscaler or a face restorer sharpens the dots into moire and fake texture; "
        "scan at 2x the target resolution (600-1200 dpi), remove the screen (an FFT notch filter, a descreen filter "
        "in the scanner software, or a light blur + downscale), then restore, upscale and colour; check skin and "
        "flat skies at 100 % for leftover rosettes",
        "скан печати (газета, журнал, книга, открытка) несёт растровую сетку точек: УБЕРИТЕ РАСТР до любой "
        "реставрации и апскейла — апскейлер или восстановитель лиц заостряет точки в муар и ложную фактуру; "
        "сканируйте в 2 раза выше целевого разрешения (600-1200 dpi), снимите растр (режекторный фильтр по "
        "спектру FFT, фильтр «descreen» в программе сканера или лёгкое размытие + уменьшение), затем "
        "реставрация, апскейл и цвет; проверьте кожу и ровное небо в 100 % на остатки розеток",
        E,
        _halftone,
        ("task", "conditions"),
        "spec.inputs[].source = 'print-scan'",
        (S_IMAGEMAGICK_FFT,),
    ),
    _r(
        "timelapse_interpolation",
        [],
        "interpolating a timelapse: the motion between two frames is huge (clouds, cars, people jump), so a "
        "flow interpolator warps and ghosts them — DEFLICKER first (exposure jumps become pulsing), keep the "
        "factor low (2x, not 4-8x), use a large-motion / optical-flow-aware model (FILM, RIFE with scene-cut "
        "detection) or frame blending for crowds and traffic, or simply play the timelapse at its native rate; "
        "check moving people and vehicles frame by frame",
        "интерполяция таймлапса: движение между двумя кадрами огромно (облака, машины, люди прыгают), и "
        "интерполятор по оптическому потоку их коверкает и двоит — сначала УБЕРИТЕ МЕРЦАНИЕ (скачки экспозиции "
        "превращаются в пульсацию), держите коэффициент низким (2x, а не 4-8x), берите модель для большого "
        "движения с учётом оптического потока (FILM, RIFE с детекцией склеек) или смешивание кадров для толпы "
        "и транспорта — или просто играйте таймлапс в родной частоте; проверьте людей и машины по кадрам",
        E,
        _timelapse_interp,
        ("task", "conditions"),
        "spec.inputs[].capture = 'timelapse'",
        (S_FFMPEG_FILTERS,),
    ),
    _r(
        "style_consistency_set",
        [],
        "{n} images in one style: lock the style before the batch — ONE model and version for every item (a "
        "checkpoint update changes the look), a written style sheet (palette hex codes, line and lighting, "
        "medium, framing, negative prompt), the same style reference image(s) or a style LoRA at a fixed weight, "
        "fixed sampler / steps / CFG and logged seeds; make 2-3 pilots, approve them, then batch; review the set "
        "side by side as a contact sheet and regenerate outliers, not the whole set",
        "{n} изображений в одном стиле: зафиксируйте стиль до серии — ОДНА модель и версия на все кадры "
        "(обновление чекпойнта меняет вид), письменный стайлгайд (палитра в hex-кодах, линия и свет, техника, "
        "кадрирование, негативный промпт), одни и те же референсы стиля или LoRA стиля с постоянным весом, "
        "постоянные сэмплер / шаги / CFG и записанные сиды; сделайте 2-3 пробы, утвердите их и только потом "
        "серию; смотрите набор бок о бок контактным листом и перегенерируйте выбивающиеся кадры, а не всю серию",
        E,
        _style_set,
        ("shots", "inputs", "consistency"),
        "spec.consistency = ['style']",
    ),
    _r(
        "no_speech_short",
        [],
        "a short without speech: the message is carried by on-screen text and captions (large, high-contrast, "
        "inside the safe area, ~3 s per line, readable muted), music and sound design (whooshes, impacts, "
        "ambience under every cut) — so no TTS, voice-over or lip sync steps; the music needs a licence that "
        "covers the use (platform commercial library or a licensed / generated track with commercial rights), "
        "and the visual story must read without a word",
        "шортс без речи: смысл несут текст в кадре и подписи (крупно, контрастно, в безопасной зоне, ~3 с на "
        "строку, читается без звука), музыка и звуковой дизайн (вжухи, удары, атмосфера под каждой склейкой) — "
        "поэтому никаких шагов синтеза речи, закадра или липсинка; на музыку нужна лицензия на такое "
        "использование (коммерческая библиотека площадки или лицензированный / сгенерированный трек с "
        "коммерческими правами), а история должна читаться без единого слова",
        E,
        _no_speech_short,
        ("outputs", "people"),
        "spec.people[].speaks = false",
        (S_TIKTOK_CML,),
    ),
    _r(
        "product_insertion",
        [],
        "placing a product into existing footage: an object-insertion / video-edit model (not a character swap), "
        "with the product photo as the reference image; the insert must follow the shot — track the surface "
        "(planar or 3D camera track) and lock the product to it, match perspective, scale and lens blur, the "
        "light direction and colour, and add a contact shadow and reflections; check the label and logo at 100 % "
        "in every frame (edit models redraw lettering — composite the real packshot over it if it drifts), and "
        "label it as product placement / an ad where the platform or broadcaster requires it",
        "вставка товара в готовый ролик: модель вставки объекта / правки видео (не замена персонажа), фото товара "
        "— референсом; вставка обязана следовать кадру — трекинг поверхности (планарный или 3D-трекинг камеры) и "
        "товар, закреплённый на ней, совпадение перспективы, масштаба и размытия объектива, направления и цвета "
        "света, контактная тень и отражения; проверьте этикетку и логотип в 100 % в каждом кадре (модели правки "
        "перерисовывают надписи — если поплыли, наложите настоящий пэкшот поверх) и помечайте продакт-плейсмент "
        "/ рекламу там, где этого требует площадка или вещатель",
        E,
        _product_insertion,
        ("edit_target", "conditions"),
        "",
        (S_FFMPEG_FILTERS,),
    ),
    _r(
        "anonymisation_gdpr",
        [],
        "anonymising bystanders (GDPR): filming identifiable people in public is processing personal data — "
        "document the legal basis (legitimate interest, art. 6(1)(f), with a balancing test) and run a DPIA "
        "(art. 35) for systematic or large-scale footage; only IRREVERSIBLE anonymisation takes the result out of "
        "GDPR (recital 26): strong blur / pixelation or a synthetic replacement face, with licence plates, "
        "tattoos, name badges and distinctive voices handled too — a face swap that keeps the raw footage, or a "
        "reversible blur, is only PSEUDONYMISATION and the data stays personal; keep the originals encrypted with "
        "a deletion date; face detection misses small, profile and occluded faces, so track faces across frames "
        "and review every frame before release",
        "анонимизация прохожих (GDPR): съёмка узнаваемых людей на улице — обработка персональных данных; "
        "запишите правовое основание (законный интерес, ст. 6(1)(f), с проверкой баланса интересов) и проведите "
        "оценку воздействия DPIA (ст. 35) для систематической или массовой съёмки; из-под GDPR выводит только "
        "НЕОБРАТИМАЯ анонимизация (преамбула 26): сильное размытие / пикселизация или синтетическое лицо на "
        "замену, плюс номера машин, татуировки, бейджи и узнаваемые голоса — замена лица при сохранённом "
        "исходнике или обратимое размытие — это лишь ПСЕВДОНИМИЗАЦИЯ, и данные остаются персональными; "
        "исходники храните зашифрованными с датой удаления; детектор лиц пропускает мелкие, профильные и "
        "закрытые лица — ведите лица трекингом по кадрам и проверьте каждый кадр до публикации",
        R,
        _anonymise,
        ("conditions",),
        "spec.anonymise = 'blur' | 'swap'",
        (S_GDPR, S_EDPB_VIDEO, S_ICO_ANON),
    ),
)

RULES_LIST = RULES_LIST + RULES_R15

RULES: dict[str, Rule] = {р.id: р for р in RULES_LIST}


def fire(
    spec: "bs.Spec", steps: Sequence[str], text: str = "", priors: Sequence[str] = ()
) -> list[tuple[str, dict[str, str]]]:
    """Which checklist rules this plan carries, with the fields of their wording.

    Condition rules first, then the rules every plan of the job class carries;
    table order inside each group.
    """
    ctx = context(spec, steps, text, priors)
    условные: list[tuple[str, dict[str, str]]] = []
    общие: list[tuple[str, dict[str, str]]] = []
    for р in RULES_LIST:
        поля = р.fire(ctx)
        if поля is not None:
            (общие if р.trigger is _always else условные).append((р.id, поля))
    # ПРАВИЛА УСЛОВИЙ — ПЕРВЫМИ: потолок ответа режет длинный список с хвоста
    # (`server.cap_response`), и сказанное про ЭТОТ заказ (телефония, RTL,
    # петля, 8K) должно пережить сказанное про любой заказ этого класса.
    return условные + общие


def spec_fields_to_add() -> dict[str, list[str]]:
    """Spec field -> the rules that read its condition from the words today (the contract's to-do list)."""
    out: dict[str, list[str]] = {}
    for р in RULES_LIST:
        if р.spec_field:
            out.setdefault(р.spec_field, []).append(р.id)
    return out
