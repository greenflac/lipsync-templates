"""Финальная сборка ролика после Kling: кроп в 9:16 плюс возврат звука."""

from __future__ import annotations

import time
from pathlib import Path

from . import fork_video
from .fork_identity import FAIL, PASS, UNMEASURED


#: ВЫБРАНО (составителем шаблонов, из вертикальных форматов площадок): 9:16 — кадр ленты.
TARGET_RATIO_W, TARGET_RATIO_H = 9, 16

#: РАСЧЁТ (по устройству yuv420p): цветность прорежена вдвое, стороны обязаны быть чётными.
DIM_MULTIPLE = 2

#: РАСЧЁТ (не наш замер: ITU-R BT.1359-1): звук впереди картинки заметен с 45 мс; берётся узкая сторона, знак сдвига неизвестен по построению.
LIPSYNC_AUDIO_AHEAD_MS = 45

#: ВЫБРАНО из ИЗМЕРЕННОГО: лучшее окно на живом материале набирает 1.0024 от центрального — это шум; ниже опускать нельзя.
BIAS_GAIN_MIN = 1.05

#: ВЫБРАНО: смещение окна — доля от -1 до +1, не пиксели (разрешение выхода уже менялось).
BIAS_LIMIT = 1.0

#: ВЫБРАНО: CRF 18 у x264 визуально почти без потерь; звук в aac 128k, copy при резке кладёт лишний кусок.
VIDEO_CRF = 18
VIDEO_PRESET = "veryfast"
AUDIO_BITRATE = "128k"

EXIT_BY_OUTCOME = fork_video.EXIT_BY_OUTCOME


def _even(value: int) -> int:
    """Вниз до кратного DIM_MULTIPLE. Вниз, а не вверх: вверх — выйти за кадр."""
    return int(value) - int(value) % DIM_MULTIPLE


def crop_geometry(width, height, *, ratio_w=TARGET_RATIO_W,
                  ratio_h=TARGET_RATIO_H, bias=0.0) -> dict:
    """План кропа: откуда и какое окно резать, и сколько площади теряем."""
    if width is None or height is None:
        return {**_geom_blank(), "outcome": UNMEASURED,
                "note": (f"размеры кадра не сняты (ширина {width}, высота "
                         f"{height}): резать вслепую нечего")}
    for name, value in (("ширина", width), ("высота", height)):
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            return {**_geom_blank(), "outcome": FAIL,
                    "note": f"{name} кадра бессмысленна: {value!r}"}
    if not (isinstance(ratio_w, int) and isinstance(ratio_h, int)
            and ratio_w > 0 and ratio_h > 0):
        return {**_geom_blank(), "outcome": FAIL,
                "note": f"соотношение сторон бессмысленно: {ratio_w}:{ratio_h}"}
    try:
        bias = float(bias)
    except (TypeError, ValueError):
        return {**_geom_blank(), "outcome": FAIL,
                "note": f"смещение не число: {bias!r}"}
    if not -BIAS_LIMIT <= bias <= BIAS_LIMIT:
        return {**_geom_blank(), "outcome": FAIL,
                "note": (f"смещение {bias:g} вне полосы "
                         f"[{-BIAS_LIMIT:g}; {BIAS_LIMIT:g}]")}

    src, want = width * ratio_h, height * ratio_w
    if src > want:
        w, h, axis = _even(height * ratio_w // ratio_h), _even(height), "по ширине"
    elif src < want:
        w, h, axis = _even(width), _even(width * ratio_h // ratio_w), "по высоте"
    else:
        w, h, axis = _even(width), _even(height), "ничего не режем"
    if w < DIM_MULTIPLE or h < DIM_MULTIPLE:
        return {**_geom_blank(), "outcome": FAIL,
                "note": (f"окно {w}x{h} вырождено: из {width}x{height} "
                         f"соотношение {ratio_w}:{ratio_h} не набирается")}

    free_x, free_y = width - w, height - h
    x = _even(round((bias + 1) / 2 * free_x))
    y = _even(round((bias + 1) / 2 * free_y)) if free_y else 0
    x, y = min(x, _even(free_x)), min(y, _even(free_y))
    kept = 100.0 * (w * h) / (width * height)
    lost = 100.0 - kept
    return {
        "outcome": PASS, "x": x, "y": y, "w": w, "h": h,
        "lost_percent": round(lost, 2), "kept_percent": round(kept, 2),
        "axis": axis,
        "note": (f"из {width}x{height} режем {w}x{h} {axis} со смещением "
                 f"{bias:+.2f} (окно x={x}, y={y}); остаётся "
                 f"{round(kept, 2):g}% площади, теряется "
                 f"{round(lost, 2):g}%"),
    }


def _geom_blank() -> dict:
    return {"x": None, "y": None, "w": None, "h": None, "lost_percent": None,
            "kept_percent": None, "axis": None}


def bias_from_columns(columns, *, ratio_w=TARGET_RATIO_W,
                      ratio_h=TARGET_RATIO_H) -> dict:
    """Смещение окна по поколоночной карте движения. Прибор с негативным контролем."""
    if columns is None:
        return {"outcome": UNMEASURED, "bias": 0.0, "gain": None,
                "note": "карты движения нет: смещать нечем, берём центр"}
    try:
        cols = [float(c) for c in columns]
    except (TypeError, ValueError):
        return {"outcome": FAIL, "bias": 0.0, "gain": None,
                "note": "карта движения не разбирается в числа"}
    if any(c < 0 for c in cols):
        return {"outcome": FAIL, "bias": 0.0, "gain": None,
                "note": "в карте движения отрицательные значения"}
    width = len(cols)
    win = round(width * ratio_w / ratio_h)
    if width < 2 or win < 1 or win >= width:
        return {"outcome": UNMEASURED, "bias": 0.0, "gain": None,
                "note": (f"выбирать не из чего: колонок {width}, окно {win} — "
                         f"смещения не существует, берём центр")}
    if sum(cols) <= 0:
        return {"outcome": UNMEASURED, "bias": 0.0, "gain": None,
                "note": (f"движения в кадре нет вовсе (сумма карты 0 по "
                         f"{width} колонкам): выбирать не по чему, берём центр")}
    sums = [sum(cols[i:i + win]) for i in range(width - win + 1)]
    best = max(range(len(sums)), key=lambda i: sums[i])
    center = (width - win) // 2
    gain = sums[best] / sums[center] if sums[center] > 0 else float("inf")
    if gain < BIAS_GAIN_MIN:
        return {"outcome": UNMEASURED, "bias": 0.0, "gain": round(gain, 4),
                "note": (f"карта движения ровная: лучшее окно (x={best}) "
                         f"выигрывает у центрального (x={center}) всего "
                         f"{round(gain, 4)}x при пороге {BIAS_GAIN_MIN} — "
                         f"это шум, а не человек сбоку. Берём центр")}
    bias = (best / (width - win)) * 2 - 1
    return {"outcome": PASS, "bias": round(bias, 3), "gain": round(gain, 4),
            "note": (f"движение стоит на окне x={best} из {width - win} "
                     f"возможных (смещение {bias:+.3f}), выигрыш у центра "
                     f"{round(gain, 4)}x при пороге {BIAS_GAIN_MIN}")}


def window_frames(first, last) -> dict:
    """Сколько кадров в окне [first..last]. ОБЕ ГРАНИЦЫ ВКЛЮЧИТЕЛЬНО."""
    if first is None or last is None:
        return {"outcome": UNMEASURED, "frames": None,
                "note": f"границы окна не заданы: [{first}..{last}]"}
    if not all(isinstance(v, int) and not isinstance(v, bool)
               for v in (first, last)):
        return {"outcome": FAIL, "frames": None,
                "note": f"границы окна не целые: [{first!r}..{last!r}]"}
    if first < 0:
        return {"outcome": FAIL, "frames": None,
                "note": f"начало окна отрицательное: {first}"}
    if last < first:
        return {"outcome": FAIL, "frames": None,
                "note": f"конец окна {last} раньше начала {first}"}
    return {"outcome": PASS, "frames": last - first + 1,
            "note": f"окно [{first}..{last}] включительно — "
                    f"{last - first + 1} кадров"}


def drift_tolerance_frames(fps):
    """Допуск рассинхрона в КАДРАХ на данной частоте. Физика — в миллисекундах."""
    if fps is None:
        return None
    try:
        fps = float(fps)
    except (TypeError, ValueError):
        return None
    if fps <= 0:
        return None
    return int(LIPSYNC_AUDIO_AHEAD_MS * fps / 1000)


def audio_drift(expected_frames, actual_frames, *, fps) -> dict:
    """Сверка ожидаемой длины окна с фактической длиной выхода Kling."""
    tol = drift_tolerance_frames(fps)
    blank = {"glue": False, "drift_frames": None, "drift_ms": None,
             "tolerance": tol, "expected": expected_frames,
             "actual": actual_frames}
    if tol is None:
        return {**blank, "outcome": UNMEASURED,
                "note": (f"частота не снята ({fps!r}): перевести кадры в "
                         f"миллисекунды нечем, судить о губах не по чему")}
    if expected_frames is None or actual_frames is None:
        return {**blank, "outcome": UNMEASURED,
                "note": (f"длительность не читается: окно {expected_frames}, "
                         f"выход {actual_frames} кадров")}
    if expected_frames <= 0 or actual_frames <= 0:
        return {**blank, "outcome": FAIL,
                "note": (f"кадров не может быть {expected_frames} и "
                         f"{actual_frames}")}
    drift = int(actual_frames) - int(expected_frames)
    ms = round(drift / float(fps) * 1000, 1)
    side = ("ДЛИННЕЕ" if drift > 0 else "КОРОЧЕ")
    common = {**blank, "drift_frames": drift, "drift_ms": ms}
    if drift == 0:
        return {**common, "outcome": PASS, "glue": True,
                "note": (f"кадр в кадр: окно {expected_frames}, выход "
                         f"{actual_frames}, расхождение 0 — звук клеится "
                         f"как есть")}
    if abs(drift) <= tol:
        return {**common, "outcome": PASS, "glue": True,
                "note": (f"выход {side} окна на {abs(drift)} кадр(ов) "
                         f"({abs(ms):g} мс): окно {expected_frames}, выход "
                         f"{actual_frames}. Допуск {tol} кадр(ов) при "
                         f"{float(fps):g} к/с — звук клеится, но сдвиг губ до "
                         f"{abs(ms):g} мс возможен, потому что где именно "
                         f"Kling потерял кадр, неизвестно")}
    return {**common, "outcome": FAIL, "glue": False,
            "note": (f"выход {side} окна на {abs(drift)} кадр(ов) "
                     f"({abs(ms):g} мс) при допуске {tol}: окно "
                     f"{expected_frames}, выход {actual_frames}. Звук НЕ "
                     f"клеится — молча уехавшие губы хуже немого ролика")}


def mux_argv(kling_path, out_path, geom, *, driving_path=None,
             start_seconds=None, seconds=None) -> list:
    """Команда сборки. Собирается ОТДЕЛЬНО от запуска: состав команды — решение."""
    argv = [fork_video.FFMPEG_BIN, "-nostdin", "-v", "error", "-y",
            "-i", str(kling_path)]
    with_audio = driving_path is not None
    if with_audio:
        if start_seconds is not None:
            argv += ["-ss", f"{float(start_seconds):.6f}"]
        if seconds is not None:
            argv += ["-t", f"{float(seconds):.6f}"]
        argv += ["-i", str(driving_path)]
    argv += ["-filter_complex",
             f"[0:v]crop={geom['w']}:{geom['h']}:{geom['x']}:{geom['y']}[v]",
             "-map", "[v]"]
    if with_audio:
        argv += ["-map", "1:a", "-c:a", "aac", "-b:a", AUDIO_BITRATE,
                 "-shortest"]
    else:
        argv += ["-an"]
    argv += ["-c:v", "libx264", "-preset", VIDEO_PRESET, "-crf", str(VIDEO_CRF),
             "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out_path)]
    return argv


def audio_plan(driving_path, window, kling_path, *, prober=None) -> dict:
    """Можно ли вернуть звук и с каким сдвигом. Ни один шаг не молчит."""
    t = time.perf_counter()
    steps = []
    drv = fork_video.probe(driving_path, prober=prober)
    steps.append(("опрос драйвинга", drv["outcome"], drv["note"]))
    kln = fork_video.probe(kling_path, prober=prober)
    steps.append(("опрос выхода Kling", kln["outcome"], kln["note"]))
    win = window_frames(*window)
    steps.append(("окно", win["outcome"], win["note"]))

    out = {"steps": steps, "glue": False, "drift_frames": None,
           "drift_ms": None, "tolerance": None, "expected": win["frames"],
           "actual": kln.get("frames"), "fps": drv.get("fps"),
           "start_seconds": None, "seconds": None,
           "elapsed": round(time.perf_counter() - t, 4)}

    if UNMEASURED in (drv["outcome"], kln["outcome"]):
        return {**out, "outcome": UNMEASURED,
                "note": "метаданные не сняты, судить о звуке не по чему"}
    if FAIL in (drv["outcome"], kln["outcome"], win["outcome"]):
        return {**out, "outcome": FAIL,
                "note": "материал не годится: см. шаги выше"}
    if win["outcome"] == UNMEASURED:
        return {**out, "outcome": UNMEASURED, "note": win["note"]}
    if not drv.get("audio"):
        return {**out, "outcome": FAIL,
                "note": (f"в драйвинге {driving_path} НЕТ звуковой дорожки — "
                         f"возвращать нечего. Это не сбой сборки, это не тот "
                         f"файл: окно резалось из ролика СО звуком")}
    fps = drv.get("fps")
    kfps = kln.get("fps")
    if kfps is not None and abs(float(kfps) - float(fps)) > fork_video.FPS_TOLERANCE:
        return {**out, "outcome": FAIL,
                "note": (f"частоты разошлись: драйвинг {float(fps):g} к/с, "
                         f"выход Kling {float(kfps):g} к/с. Сравнивать длины "
                         f"В КАДРАХ при разных частотах нельзя — кадр значит "
                         f"разное время")}
    if win["frames"] is not None and drv.get("frames") is not None:
        if window[1] >= drv["frames"]:
            return {**out, "outcome": FAIL,
                    "note": (f"окно [{window[0]}..{window[1]}] выходит за "
                             f"драйвинг: в нём {drv['frames']} кадров "
                             f"(последний номер {drv['frames'] - 1})")}
    drift = audio_drift(win["frames"], kln.get("frames"), fps=fps)
    steps.append(("сверка длин", drift["outcome"], drift["note"]))
    return {**out, **{k: drift[k] for k in
                      ("outcome", "glue", "drift_frames", "drift_ms",
                       "tolerance", "expected", "actual")},
            "note": drift["note"],
            "start_seconds": round(window[0] / float(fps), 6),
            "seconds": round(kln["frames"] / float(fps), 6),
            "elapsed": round(time.perf_counter() - t, 4)}


def finish(driving_path, kling_path, out_path, *, window, bias=0.0,
           ratio_w=TARGET_RATIO_W, ratio_h=TARGET_RATIO_H,
           prober=None, runner=None) -> dict:
    """Собрать финальный ролик: кроп плюс звук плюс отчёт. Ни один шаг не молчит."""
    runner = fork_video.run_decode if runner is None else runner
    t = time.perf_counter()
    steps = []

    def report(outcome, note, **extra):
        return {"outcome": outcome, "note": note, "steps": steps,
                "out": str(out_path), "written": False, "audio": False,
                "crop": None, "audio_plan": None, "argv": None,
                "elapsed": round(time.perf_counter() - t, 4), **extra}

    kln = fork_video.probe(kling_path, prober=prober)
    steps.append(("опрос выхода Kling", kln["outcome"], kln["note"]))
    if kln["outcome"] != PASS:
        return report(kln["outcome"], f"выход Kling не опрошен: {kln['note']}")

    geom = crop_geometry(kln["width"], kln["height"], ratio_w=ratio_w,
                         ratio_h=ratio_h, bias=bias)
    steps.append(("кроп", geom["outcome"], geom["note"]))
    if geom["outcome"] != PASS:
        return report(geom["outcome"], f"кроп не посчитан: {geom['note']}",
                      crop=geom)

    plan = audio_plan(driving_path, window, kling_path, prober=prober)
    steps.extend(plan["steps"])
    steps.append(("звук", plan["outcome"], plan["note"]))
    if plan["outcome"] == UNMEASURED:
        return report(UNMEASURED, f"звук не проверен: {plan['note']}",
                      crop=geom, audio_plan=plan)

    argv = mux_argv(kling_path, out_path, geom,
                    driving_path=driving_path if plan["glue"] else None,
                    start_seconds=plan["start_seconds"],
                    seconds=plan["seconds"])
    ran = runner(argv)
    steps.append(("сборка", PASS if ran.get("ran") and not ran.get("code")
                  else (UNMEASURED if not ran.get("ran") else FAIL),
                  (ran.get("why") or f"ffmpeg вернул {ran.get('code')}: "
                                     f"{(ran.get('err') or '').strip()[:200]}")
                  if (not ran.get("ran") or ran.get("code"))
                  else f"ffmpeg отработал, команда из {len(argv)} слов"))
    if not ran.get("ran"):
        return report(UNMEASURED, f"собрать нечем: {ran.get('why')}",
                      crop=geom, audio_plan=plan, argv=argv)
    if ran.get("code"):
        return report(FAIL, f"ffmpeg вернул {ran['code']}: "
                            f"{(ran.get('err') or '').strip()[:200]}",
                      crop=geom, audio_plan=plan, argv=argv)

    got = fork_video.probe(out_path, prober=prober)
    steps.append(("опрос результата", got["outcome"], got["note"]))
    if got["outcome"] != PASS:
        return report(got["outcome"] if got["outcome"] == UNMEASURED else FAIL,
                      f"файл записан, но не подтверждён: {got['note']}",
                      crop=geom, audio_plan=plan, argv=argv, written=True)
    mismatch = []
    if (got["width"], got["height"]) != (geom["w"], geom["h"]):
        mismatch.append(f"размер {got['width']}x{got['height']} против "
                        f"плановых {geom['w']}x{geom['h']}")
    if bool(got.get("audio")) != bool(plan["glue"]):
        mismatch.append(f"звук {'есть' if got.get('audio') else 'нет'} против "
                        f"планового {'есть' if plan['glue'] else 'нет'}")
    if mismatch:
        return report(FAIL, "файл записан, но не тот: " + "; ".join(mismatch),
                      crop=geom, audio_plan=plan, argv=argv, written=True,
                      audio=bool(got.get("audio")))
    outcome = PASS if plan["outcome"] == PASS else FAIL
    tail = ("звук возвращён" if plan["glue"] else
            "БЕЗ ЗВУКА: " + plan["note"])
    return report(outcome,
                  (f"{out_path}: {got['width']}x{got['height']}, "
                   f"{got['frames']} кадров, {got['seconds']:g} с; "
                   f"потеряно {geom['lost_percent']:g}% площади кадра; {tail}"),
                  crop=geom, audio_plan=plan, argv=argv, written=True,
                  audio=bool(got.get("audio")))


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Финальная сборка: кроп в 9:16 плюс возврат звука драйвинга")
    ap.add_argument("--driving", required=True, help="исходный драйвинг СО звуком")
    ap.add_argument("--kling", required=True, help="выход Kling, квадрат, без звука")
    ap.add_argument("--out", required=True, help="куда положить финальный ролик")
    ap.add_argument("--from-frame", type=int, required=True,
                    help="первый кадр окна драйвинга, включительно")
    ap.add_argument("--to-frame", type=int, required=True,
                    help="последний кадр окна драйвинга, включительно")
    ap.add_argument("--bias", type=float, default=0.0,
                    help="смещение окна кропа: -1 влево, 0 центр, +1 вправо")
    args = ap.parse_args(argv)
    rep = finish(args.driving, args.kling, args.out,
                 window=(args.from_frame, args.to_frame), bias=args.bias)
    for name, outcome, note in rep["steps"]:
        print(f"  [{outcome}] {name}: {note}")
    print(f"[{rep['outcome']}] {rep['note']}")
    print(f"шагов {len(rep['steps'])}, за {rep['elapsed']:g} с")
    return EXIT_BY_OUTCOME[rep["outcome"]]


if __name__ == "__main__":
    raise SystemExit(main())
