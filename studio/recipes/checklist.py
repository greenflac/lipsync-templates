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
from collections.abc import Callable, Mapping, Sequence
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
    r"chrome|\bglass\b|glassware|transparent|translucent|glossy|reflective|reflection|mirror|metallic|polished"
    r"|jewel|\bring\b|diamond|\bwatch(?:es)?\b|perfume|\bbottle|crystal|stainless"
    r"|хром|стекл|стеклян|прозрачн|глянц|отраж|зеркал|металлич|полирован|ювелир|кольц|бриллиант|часы|часов\b"
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


def _logo_motion(c: Ctx) -> bool:
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

RULES: dict[str, Rule] = {р.id: р for р in RULES_LIST}


def fire(
    spec: "bs.Spec", steps: Sequence[str], text: str = "", priors: Sequence[str] = ()
) -> list[tuple[str, dict[str, str]]]:
    """Which checklist rules this plan carries, with the fields of their wording (in table order)."""
    ctx = context(spec, steps, text, priors)
    out: list[tuple[str, dict[str, str]]] = []
    for р in RULES_LIST:
        поля = р.fire(ctx)
        if поля is not None:
            out.append((р.id, поля))
    return out


def spec_fields_to_add() -> dict[str, list[str]]:
    """Spec field -> the rules that read its condition from the words today (the contract's to-do list)."""
    out: dict[str, list[str]] = {}
    for р in RULES_LIST:
        if р.spec_field:
            out.setdefault(р.spec_field, []).append(р.id)
    return out
