"""Оконная математика выдачи: кадры, секунды, окна сэмплера.

Извлечено из обёртки локальной генерации при выделении продукта в отдельный
репозиторий: продуктовому пути (Kling Motion Control) из всей обёртки нужны
только эти константы и три функции. Формулы и комментарии перенесены дословно,
происхождение каждого числа помечено в его комментарии.
"""

from __future__ import annotations

#: Кратности из §3.2 и из первоисточника `WanAnimateToVideo.doc.md:20`.
#: Проза §3.2 говорит «length кратна 4», первоисточник — «default: 77, step: 4»
#: при минимуме 1. ~~«длина кратна 4»~~ снято: 77 на 4 не делится, и буквальное
#: чтение прозы забраковало бы штатную геометрию стека. Верх за первоисточником.
SIDE_MULTIPLE = 16
LENGTH_STEP = 4
LENGTH_BASE = 1

#: ВЫБРАНО составителем шаблонов: выход 30 к/с. Совпадает с умолчанием препроцессинга
#: вендора (`process_pipepline.py:38`, fps=30). ~~16 к/с~~ снято: это было
#: умолчание виджета CreateVideo, принятое за свойство модели.
WRAP_FPS = 30

#: ИЗМЕРЕНО в боевом воркфлоу составителя шаблонов (узел 62, `frame_window_size`), и там
#: же стоит умолчание самой ноды (nodes.py:1186). Два независимых свидетельства
#: одного числа.
WRAP_WINDOW = 77

#: ВЫБРАНО (§«Формат выдачи»): длина ролика 5-10 с.
SECONDS_MIN = 5.0
SECONDS_MAX = 10.0


def snap_frames(requested: int) -> int:
    """Сколько кадров ДЕЙСТВИТЕЛЬНО породит обёртка на запрошенных.

    Одно знание — одно место: формула не переписана здесь по памяти, а
    повторяет строку 1230 обёртки, и повторяет её ровно потому, что молчаливое
    прижатие надо уметь ПОСЧИТАТЬ до прогона, а не обнаружить по длине файла.
    """
    if not isinstance(requested, int) or isinstance(requested, bool):
        raise TypeError(f"кадров ожидалось целое, пришло {requested!r}")
    if requested < LENGTH_BASE:
        raise ValueError(f"кадров {requested}, минимум {LENGTH_BASE}")
    return ((requested - LENGTH_BASE) // LENGTH_STEP) * LENGTH_STEP + LENGTH_BASE


def frames_for_seconds(seconds: float, *, fps: int | None = None,
                       bench: bool = False) -> dict:
    """Длина ролика в кадрах, с честной разницей между «просили» и «выйдет».

    Умолчание частоты разрешается в теле, а не в сигнатуре: значение по
    умолчанию связывается на импорте, и подмена `WRAP_FPS` до него не дошла бы
    (, эту форму на проекте уже выгребали).
    """
    fps = WRAP_FPS if fps is None else fps
    # `bench` РАЗРЕШАЕТ ТОЛЬКО НИЖНЮЮ ГРАНИЦУ, и это несимметрично нарочно.
    # Короче пола — вопрос продуктового заявления: ролик выйдет, просто он не
    # тот, что продаётся. Длиннее потолка — вопрос ПАМЯТИ И ВРЕМЕНИ карты, и
    # никакая метка описания их не отменяет: там прогон не «не тот», там он
    # не доедет. Поэтому верхняя граница остаётся жёсткой при любом флаге.
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
    """Сколько окон сэмплер отработает и сколько кадров сгенерит впустую.

    РАСЧЁТ, а не замер: формула выведена из того, что окна смыкаются по одному
    кадру (`num_frames > frame_window_size` включает цикл, nodes.py:1232), и
    СВЕРЕНА с таблицей хэндофа, посчитанной независимо: 5 с -> 2 окна и 153
    кадра, 7 с -> 3 и 229, 10 с -> 4 и 305. Три совпадения — не доказательство
    исполнения, но расхождение бы здесь всплыло.
    """
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
