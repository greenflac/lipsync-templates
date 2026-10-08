"""Спецификация производства: персонажи, образ дома, планы. Читается из JSON.

ОДИН ПЛАН — ОДНА ГЕНЕРАЦИЯ. Склейки делает монтаж, а не модель: НАБЛЮДЕНО
2026-10-07 — фейс-офф с тремя CUT внутри одной генерации MiniMax H3 владелец
услышал как «звук очень сильно глючит», а речевые клипы одним планом без склеек
на тех же весах и драйверах — как чистые. Поэтому в плане нет поля для
склеек вовсе, а слова о склейках в тексте ловит валидатор.

СТОРОНА ЭКРАНА И ВЗГЛЯД — ПОЛЯ, А НЕ ТЕКСТ. Правило 180° держится, только если
его можно проверить машиной: у каждого персонажа в кадре записано, где он
(left/center/right) и куда смотрит (left/right/camera/away).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

#: В тексте плана персонаж пишется как {august}; номер <Subject N> ставит
#: компилятор по порядку расстановки. Ручная нумерация ломалась бы при каждой
#: перестановке персонажей в blocking.
PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")

SCREEN_SIDES = ("left", "center", "right")
FACINGS = ("left", "right", "camera", "away")


@dataclass(frozen=True)
class Ref:
    """Дополнительная картинка персонажа: логотип, нашивка. `what` — где она на нём."""

    file: str
    what: str


@dataclass(frozen=True)
class SetRef:
    """Картинка декорации: канвас, баннер. Подключается ко всем планам своих сцен.

    НАБЛЮДЕНО 2026-10-07: запрет брендов словами не держит пол октагона — в
    S01_announce на канвасе напечатано «UFC», в sc_S1 «OFC». Модели нужно
    показать, ЧТО напечатано на полу, а не только сказать, чего там нет.
    """

    file: str
    what: str
    scenes: tuple[str, ...] = ()  # пусто — во всех сценах


@dataclass(frozen=True)
class Character:
    key: str
    name: str
    description: str
    face: str = ""  # кроп головы для лока личности; пусто — персонаж без лока
    refs: tuple[Ref, ...] = ()
    height_m: float = 0.0
    weight_kg: float = 0.0


@dataclass(frozen=True)
class Placement:
    who: str
    screen: str
    faces: str


@dataclass(frozen=True)
class Beat:
    t: float  # секунда от начала плана
    kind: str  # "action" | "camera"
    text: str


@dataclass(frozen=True)
class Line:
    t: float
    who: str
    line: str
    delivery: str = ""


@dataclass(frozen=True)
class Shot:
    id: str
    scene: str
    seconds: int
    rig: str
    framing: str
    blocking: tuple[Placement, ...]
    beats: tuple[Beat, ...]
    dialogue: tuple[Line, ...] = ()
    soundscape: str = ""
    music: str = "None."
    seed: int = 1
    crossing: bool = False  # план сознательно переходит ось (камера проходит линию в кадре)
    purpose: str = ""  # зачем план в истории: читается монтажёром и попадает в summary


@dataclass(frozen=True)
class Production:
    title: str
    look: str
    league: str
    width: int
    height: int
    characters: dict[str, Character]
    shots: tuple[Shot, ...]
    extra_brands: tuple[str, ...] = field(default=())
    set_refs: tuple[SetRef, ...] = field(default=())
    budget_usd: float = 0.0  # 0 — бюджет не задан
    #: С какого плана карты раскрыты. До него — настоящий бой, и слова из
    #: `secret_words` нигде не звучат и не пишутся (владелец, 2026-10-08).
    reveal_from: str = ""
    secret_words: tuple[str, ...] = ()


def load(path: str | Path) -> Production:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    chars = {
        k: Character(
            key=k,
            name=v["name"],
            description=v["description"],
            face=v.get("face", ""),
            refs=tuple(Ref(r["file"], r["what"]) for r in v.get("refs", [])),
            height_m=float(v.get("height_m", 0)),
            weight_kg=float(v.get("weight_kg", 0)),
        )
        for k, v in raw["characters"].items()
    }
    shots = tuple(
        Shot(
            id=s["id"],
            scene=s["scene"],
            seconds=int(s["seconds"]),
            rig=s.get("rig", ""),
            framing=s.get("framing", ""),
            blocking=tuple(Placement(b["who"], b["screen"], b["faces"]) for b in s["blocking"]),
            beats=tuple(Beat(float(b["t"]), b["kind"], b["text"]) for b in s.get("beats", [])),
            dialogue=tuple(
                Line(float(d["t"]), d["who"], d["line"], d.get("delivery", ""))
                for d in s.get("dialogue", [])
            ),
            soundscape=s.get("soundscape", ""),
            music=s.get("music", "None."),
            seed=int(s.get("seed", 1)),
            crossing=bool(s.get("crossing", False)),
            purpose=s.get("purpose", ""),
        )
        for s in raw["shots"]
    )
    return Production(
        title=raw["title"],
        look=raw["look"],
        league=raw["league"],
        width=int(raw.get("width", 768)),
        height=int(raw.get("height", 1344)),
        characters=chars,
        shots=shots,
        extra_brands=tuple(raw.get("extra_brands", [])),
        budget_usd=float(raw.get("budget_usd", 0)),
        reveal_from=raw.get("reveal_from", ""),
        secret_words=tuple(raw.get("secret_words", [])),
        set_refs=tuple(
            SetRef(r["file"], r["what"], tuple(r.get("scenes", [])))
            for r in raw.get("set_refs", [])
        ),
    )
