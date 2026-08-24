"""Сквозной стенд продукта: фото клиента + драйвинг + эстетика -> ролик."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from .fork_identity import FAIL, PASS, UNMEASURED, SAME_PERSON_MAX
from .fork_video import EXIT_BY_OUTCOME


KLING_ENDPOINT = "fal-ai/kling-video/v2.6/standard/motion-control"

KLING_FIELDS = ("video_url", "image_url", "character_orientation")

KLING_ORIENTATIONS = ("image", "video")

CHARACTER_ORIENTATION = "video"

KLING_PRICE_PER_SECOND_USD = 0.07

PRODUCT_SECONDS = 5.0

KLING_PRICE_USD = round(KLING_PRICE_PER_SECOND_USD * PRODUCT_SECONDS, 4)

KLING_PRO_PRICE_USD = 2.6880
KLING_PRO_PRICE_3S_USD = 2.6880
KLING_PRICE_3S_USD = 0.21


def kling_price(seconds: float) -> float:
    """Цена заказа по длине. Мусор — исключение, а не догадка."""
    if not isinstance(seconds, (int, float)) or isinstance(seconds, bool):
        raise TypeError(f"длина {seconds!r}: ждали число секунд")
    if seconds <= 0:
        raise ValueError(f"длина {seconds}: ждали больше нуля")
    return round(KLING_PRICE_PER_SECOND_USD * float(seconds), 4)

KLING_LATENCY_S = (107.4, 190.0)

KLING_WAIT_S = 1520

KLING_OUT_SIZE = (960, 960)
KLING_OUT_FPS = 30.0

FRAME_SUFFIXES = {".png", ".jpg", ".jpeg"}

OUT_RATIO_MAX = 1.0

MIN_SCENE_S = 3.0

FORBIDDEN_TIERS = ("pro",)

STYLE_MODEL = "nanobanana-2"
STYLE_ROUTE = "pollinations.compose"
STYLE_IMAGES = 2

STYLE_HIT_REFERENCE = 0.8156
STYLE_HIT_REJECTED = 0.8801
STYLE_FLOOR_REFERENCE = 0.6409
STYLE_TEXT_ROUTE_REFERENCE = 0.6773

STYLE_MARGIN_MIN = 0.05

MAX_CUTS_OUT = 0

NO_BRANDS_CLAUSE = ("no logo, no logos, no brand marks, no lettering or text "
                    "anywhere in the frame or on clothing")

ROLE_CLAUSE = ("keep the person from the FIRST image unchanged — same face, "
               "same identity, same clothing, same pose, same accessories; "
               "take ONLY the lighting, colour grade, background and "
               "photographic look from the SECOND image")

LADDER_SAME = 0.0652
LADDER_REJECTED = 0.7137
LADDER_STRANGER = 1.0217


NO_LOOK_TRANSFER_CLAUSE = ("do not copy any garment, accessory, eyewear, "
                           "headwear, hairstyle or pose from the second "
                           "image; the second image is a colour and lighting "
                           "reference only")

STAGES = (
    "1 приём трёх входов",
    "2 стилизация фото клиента",
    "3 приёмка стилизованного фото",
    "4 окно драйвинга и нарезка",
    "5 загрузка входов и вызов Kling",
    "6 приёмка выхода",
    "7 финальная сборка",
    "8 отчёт",
)


def say(text: str, *, log=None) -> None:
    """Строка в stderr НЕМЕДЛЕННО. Молчание длинного прогона уже стоило прогона."""
    stream = sys.stderr if log is None else log
    stream.write(text + "\n")
    flush = getattr(stream, "flush", None)
    if flush:
        flush()


def verdict(checked: int, violations: int, unmeasured: int) -> str:
    """Три исхода из трёх чисел. Ноль проверок — НЕ успех."""
    if checked <= 0:
        return UNMEASURED
    if violations > 0:
        return FAIL
    if unmeasured > 0:
        return UNMEASURED
    return PASS


def _result(stage: str, checks: list, *, note: str = "", **extra) -> dict:
    """Ступень из списка проверок. Каждая проверка — `(имя, исход, строка)`."""
    checked = sum(1 for c in checks if c[1] in (PASS, FAIL))
    violations = sum(1 for c in checks if c[1] == FAIL)
    unmeasured = sum(1 for c in checks if c[1] == UNMEASURED)
    return {"stage": stage, "outcome": verdict(checked, violations, unmeasured),
            "checked": checked, "violations": violations,
            "unmeasured": unmeasured,
            "checks": [{"name": n, "outcome": o, "note": t} for n, o, t in checks],
            "note": note, **extra}


def line(res: dict) -> str:
    """Одна строка ступени: вердикт и числа РЯДОМ с ним."""
    return (f"[{res['outcome']:<18}] {res['stage']:<34} "
            f"проверено {res['checked']}, нарушений {res['violations']}, "
            f"не смогли {res['unmeasured']}"
            + (f" | {res['note']}" if res.get("note") else ""))


def soft_import(name: str):
    """Соседний модуль или ПОНЯТНЫЙ отказ. Никогда не исключение наружу."""
    try:
        mod = __import__(f"lipsync.{name}", fromlist=["*"])
    except ImportError as exc:
        return None, (f"модуля lipsync.{name} нет ({exc}). Это НЕ брак "
                      f"продукта: ступень не измерена. Подменить можно "
                      f"параметром прогона")
    return mod, None


def entry_point(mod, candidates):
    """Первая существующая функция из списка имён, либо отказ с перечнем."""
    for name in candidates:
        fn = getattr(mod, name, None)
        if callable(fn):
            return fn, name, None
    return None, None, (f"в {mod.__name__} нет ни одной из точек входа "
                        f"{list(candidates)}: звать нечего")


def _call(fn, kwargs: dict, positional: tuple):
    """Вызов соседа: сначала по именам, при несовпадении — позиционно."""
    try:
        return fn(**kwargs)
    except TypeError as exc:
        if "argument" not in str(exc) and "parameter" not in str(exc):
            raise
        return fn(*positional)


def outcome_of(reply, *, what: str) -> tuple:
    """Вердикт из ответа соседа. Ответ без вердикта — «не смогли», не «годно»."""
    if isinstance(reply, dict) and reply.get("outcome") in (PASS, FAIL, UNMEASURED):
        return reply["outcome"], str(reply.get("note") or "")[:400]
    return UNMEASURED, (f"{what} ответил {type(reply).__name__} без поля "
                        f"outcome: вердикта нет, судить нечем")


def refuse_pro(endpoint: str) -> None:
    """Сторож денег. `pro` исключён составителем шаблонов НАВСЕГДА, и запрет машинный."""
    parts = str(endpoint).split("/")
    hit = [p for p in parts if p in FORBIDDEN_TIERS]
    if hit:
        pro_per_s = round(KLING_PRO_PRICE_3S_USD / 3.0, 4)
        raise ValueError(
            f"эндпоинт {endpoint} содержит {hit}: {FORBIDDEN_TIERS} исключены "
            f"составителем шаблонов НАВСЕГДА (${pro_per_s} против "
            f"${KLING_PRICE_PER_SECOND_USD} за секунду, в "
            f"{round(pro_per_s / KLING_PRICE_PER_SECOND_USD, 1)} раза; лейбл "
            f"всё равно не выжил, фон получил дорисованную анимацию)")


PALETTE_BINS = 8
PALETTE_SIDE = 256


def shipped_similarity(left, right) -> float | None:
    """Прибор попадания в стиль, ОДИН на весь конвейер. `None` — не смогли."""
    try:
        from creative_eval.style import similarity as _external  # noqa: PLC0415
    except Exception:                                            # noqa: BLE001
        return palette_similarity(left, right)
    try:
        return float(_external(str(left), str(right)))
    except Exception:                                            # noqa: BLE001
        return palette_similarity(left, right)


def similarity_source() -> str:
    """Каким прибором меряем СЕЙЧАС. Печатается в отчёт."""
    try:
        from creative_eval.style import similarity  # noqa: F401,PLC0415
        return "creative_eval.style.similarity (внешний, отгружаемый)"
    except Exception:                               # noqa: BLE001
        return "palette_similarity (запасной: внешнего пакета нет)"


def palette_similarity(left, right) -> float | None:
    """ЗАПАСНОЙ прибор: косинус между палитрами. `None` — не смогли."""
    try:
        import numpy as np
        from PIL import Image
    except ImportError:
        return None
    try:
        vecs = []
        for p in (left, right):
            arr = np.asarray(Image.open(str(p)).convert("RGB")
                             .resize((PALETTE_SIDE, PALETTE_SIDE)),
                             dtype="float64").reshape(-1, 3)
            hist, _ = np.histogramdd(
                arr, bins=(PALETTE_BINS,) * 3, range=((0, 255),) * 3)
            v = hist.ravel()
            norm = float(np.linalg.norm(v))
            if norm <= 0:
                return None
            vecs.append(v / norm)
    except Exception:                                    # noqa: BLE001
        return None
    return round(float(vecs[0] @ vecs[1]), 4)


def live_upload(path) -> str:
    """Файл -> публичная ссылка на fal. НЕПРОВЕРЕНО в этой смене (денег не тратили)."""
    import fal_client                                    # noqa: PLC0415

    return fal_client.upload_file(str(path))


def live_kling(*, video_url: str, image_url: str, character_orientation: str,
               out_path, endpoint: str = KLING_ENDPOINT, poll_s: int = 15,
               wait_s: int = KLING_WAIT_S) -> str:
    """Заказ у fal и скачивание выхода. ПЛАТНЫЙ путь: ровно $0.21 за вызов."""
    import os                                            # noqa: PLC0415
    import urllib.request                                # noqa: PLC0415

    refuse_pro(endpoint)
    key = os.environ.get("FAL_KEY")
    if not key:
        raise RuntimeError("FAL_KEY не задан: заказывать нечем")
    head = {"Authorization": f"Key {key}", "Content-Type": "application/json"}
    payload = {"video_url": video_url, "image_url": image_url,
               "character_orientation": character_orientation}

    def _req(url, data=None):
        req = urllib.request.Request(url, data=data, headers=head)
        with urllib.request.urlopen(req, timeout=60) as fh:
            return json.loads(fh.read().decode() or "{}")

    app = "/".join(endpoint.split("/")[:2])
    sub = _req(f"https://queue.fal.run/{endpoint}",
               data=json.dumps(payload).encode())
    rid = sub["request_id"]
    t0 = time.time()
    while time.time() - t0 < wait_s:
        time.sleep(poll_s)
        st = _req(f"https://queue.fal.run/{app}/requests/{rid}/status")
        if st.get("status") in ("COMPLETED", "FAILED", "ERROR"):
            break
    res = _req(f"https://queue.fal.run/{app}/requests/{rid}")
    url = (res.get("video") or {}).get("url")
    if not url:
        raise RuntimeError(f"в ответе нет ссылки на видео: {str(res)[:300]}")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=600) as fh:
        Path(out_path).write_bytes(fh.read())
    return str(out_path)


def live_stylize(*, person, style, prompt: str, out_path,
                 model: str = STYLE_MODEL) -> str:
    """Стилизация ДВУМЯ картинками через победителя замера. Ходит в сеть."""
    from . import pollinations                           # noqa: PLC0415

    urls = [pollinations.upload(person), pollinations.upload(style)]
    if len(urls) != STYLE_IMAGES:
        raise RuntimeError(f"нужно ровно {STYLE_IMAGES} ссылки, вышло {len(urls)}")
    return pollinations.compose(prompt, urls, out_path, model=model)


def file_fact(path, what: str) -> tuple:
    """Дешёвая проверка раньше дорогой: файл есть и он не пуст."""
    p = Path(path)
    if not p.exists():
        return (what, FAIL, f"{p} нет на диске")
    size = p.stat().st_size
    if size == 0:
        return (what, FAIL, f"{p} пуст (0 Б)")
    return (what, PASS, f"{p} — {size} Б")


INTAKE_TRIO = ("photo_intake", "style_intake", "driving_intake")


def _numbers_of(reply) -> str:
    """Числа соседа рядом с его вердиктом. Нет чисел — так и сказано."""
    if not isinstance(reply, dict):
        return ""
    if any(k not in reply for k in ("checked", "violations", "unmeasured")):
        return ""
    return (f"проверено {reply['checked']}, нарушений {reply['violations']}, "
            f"не смогли {reply['unmeasured']}; ")


def stage_intake(*, client_photo, style_ref, driving, intake=None,
                 driving_frames=None, card_reader=None) -> dict:
    """Три входа на месте, и сосед `fork_intake` их принял."""
    checks = [file_fact(client_photo, "фото клиента"),
              file_fact(style_ref, "стилевой референс"),
              file_fact(driving, "драйвинг")]
    note = ""
    if intake is None:
        mod, why = soft_import("fork_intake")
        if mod is None:
            checks.append(("приём соседним модулем", UNMEASURED, why))
            return _result(STAGES[0], checks, note=why)
        trio = [getattr(mod, n, None) for n in INTAKE_TRIO]
        if all(callable(f) for f in trio):
            photo, style, drive = trio
            calls = (("приём фото клиента", photo, (str(client_photo),), {}),
                     ("приём стилевого референса", style, (str(style_ref),),
                      {} if card_reader is None else {"card_reader": card_reader}),
                     ("приём драйвинга", drive, (str(driving), driving_frames), {}))
            for name, fn, args, extra in calls:
                try:
                    reply = fn(*args, **extra)
                except Exception as exc:             # noqa: BLE001
                    checks.append((name, UNMEASURED, f"{type(exc).__name__}: {exc}"))
                    continue
                out, why = outcome_of(reply, what=f"fork_intake.{fn.__name__}")
                checks.append((name, out, _numbers_of(reply) + why))
            return _result(STAGES[0], checks, note="fork_intake: " +
                           ", ".join(INTAKE_TRIO))
        intake, name, why = entry_point(
            mod, ("accept", "intake", "take", "check", "run"))
        if intake is None:
            checks.append(("приём соседним модулем", UNMEASURED, why))
            return _result(STAGES[0], checks, note=why)
        note = f"fork_intake.{name}"
    try:
        reply = _call(intake,
                      {"client_photo": str(client_photo),
                       "style_ref": str(style_ref), "driving": str(driving)},
                      (str(client_photo), str(style_ref), str(driving)))
    except Exception as exc:                             # noqa: BLE001
        checks.append(("приём соседним модулем", UNMEASURED,
                       f"{type(exc).__name__}: {exc}"))
        return _result(STAGES[0], checks, note="сосед упал: это НЕ «не годно»")
    out, why = outcome_of(reply, what="fork_intake")
    checks.append(("приём соседним модулем", out, why))
    return _result(STAGES[0], checks, note=note or why)


def style_prompt(style_ref, *, card_reader=None) -> dict:
    """Промт стилизации: роли, стиль словами (если читается) и запрет брендов."""
    from . import fork_style_prompt                      # noqa: PLC0415

    card = fork_style_prompt.from_image(style_ref, reader=card_reader)
    words = card.get("prompt")
    parts = ([ROLE_CLAUSE] + ([words] if words else [])
             + [NO_LOOK_TRANSFER_CLAUSE, NO_BRANDS_CLAUSE])
    return {"prompt": ", ".join(parts), "card_outcome": card.get("outcome"),
            "card_note": card.get("note"), "words": words}


def _default_aesthetic():
    """Сосед-эстетика. Импорт настоящий, а не по строке: модуль, позванный"""
    from . import fork_aesthetic                         # noqa: PLC0415

    return fork_aesthetic


def _default_plan():
    """Сосед-план. Тот же довод, что и выше."""
    from . import fork_plan                              # noqa: PLC0415

    return fork_plan


def _person_in_plan(image, *, plan, pose=None, card=None) -> tuple:
    """Попадает ли ЧЕЛОВЕК на картинке в полосы плана. Три исхода."""
    if pose is None:
        def pose(path):
            from . import fork_looper                     # noqa: PLC0415

            return (fork_looper.read_pose(str(path)) or {}).get("points") or {}
    try:
        points = pose(str(image))
    except Exception as exc:                              # noqa: BLE001
        return ("человек в плане", UNMEASURED,
                f"позу не сняли: {type(exc).__name__}: {exc}")
    if card is not None:
        got = plan.in_card(points, card)
        return ("человек в карточке драйвинга", got["outcome"],
                str(got.get("note"))[:250])
    box = plan.person_box(points)
    if box["outcome"] != PASS:
        return ("человек в плане", UNMEASURED, str(box.get("note"))[:200])
    bad = []
    lo, hi = plan.SHOULDERS_BAND
    if not lo <= (box["shoulders"] or -1) <= hi:
        bad.append(f"плечи {box['shoulders']} вне {lo}..{hi}")
    lo, hi = plan.ANKLES_BAND
    if not lo <= (box["ankles"] or -1) <= hi:
        bad.append(f"щиколотки {box['ankles']} вне {lo}..{hi}")
    if abs(box["centre"] - 0.5) > plan.CENTRE_TOL:
        bad.append(f"центр {box['centre']} дальше {plan.CENTRE_TOL} от середины")
    if box["width"] > plan.WIDTH_MAX:
        bad.append(f"ширина {box['width']} выше {plan.WIDTH_MAX}")
    tail = (f"плечи {box['shoulders']}, щиколотки {box['ankles']}, центр "
            f"{box['centre']}, ширина {box['width']}")
    if bad:
        return ("человек в плане", FAIL,
                "; ".join(bad) + f" ({tail}). Kling масштабирует персонажа под "
                f"скелет драйвинга: рефка не в плане уедет за край кадра")
    return ("человек в плане", PASS, tail)


def stage_stylize(*, client_photo, style_ref, out_path, stylize=None,
                  card_reader=None, prompt=None, aesthetic=None,
                  client_gender=None, plan=None, aesthetic_mod=None,
                  extend=None, pose=None, card=None) -> dict:
    """Фото клиента + стилевой референс -> стилизованное фото."""
    A = _default_aesthetic() if aesthetic_mod is None else aesthetic_mod
    checks_pre = []
    if aesthetic is not None:
        gender = A.gender_of(aesthetic)
        pair = A.pair_check(client_gender=client_gender, aesthetic_gender=gender)
        checks_pre.append(("пол клиента и шаблона", pair["outcome"], pair["note"]))
        if pair["outcome"] != PASS:
            return _result(STAGES[1], checks_pre,
                           note="пол не сошёлся: генерация не запускалась")
        style_ref = str(A.aesthetic_file(aesthetic))
        prompt = (f"{A.compose(aesthetic, card=card)['prompt']}. "
                  f"{A.assemble_prompt(card=card)}")

    built = ({"prompt": prompt, "card_note": "промт подан снаружи"}
             if prompt is not None else style_prompt(style_ref,
                                                     card_reader=card_reader))
    prompt = built["prompt"]
    checks = list(checks_pre) + [("запрет брендов в промте",
               PASS if NO_BRANDS_CLAUSE in prompt else FAIL,
               NO_BRANDS_CLAUSE if NO_BRANDS_CLAUSE in prompt
               else "запрет вынули из промта: бренды поедут в кадр")]
    stylize = live_stylize if stylize is None else stylize
    t0 = time.perf_counter()
    try:
        got = stylize(person=str(client_photo), style=str(style_ref),
                      prompt=prompt, out_path=str(out_path))
    except Exception as exc:                             # noqa: BLE001
        checks.append(("стилизация", UNMEASURED, f"{type(exc).__name__}: {exc}"))
        return _result(STAGES[1], checks, prompt=prompt,
                       note="стилизатор не ответил: измерять нечего")
    checks.append(("стилизация", PASS,
                   f"{STYLE_ROUTE}/{STYLE_MODEL}, {STYLE_IMAGES} картинки, "
                   f"{round(time.perf_counter() - t0, 1)} с"))
    checks.append(file_fact(got or out_path, "стилизованное фото"))
    made = str(got or out_path)

    P = _default_plan() if plan is None else plan
    planned = Path(str(out_path)).with_name(Path(str(out_path)).stem + "_9x16.png")
    try:
        laid = P.to_plan(made, planned)
    except Exception as exc:                             # noqa: BLE001
        checks.append(("план 9:16", UNMEASURED, f"{type(exc).__name__}: {exc}"))
        return _result(STAGES[1], checks, styled=made, prompt=prompt,
                       note=str(built["card_note"] or "")[:160])
    checks.append(("план 9:16", laid["outcome"], str(laid.get("note"))[:200]))
    if laid["outcome"] == PASS:
        made = laid["path"]

        grown = Path(made).with_name(Path(made).stem + "_full.png")
        ext = P.extend_to_plan(made, grown, extender=extend)
        checks.append(("дорисовка полей", ext["outcome"],
                       str(ext.get("note"))[:200]))
        if ext["outcome"] == PASS:
            made = ext["path"]

        checks.append(_person_in_plan(made, plan=P, pose=pose, card=card))

    return _result(STAGES[1], checks, styled=made, prompt=prompt,
                   note=str(built["card_note"] or "")[:160])


def stage_style_acceptance(*, styled, style_ref, client_photo, operator_ok_identity=False,
                           similarity=None, distances=None) -> dict:
    """Попал ли в стиль (против ПОЛА) и уцелела ли личность (против планки)."""
    similarity = shipped_similarity if similarity is None else similarity
    checks, numbers = [], {}

    floor = similarity(style_ref, client_photo)
    hit = similarity(style_ref, styled)
    numbers["floor"] = floor
    numbers["hit"] = hit
    if floor is None or hit is None:
        checks.append(("попадание в стиль", UNMEASURED,
                       f"прибор стиля не дал числа: пол={floor}, попадание={hit}"))
    else:
        margin = round(hit - floor, 4)
        numbers["margin"] = margin
        ok = margin >= STYLE_MARGIN_MIN
        checks.append(("попадание в стиль", PASS if ok else FAIL,
                       f"попадание {hit} при поле {floor} (пол = стиль против "
                       f"НЕстилизованного фото), запас {margin} при планке "
                       f"{STYLE_MARGIN_MIN}"))

    distances = _default_distances() if distances is None else distances
    try:
        d = distances([str(styled)], str(client_photo))
    except Exception as exc:                             # noqa: BLE001
        checks.append(("личность на стилизованном", UNMEASURED,
                       f"{type(exc).__name__}: {exc}"))
        return _result(STAGES[2], checks, numbers=numbers)
    numbers["identity_median"] = d.get("median")
    numbers["identity_bar"] = SAME_PERSON_MAX
    if d.get("outcome") == UNMEASURED:
        checks.append(("личность на стилизованном", UNMEASURED,
                       str(d.get("note"))[:300]))
    else:
        med = d.get("median")
        if med is None:
            checks.append(("личность на стилизованном", UNMEASURED,
                           "медианы нет: судить нечем"))
        elif med <= SAME_PERSON_MAX:
            checks.append(("личность на стилизованном", PASS,
                           f"медиана {med} при планке {SAME_PERSON_MAX} "
                           f"(лестница: {LADDER_SAME} тот же, "
                           f"{LADDER_REJECTED} другой, {LADDER_STRANGER} чужой)"))
        elif med < LADDER_REJECTED:
            band = (f"медиана {med} между планкой {SAME_PERSON_MAX} и ступенью "
                    f"«другой человек» {LADDER_REJECTED}: лицо ЧАСТИЧНО "
                    f"ЗАКРЫТО или изменено аксессуаром — ArcFace здесь НЕ СУДЬЯ")
            if operator_ok_identity:
                checks.append(("личность на стилизованном", PASS,
                               band + "; ДОПУЩЕНО ОПЕРАТОРОМ явным флагом"))
            else:
                checks.append(("личность на стилизованном", UNMEASURED,
                               band + ", судит оператор глазами"))
        else:
            checks.append(("личность на стилизованном", FAIL,
                           f"медиана {med} выше ступени «другой человек» "
                           f"{LADDER_REJECTED}: это подмена личности, а не "
                           f"аксессуар (лестница: {LADDER_SAME} тот же, "
                           f"{LADDER_STRANGER} чужой)"))
    return _result(STAGES[2], checks, numbers=numbers)


def _default_distances():
    from . import fork_identity                          # noqa: PLC0415

    return fork_identity.distances


def cut_argv(src, dst, *, first: int, last: int, fps: float, exe: str) -> list:
    """Рез: старт по времени, длина ПО КАДРАМ."""
    return [exe, "-hide_banner", "-loglevel", "error", "-y",
            "-ss", f"{first / fps:.6f}", "-i", str(src),
            "-frames:v", str(last - first + 1),
            "-c:v", "libx264", "-crf", "18", "-pix_fmt", "yuv420p",
            "-an", str(dst)]


def _decoded_frames(path, exe: str):
    out = subprocess.run([exe, "-hide_banner", "-i", str(path), "-map", "0:v:0",
                          "-f", "null", "-"], capture_output=True, text=True)
    for row in reversed(out.stderr.splitlines()):
        if "frame=" in row:
            try:
                return int(row.split("frame=")[1].split()[0])
            except (IndexError, ValueError):
                return None
    return None


def stage_window(*, driving, first: int, last: int, out_path,
                 probe=None, cutter=None) -> dict:
    """Окно по номерам кадров, проверка длины и рез с ПЕРЕСЧЁТОМ кадров."""
    checks, numbers = [], {"first": first, "last": last}
    probe = _default_probe() if probe is None else probe
    info = probe(str(driving))
    fps = info.get("fps")
    total = info.get("frames")
    numbers["fps"] = fps
    numbers["source_frames"] = total
    if not fps or not total:
        checks.append(("опрос драйвинга", UNMEASURED, str(info.get("note"))[:200]))
        return _result(STAGES[3], checks, numbers=numbers)
    checks.append(("опрос драйвинга", PASS, str(info.get("note"))[:200]))

    want = last - first + 1
    numbers["want_frames"] = want
    inside = 0 <= first <= last < total
    checks.append(("окно внутри драйвинга", PASS if inside else FAIL,
                   f"кадры {first}..{last} при {total} кадрах в ролике"))
    seconds = round(want / fps, 3)
    numbers["seconds"] = seconds
    long_enough = seconds >= MIN_SCENE_S
    checks.append(("сцена не короче порога", PASS if long_enough else FAIL,
                   f"{seconds} с при пороге {MIN_SCENE_S} с (гейт Kling: "
                   f"«Video duration can not less than 3s»)"))
    if not (inside and long_enough):
        return _result(STAGES[3], checks, numbers=numbers)

    if cutter is None:
        import shutil                                    # noqa: PLC0415
        exe = shutil.which("ffmpeg")
        if not exe:
            checks.append(("рез", UNMEASURED, "ffmpeg не найден: резать нечем"))
            return _result(STAGES[3], checks, numbers=numbers)

        def cutter(src, dst, first=first, last=last, fps=fps, exe=exe):
            run = subprocess.run(cut_argv(src, dst, first=first, last=last,
                                          fps=fps, exe=exe),
                                 capture_output=True, text=True)
            if run.returncode != 0:
                raise RuntimeError(f"ffmpeg вернул {run.returncode}: "
                                   f"{run.stderr[-300:]}")
            return {"path": str(dst), "frames": _decoded_frames(dst, exe)}

    try:
        got = cutter(str(driving), str(out_path))
    except Exception as exc:                             # noqa: BLE001
        checks.append(("рез", UNMEASURED, f"{type(exc).__name__}: {exc}"))
        return _result(STAGES[3], checks, numbers=numbers)
    got = got if isinstance(got, dict) else {"path": str(out_path), "frames": None}
    numbers["cut_frames"] = got.get("frames")
    if got.get("frames") is None:
        checks.append(("кадров в куске", UNMEASURED,
                       "пересчитать кадры не вышло: рез не подтверждён"))
    else:
        checks.append(("кадров в куске",
                       PASS if got["frames"] == want else FAIL,
                       f"{got['frames']} при заказанных {want}"))
    checks.append(file_fact(got.get("path") or out_path, "кусок драйвинга"))
    return _result(STAGES[3], checks, numbers=numbers,
                   window=str(got.get("path") or out_path))


def _default_probe():
    from . import fork_video                             # noqa: PLC0415

    return fork_video.probe


def kling_payload(*, video_url: str, image_url: str,
                  character_orientation: str = CHARACTER_ORIENTATION) -> dict:
    """Ровно три поля и ни одним больше. Значение ориентации — из измеренных."""
    if character_orientation not in KLING_ORIENTATIONS:
        raise ValueError(f"character_orientation={character_orientation!r}: у "
                         f"эндпоинта ровно {list(KLING_ORIENTATIONS)} "
                         f"(ИЗМЕРЕНО щупом)")
    return {"video_url": video_url, "image_url": image_url,
            "character_orientation": character_orientation}


def _window_seconds(window, *, prober=None) -> float | None:
    """Длина куска драйвинга в секундах, или None. Догадку не подставляем:"""
    prober = _default_probe() if prober is None else prober
    try:
        info = prober(str(window))
    except Exception:                                    # noqa: BLE001
        return None
    frames, fps = info.get("frames"), info.get("fps")
    if not frames or not fps:
        return None
    return round(frames / fps, 3)


def stage_kling(*, styled, window, out_path, upload=None, kling=None,
                probe=None,
                endpoint: str = KLING_ENDPOINT,
                orientation: str = CHARACTER_ORIENTATION) -> dict:
    """Две загрузки и один платный вызов. Любой отказ — «не смогли», не «не годно»."""
    seconds = _window_seconds(window, prober=probe)
    price = KLING_PRICE_USD if seconds is None else kling_price(seconds)
    checks, numbers = [], {"endpoint": endpoint, "price_usd": price,
                           "seconds": seconds}
    try:
        refuse_pro(endpoint)
        checks.append(("сторож pro", PASS, f"{endpoint}: тарифов "
                                           f"{list(FORBIDDEN_TIERS)} нет"))
    except ValueError as exc:
        checks.append(("сторож pro", FAIL, str(exc)))
        return _result(STAGES[4], checks, numbers=numbers)

    upload = live_upload if upload is None else upload
    kling = live_kling if kling is None else kling
    try:
        video_url = upload(str(window))
        image_url = upload(str(styled))
    except Exception as exc:                             # noqa: BLE001
        checks.append(("загрузка входов", UNMEASURED,
                       f"{type(exc).__name__}: {exc}"))
        return _result(STAGES[4], checks, numbers=numbers,
                       note="входы не уехали: заказ не делался, денег не потрачено")
    checks.append(("загрузка входов", PASS, "video_url и image_url получены"))

    try:
        payload = kling_payload(video_url=video_url, image_url=image_url,
                                character_orientation=orientation)
    except ValueError as exc:
        checks.append(("состав запроса", FAIL, str(exc)))
        return _result(STAGES[4], checks, numbers=numbers)
    extra = sorted(set(payload) - set(KLING_FIELDS))
    missing = sorted(set(KLING_FIELDS) - set(payload))
    checks.append(("состав запроса", PASS if not (extra or missing) else FAIL,
                   f"поля {sorted(payload)} при измеренных {sorted(KLING_FIELDS)}"
                   + (f", лишние {extra}" if extra else "")
                   + (f", нет {missing}" if missing else "")))
    if extra or missing:
        return _result(STAGES[4], checks, numbers=numbers)

    t0 = time.perf_counter()
    try:
        got = kling(video_url=payload["video_url"],
                    image_url=payload["image_url"],
                    character_orientation=payload["character_orientation"],
                    out_path=str(out_path))
    except Exception as exc:                             # noqa: BLE001
        checks.append(("вызов Kling", UNMEASURED, f"{type(exc).__name__}: {exc}"))
        return _result(STAGES[4], checks, numbers=numbers,
                       note="заказ не состоялся: измерять нечего")
    spent = round(time.perf_counter() - t0, 1)
    numbers["latency_s"] = spent
    lo, hi = KLING_LATENCY_S
    checks.append(("вызов Kling", PASS,
                   f"{spent} с (измеренная полоса {lo}..{hi} с), "
                   f"${price}"))
    checks.append(file_fact(got or out_path, "выход Kling"))
    return _result(STAGES[4], checks, numbers=numbers,
                   produced=str(got or out_path))


def stage_output_acceptance(*, produced, client_photo, frames_dir,
                            probe=None, decode=None, distances=None,
                            cuts=None, operator_ok_identity=False) -> dict:
    """Геометрия, личность и монтажные резы на выходе Kling."""
    checks, numbers = [], {}
    probe = _default_probe() if probe is None else probe
    info = probe(str(produced))
    numbers["width"] = info.get("width")
    numbers["height"] = info.get("height")
    numbers["fps"] = info.get("fps")
    numbers["frames"] = info.get("frames")
    if not info.get("width"):
        checks.append(("геометрия выхода", UNMEASURED, str(info.get("note"))[:200]))
    else:
        w, h = info.get("width"), info.get("height")
        ratio = w / h
        numbers["ratio"] = round(ratio, 4)
        known = (w, h) == KLING_OUT_SIZE
        fps_ok = info.get("fps") == KLING_OUT_FPS
        if ratio > OUT_RATIO_MAX:
            checks.append(("геометрия выхода", FAIL,
                           f"{w}x{h}, соотношение {ratio:.4f} > "
                           f"{OUT_RATIO_MAX}: ГОРИЗОНТАЛЬ, для вертикального "
                           f"продукта это брак"))
        elif not fps_ok:
            checks.append(("геометрия выхода", UNMEASURED,
                           f"{w}x{h} при {info.get('fps')} к/с вместо "
                           f"{KLING_OUT_FPS}: частота не та, сборка звука "
                           f"считает кадры по 30 — судить нечем"))
        else:
            was = "как на прежних заказах" if known else (
                f"НОВАЯ геометрия, прежние восемь давали "
                f"{KLING_OUT_SIZE[0]}x{KLING_OUT_SIZE[1]}")
            checks.append(("геометрия выхода", PASS,
                           f"{w}x{h}, соотношение {ratio:.4f} при потолке "
                           f"{OUT_RATIO_MAX} — вертикаль или квадрат; {was}"))

    decode = _default_decode() if decode is None else decode
    try:
        got = decode(str(produced), str(frames_dir))
    except Exception as exc:                             # noqa: BLE001
        checks.append(("раскладка на кадры", UNMEASURED,
                       f"{type(exc).__name__}: {exc}"))
        return _result(STAGES[5], checks, numbers=numbers)
    paths = list(got.get("paths") or [])
    numbers["decoded"] = len(paths)
    if not paths:
        checks.append(("раскладка на кадры", UNMEASURED,
                       f"кадров не вышло: {str(got.get('note'))[:200]}"))
        return _result(STAGES[5], checks, numbers=numbers)
    checks.append(("раскладка на кадры", PASS, f"кадров {len(paths)}"))

    distances = _default_distances() if distances is None else distances
    try:
        d = distances(paths, str(client_photo))
    except Exception as exc:                             # noqa: BLE001
        d = {"outcome": UNMEASURED, "note": f"{type(exc).__name__}: {exc}"}
    numbers["identity_median"] = d.get("median")
    numbers["identity_inside"] = d.get("inside")
    numbers["identity_judged"] = d.get("judged")
    if d.get("outcome") == UNMEASURED:
        checks.append(("личность на выходе", UNMEASURED, str(d.get("note"))[:300]))
    else:
        med = d.get("median")
        tail = (f"в баре {d.get('inside')} из {d.get('judged')} судимых "
                f"(лестница: {LADDER_SAME} тот же, {LADDER_REJECTED} другой, "
                f"{LADDER_STRANGER} чужой)")
        if med is None:
            checks.append(("личность на выходе", UNMEASURED,
                           "медианы нет: судить нечем"))
        elif med <= SAME_PERSON_MAX:
            checks.append(("личность на выходе", PASS,
                           f"медиана {med} при планке {SAME_PERSON_MAX}, {tail}"))
        elif med < LADDER_REJECTED:
            band = (f"медиана {med} между планкой {SAME_PERSON_MAX} и ступенью "
                    f"«другой человек» {LADDER_REJECTED}: лицо ЧАСТИЧНО "
                    f"ЗАКРЫТО, ArcFace здесь НЕ СУДЬЯ; {tail}")
            if operator_ok_identity:
                checks.append(("личность на выходе", PASS,
                               band + "; ДОПУЩЕНО ОПЕРАТОРОМ явным флагом"))
            else:
                checks.append(("личность на выходе", UNMEASURED,
                               band + ", судит оператор глазами"))
        else:
            checks.append(("личность на выходе", FAIL,
                           f"медиана {med} выше ступени «другой человек» "
                           f"{LADDER_REJECTED}: подмена личности; {tail}"))

    cuts = _default_cuts() if cuts is None else cuts
    try:
        c = cuts(paths)
    except Exception as exc:                             # noqa: BLE001
        c = {"outcome": UNMEASURED, "note": f"{type(exc).__name__}: {exc}"}
    numbers["cuts"] = None if c.get("outcome") == UNMEASURED else len(c.get("cuts") or [])
    if c.get("outcome") == UNMEASURED:
        checks.append(("монтажные резы", UNMEASURED, str(c.get("note"))[:300]))
    else:
        found = len(c.get("cuts") or [])
        checks.append(("монтажные резы", PASS if found <= MAX_CUTS_OUT else FAIL,
                       f"резов {found} при допуске {MAX_CUTS_OUT}; "
                       f"{str(c.get('note'))[:160]}"))
    return _result(STAGES[5], checks, numbers=numbers)


def _default_decode():
    from . import fork_video                             # noqa: PLC0415

    def decode(video, out_dir):
        return fork_video.frames(video, out_dir, overwrite=True)

    return decode


def _default_cuts():
    from . import fork_looper                            # noqa: PLC0415

    return fork_looper.cuts


def stage_finish(*, produced, driving, out_path, window=None,
                 finish=None) -> dict:
    """Кроп 9:16 и возврат звука. Живёт в `fork_finish`, зовётся мягко."""
    checks = []
    note = ""
    if finish is None:
        mod, why = soft_import("fork_finish")
        if mod is None:
            checks.append(("финальная сборка", UNMEASURED, why))
            return _result(STAGES[6], checks, note=why)
        finish, name, why = entry_point(
            mod, ("finish", "assemble", "build", "compose", "run"))
        if finish is None:
            checks.append(("финальная сборка", UNMEASURED, why))
            return _result(STAGES[6], checks, note=why)
        note = f"fork_finish.{name}"
    try:
        reply = _call(finish,
                      {"driving_path": str(driving), "kling_path": str(produced),
                       "out_path": str(out_path), "window": window},
                      (str(driving), str(produced), str(out_path)))
    except Exception as exc:                             # noqa: BLE001
        checks.append(("финальная сборка", UNMEASURED,
                       f"{type(exc).__name__}: {exc}"))
        return _result(STAGES[6], checks, note="сосед упал: это НЕ «не годно»")
    out, why = outcome_of(reply, what="fork_finish")
    checks.append(("финальная сборка", out, why))
    if out == PASS:
        target = (reply.get("path") if isinstance(reply, dict) else None) or out_path
        checks.append(file_fact(target, "финальный ролик"))
    return _result(STAGES[6], checks, note=note or why)


def stage_report(stages: list, *, out_path=None) -> dict:
    """Свод по ступеням. Частичный результат — ЧИСЛАМИ, а не флагом."""
    checked = sum(s["checked"] for s in stages)
    violations = sum(s["violations"] for s in stages)
    unmeasured = sum(s["unmeasured"] for s in stages)
    done = sum(1 for s in stages if s["outcome"] == PASS)
    checks = [("свод по ступеням", PASS,
               f"ступеней пройдено {done} из {len(STAGES) - 1} до отчёта; "
               f"проверок {checked}, нарушений {violations}, "
               f"не смогли {unmeasured}")]
    if out_path is not None:
        try:
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_text(
                json.dumps({"stages": stages, "checked": checked,
                            "violations": violations, "unmeasured": unmeasured},
                           ensure_ascii=False, indent=2), encoding="utf-8")
            checks.append(("отчёт на диск", PASS, str(out_path)))
        except OSError as exc:
            checks.append(("отчёт на диск", UNMEASURED, f"{type(exc).__name__}: {exc}"))
    return _result(STAGES[7], checks,
                   totals={"checked": checked, "violations": violations,
                           "unmeasured": unmeasured, "stages_passed": done})


def run(*, client_photo, style_ref, driving, first: int, last: int,
        out_dir="work/e2e", intake=None, stylize=None, similarity=None,
        distances=None, probe=None, cutter=None, decode=None, cuts=None,
        upload=None, kling=None, finish=None, card_reader=None,
        driving_frames=None, operator_ok_identity: bool = False,
        aesthetic=None, client_gender=None, plan=None, aesthetic_mod=None,
        extend=None, pose=None, card=None,
        orientation: str = CHARACTER_ORIENTATION, endpoint: str = KLING_ENDPOINT,
        log=None) -> dict:
    """Весь путь по ступеням. Печатает КАЖДУЮ сразу и стоит на первой «не годно»."""
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    say(f"стенд: {len(STAGES)} ступеней, останов на первой «{FAIL}»; "
        f"платный вызов ровно один (${KLING_PRICE_USD} за "
        f"{PRODUCT_SECONDS:g} с, {KLING_PRICE_PER_SECOND_USD}/с)", log=log)

    styled = out / "styled.png"
    window = out / "window.mp4"
    produced = out / "kling_out.mp4"
    final = out / "final_9x16.mp4"

    stages, stopped = [], None

    def step(fn):
        nonlocal stopped
        t0 = time.perf_counter()
        res = fn()
        res["elapsed"] = round(time.perf_counter() - t0, 2)
        stages.append(res)
        say(line(res) + f" | {res['elapsed']} с", log=log)
        for c in res["checks"]:
            say(f"      · {c['name']}: {c['outcome']} — {c['note']}", log=log)
        if res["outcome"] != PASS and stopped is None:
            stopped = res
        return res

    r1 = step(lambda: stage_intake(client_photo=client_photo, style_ref=style_ref,
                                   driving=driving, intake=intake,
                                   driving_frames=driving_frames,
                                   card_reader=card_reader))
    if r1["outcome"] == PASS:
        r2 = step(lambda: stage_stylize(client_photo=client_photo,
                                        style_ref=style_ref, out_path=styled,
                                        stylize=stylize, card_reader=card_reader,
                                        aesthetic=aesthetic,
                                        client_gender=client_gender,
                                        plan=plan, aesthetic_mod=aesthetic_mod,
                                        extend=extend, pose=pose, card=card))
        if r2["outcome"] == PASS:
            r3 = step(lambda: stage_style_acceptance(
                styled=r2.get("styled", styled), style_ref=style_ref,
                client_photo=client_photo, similarity=similarity,
                distances=distances, operator_ok_identity=operator_ok_identity))
            if r3["outcome"] == PASS:
                r4 = step(lambda: stage_window(driving=driving, first=first,
                                               last=last, out_path=window,
                                               probe=probe, cutter=cutter))
                if r4["outcome"] == PASS:
                    r5 = step(lambda: stage_kling(
                        styled=r2.get("styled", styled),
                        window=r4.get("window", window), out_path=produced,
                        upload=upload, kling=kling, probe=probe,
                        endpoint=endpoint, orientation=orientation))
                    if r5["outcome"] == PASS:
                        r6 = step(lambda: stage_output_acceptance(
                            produced=r5.get("produced", produced),
                            client_photo=client_photo,
                            frames_dir=out / "out_frames", probe=probe,
                            decode=decode, distances=distances, cuts=cuts,
                            operator_ok_identity=operator_ok_identity))
                        if r6["outcome"] != FAIL:
                            step(lambda: stage_finish(
                                produced=r5.get("produced", produced),
                                driving=driving, out_path=final,
                                window=(first, last), finish=finish))

    report = stage_report(stages, out_path=out / "e2e_report.json")
    stages_before_report = list(stages)
    stages.append(report)
    say(line(report), log=log)

    outcome = stopped["outcome"] if stopped is not None else report["outcome"]
    where = (f"{stopped['stage']}" if stopped is not None else "все ступени")
    totals = report["totals"]
    say(f"ИТОГ: {outcome} на ступени «{where}» | ступеней пройдено "
        f"{totals['stages_passed']} из {len(STAGES) - 1} | проверок "
        f"{totals['checked']}, нарушений {totals['violations']}, не смогли "
        f"{totals['unmeasured']}", log=log)
    return {"outcome": outcome, "stopped_at": where,
            "stopped_index": (stages_before_report.index(stopped) + 1
                              if stopped is not None else None),
            "stages": stages, "totals": totals,
            "exit_code": EXIT_BY_OUTCOME[outcome],
            "report": str(out / "e2e_report.json")}


def parse_window(text: str) -> tuple:
    """`первый:последний` -> пара чисел. Мусор — исключение, а не догадка."""
    parts = str(text).split(":")
    if len(parts) != 2 or not all(p.strip().lstrip("-").isdigit() for p in parts):
        raise ValueError(f"окно {text!r} не вида «первый:последний», например 100:199")
    first, last = int(parts[0]), int(parts[1])
    if first > last:
        raise ValueError(f"окно {text!r}: первый кадр за последним")
    return first, last


def frame_paths(directory) -> list | None:
    """Кадры каталога по порядку. Пустой каталог — исключение, а не тишина."""
    if directory is None:
        return None
    root = Path(directory)
    if not root.is_dir():
        raise ValueError(f"каталог кадров {directory!r} не существует")
    got = sorted(str(p) for p in root.iterdir()
                 if p.suffix.lower() in FRAME_SUFFIXES)
    if not got:
        raise ValueError(f"каталог кадров {directory!r} пуст: "
                         f"ждали файлы {', '.join(sorted(FRAME_SUFFIXES))}")
    return got


def main(argv=None) -> int:
    """Тонкая точка входа: разбор аргументов и вызов `run`."""
    import argparse                                      # noqa: PLC0415

    ap = argparse.ArgumentParser(description="сквозной стенд продукта")
    ap.add_argument("--client", required=True)
    ap.add_argument("--style", default=None,
                    help="стилевой референс; не нужен при --aesthetic")
    ap.add_argument("--driving", required=True)
    ap.add_argument("--window", required=True, help="первый:последний, напр. 100:199")
    ap.add_argument("--out", default="work/e2e")
    ap.add_argument("--aesthetic", default=None,
                    help="имя эстетики из assets/fork_aesthetics.json")
    ap.add_argument("--client-gender", default=None, choices=("m", "f"),
                    help="пол клиента; обязателен вместе с --aesthetic")
    ap.add_argument("--frames", default=None,
                    help="каталог с уже распакованными кадрами драйвинга")
    ap.add_argument("--operator-ok-identity", action="store_true",
                    help="оператор посмотрел глазами и допустил личность")
    a = ap.parse_args(argv)
    if a.aesthetic is None and a.style is None:
        ap.error("нужен либо --style, либо --aesthetic")
    if a.aesthetic is not None and a.client_gender is None:
        ap.error("--aesthetic требует --client-gender")
    first, last = parse_window(a.window)
    got = run(client_photo=a.client, style_ref=a.style, driving=a.driving,
              first=first, last=last, out_dir=a.out,
              driving_frames=frame_paths(a.frames),
              aesthetic=a.aesthetic, client_gender=a.client_gender,
              operator_ok_identity=a.operator_ok_identity)
    return got["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
