"""Замер готового плана: есть ли в нём оператор и нет ли склейки внутри генерации.

Валидатор проверяет, что ПРОСИЛИ; здесь проверяется, что модель СДЕЛАЛА. Без
этого «оператор с плечевой камерой» в промпте ничего не гарантирует: модель
вправе отдать тот же гладкий наезд, что и раньше.

ЧТО МЕРЯЕТСЯ
* дрожь камеры — фазовая корреляция соседних кадров даёт сдвиг кадра; путь
  камеры минус его скользящее среднее — то высокочастотное, чего у ИИ-наезда
  нет, а у плечевой камеры есть всегда. В процентах ширины кадра, чтобы
  не зависеть от разрешения;
* склейки — скачок средней разницы соседних кадров во много раз выше медианы;
* звук — есть ли он и не упирается ли в потолок;
* похожие на бренды надписи (OCR) и контактный лист: OCR ловит не всё, лист
  смотрится глазами до того, как план идёт в монтаж.

Пороги дрожи откалиброваны на роликах 2026-10-07 (см. `JITTER_*`), а не взяты
из головы. Нет ffmpeg или не читается файл — «не смогли», а не «годно».
"""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass, field

import numpy as np

from studio.shoot.camera import RIGS

#: Ширина, до которой ужимается кадр перед замером: дрожь в процентах ширины
#: от этого не зависит, а фазовая корреляция на 192 px идёт быстро.
ANALYSIS_WIDTH = 192

#: Нижняя граница дрожи для постов, где оператор держит камеру сам.
#: ОТКАЛИБРОВАНО 2026-10-07 на восьми роликах H3 768×1344 (блочный замер):
#:     ИИ-наезд «slow push-in»   fo_A 0,281  fo_B 0,111  fo_C 0,256  sc_S1 0,115
#:     статичный речевой план    nb_N1 0,202
#:     живой оператор по посту   op_A 0,506 (плечевая)  op_B 0,330 (телевик)
#: Порог посередине зазора 0,28…0,33. Зазор узкий — граница записана как
#: измеренная, а не как надёжная: пограничный ролик смотрится глазами.
JITTER_HANDHELD_MIN = 0.30
#: Верхняя граница для статичной камеры в комментаторской.
JITTER_LOCKED_MAX = 0.05

#: Какой дрожи ждать от поста: "handheld" — не меньше, "locked" — не больше,
#: "floating" — не проверяется (стедикам и трос плавные по определению).
RIG_MOTION = {
    "in_cage_handheld": "handheld",
    "cage_side_tele": "handheld",
    "steadicam_orbit": "floating",
    "steadicam_follow": "floating",
    "overhead_cable": "floating",
    "booth_locked": "locked",
}
assert set(RIG_MOTION) == set(RIGS), "у каждого поста должно быть ожидание движения"

CUT_RATIO = 6.0  # во столько раз разница кадров выше медианы — склейка
CUT_ABS = 18.0  # и при этом не меньше этого в уровнях серого 0..255


@dataclass
class Report:
    outcome: str
    jitter_pct: float = 0.0
    drift_pct: float = 0.0
    zoom: float = 1.0
    cuts: list[float] = field(default_factory=list)
    audio_peak: float = 0.0
    audio_rms_db: float = -120.0
    text_seen: list[str] = field(default_factory=list)
    sheet: str = ""
    notes: list[str] = field(default_factory=list)


def _shift(a: np.ndarray, b: np.ndarray) -> tuple[float, float]:
    """Сдвиг b относительно a фазовой корреляцией, с субпиксельной доводкой."""
    win = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1]))
    fa = np.fft.fft2((a - a.mean()) * win)
    fb = np.fft.fft2((b - b.mean()) * win)
    r = fa * np.conj(fb)
    r /= np.abs(r) + 1e-9
    c = np.fft.ifft2(r).real
    py, px = np.unravel_index(int(np.argmax(c)), c.shape)
    h, w = c.shape

    def sub(arr: np.ndarray, i: int, n: int) -> float:
        lo, mid, hi = arr[(i - 1) % n], arr[i], arr[(i + 1) % n]
        den = lo - 2 * mid + hi
        return float(i + (0.5 * (lo - hi) / den if abs(den) > 1e-12 else 0.0))

    dy = sub(c[:, px], int(py), h)
    dx = sub(c[py, :], int(px), w)
    if dy > h / 2:
        dy -= h
    if dx > w / 2:
        dx -= w
    return -dx, -dy


BLOCK = 32  # сторона блока, по которому меряется местный сдвиг


def _peak(a: np.ndarray, b: np.ndarray) -> float:
    """Насколько уверенна фазовая корреляция: высота пика. На гладком блоке — шум."""
    fa = np.fft.fft2(a - a.mean())
    fb = np.fft.fft2(b - b.mean())
    r = fa * np.conj(fb)
    r /= np.abs(r) + 1e-9
    return float(np.fft.ifft2(r).real.max())


def frame_motion(a: np.ndarray, b: np.ndarray) -> tuple[float, float, float]:
    """Движение камеры между кадрами: (tx, ty, масштаб−1), без движения героев.

    ПОЧЕМУ НЕ ОДИН СДВИГ НА ВЕСЬ КАДР. Первая версия мерила глобальную фазовую
    корреляцию, и 2026-10-07 гладкий ИИ-наезд fo_A дал «дрожь» 0,50 % — больше,
    чем у статичного речевого плана: наезд раздвигает текстуру во все стороны,
    и один сдвиг на кадр его не описывает, а движение героя примешивается.
    Здесь кадр режется на блоки, сдвиг каждого блока раскладывается на перенос
    плюс масштаб от центра, и блоки, которые с этой моделью не сходятся
    (это герой, а не камера), выбрасываются.
    """
    h, w = a.shape
    pts, shifts, weights = [], [], []
    for y0 in range(0, h - BLOCK + 1, BLOCK):
        for x0 in range(0, w - BLOCK + 1, BLOCK):
            pa = a[y0 : y0 + BLOCK, x0 : x0 + BLOCK]
            pb = b[y0 : y0 + BLOCK, x0 : x0 + BLOCK]
            if pa.std() < 4:  # гладкий блок: свет, канвас без рисунка
                continue
            pk = _peak(pa, pb)
            if pk < 0.2:
                continue
            pts.append((x0 + BLOCK / 2 - w / 2, y0 + BLOCK / 2 - h / 2))
            shifts.append(_shift(pa, pb))
            weights.append(pk)
    if len(pts) < 6:
        return 0.0, 0.0, 0.0
    p = np.asarray(pts)
    d = np.asarray(shifts)
    wt = np.asarray(weights)
    keep = np.ones(len(p), bool)
    sol = np.zeros(3)
    for _ in range(3):
        n = int(keep.sum())
        m = np.zeros((2 * n, 3))
        m[:n, 0] = 1
        m[n:, 1] = 1
        m[:n, 2] = p[keep, 0]
        m[n:, 2] = p[keep, 1]
        rhs = np.concatenate([d[keep, 0], d[keep, 1]])
        sw = np.sqrt(np.concatenate([wt[keep], wt[keep]]))
        sol = np.linalg.lstsq(m * sw[:, None], rhs * sw, rcond=None)[0]
        pred = np.stack([sol[0] + sol[2] * p[:, 0], sol[1] + sol[2] * p[:, 1]], axis=1)
        res = np.linalg.norm(d - pred, axis=1)
        lim = max(0.5, 2.0 * float(np.median(res[keep])))
        new = res <= lim
        if new.sum() < 6 or (new == keep).all():
            break
        keep = new
    return float(sol[0]), float(sol[1]), float(sol[2])


def camera_path(frames: np.ndarray) -> np.ndarray:
    """(N, H, W) серые кадры → (N, 3): накопленный перенос x, y (px) и логарифм масштаба."""
    steps = [(0.0, 0.0, 0.0)]
    for i in range(1, len(frames)):
        tx, ty, s = frame_motion(frames[i - 1].astype(np.float64), frames[i].astype(np.float64))
        steps.append((tx, ty, float(np.log1p(s))))
    return np.cumsum(np.asarray(steps), axis=0)


def jitter(path: np.ndarray, width: int, window: int = 9) -> tuple[float, float]:
    """(дрожь, общий увод) в процентах ширины. Дрожь — RMS отклонения от скользящего среднего."""
    if len(path) < window + 2:
        return 0.0, 0.0
    k = np.ones(window) / window
    pad = window // 2
    smooth = np.stack(
        [np.convolve(np.pad(path[:, i], pad, mode="edge"), k, mode="valid") for i in (0, 1)],
        axis=1,
    )
    resid = path[:, :2] - smooth
    jit = float(np.sqrt((resid**2).sum(axis=1).mean())) / width * 100
    drift = float(np.linalg.norm(path[-1, :2] - path[0, :2])) / width * 100
    return jit, drift


def zoom(path: np.ndarray) -> float:
    """Во сколько раз за план вырос масштаб кадра (1.0 — без наезда)."""
    return float(np.exp(path[-1, 2] - path[0, 2])) if path.shape[1] > 2 else 1.0


def cuts(frames: np.ndarray, fps: float = 24.0) -> list[float]:
    """Секунды, на которых внутри ролика стоит склейка."""
    if len(frames) < 3:
        return []
    f = frames.astype(np.float64)
    d = np.abs(np.diff(f, axis=0)).mean(axis=(1, 2))
    med = float(np.median(d)) + 1e-6
    return [round((i + 1) / fps, 3) for i, v in enumerate(d) if v > CUT_ABS and v > CUT_RATIO * med]


#: Наибольший рост масштаба за план там, где у оператора нет трансфокатора под
#: рукой. НАБЛЮДЕНО 2026-10-07: «very slow push-in» дал ×2,49 (fo_A), ×2,29
#: (fo_B), ×1,46 (fo_C) — так снимает не человек, а модель. Телевик у сетки
#: зумит по-настоящему, ему порог не ставится.
ZOOM_MAX = {
    "in_cage_handheld": 1.3,
    "steadicam_orbit": 1.3,
    "steadicam_follow": 1.3,
    "overhead_cable": 1.6,
    "booth_locked": 1.15,  # статичный речевой план nb_N1 намерил ×1,06 — шум оценки
}


def judge(rig: str, jit: float, found_cuts: list[float], zm: float = 1.0) -> tuple[str, list[str]]:
    notes: list[str] = []
    lim = ZOOM_MAX.get(rig)
    # Наезд сам по себе не дефект: в op_A оператор по промпту шагнул за плечо
    # Адгара, и масштаб вырос в 1,63 раза — это и есть работа оператора. Дефект —
    # наезд ГЛАДКИЙ, без дрожи рук; у статичной камеры — любой.
    smooth = jit < JITTER_HANDHELD_MIN or RIG_MOTION.get(rig) == "locked"
    if lim and smooth and max(zm, 1 / max(zm, 1e-6)) > lim:
        notes.append(f"масштаб кадра ×{zm:.2f} за план у поста {rig} (не больше ×{lim}): ИИ-наезд")
    if found_cuts:
        notes.append(f"склейка внутри генерации на {found_cuts} с — звук H3 на ней ломается")
    kind = RIG_MOTION.get(rig, "floating")
    if kind == "handheld" and jit < JITTER_HANDHELD_MIN:
        notes.append(
            f"дрожь {jit:.3f}% ширины < {JITTER_HANDHELD_MIN}%: у поста {rig} нет оператора, "
            "это гладкий ИИ-наезд"
        )
    if kind == "locked" and jit > JITTER_LOCKED_MAX:
        notes.append(f"дрожь {jit:.3f}% ширины > {JITTER_LOCKED_MAX}% у статичной камеры")
    return ("не годно" if notes else "годно"), notes


#: НАБЛЮДЕНО 2026-10-07, sc_S1: на перчатках и канвасе общего плана модель
#: напечатала «OFC» и «OFE» — подделку под UFC, хотя промпт запрещал бренды.
#: Точное имя такую подделку не ловит, поэтому бренд считается найденным и на
#: расстоянии одной правки (для имён от трёх букв).
OCR_TIMES = (0.15, 0.5, 0.85)  # доли длины плана, на которых читается текст


def _edits(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def brand_hits(tokens: list[str], brands: tuple[str, ...] = ()) -> list[tuple[str, str]]:
    """(увиденное, бренд) для каждого токена, похожего на настоящий бренд."""
    from studio.shoot.validate import BRANDS

    brands = brands or BRANDS
    hits = []
    for tok in tokens:
        t = "".join(ch for ch in tok.upper() if ch.isalnum())
        for b in brands:
            n = "".join(ch for ch in b.upper() if ch.isalnum())
            if len(n) < 3:
                continue
            if n in t or (abs(len(t) - len(n)) <= 1 and _edits(t, n) <= 1):
                hits.append((tok, b))
    return hits


def contact_sheet(path: str, seconds: float, frames_n: int = 6) -> str:
    """Лист из `frames_n` кадров рядом с роликом — для просмотра глазами.

    ПОЧЕМУ ГЛАЗА ОБЯЗАТЕЛЬНЫ. НАБЛЮДЕНО 2026-10-07, S01_announce: на канвасе
    крупно напечатано «UFC» в перспективе, а RapidOCR на тех же кадрах прочёл
    только «SIEV» — и с поворотами, и с увеличением нижней половины кадра.
    Пустой список прочитанного текста НЕ значит «надписей нет».
    """
    out = path.rsplit(".", 1)[0] + ".sheet.jpg"
    rate = frames_n / max(seconds, 0.1)
    subprocess.run(
        ["ffmpeg", "-v", "error", "-y", "-i", path, "-vf"]
        + [f"fps={rate:.4f},scale=320:-2,tile={frames_n}x1", "-frames:v", "1", out],
        capture_output=True,
        check=True,
    )
    return out


def _ocr_brands(path: str, seconds: float) -> list[str] | None:
    """Весь текст, прочитанный на трёх кадрах плана; None — читать нечем."""
    try:
        from rapidocr_onnxruntime import RapidOCR  # необязательная зависимость
    except ImportError:
        return None
    ocr = RapidOCR()
    seen: list[str] = []
    for frac in OCR_TIMES:
        png = subprocess.run(
            ["ffmpeg", "-v", "error", "-ss", f"{seconds * frac:.2f}", "-i", path]
            + ["-frames:v", "1", "-f", "image2pipe", "-vcodec", "png", "-"],
            capture_output=True,
            check=True,
        ).stdout
        result, _ = ocr(png)
        seen.extend(str(r[1]) for r in result or [])
    return seen


def _read_frames(path: str) -> tuple[np.ndarray, float]:
    probe = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate",
            "-of",
            "csv=p=0",
            path,
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    w, h, rate = probe.split(",")[:3]
    num, _, den = rate.partition("/")
    fps = float(num) / float(den or 1)
    ow = ANALYSIS_WIDTH
    oh = round(int(h) * ow / int(w) / 2) * 2
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", path, "-vf", f"scale={ow}:{oh}", "-f", "rawvideo"]
        + ["-pix_fmt", "gray", "-"],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, np.uint8).reshape(-1, oh, ow), fps


def _read_audio(path: str) -> np.ndarray:
    raw = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            path,
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "f32le",
            "-",
        ],
        capture_output=True,
        check=True,
    ).stdout
    return np.frombuffer(raw, np.float32)


def measure(path: str, rig: str) -> Report:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        return Report("не смогли", notes=["нет ffmpeg/ffprobe"])
    try:
        frames, fps = _read_frames(path)
        audio = _read_audio(path)
    except (subprocess.CalledProcessError, ValueError) as e:
        return Report("не смогли", notes=[f"не читается {path}: {e}"])
    cam = camera_path(frames)
    jit, drift = jitter(cam, frames.shape[2])
    found = cuts(frames, fps)
    verdict, notes = judge(rig, jit, found, zoom(cam))
    rep = Report(verdict, round(jit, 4), round(drift, 3), cuts=found, notes=notes)
    if audio.size:
        rep.audio_peak = round(float(np.abs(audio).max()), 4)
        rms = float(np.sqrt((audio.astype(np.float64) ** 2).mean()))
        rep.audio_rms_db = round(20 * np.log10(rms + 1e-12), 1)
        if rep.audio_peak >= 0.999:
            rep.notes.append("звук упирается в 0 dBFS")
        if rep.audio_rms_db < -50:
            rep.notes.append("звука почти нет")
    else:
        rep.notes.append("в файле нет звуковой дорожки")
    rep.zoom = round(zoom(cam), 3)
    rep.sheet = contact_sheet(path, len(frames) / fps)
    seen = _ocr_brands(path, len(frames) / fps)
    if seen is not None:
        rep.text_seen = seen
        rep.notes.extend(f"на кадре «{t}» — похоже на бренд {b}" for t, b in brand_hits(seen))
    if rep.notes:
        rep.outcome = "не годно"
    elif seen is None:
        rep.outcome = "не смогли"
        rep.notes.append("бренды на кадрах не проверены: нет rapidocr_onnxruntime")
    return rep
