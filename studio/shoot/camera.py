"""Камеры прямой трансляции: кто держит камеру и как ошибается живой оператор.

ПОЧЕМУ КАМЕРА — ЭТО ПОСТ С ОПЕРАТОРОМ, А НЕ «ДВИЖЕНИЕ КАМЕРЫ»

НАБЛЮДЕНО 2026-10-07 на трёх планах фейс-оффа MiniMax H3 (fo_A, fo_B, fo_C):
промпт с «very slow push-in» дал во всех трёх один и тот же ровный ИИ-наезд от
общего плана к крупному. Владелец: «склейка слишком нереалистичная даже в таком
коротком отрывке». Живого оператора выдают ошибки — покачивание плечевой
камеры, доводка кадра за героем, перелёт и поправка, поиск фокуса, сетка клетки
на переднем плане у длиннофокусной камеры. Поэтому план описывается ПОСТОМ
трансляции (кто, чем, откуда снимает), и пост несёт свои несовершенства сам —
автору плана не нужно их помнить.

Посты взяты из того, как на самом деле снимают турнир по MMA: оператор с
плечевой камерой внутри клетки, длинный объектив снаружи сквозь сетку, стедикам
на выходе бойцов, тросовая камера над октагоном, статичная камера в
комментаторской.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Rig:
    """Пост камеры. Поля пишутся в промпт как есть, по-английски: модель читает их."""

    key: str
    body: str  # кто и как держит камеру
    lens: str  # объектив и глубина резкости
    operator: str  # несовершенства живого оператора — то, что отличает съёмку от ИИ-наезда
    handling: str  # что слышно от самой камеры (идёт в звуковую сцену)


RIGS: dict[str, Rig] = {
    "in_cage_handheld": Rig(
        "in_cage_handheld",
        "a broadcast camera operator inside the cage holding a shoulder-mounted camera",
        "medium zoom lens around 35mm, shallow depth of field",
        "natural shoulder sway and breathing motion, quick micro-corrections to keep the faces "
        "framed, a slight overshoot when following a sudden move and an immediate correction, "
        "one brief focus hunt",
        "faint camera handling noise",
    ),
    "cage_side_tele": Rig(
        "cage_side_tele",
        "a cage-side broadcast camera on a fluid-head tripod outside the octagon, shooting "
        "through the black chain-link fence",
        "long telephoto lens around 300mm, compressed perspective, very shallow depth of field, "
        "the fence mesh a soft out-of-focus diamond pattern in the foreground",
        "a slightly unsteady pan following the action, small manual zoom adjustments, the focus "
        "drifting onto the fence for a moment and snapping back",
        "",
    ),
    "steadicam_orbit": Rig(
        "steadicam_orbit",
        "a Steadicam operator walking a slow arc around the subject inside the cage",
        "wide-normal lens around 28mm, moderate depth of field",
        "a floating move with a light bob from the operator's footsteps and a slight horizon "
        "drift that the operator corrects",
        "",
    ),
    "steadicam_follow": Rig(
        "steadicam_follow",
        "a Steadicam operator walking backwards in front of the subject at shoulder height",
        "wide-normal lens around 28mm, moderate depth of field",
        "a rhythmic bob matching the walking pace, the frame lagging a little behind sudden "
        "turns of the subject and catching up",
        "",
    ),
    "overhead_cable": Rig(
        "overhead_cable",
        "a cable-suspended camera flying above the octagon",
        "wide lens around 24mm",
        "a slow descent with a gentle sway of the cables and a soft settle at the end of the move",
        "",
    ),
    "booth_locked": Rig(
        "booth_locked",
        "a locked-off broadcast camera on a tripod inside the commentary booth",
        "normal lens around 50mm, the glowing cage softly out of focus through the booth glass",
        "static framing with only a barely visible tripod settle",
        "",
    ),
}

#: Глаголы и обороты, которыми описывают работу оператора. План без хотя бы
#: одного из них на собственных битах камеры — это «камера без оператора».
OPERATOR_VERBS = re.compile(
    r"\b(reframes?|re-?centers?|rack focus|focus (?:pull|hunt|drifts?)|whip[- ]?pans?|pans?|"
    r"tilts?|follows?|pulls? back|steps? (?:around|in|back)|circles?|arcs?|zoom adjust\w*|"
    r"over-the-shoulder|tracks?|cranes?|descends?|holds? on)\b",
    re.IGNORECASE,
)

#: Гладкий ИИ-наезд. Сам по себе он и есть дефект 2026-10-07; рядом с работой
#: оператора — допустим (оператор может и наехать).
BARE_PUSH = re.compile(r"\b(slow )?(push[- ]?in|zoom[- ]?in|dolly[- ]?in)\b", re.IGNORECASE)


def describe(rig: Rig) -> str:
    """Предложение о посте для `detailed_description`."""
    return f"Filmed by {rig.body}, {rig.lens}. The camera work shows {rig.operator}."
