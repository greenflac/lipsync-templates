"""Route an edit of the customer's footage by WHAT is edited, not by the task word (round 13).

WHY. "Replace the text on the sign" was planned as character replacement: the
caller wrote `task: face-replace` (the brief says "replace"), and the route
went to `замена_персонажа` — a step that swaps a person, with no candidate
for a shop sign. Changing lettering in a shot is an INPAINT / video-edit job
with text rendering: a mask over the sign, new text drawn into it, tracked
across frames — or a planar track and a composite at assembly.

RULE (structured first). `spec.edit` names `replace-text` -> the edit job,
whatever task word came with it. Without it, the words decide only when the
spec cannot: a face/character task on the customer's VIDEO and the brief asks
to change text, a sign, a label or a billboard. Round 14: the edit TARGET
decides, not whether people are in the shot — a person in `spec.people` who
walks past the sign does not make the lettering a character swap; only a face
or a person named as the object of the edit (`PERSON_EDIT`) keeps the task.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from studio import endpoints as ep

#: Tasks whose route is a person/character swap or a generic edit — the ones a
#: text edit gets misfiled under.
TEXT_EDIT_TASKS: frozenset[str] = frozenset({"face-replace", "edit", "video-edit"})

#: "change the text / lettering / sign", "the words on the billboard", RU too.
TEXT_EDIT_WORDS = re.compile(
    r"\b(?:replac|chang|swap|updat|edit|rewrit|translat|correct|fix)\w*\s+(?:\w+\s+){0,3}?"
    r"(?:text|lettering|wording|words|writing|inscription|sign|signage|signboard|label|headline|caption|title|logo text|typo|spelling|misspelling)\b"
    r"|\b(?:text|lettering|wording|words|writing|inscription|name)\s+on\s+(?:the\s+|a\s+|our\s+|my\s+|this\s+)?"
    r"(?:\w+\s+)?(?:sign|signboard|billboard|banner|board|storefront|shop ?front|truck|van|poster|placard|plate|label|door|wall|screen)\b"
    r"|замен\w*\s+(?:\w+\s+){0,2}?(?:текст|надпис|вывеск|табличк)|(?:измен|исправ|перевед|поменя|перепиш)\w*\s+(?:\w+\s+){0,2}?"
    r"(?:текст|надпис|вывеск|табличк)|надпис\w*\s+на\s+(?:\w+\s+)?(?:вывеск|табличк|баннер|билборд|витрин|фасад|машин|грузовик|стен)",
    re.I,
)
#: A face or a person named (kept for callers that read it; the route reads `PERSON_EDIT`).
PERSON_WORDS = re.compile(
    r"\bfaces?\b|\bperson\b|\bpeople\b|\bactor|\bcharacter|\bhead\b|\bbody\b|\bmascot|лиц[оаеу]\b|человек|актёр|актер|персонаж|голов",
    re.I,
)
#: Round 14: a person or a face is the OBJECT of the edit ("swap the actor's face", "put my face on the
#: presenter", "замените лицо ведущего") — not merely in the shot ("two people walk past the sign",
#: "the presenter stands by the screen"). Only this keeps a face/character task.
PERSON_EDIT = re.compile(
    r"face[- ]?swap|faceswap|deep-?fake|\b(?:my|our|his|her|their|your|new|another) faces?\b"
    r"|\b(?:replac|swap|chang|put|turn|transform|mak)\w*\s+(?:(?:the|a|an|my|our|his|her|their|this|that)\s+)?"
    r"(?:[\w'’-]+\s+)?(?:faces?|heads?|bod(?:y|ies)|actors?|actress\w*|presenters?|persons?|people|man|men|woman|women"
    r"|him|her|them|characters?|mascots?|hosts?|speakers?|anchors?)\b(?!\s+(?:holds|wears|stands|is holding|is wearing))"
    r"|подмен\w* лиц|\bмо[её] лицо|\bнаш\w* лиц|\bего лицо|\bеё лицо|лиц[оау]\s+(?:ведущ|актёр|актер|человек|персонаж|диктор|спикер)"
    r"|(?:замен|поменя|постав|сдела|превра)\w*\s+(?:\w+\s+)?(?:лиц[оа]|голов\w*|человек\w*|актёр\w*|актер\w*|актрис\w*|ведущ\w*"
    r"|персонаж\w*|диктор\w*|спикер\w*|его|её|ее|их)\b",
    re.I,
)

NOTE_EN = (
    "text in the shot is an inpaint / video-edit job with text rendering, not a character swap: mask the sign, "
    "draw the new lettering into it and track it across frames — or, for exact typography, planar-track the "
    "surface (Mocha / After Effects) and composite the text at assembly"
)
NOTE_RU = (
    "текст в кадре — правка по маске с отрисовкой текста, а не замена персонажа: маска вывески, новая надпись "
    "внутри неё и трекинг по кадрам — или, для точной типографики, планарный трекинг поверхности (Mocha / "
    "After Effects) и композитинг текста на монтаже"
)


def wants_text_edit(spec: Any, text: str) -> bool:
    """Is this order an edit of lettering in the customer's video?"""
    if ep.EDIT_REPLACE_TEXT in tuple(getattr(spec, "edit", ()) or ()):
        return True
    if getattr(spec, "task", "") not in TEXT_EDIT_TASKS or "video" not in tuple(getattr(spec, "inputs", ()) or ()):
        return False
    # ЧЕЛОВЕК В КАДРЕ — НЕ ЦЕЛЬ ПРАВКИ (четырнадцатый круг). Раньше любой
    # человек в `spec.people` держал задачу «замена лица», и «двое проходят
    # мимо вывески — замените надпись» уходило в замену персонажа без модели и
    # без цены. Решает ЦЕЛЬ правки: надпись (TEXT_EDIT_WORDS) — правка видео;
    # лицо или человек как объект замены (PERSON_EDIT) — задача остаётся.
    низ = " ".join(str(text or "").split())
    return bool(TEXT_EDIT_WORDS.search(низ)) and not PERSON_EDIT.search(низ)


def reroute(spec: Any, text: str) -> tuple[Any, str]:
    """(spec routed as a text edit of the video, note) — or the spec unchanged and ""."""
    if not wants_text_edit(spec, text) or "video" not in tuple(getattr(spec, "inputs", ()) or ()):
        return spec, ""
    правки = tuple(dict.fromkeys((*tuple(spec.edit or ()), ep.EDIT_REPLACE_TEXT)))
    правки = tuple(п for п in правки if п != ep.EDIT_REPLACE_OBJECT) or (ep.EDIT_REPLACE_TEXT,)
    if spec.task == "video-edit" and tuple(spec.edit or ()) == правки:
        return spec, NOTE_EN
    источник = dict(getattr(spec, "source", {}) or {})
    источник["edit"] = источник.get("edit") or "derived"
    return replace(spec, task="video-edit", edit=правки, source=источник), NOTE_EN
