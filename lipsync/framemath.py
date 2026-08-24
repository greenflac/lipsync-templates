"""Оконная математика выдачи: кадры, секунды, окна сэмплера."""

from __future__ import annotations

SIDE_MULTIPLE = 16
LENGTH_STEP = 4
LENGTH_BASE = 1

WRAP_FPS = 30

WRAP_WINDOW = 77

SECONDS_MIN = 5.0
SECONDS_MAX = 10.0


def snap_frames(requested: int) -> int:
    """Сколько кадров ДЕЙСТВИТЕЛЬНО породит обёртка на запрошенных."""
    if not isinstance(requested, int) or isinstance(requested, bool):
        raise TypeError(f"кадров ожидалось целое, пришло {requested!r}")
    if requested < LENGTH_BASE:
        raise ValueError(f"кадров {requested}, минимум {LENGTH_BASE}")
    return ((requested - LENGTH_BASE) // LENGTH_STEP) * LENGTH_STEP + LENGTH_BASE


def frames_for_seconds(seconds: float, *, fps: int | None = None,
                       bench: bool = False) -> dict:
    """Длина ролика в кадрах, с честной разницей между «просили» и «выйдет»."""
    fps = WRAP_FPS if fps is None else fps
    floor = 0 if bench else SECONDS_MIN
    if not floor < seconds <= SECONDS_MAX if bench else \
            not SECONDS_MIN <= seconds <= SECONDS_MAX:
        raise ValueError(
            f"длина {seconds} с вне полосы "
            f"{'>0' if bench else SECONDS_MIN}-{SECONDS_MAX} с "
            f"(решение составителя шаблонов, §«Формат выдачи»)"
            + (" — стендовому описанию послаблена только нижняя граница"
               if bench else ""))
    requested = int(round(seconds * fps))
    frames = snap_frames(requested)
    return {
        "seconds_requested": seconds, "fps": fps,
        "frames_requested": requested, "frames": frames,
        "snapped_away": requested - frames,
        "seconds_actual": round(frames / fps, 4),
        "note": (f"{seconds} с при {fps} к/с = {requested} кадров, обёртка "
                 f"прижмёт к {frames} (шаг {LENGTH_STEP} от {LENGTH_BASE}); "
                 f"пропадёт молча кадров: {requested - frames}"
                 + ("" if not bench or seconds >= SECONDS_MIN else
                    f". КОРОЧЕ ПОЛА {SECONDS_MIN} с — стендовый прогон, "
                    f"продуктовое заявление про длину им не проверяется")),
    }


def window_plan(frames: int, *, window: int | None = None) -> dict:
    """Сколько окон сэмплер отработает и сколько кадров сгенерит впустую."""
    window = WRAP_WINDOW if window is None else window
    if frames < 1 or window < 1:
        raise ValueError(f"кадров {frames}, окно {window} — оба от 1")
    if frames <= window:
        return {"windows": 1, "generated": frames, "discarded": 0,
                "window": window,
                "note": f"{frames} кадров влезают в одно окно {window}"}
    step = window - 1
    windows = -(-(frames - 1) // step)
    generated = windows * step + 1
    return {"windows": windows, "generated": generated,
            "discarded": generated - frames, "window": window,
            "note": (f"{frames} кадров окнами по {window}: окон {windows}, "
                     f"сгенерится {generated}, выброшено "
                     f"{generated - frames}")}
