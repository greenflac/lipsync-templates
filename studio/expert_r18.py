"""Round 18: specialist knowledge the hidden set found missing (e-learning, medicine, Deaf access,
loudness, dialogue replacement, typography, localisation masters, product optics, data graphics,
accents) and two pricing residuals.

Every decision reads a structured spec field first and the brief's words (EN/RU) only when the
field is absent; a named field beats the words both ways (docs/MCP_AGENT.md, "decisions read from
the spec first"). FOUR spec VALUES are added, each because no existing field could carry it
(documented in the `plan_pipeline` description, `spec_needed.allowed` and `decision_fields`):
`delivery.format` scorm | xapi (an LMS package is a delivery format, not a platform — `internal`
says only who watches), `domain` medical | science (no domain held non-advertising medicine or
science; `health-advertising` is an advert), `accessibility` sign-language (a sign-language tag in
`languages` would be priced as a spoken language), `subject` chart | map (no subject said "the
picture carries data").

CAVEATS (`checklist.RULES_R18`):
1. SCORM / xAPI packaging of e-learning video (`elearning_package`).
2. MEDICAL / SCIENTIFIC explainers: expert review, no invented anatomy or data, cited sources,
   regulated drug claims (`medical_science`); `claims_policy` decides claims unchanged.
3. SIGN LANGUAGE: the regional sign language, native Deaf signers over avatars, a Deaf reviewer
   (`sign_language_access`; the round-7 gap stays the outcome and now carries this note;
   `brief_spec.sign_language` reads `accessibility` before the words).
4. LOUDNESS by `delivery.platform`, measured on the final mix (`loudness_target`).
5. ROOM TONE / ADR matching of replaced dialogue (`replaced_dialogue`) and NONVERBAL sounds for
   TTS / dubbing / game barks (`nonverbal_needed`).
6. CJK locale glyphs and vertical text (`cjk_locales`), RTL graphics (fonts, digits, mirroring).
7. TEXTLESS master and elements for localisation (`textless_needed`).
8. GARMENT print scale and drape (`garment`), GLASS / LIQUID optics (`glass_liquid`).
9. RENDER FROM DATA: charts, maps, figures from data, never generated (`data_graphics`).
10. ACCENT / LOCALE consistency of voices (`locale_variants`); the `mul` path also covers TTS /
    voice-over jobs (one mixed track: no translation review, no M&E localisation note).

PRICING (round 18):
a. a condensed cut of the customer's material ordered as `video-edit` with nothing named to
   change: an output far shorter than the material (`CONDENSE_SHARE`) is a cut — never a
   generative edit — and its narrator is priced by the cut's length (`condensed_cut`);
b. one programme brought twice — an audio file as long as a video (its own track, a separate
   recorder) — is transcribed ONCE (`programme_seconds`).

DECISION CONSTANTS (mutated both ways by `scripts/mutate_round18_knowledge.py`):
`ELEARNING_FORMATS`, `SCIENCE_DOMAINS`, `SIGN_LANGUAGE_NAMES` (and `brief_spec.ACCESSIBILITY_SIGN_LANGUAGE`),
`LOUDNESS_TARGETS`, `CONDENSE_SHARE`, `PLURICENTRIC`, `BARE_UNDECIDED`, `VERTICAL_CJK`, `DATA_SUBJECTS`,
`GLASS_SUBJECTS`.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from studio import spec_first as sf

# --- shared readers --------------------------------------------------------------------------


def _words(spec: Any, text: str = "") -> str:
    """The brief's words with the caller's conditions and input notes (lower case)."""
    части = [str(text or "")]
    части += [str(у) for у in getattr(spec, "conditions", None) or ()]
    части += [str(з.get("note") or "") for з in getattr(spec, "input_items", None) or () if isinstance(з, Mapping)]
    return " ".join(" ".join(части).lower().split())


def _inputs(spec: Any) -> set[str]:
    return set(getattr(spec, "inputs", None) or ())


def _tags(spec: Any) -> list[str]:
    return [str(т) for т in getattr(spec, "language_tags", None) or () if т]


def _primary(тег: str) -> str:
    return тег.split("-")[0].lower()


def _formats(spec: Any) -> list[str] | None:
    форматы = sf._delivery(spec).get("format")
    return [str(ф) for ф in форматы] if форматы else None


# --- 1. SCORM / xAPI ------------------------------------------------------------------------------

#: `delivery.format` values of an LMS package (round 18).
ELEARNING_FORMATS: tuple[str, ...] = ("scorm", "xapi")
#: An LMS package named in words (EN/RU) — read only when `delivery.format` is not named.
W_ELEARNING = re.compile(
    r"\bscorm\b|\bxapi\b|experience api|tin ?can api|\bcmi5\b|\blms\b|learning management system|moodle"
    r"|articulate|storyline|e-?learning (?:module|course|package)s?"
    r"|\bсдо\b|систем\w* дистанционн\w* обучени\w*|электронн\w* курс\w*",
    re.I,
)


def elearning_package(spec: Any, text: str = "") -> bool:
    """The deliverable goes into an LMS package: `delivery.format` first, then the words."""
    форматы = _formats(spec)
    if форматы is not None:
        return bool(set(форматы) & set(ELEARNING_FORMATS))
    return bool(W_ELEARNING.search(_words(spec, text)))


# --- 2. medical and scientific explainers ------------------------------------------------------

#: `domain` values of non-advertising medicine and science (round 18).
SCIENCE_DOMAINS: tuple[str, ...] = ("medical", "science")
#: Medicine / science named in words (EN/RU).
W_MEDICAL_SCIENCE = re.compile(
    r"anatom\w*|medical (?:explainer|animation|illustration|video|education|training|device)s?"
    r"|patient (?:education|information)|mechanism of action|\bmoa\b|pharma\w*|clinical|surg(?:ery|ical)"
    r"|physiolog\w*|patholog\w*|scientific (?:explainer|animation|video|illustration|visuali[sz]ation)s?"
    r"|molecul\w*|cell biology"
    r"|анатом\w*|медицинск\w*|для пациентов|механизм\w* действия|фармацевт\w*|клиническ\w*|хирург\w*"
    r"|физиолог\w*|научн\w* (?:ролик|анимац\w*|видео|объяснени\w*|иллюстрац\w*)|молекул\w*",
    re.I,
)


def medical_science(spec: Any, text: str = "") -> bool:
    """A medical or scientific explainer: `domain` first, then the words."""
    поле = sf.domain(spec, *SCIENCE_DOMAINS)
    if поле is not None:
        return поле
    return bool(W_MEDICAL_SCIENCE.search(_words(spec, text)))


# --- 3. sign language --------------------------------------------------------------------------

#: ISO 639-3 sign-language codes -> the name a Deaf viewer knows (`brief_spec.SIGN_LANGUAGE_CODES` are the
#: codes the planner reads; these are the names said back).
SIGN_LANGUAGE_NAMES: dict[str, str] = {
    "ase": "ASL", "bfi": "BSL", "rsl": "RSL", "fsl": "LSF", "lsf": "LSF", "gsg": "DGS", "jsl": "JSL",
    "csl": "CSL", "ins": "ISL (Indian)", "asf": "Auslan", "ssp": "LSE", "ise": "LIS", "bzs": "Libras",
    "kvk": "KSL",
}  # fmt: skip


def sign_languages(spec: Any) -> list[str]:
    """The regional sign languages named as language tags ('BSL (bfi)'); [] — none named."""
    out = []
    for тег in _tags(spec):
        код = _primary(тег)
        if код in SIGN_LANGUAGE_NAMES:
            out.append(f"{SIGN_LANGUAGE_NAMES[код]} ({код})")
    return list(dict.fromkeys(out))



# --- 4. loudness ----------------------------------------------------------------------------------

#: `delivery.platform` -> the loudness target (en, ru). DECISION TABLE: a platform with no entry has no
#: integrated-loudness target to state (print, vfx / editorial hand-offs, telephony levels).
LOUDNESS_TARGETS: dict[str, tuple[str, str]] = {
    "broadcast": ("EBU R128: -23 LUFS integrated +-0.5 LU, true peak at most -1 dBTP (US ATSC A/85: -24 LKFS)",
                  "EBU R128: -23 LUFS интегрально +-0,5 LU, истинный пик не выше -1 dBTP (США, ATSC A/85: -24 LKFS)"),
    "streaming-premium": ("Netflix-class: -27 LKFS dialogue-gated +-2 LU, true peak at most -2 dBTP",
                          "стриминг класса Netflix: -27 LKFS по диалогу +-2 LU, истинный пик не выше -2 dBTP"),
    "podcast": ("podcast: -16 LUFS integrated (Apple Podcasts), true peak at most -1 dBTP",
                "подкаст: -16 LUFS интегрально (Apple Podcasts), истинный пик не выше -1 dBTP"),
    "audiobook": ("ACX: -23 to -18 dB RMS, peaks at most -3 dB",
                  "ACX: от -23 до -18 дБ RMS, пики не выше -3 дБ"),
    "youtube": ("YouTube: about -14 LUFS integrated (louder uploads are turned down; YouTube publishes no "
                "figure, practitioners measure about -14), true peak at most -1 dBTP",
                "YouTube: около -14 LUFS интегрально (громкие загрузки приглушаются; YouTube цифру не публикует, "
                "практики измеряют около -14), истинный пик не выше -1 dBTP"),
    "youtube-shorts": ("YouTube Shorts: about -14 LUFS integrated, true peak at most -1 dBTP",
                       "YouTube Shorts: около -14 LUFS интегрально, истинный пик не выше -1 dBTP"),
    "tiktok": ("TikTok: about -14 LUFS integrated, true peak at most -1 dBTP (the platform publishes no target)",
               "TikTok: около -14 LUFS интегрально, истинный пик не выше -1 dBTP (площадка цель не публикует)"),
    "instagram": ("Instagram: about -14 LUFS integrated, true peak at most -1 dBTP (the platform publishes no target)",
                  "Instagram: около -14 LUFS интегрально, истинный пик не выше -1 dBTP (площадка цель не публикует)"),
    "reels": ("Reels: about -14 LUFS integrated, true peak at most -1 dBTP (the platform publishes no target)",
              "Reels: около -14 LUFS интегрально, истинный пик не выше -1 dBTP (площадка цель не публикует)"),
    "music-distribution": ("Spotify normalises to -14 LUFS integrated; true peak at most -1 dBTP (-2 dBTP for a "
                           "master louder than -14 LUFS)",
                           "Spotify нормализует к -14 LUFS интегрально; истинный пик не выше -1 dBTP (-2 dBTP для "
                           "мастера громче -14 LUFS)"),
    "web": ("web / e-learning video: -16 LUFS integrated (AES TD1004: -16 to -20 LUFS for streamed and file "
            "playback; from memory — source not reachable; verify), true peak at most -1 dBTP",
            "веб-видео и электронные курсы: -16 LUFS интегрально (AES TD1004: от -16 до -20 LUFS для потокового "
            "и файлового воспроизведения; по памяти — источник недоступен; проверить), истинный пик не выше -1 dBTP"),
    "internal": ("internal / LMS video: -16 LUFS integrated (AES TD1004: -16 to -20 LUFS for file playback; from memory — source not reachable; verify), "
                 "true peak at most -1 dBTP",
                 "внутреннее видео и СДО: -16 LUFS интегрально (AES TD1004: от -16 до -20 LUFS для файлового "
                 "воспроизведения; по памяти — источник недоступен; проверить), истинный пик не выше -1 dBTP"),
    "app-store": ("app preview: -16 LUFS integrated (AES TD1004 file playback; from memory — source not reachable; verify), true peak at most -1 dBTP",
                  "превью приложения: -16 LUFS интегрально (AES TD1004, файловое воспроизведение; по памяти — источник недоступен; проверить), истинный пик "
                  "не выше -1 dBTP"),
    "marketplace": ("marketplace video: -16 LUFS integrated (AES TD1004 file playback; from memory — source not reachable; verify), true peak at most -1 dBTP",
                    "видео маркетплейса: -16 LUFS интегрально (AES TD1004, файловое воспроизведение; по памяти — источник недоступен; проверить), истинный "
                    "пик не выше -1 dBTP"),
    "game-engine": ("game audio (Sony ASWG-R001): -24 LUFS +-2 LU for console / PC, -18 LUFS for mobile, measured "
                    "over a long stretch of play (from memory — source not reachable; verify)",
                    "звук игры (Sony ASWG-R001): -24 LUFS +-2 LU для консоли и ПК, -18 LUFS для мобильных, мерить "
                    "на длинном отрезке игры (по памяти — источник недоступен; проверить)"),
}  # fmt: skip
#: No platform named: the usual targets, the caller picks (en, ru).
LOUDNESS_ASK = (
    "the platform decides: -23 LUFS broadcast (EBU R128), about -14 LUFS streaming / social, -16 LUFS podcast, "
    "true peak at most -1 dBTP",
    "цель задаёт площадка: -23 LUFS эфир (EBU R128), около -14 LUFS стриминг и соцсети, -16 LUFS подкаст, "
    "истинный пик не выше -1 dBTP",
)
#: Loudness named in words (EN/RU) — read only when `delivery.platform` is not named.
W_LOUDNESS = re.compile(r"\blufs\b|\blkfs\b|\bdbtp\b|loudness|ebu ?r ?128|громкост\w*", re.I)


def loudness_target(spec: Any, text: str = "") -> tuple[str, str] | None:
    """The loudness target of the order: the first named platform with a target, else (with loudness words
    and no platform) the usual targets; None — nothing to state."""
    площадки = sf._delivery(spec).get("platform") or ()
    if площадки:
        for п in площадки:
            if п in LOUDNESS_TARGETS:
                return LOUDNESS_TARGETS[п]
        return None
    if W_LOUDNESS.search(_words(spec, text)):
        return LOUDNESS_ASK
    return None


# --- 5. replaced dialogue, nonverbal sounds ---------------------------------------------------------

#: Dialogue replaced inside the customer's take named in words (EN/RU).
W_REPLACED_DIALOGUE = re.compile(
    r"\badr\b|re-?record\w* (?:the |a |some )?(?:line|dialogue|voice)s?|dialogue replacement|room tone"
    r"|(?:replace|fix|change|swap) (?:a |the |one |some |two )?(?:\w+ )?(?:line|word|sentence|phrase)s?\b"
    r"|переозвуч\w*|рум-?тон\w*|(?:замен|исправ|поменя)\w* (?:\w+ )?(?:фраз|слов|реплик|предложени)\w*",
    re.I,
)
#: Nonverbal sounds named in words (EN/RU).
W_NONVERBAL = re.compile(
    r"\blaugh\w*|\bbreath\w*|\bsigh\w*|\bscream\w*|\bgrunt\w*|\befforts?\b|\bbarks?\b|\bgasp\w*|\bcry(?:ing)?\b"
    r"|\bsob\w*|\bwhisper\w*|vocali[sz]ations?|non-?verbal"
    r"|смех\w*|смеё\w*|вздох\w*|дыхани\w*|крик\w*|кряхт\w*|стон\w*|плач\w*|шёпот\w*|шепч\w*|междомети\w*|возглас\w*",
    re.I,
)


# --- 6. typography ------------------------------------------------------------------------------

#: Locales that set text VERTICALLY in titles, signage and some subtitles (primary or full tags).
VERTICAL_CJK: frozenset[str] = frozenset({"ja", "zh-TW", "zh-HK", "zh-Hant", "zh-MO", "yue"})
#: The Chinese tags that name the script / region (a bare `zh` does not).
ZH_NAMED: frozenset[str] = frozenset({"zh-CN", "zh-SG", "zh-Hans", "zh-TW", "zh-HK", "zh-Hant", "zh-MO"})


def cjk_locales(tags: list[str]) -> tuple[list[str], bool, bool]:
    """(the CJK tags named, a vertical-text locale among them, a bare `zh` with no script / region)."""
    cjk = [т for т in tags if _primary(т) in ("zh", "cmn", "yue", "ja", "ko")]
    вертикально = any(т in VERTICAL_CJK or _primary(т) in VERTICAL_CJK for т in cjk)
    голый_zh = any(_primary(т) in ("zh", "cmn") and т not in ZH_NAMED and not any(т.startswith(z) for z in ZH_NAMED) for т in cjk)
    return cjk, вертикально, голый_zh


# --- 7. textless master -----------------------------------------------------------------------------

#: Textless / clean-feed deliverables named in words (EN/RU).
W_TEXTLESS = re.compile(
    r"textless|clean (?:feed|version|master)|without (?:titles|graphics|text)|no (?:burned-in |on-screen )?text version"
    r"|international version|\bm&e\b|versions? for (?:\d+|several|many|other) (?:markets|countries|languages)"
    r"|без титров|без надписей|чист\w* (?:версия|мастер)|текстлесс|международн\w* верси\w*",
    re.I,
)
#: Versions from which a localisation master is due (languages or markets).
TEXTLESS_MIN_VERSIONS = 2


def _spoken_tags(spec: Any) -> list[str]:
    """Language tags that are spoken / written versions (not `mul`, not a sign language)."""
    return [т for т in _tags(spec) if _primary(т) != "mul" and _primary(т) not in SIGN_LANGUAGE_NAMES and _primary(т) != "sgn"]


def textless_needed(spec: Any, text: str = "", dub: bool = False, mixed: bool = False) -> bool:
    """A localisation master is due: a dub, several languages or markets — the fields first, then the words.

    :param mixed: the languages are ONE code-switched track (`expert_r17.code_switching`), not versions.
    """
    if dub:
        return True
    языки = 1 if mixed else len(dict.fromkeys(_spoken_tags(spec)))
    рынки = len(sf._delivery(spec).get("markets") or ())
    if max(языки, рынки) >= TEXTLESS_MIN_VERSIONS:
        return True
    названо = getattr(spec, "source", {}) or {}
    if названо.get("languages") == "spec" or рынки:
        return False
    return bool(W_TEXTLESS.search(_words(spec, text)))


# --- 8. garments, glass and liquid -----------------------------------------------------------------

W_GARMENT = re.compile(
    r"try-?on|garment|dress(?:es)?\b|fabric|apparel|clothing|outfit|t-?shirt|jacket|\bprint(?:ed)? pattern"
    r"|примерк\w*|одежд\w*|ткан[ьи]\w*|плать\w*|футболк\w*|куртк\w*|принт\w*",
    re.I,
)
#: `subject` values of a see-through product (round 18 reads the existing value).
GLASS_SUBJECTS: tuple[str, ...] = ("transparent",)
W_GLASS_LIQUID = re.compile(
    r"\bglass\w*|liquid|bottle|perfume|fragrance|\bpour\w*|splash\w*|beverage|\bdrinks?\b|ice cubes?|\bjuice|cocktail"
    r"|стекл\w*|стакан\w*|жидкост\w*|флакон\w*|бутыл\w*|парфюм\w*|духи\b|напит\w*|налив\w*|брызг\w*|коктейл\w*|сок\b",
    re.I,
)


def garment(spec: Any, text: str = "", try_on: bool = False) -> bool:
    """A garment is shown / tried on: the try-on step, then `subject`, then the words."""
    if try_on:
        return True
    поле = sf.subject(spec, "garment")
    if поле is not None:
        return поле
    return bool(W_GARMENT.search(_words(spec, text)))


def glass_liquid(spec: Any, text: str = "") -> bool:
    """A see-through product (glass, liquid): `subject` first, then the words."""
    поле = sf.subject(spec, *GLASS_SUBJECTS)
    if поле is not None:
        return поле
    return bool(W_GLASS_LIQUID.search(_words(spec, text)))


# --- 9. render from data -------------------------------------------------------------------------

#: `subject` values of a picture that carries data (round 18).
DATA_SUBJECTS: tuple[str, ...] = ("chart", "map")
W_DATA_GRAPHICS = re.compile(
    r"\bcharts?\b|\bgraphs?\b|infographic\w*|data[- ]?vi[sz]\w*|dashboard|statistic\w*|bar chart|pie chart|\bkpis?\b"
    r"|(?:route|world|country|city|animated|interactive|election|weather) maps?\b|\bmaps? (?:of|animation)\b"
    r"|диаграмм\w*|график\w*|инфографик\w*|статистик\w*|дашборд\w*"
    r"|карт[аеуыой]{1,2} (?:мира|маршрут\w*|страны|города|выборов|погоды)|анимированн\w* карт\w*",
    re.I,
)


def data_graphics(spec: Any, text: str = "") -> bool:
    """The picture carries data (a chart, a map, figures): `subject` first, then the words."""
    поле = sf.subject(spec, *DATA_SUBJECTS)
    if поле is not None:
        return поле
    return bool(W_DATA_GRAPHICS.search(_words(spec, text)))


# --- 10. accents and locale variants ------------------------------------------------------------------

#: Languages spoken with distinct national standards (a voice and a script are per variant): a tag that names
#: the region of one of them fires the caveat (the variant is a decision to keep).
PLURICENTRIC: frozenset[str] = frozenset({"es", "pt", "en", "fr", "ar", "zh", "de"})
#: Of those, the languages whose BARE tag already leaves the voice undecided (es-MX / es-ES, pt-BR / pt-PT,
#: a spoken Arabic dialect, Mandarin / Cantonese) — a bare `en`, `fr` or `de` stays silent.
BARE_UNDECIDED: frozenset[str] = frozenset({"es", "pt", "ar", "zh"})
#: Accent / dialect named in words (EN/RU).
W_ACCENT = re.compile(
    r"\baccents?\b|dialect\w*|\blatam\b|latin american spanish|castilian|brazilian portuguese|european portuguese"
    r"|canadian french|акцент\w*|диалект\w*|латиноамерикан\w*|бразильск\w* португал\w*|европейск\w* португал\w*",
    re.I,
)


def locale_variants(spec: Any, text: str = "") -> str | None:
    """The locales of a voiced order whose variant is a decision ('es (es-ES / es-MX / es-US?)', 'es-MX'); None — none.

    The language tags first (a pluricentric language named with or without its region); with no tag of
    such a language, the accent / dialect words.
    """
    теги = [
        т for т in dict.fromkeys(_spoken_tags(spec))
        if ("-" in т and _primary(т) in PLURICENTRIC) or ("-" not in т and _primary(т) in BARE_UNDECIDED)
    ]
    if теги:
        return ", ".join(т if "-" in т else f"{т} ({VARIANT_HINTS[_primary(т)]}?)" for т in теги)
    названо = (getattr(spec, "source", {}) or {}).get("languages") == "spec"
    if not названо and W_ACCENT.search(_words(spec, text)):
        return "es-ES / es-MX, pt-BR / pt-PT, en-US / en-GB, fr-FR / fr-CA …"
    return None


#: The variants to choose from for a bare tag (language-neutral: tags only).
VARIANT_HINTS: dict[str, str] = {
    "es": "es-ES / es-MX / es-US", "pt": "pt-BR / pt-PT", "ar": "ar-SA / ar-EG / ar-MA", "zh": "zh-CN / zh-TW / zh-HK",
}


# --- 11. pricing residuals ------------------------------------------------------------------------------

#: An output this much shorter than the material (or less) is a condensed cut, not an edit of every frame.
CONDENSE_SHARE = 0.5


def programme_seconds(spec: Any) -> float:
    """Seconds of the customer's material, counting ONE programme brought twice once: an audio item as long as
    (and as many as) a video item is that video's track or a second recorder of it."""
    видео = [
        (float(з.get("duration_s") or 0.0), int(з.get("count") or 1))
        for з in getattr(spec, "input_items", None) or ()
        if isinstance(з, Mapping) and з.get("kind") == "video"
    ]
    всего = 0.0
    for з in getattr(spec, "input_items", None) or ():
        if not isinstance(з, Mapping) or з.get("kind") not in ("video", "audio"):
            continue
        длина, штук = float(з.get("duration_s") or 0.0), int(з.get("count") or 1)
        if з.get("kind") == "audio" and длина and (длина, штук) in видео:
            continue
        всего += длина * штук
    return всего


def condensed_cut(spec: Any) -> bool:
    """A `video-edit` of the customer's video with nothing named to change whose ordered length is at most
    `CONDENSE_SHARE` of the material: a cut (a recap, a highlight reel, "the season in a minute")."""
    if getattr(spec, "task", None) not in ("video-edit", "edit") or "video" not in _inputs(spec):
        return False
    if getattr(spec, "edit", None) or getattr(spec, "edit_target", None) is not None:
        return False
    материал = programme_seconds(spec)
    длина = float(getattr(spec, "duration_s", None) or 0.0)
    return bool(материал and длина) and длина <= материал * CONDENSE_SHARE
