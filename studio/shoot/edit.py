"""Монтаж: лист `edit.json` → мастер 1080×1920 на ffmpeg, план за планом.

Монтажный лист — данные, как и сценарий: каждый план берёт отрезок из своего
рендера, поверх кладутся графика, субтитры и звуковые эффекты со временем
ОТНОСИТЕЛЬНО ПЛАНА. Поэтому замена дубля (другой сид) не сдвигает ничего,
кроме этого плана.

ПЛАНА ЕЩЁ НЕТ — СЛЕЙТ, А НЕ ОТКАЗ. На место отсутствующего рендера встаёт
чёрный кадр с id и назначением плана той же длины. Так ритм, графику и звук
ролика можно смотреть и править до того, как оплачен GPU. НАБЛЮДЕНО
2026-10-07: GPU простаивал три четверти оплаченного времени, а баланс
кончился посреди производства (см. POSTMORTEM.md).

Склейки внутри генерации запрещены (`validate.CUT_WORDS`), поэтому каждая
склейка ролика — здесь. На каждом стыке у звука фейд 20 мс: жёсткий стык
волны щёлкает.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

W, H, FPS, AR = 1080, 1920, 24, 48000
EDGE_FADE = 0.02  # секунд фейда звука на каждом стыке
FONT = "/usr/share/fonts/opentype/inter/Inter-Bold.otf"
#: Верх строки субтитра. Ниже ~1500 px вертикальный кадр закрывает интерфейс
#: площадки, а 960–1390 заняты эфирной графикой (render_gfx.py) — субтитр между.
SUB_Y = 1400
SUB_SIZE = 46
SUB_MAX_W = W - 2 * 60  # строка субтитра с плашкой не шире кадра минус поля


def text_width(text: str, size: int = SUB_SIZE) -> float:
    from PIL import ImageFont

    return float(ImageFont.truetype(FONT, size).getlength(text))


@dataclass(frozen=True)
class Overlay:
    img: str
    t: float = 0.0
    dur: float = -1.0  # -1 — до конца плана


@dataclass(frozen=True)
class Sub:
    t: float
    dur: float
    text: str


@dataclass(frozen=True)
class Sfx:
    file: str
    t: float
    gain_db: float = 0.0


@dataclass(frozen=True)
class Hold:
    """Стоп-кадр внутри плана: «лаг». Звук на это время пропадает."""

    t: float
    dur: float


@dataclass(frozen=True)
class Glitch:
    """Сбой сигнала на кадре: сдвиг каналов и цифровой шум. Только в развязке."""

    t: float
    dur: float


VIDEO_OVERLAY = (".mov", ".webm", ".mp4")


def video_input(path: Path) -> list[str]:
    """Входные опции ffmpeg для анимированной графики.

    Альфу VP9 декодирует только libvpx: встроенный декодер ffmpeg молча отдаёт
    непрозрачный кадр, и графика ложится чёрным прямоугольником.
    """
    pre = ["-c:v", "libvpx-vp9"] if path.suffix.lower() == ".webm" else []
    return [*pre, "-i", str(path)]


def is_video(path: str) -> bool:
    """Анимированная графика (.mov с альфой из render_gfx.py), а не картинка."""
    return path.lower().endswith(VIDEO_OVERLAY)


@dataclass(frozen=True)
class Clip:
    shot: str
    src_in: float
    src_out: float
    note: str = ""
    overlays: tuple[Overlay, ...] = ()
    subs: tuple[Sub, ...] = ()
    sfx: tuple[Sfx, ...] = ()
    holds: tuple[Hold, ...] = ()
    still: str = ""  # картинка или ролик вместо рендера (пэкшот)
    gain_db: float = 0.0
    glitches: tuple[Glitch, ...] = ()
    #: Укрупнение в монтаже: 1.18 — кадр на 18 % крупнее; zoom_y — куда сдвинут
    #: кроп (0 — верх кадра, 0.5 — центр). Ревью 2026-10-08: S03 и S04 сняты
    #: одной крупностью, и 77 против 150 кг на одиночных планах не читается.
    zoom: float = 1.0
    zoom_y: float = 0.5
    #: Окна полной тишины плана (звук модели и эффекты). Ревью 2026-10-08:
    #: стоп-кадр читается как «зависло», только если вместе с картинкой
    #: встаёт и звук.
    mutes: tuple[Glitch, ...] = ()
    #: Звуковые «ручки» склейки (J/L-cut). НАБЛЮДЕНО 2026-10-08, владелец о
    #: монтаже: «рваный, обрезается ровно в конце фразы». Звук каждого плана
    #: кончался точно на склейке, следующий начинался с нуля. Теперь звук плана
    #: заходит под предыдущую картинку на audio_lead с и тянется под следующую
    #: на audio_tail с, с фейдом, — как в живом монтаже. None — значения листа.
    audio_lead: float | None = None
    audio_tail: float | None = None

    @property
    def length(self) -> float:
        return self.src_out - self.src_in + sum(h.dur for h in self.holds)


@dataclass(frozen=True)
class Edit:
    clips: tuple[Clip, ...]
    global_overlays: tuple[Overlay, ...] = ()
    #: Водяной знак — отдельно от графики: его снимают одним флагом
    #: (`edit … --no-watermark`), не трогая лист. Владелец, 2026-10-08: «потом
    #: должна быть возможность её убрать».
    watermark: Overlay | None = None
    #: Подложки поверх нескольких планов (гул зала, пульс): файл, от плана, до плана.
    beds: tuple[Sfx, ...] = ()
    bed_ends: tuple[float, ...] = ()
    #: Ручки по умолчанию для всех планов с исходником.
    audio_lead: float = 0.12
    audio_tail: float = 0.35
    loudness_lufs: float = -14.0
    true_peak_db: float = -1.0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def length(self) -> float:
        return sum(c.length for c in self.clips)


def load(path: str | Path) -> Edit:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))

    def ovs(items: list[dict[str, Any]]) -> tuple[Overlay, ...]:
        return tuple(
            Overlay(o["img"], float(o.get("t", 0)), float(o.get("dur", -1))) for o in items
        )

    clips = tuple(
        Clip(
            shot=c["shot"],
            src_in=float(c.get("in", 0)),
            src_out=float(c["out"]),
            note=c.get("note", ""),
            overlays=ovs(c.get("overlays", [])),
            subs=tuple(Sub(float(s["t"]), float(s["dur"]), s["text"]) for s in c.get("subs", [])),
            sfx=tuple(
                Sfx(s["file"], float(s["t"]), float(s.get("gain_db", 0))) for s in c.get("sfx", [])
            ),
            holds=tuple(Hold(float(h["t"]), float(h["dur"])) for h in c.get("holds", [])),
            still=c.get("still", ""),
            gain_db=float(c.get("gain_db", 0)),
            glitches=tuple(Glitch(float(g["t"]), float(g["dur"])) for g in c.get("glitches", [])),
            zoom=float(c.get("zoom", 1.0)),
            zoom_y=float(c.get("zoom_y", 0.5)),
            mutes=tuple(Glitch(float(g["t"]), float(g["dur"])) for g in c.get("mutes", [])),
            audio_lead=float(c["audio_lead"]) if "audio_lead" in c else None,
            audio_tail=float(c["audio_tail"]) if "audio_tail" in c else None,
        )
        for c in raw["clips"]
    )
    # Общая графика привязывается к планам («from»/«to» — id плана), а не к
    # секундам: после подгонки in/out по реальным рендерам секунды уезжают.
    starts, t0 = {}, 0.0
    for c in clips:
        starts[c.shot] = (t0, t0 + c.length)
        t0 += c.length

    def glob(items: list[dict[str, Any]]) -> tuple[Overlay, ...]:
        out = []
        for o in items:
            if "from" in o:
                a = starts[o["from"]][0]
                b = starts[o.get("to", o["from"])][1]
                out.append(Overlay(o["img"], a, b - a))
            else:
                out.append(Overlay(o["img"], float(o.get("t", 0)), float(o.get("dur", -1))))
        return tuple(out)

    return Edit(
        clips=clips,
        global_overlays=glob(raw.get("global_overlays", [])),
        watermark=ovs([raw["watermark"]])[0] if raw.get("watermark") else None,
        beds=tuple(
            Sfx(b["file"], starts[b["from"]][0], float(b.get("gain_db", 0)))
            for b in raw.get("beds", [])
        ),
        bed_ends=tuple(starts[b.get("to", b["from"])][1] for b in raw.get("beds", [])),
        audio_lead=float(raw.get("audio_lead", 0.12)),
        audio_tail=float(raw.get("audio_tail", 0.35)),
        loudness_lufs=float(raw.get("loudness_lufs", -14)),
        true_peak_db=float(raw.get("true_peak_db", -1)),
    )


def problems(
    e: Edit,
    base: Path,
    shots: set[str],
    reveal_from: str = "",
    secret: re.Pattern[str] | None = None,
) -> list[str]:
    """Что не так с листом до сборки. Отсутствующий рендер — не проблема, а слейт.

    `reveal_from`/`secret` — то же правило, что `validate.check_reveal`, для
    субтитров: зритель читает их раньше, чем слышит реплику.
    """
    out: list[str] = []
    revealed = not reveal_from
    for i, c in enumerate(e.clips):
        tag = f"#{i + 1} {c.shot}"
        revealed = revealed or c.shot == reveal_from
        if secret is not None and not revealed:
            for sub in c.subs:
                if m := secret.search(sub.text):
                    out.append(f"{tag}: субтитр «{m.group(0)}» до развязки раскрывает карты")
        if not c.still and c.shot not in shots:
            out.append(f"{tag}: плана нет в production.json")
        if c.src_out <= c.src_in:
            out.append(f"{tag}: out {c.src_out} не позже in {c.src_in}")
        for h in c.holds:
            if not c.src_in <= h.t <= c.src_out:
                out.append(f"{tag}: стоп-кадр на {h.t} вне отрезка {c.src_in}–{c.src_out}")
        placed = [(o.img, o.t) for o in c.overlays] + [(f.file, f.t) for f in c.sfx]
        for path, t in placed:
            if not (base / path).exists():
                out.append(f"{tag}: нет файла {path}")
            if t < 0 or t >= c.length:
                out.append(f"{tag}: {path} на {t} с вне плана длиной {c.length:.2f} с")
        for s in c.subs:
            if s.t < 0 or s.t + s.dur > c.length + 1e-6:
                out.append(f"{tag}: субтитр «{s.text[:20]}…» выходит за план")
            if Path(FONT).exists() and text_width(s.text) > SUB_MAX_W:
                out.append(f"{tag}: субтитр «{s.text[:20]}…» шире кадра — разбить на два")
            if len(s.text) / max(s.dur, 0.1) > 20:
                out.append(f"{tag}: субтитр «{s.text[:20]}…» не успеть прочитать (>20 знаков/с)")
        if c.still and not (base / c.still).exists():
            out.append(f"{tag}: нет картинки {c.still}")
        for g in c.glitches:
            if g.t < 0 or g.t + g.dur > c.length + 1e-6:
                out.append(f"{tag}: сбой на {g.t} с выходит за план")
    for o in (*e.global_overlays, *([e.watermark] if e.watermark else [])):
        if not (base / o.img).exists():
            out.append(f"общий оверлей: нет файла {o.img}")
        if o.t < 0 or o.t >= e.length:
            out.append(f"общий оверлей {o.img} на {o.t} с вне ролика длиной {e.length:.2f} с")
    return out


def _overlay(idx: int, o: Overlay, cur: str, end: float, k: str) -> tuple[list[str], str]:
    """Входы ffmpeg и звено цепочки, кладущее графику `o` поверх `cur` до `end`."""
    if is_video(o.img):
        # анимация стартует в момент o.t; после последнего кадра держится он же
        # (у титров он пустой — они уходят сами, у плашки эфира — она остаётся)
        prep = f"[{idx}:v]format=rgba,setpts=PTS-STARTPTS+{o.t:.3f}/TB[g{k}]"
        lay = f"{cur}[g{k}]overlay=0:0:eof_action=repeat:enable='between(t,{o.t:.3f},{end:.3f})'"
        return [prep, lay], "video"
    prep = f"[{idx}:v]scale={W}:{H},format=rgba[g{k}]"
    lay = f"{cur}[g{k}]overlay=0:0:enable='between(t,{o.t:.3f},{end:.3f})'"
    return [prep, lay], "image"


def _esc(text: str) -> str:
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "’").replace("%", "\\%")


def _wrap(text: str, width: int) -> list[str]:
    """Первая строка — id плана, дальше назначение, по словам."""
    head, _, rest = text.partition("\n")
    lines, cur = [head], ""
    for word in rest.split():
        if cur and len(cur) + 1 + len(word) > width:
            lines.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        lines.append(cur)
    return lines


def _segment_cmd(
    c: Clip,
    src: Path | None,
    base: Path,
    out: Path,
    slate_text: str,
    fade_in: bool = True,
    fade_out: bool = True,
) -> list[str]:
    """Команда ffmpeg, собирающая один план в промежуточный файл единого формата."""
    length = c.length
    inputs: list[str] = []
    if c.still:
        if is_video(c.still):
            inputs += ["-t", f"{length:.3f}", *video_input(base / c.still)]
        else:
            inputs += ["-loop", "1", "-t", f"{length:.3f}", "-i", str(base / c.still)]
        inputs += ["-f", "lavfi", "-t", f"{length:.3f}", "-i", f"anullsrc=r={AR}:cl=stereo"]
        v, a = "[0:v]", "[1:a]"
        chain = [
            f"color=c=black:s={W}x{H}:r={FPS}:d={length:.3f}[bk];{v}scale={W}:{H},fps={FPS}[st];"
            "[bk][st]overlay=0:0:eof_action=repeat,format=yuv420p[v0]"
        ]
    elif src is None:
        inputs += [
            "-f",
            "lavfi",
            "-t",
            f"{length:.3f}",
            "-i",
            f"color=c=0x101010:s={W}x{H}:r={FPS}",
        ]
        inputs += ["-f", "lavfi", "-t", f"{length:.3f}", "-i", f"anullsrc=r={AR}:cl=stereo"]
        # drawtext не переносит строки сам: каждая строка слейта — свой фильтр
        lines = _wrap(slate_text, 30)[:6]
        draws = ",".join(
            f"drawtext=fontfile={FONT}:text='{_esc(line)}':fontcolor=0x9a9a9a:"
            f"fontsize={52 if k == 0 else 40}:x=(w-text_w)/2:y={760 + k * 64}"
            for k, line in enumerate(lines)
        )
        chain = [f"[0:v]{draws},format=yuv420p[v0]"]
        a = "[1:a]"
    else:
        inputs += ["-i", str(src)]
        cuts = [c.src_in, *sorted(h.t for h in c.holds), c.src_out]
        holds = sorted(c.holds, key=lambda h: h.t)
        parts_v, parts_a = [], []
        for k in range(len(cuts) - 1):
            a0, a1 = cuts[k], cuts[k + 1]
            pad = holds[k].dur if k < len(holds) else 0.0
            vt = f"[0:v]trim={a0:.3f}:{a1:.3f},setpts=PTS-STARTPTS"
            at = f"[0:a]atrim={a0:.3f}:{a1:.3f},asetpts=PTS-STARTPTS"
            if pad:
                vt += f",tpad=stop_mode=clone:stop_duration={pad:.3f}"
                at += f",apad=pad_dur={pad:.3f}"
            chain_v, chain_a = f"vp{k}", f"ap{k}"
            parts_v.append(f"{vt}[{chain_v}]")
            parts_a.append(f"{at}[{chain_a}]")
        n = len(parts_v)
        chain = parts_v + parts_a
        chain.append("".join(f"[vp{k}][ap{k}]" for k in range(n)) + f"concat=n={n}:v=1:a=1[vc][ac]")
        zh = round(H * c.zoom / 2) * 2
        chain.append(
            f"[vc]scale=-2:{zh}:flags=lanczos,crop={W}:{H}:(iw-{W})/2:(ih-{H})*{c.zoom_y:.3f},"
            f"fps={FPS},format=yuv420p[v0]"
        )
        a = "[ac]"
    # графика плана
    idx = sum(1 for x in inputs if x == "-i")
    cur = "[v0]"
    for k, g in enumerate(c.glitches):
        nxt = f"[gl{k}]"
        on = f"enable='between(t,{g.t:.3f},{g.t + g.dur:.3f})'"
        chain.append(f"{cur}rgbashift=rh=-18:bh=18:{on},noise=alls=45:allf=t:{on}{nxt}")
        cur = nxt
    for k, o in enumerate(c.overlays):
        if is_video(o.img):
            inputs += video_input(base / o.img)
        else:
            inputs += ["-loop", "1", "-t", f"{length:.3f}", "-i", str(base / o.img)]
        end = length if o.dur < 0 else min(length, o.t + o.dur)
        nxt = f"[vo{k}]"
        links, _ = _overlay(idx, o, cur, end, f"c{k}")
        chain += [links[0], links[1] + nxt]
        cur, idx = nxt, idx + 1
    for k, s in enumerate(c.subs):
        nxt = f"[vs{k}]"
        chain.append(
            f"{cur}drawtext=fontfile={FONT}:text='{_esc(s.text)}':fontcolor=white:fontsize={SUB_SIZE}:"
            f"box=1:boxcolor=black@0.55:boxborderw=18:x=(w-text_w)/2:y={SUB_Y}:"
            f"enable='between(t,{s.t:.3f},{s.t + s.dur:.3f})'{nxt}"
        )
        cur = nxt
    chain.append(f"{cur}null[vout]")
    # звук: нормализовать формат, громкость плана, эффекты
    chain.append(
        f"{a}aresample={AR},aformat=channel_layouts=stereo,volume={c.gain_db}dB,"
        f"apad=whole_dur={length:.3f},atrim=0:{length:.3f}[a0]"
    )
    mute = "".join(f",volume=0:enable='between(t,{m.t:.3f},{m.t + m.dur:.3f})'" for m in c.mutes)
    mix = ["[a0]"]
    for k, fx in enumerate(c.sfx):
        inputs += ["-i", str(base / fx.file)]
        ms = int(fx.t * 1000)
        chain.append(
            f"[{idx}:a]aresample={AR},aformat=channel_layouts=stereo,volume={fx.gain_db}dB,"
            f"adelay={ms}|{ms}[fx{k}]"
        )
        mix.append(f"[fx{k}]")
        idx += 1
    # край без ручки — короткий фейд от щелчка; край с ручкой — без фейда:
    # звук продолжается тем же исходником в ручке, фейд дал бы провал
    edges = ""
    if fade_in:
        edges += f",afade=t=in:d={EDGE_FADE}"
    if fade_out:
        edges += f",afade=t=out:st={max(0.0, length - EDGE_FADE):.3f}:d={EDGE_FADE}"
    chain.append(
        "".join(mix) + f"amix=inputs={len(mix)}:duration=first:normalize=0{edges}{mute}[aout]"
    )
    return [
        "ffmpeg",
        "-v",
        "error",
        "-y",
        *inputs,
        "-filter_complex",
        ";".join(chain),
        "-map",
        "[vout]",
        "-map",
        "[aout]",
        "-t",
        f"{length:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "16",
        "-c:a",
        "pcm_s16le",
        str(out),
    ]


def duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0


def handles(e: Edit, c: Clip, src_len: float) -> tuple[float, float]:
    """Сколько звука плана взять до входа и после выхода — в пределах исходника."""
    if c.still:
        return 0.0, 0.0
    lead = e.audio_lead if c.audio_lead is None else c.audio_lead
    tail = e.audio_tail if c.audio_tail is None else c.audio_tail
    return max(0.0, min(lead, c.src_in)), max(0.0, min(tail, src_len - c.src_out))


def assemble(
    e: Edit,
    base: Path,
    renders: dict[str, Path],
    purposes: dict[str, str],
    out: Path,
    watermark: bool = True,
) -> list[str]:
    """Собрать мастер. Возвращает список планов, ушедших в монтаж слейтом."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("нет ffmpeg")
    slates: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        segs = []
        # куски звука вокруг склеек: (исходник, с какой секунды исходника,
        # сколько, где в ролике, фейд «in»/«out», громкость плана)
        handle_parts: list[tuple[Path, float, float, float, str, float]] = []
        t0 = 0.0
        for i, c in enumerate(e.clips):
            src = renders.get(c.shot)
            if src is None and not c.still:
                slates.append(c.shot)
            lead, tail = handles(e, c, duration(src)) if src is not None else (0.0, 0.0)
            seg = Path(tmp) / f"seg{i:02d}.mkv"
            slate = f"{c.shot} · нет рендера\n{purposes.get(c.shot) or c.note}"
            cmd = _segment_cmd(c, src, base, seg, slate, fade_in=lead <= 0, fade_out=tail <= 0)
            subprocess.run(cmd, check=True)
            segs.append(seg)
            if src is not None and lead > 0:
                handle_parts.append((src, c.src_in - lead, lead, t0 - lead, "in", c.gain_db))
            if src is not None and tail > 0:
                handle_parts.append((src, c.src_out, tail, t0 + c.length, "out", c.gain_db))
            t0 += c.length
        lst = Path(tmp) / "list.txt"
        lst.write_text("".join(f"file '{s}'\n" for s in segs), encoding="utf-8")
        joined = Path(tmp) / "joined.mkv"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(lst)]
            + ["-c", "copy", str(joined)],
            check=True,
        )
        inputs = ["-i", str(joined)]
        chain, cur = [], "[0:v]"
        layers = list(e.global_overlays)
        if watermark and e.watermark:
            layers.append(e.watermark)
        for k, o in enumerate(layers):
            if is_video(o.img):
                inputs += video_input(base / o.img)
            else:
                inputs += ["-loop", "1", "-t", f"{e.length:.3f}", "-i", str(base / o.img)]
            end = e.length if o.dur < 0 else o.t + o.dur
            links, _ = _overlay(k + 1, o, cur, end, f"g{k}")
            chain += [links[0], links[1] + f"[go{k}]"]
            cur = f"[go{k}]"
        chain.append(f"{cur}format=yuv420p[vout]")
        mix = ["[0:a]"]
        for k, (hsrc, ss, dur, at, kind, gain) in enumerate(handle_parts):
            n = len([x for x in inputs if x == "-i"])
            inputs += ["-i", str(hsrc)]
            ms = max(0, int(at * 1000))
            fade = f"afade=t=in:d={dur:.3f}" if kind == "in" else f"afade=t=out:d={dur:.3f}"
            chain.append(
                f"[{n}:a]atrim={ss:.3f}:{ss + dur:.3f},asetpts=PTS-STARTPTS,aresample={AR},"
                f"aformat=channel_layouts=stereo,volume={gain}dB,{fade},adelay={ms}|{ms}[hd{k}]"
            )
            mix.append(f"[hd{k}]")
        for k, (b, end) in enumerate(zip(e.beds, e.bed_ends, strict=True)):
            n = len([x for x in inputs if x == "-i"])
            inputs += ["-stream_loop", "-1", "-i", str(base / b.file)]
            ms = int(b.t * 1000)
            dur = end - b.t
            chain.append(
                f"[{n}:a]aresample={AR},aformat=channel_layouts=stereo,atrim=0:{dur:.3f},"
                f"afade=t=out:st={max(0.0, dur - 0.15):.3f}:d=0.15,volume={b.gain_db}dB,"
                f"adelay={ms}|{ms}[bed{k}]"
            )
            mix.append(f"[bed{k}]")
        chain.append(
            "".join(mix)
            + f"amix=inputs={len(mix)}:duration=first:normalize=0,"
            + f"loudnorm=I={e.loudness_lufs}:TP={e.true_peak_db}:LRA=11,"
            f"alimiter=limit={10 ** (e.true_peak_db / 20):.4f},aresample={AR}[aout]"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", *inputs, "-filter_complex", ";".join(chain)]
            + ["-map", "[vout]", "-map", "[aout]", "-t", f"{e.length:.3f}"]
            + ["-c:v", "libx264", "-preset", "slow", "-crf", "18", "-profile:v", "high"]
            + ["-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
            + [str(out)],
            check=True,
        )
    return slates
