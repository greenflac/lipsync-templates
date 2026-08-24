"""УНИВЕРСАЛЬНЫЙ ПЛАН: один кадр личности на входе Kling, всегда один и тот же."""

from __future__ import annotations

import time
from pathlib import Path

from .fork_identity import FAIL, PASS, UNMEASURED


PLAN_RATIO = 0.5625

SHOULDERS_BAND = (0.20, 0.42)

ANKLES_BAND = (0.86, 0.99)

CENTRE_TOL = 0.08

WIDTH_MAX = 0.72

from .fork_intake import MIN_FACE_PX  # noqa: E402

MIN_VISIBILITY = 0.5

STYLED_SIZE_MEASURED = (896, 1200)

SHOULDER_POINTS = ("l_shoulder", "r_shoulder")
ANKLE_POINTS = ("l_ankle", "r_ankle")


def tally(checked: int, violations: int, unmeasured: int) -> dict:
    """Числа рядом с вердиктом. Ноль нарушений при нуле проверок — НЕ успех."""
    if checked == 0:
        outcome = UNMEASURED
    elif violations:
        outcome = FAIL
    elif unmeasured:
        outcome = UNMEASURED
    else:
        outcome = PASS
    return {
        "outcome": outcome,
        "checked": checked,
        "violations": violations,
        "unmeasured": unmeasured,
    }


def _axis(name: str, ok: bool | None, note: str) -> dict:
    """Ось плана. `None` — «не смогли», и это НЕ «не годно»."""
    if ok is None:
        return {"name": name, **tally(0, 0, 1), "note": note}
    return {"name": name, **tally(1, 0 if ok else 1, 0), "note": note}


def person_box(points, *, min_visibility: float = MIN_VISIBILITY) -> dict:
    """Коробка человека в долях кадра плюс высоты плеч и щиколоток."""
    if not isinstance(points, dict) or not points:
        return {**tally(0, 0, 1), "note": "позы нет: план читать не по чему"}
    good = {
        k: v
        for k, v in points.items()
        if isinstance(v, (tuple, list))
        and len(v) >= 3
        and v[2] is not None
        and v[2] >= min_visibility
    }
    if not good:
        return {
            **tally(0, 0, 1),
            "note": (
                f"ни одной точки с уверенностью {min_visibility}: "
                f"суставов {len(points)}, все ниже планки"
            ),
        }

    def mid(names):
        got = [good[n][1] for n in names if n in good]
        return round(sum(got) / len(got), 4) if got else None

    xs = [v[0] for v in good.values()]
    ys = [v[1] for v in good.values()]
    x0, x1 = min(xs), max(xs)
    return {
        **tally(1, 0, 0),
        "x0": round(x0, 4),
        "x1": round(x1, 4),
        "y0": round(min(ys), 4),
        "y1": round(max(ys), 4),
        "centre": round((x0 + x1) / 2, 4),
        "width": round(x1 - x0, 4),
        "shoulders": mid(SHOULDER_POINTS),
        "ankles": mid(ANKLE_POINTS),
        "joints": len(good),
        "note": (
            f"суставов уверенных {len(good)} из {len(points)}; "
            f"по ширине {x0:.3f}..{x1:.3f}, по высоте "
            f"{min(ys):.3f}..{max(ys):.3f}"
        ),
    }


def ratio_axis(width, height) -> dict:
    """Соотношение сторон. Полосы нет: 9:16 — это число, а не настроение."""
    if not width or not height:
        return _axis("канвас", None, f"размеры не сняты: {width}x{height}")
    got = width / height
    ok = abs(got - PLAN_RATIO) <= 0.015
    return _axis(
        "канвас",
        ok,
        f"{width}x{height} = {got:.4f} при плане {PLAN_RATIO} "
        f"(допуск 0.015 — округление на целых пикселях)",
    )


def _band_axis(name, value, band, what) -> dict:
    lo, hi = band
    if value is None:
        return _axis(name, None, f"{what} не видны: судить нечем")
    return _axis(name, lo <= value <= hi, f"{what} на {value} при полосе {lo}..{hi}")


def plan_verdict(*, width=None, height=None, points=None, face_px=None) -> dict:
    """Попадает ли картинка в универсальный план. Пять осей, три исхода."""
    t0 = time.perf_counter()
    axes = [ratio_axis(width, height)]

    box = person_box(points or {})
    if box["outcome"] != PASS:
        axes += [_axis(n, None, box["note"]) for n in ("плечи", "щиколотки", "центр", "ширина")]
    else:
        axes.append(_band_axis("плечи", box["shoulders"], SHOULDERS_BAND, "плечи"))
        axes.append(_band_axis("щиколотки", box["ankles"], ANKLES_BAND, "щиколотки"))
        off = abs(box["centre"] - 0.5)
        axes.append(
            _axis(
                "центр",
                off <= CENTRE_TOL,
                f"центр человека {box['centre']}, отклонение {off:.4f} при допуске {CENTRE_TOL}",
            )
        )
        axes.append(
            _axis(
                "ширина",
                box["width"] <= WIDTH_MAX,
                f"человек занимает {box['width']} ширины при потолке {WIDTH_MAX}",
            )
        )

    if face_px is None:
        axes.append(_axis("лицо", None, "лицо не спрашивали: размер НЕ ИЗМЕРЕН"))
    else:
        axes.append(
            _axis(
                "лицо",
                True,
                f"{face_px} px при планке {MIN_FACE_PX}"
                + (
                    ""
                    if face_px >= MIN_FACE_PX
                    else "; ПРЕДУПРЕЖДЕНИЕ: мельче планки — личность "
                    "на выходе СУДИТ ОПЕРАТОР ГЛАЗАМИ"
                ),
            )
        )

    checked = sum(a["checked"] for a in axes)
    violations = sum(a["violations"] for a in axes)
    unmeasured = sum(a["unmeasured"] for a in axes)
    return {
        **tally(checked, violations, unmeasured),
        "axes": axes,
        "box": box,
        "seconds": round(time.perf_counter() - t0, 3),
        "note": "; ".join(f"{a['name']}: {a['note']}" for a in axes),
    }


def canvas_for(width: int, height: int) -> dict:
    """Канвас 9:16, в который картинка ложится ЦЕЛИКОМ. Дополнение, не обрезка."""
    if not isinstance(width, int) or not isinstance(height, int):
        raise TypeError(f"размеры {width!r}x{height!r}: ждали целые")
    if width <= 0 or height <= 0:
        raise ValueError(f"размеры {width}x{height}: ждали больше нуля")
    if width / height > PLAN_RATIO:
        out_w, out_h = width, round(width / PLAN_RATIO)
    else:
        out_w, out_h = round(height * PLAN_RATIO), height
    out_w += out_w % 2
    out_h += out_h % 2
    return {
        "width": out_w,
        "height": out_h,
        "left": (out_w - width) // 2,
        "top": (out_h - height) // 2,
        "added_share": round(1 - (width * height) / (out_w * out_h), 4),
        "note": (
            f"{width}x{height} -> {out_w}x{out_h}: дополнено, "
            f"не обрезано; поля {(out_w - width) // 2} по бокам и "
            f"{(out_h - height) // 2} сверху и снизу"
        ),
    }


def to_plan(src, dst, *, opener=None, filler=None) -> dict:
    """Положить картинку в канвас плана. Точки внедрения — чтобы тест не ходил"""
    if opener is None:
        from PIL import Image  # noqa: PLC0415

        def opener(path):
            return Image.open(path).convert("RGB")

    try:
        im = opener(str(src))
    except Exception as exc:  # noqa: BLE001
        return {
            **tally(0, 0, 1),
            "path": None,
            "note": f"картинка не открылась: {type(exc).__name__}: {exc}",
        }

    w, h = im.size
    plan = canvas_for(int(w), int(h))
    if filler is None:
        from PIL import Image, ImageFilter  # noqa: PLC0415

        def filler(image, box):
            back = image.resize((box["width"], box["height"]))
            return back.filter(ImageFilter.GaussianBlur(radius=24))

    out = filler(im, plan)
    out.paste(im, (plan["left"], plan["top"]))
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    out.save(str(dst))
    return {**tally(1, 0, 0), "path": str(dst), "plan": plan, "note": plan["note"]}


CARD_TOL_MIN = 0.05

CARD_TOL_MAX = 0.20


def _spread(values):
    """Половина размаха между 10-м и 90-м процентилями. Края отброшены"""
    got = sorted(v for v in values if v is not None)
    if len(got) < 3:
        return None
    lo = got[int(0.10 * (len(got) - 1))]
    hi = got[int(0.90 * (len(got) - 1))]
    return round((hi - lo) / 2, 4)


def composition_card(poses, *, min_visibility: float = MIN_VISIBILITY) -> dict:
    """Где стоит человек НА ДРАЙВИНГЕ: медианы плюс измеренный разброс."""
    boxes = [person_box(p, min_visibility=min_visibility) for p in (poses or [])]
    good = [b for b in boxes if b["outcome"] == PASS]
    if not good:
        return {**tally(0, 0, 1), "note": (f"позу не прочитали ни на одном кадре из {len(boxes)}")}

    def med(key):
        got = sorted(b[key] for b in good if b.get(key) is not None)
        return round(got[len(got) // 2], 4) if got else None

    def tol(key):
        got = _spread([b.get(key) for b in good])
        if got is None:
            return CARD_TOL_MIN
        return round(min(max(got, CARD_TOL_MIN), CARD_TOL_MAX), 4)

    card = {
        "shoulders": med("shoulders"),
        "ankles": med("ankles"),
        "centre": med("centre"),
        "width": med("width"),
        "tol_shoulders": tol("shoulders"),
        "tol_ankles": tol("ankles"),
        "tol_centre": tol("centre"),
        "tol_width": tol("width"),
        "frames": len(good),
        "of": len(boxes),
    }
    return {
        **tally(len(good), 0, len(boxes) - len(good)),
        **card,
        "note": (
            f"по {len(good)} кадрам из {len(boxes)}: плечи "
            f"{card['shoulders']}+-{card['tol_shoulders']}, щиколотки "
            f"{card['ankles']}+-{card['tol_ankles']}, центр "
            f"{card['centre']}+-{card['tol_centre']}, ширина "
            f"{card['width']}+-{card['tol_width']}"
        ),
    }


def _height_words(top, bottom) -> str:
    """Числа -> фотографический язык. Модель понимает «в полный рост» и НЕ"""
    span = None if (top is None or bottom is None) else bottom - top
    if span is None:
        return "full-length framing, the whole person inside the frame"
    if span >= 0.55:
        return (
            "a full-length shot: the person occupies most of the frame "
            "height, the whole body inside the frame"
        )
    if span >= 0.38:
        return (
            "a full-length shot with air: the whole person is in frame "
            "with some space above and below"
        )
    return (
        "a wider shot: the person is small in the frame, the whole body "
        "visible with generous space around"
    )


def framing_clause(card) -> str:
    """Карточка композиции -> строка промта. Собирается ОТДЕЛЬНО от вызова:"""
    if not isinstance(card, dict) or card.get("outcome") != PASS:
        return ""
    parts = [_height_words(card.get("shoulders"), card.get("ankles"))]
    off = abs((card.get("centre") or 0.5) - 0.5)
    parts.append(
        "the person centred horizontally"
        if off <= 0.08
        else (
            "the person placed left of centre"
            if card["centre"] < 0.5
            else "the person placed right of centre"
        )
    )
    parts.append(
        "shot on a normal lens with no perspective distortion, the "
        "camera at chest height and far enough back to keep the whole "
        "body in frame"
    )
    return "FRAMING, this outranks any framing described above: " + "; ".join(parts)


def in_card(points, card, *, min_visibility: float = MIN_VISIBILITY) -> dict:
    """Попадает ли поза на картинке в КАРТОЧКУ ДРАЙВИНГА, а не в глобальные"""
    if not isinstance(card, dict) or card.get("outcome") != PASS:
        return {**tally(0, 0, 1), "note": "карточки композиции нет: сверять не с чем"}
    box = person_box(points, min_visibility=min_visibility)
    if box["outcome"] != PASS:
        return {**tally(0, 0, 1), "note": str(box.get("note"))[:200]}
    bad, seen = [], 0
    for key, label in (("centre", "центр"), ("width", "ширина")):
        want, tol, got = card.get(key), card.get(f"tol_{key}"), box.get(key)
        if want is None or got is None:
            continue
        seen += 1
        if abs(got - want) > tol:
            bad.append(f"{label} {got} против {want}+-{tol}")
    if not seen:
        return {**tally(0, 0, 1), "note": "ни одну ось сравнить не удалось"}
    return {
        **tally(seen, len(bad), 0),
        "box": box,
        "note": (
            "; ".join(bad) + "; Kling масштабирует персонажа под "
            "скелет драйвинга, и рефка мимо композиции уедет за край"
            if bad
            else f"композиция совпала по {seen} осям: центр {box['centre']}, "
            f"ширина {box['width']} (плечи {box['shoulders']} и "
            f"щиколотки {box['ankles']} измерены, но НЕ СУДЯТСЯ)"
        ),
    }


EXTEND_CLAUSE = (
    "extend this image so it fills the whole vertical frame edge to edge: the "
    "blurred bands at the top and bottom must become a natural continuation of "
    "the same scene — same background, same lighting, same perspective, same "
    "colour grade — as if the photograph had always been this tall"
)

KEEP_SUBJECT_CLAUSE = (
    "do not move, rescale, recrop or alter the person in any way; keep the "
    "same face and the same composition of the subject"
)


def extend_prompt(*, extra: str = "") -> str:
    """Промт дорисовки полей плюс запрет надписей."""
    parts = [EXTEND_CLAUSE, KEEP_SUBJECT_CLAUSE, no_brands_clause()]
    if extra:
        parts.append(extra.strip())
    return ". ".join(parts)


def extend_to_plan(src, dst, *, extender=None, sizer=None) -> dict:
    """Превратить поля плана в продолжение сцены."""
    if extender is None:

        def extender(prompt, source, out_path):
            from . import pollinations  # noqa: PLC0415

            return pollinations.images_edit(prompt, source, out_path, model="nanobanana-2")

    prompt = extend_prompt()
    try:
        extender(prompt, str(src), str(dst))
    except Exception as exc:  # noqa: BLE001
        return {
            **tally(0, 0, 1),
            "path": str(src),
            "extended": False,
            "note": (
                f"дорисовщик не ответил: {type(exc).__name__}: {exc}. "
                f"Идём дальше НА КАРТИНКЕ С ПОЛЯМИ — она хуже, но она "
                f"есть"
            ),
        }
    if sizer is None:

        def sizer(path):
            from PIL import Image  # noqa: PLC0415

            return Image.open(path).size

    try:
        w, h = sizer(str(dst))
    except Exception as exc:  # noqa: BLE001
        return {
            **tally(0, 0, 1),
            "path": str(dst),
            "extended": True,
            "note": f"размер дорисованного не снят: {type(exc).__name__}: {exc}",
        }
    got = ratio_axis(w, h)
    return {
        **tally(1, got["violations"], 0),
        "path": str(dst),
        "extended": True,
        "width": w,
        "height": h,
        "note": f"дорисовано до {w}x{h}; {got['note']}",
    }


FULL_BODY_CLAUSE = (
    "show the SAME person from the first image at FULL HEIGHT, head to feet, "
    "standing upright and facing the camera, the whole body inside the frame "
    "with clear margin above the head and below the feet, centred horizontally"
)

KEEP_IDENTITY_CLAUSE = (
    "keep the face, hair, skin tone and body type unchanged — this must read "
    "as the same person, not a lookalike"
)


def no_brands_clause() -> str:
    """Запрет брендов ОДНИМ источником на проект: он живёт в стенде, где"""
    from .fork_e2e import NO_BRANDS_CLAUSE  # noqa: PLC0415

    return NO_BRANDS_CLAUSE


def full_body_prompt(*, extra: str = "") -> str:
    """Промт приведения к полному росту. Собирается ОТДЕЛЬНО от вызова: состав"""
    parts = [FULL_BODY_CLAUSE, KEEP_IDENTITY_CLAUSE, no_brands_clause()]
    if extra:
        parts.append(extra.strip())
    return "; ".join(parts)


def render(report: dict) -> str:
    """Печать для человека: вердикт, числа, потом каждая ось отдельной строкой."""
    head = (
        f"ПЛАН: {report['outcome']}  (проверено {report['checked']}, "
        f"нарушений {report['violations']}, не смогли "
        f"{report['unmeasured']})"
    )
    rows = [f"  {a['name']}: {a['outcome']} — {a['note']}" for a in report.get("axes", [])]
    return "\n".join([head, *rows])
