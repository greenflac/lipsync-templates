"""Ось личности, у которой якорь — сырая фотография клиента, и только она."""

from __future__ import annotations

import json
from pathlib import Path

from .identity_arcface import HARD_DRIFT_MAX, SAME_PERSON_MAX

DEFAULT_INSTRUMENT = "identity_arcface"

INSTRUMENT_LICENCE = {
    "identity_arcface": ("buffalo_l / InsightFace — non-commercial. "
                         "В учёт к отгрузке, работу не блокирует. "
                         "Цена замены: пересчёт всех порогов."),
}

PASS, FAIL, UNMEASURED = "годно", "не годно", "не смогли проверить"

from .identity_arcface import MIN_COVERAGE  # noqa: E402

FOREIGN_FACE_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "foreign_face.png"

UPSCALE_DRIFT_MAX = 0.05

RESTORE_PULL_MAX = 0.05

ACCEPTANCE_ROWS = {
    "против сырой фотографии": {
        "target": {"median": 0.5067, "inside": 0, "judged": 21},
        "reproduced": None,
        "outcome": UNMEASURED,
        "why": ("сырой фотографии НЕТ в дереве. Манифест "
                "манифест калибровочного набора прямо говорит, что якорь "
                "`img/real_0000.png` — МЕДОИД порождённых, а загруженная "
                "фотография исключена составителем шаблонов намеренно. Мерить не от "
                "чего; 0.5067 снято тогда, когда фотография была. ЭТО "
                "ГЛАВНАЯ строка приёмки, и она НЕ ЗАКРЫТА."),
    },
    "против медоида": {
        "target": {"median": 0.2579, "inside": 19, "judged": 21},
        "reproduced": {"median": 0.2579, "inside": 19, "judged": 21},
        "outcome": PASS,
        "why": ("воспроизведено точно, до четвёртого знака, командой "
                "`python3 -m unittest lipsync.tests.test_fork_identity`. "
                "Доказывает, что ПРИБОР тот же. Про продукт не говорит "
                "ничего: это порождённое против порождённого."),
    },
    "негативный контроль": {
        "target": {"band": (0.96, 1.05), "inside": 0},
        "reproduced": {"median": 0.6809, "min": 0.5478, "max": 0.7454,
                       "inside": 0, "judged": 21},
        "outcome": UNMEASURED,
        "why": ("направление верное — 0 из 21 в баре, медиана 0.6809 выше "
                "HARD_DRIFT_MAX 0.6, прибор говорит «другой человек». Но "
                "полоса 0.96–1.05 снималась на фотографии, которой в дереве "
                "нет, и 0.6809 — самое далёкое, что ПРИБОР нашёл среди "
                "имеющегося (66 кадров просмотрено). Выдавать 0.68 за "
                "0.96–1.05 нельзя."),
    },
}


class DerivedAnchor(ValueError):
    """Якорем подан кадр из судимого набора. Это и есть дефект медоида."""


def _samples(manifest_path: str | Path) -> list:
    """Пути всех кадров набора, относительно каталога манифеста."""
    p = Path(manifest_path)
    data = json.loads(p.read_text(encoding="utf-8"))
    root = p.parent
    return [(root / s["path"]).resolve() for s in data.get("samples", [])]


def refuse_derived_anchor(anchor: str | Path, frames, *,
                          manifest: str | Path | None = None) -> None:
    """Уронить прогон, если якорь взят из того, что судят. Медоид — этот случай."""
    a = Path(anchor).resolve()
    if a in {Path(f).resolve() for f in frames}:
        raise DerivedAnchor(
            f"якорем подан кадр из судимого набора: {a.name}. Это сравнение "
            f"порождённого с порождённым — ровно тот дефект, из-за которого "
            f"0.2579 однажды прочли как успех при 0.5067 на настоящем якоре.")
    if manifest is None:
        return
    if a in _samples(manifest):
        raise DerivedAnchor(
            f"якорь {a.name} перечислен в наборе {Path(manifest).name} среди "
            f"samples: по происхождению он производный, даже если в судимый "
            f"список не попал. Якорем может быть только ЗАГРУЖЕННАЯ "
            f"фотография.")
    text = Path(manifest).read_text(encoding="utf-8")
    if "МЕДОИД" in text and a.name in text:
        raise DerivedAnchor(
            f"манифест {Path(manifest).name} сам называет {a.name} медоидом.")


def _instrument(name: str):
    """Прибор по имени. Только известные — опечатка не должна давать заглушку."""
    if name != DEFAULT_INSTRUMENT:
        raise ValueError(
            f"неизвестный прибор личности: {name!r}. Известен "
            f"{DEFAULT_INSTRUMENT!r}. Смена прибора обнуляет все снятые числа "
            f"и делается решением, а не опечаткой.")
    from . import identity_arcface

    return identity_arcface


def distances(frames, anchor: str | Path, *,
              instrument: str = DEFAULT_INSTRUMENT,
              min_face_px: int | None = None) -> dict:
    """Расстояния от каждого кадра до якоря. Три исхода на кадр, не два."""
    mod = _instrument(instrument)
    a = mod.face_detail(anchor)
    empty = {"per_frame": {}, "face_px": {}, "no_face": [], "too_small": [],
             "median": None, "min": None, "max": None,
             "inside": 0, "judged": 0, "total": 0,
             "coverage": 0.0, "outcome": UNMEASURED,
             "bar": SAME_PERSON_MAX, "min_face_px": min_face_px}
    if a is None:
        return {**empty,
                "note": f"на якоре {Path(anchor).name} лица нет: мерить не от чего"}

    per_frame, face_px, no_face, too_small = {}, {}, [], []
    total = 0
    for p in frames:
        total += 1
        name = Path(p).name
        d = mod.face_detail(p)
        if d is None:
            no_face.append(name)
            continue
        face_px[name] = d["face_px"]
        if min_face_px is not None and d["face_px"] < min_face_px:
            too_small.append(name)
            continue
        per_frame[name] = mod.cosine_distance(a["embedding"], d["embedding"])

    if not per_frame:
        return {**empty, "total": total, "face_px": face_px,
                "no_face": no_face, "too_small": too_small,
                "note": (f"судить нечего: из {total} кадров {len(no_face)} без "
                         f"лица, {len(too_small)} с лицом мельче "
                         f"{min_face_px}px. Это НЕ «другой человек».")}

    vals = sorted(per_frame.values())
    inside = sum(1 for v in vals if v <= SAME_PERSON_MAX)
    coverage = round(len(vals) / total, 3)
    return {
        "per_frame": per_frame, "face_px": face_px,
        "no_face": no_face, "too_small": too_small,
        "median": round(mod._quantile(vals, 0.5), 4),
        "min": round(vals[0], 4), "max": round(vals[-1], 4),
        "inside": inside, "judged": len(vals), "total": total,
        "coverage": coverage,
        "bar": SAME_PERSON_MAX, "min_face_px": min_face_px,
        "outcome": UNMEASURED if coverage < MIN_COVERAGE else (
            PASS if inside * 2 > len(vals) else FAIL),
        "note": (f"{instrument}: медиана "
                 f"{round(mod._quantile(vals, 0.5), 4)}, "
                 f"в баре {SAME_PERSON_MAX}: {inside} из {len(vals)} судимых "
                 f"(всего {total}; отсев по размеру лица: "
                 f"{'выключен' if min_face_px is None else str(min_face_px) + 'px'})"),
    }


def axis(frames, *, raw_photo: str | Path,
         upscaled_reference: str | Path | None = None,
         foreign: str | Path | None = None,
         driving_actor: str | Path | None = None,
         manifest: str | Path | None = None,
         instrument: str = DEFAULT_INSTRUMENT,
         min_face_px: int | None = None) -> dict:
    """Четыре числа разом, с вердиктом ПО СЫРОЙ ФОТОГРАФИИ и ни по чему другому."""
    refuse_derived_anchor(raw_photo, frames, manifest=manifest)
    if upscaled_reference is not None:
        refuse_derived_anchor(upscaled_reference, frames, manifest=manifest)

    out = {
        "instrument": instrument,
        "licence": INSTRUMENT_LICENCE.get(instrument, "лицензия не проверена"),
        "bar": SAME_PERSON_MAX,
        "hard_bar": HARD_DRIFT_MAX,
        "d_raw": distances(frames, raw_photo, instrument=instrument,
                           min_face_px=min_face_px),
        "d_ref": None,
        "d_neg": None,
        "d_drv": None,
        "control": "НЕ СТАВИЛСЯ",
        "leak_to_actor": "НЕ ПРОВЕРЯЛАСЬ",
        "upscale": "НЕ ПРОВЕРЯЛСЯ",
    }
    if upscaled_reference is not None:
        out["d_ref"] = distances(frames, upscaled_reference,
                                 instrument=instrument,
                                 min_face_px=min_face_px)
        out["upscale"] = upscale_drift_verdict(out["d_raw"], out["d_ref"])
    if foreign is not None:
        out["d_neg"] = distances(frames, foreign, instrument=instrument,
                                 min_face_px=min_face_px)
        out["control"] = control_verdict(out["d_neg"])
    if driving_actor is not None:
        out["d_drv"] = distances(frames, driving_actor, instrument=instrument,
                                 min_face_px=min_face_px)
        out["leak_to_actor"] = actor_leak_verdict(out["d_raw"], out["d_drv"])

    out["verdict"] = out["d_raw"]["outcome"]
    out["note"] = _note(out)
    return out


def control_verdict(d_neg: dict) -> str:
    """Сработал ли негативный контроль. Тоже три исхода."""
    if d_neg.get("median") is None:
        return f"{UNMEASURED}: контроль не дал ни одного судимого кадра"
    if d_neg["inside"] > 0:
        return (f"{FAIL}: прибор принял чужого человека за своего на "
                f"{d_neg['inside']} кадре(ах) — числа прогона недействительны")
    if d_neg["median"] < HARD_DRIFT_MAX:
        return (f"{UNMEASURED}: чужой стоит на {d_neg['median']}, ниже "
                f"{HARD_DRIFT_MAX} — контроль слабый, полосу «заведомо чужой» "
                f"он не показывает")
    return f"{PASS}: чужой на {d_neg['median']}, ни одного кадра в баре"


def upscale_drift_verdict(d_raw: dict, d_ref: dict, *,
                          drift_max: float = UPSCALE_DRIFT_MAX) -> str:
    """ЧТО ДАЛ АПСКЕЙЛ ЛИЦА. Не вердикт личности и никогда им не станет."""
    a, b = d_raw.get("median"), d_ref.get("median")
    if a is None or b is None:
        return (f"{UNMEASURED}: нет одной из двух медиан (до сырой {a}, до "
                f"референса {b}). Это НЕ «апскейл безвреден».")
    drift = round(b - a, 4)
    if drift < -drift_max:
        return (f"{FAIL}: до референса {b} против {a} до сырой фотографии — "
                f"кадры ближе к референсу на {abs(drift)} при пороге "
                f"{drift_max}. Апскейлер ДОРИСОВАЛ лицо: референс перестал "
                f"быть клиентом, а d_ref — сравнением с ним.")
    if drift > drift_max:
        return (f"{FAIL}: до референса {b} против {a} до сырой фотографии — "
                f"референс дальше на {drift} при пороге {drift_max}. "
                f"Апскейлер лицо испортил.")
    return (f"{PASS}: до сырой {a}, до референса после апскейла {b}, "
            f"расхождение {drift} в пределах {drift_max} — апскейл личность "
            f"не сдвинул")


def actor_leak_verdict(d_raw: dict, d_drv: dict) -> str:
    """Не уехал ли выход к АКТЁРУ ДРАЙВИНГА вместо клиента. Четвёртое число."""
    if d_raw.get("median") is None or d_drv.get("median") is None:
        return (f"{UNMEASURED}: нет одного из двух расстояний "
                f"(до клиента {d_raw.get('median')}, "
                f"до актёра {d_drv.get('median')})")
    if d_drv["median"] < d_raw["median"]:
        return (f"{FAIL}: до актёра драйвинга {d_drv['median']} БЛИЖЕ, чем до "
                f"клиента {d_raw['median']} — лицо утекло из драйвинга")
    return (f"{PASS}: до клиента {d_raw['median']}, до актёра "
            f"{d_drv['median']} — актёр дальше, утечки не видно")


def before_after_restore(before_frames, after_frames, *,
                         raw_photo: str | Path,
                         instrument: str = DEFAULT_INSTRUMENT,
                         min_face_px: int | None = None) -> dict:
    """Личность ДО и ПОСЛЕ доводки лица, ОДНИМ баром, парой."""
    common = {"instrument": instrument, "min_face_px": min_face_px}
    before = distances(before_frames, raw_photo, **common)
    after = distances(after_frames, raw_photo, **common)

    if (before["bar"], before["min_face_px"]) != (after["bar"],
                                                  after["min_face_px"]):
        raise RuntimeError(
            f"половины пары измерены РАЗНЫМИ условиями: до — бар "
            f"{before['bar']}, отсев {before['min_face_px']}; после — бар "
            f"{after['bar']}, отсев {after['min_face_px']}. Такие два числа "
            f"несравнимы, и «стало лучше» по ним не значит ничего.")

    judged_gain = after["judged"] - before["judged"]
    delta = (None if before["median"] is None or after["median"] is None
             else round(after["median"] - before["median"], 4))

    if after["median"] is None:
        outcome = UNMEASURED
    elif before["median"] is None:
        outcome = PASS if after["outcome"] == PASS else after["outcome"]
    else:
        outcome = after["outcome"]

    return {
        "outcome": outcome,
        "bar": SAME_PERSON_MAX,
        "before": before, "after": after,
        "delta": delta, "judged_gain": judged_gain,
        "note": (
            f"личность ОДНИМ баром {SAME_PERSON_MAX}. "
            f"ДО доводки: медиана {before['median']}, судимо "
            f"{before['judged']} из {before['total']}. "
            f"ПОСЛЕ: медиана {after['median']}, судимо {after['judged']} из "
            f"{after['total']}. "
            + (f"Медиана сдвинулась на {delta}. " if delta is not None else
               "Медианы не с чем сравнить — до доводки судить было нечем, и "
               "это НЕ ухудшение, а первое измерение. ")
            + (f"Судимых кадров стало больше на {judged_gain}."
               if judged_gain > 0 else
               f"Судимых кадров не прибавилось ({judged_gain})."
               if judged_gain <= 0 else "")),
    }


def restore_negative_control(restored_foreign_frames=None, *,
                             raw_photo: str | Path,
                             foreign_frames_before=None,
                             instrument: str = DEFAULT_INSTRUMENT,
                             min_face_px: int | None = None,
                             pull_max: float = RESTORE_PULL_MAX) -> dict:
    """НЕГАТИВНЫЙ КОНТРОЛЬ ДЛЯ ДОВОДКИ ЛИЦА. Пробел, которого не было в §7."""
    common = {"instrument": instrument, "min_face_px": min_face_px}
    out = {"bar": SAME_PERSON_MAX, "pull_max": pull_max,
           "before": None, "after": None, "pull": None}
    if restored_foreign_frames is None:
        return {**out, "outcome": UNMEASURED,
                "note": ("НЕПРОВЕРЕНО: доводчик на чужом лице не прогонялся "
                         "(нужна карта). Пока этого прогона нет, d_raw ПОСЛЕ "
                         "доводки не отделён от качества доводчика — это "
                         "«не смогли проверить», а НЕ «доводчик честен».")}

    after = distances(restored_foreign_frames, raw_photo, **common)
    out["after"] = after
    if after["median"] is None:
        return {**out, "outcome": UNMEASURED,
                "note": (f"контроль доводки не дал ни одного судимого кадра: "
                         f"{after['note']}. Это НЕ «доводчик честен».")}

    if after["inside"] > 0:
        return {**out, "outcome": FAIL,
                "note": (f"ДОВОДЧИК ПЕЧАТАЕТ РЕФЕРЕНС: чужое лицо после "
                         f"доводки попало в бар {SAME_PERSON_MAX} к клиенту на "
                         f"{after['inside']} кадре(ах) из {after['judged']}, "
                         f"медиана {after['median']}. Значит d_raw после "
                         f"доводки измеряет доводчик, а не Wan-Animate, и все "
                         f"числа оси после доводки НЕДЕЙСТВИТЕЛЬНЫ.")}

    if foreign_frames_before is None:
        return {**out, "outcome": PASS,
                "note": (f"чужое лицо после доводки стоит на "
                         f"{after['median']}, ни одного кадра в баре "
                         f"{SAME_PERSON_MAX} — доводчик референс не печатает. "
                         f"ПОДТЯЖКА НЕ МЕРЕНА: кадров ДО доводки не подано, "
                         f"ранняя стадия той же болезни осталась бы невидимой.")}

    before = distances(foreign_frames_before, raw_photo, **common)
    out["before"] = before
    if before["median"] is None:
        return {**out, "outcome": UNMEASURED,
                "note": (f"чужое лицо ДО доводки судить нечем "
                         f"({before['note']}), а без этого числа подтяжку не "
                         f"вычесть: {after['median']} не с чем сравнить.")}

    pull = round(before["median"] - after["median"], 4)
    out["pull"] = pull
    if pull > pull_max:
        return {**out, "outcome": FAIL,
                "note": (f"доводчик ПОДТЯНУЛ чужое лицо к клиенту на {pull} "
                         f"({before['median']} → {after['median']}) при пороге "
                         f"{pull_max}. В бар {SAME_PERSON_MAX} чужой не попал, "
                         f"но направление то самое: доводчик подмешивает "
                         f"референс, и d_raw после него завышен.")}
    return {**out, "outcome": PASS,
            "note": (f"чужое лицо {before['median']} → {after['median']}, "
                     f"подтяжка {pull} не превышает {pull_max}, в баре "
                     f"{SAME_PERSON_MAX} ноль кадров из {after['judged']} — "
                     f"доводчик референс не печатает, d_raw после доводки "
                     f"измеряет Wan-Animate")}


def acceptance_report() -> dict:
    """Что из приёмки §6 A ДЕЙСТВИТЕЛЬНО воспроизведено. Числами, а не флагом."""
    rows = ACCEPTANCE_ROWS
    done = [n for n, r in rows.items() if r["outcome"] == PASS]
    unmeasured = [n for n, r in rows.items() if r["outcome"] == UNMEASURED]
    failed = [n for n, r in rows.items() if r["outcome"] == FAIL]
    outcome = PASS if len(done) == len(rows) else (
        FAIL if failed else UNMEASURED)
    return {
        "outcome": outcome,
        "reproduced": len(done), "of": len(rows),
        "unmeasured": unmeasured, "failed": failed, "rows": rows,
        "note": (f"приёмка §6 A: воспроизведено {len(done)} строк(и) из "
                 f"{len(rows)}, не смогли {len(unmeasured)}, провалено "
                 f"{len(failed)}. Воспроизведено: {', '.join(done) or '—'}. "
                 f"НЕ СМОГЛИ: {', '.join(unmeasured) or '—'}. "
                 + ("ХЭНДОФ требует ВСЕ ТРИ, и все три воспроизведены: "
                    "приёмка потока ЗАКРЫТА." if outcome == PASS else
                    f"ХЭНДОФ требует ВСЕ ТРИ, поэтому приёмка потока НЕ "
                    f"ЗАКРЫТА — и «{len(done)} из {len(rows)}» тут не «почти», "
                    f"а «главная строка не мерена».")),
    }


def lora_regression(without: dict, with_lora: dict, *,
                    worse_by: float = 0.02) -> dict:
    """Портится ли `d_raw` при ВКЛЮЧЁННОЙ LoRA. Приёмка гипотезы LoRA темплейта."""
    a, b = without.get("median"), with_lora.get("median")
    if a is None or b is None:
        return {"outcome": UNMEASURED, "delta": None,
                "note": (f"нет одной из двух медиан (без LoRA {a}, с LoRA "
                         f"{b}): сравнивать нечего. Это НЕ «LoRA безвредна».")}
    delta = round(b - a, 4)
    if delta > worse_by:
        return {"outcome": FAIL, "delta": delta,
                "note": (f"с LoRA {b} против {a} без неё — хуже на {delta} "
                         f"при пороге различимости {worse_by}. LoRA тянет "
                         f"лицо к среднему по категории.")}
    return {"outcome": PASS, "delta": delta,
            "note": (f"с LoRA {b} против {a} без неё — разница {delta} не "
                     f"превышает порог различимости {worse_by}")}


def _note(out: dict) -> str:
    """Отчёт числами: проверено N, в баре M, не смогли K."""
    raw = out["d_raw"]
    head = (f"ВЕРДИКТ ПО СЫРОЙ ФОТОГРАФИИ: {raw['outcome']}. "
            f"медиана {raw['median']}, в баре {raw['inside']} из "
            f"{raw['judged']} судимых, не смогли "
            f"{len(raw['no_face']) + len(raw['too_small'])} из {raw['total']}.")
    if out["d_ref"] is not None:
        ref = out["d_ref"]
        head += (f" СПРАВОЧНО, НЕ ВЕРДИКТ — до референса (сырая фотография "
                 f"ПОСЛЕ АПСКЕЙЛА ЛИЦА, порождённого звена нет): медиана "
                 f"{ref['median']}, в баре {ref['inside']} из {ref['judged']}."
                 f" ЧТО ДАЛ АПСКЕЙЛ: {out['upscale']}.")
    if out.get("d_drv") is not None:
        head += f" УТЕЧКА К АКТЁРУ ДРАЙВИНГА: {out['leak_to_actor']}."
    head += f" КОНТРОЛЬ: {out['control']}."
    head += f" ЛИЦЕНЗИЯ ПРИБОРА: {out['licence']}"
    return head
