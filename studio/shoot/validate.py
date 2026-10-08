"""Проверка плана ДО генерации: всё, что владелец уже однажды заметил глазами.

Генерация одного плана MiniMax H3 на RTX PRO 6000 — около трёх минут и денег
за час пода; ошибка, пойманная здесь, стоит миллисекунды. Каждое правило ниже
ссылается на наблюдение, из которого оно выросло, — правило без наблюдения
сюда не добавляется.

Нарушение (`violation`) не пускает план в рендер. Риск (`risk`) печатается и
пропускает: это то, что монтажёр должен знать, но что бывает оправдано.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from itertools import pairwise

from studio.shoot.camera import BARE_PUSH, OPERATOR_VERBS, RIGS
from studio.shoot.spec import FACINGS, PLACEHOLDER, SCREEN_SIDES, Production, Shot

VIOLATION = "violation"
RISK = "risk"

#: Окно, на котором H3 обучен: 124–362 кадра при 24 fps (карточка модели).
MIN_SECONDS, MAX_SECONDS = 5, 15

#: НАБЛЮДЕНО 2026-10-07: склейки внутри генерации ломают родной звук H3.
CUT_WORDS = re.compile(
    r"(?i:\bcut(?:s|ting)? (?:to|back)\b|\b(?:hard|jump|smash|match) cut\b|\b(?:new|next) shot\b)"
    r"|\bCUT\b|\[Shot [2-9]\d*\]",
)

#: НАБЛЮДЕНО 2026-10-07: «pores and sweat sheen» → блеск и бугры на коже крупного плана.
SKIN_WORDS = re.compile(
    r"\b(pores?|sweat(?:y|ing)?(?: sheen)?|sheen|glisten\w*|oily|shiny skin|dewy|glossy skin)\b",
    re.IGNORECASE,
)

#: НАБЛЮДЕНО 2026-10-07: без запрета модель печатает UFC и ESPN на перчатках и сетке.
#: ТЗ: ни одного настоящего логотипа и имени конкурента, только «Free VPN».
BRANDS = (
    "UFC",
    "ESPN",
    "Bellator",
    "PFL",
    "ONE Championship",
    "Venum",
    "Reebok",
    "Nike",
    "Adidas",
    "Everlast",
    "Monster Energy",
    "Crypto.com",
    "NordVPN",
    "ExpressVPN",
    "Surfshark",
    "ProtonVPN",
    "CyberGhost",
    "Hotspot Shield",
    "Windscribe",
    "TunnelBear",
    "Hola",
)

#: ТЗ: «без насилия и крови, ролик должен пройти модерацию площадок».
VIOLENCE_WORDS = re.compile(
    r"\b(blood\w*|bleed\w*|gore|bruis\w*|wound\w*|broken nose|knock(?:s|ed)? (?:him )?out cold|"
    r"elbows? to the face|stomp\w*)\b",
    re.IGNORECASE,
)

#: Темп речи выше этого — актёр не успеет, H3 комкает слова (≈ 2,5–3 слова/с в живой речи).
MAX_WORDS_PER_SECOND = 3.0

_SIDE_ORDER = {"left": 0, "center": 1, "right": 2}


@dataclass(frozen=True)
class Finding:
    shot: str
    severity: str
    rule: str
    message: str


def _texts(shot: Shot) -> Iterable[tuple[str, str]]:
    yield "framing", shot.framing
    yield "purpose", shot.purpose
    yield "soundscape", shot.soundscape
    yield "music", shot.music
    for b in shot.beats:
        yield f"beat@{b.t:g}", b.text
    for d in shot.dialogue:
        yield f"line@{d.t:g}", f"{d.line} {d.delivery}"


def _brand_re(extra: tuple[str, ...]) -> re.Pattern[str]:
    names = sorted({*BRANDS, *extra}, key=len, reverse=True)
    return re.compile(
        r"(?<![\w.])(" + "|".join(re.escape(n) for n in names) + r")(?![\w])", re.IGNORECASE
    )


def check_shot(prod: Production, shot: Shot) -> list[Finding]:
    out: list[Finding] = []

    def bad(rule: str, msg: str, sev: str = VIOLATION) -> None:
        out.append(Finding(shot.id, sev, rule, msg))

    if not shot.rig:
        bad("rig", "у плана нет поста камеры: кто снимает, чем, откуда")
    elif shot.rig not in RIGS:
        bad("rig", f"неизвестный пост {shot.rig!r}; есть: {', '.join(sorted(RIGS))}")

    if not MIN_SECONDS <= shot.seconds <= MAX_SECONDS:
        bad("duration", f"{shot.seconds} с вне окна обучения H3 {MIN_SECONDS}–{MAX_SECONDS} с")

    cam = [b for b in shot.beats if b.kind == "camera"]
    if not any(OPERATOR_VERBS.search(b.text) for b in cam):
        bad(
            "operator",
            "ни один бит камеры не говорит, что делает оператор в ответ на действие "
            "(reframes, follows, rack focus, pans, steps around…)",
        )
    for b in cam:
        if BARE_PUSH.search(b.text) and not OPERATOR_VERBS.search(b.text):
            bad("bare_push", f"бит {b.t:g} с — голый наезд без работы оператора: «{b.text}»")
    for b in shot.beats:
        if b.kind not in ("action", "camera"):
            bad("beat_kind", f"бит {b.t:g} с: вид {b.kind!r}, нужен action или camera")
        if not 0 <= b.t < shot.seconds:
            bad("timing", f"бит на {b.t:g} с за пределами плана в {shot.seconds} с")

    brand = _brand_re(prod.extra_brands)
    on_set = {p.who for p in shot.blocking} | {d.who for d in shot.dialogue}
    for where, text in _texts(shot):
        if "<Subject" in text or "<Picture" in text:
            bad("subject", f"{where}: нумерацию <Subject N> ставит компилятор, пишите {{ключ}}")
        for key in PLACEHOLDER.findall(text):
            if key not in on_set:
                bad("subject", f"{where}: {{{key}}} не расставлен в этом плане")
        if CUT_WORDS.search(text):
            bad("cut", f"{where}: склейка внутри генерации — склеивает монтаж: «{text}»")
        if m := SKIN_WORDS.search(text):
            bad("skin", f"{where}: «{m.group(0)}» даёт блеск и бугры на коже")
        if m := brand.search(text):
            bad("brand", f"{where}: настоящий бренд «{m.group(0)}»")
        if m := VIOLENCE_WORDS.search(text):
            bad("violence", f"{where}: «{m.group(0)}» не пройдёт модерацию площадок")

    names = set(prod.characters)
    seen: set[str] = set()
    for p in shot.blocking:
        if p.who not in names:
            bad("blocking", f"в кадре неизвестный персонаж {p.who!r}")
        if p.who in seen:
            bad("blocking", f"{p.who} в кадре дважды")
        seen.add(p.who)
        if p.screen not in SCREEN_SIDES:
            bad("blocking", f"{p.who}: сторона {p.screen!r}, нужна одна из {SCREEN_SIDES}")
        if p.faces not in FACINGS:
            bad("blocking", f"{p.who}: взгляд {p.faces!r}, нужен один из {FACINGS}")
    if not shot.blocking:
        bad("blocking", "в плане никто не расставлен: сторона экрана и взгляд не проверяемы")

    sides = [p for p in shot.blocking if p.screen in ("left", "right")]
    if len(sides) == 2 and sides[0].screen != sides[1].screen:
        lft = sides[0] if sides[0].screen == "left" else sides[1]
        rgt = sides[1] if lft is sides[0] else sides[0]
        if lft.faces == "left" and rgt.faces == "right":
            bad("eyeline", f"{lft.who} и {rgt.who} смотрят друг от друга", RISK)

    for d in shot.dialogue:
        if d.who not in names:
            bad("dialogue", f"реплику говорит неизвестный {d.who!r}")
        if not 0 <= d.t < shot.seconds:
            bad("timing", f"реплика на {d.t:g} с за пределами плана в {shot.seconds} с")
    lines = sorted(shot.dialogue, key=lambda d: d.t)
    for i, d in enumerate(lines):
        end = lines[i + 1].t if i + 1 < len(lines) else float(shot.seconds)
        words = len(d.line.split())
        if end > d.t and words / (end - d.t) > MAX_WORDS_PER_SECOND:
            bad(
                "pace",
                f"«{d.line[:40]}…»: {words} слов за {end - d.t:.1f} с — актёр не успеет",
            )
    return out


def check_continuity(prod: Production) -> list[Finding]:
    """Правило 180° и встречные взгляды между соседними планами одной сцены."""
    out: list[Finding] = []
    for prev, cur in pairwise(prod.shots):
        if prev.scene != cur.scene or cur.crossing or prev.crossing:
            continue
        a = {p.who: p for p in prev.blocking}
        b = {p.who: p for p in cur.blocking}
        both = [w for w in a if w in b]
        for i, x in enumerate(both):
            for y in both[i + 1 :]:
                before = _SIDE_ORDER[a[x].screen] - _SIDE_ORDER[a[y].screen]
                after = _SIDE_ORDER[b[x].screen] - _SIDE_ORDER[b[y].screen]
                if before * after < 0:
                    out.append(
                        Finding(
                            cur.id,
                            VIOLATION,
                            "axis",
                            f"{x} и {y} поменялись сторонами экрана после {prev.id}: "
                            "камера перепрыгнула ось; если так задумано — crossing: true",
                        )
                    )
        if len(prev.blocking) == 1 and len(cur.blocking) == 1:
            p, c = prev.blocking[0], cur.blocking[0]
            if p.who != c.who and p.faces == c.faces and p.faces in ("left", "right"):
                out.append(
                    Finding(
                        cur.id,
                        VIOLATION,
                        "eyeline",
                        f"{p.who} в {prev.id} и {c.who} в {cur.id} оба смотрят {p.faces}: "
                        "на монтаже они не смотрят друг на друга",
                    )
                )
    return out


def secret_pattern(words: tuple[str, ...]) -> re.Pattern[str] | None:
    if not words:
        return None
    # «слово» — целиком; «основа*» — с любым окончанием (русские падежи)
    alts = [re.escape(w[:-1]) + r"\w*" if w.endswith("*") else re.escape(w) + r"\b" for w in words]
    return re.compile(r"\b(" + "|".join(alts) + r")", re.IGNORECASE)


def check_reveal(prod: Production) -> list[Finding]:
    """Карты не раскрываются раньше времени.

    НАБЛЮДЕНО 2026-10-08, владелец о сценарии v2: реплики «Я бесплатный, мной
    все пользуются» — «кринж и детский сад»; «до последнего момента всё должно
    выглядеть как реальный бой, карты раскрываются в конце». Сценарий v2 называл
    продукт в каждой сцене — и в репликах, и в звуке, и в назначении плана,
    которое компилятор отдаёт модели в `summary`.
    """
    pat = secret_pattern(prod.secret_words)
    if not prod.reveal_from:
        return []
    ids = [s.id for s in prod.shots]
    if prod.reveal_from not in ids:
        return [
            Finding("*", VIOLATION, "reveal", f"reveal_from={prod.reveal_from!r}: нет такого плана")
        ]
    if pat is None:
        return [
            Finding("*", RISK, "reveal", "reveal_from задан, а secret_words пуст — проверять нечем")
        ]
    out: list[Finding] = []
    for shot in prod.shots[: ids.index(prod.reveal_from)]:
        for where, text in _texts(shot):
            if m := pat.search(text):
                out.append(
                    Finding(
                        shot.id,
                        VIOLATION,
                        "reveal",
                        f"{where}: «{m.group(0)}» до развязки ({prod.reveal_from}) раскрывает карты",
                    )
                )
    return out


def check(prod: Production) -> list[Finding]:
    found: list[Finding] = []
    ids: set[str] = set()
    look_brand = _brand_re(prod.extra_brands)
    for where, text in (("look", prod.look), ("league", prod.league)):
        if m := look_brand.search(text):
            found.append(
                Finding("*", VIOLATION, "brand", f"{where}: настоящий бренд «{m.group(0)}»")
            )
        if m := SKIN_WORDS.search(text):
            found.append(Finding("*", VIOLATION, "skin", f"{where}: «{m.group(0)}»"))
    for c in prod.characters.values():
        if m := look_brand.search(c.description):
            found.append(
                Finding(
                    "*", VIOLATION, "brand", f"описание {c.key}: настоящий бренд «{m.group(0)}»"
                )
            )
        if m := SKIN_WORDS.search(c.description):
            found.append(Finding("*", VIOLATION, "skin", f"описание {c.key}: «{m.group(0)}»"))
    for s in prod.shots:
        if s.id in ids:
            found.append(Finding(s.id, VIOLATION, "id", "id плана повторяется"))
        ids.add(s.id)
        found.extend(check_shot(prod, s))
    found.extend(check_continuity(prod))
    found.extend(check_reveal(prod))
    return found


def outcome(found: list[Finding]) -> str:
    """«годно» — ни одного нарушения; риски не останавливают."""
    return "не годно" if any(f.severity == VIOLATION for f in found) else "годно"
