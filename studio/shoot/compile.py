"""План → промпт MiniMax H3 в его собственной схеме разделов.

СХЕМА ВЗЯТА У ВЕНДОРА, А НЕ ПРИДУМАНА. Шаблон Comfy-Org
`video_minimax_h3_multiframe_reference` (прочитан 2026-10-07) пишет промпт
разделами subject_definitions / summary / retention_analysis /
detailed_description / overall_soundscape / non_diegetic_music, с персонажами
`<Subject N>`, картинками `<Picture N>` в порядке подключения и временем вида
00:02.500 внутри `[Shot N]`. До этого промпты писались прозой.

ЧТО КОМПИЛЯТОР ПИШЕТ ЗА АВТОРА, ЧТОБЫ АВТОР НЕ ЗАБЫЛ
* пост камеры с несовершенствами живого оператора (`camera.RIGS`);
* «один непрерывный дубль, без склеек» — всегда;
* разницу в росте из чисел персонажей. НАБЛЮДЕНО 2026-10-07: «twice as wide,
  towering» словами модель дважды не выполнила; число в сантиметрах — попытка
  дать ей то, что она может проверить;
* образ дома: свет трансляции, своя лига на канвасе, ни одного чужого бренда,
  матовая кожа. НАБЛЮДЕНО 2026-10-07: «pores and sweat sheen» в промпте дало
  блеск и бугры на коже, которые владелец заметил на первом же стоп-кадре.
  Тот же день, A/B sk_R1–R5: матовая формулировка убрала блеск у обоих бойцов;
  у Адгара остались красные отметины на скуле, которые читаются как ссадины, —
  ТЗ запрещает кровь и насилие, поэтому лицо прямо названо чистым.
* форма без знаков спортивных брендов. НАБЛЮДЕНО 2026-10-08, S01_hook_lookup:
  на плече Адгара и у ворота Августа модель дорисовала знак, похожий на
  логотип Venum, — OCR его не читает (это знак, не буквы). Владелец: похожий
  знак допустим, идентичный — нет.
* пол целиком. НАБЛЮДЕНО 2026-10-08, S05_faceoff: с рефом канваса в центре
  модель всё равно напечатала рядом курсивное UFC — запрет «других слов» не
  описывал, что там вместо них. Теперь описан пустой белый канвас с линиями.
"""

from __future__ import annotations

from dataclasses import dataclass

from studio.shoot.camera import RIGS, describe
from studio.shoot.spec import PLACEHOLDER, Production, Shot


@dataclass(frozen=True)
class Compiled:
    shot_id: str
    refs: tuple[str, ...]  # файлы картинок в порядке <Picture 1..N>
    prompt: str
    seconds: int
    seed: int
    width: int
    height: int


def _ts(t: float) -> str:
    m, s = divmod(max(0.0, t), 60)
    return f"{int(m):02d}:{s:06.3f}"


def _cast(prod: Production, shot: Shot) -> list[str]:
    keys: list[str] = []
    for p in shot.blocking:
        if p.who not in keys:
            keys.append(p.who)
    for d in shot.dialogue:
        if d.who not in keys:
            keys.append(d.who)
    return keys


def compile_shot(prod: Production, shot: Shot) -> Compiled:
    cast = _cast(prod, shot)
    subj = {k: i + 1 for i, k in enumerate(cast)}
    refs: list[str] = []
    face_pic: dict[str, int] = {}
    extra_pic: list[tuple[str, int, str]] = []
    for k in cast:
        c = prod.characters[k]
        if c.face:
            refs.append(c.face)
            face_pic[k] = len(refs)
    for k in cast:
        for r in prod.characters[k].refs:
            refs.append(r.file)
            extra_pic.append((k, len(refs), r.what))
    set_pic: list[tuple[int, str]] = []
    for sr in prod.set_refs:
        if not sr.scenes or shot.scene in sr.scenes:
            refs.append(sr.file)
            set_pic.append((len(refs), sr.what))

    defs = []
    for k in cast:
        c = prod.characters[k]
        who = f"the man in <Picture {face_pic[k]}>" if k in face_pic else "a man"
        body = ""
        if c.height_m and c.weight_kg:
            body = f", {c.height_m:.2f} m tall and {c.weight_kg:.0f} kg"
        extras = "".join(
            f" He has the {what} from <Picture {n}>." for kk, n, what in extra_pic if kk == k
        )
        defs.append(f"<Subject {subj[k]}> is {c.name}, {who}{body}: {c.description}.{extras}")

    # разница в росте — из чисел, одна фраза на самую большую пару в кадре:
    # три фразы про рост в одном промпте модель путает между собой
    heights = [(prod.characters[p.who].height_m, p.who) for p in shot.blocking]
    heights = [h for h in heights if h[0]]
    scale = []
    if len(heights) >= 2:
        (hs, short), (ht, tall) = min(heights), max(heights)
        cm = round((ht - hs) * 100)
        if cm >= 8:
            level = "mouth" if cm < 15 else "chin" if cm < 25 else "collarbones"
            scale.append(
                f"<Subject {subj[tall]}> is {cm} cm taller than <Subject {subj[short]}>: "
                f"standing face to face, <Subject {subj[short]}>'s eyes are level with "
                f"<Subject {subj[tall]}>'s {level}, so <Subject {subj[short]}> must look up."
            )

    retention = (
        [
            f"<Subject {subj[k]}>: fully_preserved - face and hair from <Picture {face_pic[k]}>."
            for k in cast
            if k in face_pic
        ]
        + [
            f"<Picture {n}>: fully_preserved - {what} (<Subject {subj[k]}>)."
            for k, n, what in extra_pic
        ]
        + [f"<Picture {n}>: fully_preserved - {what}." for n, what in set_pic]
    )

    placement = []
    for p in shot.blocking:
        s = f"<Subject {subj[p.who]}>"
        side = {"left": "on the left of frame", "right": "on the right of frame"}.get(
            p.screen, "in the center of frame"
        )
        look = {
            "left": "facing left",
            "right": "facing right",
            "camera": "facing the camera",
            "away": "with his back to the camera",
        }[p.faces]
        placement.append(f"{s} {side}, {look}")

    def sub(text: str) -> str:
        return PLACEHOLDER.sub(lambda m: f"<Subject {subj[m.group(1)]}>", text)

    rig = RIGS[shot.rig]
    timeline = []
    events: list[tuple[float, str]] = [(b.t, sub(b.text)) for b in shot.beats]
    for d in shot.dialogue:
        how = f" {d.delivery}" if d.delivery else ""
        events.append((d.t, f"<Subject {subj[d.who]}> says{how}: {d.line}"))
    for t, text in sorted(events, key=lambda e: e[0]):
        timeline.append(f"At {_ts(t)} {text}" if t > 0 else text)

    # НАБЛЮДЕНО 2026-10-07, S01_announce: фраза о перчатках в образе дома надела
    # боксёрскую перчатку на конферансье. Перчатки называются, только если в
    # кадре есть тот, у кого они в описании.
    gloved = any("glove" in prod.characters[p.who].description for p in shot.blocking)
    look = " ".join(
        [
            prod.look,
            f"The only lettering in the arena is the made-up league name {prod.league}; there "
            "are no real-world brand logos or league names anywhere.",
            # каждая декорация — своей фразой: до 2026-10-08 любая называлась «полом»,
            # и реф мата сетки уходил в модель как второй рисунок канваса
            *(f"Exactly as in <Picture {n}>: {what}." for n, what in set_pic),
            *(
                [
                    "Around the center logo the canvas is plain white with thin black octagon "
                    "lines and nothing else printed on it; the corner posts and the fence "
                    "padding carry no other words or logos."
                ]
                if set_pic
                else []
            ),
            *(
                [
                    "The fighters' gloves are plain matte black with no letters or logos at all. "
                    "Jerseys and shorts carry no sportswear brand marks: the only print on a "
                    "jersey is its one chest sponsor."
                ]
                if gloved
                else []
            ),
            "Natural matte skin with subtle true-to-life texture, no oily shine, no beauty "
            "retouching; clean unmarked faces with no scratches, cuts or red marks.",
            # НАБЛЮДЕНО 2026-10-08, владелец о S03: «футболка неестественно
            # сжимается, движения слишком плавные» — у H3 тянет к слоумо
            "Everything moves at real-time speed with natural weight, momentum and small "
            "irregularities, never in slow motion; fabric keeps its thickness and creases "
            "naturally, it never shrinks or stretches like rubber.",
        ]
    )
    shot_text = " ".join(
        [
            f"[Shot 1] One continuous take, no cuts, {sub(shot.framing)}.",
            describe(rig),
            "Blocking: " + "; ".join(placement) + ".",
            *scale,
            *timeline,
        ]
    )
    sound = sub(shot.soundscape.strip())
    if rig.handling:
        sound = (sound + " " if sound else "") + f"Under it, {rig.handling}."

    prompt = "\n".join(
        [
            "subject_definitions:",
            *defs,
            "",
            "summary:",
            f"[reference generation] {sub(shot.purpose or shot.framing)}",
            "",
            "retention_analysis:",
            *retention,
            "",
            "detailed_description:",
            look,
            shot_text,
            "",
            "overall_soundscape:",
            sound or "Live arena ambience.",
            "",
            "non_diegetic_music:",
            shot.music or "None.",
        ]
    )
    return Compiled(shot.id, tuple(refs), prompt, shot.seconds, shot.seed, prod.width, prod.height)
