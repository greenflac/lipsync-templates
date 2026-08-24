"""Отбор петель в драйвинге: где движение повторяется и как это показать глазам."""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

from . import framemath
from . import motion, pose
from .fork_identity import FAIL, PASS, UNMEASURED


LOOP_MIN_FRAMES = 41

ADVANTAGE_MIN = 2.0

FLOW_WEIGHT = 1.0

PIXEL_WEIGHT = 1.0


HEAD_WEIGHT = 1.0

HEAD_SCALE_PAIRS = 40

HEAD_MAX_TRIES = 20

HEAD_LOCAL_PAIRS = 8

OVERLAP_MAX = 0.5

DUP_PHASES = 8

DUPLICATE_MAX_STEPS = 24.0

BRIDGE_MAX_FRAMES = 8

TOP_LOOPS = 5

MIN_POSE_COVERAGE = 0.8

GIF_MAX_FRAMES = 24

GIF_MAX_SIDE = 320

CUT_JUMP = motion.JUMP_MAX

CUT_SIDE = 96

PRESENCE_GAP_MIN = 15

COARSE_ABOVE_FRAMES = 900

COARSE_STRIDE = 5

MAX_FRAMES = 36000

FPS_PROBED = "снята с файла"
FPS_GIVEN = "подана руками"
FPS_UNKNOWN = "неизвестна"

SCAN_FULL = "полная частота"
SCAN_COARSE = "прорежённая"
SCAN_TOO_LONG = "слишком длинное"

EXIT_BY_OUTCOME = {PASS: 0, FAIL: 1, UNMEASURED: 2}

FRAME_SUFFIXES = (".png", ".jpg", ".jpeg")

CACHE_VERSION = 1


def read_pose(path) -> dict:
    """Снять позу с одного кадра. ТОЧКА ВНЕДРЕНИЯ: тест подменяет её целиком."""
    try:
        return {"points": pose.landmarks(path), "why": "", "people": None}
    except Exception as exc:  # noqa: BLE001 — намеренно широко: причин «спросить
        return {"points": None, "why": f"{type(exc).__name__}: {str(exc)[:200]}"}


def read_gray(path):
    """Уменьшенный серый кадр. ВТОРАЯ ТОЧКА ВНЕДРЕНИЯ."""
    return motion._gray(path, CUT_SIDE)


def read_head(path) -> dict:
    """Где в кадре голова. ТРЕТЬЯ ТОЧКА ВНЕДРЕНИЯ."""
    try:
        from PIL import Image

        from . import fork_channels

        pts = fork_channels.wholebody_points(str(path))
        if pts is None:
            return {"head": None, "why": ""}
        with Image.open(path) as im:
            w, h = im.size
        box = fork_channels.face_bbox(pts, (h, w))
        if box is None:
            return {"head": None, "why": ""}
        x1, x2, y1, y2 = box
        return {"head": ((x1 + x2) / 2.0, (y1 + y2) / 2.0), "why": ""}
    except Exception as exc:  # noqa: BLE001 — см. `read_pose`: причин «спросить
        return {"head": None, "why": f"{type(exc).__name__}: {str(exc)[:200]}"}


def _head_at(paths, k, *, reader, cache) -> dict:
    """Голова на кадре k с запоминанием: один кадр опрашивается один раз."""
    if k not in cache:
        cache[k] = reader(str(paths[k]))
    return cache[k]


def head_scale(paths, *, reader=None, pairs=None, cache=None) -> dict:
    """Типичное смещение головы за кадр — СВОЯ единица для своей оси."""
    import numpy as np

    reader = read_head if reader is None else reader
    pairs = HEAD_SCALE_PAIRS if pairs is None else pairs
    cache = {} if cache is None else cache
    t = time.perf_counter()
    n = len(paths)
    if n < 2:
        return {"step": None, "measured": 0, "frames": 0, "elapsed": 0.0,
                "reason": "кадров меньше двух", "outcome": UNMEASURED}
    spots = sorted({int(k) for k in np.linspace(0, n - 2, min(pairs, n - 1))})
    steps, broken = [], ""
    for k in spots:
        a = _head_at(paths, k, reader=reader, cache=cache)
        b = _head_at(paths, k + 1, reader=reader, cache=cache)
        if a["why"] or b["why"]:
            broken = a["why"] or b["why"]
            continue
        if a["head"] is None or b["head"] is None:
            continue
        steps.append(float(np.hypot(a["head"][0] - b["head"][0],
                                    a["head"][1] - b["head"][1])))
    elapsed = round(time.perf_counter() - t, 4)
    if not steps:
        return {"step": None, "measured": 0, "frames": len(cache),
                "elapsed": elapsed, "outcome": UNMEASURED,
                "reason": (f"спросить нечем: {broken}" if broken else
                           "лица не видно ни на одной паре кадров")}
    return {"step": float(np.median(steps)), "measured": len(steps),
            "frames": len(cache), "elapsed": elapsed, "outcome": PASS,
            "reason": ""}


def head_seam(paths, i, j, *, reader=None, cache=None) -> dict:
    """Насколько голова НЕ ВЕРНУЛАСЬ на место к концу петли, в пикселях."""
    import numpy as np

    reader = read_head if reader is None else reader
    cache = {} if cache is None else cache
    a = _head_at(paths, i, reader=reader, cache=cache)
    b = _head_at(paths, j, reader=reader, cache=cache)
    if a["why"] or b["why"]:
        return {"outcome": UNMEASURED, "gap": None,
                "reason": f"спросить нечем: {a['why'] or b['why']}"}
    if a["head"] is None or b["head"] is None:
        gone = i if a["head"] is None else j
        return {"outcome": UNMEASURED, "gap": None,
                "reason": f"лица не видно на кадре {gone}"}
    return {"outcome": PASS, "reason": "",
            "gap": round(float(np.hypot(a["head"][0] - b["head"][0],
                                        a["head"][1] - b["head"][1])), 3)}


def cuts(paths, *, gray=None, jump=None) -> dict:
    """Где в клипе монтажный рез. Дёшево, по пикселям, ДО снятия поз."""
    import numpy as np

    gray = read_gray if gray is None else gray
    jump = CUT_JUMP if jump is None else jump
    t = time.perf_counter()
    steps, prev = [], None
    for p in paths:
        cur = gray(str(p))
        if prev is not None:
            steps.append(float(np.abs(cur - prev).mean()))
        prev = cur
    elapsed = round(time.perf_counter() - t, 4)
    if not steps:
        return {"outcome": UNMEASURED, "cuts": [], "steps": 0, "median": None,
                "worst": None, "elapsed": elapsed,
                "note": "кадров меньше двух: резы искать не в чем"}
    med = float(np.median(steps))
    if med <= 0:
        return {"outcome": UNMEASURED, "cuts": [], "steps": len(steps),
                "median": 0.0, "worst": round(max(steps), 4), "elapsed": elapsed,
                "note": ("типичный межкадровый скачок равен нулю: сравнивать не "
                         "с чем, резы НЕ ИСКАЛИ. Это не «резов нет»")}
    found = [k for k, v in enumerate(steps) if v / med > jump]
    worst = max(steps) / med
    return {"outcome": PASS, "cuts": found, "steps": len(steps),
            "median": round(med, 4), "worst": round(worst, 2),
            "elapsed": elapsed,
            "note": (f"резов найдено {len(found)} по {len(steps)} переходам "
                     f"(планка {jump}x типичного скачка, самый резкий переход "
                     f"{worst:.2f}x)"
                     + (f"; кадры-швы: {found[:10]}" if found else ""))}


def keep_grays(paths, *, gray=None) -> dict:
    """Серые кадры для ПИКСЕЛЬНОГО СТЫКА, сложенные в память как uint8."""
    import numpy as np

    gray = read_gray if gray is None else gray
    t = time.perf_counter()
    out = {}
    for k, p in paths:
        arr = np.asarray(gray(str(p)))
        lo, hi = float(arr.min()), float(arr.max())
        if lo < 0 or hi > 255:
            raise ValueError(
                f"серый кадр {p} вне восьмибитного диапазона: {lo}..{hi}. "
                f"`read_gray` обязан отдавать яркость 0..255 — склад хранит "
                f"кадры как uint8, и другое значение завернулось бы молча")
        out[k] = arr.astype("uint8")
    return {"grays": out, "frames": len(out),
            "bytes": sum(a.nbytes for a in out.values()),
            "elapsed": round(time.perf_counter() - t, 4)}


def pixel_gap(grays, i, j):
    """Насколько РАЗНАЯ КАРТИНКА в двух кадрах, в средней яркости."""
    import numpy as np

    a, b = grays.get(i), grays.get(j)
    if a is None or b is None:
        return None
    return round(float(np.abs(a.astype("float64") - b.astype("float64")).mean()), 6)


def pixel_step(grays, order) -> float | None:
    """Типичный ПИКСЕЛЬНЫЙ переход между соседними опрошенными кадрами."""
    import numpy as np

    steps = [g for g in (pixel_gap(grays, order[k], order[k + 1])
                         for k in range(len(order) - 1)) if g is not None]
    return float(np.median(steps)) if steps else None


def presence(poses, *, people=None, index=None, gap_min=None) -> dict:
    """Есть ли человек, один ли он, и не выходил ли он из кадра."""
    gap_min = PRESENCE_GAP_MIN if gap_min is None else gap_min
    index = list(range(len(poses))) if index is None else list(index)
    seen = [i for i, p in enumerate(poses) if p is not None]
    crowd = sorted({c for c in (people or []) if c is not None and c > 1})
    gaps, run = [], []
    for i, p in enumerate(poses):
        if p is None:
            run.append(i)
        elif run:
            gaps.append((run[0], run[-1]))
            run = []
    if run:
        gaps.append((run[0], run[-1]))
    long_gaps = [(a, b) for a, b in gaps if b - a + 1 >= gap_min]
    return {"frames": len(poses), "seen": len(seen), "crowd": crowd,
            "gaps": gaps, "long_gaps": long_gaps,
            "left_at": (index[long_gaps[0][0]] if long_gaps else None),
            "missing": [index[i] for i, p in enumerate(poses) if p is None]}


def frame_paths(directory) -> list:
    """Кадры каталога, отсортованные по имени."""
    d = Path(directory)
    return sorted((p for p in d.iterdir()
                   if p.is_file() and p.suffix.lower() in FRAME_SUFFIXES),
                  key=lambda p: p.name)


def _cache_key(path) -> str:
    st = Path(path).stat()
    return f"{Path(path).name}:{st.st_size}:{st.st_mtime_ns}"


def read_all(paths, *, reader=None, cache=None) -> dict:
    """Снять позы со всех кадров. Числа рядом с результатом."""
    reader = read_pose if reader is None else reader
    paths = [Path(p) for p in paths]
    t = time.perf_counter()

    store = {}
    if cache is not None and Path(cache).exists():
        try:
            raw = json.loads(Path(cache).read_text(encoding="utf-8"))
            if raw.get("version") == CACHE_VERSION:
                store = raw.get("frames") or {}
        except (OSError, ValueError):
            store = {}

    poses, whys, crowd = [], [], []
    hits = 0
    for p in paths:
        key = None
        if cache is not None:
            try:
                key = _cache_key(p)
            except OSError:
                key = None
        if key is not None and key in store:
            hits += 1
            got = store[key]
            poses.append(None if got is None
                         else {n: tuple(v) for n, v in got.items()})
            whys.append("")
            crowd.append(None)
            continue
        got = reader(str(p))
        poses.append(got.get("points"))
        whys.append(got.get("why") or "")
        crowd.append(got.get("people"))
        if key is not None and not whys[-1]:
            store[key] = (None if poses[-1] is None
                          else {n: list(v) for n, v in poses[-1].items()})

    if cache is not None:
        try:
            Path(cache).parent.mkdir(parents=True, exist_ok=True)
            Path(cache).write_text(
                json.dumps({"version": CACHE_VERSION, "frames": store}),
                encoding="utf-8")
        except OSError:
            pass

    taken = sum(1 for p in poses if p is not None)
    broken = [w for w in whys if w]
    return {"poses": poses, "why": whys, "people": crowd,
            "frames": len(paths), "taken": taken,
            "no_body": sum(1 for p, w in zip(poses, whys)
                           if p is None and not w),
            "unreadable": len(broken),
            "first_why": broken[0] if broken else "",
            "cached": hits,
            "elapsed": round(time.perf_counter() - t, 4)}


def states(poses) -> list:
    """Позы, приведённые к торсу и центрированные на бёдрах."""
    return [None if p is None else pose._normalise(p) for p in poses]


def pose_gap(a, b):
    """Расхождение двух ПРИВЕДЁННЫХ поз в длинах торса, или None."""
    import numpy as np

    if a is None or b is None:
        return None
    shared = [n for n in a
              if a[n][1] >= pose.MIN_VISIBILITY and b[n][1] >= pose.MIN_VISIBILITY]
    return round(float(np.mean([float(np.linalg.norm(a[n][0] - b[n][0]))
                                for n in shared])), 6)


def flow_gap(states_list, i, j):
    """Расхождение НАПРАВЛЕНИЙ движения в кадрах i и j, в длинах торса за кадр."""
    import numpy as np

    n = len(states_list)
    if i + 1 >= n or j + 1 >= n:
        return None
    quad = [states_list[k] for k in (i, i + 1, j, j + 1)]
    if any(s is None for s in quad):
        return None
    shared = [k for k in quad[0]
              if all(s[k][1] >= pose.MIN_VISIBILITY for s in quad)]
    vals = [float(np.linalg.norm((quad[1][k][0] - quad[0][k][0])
                                 - (quad[3][k][0] - quad[2][k][0])))
            for k in shared]
    return round(float(np.mean(vals)), 6)


def typical_step(states_list) -> dict:
    """Обычный межкадровый шаг клипа — единица, в которой меряется стык."""
    import numpy as np

    steps = [g for g in (pose_gap(states_list[k], states_list[k + 1])
                         for k in range(len(states_list) - 1)) if g is not None]
    if not steps:
        return {"step": None, "measured": 0,
                "note": "межкадровый шаг НЕ ИЗМЕРЕН: нет ни одной пары соседних "
                        "кадров с пригодной позой"}
    step = float(np.median(steps))
    return {"step": step, "measured": len(steps),
            "note": (f"обычный шаг клипа {step:.4f} длин торса за кадр, "
                     f"по {len(steps)} парам соседних кадров")}


def length_is_admissible(length, *, fps=None, min_frames=None) -> bool:
    """Пройдёт ли такая длина петли обёртку и продуктовую полосу."""
    min_frames = LOOP_MIN_FRAMES if min_frames is None else min_frames
    if length < min_frames:
        return False
    if fps is not None and length > int(framemath.SECONDS_MAX * fps):
        return False
    return (length - framemath.LENGTH_BASE) % framemath.LENGTH_STEP == 0


def admissible_lengths(n_frames, *, fps=None, min_frames=None) -> list:
    """Длины петли, которые обёртка НЕ прижмёт и продукт примет."""
    return [L for L in range(1, n_frames + 1)
            if length_is_admissible(L, fps=fps, min_frames=min_frames)]


def admissible_pairs(index, *, fps=None, min_frames=None) -> list:
    """Пары ПОЗИЦИЙ, чья длина в ИСХОДНЫХ кадрах допустима."""
    top = None if fps is None else int(framemath.SECONDS_MAX * fps)
    out = []
    for a in range(len(index)):
        for b in range(a + 1, len(index)):
            L = index[b] - index[a] + 1
            if top is not None and L > top:
                break
            if length_is_admissible(L, fps=fps, min_frames=min_frames):
                out.append((a, b))
    return out


def shared_joints(states_list, a, b) -> int:
    """Сколько суставов реально участвовало в сравнении пары."""
    a_st, b_st = states_list[a], states_list[b]
    if a_st is None or b_st is None:
        return 0
    return sum(1 for n in a_st
               if a_st[n][1] >= pose.MIN_VISIBILITY
               and b_st[n][1] >= pose.MIN_VISIBILITY)


def similarity(states_list, *, fps=None, min_frames=None, index=None,
               blocked=None, grays=None) -> dict:
    """Матрица самоподобия поз — в разреженном виде, по допустимым парам."""
    index = list(range(len(states_list))) if index is None else list(index)
    pairs = admissible_pairs(index, fps=fps, min_frames=min_frames)
    pose_m, flow_m, pix_m, joints_m = {}, {}, {}, {}
    unmeasurable = 0
    rejected: dict = {}
    for a, b in pairs:
        i, j = index[a], index[b]
        why = blocked(i, j) if blocked is not None else None
        if why:
            rejected[why] = rejected.get(why, 0) + 1
            continue
        pg = pose_gap(states_list[a], states_list[b])
        fg = flow_gap(states_list, a, b)
        xg = None if grays is None else pixel_gap(grays, i, j)
        pose_m[(i, j)] = pg
        flow_m[(i, j)] = fg
        pix_m[(i, j)] = xg
        joints_m[(i, j)] = shared_joints(states_list, a, b)
        if pg is None or fg is None or (grays is not None and xg is None):
            unmeasurable += 1
    return {"pose": pose_m, "flow": flow_m, "pixel": pix_m, "joints": joints_m,
            "index": index,
            "pairs": len(pairs), "rejected": rejected,
            "kept": len(pose_m), "unmeasurable": unmeasurable,
            "measured": len(pose_m) - unmeasurable}


def score_pairs(sim, step, *, flow_weight=None, pix_step=None,
                pixel_weight=None) -> list:
    """Оценка стыка по каждой паре, в единицах обычного шага клипа."""
    flow_weight = FLOW_WEIGHT if flow_weight is None else flow_weight
    pixel_weight = PIXEL_WEIGHT if pixel_weight is None else pixel_weight
    if not step or step <= 0:
        raise ValueError(
            f"обычный шаг клипа {step!r}: делить на него нельзя. Клип, который "
            f"не движется, — исход «не смогли», и решается он выше")
    out = []
    for key, pg in sim["pose"].items():
        fg = sim["flow"].get(key)
        xg = sim.get("pixel", {}).get(key)
        if pg is None or fg is None:
            continue
        if pix_step and xg is None:
            continue
        i, j = key
        seam_pose = pg / step
        seam_flow = fg / step
        seam_pix = (xg / pix_step) if (pix_step and xg is not None) else None
        score = max(seam_pose, flow_weight * seam_flow)
        if seam_pix is not None:
            score = max(score, pixel_weight * seam_pix)
        out.append({
            "i": i, "j": j, "frames": j - i + 1,
            "pose_gap": round(pg, 4), "flow_gap": round(fg, 4),
            "pixel_gap": None if xg is None else round(xg, 4),
            "seam_pose": round(seam_pose, 3), "seam_flow": round(seam_flow, 3),
            "seam_pixel": None if seam_pix is None else round(seam_pix, 3),
            "joints": sim.get("joints", {}).get(key),
            "score": round(score, 3),
        })
    out.sort(key=lambda c: (c["score"], c["i"]))
    return out


def bridge_frames(seam) -> int | None:
    """Сколько кадров моста стоит стык величиной `seam` типичных шагов."""
    if seam is None:
        return None
    return int(math.ceil(float(seam)))


def bridge_cost(seams, *, max_frames=None) -> dict:
    """Цена моста по ЧЕТЫРЁМ осям сразу, с тремя исходами."""
    max_frames = BRIDGE_MAX_FRAMES if max_frames is None else max_frames
    measured = {k: float(v) for k, v in seams.items() if v is not None}
    missing = sorted(k for k, v in seams.items() if v is None)
    worst_axis = max(measured, key=measured.get) if measured else None
    seam = measured[worst_axis] if worst_axis is not None else None
    frames = bridge_frames(seam)
    if not measured:
        return {"outcome": UNMEASURED, "frames": None, "floor": None,
                "seam": None, "worst_axis": None, "unmeasured": missing,
                "measured": sorted(measured),
                "reason": "не измерена ни одна ось стыка"}
    if missing:
        if frames > max_frames:
            return {"outcome": FAIL, "frames": None, "floor": frames,
                    "seam": seam, "worst_axis": worst_axis,
                    "unmeasured": missing, "measured": sorted(measured),
                    "reason": (f"мост НЕ МЕНЬШЕ {frames} кадров уже по оси "
                               f"{worst_axis!r} при потолке {max_frames}; "
                               f"неизмеренная ось ({', '.join(missing)}) его "
                               f"только удлинит")}
        return {"outcome": UNMEASURED, "frames": None, "floor": frames,
                "seam": seam, "worst_axis": worst_axis, "unmeasured": missing,
                "measured": sorted(measured),
                "reason": (f"мост не меньше {frames} кадров, а точнее сказать "
                           f"нечем: не измерены оси {', '.join(missing)}")}
    if frames > max_frames:
        return {"outcome": FAIL, "frames": frames, "floor": frames,
                "seam": seam, "worst_axis": worst_axis, "unmeasured": [],
                "measured": sorted(measured),
                "reason": (f"мост {frames} кадров при потолке {max_frames}: "
                           f"хуже всех ось {worst_axis!r} ({seam:.2f} шага)")}
    return {"outcome": PASS, "frames": frames, "floor": frames, "seam": seam,
            "worst_axis": worst_axis, "unmeasured": [],
            "measured": sorted(measured), "reason": ""}


def rank_loops(loops) -> list:
    """Порядок карточек: ДВЕ ОЧЕРЕДИ, сначала полностью измеренные."""
    def key(lp):
        cost = lp.get("bridge") or {}
        measured = cost.get("outcome") == PASS
        price = cost.get("frames") if measured else cost.get("floor")
        return (0 if measured else 1,
                math.inf if price is None else price,
                math.inf if cost.get("seam") is None else cost["seam"],
                lp.get("i", 0))
    return sorted(loops, key=key)


def overlap(a, b) -> float:
    """Какую долю более КОРОТКОЙ из двух петель они делят."""
    inter = min(a["j"], b["j"]) - max(a["i"], b["i"]) + 1
    if inter <= 0:
        return 0.0
    return inter / min(a["frames"], b["frames"])


def select(cands, *, overlap_max=None, top=None) -> dict:
    """Принять несколько РАЗНЫХ петель, а не десяток сдвинутых на кадр."""
    overlap_max = OVERLAP_MAX if overlap_max is None else overlap_max
    top = TOP_LOOPS if top is None else top
    kept, dropped = [], 0
    for c in cands:
        if len(kept) >= top:
            break
        if any(overlap(c, k) > overlap_max for k in kept):
            dropped += 1
            continue
        kept.append(c)
    return {"kept": kept, "dropped_overlap": dropped,
            "considered": len(cands)}


def loop_signature(state_at, i, j, *, phases=None) -> list | None:
    """Чем описывается петля при сверке «одно ли это движение»."""
    phases = DUP_PHASES if phases is None else phases
    every = max(1, round(LOOP_MIN_FRAMES / phases))
    out = []
    for frame in range(i, j, every):
        st = state_at(frame)
        if st is None:
            return None
        out.append(st)
    return out


def signature_gap(a, b):
    """Расхождение двух петель как ДВИЖЕНИЙ, в длинах торса."""
    import numpy as np

    if not a or not b:
        return None
    def pack(sig):
        names = list(sig[0])
        xy = np.array([[st[n][0] for n in names] for st in sig], dtype="float64")
        vis = np.array([[st[n][1] >= pose.MIN_VISIBILITY for n in names]
                        for st in sig], dtype=bool)
        return names, xy, vis

    names_a, xy_a, vis_a = pack(a)
    names_b, xy_b, vis_b = pack(b)
    if names_a != names_b:
        return None
    dist = np.linalg.norm(xy_a[:, None, :, :] - xy_b[None, :, :, :], axis=-1)
    mask = vis_a[:, None, :] & vis_b[None, :, :]
    counts = mask.sum(axis=-1)
    if not counts.all():
        return None
    means = (dist * mask).sum(axis=-1) / counts
    forward = float(means.min(axis=1).max())
    backward = float(means.min(axis=0).max())
    return max(forward, backward)


def repeat_plan(length, *, fps=None) -> list:
    """Сколько повторов петли даёт продуктовую длину 5-10 с."""
    if fps is None or fps <= 0:
        return []
    if length < 2:
        return []
    ceiling = int(framemath.SECONDS_MAX * fps)
    out = []
    for n in range(1, (ceiling - 1) // (length - 1) + 1):
        total = n * (length - 1) + 1
        seconds = total / fps
        if seconds > framemath.SECONDS_MAX:
            break
        if seconds < framemath.SECONDS_MIN:
            continue
        out.append({"repeats": n, "frames": total,
                    "seconds": round(seconds, 2),
                    "snapped": framemath.snap_frames(total)})
    return out


def gif_indices(i, j, *, max_frames=None) -> list:
    """Номера кадров для GIF петли [i..j]."""
    max_frames = GIF_MAX_FRAMES if max_frames is None else max_frames
    body = list(range(i, j))
    if len(body) <= max_frames:
        return body
    stride = math.ceil(len(body) / max_frames)
    return body[::stride][:max_frames]


def make_gif(paths, i, j, out_path, *, fps=None, max_frames=None,
             max_side=None) -> dict:
    """Собрать GIF петли. Возвращает путь, число кадров и размер файла."""
    from PIL import Image

    fps = framemath.WRAP_FPS if fps is None else fps
    max_side = GIF_MAX_SIDE if max_side is None else max_side
    idx = gif_indices(i, j, max_frames=max_frames)
    if not idx:
        return {"path": None, "frames": 0, "bytes": 0,
                "note": f"петля [{i}..{j}] пуста — GIF собирать не из чего"}
    stride = (idx[1] - idx[0]) if len(idx) > 1 else 1
    frames_img = []
    for k in idx:
        im = Image.open(paths[k]).convert("RGB")
        if max(im.size) > max_side:
            scale = max_side / max(im.size)
            im = im.resize((max(1, round(im.width * scale)),
                            max(1, round(im.height * scale))))
        frames_img.append(im)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames_img[0].save(out_path, save_all=True, append_images=frames_img[1:],
                       duration=int(round(1000 * stride / fps)), loop=0,
                       optimize=True)
    return {"path": str(out_path), "frames": len(idx),
            "bytes": out_path.stat().st_size, "stride": stride,
            "size": frames_img[0].size}


def _report(outcome, note, t0, steps, **extra) -> dict:
    out = {"outcome": outcome, "loops": [], "note": note,
           "elapsed": round(time.perf_counter() - t0, 4),
           "steps": [{"step": s, "outcome": o, "note": n, "seconds": round(e, 4)}
                     for s, o, n, e in steps]}
    out.update(extra)
    out["note"] = f"{outcome}: {note}"
    return out


def refine_all(loops, paths, *, stride, reader=None, cache=None, fps=None,
               min_frames=None, flow_weight=None, pixel_weight=None,
               blocked=None, gray=None, pix_step=None) -> dict:
    """Уточнить границы петель на ПОЛНОЙ частоте в окне ±шаг вокруг найденного."""
    if stride <= 1 or not loops:
        return {"loops": loops, "poses": 0, "elapsed": 0.0, "windows": 0}
    t = time.perf_counter()
    n = len(paths)
    wanted, windows = set(), []
    for lp in loops:
        wi = range(max(0, lp["i"] - stride), min(n - 1, lp["i"] + stride) + 1)
        wj = range(max(0, lp["j"] - stride), min(n - 1, lp["j"] + stride) + 1)
        wanted |= {k for k in wi} | {k + 1 for k in wi if k + 1 < n}
        wanted |= {k for k in wj} | {k + 1 for k in wj if k + 1 < n}
        windows.append((list(wi), list(wj)))
    order = sorted(wanted)
    got = read_all([paths[k] for k in order], reader=reader, cache=cache)
    st = {k: v for k, v in zip(order, states(got["poses"]))}
    grays = (keep_grays([(k, paths[k]) for k in order], gray=gray)["grays"]
             if pix_step else {})

    import numpy as np

    fine = [g for g in (pose_gap(st.get(k), st.get(k + 1)) for k in order)
            if g is not None]
    fine_pix = [g for g in (pixel_gap(grays, k, k + 1) for k in order)
                if g is not None] if pix_step else []
    if not fine:
        return {"loops": loops, "poses": len(order),
                "elapsed": round(time.perf_counter() - t, 4),
                "windows": len(windows),
                "note": "уточнение не состоялось: на полной частоте поз нет"}
    step = float(np.median(fine))
    pstep = float(np.median(fine_pix)) if fine_pix else None
    out = []
    for lp, (wi, wj) in zip(loops, windows):
        best = None
        for i in wi:
            for j in wj:
                if not length_is_admissible(j - i + 1, fps=fps,
                                            min_frames=min_frames):
                    continue
                if blocked is not None and blocked(i, j):
                    continue
                pg = pose_gap(st.get(i), st.get(j))
                fg = (None if any(st.get(k) is None for k in (i, i + 1, j, j + 1))
                      else _flow_between(st, i, j))
                if pg is None or fg is None or step <= 0:
                    continue
                xg = pixel_gap(grays, i, j) if pstep else None
                if pstep and xg is None:
                    continue
                fw = FLOW_WEIGHT if flow_weight is None else flow_weight
                xw = PIXEL_WEIGHT if pixel_weight is None else pixel_weight
                sc = max(pg / step, fw * fg / step)
                if xg is not None:
                    sc = max(sc, xw * xg / pstep)
                sc = round(sc, 3)
                if best is None or sc < best["score"]:
                    best = {"i": i, "j": j, "frames": j - i + 1,
                            "pose_gap": round(pg, 4), "flow_gap": round(fg, 4),
                            "pixel_gap": None if xg is None else round(xg, 4),
                            "seam_pose": round(pg / step, 3),
                            "seam_flow": round(fg / step, 3),
                            "seam_pixel": (None if xg is None
                                           else round(xg / pstep, 3)),
                            "joints": sum(
                                1 for nm in (st.get(i) or {})
                                if st[i][nm][1] >= pose.MIN_VISIBILITY
                                and st[j][nm][1] >= pose.MIN_VISIBILITY),
                            "score": sc}
        item = dict(lp)
        if best is not None:
            item["coarse"] = {"i": lp["i"], "j": lp["j"], "score": lp["score"]}
            item.update(best)
        out.append(item)
    return {"loops": out, "poses": len(order), "fine_step": round(step, 4),
            "fine_pixel_step": None if pstep is None else round(pstep, 4),
            "elapsed": round(time.perf_counter() - t, 4), "windows": len(windows)}


def _flow_between(st, i, j):
    """Расхождение направлений по словарю состояний (для уточнения)."""
    import numpy as np

    quad = [st.get(i), st.get(i + 1), st.get(j), st.get(j + 1)]
    if any(q is None for q in quad):
        return None
    shared = [k for k in quad[0]
              if all(q[k][1] >= pose.MIN_VISIBILITY for q in quad)]
    if not shared:
        return None
    return round(float(np.mean(
        [float(np.linalg.norm((quad[1][k][0] - quad[0][k][0])
                              - (quad[3][k][0] - quad[2][k][0])))
         for k in shared])), 6)


def pick_finalists(worthy, paths, *, top=None, overlap_max=None, head=None,
                   head_weight=None, flow_weight=None, pixel_weight=None,
                   tries=None, scale=None, refine=None, local=None,
                   state_at=None, typical=None, phases=None, duplicate_max=None,
                   bridge_max=None, head_local_pairs=None) -> dict:
    """Набрать финалистов: сита от бесплатного к дорогому и ДВЕ ОЧЕРЕДИ."""
    top = TOP_LOOPS if top is None else top
    overlap_max = OVERLAP_MAX if overlap_max is None else overlap_max
    head_weight = HEAD_WEIGHT if head_weight is None else head_weight
    flow_weight = FLOW_WEIGHT if flow_weight is None else flow_weight
    pixel_weight = PIXEL_WEIGHT if pixel_weight is None else pixel_weight
    head_local_pairs = (HEAD_LOCAL_PAIRS if head_local_pairs is None
                        else head_local_pairs)
    tries = HEAD_MAX_TRIES if tries is None else tries
    duplicate_max = DUPLICATE_MAX_STEPS if duplicate_max is None else duplicate_max
    bridge_max = BRIDGE_MAX_FRAMES if bridge_max is None else bridge_max
    head = read_head if head is None else head
    refine = (lambda c: c) if refine is None else refine
    local = (lambda i, j: {}) if local is None else local
    cache: dict = {}
    memo: dict = {}

    def remember(path):
        if path not in memo:
            memo[path] = head(path)
        return memo[path]
    head_off = scale is None or scale.get("step") in (None, 0)
    head_off_note = ((scale or {}).get("reason") or "масштаб оси головы не измерен")

    kept, deferred = [], []
    dropped_overlap, dropped_duplicate, dup_unmeasured = 0, 0, 0
    dropped_bridge, dropped_head, tried, budget_hit = 0, 0, 0, False

    def clash(cand, against):
        """Сита диапазона и содержания против уже занятых мест."""
        if any(overlap(cand, k) > overlap_max for k in against):
            return "пересечение"
        sig = cand.get("signature")
        if sig is not None:
            for k in against:
                other = k.get("signature")
                gap = signature_gap(sig, other) if other else None
                if gap is not None and gap / typical <= duplicate_max:
                    return "дубль"
        return None

    for cand in worthy:
        if len(kept) >= top:
            break
        if head_off and len(deferred) >= top:
            break
        if any(overlap(cand, k) > overlap_max for k in kept):
            dropped_overlap += 1
            continue
        if state_at is not None and typical:
            sig = loop_signature(state_at, cand["i"], cand["j"], phases=phases)
            if sig is None:
                dup_unmeasured += 1
            else:
                cand = {**cand, "signature": sig}
                if clash(cand, kept) == "дубль":
                    dropped_duplicate += 1
                    continue
        loop = dict(refine(cand))
        loop["signature"] = cand.get("signature")
        loc = local(loop["i"], loop["j"]) or {}
        pstep_loc, xstep_loc = loc.get("поза"), loc.get("пиксели")
        seams = {
            "поза": (loop["pose_gap"] / pstep_loc) if pstep_loc else None,
            "поток": (flow_weight * loop["flow_gap"] / pstep_loc)
                     if pstep_loc else None,
            "голова": None,
        }
        if loop.get("pixel_gap") is not None:
            seams["пиксели"] = ((pixel_weight * loop["pixel_gap"] / xstep_loc)
                                if xstep_loc else None)
        loop["pixel_axis_off"] = loop.get("seam_pixel") is None
        if head_off:
            loop["head_state"] = UNMEASURED
            loop["head_note"] = head_off_note
            loop["seam_head"] = None
        else:
            if tried >= tries:
                budget_hit = True
                break
            tried += 1
            seam = head_seam(paths, loop["i"], loop["j"], reader=remember,
                             cache=cache)
            if seam["outcome"] == PASS:
                near = head_scale(paths[loop["i"]:loop["j"] + 1],
                                  reader=remember, pairs=head_local_pairs)
                loop["head_step_local"] = near["step"]
                loop["head_state"] = PASS
                loop["head_note"] = ""
                loop["head_gap"] = seam["gap"]
                loop["seam_head_clip"] = round(seam["gap"] / scale["step"], 3)
                loop["seam_head"] = (None if not near["step"] else
                                     round(seam["gap"] / near["step"], 3))
                seams["голова"] = (None if not near["step"] else
                                   head_weight * seam["gap"] / near["step"])
                if not near["step"]:
                    loop["head_state"] = UNMEASURED
                    loop["head_note"] = (f"стык головы измерен ({seam['gap']} "
                                         f"px), а её обычный шаг ВНУТРИ петли "
                                         f"— нет: {near['reason']}")
            else:
                loop["head_state"] = UNMEASURED
                loop["head_note"] = seam["reason"]
                loop["seam_head"] = None
        cost = bridge_cost(seams, max_frames=bridge_max)
        loop["bridge_seams"] = {k: (None if v is None else round(v, 3))
                                for k, v in seams.items()}
        loop["bridge"] = cost
        loop["bridge_frames"] = cost["frames"]
        if cost["outcome"] == FAIL:
            dropped_bridge += 1
            dropped_head += 1 if cost["worst_axis"] == "голова" else 0
            continue
        if cost["outcome"] == UNMEASURED:
            if clash(loop, deferred) is None and len(deferred) < top:
                deferred.append(loop)
            continue
        if loop.get("seam_head_clip") is not None:
            loop["score"] = round(max(loop["score"],
                                      head_weight * loop["seam_head_clip"]), 3)
        kept.append(loop)

    for loop in deferred:
        if len(kept) >= top:
            break
        why = clash(loop, kept)
        if why == "пересечение":
            dropped_overlap += 1
        elif why == "дубль":
            dropped_duplicate += 1
        else:
            kept.append(loop)

    kept = rank_loops(kept)
    for loop in kept:
        loop.pop("signature", None)
    unchecked = sum(1 for lp in kept if lp["head_state"] == UNMEASURED)
    return {"kept": kept, "dropped_overlap": dropped_overlap,
            "dropped_duplicate": dropped_duplicate,
            "dup_unmeasured": dup_unmeasured,
            "dropped_bridge": dropped_bridge,
            "dropped_head": dropped_head, "head_tried": tried,
            "head_budget_hit": budget_hit,
            "head_frames": len(memo), "unchecked": unchecked,
            "deferred": len(deferred),
            "bridge_measured": sum(1 for lp in kept
                                   if lp["bridge"]["outcome"] == PASS),
            "considered": len(worthy)}


def find_loops(source, *, out_dir=None, fps=None, reader=None, gray=None,
               cache=None, min_frames=None, overlap_max=None, top=None,
               advantage_min=None, flow_weight=None, pixel_weight=None,
               head=None, head_weight=None, gif=True, decode=None, stride=None,
               max_frames=None, bridge_max=None) -> dict:
    """Найти петли в драйвинге. Дешёвое раньше дорогого, три исхода."""
    fps_source = FPS_UNKNOWN if fps is None else FPS_GIVEN
    min_frames = LOOP_MIN_FRAMES if min_frames is None else min_frames
    advantage_min = ADVANTAGE_MIN if advantage_min is None else advantage_min
    top = TOP_LOOPS if top is None else top
    max_frames = MAX_FRAMES if max_frames is None else max_frames
    bridge_max = BRIDGE_MAX_FRAMES if bridge_max is None else bridge_max
    t = time.perf_counter()
    steps = []
    src = Path(source)

    t0 = time.perf_counter()
    if src.is_dir():
        paths = frame_paths(src)
    elif src.is_file():
        from . import fork_video
        decode = fork_video.frames if decode is None else decode
        dest = Path(out_dir or ".") / "frames"
        got = decode(str(src), str(dest), overwrite=True)
        if got.get("outcome") != PASS:
            steps.append(("кадры", got["outcome"], got["note"],
                          time.perf_counter() - t0))
            return _report(got["outcome"], got["note"], t, steps, frames=0)
        paths = [Path(p) for p in got["paths"]]
        if fps is None:
            probed = got.get("fps_out") or got.get("fps_in")
            if probed:
                fps, fps_source = probed, FPS_PROBED
    else:
        note = f"{src} — не каталог кадров и не файл"
        steps.append(("кадры", UNMEASURED, note, time.perf_counter() - t0))
        return _report(UNMEASURED, note, t, steps, frames=0)

    n = len(paths)
    if n < min_frames + 1:
        note = (f"кадров {n}, а самая короткая петля требует {min_frames} плюс "
                f"кадр на производную. Материал короче петли — это измерение, "
                f"а не сбой прибора")
        steps.append(("кадры", FAIL, note, time.perf_counter() - t0))
        return _report(FAIL, note, t, steps, frames=n, scan=SCAN_FULL)
    if n > max_frames:
        note = (f"кадров {n}, потолок {max_frames} "
                f"({max_frames / framemath.WRAP_FPS / 60:.0f} минут при наших "
                f"{framemath.WRAP_FPS} к/с). Даже по прорежённой это "
                f"{n / (COARSE_STRIDE or 1) * 0.031 / 60:.0f}+ минут одного "
                f"только снятия поз — разбирать не беремся. Нарежьте материал")
        steps.append(("кадры", UNMEASURED, note, time.perf_counter() - t0))
        return _report(UNMEASURED, note, t, steps, frames=n, scan=SCAN_TOO_LONG)

    steps.append(("частота",
                  PASS if fps is not None else UNMEASURED,
                  (f"частота источника {fps} к/с ({fps_source})"
                   if fps is not None else
                   f"частота источника {FPS_UNKNOWN}: у каталога кадров её не "
                   f"записано нигде. Длины петель печатаются В КАДРАХ, секунды "
                   f"и план повторов — НЕТ. Задайте --fps, если знаете её"),
                  0.0))

    stride = (COARSE_STRIDE if n > COARSE_ABOVE_FRAMES else 1) \
        if stride is None else stride
    scan = SCAN_FULL if stride == 1 else SCAN_COARSE
    steps.append(("кадры", PASS,
                  f"кадров {n}, разбор по {scan}"
                  + ("" if stride == 1 else f" 1 из {stride}"),
                  time.perf_counter() - t0))

    cut = cuts(paths, gray=gray)
    steps.append(("резы", cut["outcome"], cut["note"], cut["elapsed"]))
    cut_set = sorted(cut["cuts"])

    index = list(range(0, n, stride))
    got = read_all([paths[k] for k in index], reader=reader, cache=cache)
    if got["unreadable"]:
        note = (f"позу снять нечем: {got['unreadable']} кадр(ов) не опрошены "
                f"({got['first_why']}). Это НЕ «петель нет»")
        steps.append(("позы", UNMEASURED, note, got["elapsed"]))
        return _report(UNMEASURED, note, t, steps, frames=n, taken=got["taken"],
                       scan=scan, stride=stride)

    who = presence(got["poses"], people=got["people"], index=index)
    coverage = got["taken"] / len(index)
    steps.append(("позы", PASS if coverage >= MIN_POSE_COVERAGE else UNMEASURED,
                  f"поза снята на {got['taken']} из {len(index)} опрошенных "
                  f"кадров ({coverage:.0%}), из кэша {got['cached']}, "
                  f"{got['elapsed'] / max(1, len(index) - got['cached']):.4f} "
                  f"с/кадр", got["elapsed"]))

    if who["crowd"]:
        note = (f"людей в кадре несколько (до {max(who['crowd'])}). Кого вести "
                f"— решает разметка `fork_props` (роль "
                f"{'протагонист'!r}); второго способа выбирать протагониста "
                f"здесь нет и не будет. Пока он не назван, детектор берёт "
                f"на каждом кадре первую попавшуюся рамку, и скелет прыгает с "
                f"человека на человека посреди клипа")
        steps.append(("люди", UNMEASURED, note, 0.0))
        return _report(UNMEASURED, note, t, steps, frames=n, taken=got["taken"],
                       scan=scan, stride=stride, crowd=who["crowd"])
    if got["taken"] == 0:
        note = (f"человека в кадре нет ни на одном из {len(index)} опрошенных "
                f"кадров. Это не «петель нет»: петли ищутся по телу")
        steps.append(("люди", UNMEASURED, note, 0.0))
        return _report(UNMEASURED, note, t, steps, frames=n, taken=0, scan=scan,
                       stride=stride)
    if who["long_gaps"]:
        spans = ", ".join(f"{index[a]}..{index[b]}" for a, b in who["long_gaps"])
        steps.append(("люди", UNMEASURED,
                      f"человек уходит из кадра: подряд без тела кадры {spans}. "
                      f"Петли через эти участки не выпускаются", 0.0))
    if coverage < MIN_POSE_COVERAGE:
        note = (f"поза снята только на {got['taken']} из {len(index)} кадров "
                f"({coverage:.0%}, планка {MIN_POSE_COVERAGE:.0%}). Отсутствие "
                f"петель на таком материале ничего не значит"
                + (f". Человек уходит из кадра с кадра {who['left_at']}"
                   if who["long_gaps"] else ""))
        return _report(UNMEASURED, note, t, steps, frames=n, taken=got["taken"],
                       coverage=round(coverage, 3), scan=scan, stride=stride,
                       left_at=who["left_at"])

    st = states(got["poses"])
    step_info = typical_step(st)
    if step_info["step"] is None or step_info["step"] <= 0:
        note = (f"{step_info['note']}. Стык не в чем мерить: единица измерения "
                f"— обычный шаг этого же клипа" if step_info["step"] is None
                else "клип не движется: обычный шаг равен нулю, ранжировать "
                     "стыки нечем")
        steps.append(("масштаб", UNMEASURED, note, 0.0))
        return _report(UNMEASURED, note, t, steps, frames=n, taken=got["taken"],
                       scan=scan, stride=stride)
    steps.append(("масштаб", PASS, step_info["note"], 0.0))

    import bisect

    gone = sorted(index[k] for a, b in who["long_gaps"] for k in range(a, b + 1))

    def blocked(i, j):
        if bisect.bisect_left(cut_set, i) < bisect.bisect_left(cut_set, j):
            return "рез внутри петли"
        if bisect.bisect_left(gone, i) < bisect.bisect_right(gone, j):
            return "человека нет в кадре внутри петли"
        return None

    t0 = time.perf_counter()
    store = keep_grays([(k, paths[k]) for k in index], gray=gray)
    pstep = pixel_step(store["grays"], index)
    steps.append(("картинка", PASS if pstep else UNMEASURED,
                  f"серых кадров в памяти {store['frames']}, "
                  f"{store['bytes'] / 1048576:.1f} МБ; типичный пиксельный "
                  f"переход " + (f"{pstep:.3f}" if pstep else
                                 "НЕ ИЗМЕРЕН — пиксельная ось выключена"),
                  store["elapsed"]))
    sim = similarity(st, fps=fps, min_frames=min_frames, index=index,
                     blocked=blocked, grays=store["grays"] if pstep else None)
    cands = score_pairs(sim, step_info["step"], flow_weight=flow_weight,
                        pix_step=pstep, pixel_weight=pixel_weight)
    sim_elapsed = time.perf_counter() - t0
    blocked_note = ("; ".join(f"{why}: {cnt}"
                              for why, cnt in sorted(sim["rejected"].items()))
                    or "нет")
    if not cands:
        note = (f"допустимых пар {sim['pairs']}, измерить не удалось ни одной. "
                f"Отвергнуто до измерения — {blocked_note}")
        steps.append(("кандидаты", UNMEASURED, note, sim_elapsed))
        return _report(UNMEASURED, note, t, steps, frames=n, taken=got["taken"],
                       scan=scan, stride=stride, pairs=sim["pairs"],
                       rejected=sim["rejected"])

    import numpy as np
    median_score = float(np.median([c["score"] for c in cands]))
    best = cands[0]
    advantage = median_score / best["score"] if best["score"] > 0 else math.inf
    steps.append(("кандидаты", PASS,
                  f"пар допустимых {sim['pairs']}, отвергнуто до измерения "
                  f"({blocked_note}), измерено {sim['measured']}, не смогли "
                  f"{sim['unmeasurable']}; лучший стык {best['score']} шага, "
                  f"типичный {median_score:.3f}, преимущество {advantage:.2f}x",
                  sim_elapsed))

    worthy = [c for c in cands
              if (median_score / c["score"] if c["score"] > 0 else math.inf)
              >= advantage_min]
    if not worthy:
        note = (f"ПЕТЕЛЬ НЕ НАШЛОСЬ ({scan}): ни одна пара не обошла типичную в "
                f"{advantage_min} раза, лучшая обошла в {advantage:.2f}. Так "
                f"выглядит материал без повтора — лучшая пара в нём выигрывает "
                f"только тем, что она короче. Поза снята на {got['taken']} из "
                f"{len(index)} опрошенных кадров, пар разобрано "
                f"{sim['measured']}, отвергнуто до измерения ({blocked_note})")
        return _report(FAIL, note, t, steps, frames=n, taken=got["taken"],
                       coverage=round(coverage, 3), pairs=sim["pairs"],
                       measured_pairs=sim["measured"],
                       unmeasurable_pairs=sim["unmeasurable"],
                       rejected=sim["rejected"], scan=scan, stride=stride,
                       advantage=round(advantage, 3),
                       typical_score=round(median_score, 3),
                       best_score=best["score"], candidates=len(cands))

    t0 = time.perf_counter()
    head_cache: dict = {}
    scale = head_scale(paths, reader=head, cache=head_cache)
    steps.append(("голова", scale["outcome"],
                  (f"типичное смещение головы {scale['step']:.2f} px по "
                   f"{scale['measured']} парам, снято кадров {scale['frames']}"
                   if scale["outcome"] == PASS else
                   f"ось головы ВЫКЛЮЧЕНА: {scale['reason']}. Петли выйдут "
                   f"помеченными «голова не проверена», а не молча годными"),
                  scale["elapsed"]))

    fine_poses = [0]

    def refine_one(cand):
        got_fine = refine_all([cand], paths, stride=stride, reader=reader,
                              cache=cache, fps=fps, min_frames=min_frames,
                              flow_weight=flow_weight, pixel_weight=pixel_weight,
                              blocked=blocked, gray=gray, pix_step=pstep)
        fine_poses[0] += got_fine["poses"]
        return got_fine["loops"][0]

    by_frame = {f: v for f, v in zip(index, st)}
    known = sorted(by_frame)

    def state_at(frame):
        if frame in by_frame:
            return by_frame[frame]
        pos = bisect.bisect_left(known, frame)
        near = [k for k in (pos - 1, pos) if 0 <= k < len(known)]
        if not near:
            return None
        pick = min((known[k] for k in near), key=lambda k: abs(k - frame))
        return by_frame[pick] if abs(pick - frame) <= stride else None

    def local_scale(i, j):
        """Типичный шаг ВНУТРИ петли: чем меряется ДЛИНА МОСТА (не порядок)."""
        inner = [k for k in index if i <= k <= j]
        sub = [by_frame[k] for k in inner]
        return {"поза": typical_step(sub)["step"],
                "пиксели": (pixel_step(store["grays"], inner)
                            if pstep else None)}

    chosen = pick_finalists(
        worthy, paths, top=top, overlap_max=overlap_max, head=head,
        head_weight=head_weight, flow_weight=flow_weight,
        pixel_weight=pixel_weight, bridge_max=bridge_max,
        scale=scale, refine=refine_one, local=local_scale, state_at=state_at,
        typical=step_info["step"])
    steps.append(("финалисты", PASS,
                  f"принято {len(chosen['kept'])}; МОСТЫ: посчитано "
                  f"{chosen['bridge_measured']}, отвергнуто длинных "
                  f"{chosen['dropped_bridge']} (из них по голове "
                  f"{chosen['dropped_head']}) при потолке {bridge_max} кадров, "
                  f"не смогли посчитать {chosen['unchecked']}; отвергнуто: по "
                  f"пересечению кадров {chosen['dropped_overlap']}, КАК ПОВТОР "
                  f"ТОГО ЖЕ ДВИЖЕНИЯ {chosen['dropped_duplicate']}; движение "
                  f"не сверялось у {chosen['dup_unmeasured']}; голову "
                  f"спрашивали {chosen['head_tried']} раз, кадров головы "
                  f"{scale['frames'] + chosen['head_frames']}, поз на "
                  f"уточнение {fine_poses[0]}"
                  + ("; БЮДЖЕТ ГОЛОВЫ ИСЧЕРПАН — поиск остановлен, "
                     "непроверенных не выпускаем" if chosen["head_budget_hit"]
                     else ""),
                  round(time.perf_counter() - t0, 4) - scale["elapsed"]))

    loops = []
    for rank, c in enumerate(chosen["kept"], 1):
        loop = dict(c)
        loop["rank"] = rank
        loop["seconds"] = None if fps is None else round(c["frames"] / fps, 2)
        loop["advantage"] = (round(median_score / c["score"], 2)
                             if c["score"] > 0 else None)
        loop["advantage_is_bound"] = c["bridge"]["outcome"] != PASS
        loop["repeats"] = repeat_plan(c["frames"], fps=fps)
        loop["gif"] = None
        if gif and out_dir is not None:
            loop["gif"] = make_gif(
                paths, c["i"], c["j"],
                Path(out_dir) / f"loop_{c['i']:04d}_{c['j']:04d}.gif", fps=fps)
            if fps is None and loop["gif"]:
                loop["gif"]["note"] = (
                    f"скорость показа взята {framemath.WRAP_FPS} к/с, потому "
                    f"что частота источника неизвестна: движение на GIF может "
                    f"идти быстрее или медленнее настоящего")
        loops.append(loop)

    short = ("" if len(loops) >= top else
             f" РАЗНЫХ ДВИЖЕНИЙ МЕНЬШЕ ЗАКАЗАННЫХ {top}: набралось "
             f"{len(loops)}, схлопнуто как повтор того же движения "
             f"{chosen['dropped_duplicate']}. Добивать список повторами нельзя: "
             f"клиент увидит пять карточек и решит, что у него пять вариантов.")
    note = (f"петель принято {len(loops)} из {len(worthy)} прошедших планку "
            f"преимущества {advantage_min}x (всего пар с оценкой {len(cands)}, "
            f"отброшено по пересечению {chosen['dropped_overlap']}, как повтор "
            f"движения {chosen['dropped_duplicate']}, ДЛИННЫМ МОСТОМ "
            f"{chosen['dropped_bridge']} при потолке {bridge_max} кадров, "
            f"мост посчитан у {chosen['bridge_measured']}, не смогли "
            f"посчитать у {chosen['unchecked']}); кадров "
            f"{n}, опрошено {len(index)} ({scan}), поза снята на "
            f"{got['taken']}, резов {len(cut_set)}, пар разобрано "
            f"{sim['measured']}, не смогли {sim['unmeasurable']}.{short} Это "
            f"РАНГ, а не вердикт: планки бесшовности для расстояния поз у "
            f"проекта нет")
    return _report(PASS, note, t, steps, frames=n, taken=got["taken"],
                   fps=fps, fps_source=fps_source,
                   pixel_step=None if pstep is None else round(pstep, 4),
                   coverage=round(coverage, 3), pairs=sim["pairs"],
                   measured_pairs=sim["measured"],
                   unmeasurable_pairs=sim["unmeasurable"],
                   rejected=sim["rejected"], cuts=cut_set, scan=scan,
                   stride=stride, asked=top,
                   candidates=len(cands), worthy=len(worthy),
                   dropped_overlap=chosen["dropped_overlap"],
                   dropped_head=chosen["dropped_head"],
                   dropped_bridge=chosen["dropped_bridge"],
                   bridge_max=bridge_max,
                   bridge_measured=chosen["bridge_measured"],
                   dropped_duplicate=chosen["dropped_duplicate"],
                   dup_unmeasured=chosen["dup_unmeasured"],
                   head_step=None if scale["step"] is None else round(scale["step"], 3),
                   head_tried=chosen["head_tried"],
                   head_frames=scale["frames"] + chosen["head_frames"],
                   head_unchecked=chosen["unchecked"],
                   advantage=round(advantage, 3),
                   typical_score=round(median_score, 3),
                   typical_step=round(step_info["step"], 4),
                   pose_seconds=got["elapsed"],
                   pose_frames=len(index) + fine_poses[0],
                   cut_seconds=cut["elapsed"], cached=got["cached"],
                   loops=loops)


def table(report) -> str:
    """Таблица петель для человека."""
    fps = report.get("fps")
    head = (f"{'#':>2} {'кадры':>11} {'кадров':>6} {'сек':>6} {'суст':>4} "
            f"{'мост':>6} | {'поза':>6} {'поток':>6} {'пиксели':>7} "
            f"{'голова':>7} (локальных шага) | {'стык':>6} {'выигрыш':>8} "
            f"(клиповых)  повторы -> с        GIF")
    rows = [head]
    for lp in report.get("loops", []):
        rep = (", ".join(f"{r['repeats']}x={r['frames']}к/{r['seconds']}с"
                         for r in lp["repeats"])
               or ("частота неизвестна — план не считается"
                   if fps is None else "нет в полосе 5-10 с"))
        g = lp.get("gif") or {}
        gtxt = (f"{Path(g['path']).name} {g['frames']}к {g['bytes']}Б"
                if g.get("path") else "-")
        secs = "—" if lp.get("seconds") is None else f"{lp['seconds']}"
        axes = lp.get("bridge_seams") or {}

        def cell(name):
            v = axes.get(name)
            return "н/п" if v is None else f"{v}"
        cost = lp.get("bridge") or {}
        if cost.get("frames") is not None:
            br = f"{cost['frames']}к"
        elif cost.get("floor") is not None:
            br = f"≥{cost['floor']}к"
        else:
            br = "н/п"
        adv = ("—" if lp.get("advantage") is None else
               ("≤" if lp.get("advantage_is_bound") else "")
               + f"{lp['advantage']}x")
        rows.append(f"{lp['rank']:>2} {lp['i']:>5}..{lp['j']:<5} "
                    f"{lp['frames']:>6} {secs:>6} {str(lp.get('joints')):>4} "
                    f"{br:>6} | {cell('поза'):>6} {cell('поток'):>6} "
                    f"{cell('пиксели'):>7} {cell('голова'):>7} "
                    f"{'':>17} | {lp['score']:>6} {adv:>8} {'':>10}  {rep}  "
                    f"{gtxt}")
    if fps is None:
        rows.append("    секунды и план повторов не печатаются: частота "
                    "источника неизвестна (см. шаг «частота»)")
    for lp in report.get("loops", []):
        if lp.get("head_state") == UNMEASURED:
            rows.append(f"    петля {lp['rank']}: ГОЛОВА НЕ ПРОВЕРЕНА — "
                        f"{lp.get('head_note')}")
        if lp.get("pixel_axis_off"):
            rows.append(f"    петля {lp['rank']}: пиксельная ось клипа НЕ "
                        f"ИЗМЕРЕНА, мост посчитан по трём осям из четырёх и "
                        f"потому может быть только ДЛИННЕЕ напечатанного")
        missed = (lp.get("bridge") or {}).get("unmeasured")
        if missed:
            rows.append(f"    петля {lp['rank']}: ЦЕНА МОСТА НЕ ПОСЧИТАНА, не "
                        f"измерены оси {', '.join(missed)} — петля стоит НИЖЕ "
                        f"всех измеренных, а «мост» и «выигрыш» у неё границы, "
                        f"а не числа")
    if report.get("dropped_bridge"):
        rows.append(f"    отвергнуто длинным мостом: {report['dropped_bridge']} "
                    f"(потолок {report.get('bridge_max')} кадров"
                    + ("" if fps is None else
                       f", {report['bridge_max'] / fps:.2f} с при {fps} к/с")
                    + ")")
    if report.get("dropped_duplicate"):
        rows.append(f"    схлопнуто как повтор того же движения: "
                    f"{report['dropped_duplicate']} (сверка по "
                    f"{DUP_PHASES} точкам фазы, порог "
                    f"{DUPLICATE_MAX_STEPS} типичных шага)")
    if any(lp.get("joints") not in (None, len(pose.BODY_POINTS))
           for lp in report.get("loops", [])):
        rows.append(f"    «суст» — сколько суставов из {len(pose.BODY_POINTS)} "
                    f"реально сравнивалось: остальные детектор не видел, и в "
                    f"оценку позы они не вошли")
    return "\n".join(rows)


def main(argv=None) -> int:
    import argparse

    ap = argparse.ArgumentParser(
        prog="python3 -m lipsync.fork_looper",
        description="Отбор петель в драйвинге: ранжирует стыки и кладёт GIF.")
    ap.add_argument("source", help="каталог кадров или видеофайл")
    ap.add_argument("--out", default="looper_out", help="куда класть GIF-ы")
    ap.add_argument("--fps", type=int, default=None)
    ap.add_argument("--min-frames", type=int, default=None)
    ap.add_argument("--top", type=int, default=None)
    ap.add_argument("--overlap-max", type=float, default=None)
    ap.add_argument("--cache", default=None, help="JSON с уже снятыми позами")
    ap.add_argument("--stride", type=int, default=None,
                    help="шаг прореживания; по умолчанию 1, а на длинном "
                         "материале включается сам")
    ap.add_argument("--max-frames", type=int, default=None)
    ap.add_argument("--no-gif", action="store_true")
    a = ap.parse_args(argv)

    rep = find_loops(a.source, out_dir=a.out, fps=a.fps,
                     min_frames=a.min_frames, top=a.top,
                     overlap_max=a.overlap_max, cache=a.cache,
                     stride=a.stride, max_frames=a.max_frames,
                     gif=not a.no_gif)
    print(f"ИСХОД: {rep['outcome']}")
    for s in rep["steps"]:
        print(f"  [{s['outcome']:>18}] {s['step']:<12} {s['seconds']:>7.3f} с  "
              f"{s['note']}")
    if rep.get("loops"):
        print()
        print(table(rep))
    print()
    print(rep["note"])
    return EXIT_BY_OUTCOME[rep["outcome"]]


if __name__ == "__main__":
    raise SystemExit(main())
