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
#: площадки, а 1080–1270 заняты нижними третями — субтитр между ними.
SUB_Y = 1300
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
class Clip:
    shot: str
    src_in: float
    src_out: float
    note: str = ""
    overlays: tuple[Overlay, ...] = ()
    subs: tuple[Sub, ...] = ()
    sfx: tuple[Sfx, ...] = ()
    holds: tuple[Hold, ...] = ()
    still: str = ""  # картинка вместо рендера (пэкшот)
    gain_db: float = 0.0

    @property
    def length(self) -> float:
        return self.src_out - self.src_in + sum(h.dur for h in self.holds)


@dataclass(frozen=True)
class Edit:
    clips: tuple[Clip, ...]
    global_overlays: tuple[Overlay, ...] = ()
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
        )
        for c in raw["clips"]
    )
    return Edit(
        clips=clips,
        global_overlays=ovs(raw.get("global_overlays", [])),
        loudness_lufs=float(raw.get("loudness_lufs", -14)),
        true_peak_db=float(raw.get("true_peak_db", -1)),
    )


def problems(e: Edit, base: Path, shots: set[str]) -> list[str]:
    """Что не так с листом до сборки. Отсутствующий рендер — не проблема, а слейт."""
    out: list[str] = []
    for i, c in enumerate(e.clips):
        tag = f"#{i + 1} {c.shot}"
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
    for o in e.global_overlays:
        if not (base / o.img).exists():
            out.append(f"общий оверлей: нет файла {o.img}")
    return out


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


def _segment_cmd(c: Clip, src: Path | None, base: Path, out: Path, slate_text: str) -> list[str]:
    """Команда ffmpeg, собирающая один план в промежуточный файл единого формата."""
    length = c.length
    inputs: list[str] = []
    if c.still:
        inputs += ["-loop", "1", "-t", f"{length:.3f}", "-i", str(base / c.still)]
        inputs += ["-f", "lavfi", "-t", f"{length:.3f}", "-i", f"anullsrc=r={AR}:cl=stereo"]
        v, a = "[0:v]", "[1:a]"
        chain = [f"{v}scale={W}:{H},fps={FPS},format=yuv420p[v0]"]
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
        chain.append(f"[vc]scale=-2:{H}:flags=lanczos,crop={W}:{H},fps={FPS},format=yuv420p[v0]")
        a = "[ac]"
    # графика плана
    idx = sum(1 for x in inputs if x == "-i")
    cur = "[v0]"
    for k, o in enumerate(c.overlays):
        inputs += ["-loop", "1", "-t", f"{length:.3f}", "-i", str(base / o.img)]
        end = length if o.dur < 0 else min(length, o.t + o.dur)
        nxt = f"[vo{k}]"
        chain.append(
            f"[{idx}:v]scale={W}:{H}[g{k}];{cur}[g{k}]overlay=0:0:"
            f"enable='between(t,{o.t:.3f},{end:.3f})'{nxt}"
        )
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
    fade_out = max(0.0, length - EDGE_FADE)
    chain.append(
        "".join(mix)
        + f"amix=inputs={len(mix)}:duration=first:normalize=0,"
        + f"afade=t=in:d={EDGE_FADE},afade=t=out:st={fade_out:.3f}:d={EDGE_FADE}[aout]"
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


def assemble(
    e: Edit,
    base: Path,
    renders: dict[str, Path],
    purposes: dict[str, str],
    out: Path,
) -> list[str]:
    """Собрать мастер. Возвращает список планов, ушедших в монтаж слейтом."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("нет ffmpeg")
    slates: list[str] = []
    with tempfile.TemporaryDirectory() as tmp:
        segs = []
        for i, c in enumerate(e.clips):
            src = renders.get(c.shot)
            if src is None and not c.still:
                slates.append(c.shot)
            seg = Path(tmp) / f"seg{i:02d}.mkv"
            slate = f"{c.shot} · нет рендера\n{purposes.get(c.shot) or c.note}"
            subprocess.run(_segment_cmd(c, src, base, seg, slate), check=True)
            segs.append(seg)
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
        for k, o in enumerate(e.global_overlays):
            inputs += ["-loop", "1", "-i", str(base / o.img)]
            end = e.length if o.dur < 0 else o.t + o.dur
            chain.append(
                f"[{k + 1}:v]scale={W}:{H}[gg{k}];{cur}[gg{k}]overlay=0:0:shortest=1:"
                f"enable='between(t,{o.t:.3f},{end:.3f})'[go{k}]"
            )
            cur = f"[go{k}]"
        chain.append(f"{cur}format=yuv420p[vout]")
        chain.append(
            f"[0:a]loudnorm=I={e.loudness_lufs}:TP={e.true_peak_db}:LRA=11,"
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
