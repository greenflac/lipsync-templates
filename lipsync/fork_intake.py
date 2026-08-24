"""Приём входов сквозного стенда: драйвинг, фотография клиента, стилевой референс."""

from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path

from . import fork_looper, fork_video
from .fork_identity import FAIL, PASS, UNMEASURED


from .fork_identity import SAME_PERSON_MAX  # noqa: E402

from .fork_looper import CUT_JUMP  # noqa: E402

from .pose import MIN_VISIBILITY  # noqa: E402

from .identity_arcface import MIN_FACE_PX  # noqa: E402

MIN_SCENE_SECONDS = 3.0

ORPHAN_WRIST_WARN = 0.10

WINDOW_FPS_PROVEN = 30.0

FRAME_COUNT_EXACT = 0

PHOTO_PEOPLE_EXPECTED = 1

VSYNC_ADVICE = (
    "распаковывать только с `-vsync 0` (в новых ffmpeg — "
    "`-fps_mode passthrough`, ИЗМЕРЕНО: оба дают 305 на "
    "driving_selfie): без него ffmpeg ПОДДЕЛЫВАЕТ пропущенные "
    "кадры дублями, подгоняя поток под свою решётку"
)

EXIT_BY_OUTCOME = fork_looper.EXIT_BY_OUTCOME


def read_count_frames(path) -> dict:
    """Спросить ffprobe ПОКАДРОВО. ТОЧКА ВНЕДРЕНИЯ: тест подменяет целиком."""
    if shutil.which(fork_video.FFPROBE_BIN) is None:
        return {
            "ran": False,
            "code": None,
            "out": "",
            "err": "",
            "why": (f"{fork_video.FFPROBE_BIN} не найден: спросить нечем. Это НЕ «файл плохой»"),
        }
    try:
        raw = subprocess.run(
            [
                fork_video.FFPROBE_BIN,
                "-v",
                "error",
                "-count_frames",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=nb_read_frames,avg_frame_rate,duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            timeout=fork_video.DECODE_TIMEOUT_S,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ran": False,
            "code": None,
            "out": "",
            "err": "",
            "why": f"{fork_video.FFPROBE_BIN} не отработал: {str(exc)[:120]}",
        }
    return {
        "ran": True,
        "code": raw.returncode,
        "out": raw.stdout or "",
        "err": raw.stderr or "",
        "why": "",
    }


def read_decoded_frames(path, *, vsync0: bool) -> dict:
    """Сколько кадров ВЫДАЛ БЫ распаковщик. ТОЧКА ВНЕДРЕНИЯ."""
    if shutil.which(fork_video.FFMPEG_BIN) is None:
        return {
            "ran": False,
            "code": None,
            "out": "",
            "err": "",
            "why": (
                f"{fork_video.FFMPEG_BIN} не найден: посчитать "
                f"распакованное нечем. Это НЕ «видео плохое»"
            ),
        }
    argv = [
        fork_video.FFMPEG_BIN,
        "-nostdin",
        "-v",
        "error",
        "-stats",
        "-i",
        str(path),
        "-an",
        "-vf",
        "scale=16:16",
    ]
    if vsync0:
        argv += ["-vsync", "0"]
    argv += ["-f", "image2", "-update", "1", "-y", "/dev/null"]
    try:
        raw = subprocess.run(
            argv, capture_output=True, text=True, timeout=fork_video.DECODE_TIMEOUT_S
        )
    except subprocess.TimeoutExpired:
        return {
            "ran": False,
            "code": None,
            "out": "",
            "err": "",
            "why": (
                f"{fork_video.FFMPEG_BIN} не уложился в "
                f"{fork_video.DECODE_TIMEOUT_S} с: сколько кадров "
                f"вышло — НЕИЗВЕСТНО"
            ),
        }
    except (OSError, subprocess.SubprocessError) as exc:
        return {
            "ran": False,
            "code": None,
            "out": "",
            "err": "",
            "why": f"{fork_video.FFMPEG_BIN} не отработал: {str(exc)[:120]}",
        }
    return {
        "ran": True,
        "code": raw.returncode,
        "out": raw.stdout or "",
        "err": raw.stderr or "",
        "why": "",
    }


def read_faces(path) -> dict:
    """Все лица кадра, а не только самое крупное. ТОЧКА ВНЕДРЕНИЯ."""
    try:
        from . import identity_arcface

        faces = identity_arcface._analyzer().get(identity_arcface._read_bgr(path))
        out = []
        for f in faces:
            x0, y0, x1, y1 = (float(v) for v in f.bbox)
            out.append(
                {"face_px": round(min(x1 - x0, y1 - y0)), "det_score": round(float(f.det_score), 3)}
            )
        out.sort(key=lambda d: d["face_px"], reverse=True)
        return {"faces": out, "why": ""}
    except Exception as exc:  # noqa: BLE001 — причин «спросить нечем» много
        return {"faces": None, "why": f"{type(exc).__name__}: {str(exc)[:200]}"}


def read_style_card(path) -> dict:
    """Карточка стиля. ТОЧКА ВНЕДРЕНИЯ, и она же — единственный вход"""
    try:
        from creative_eval.style import style_card  # noqa: PLC0415

        return {"card": style_card(str(path)), "why": ""}
    except Exception as exc:  # noqa: BLE001
        return {"card": None, "why": f"{type(exc).__name__}: {str(exc)[:200]}"}


def tally(checked: int, violations: int, unmeasured: int) -> dict:
    """Три числа рядом с вердиктом, и вердикт, выведенный ИЗ НИХ."""
    out = {"checked": int(checked), "violations": int(violations), "unmeasured": int(unmeasured)}
    if checked == 0:
        out["outcome"] = UNMEASURED
    elif violations > 0:
        out["outcome"] = FAIL
    elif unmeasured > 0:
        out["outcome"] = UNMEASURED
    else:
        out["outcome"] = PASS
    return out


def parse_count_frames(text: str) -> dict:
    """Ответ `ffprobe -count_frames` -> число кадров. Тест — на литерале."""
    import json

    try:
        data = json.loads(text or "")
    except (ValueError, TypeError):
        return {
            "ok": False,
            "frames": None,
            "fps": None,
            "seconds": None,
            "why": (f"ответ ffprobe не разобрался как JSON: {(text or '')[:120]!r}"),
        }
    streams = (data or {}).get("streams") or []
    if not streams:
        return {
            "ok": False,
            "frames": None,
            "fps": None,
            "seconds": None,
            "why": "видеопотока в ответе нет: считать нечего",
        }
    s = streams[0]
    raw = s.get("nb_read_frames")
    try:
        frames = int(raw)
    except (TypeError, ValueError):
        return {
            "ok": False,
            "frames": None,
            "fps": None,
            "seconds": None,
            "why": (f"nb_read_frames = {raw!r}: ffprobe кадры НЕ СЧИТАЛ. Это не «кадров нет»"),
        }
    if frames <= 0:
        return {
            "ok": False,
            "frames": None,
            "fps": None,
            "seconds": None,
            "why": f"ffprobe насчитал {frames} кадров: считать нечего",
        }
    fps = fork_video._ratio(s.get("avg_frame_rate"))
    try:
        seconds = float(s.get("duration"))
    except (TypeError, ValueError):
        seconds = None
    return {"ok": True, "frames": frames, "fps": fps, "seconds": seconds, "why": ""}


def parse_decoded_frames(text: str) -> dict:
    """Строка `-stats` от ffmpeg -> сколько кадров он выдал. Тест — на литерале."""
    import re

    hits = re.findall(r"frame=\s*(\d+)", text or "")
    if not hits:
        return {
            "ok": False,
            "frames": None,
            "why": (
                f"в ответе ffmpeg нет ни одного `frame=`: сколько "
                f"кадров вышло — НЕИЗВЕСТНО. Хвост: "
                f"{(text or '')[-120:]!r}"
            ),
        }
    return {"ok": True, "frames": int(hits[-1]), "why": ""}


def timestamp_verdict(probed: int | None, plain: int | None, fixed: int | None) -> dict:
    """Дырки во временных метках. Три исхода, и совет вместо догадки."""
    known = [v for v in (probed, plain, fixed) if v is not None]
    if len(known) < 3:
        missing = [
            n
            for n, v in (("ffprobe", probed), ("ffmpeg", plain), ("ffmpeg -vsync 0", fixed))
            if v is None
        ]
        return {
            **tally(0, 0, 1),
            "probed": probed,
            "plain": plain,
            "fixed": fixed,
            "gap": None,
            "advice": VSYNC_ADVICE,
            "note": (
                f"счётчики не сняты: {', '.join(missing)}. Это НЕ "
                f"«кадры на месте» и НЕ «файл битый»"
            ),
        }
    gap = plain - probed
    if abs(gap) <= FRAME_COUNT_EXACT:
        return {
            **tally(1, 0, 0),
            "probed": probed,
            "plain": plain,
            "fixed": fixed,
            "gap": gap,
            "advice": "",
            "note": (
                f"ffprobe {probed}, ffmpeg {plain}, ffmpeg -vsync 0 "
                f"{fixed}: расхождение {gap}, дырок во временных "
                f"метках не видно"
            ),
        }
    healed = fixed == probed
    return {
        **tally(1, 1, 0),
        "probed": probed,
        "plain": plain,
        "fixed": fixed,
        "gap": gap,
        "advice": VSYNC_ADVICE,
        "note": (
            f"ffprobe {probed}, ffmpeg БЕЗ ключей {plain} "
            f"(расхождение {gap:+d}), с -vsync 0 {fixed}. В файле "
            f"пропущены кадры, и обычная распаковка их ПОДДЕЛЫВАЕТ "
            f"дублями"
            + (
                f"; {VSYNC_ADVICE}"
                if healed
                else f"; и `-vsync 0` НЕ ЛЕЧИТ ({fixed} против {probed}) — "
                f"материал в работу не брать"
            )
        ),
    }


def scenes(n_frames: int, cut_list) -> list:
    """Разбиение на сцены по швам. Чистая арифметика, тест — на литералах."""
    if n_frames <= 0:
        return []
    marks = sorted({int(c) for c in (cut_list or []) if 0 <= int(c) < n_frames - 1})
    out, start = [], 0
    for k in marks:
        out.append({"start": start, "end": k, "frames": k - start + 1})
        start = k + 1
    out.append({"start": start, "end": n_frames - 1, "frames": n_frames - 1 - start + 1})
    return out


def scene_length_verdict(
    scene_list, fps: float | None, *, min_seconds: float | None = None
) -> dict:
    """Каждая ли сцена не короче планки. КРИТЕРИЙ ПРИЁМА, а не пожелание."""
    bar = MIN_SCENE_SECONDS if min_seconds is None else min_seconds
    if not scene_list:
        return {
            **tally(0, 0, 1),
            "bar_seconds": bar,
            "short": [],
            "seconds": [],
            "note": "сцен нет: разметка не снята, длину мерить не у чего",
        }
    if not fps or fps <= 0:
        return {
            **tally(0, 0, len(scene_list)),
            "bar_seconds": bar,
            "short": [],
            "seconds": [],
            "note": (
                f"частота не снята: {len(scene_list)} сцен есть, а "
                f"перевести кадры в секунды нечем. Это НЕ «сцены "
                f"короткие» и НЕ «сцены длинные»"
            ),
        }
    secs = [round(s["frames"] / fps, 3) for s in scene_list]
    short = [i for i, v in enumerate(secs) if v < bar]
    return {
        **tally(len(scene_list), len(short), 0),
        "bar_seconds": bar,
        "short": short,
        "seconds": secs,
        "note": (
            f"сцен {len(scene_list)}, планка {bar} с, короче планки "
            f"{len(short)}"
            + (
                f": номера {short[:10]}, длины {[secs[i] for i in short[:10]]}"
                if short
                else f"; самая короткая {min(secs)} с, самая длинная {max(secs)} с"
            )
        ),
    }


def is_orphan_wrist(points) -> bool | None:
    """Один кадр: есть ли на нём сиротская кисть. Определение — здесь и только."""
    if not points:
        return None

    def seen(name):
        p = points.get(name)
        if p is None or len(p) < 3:
            return False
        x, y, vis = float(p[0]), float(p[1]), float(p[2])
        return vis >= MIN_VISIBILITY and 0.0 <= x <= 1.0 and 0.0 <= y <= 1.0

    for side in ("l", "r"):
        if seen(f"{side}_wrist") and not (seen(f"{side}_elbow") and seen(f"{side}_shoulder")):
            return True
    return False


def orphan_verdict(share: float | None, checked: int, unmeasured: int) -> dict:
    """МЯГКАЯ ось: доля сирот и предупреждение. Вердикт НЕ РОНЯЕТ."""
    if share is None or checked == 0:
        return {
            **tally(0, 0, max(1, unmeasured)),
            "share": None,
            "warn": False,
            "bar": ORPHAN_WRIST_WARN,
            "note": (
                "позу снять не удалось ни на одном кадре: доля сирот "
                "НЕ ИЗМЕРЕНА. Это не «сирот нет»"
            ),
        }
    warn = share >= ORPHAN_WRIST_WARN
    base = tally(checked, 0, unmeasured)
    return {
        **base,
        "share": round(share, 4),
        "warn": warn,
        "bar": ORPHAN_WRIST_WARN,
        "note": (
            f"сиротских кистей {round(share * 100, 1)}% "
            f"({checked} кадров с позой, {unmeasured} без)"
            + (
                f". ПРЕДУПРЕЖДЕНИЕ: доля не ниже "
                f"{round(ORPHAN_WRIST_WARN * 100)}%. Это ПОПРАВКА К "
                f"ОЖИДАНИЮ по личности, а не отказ: ИЗМЕРЕНО, что 21% "
                f"сирот дали ArcFace 0.2960 (81/99 в баре "
                f"{SAME_PERSON_MAX}) против 0.2430 (98/99) при 0%, то "
                f"есть около 0.05 по личности. Составитель шаблонов посмотрел "
                f"выход с 21% и назвал кисти правильными"
                if warn
                else f"; ниже планки предупреждения {round(ORPHAN_WRIST_WARN * 100)}%"
            )
        ),
    }


def face_size_verdict(
    sizes: list, no_face: int, unmeasured: int, *, min_face_px: int | None = None
) -> dict:
    """Хватает ли лицу пикселей, чтобы личность вообще было чем мерить."""
    bar = MIN_FACE_PX if min_face_px is None else min_face_px
    checked = len(sizes) + no_face
    if checked == 0:
        return {
            **tally(0, 0, max(1, unmeasured)),
            "bar_px": bar,
            "small": 0,
            "no_face": no_face,
            "min": None,
            "max": None,
            "note": ("лицо не спрашивали ни на одном кадре: размер НЕ ИЗМЕРЕН. Это не «лица нет»"),
        }
    small = [v for v in sizes if v < bar]
    hurt = len(small) + no_face
    warn = (
        (
            f"; ПРЕДУПРЕЖДЕНИЕ: {hurt} из {checked} кадров непригодны для "
            f"ArcFace — личность на выходе СУДИТ ОПЕРАТОР ГЛАЗАМИ, прибор "
            f"здесь не судья"
        )
        if hurt
        else ""
    )
    return {
        **tally(checked, 0, unmeasured),
        "bar_px": bar,
        "small": len(small),
        "no_face": no_face,
        "hurt": hurt,
        "min": min(sizes) if sizes else None,
        "max": max(sizes) if sizes else None,
        "note": (
            f"планка {bar}px: кадров {checked}, лицо найдено на "
            f"{len(sizes)}, мельче планки {len(small)}, без лица "
            f"{no_face}"
            + (f"; размах {min(sizes)}..{max(sizes)} px" if sizes else "")
            + (f", не спросили {unmeasured}" if unmeasured else "")
            + warn
        ),
    }


def window(scene_list, product_seconds: float, fps: float | None) -> dict:
    """Границы окна В НОМЕРАХ КАДРОВ. По времени резать НЕЛЬЗЯ."""
    if not scene_list:
        return {
            **tally(0, 0, 1),
            "start": None,
            "end": None,
            "frames": None,
            "scene": None,
            "note": "разметки сцен нет: выбирать окно не из чего",
        }
    if not fps or fps <= 0:
        return {
            **tally(0, 0, len(scene_list)),
            "start": None,
            "end": None,
            "frames": None,
            "scene": None,
            "note": (
                "частота не снята: продуктовую длину в кадры "
                "перевести нечем. Догадку 30 не подставляем"
            ),
        }
    need = int(round(product_seconds * fps))
    if need <= 0:
        return {
            **tally(0, 0, 1),
            "start": None,
            "end": None,
            "frames": None,
            "scene": None,
            "note": (
                f"продуктовая длина {product_seconds} с при {fps} к/с "
                f"— это {need} кадров: резать нечего"
            ),
        }
    best = max(range(len(scene_list)), key=lambda i: scene_list[i]["frames"])
    have = scene_list[best]["frames"]
    if have < need:
        return {
            **tally(len(scene_list), 1, 0),
            "start": None,
            "end": None,
            "frames": None,
            "scene": None,
            "note": (
                f"нужно {need} кадров ({product_seconds} с при {fps} "
                f"к/с), самая длинная сцена {have} кадров "
                f"({round(have / fps, 3)} с): окно НЕ ВМЕЩАЕТСЯ"
            ),
        }
    pad = (have - need) // 2
    start = scene_list[best]["start"] + pad
    end = start + need - 1
    return {
        **tally(len(scene_list), 0, 0),
        "start": start,
        "end": end,
        "frames": need,
        "scene": best,
        "note": (
            f"окно {start}..{end} ({need} кадров, "
            f"{round(need / fps, 3)} с) из сцены {best} "
            f"({scene_list[best]['start']}..{scene_list[best]['end']}, "
            f"{have} кадров), поля по {pad} кадров с каждой стороны"
        ),
    }


def window_argv(video_path, out_path, start: int, end: int, *, fps: float | None = None) -> list:
    """Команда вырезки окна. Собирается ОТДЕЛЬНО от запуска: состав команды —"""
    if not isinstance(start, int) or not isinstance(end, int) or start < 0:
        raise ValueError(f"границы окна {start!r}..{end!r}: ждали целые от нуля")
    if end < start:
        raise ValueError(f"границы окна {start}..{end}: конец раньше начала")
    rate = WINDOW_FPS_PROVEN if fps is None else float(fps)
    if rate <= 0:
        raise ValueError(f"частота {fps!r}: ждали положительное число")
    return [
        fork_video.FFMPEG_BIN,
        "-v",
        "error",
        "-y",
        "-i",
        str(video_path),
        "-vf",
        f"select='between(n\\,{start}\\,{end})',setpts=N/{rate:g}/TB",
        "-an",
        str(out_path),
    ]


def driving_intake(
    video_path,
    frame_paths=None,
    *,
    product_seconds=None,
    prober=None,
    decoder=None,
    gray=None,
    pose_reader=None,
    face_prober=None,
) -> dict:
    """ПРИЁМ ДРАЙВИНГА: пять осей, из них четыре жёсткие и одна мягкая."""
    t0 = time.perf_counter()
    prober = read_count_frames if prober is None else prober
    decoder = read_decoded_frames if decoder is None else decoder
    gray = fork_looper.read_gray if gray is None else gray
    pose_reader = fork_looper.read_pose if pose_reader is None else pose_reader
    if face_prober is None:

        def face_prober(p):
            from . import identity_arcface

            return identity_arcface.face_detail(p)

    axes, steps = {}, {}

    t = time.perf_counter()
    raw = prober(video_path)
    probed = (
        parse_count_frames(raw.get("out", ""))
        if raw.get("ran")
        else {"ok": False, "frames": None, "fps": None, "seconds": None, "why": raw.get("why", "")}
    )
    plain = decoder(video_path, vsync0=False)
    fixed = decoder(video_path, vsync0=True)
    p_n = (
        parse_decoded_frames(plain.get("err", ""))
        if plain.get("ran")
        else {"ok": False, "frames": None, "why": plain.get("why", "")}
    )
    f_n = (
        parse_decoded_frames(fixed.get("err", ""))
        if fixed.get("ran")
        else {"ok": False, "frames": None, "why": fixed.get("why", "")}
    )
    axes["timestamps"] = timestamp_verdict(
        probed.get("frames"), p_n.get("frames"), f_n.get("frames")
    )
    axes["timestamps"]["why"] = "; ".join(
        w for w in (probed.get("why"), p_n.get("why"), f_n.get("why")) if w
    )
    steps["timestamps"] = round(time.perf_counter() - t, 3)
    fps = probed.get("fps")
    seconds = probed.get("seconds")

    paths = list(frame_paths or [])
    n = len(paths)

    t = time.perf_counter()
    if not paths:
        axes["cuts"] = {
            **tally(0, 0, 1),
            "cuts": [],
            "bar": CUT_JUMP,
            "note": ("кадров не подано: швы искать не в чем. Это НЕ «швов нет»"),
        }
        marks = []
    else:
        c = fork_looper.cuts(paths, gray=gray)
        marks = c.get("cuts") or []
        axes["cuts"] = {
            **(tally(len(paths) - 1, 0, 0) if c.get("outcome") != UNMEASURED else tally(0, 0, 1)),
            "cuts": marks,
            "bar": CUT_JUMP,
            "note": c.get("note", ""),
        }
    steps["cuts"] = round(time.perf_counter() - t, 3)

    scene_list = scenes(n, marks) if n else []
    axes["scenes"] = scene_length_verdict(scene_list, fps)

    t = time.perf_counter()
    orphans = seen_poses = pose_blind = 0
    sizes, no_face, face_blind = [], 0, 0
    for p in paths:
        r = pose_reader(str(p))
        if r.get("why"):
            pose_blind += 1
        else:
            verdict = is_orphan_wrist(r.get("points"))
            if verdict is None:
                pose_blind += 1
            else:
                seen_poses += 1
                orphans += 1 if verdict else 0
        try:
            d = face_prober(str(p))
        except Exception:  # noqa: BLE001 — «спросить нечем» на этом кадре
            face_blind += 1
        else:
            if d is None:
                no_face += 1
            else:
                sizes.append(int(d["face_px"]))
    axes["orphan_wrists"] = orphan_verdict(
        (orphans / seen_poses) if seen_poses else None, seen_poses, pose_blind
    )
    axes["face_size"] = face_size_verdict(sizes, no_face, face_blind)
    steps["pose_and_face"] = round(time.perf_counter() - t, 3)

    axes["window"] = (
        window(scene_list, product_seconds, fps)
        if product_seconds is not None
        else {
            **tally(0, 0, 1),
            "start": None,
            "end": None,
            "frames": None,
            "scene": None,
            "note": "продуктовая длина не задана: окно не выбирали",
        }
    )

    return _report(
        "драйвинг",
        video_path,
        axes,
        steps,
        t0,
        soft=("orphan_wrists", "window"),
        extra={"fps": fps, "seconds": seconds, "frames": n, "scenes": scene_list},
    )


def photo_intake(photo_path, *, faces_prober=None) -> dict:
    """ПРИЁМ ФОТОГРАФИИ КЛИЕНТА: лицо найдено, размер в px, один человек."""
    t0 = time.perf_counter()
    faces_prober = read_faces if faces_prober is None else faces_prober
    r = faces_prober(str(photo_path))
    axes = {}
    if r.get("why") or r.get("faces") is None:
        blind = {
            **tally(0, 0, 1),
            "note": (f"спросить нечем: {r.get('why') or 'детектор молчит'}. Это НЕ «лица нет»"),
        }
        axes = {"face_found": dict(blind), "face_size": dict(blind), "one_person": dict(blind)}
        return _report("фото клиента", photo_path, axes, {}, t0, soft=())

    faces = r["faces"]
    axes["face_found"] = {
        **tally(1, 0 if faces else 1, 0),
        "faces": len(faces),
        "note": (
            f"лиц найдено {len(faces)}"
            if faces
            else "лица не найдено: якорь личности брать не с чего"
        ),
    }
    if faces:
        biggest = faces[0]["face_px"]
        axes["face_size"] = {
            **tally(1, 0 if biggest >= MIN_FACE_PX else 1, 0),
            "face_px": biggest,
            "bar_px": MIN_FACE_PX,
            "note": (f"самое крупное лицо {biggest} px при планке {MIN_FACE_PX} px"),
        }
    else:
        axes["face_size"] = {
            **tally(0, 0, 1),
            "face_px": None,
            "bar_px": MIN_FACE_PX,
            "note": "лица нет: размер мерить не у чего",
        }
    axes["one_person"] = {
        **tally(1, 0 if len(faces) == PHOTO_PEOPLE_EXPECTED else 1, 0),
        "faces": len(faces),
        "expected": PHOTO_PEOPLE_EXPECTED,
        "note": (
            f"людей на кадре {len(faces)}, ждали {PHOTO_PEOPLE_EXPECTED}"
            + (
                ""
                if len(faces) == PHOTO_PEOPLE_EXPECTED
                else ". Личность меряется по САМОМУ КРУПНОМУ лицу, то есть "
                "выбирает его прибор, а не человек"
            )
        ),
    }
    return _report("фото клиента", photo_path, axes, {}, t0, soft=())


def style_intake(ref_path, *, card_reader=None) -> dict:
    """ПРИЁМ СТИЛЕВОГО РЕФЕРЕНСА: читается ли карточка стиля."""
    t0 = time.perf_counter()
    card_reader = read_style_card if card_reader is None else card_reader
    r = card_reader(str(ref_path))
    card = r.get("card")
    if r.get("why") or card is None:
        axes = {
            "card_readable": {
                **tally(0, 0, 1),
                "card": None,
                "note": (
                    f"карточку прочитать нечем: {r.get('why') or 'ответа нет'}. "
                    f"Это НЕ «стиль плохой»"
                ),
            }
        }
        return _report("стилевой референс", ref_path, axes, {}, t0, soft=())

    need = ("colours", "value_key", "saturation", "texture")
    if not isinstance(card, dict):
        missing = list(need)
    else:
        missing = [k for k in need if not card.get(k)]
    axes = {
        "card_readable": {
            **tally(len(need), len(missing), 0),
            "card": card,
            "missing": missing,
            "note": (
                f"полей в карточке {len(need) - len(missing)} из {len(need)}"
                + (
                    f", пусты: {missing}"
                    if missing
                    else f"; палитра {list(card.get('colours') or [])}, "
                    f"тональность {card.get('value_key')!r}, насыщенность "
                    f"{card.get('saturation')!r}, фактура {card.get('texture')!r}"
                )
            ),
        }
    }
    return _report("стилевой референс", ref_path, axes, {}, t0, soft=())


def _report(
    kind, source, axes: dict, steps: dict, t0: float, *, soft=(), extra: dict | None = None
) -> dict:
    """Свести оси в один вердикт. Мягкие оси в него НЕ ВХОДЯТ."""
    hard = {k: v for k, v in axes.items() if k not in soft}
    checked = sum(v.get("checked", 0) for v in hard.values())
    violations = sum(v.get("violations", 0) for v in hard.values())
    unmeasured = sum(v.get("unmeasured", 0) for v in hard.values())
    total = tally(checked, violations, unmeasured)
    outcomes = [v.get("outcome") for v in hard.values()]
    if FAIL in outcomes:
        total["outcome"] = FAIL
    elif UNMEASURED in outcomes:
        total["outcome"] = UNMEASURED
    warns = [k for k, v in axes.items() if v.get("warn")]
    return {
        "kind": kind,
        "source": str(source),
        "axes": axes,
        "outcome": total["outcome"],
        "checked": total["checked"],
        "violations": total["violations"],
        "unmeasured": total["unmeasured"],
        "soft": list(soft),
        "warnings": warns,
        "steps": steps,
        "elapsed": round(time.perf_counter() - t0, 3),
        **(extra or {}),
    }


def render(report: dict) -> str:
    """Отчёт глазами. Числа рядом с вердиктом на каждой строке."""
    lines = [
        f"ПРИЁМ: {report['kind']} — {Path(report['source']).name}",
        f"  ВЕРДИКТ: {report['outcome']}  "
        f"(проверено {report['checked']}, нарушений "
        f"{report['violations']}, не смогли {report['unmeasured']})",
    ]
    for name, ax in report["axes"].items():
        mark = " [мягкая]" if name in report.get("soft", []) else ""
        lines.append(
            f"  {name}{mark}: {ax.get('outcome')} "
            f"(проверено {ax.get('checked')}, нарушений "
            f"{ax.get('violations')}, не смогли {ax.get('unmeasured')})"
        )
        if ax.get("note"):
            lines.append(f"      {ax['note']}")
    if report.get("warnings"):
        lines.append(f"  ПРЕДУПРЕЖДЕНИЯ: {report['warnings']}")
    if report.get("steps"):
        lines.append(f"  длительность шагов, с: {report['steps']}")
    return "\n".join(lines)
