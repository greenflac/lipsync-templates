"""Раскодировщик видео: mp4 -> кадры PNG."""

from __future__ import annotations

import json
import math
import shutil
import subprocess
import time
from pathlib import Path

from . import framemath
from .fork_identity import FAIL, PASS, UNMEASURED

FFPROBE_BIN = "ffprobe"
FFMPEG_BIN = "ffmpeg"

PROBE_TIMEOUT_S = 20

DECODE_TIMEOUT_S = 600

NAME_DIGITS = 5

FRAME_SUFFIX = ".png"

FRAME_COUNT_TOLERANCE = 1

FPS_TOLERANCE = 0.01

AS_IS, DROP, REFUSE = "как есть", "прорежаем", "отказ"

EXIT_BY_OUTCOME = {PASS: 0, FAIL: 1, UNMEASURED: 2}


def read_probe(path) -> dict:
    """Спросить у ffprobe метаданные. ТОЧКА ВНЕДРЕНИЯ: тест подменяет целиком."""
    if shutil.which(FFPROBE_BIN) is None:
        return {"ran": False, "code": None, "out": "", "err": "",
                "why": (f"{FFPROBE_BIN} не найден: спросить нечем. Это НЕ "
                        f"«файл плохой» — утилита ставится пакетом ffmpeg")}
    try:
        raw = subprocess.run(
            [FFPROBE_BIN, "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", str(path)],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_S)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ran": False, "code": None, "out": "", "err": "",
                "why": f"{FFPROBE_BIN} не отработал: {str(exc)[:120]}"}
    return {"ran": True, "code": raw.returncode, "out": raw.stdout or "",
            "err": raw.stderr or "", "why": ""}


def run_decode(argv) -> dict:
    """Раскодировать. ТОЧКА ВНЕДРЕНИЯ: тест подменяет целиком."""
    if shutil.which(FFMPEG_BIN) is None:
        return {"ran": False, "code": None, "out": "", "err": "",
                "why": (f"{FFMPEG_BIN} не найден: раскодировать нечем. Это НЕ "
                        f"«видео плохое»")}
    try:
        raw = subprocess.run(argv, capture_output=True, text=True,
                             timeout=DECODE_TIMEOUT_S)
    except subprocess.TimeoutExpired:
        return {"ran": False, "code": None, "out": "", "err": "",
                "why": (f"{FFMPEG_BIN} не уложился в {DECODE_TIMEOUT_S} с и "
                        f"убит: раскодировано неизвестно сколько")}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ran": False, "code": None, "out": "", "err": "",
                "why": f"{FFMPEG_BIN} не отработал: {str(exc)[:120]}"}
    return {"ran": True, "code": raw.returncode, "out": raw.stdout or "",
            "err": raw.stderr or "", "why": ""}


def frame_name(index: int) -> str:
    """Имя кадра. Ширина поля — константа, а не литерал в двух местах."""
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise ValueError(f"номер кадра {index!r}: ожидалось целое от нуля")
    return f"{index:0{NAME_DIGITS}d}{FRAME_SUFFIX}"


def _ratio(raw) -> float | None:
    """`30000/1001` -> 29.97003. Кривое или нулевое — `None`, а не догадка."""
    if raw is None:
        return None
    try:
        num, _, den = str(raw).partition("/")
        value = float(num) / float(den or 1)
    except (ValueError, ZeroDivisionError):
        return None
    return value if value > 0 else None


def parse_probe(text: str) -> dict:
    """Разбор JSON от ffprobe в наши поля. Чистая функция, тест — на литерале."""
    try:
        data = json.loads(text or "")
    except (ValueError, TypeError):
        return {"ok": False, "why": f"ответ ffprobe не разобрался как JSON: "
                                    f"{(text or '')[:120]!r}"}
    if not isinstance(data, dict):
        return {"ok": False, "why": f"ждали объект, пришло {type(data).__name__}"}
    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = any(s.get("codec_type") == "audio" for s in streams)
    if video is None:
        return {"ok": False, "audio": audio,
                "why": (f"видеопотока в файле нет (потоков всего "
                        f"{len(streams)}, звуковых {'есть' if audio else 'нет'})")}
    fps = _ratio(video.get("avg_frame_rate")) or _ratio(video.get("r_frame_rate"))
    try:
        seconds = float(video.get("duration")
                        or (data.get("format") or {}).get("duration"))
    except (TypeError, ValueError):
        seconds = None
    nb = video.get("nb_frames")
    frames = frames_from = None
    try:
        if nb is not None and int(nb) > 0:
            frames, frames_from = int(nb), "nb_frames"
    except (TypeError, ValueError):
        frames = None
    if frames is None and fps and seconds:
        frames, frames_from = int(round(seconds * fps)), "длительность x частота"
    return {
        "ok": True, "why": "", "fps": fps, "frames": frames,
        "frames_from": frames_from, "seconds": seconds,
        "width": video.get("width"), "height": video.get("height"),
        "audio": audio, "codec": video.get("codec_name"),
    }


def fps_plan(source_fps, *, want=None) -> dict:
    """Что делаем с частотой. Три ветки, и молчаливого приведения среди них нет."""
    if source_fps is None:
        return {"outcome": UNMEASURED, "mode": REFUSE, "fps": None,
                "note": ("частота исходника не снята — решать про приведение "
                         "не из чего. Это НЕ «берём как есть»: как есть — это "
                         "тоже решение, и оно требует знать, что есть")}
    if want is None:
        return {"outcome": PASS, "mode": AS_IS, "fps": source_fps,
                "note": (f"частота исходника {source_fps:g} к/с, кадры берутся "
                         f"ВСЕ, приведения нет. Число кадров равно числу "
                         f"кадров в файле")}
    if (not isinstance(want, (int, float)) or isinstance(want, bool)
            or not math.isfinite(want) or want <= 0):
        return {"outcome": FAIL, "mode": REFUSE, "fps": None,
                "note": f"частота {want!r}: ожидалось положительное конечное число"}
    if abs(want - source_fps) <= FPS_TOLERANCE:
        return {"outcome": PASS, "mode": AS_IS, "fps": source_fps,
                "note": (f"запрошено {want:g} к/с при исходных {source_fps:g} — "
                         f"это одно и то же в пределах допуска "
                         f"{FPS_TOLERANCE}, ничего не трогаем")}
    if want > source_fps:
        return {"outcome": FAIL, "mode": REFUSE, "fps": None,
                "note": (f"запрошено {want:g} к/с при исходных {source_fps:g}: "
                         f"ВВЕРХ НЕ ПРИВОДИМ. Интерполяции нет по решению "
                         f"составителя шаблонов ({want:g} - {source_fps:g} = "
                         f"{want - source_fps:g} к/с пришлось бы выдумать), а "
                         f"выдуманный кадр в драйвинге — это выдуманное "
                         f"движение. Снимать драйвинг не ниже "
                         f"{framemath.WRAP_FPS} к/с — требование к съёмке")}
    return {"outcome": PASS, "mode": DROP, "fps": float(want),
            "note": (f"прорежаем {source_fps:g} -> {want:g} к/с. ДЛИНА В "
                     f"КАДРАХ МЕНЯЕТСЯ: на секунду выйдет {want:g} кадров "
                     f"вместо {source_fps:g}, и число окон сэмплера считается "
                     f"уже по новому числу")}


def expected_frames(source_frames, *, source_fps=None, out_fps=None,
                    limit=None) -> int | None:
    """Сколько кадров ОБЯЗАНО лечь на диск. `None` — если считать не из чего."""
    if source_frames is None:
        return None
    n = int(source_frames)
    if out_fps is not None and source_fps and abs(out_fps - source_fps) > FPS_TOLERANCE:
        n = int(round(n * out_fps / source_fps))
    if limit is not None:
        n = min(n, int(limit))
    return max(n, 0)


def count_outcome(expected, written: int) -> dict:
    """Вердикт по числам кадров. Чистая функция — тест кормит её литералами."""
    if written < 0:
        raise ValueError(f"записано {written}: отрицательных кадров не бывает")
    if written == 0:
        return {"outcome": FAIL,
                "note": ("кадров записано 0 — это НЕ успех, а отсутствие "
                         "результата: судить и анимировать нечем")}
    if expected is None:
        return {"outcome": UNMEASURED,
                "note": (f"записано {written} кадров, но метаданные не сказали, "
                         f"сколько их в файле — подтвердить полноту нечем")}
    diff = abs(written - int(expected))
    if diff <= FRAME_COUNT_TOLERANCE:
        return {"outcome": PASS,
                "note": (f"ожидалось {expected}, записано {written} "
                         f"(расхождение {diff}, допуск {FRAME_COUNT_TOLERANCE} "
                         f"— это округление, а не потеря)")}
    return {"outcome": UNMEASURED,
            "note": (f"ожидалось {expected}, записано {written}: расхождение "
                     f"{diff} больше допуска {FRAME_COUNT_TOLERANCE}. "
                     f"Раскодировано что-то, но что именно — метаданные не "
                     f"подтверждают. Это НЕ «годно»")}


def decode_argv(video_path, out_dir, *, out_fps=None, limit=None) -> list:
    """Команда раскодирования. Собирается отдельно — состав команды это решение."""
    argv = [FFMPEG_BIN, "-nostdin", "-v", "error", "-i", str(video_path)]
    if out_fps is not None:
        argv += ["-vf", f"fps={out_fps:g}"]
    argv += ["-fps_mode", "passthrough", "-start_number", "0"]
    if limit is not None:
        argv += ["-frames:v", str(int(limit))]
    argv.append(str(Path(out_dir) / f"%0{NAME_DIGITS}d{FRAME_SUFFIX}"))
    return argv


def probe(video_path, *, prober=None) -> dict:
    """Метаданные видео. Три исхода, числа рядом с вердиктом."""
    prober = read_probe if prober is None else prober
    t = time.perf_counter()
    p = Path(video_path)
    if not p.exists():
        return _probe_report(FAIL, f"файла нет: {p}", t)
    if p.is_dir():
        return _probe_report(
            FAIL, f"{p} — это КАТАЛОГ, а не видеофайл. Кадры в каталоге "
                  f"раскодировать не надо: их надо подавать как есть", t)
    size = p.stat().st_size
    if size == 0:
        return _probe_report(FAIL, f"{p}: файл пустой, 0 байт", t)

    raw = prober(p)
    if not raw.get("ran"):
        return _probe_report(UNMEASURED, raw.get("why") or "спросить нечем", t)
    if raw.get("code"):
        return _probe_report(
            FAIL, f"{FFPROBE_BIN} вернул {raw['code']}: "
                  f"{(raw.get('err') or '').strip()[:200] or 'без объяснения'}", t)
    parsed = parse_probe(raw.get("out") or "")
    if not parsed.get("ok"):
        return _probe_report(FAIL, parsed.get("why", "ответ не разобран"), t,
                             **({"audio": parsed["audio"]}
                                if "audio" in parsed else {}))
    rep = _probe_report(
        PASS,
        (f"{parsed['width']}x{parsed['height']}, {parsed['fps']:g} к/с, "
         f"кадров {parsed['frames']} (по «{parsed['frames_from']}»), "
         f"{parsed['seconds']:g} с, звук "
         f"{'есть' if parsed['audio'] else 'нет'}, кодек {parsed['codec']}")
        if parsed.get("fps") and parsed.get("seconds") is not None else
        (f"метаданные разобрались не полностью: частота {parsed.get('fps')}, "
         f"кадров {parsed.get('frames')}, длительность {parsed.get('seconds')}"),
        t, **{k: parsed[k] for k in
              ("fps", "frames", "frames_from", "seconds", "width", "height",
               "audio", "codec")})
    if rep["fps"] is None or rep["frames"] is None:
        rep["outcome"] = UNMEASURED
    rep["bytes"] = size
    return rep


def _probe_report(outcome: str, note: str, t0: float, **extra) -> dict:
    rep = {"outcome": outcome, "note": note, "fps": None, "frames": None,
           "frames_from": None, "seconds": None, "width": None, "height": None,
           "audio": None, "codec": None, "bytes": None,
           "elapsed": round(time.perf_counter() - t0, 4)}
    rep.update(extra)
    return rep


def fps_prober(path):
    """Частота исходника как одно число. Совместимая замена `_ffprobe_fps`."""
    rep = probe(path)
    return rep["fps"] if rep["outcome"] == PASS else None


def plan_for_seconds(seconds, *, fps=None) -> dict:
    """Сколько кадров драйвинга нужно под ролик такой длины."""
    return framemath.frames_for_seconds(seconds, fps=fps)


def frames(video_path, out_dir, *, fps=None, limit=None, overwrite=False,
           prober=None, decoder=None) -> dict:
    """Раскодировать видео в PNG. Три исхода, числа рядом с вердиктом."""
    prober = read_probe if prober is None else prober
    decoder = run_decode if decoder is None else decoder
    t = time.perf_counter()
    steps = []

    if limit is not None:
        if not isinstance(limit, int) or isinstance(limit, bool) or limit < 1:
            return _frames_report(FAIL, f"limit={limit!r}: ожидалось целое от 1",
                                  t, steps)

    meta = probe(video_path, prober=prober)
    steps.append(("метаданные", meta["outcome"], meta["note"], meta["elapsed"]))
    if meta["outcome"] != PASS:
        return _frames_report(meta["outcome"], meta["note"], t, steps, meta=meta)

    plan = fps_plan(meta["fps"], want=fps)
    steps.append(("частота", plan["outcome"], plan["note"], 0.0))
    if plan["outcome"] != PASS:
        return _frames_report(plan["outcome"], plan["note"], t, steps, meta=meta,
                              plan=plan)

    want = plan["fps"] if plan["mode"] == DROP else None
    expected = expected_frames(meta["frames"], source_fps=meta["fps"],
                               out_fps=want, limit=limit)

    out = Path(out_dir)
    if out.exists() and not out.is_dir():
        return _frames_report(FAIL, f"{out} — не каталог", t, steps, meta=meta,
                              plan=plan, expected=expected)
    already = sorted(out.glob(f"*{FRAME_SUFFIX}")) if out.is_dir() else []
    present = len(already)
    present_bytes = sum(f.stat().st_size for f in already)
    if already and not overwrite:
        note = (f"в {out} уже лежит кадров: {present} (первый "
                f"{already[0].name}, последний {already[-1].name}, байт "
                f"{present_bytes}). Молча поверх не пишем: раскодировав 60 "
                f"кадров поверх 320, мы получили бы каталог из 260 чужих и 60 "
                f"своих — отсортованный и правдоподобный. Мы НЕ ПИСАЛИ ни "
                f"одного кадра: эти {present} — чужие. Задайте overwrite=True "
                f"или другой каталог")
        steps.append(("каталог", UNMEASURED, note, 0.0))
        return _frames_report(UNMEASURED, note, t, steps, meta=meta, plan=plan,
                              expected=expected, present=present,
                              present_bytes=present_bytes)
    if already and overwrite:
        for f in already:
            f.unlink()
    out.mkdir(parents=True, exist_ok=True)

    argv = decode_argv(video_path, out, out_fps=want, limit=limit)
    t_dec = time.perf_counter()
    got = decoder(argv)
    dec_elapsed = round(time.perf_counter() - t_dec, 4)
    written_paths = sorted(out.glob(f"*{FRAME_SUFFIX}"))
    written = len(written_paths)
    size = sum(p.stat().st_size for p in written_paths)

    if not got.get("ran"):
        note = (f"{got.get('why') or 'раскодировать нечем'}. Успело лечь "
                f"кадров: {written}, ожидалось {expected}")
        steps.append(("раскодирование", UNMEASURED, note, dec_elapsed))
        return _frames_report(UNMEASURED, note, t, steps, meta=meta, plan=plan,
                              expected=expected, written=written, nbytes=size,
                              paths=written_paths, present=present,
                              present_bytes=present_bytes)
    if got.get("code"):
        note = (f"{FFMPEG_BIN} вернул {got['code']}: "
                f"{(got.get('err') or '').strip()[:200] or 'без объяснения'}. "
                f"Кадров записано {written}, ожидалось {expected}")
        steps.append(("раскодирование", FAIL, note, dec_elapsed))
        return _frames_report(FAIL, note, t, steps, meta=meta, plan=plan,
                              expected=expected, written=written, nbytes=size,
                              paths=written_paths, present=present,
                              present_bytes=present_bytes)
    steps.append(("раскодирование", PASS,
                  f"{FFMPEG_BIN} отработал, код 0", dec_elapsed))

    verdict = count_outcome(expected, written)
    steps.append(("кадры", verdict["outcome"], verdict["note"], 0.0))
    return _frames_report(verdict["outcome"], verdict["note"], t, steps,
                          meta=meta, plan=plan, expected=expected,
                          written=written, nbytes=size, paths=written_paths,
                          present=present, present_bytes=present_bytes)


DIR_UNSEEN = "каталог назначения не осматривали"
DIR_EMPTY = "каталог назначения был пуст"


def _dir_fact(present, present_bytes) -> str:
    """Фраза про каталог назначения. Выведена из того, что ИСПОЛНИЛОСЬ."""
    if present is None:
        return DIR_UNSEEN
    if present == 0:
        return DIR_EMPTY
    return (f"до нас в каталоге лежало кадров {present}, "
            f"байт {0 if present_bytes is None else present_bytes}")


def _frames_report(outcome: str, note: str, t0: float, steps, *, meta=None,
                   plan=None, expected=None, written=0, nbytes=0,
                   paths=None, present=None, present_bytes=None) -> dict:
    """Один отчёт на все исходы."""
    elapsed = round(time.perf_counter() - t0, 4)
    paths = list(paths or [])
    return {
        "outcome": outcome,
        "expected": expected, "written": written, "bytes": nbytes,
        "present": present, "present_bytes": present_bytes,
        "elapsed": elapsed,
        "fps_in": (meta or {}).get("fps"), "fps_out": (plan or {}).get("fps"),
        "mode": (plan or {}).get("mode"),
        "paths": paths,
        "steps": [{"step": s, "outcome": o, "note": n, "seconds": round(e, 4)}
                  for s, o, n, e in steps],
        "note": (f"{outcome}: {note}. Ожидалось кадров "
                 f"{'неизвестно' if expected is None else expected}, записано "
                 f"нами {written}, байт {nbytes}, "
                 f"{_dir_fact(present, present_bytes)}, за {elapsed} с"),
    }


def main(argv=None) -> int:
    """`python3 -m lipsync.fork_video probe|frames ...`."""
    import argparse

    ap = argparse.ArgumentParser(
        prog="fork_video", description="раскодировщик видео")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p1 = sub.add_parser("probe", help="метаданные видео")
    p1.add_argument("video")
    p2 = sub.add_parser("frames", help="раскодировать в PNG")
    p2.add_argument("video")
    p2.add_argument("out_dir")
    p2.add_argument("--fps", type=float, default=None,
                    help="привести частоту ВНИЗ; без него берётся как есть")
    p2.add_argument("--limit", type=int, default=None)
    p2.add_argument("--overwrite", action="store_true")
    args = ap.parse_args(argv)

    if args.cmd == "probe":
        rep = probe(args.video)
        print(f"{rep['outcome']:20s} {rep['note']}")
    else:
        rep = frames(args.video, args.out_dir, fps=args.fps, limit=args.limit,
                     overwrite=args.overwrite)
        for s in rep["steps"]:
            print(f"{s['outcome']:20s} {s['step']:15s} {s['seconds']:7.3f} с  "
                  f"{s['note']}")
        print(rep["note"])
    return EXIT_BY_OUTCOME[rep["outcome"]]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
