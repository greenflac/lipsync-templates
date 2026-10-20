"""Round 16: anonymisation routes read from `spec.anonymise` (any brief language).

WHY. Round 15 planned anonymising bystanders from EN/RU words only
(`expert_r15.anonymise_method`): the same order in German got no model, no
price and no GDPR note, and a witness whose VOICE had to be unrecognisable was
planned as a dub — an end-to-end dubbing endpoint is built to KEEP the
speaker's timbre, the opposite of the order.

THE ROUTES (spec first; the words only when `spec.anonymise` is absent):

* faces, method `swap` (the default): one generated SYNTHETIC face that
  resembles nobody, then a video face swap onto every face (priced per second);
  the irreversible blur is named as the alternative at assembly;
* faces, method `blur` / `pixelate`: faces detected and blurred / pixelated
  over tracked boxes at assembly (0 usd, no generative model);
* voice (`voice: true` or method `voice-replace`): the speech is TRANSCRIBED
  and re-spoken by a DIFFERENT stock voice of the TTS library — never a clone
  of the speaker, never a dubbing endpoint; a same-language `dub-translate`
  order with `anonymise.voice` is routed here, not to dubbing;
* both: both.

Every route carries the GDPR / anonymisation caveat (`checklist.anonymisation_gdpr`
for pictures, `checklist.voice_anonymisation` for voices): irreversibility,
missed faces / voices, DPIA.

A FACE SWAP WITHOUT THE NEW FACE LISTED (documentary, consented): `task:
face-replace` on the customer's video with no image in `inputs` had NO candidate
and no price — every video face-swap endpoint takes the new face as an image,
and the candidate filter did not count the reference the plan already names as
an assumption ("the new face comes from YOUR reference image — attach it"). The
step is now chosen and priced with that reference counted as brought
(`assumed_inputs`).

DECISION CONSTANTS (mutated both ways by `scripts/mutate_round16_spec.py`):
`VOICE_DROPS`, `VOICE_STEPS`, `REFERENCE_FACE_STEPS` (the default face method is
`brief_spec.FACE_ANON_METHODS[0]`, swap).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from studio import spec_first as sf

#: Steps a voice anonymisation removes: dubbing keeps the speaker's timbre, a clone copies it, lip sync
#: fits the real face to the new voice.
VOICE_DROPS: frozenset[str] = frozenset({"дубляж", "клонирование_голоса", "липсинк"})
#: The voice route: transcript, then a different stock voice.
VOICE_STEPS: tuple[str, ...] = ("расшифровка", "озвучка")
#: TTS candidates ranked LAST on the voice route: endpoints whose job is cloning a voice (a build
#: published WITHOUT the cloning head reads stock voices and stays in front).
CLONE_ONLY_MODELS = r"(?<!without-)(?<!no-)voice-clon|instant-clon|clone-voice"
#: Steps of the face-swap route (synthetic face, then the video face swap).
FACE_SWAP_STEPS: tuple[str, ...] = ("генерация_изображения", "замена_персонажа")


def face_method(spec: Any, text: str = "") -> str | None:
    """'swap' | 'blur' | 'pixelate' when faces are anonymised; None — not.

    `spec.anonymise` named decides (faces false = no face route, whatever the words say); without it
    the round-15 words (`expert_r15.anonymise_method`).
    """
    поле = sf.anonymise_faces(spec)
    if поле is False:
        return None
    if isinstance(поле, str):
        return поле
    from studio import expert_r15 as x15

    return x15.anonymise_method(spec, text)


def voice(spec: Any, text: str = "") -> bool:
    """The speaker's voice is anonymised (field first, then the EN/RU words)."""
    from studio.recipes import checklist as cl

    return cl.anonymise_voice(spec, text)


def field_named(spec: Any) -> bool:
    return sf.anonymise(spec) is not None


def voice_route(steps: Sequence[str]) -> list[str]:
    """The plan's steps with the voice route in place of dubbing / cloning / lip sync."""
    rest = [s for s in steps if s not in VOICE_DROPS and s not in VOICE_STEPS]
    return [*VOICE_STEPS, *rest]


#: Face-swap steps whose new face is the customer's REFERENCE image (named as an assumption by the route).
REFERENCE_FACE_STEPS: frozenset[str] = frozenset({"замена_персонажа"})


def assumed_inputs(step: str, spec: Any, image_artefact: str) -> set[str]:
    """The reference face a `face-replace` route assumes the customer brings (counted for the candidate filter).

    The route names it as an assumption in `understood_as` ("the new face comes from YOUR reference image —
    attach it"); the anonymisation swap makes its face itself (`expert_r15.made_inputs`).
    """
    if step in REFERENCE_FACE_STEPS and getattr(spec, "task", None) == "face-replace":
        return {image_artefact}
    return set()


# --- notes (ru, en) — localised through `studio/l10n.py` ------------------------------------------

NOTE_VOICE_TRANSCRIPT = (
    "расшифровка речи говорящего с таймингами — до синтеза её вычитывают и убирают имена, места и даты",
    "a timed transcript of the speaker's words — reviewed and redacted (names, places, dates) before synthesis",
)
NOTE_VOICE_TTS = (
    "вычитанный текст читает ДРУГОЙ стоковый голос из библиотеки синтеза — не клон говорящего и не дубляж, "
    "сохраняющий его тембр",
    "the redacted text is read by a DIFFERENT stock voice from the TTS library — never a clone of the speaker, "
    "never a dub that keeps their timbre",
)
ASSEMBLY_VOICE = (
    "синтетический голос заменяет исходную речь фраза за фразой (подгонка по таймингам, ffmpeg); музыка и "
    "атмосфера — только из разделения на стемы (demucs), проверенного на слух — 0 usd",
    "the synthetic voice replaces the original speech line by line (time-fitted, ffmpeg); music and ambience "
    "only from a stem separation (demucs) checked by ear — 0 usd",
)
ASSEMBLY_PIXELATE = (
    "лица находятся в каждом кадре и пикселизуются крупным блоком (deface / ffmpeg pixelize по трекингу) — "
    "необратимая анонимизация без генеративной модели, 0 usd",
    "faces are detected in every frame and pixelated with a coarse block (deface / ffmpeg pixelize over tracked "
    "boxes) — irreversible anonymisation with no generative model, 0 usd",
)

NOTE_PAIRS: tuple[tuple[str, str], ...] = (
    NOTE_VOICE_TRANSCRIPT,
    NOTE_VOICE_TTS,
    ASSEMBLY_VOICE,
    ASSEMBLY_PIXELATE,
)


def _register() -> None:
    """Assembly lines join `brief_spec.ASSEMBLY_REASONS`, step notes `brief_spec.NOTES_EN` (by the Russian line)."""
    from studio import brief_spec as bs

    for ru, en in (ASSEMBLY_VOICE, ASSEMBLY_PIXELATE):
        bs.ASSEMBLY_REASONS.setdefault(ru, (ru, en))
    for ru, en in (NOTE_VOICE_TRANSCRIPT, NOTE_VOICE_TTS):
        bs.NOTES_EN.setdefault(ru, en)


_register()
