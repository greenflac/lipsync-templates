"""Эстетика: шаг составителя шаблона. Промт плюс демо-личность -> эстетика."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .fork_identity import FAIL, PASS, SAME_PERSON_MAX, UNMEASURED

BASE_PATH = Path(__file__).resolve().parent.parent / "assets" / "fork_aesthetics.json"

IDENTITY_CLAUSE = (
    "the person in the frame is the person from the input image: same face, "
    "same facial features, same skin tone and same hair colour; where the "
    "description above names a different appearance, the input image wins on "
    "identity and the description applies only to wardrobe, hairstyling, "
    "setting, lens, lighting, pose and mood"
)


ANTHROPOMETRY_CLAUSES = (
    r"\bhas\b[^,]*\bskin\b",
    r"\b\w+ skin with\b",
    r"\bflawless skin\b",
    r"\bfreckles?\b",
    r"\bcomplexion\b",
    r"\b(green|blue|brown|hazel|grey|gray|dark|light|piercing) eyes\b",
    r"\bfacial features?\b",
    r"\bcheekbones?\b",
    r"\bjawline\b",
    r"\bbody type\b",
    r"\bphysique\b",
)

ANTHROPOMETRY_WORDS = (
    r"\b(?:extremely|very|incredibly|stunningly|exceptionally)?\s*beautiful\b",
    r"\bsupermodel-level\b", r"\bsupermodel\b", r"\bbeauty\b",
    r"\b(?:extremely|very)?\s*(?:gorgeous|stunning|attractive|pretty)\b",
    r"\bbrunette\b", r"\bblonde?\b", r"\bplatinum\b", r"\bginger\b",
    r"\bauburn\b", r"\bredhead\b", r"\b(?:red|dark|fair)-haired\b",
    r"\btanned\b", r"\b(?:olive|pale|fair)-skinned\b",
    r"\bslavic\b", r"\bnordic\b", r"\bscandinavian\b", r"\basian\b",
    r"\bafrican\b", r"\blatina\b", r"\bcaucasian\b",
    r"\bslim\b", r"\bcurvy\b", r"\bpetite\b", r"\bathletic\b",
)

GENDER_SWAPS = (
    ("women", "people"), ("woman", "person"), ("men", "people"),
    ("man", "person"), ("girl", "person"), ("boy", "person"),
    ("lady", "person"), ("female", "person"), ("male", "person"),
    ("herself", "themselves"), ("himself", "themselves"),
    ("hers", "theirs"), ("her", "their"), ("his", "their"),
    ("she", "they"), ("he", "they"),
)


def _clause_is_anthropometric(clause: str) -> str | None:
    """Образец, по которому оборот признан описанием человека, или None."""
    for pattern in ANTHROPOMETRY_CLAUSES:
        if re.search(pattern, clause, re.IGNORECASE):
            return pattern
    return None


def strip_anthropometry(prompt: str) -> dict:
    """Убрать из промта всё, что описывает ЧЕЛОВЕКА, оставив всё про КАДР."""
    if not isinstance(prompt, str) or not prompt.strip():
        return {**tally(0, 0, 1), "prompt": None, "dropped": [], "words": [],
                "genders": [], "cut_share": None,
                "note": "промта нет: резать нечего"}

    kept, dropped = [], []
    for clause in prompt.split(","):
        hit = _clause_is_anthropometric(clause)
        if hit:
            dropped.append({"clause": clause.strip(), "pattern": hit})
        else:
            kept.append(clause)
    text = ",".join(kept)

    words = []
    for pattern in ANTHROPOMETRY_WORDS:
        text, n = re.subn(pattern + r"\s*", "", text, flags=re.IGNORECASE)
        if n:
            words.append({"pattern": pattern, "times": n})

    genders = []
    for src, dst in GENDER_SWAPS:
        text, n = re.subn(rf"\b{re.escape(src)}\b", dst, text,
                          flags=re.IGNORECASE)
        if n:
            genders.append({"from": src, "to": dst, "times": n})

    text = re.sub(r"\s{2,}", " ", text)
    text = re.sub(r"\s+,", ",", text)
    text = re.sub(r"(,\s*){2,}", ", ", text).strip().strip(",").strip()
    text = re.sub(r"\ban\s+(?=[^aeiouAEIOU\s])", "a ", text)
    text = re.sub(r"\ba\s+(?=[aeiouAEIOU])", "an ", text)
    text = re.sub(r"(^|[.!?]\s+)([a-z])",
                  lambda m: m.group(1) + m.group(2).upper(), text)

    return {**tally(1, 0, 0), "prompt": text,
            "dropped": dropped, "words": words, "genders": genders,
            "cut_share": round(1 - len(text.split()) / len(prompt.split()), 4),
            "note": (f"оборотов унесено {len(dropped)}, слов тела "
                     f"{sum(w['times'] for w in words)}, замен пола "
                     f"{sum(g['times'] for g in genders)}; слов было "
                     f"{len(prompt.split())}, стало {len(text.split())}")}


DEMOS = {
    "m": "assets/fork_plan_man_fullbody.png",
    "f": "assets/fork_plan_woman_fullbody.png",
}

GENDERS = tuple(DEMOS)

AESTHETIC_DIR = Path("assets") / "aesthetics"


def demo_for(gender: str):
    """Демо-личность по полу. Неизвестный пол — исключение, а не умолчание:"""
    key = str(gender).strip().lower()
    if key not in DEMOS:
        raise KeyError(f"пол {gender!r} не из {GENDERS}")
    return DEMOS[key]


def gender_of(aesthetic) -> str:
    """Пол шаблона. Он же пол эстетики: по решению составителя шаблонов пол"""
    if isinstance(aesthetic, str):
        aesthetic = load(aesthetic)
    got = (aesthetic or {}).get("demo")
    if str(got).strip().lower() not in DEMOS:
        raise KeyError(f"у эстетики {(aesthetic or {}).get('id')!r} не назван "
                       f"пол (поле «demo» из {GENDERS}), получено {got!r}")
    return str(got).strip().lower()


def aesthetic_file(aesthetic_id: str, gender: str | None = None, *,
                   root=None) -> Path:
    """Путь эстетики. Пол В ИМЕНИ ФАЙЛА, а не только в базе: имя едет вместе с"""
    g = gender_of(aesthetic_id) if gender is None else str(gender).strip().lower()
    demo_for(g)
    base = AESTHETIC_DIR if root is None else Path(root)
    return base / f"{aesthetic_id}_{g}.png"


def pair_check(*, client_gender: str, aesthetic_gender: str) -> dict:
    """Совпадают ли пол клиента и пол эстетики. ГЕЙТ, а не совет."""
    def known(value):
        return str(value).strip().lower() if str(value).strip().lower() in DEMOS else None

    c, a = known(client_gender), known(aesthetic_gender)
    if c is None or a is None:
        return {**tally(0, 0, 1), "client": c, "aesthetic": a,
                "note": (f"пол не назван или не из {GENDERS}: клиент "
                         f"{client_gender!r}, эстетика {aesthetic_gender!r}. "
                         f"Это НЕ разрешение продолжать")}
    if c != a:
        return {**tally(1, 1, 0), "client": c, "aesthetic": a,
                "note": (f"ПОЛ РАЗЪЕХАЛСЯ: клиент {c}, эстетика {a}. ИЗМЕРЕНО, "
                         f"чем это кончается: клиент-мужчина с женской "
                         f"эстетикой получил женскую мини-юбку, и ни один "
                         f"прибор этого не увидел")}
    return {**tally(1, 0, 0), "client": c, "aesthetic": a,
            "note": f"пол совпал: {c}"}


AESTHETIC_ROLE_CLAUSE = (
    "keep the FACE and identity of the person from the FIRST image completely "
    "unchanged — same face, same facial features, same skin tone, same hair "
    "colour, same body; take the wardrobe, styling, accessories, hairstyling, "
    "pose, framing, lens, lighting, colour grade and setting from the SECOND "
    "image"
)

NEVER_THE_FACE_CLAUSE = (
    "never copy the face, facial features or identity of the person in the "
    "SECOND image; that person is a wardrobe and styling reference only, and "
    "must not appear in the result"
)


def assemble_prompt(*, legacy: bool = False, card=None) -> str:
    """Промт сборки рефки. `legacy=True` даёт СТАРЫЕ строки стенда."""
    if legacy:
        from .fork_e2e import (NO_LOOK_TRANSFER_CLAUSE,     # noqa: PLC0415
                               ROLE_CLAUSE)

        return f"{ROLE_CLAUSE}. {NO_LOOK_TRANSFER_CLAUSE}. {no_brands_clause()}"
    framing = framing_clause(card)
    tail = f" {framing}." if framing else ""
    return (f"{AESTHETIC_ROLE_CLAUSE}. {NEVER_THE_FACE_CLAUSE}.{tail} "
            f"{no_brands_clause()}")


def leak_verdict(*, made, client, demo, distances=None) -> dict:
    """ДВУСТОРОННИЙ замер: кто на собранной рефке — клиент или демо."""
    t0 = time.perf_counter()
    if distances is None:
        from . import fork_identity                       # noqa: PLC0415

        distances = fork_identity.distances
    out = {"seconds": None, "to_client": None, "to_demo": None, "gap": None}
    try:
        c = distances([str(made)], str(client))
        d = distances([str(made)], str(demo))
    except Exception as exc:                              # noqa: BLE001
        return {**tally(0, 0, 1), **out,
                "note": f"прибор упал: {type(exc).__name__}: {exc}"}
    to_client, to_demo = c.get("median"), d.get("median")
    out.update({"to_client": to_client, "to_demo": to_demo,
                "seconds": round(time.perf_counter() - t0, 3)})
    if to_client is None or to_demo is None:
        return {**tally(0, 0, 1), **out,
                "note": (f"одно из расстояний не снято: до клиента "
                         f"{to_client}, до демо {to_demo}")}
    gap = round(to_demo - to_client, 4)
    out["gap"] = gap
    tail = (f"до клиента {to_client}, до демо {to_demo}, разность {gap} "
            f"(планка «тот же человек» {SAME_PERSON_MAX})")
    if to_demo < to_client:
        return {**tally(1, 1, 0), **out,
                "note": f"ЛИЧНОСТЬ ПРОТЕКЛА: демо БЛИЖЕ клиента; {tail}"}
    if to_client <= SAME_PERSON_MAX < to_demo:
        return {**tally(1, 0, 0), **out,
                "note": f"клиент на месте, демо не протекла; {tail}"}
    return {**tally(0, 0, 1), **out,
            "note": (f"прибор не различает: ни одно расстояние не по разные "
                     f"стороны планки; {tail}. СУДИТ ОПЕРАТОР ГЛАЗАМИ")}


PLAN_NOTE = ("план 9:16 на эстетике НЕ ТРЕБУЕТСЯ: план навязывается на "
             "собранной рефке клиента, а эстетика несёт вид, а не кадр")


def tally(checked: int, violations: int, unmeasured: int) -> dict:
    """Числа рядом с вердиктом."""
    if checked == 0:
        outcome = UNMEASURED
    elif violations:
        outcome = FAIL
    elif unmeasured:
        outcome = UNMEASURED
    else:
        outcome = PASS
    return {"outcome": outcome, "checked": checked,
            "violations": violations, "unmeasured": unmeasured}


def load_base(path=None) -> dict:
    """База эстетик с диска. Отсутствие файла — исключение, а не пустая база:"""
    p = Path(BASE_PATH if path is None else path)
    if not p.is_file():
        raise FileNotFoundError(f"базы эстетик нет: {p}")
    doc = json.loads(p.read_text(encoding="utf-8"))
    got = doc.get("aesthetics")
    if not isinstance(got, list) or not got:
        raise ValueError(f"в базе {p} нет ни одной эстетики")
    return doc


def ids(path=None) -> list:
    return [a["id"] for a in load_base(path)["aesthetics"]]


def load(aesthetic_id: str, path=None) -> dict:
    """Одна эстетика по имени. Неизвестное имя — исключение со списком того,"""
    for a in load_base(path)["aesthetics"]:
        if a["id"] == aesthetic_id:
            return a
    raise KeyError(f"эстетики {aesthetic_id!r} нет; есть: "
                   f"{', '.join(ids(path))}")


def brand_conflict(aesthetic: dict) -> dict:
    """Какие марки названы в промте. СПРАВКА, а не гейт."""
    text = str(aesthetic.get("prompt", ""))
    hits = [w for w in ("Adidas", "Balenciaga", "Nike", "Gucci", "Prada",
                        "Zara", "Levi's", "Chanel") if w.lower() in text.lower()]
    if not hits:
        return {**tally(1, 0, 0), "brands": [],
                "note": "марок в промте не названо"}
    return {**tally(1, 0, 0), "brands": hits,
            "note": (f"промт называет марки {hits} — РАЗРЕШЕНО решением "
                     f"составителя шаблонов; запрещён только нарисованный знак, и "
                     f"его отсутствие СУДИТ ГЛАЗ: прибора для надписей нет")}


def no_brands_clause() -> str:
    """Запрет надписей ОДНИМ источником на проект. Импорт ленивый."""
    from .fork_e2e import NO_BRANDS_CLAUSE                # noqa: PLC0415

    return NO_BRANDS_CLAUSE


def framing_clause(card) -> str:
    """Строка кадрирования из КАРТОЧКИ ДРАЙВИНГА."""
    from . import fork_plan                               # noqa: PLC0415

    return fork_plan.framing_clause(card)


def compose(aesthetic, *, with_ban: bool = True, cut_body: bool = True,
            card=None) -> dict:
    """Промт эстетики: материал составителя шаблонов + разрешение конфликта личности."""
    if isinstance(aesthetic, str):
        aesthetic = load(aesthetic)
    if not isinstance(aesthetic, dict) or not aesthetic.get("prompt"):
        return {**tally(0, 0, 1), "prompt": None,
                "note": "эстетика без промта: собирать нечего"}
    own = aesthetic["prompt"].strip()
    cut = strip_anthropometry(own) if cut_body else None
    body = cut["prompt"] if cut and cut["outcome"] == PASS else own

    parts = [body, IDENTITY_CLAUSE]
    framing = framing_clause(card)
    if framing:
        parts.append(framing)
    if with_ban:
        parts.append(no_brands_clause())
    text = ". ".join(parts)
    how = ("промт составителя шаблонов без антропометрии" if cut_body else
           "промт составителя шаблонов ДОСЛОВНО (РЕЗ ОТКЛЮЧЁН ЯВНО)")
    return {**tally(1, 0, 0), "prompt": text,
            "id": aesthetic.get("id"), "kind": aesthetic.get("kind"),
            "words": len(text.split()), "cut": cut, "framed": bool(framing),
            "brand_conflict": brand_conflict(aesthetic),
            "note": (f"эстетика {aesthetic.get('id')}: слов {len(text.split())}, "
                     f"{how} + личность"
                     + ("" if with_ban else " (ЗАПРЕТ НАДПИСЕЙ ОТКЛЮЧЁН ЯВНО)")
                     + (f"; {cut['note']}" if cut else ""))}


def accept(*, made, demo, distances=None) -> dict:
    """Осталась ли на эстетике ДЕМО-личность. Единственная измеримая ось."""
    t0 = time.perf_counter()
    if distances is None:
        from . import fork_identity                       # noqa: PLC0415

        distances = fork_identity.distances
    try:
        d = distances([str(made)], str(demo))
    except Exception as exc:                              # noqa: BLE001
        return {**tally(0, 0, 1), "median": None,
                "seconds": round(time.perf_counter() - t0, 3),
                "note": f"прибор личности упал: {type(exc).__name__}: {exc}"}

    med = d.get("median")
    tail = (f"лестница: 0.0652 тот же, {SAME_PERSON_MAX} планка, 0.7137 другой, "
            f"1.0217 чужой")
    if d.get("outcome") == UNMEASURED or med is None:
        return {**tally(0, 0, 1), "median": med,
                "seconds": round(time.perf_counter() - t0, 3),
                "note": f"личность НЕ ИЗМЕРЕНА: {str(d.get('note'))[:200]}"}
    if med <= SAME_PERSON_MAX:
        return {**tally(1, 0, 0), "median": med,
                "seconds": round(time.perf_counter() - t0, 3),
                "note": (f"демо-личность на месте: медиана {med} при планке "
                         f"{SAME_PERSON_MAX} ({tail}). {PLAN_NOTE}. "
                         f"ПОПАДАНИЕ В ЭСТЕТИКУ СУДИТ СОСТАВИТЕЛЬ ГЛАЗАМИ — "
                         f"прибора для этого нет")}
    if med < 0.7137:
        return {**tally(0, 0, 1), "median": med,
                "seconds": round(time.perf_counter() - t0, 3),
                "note": (f"медиана {med} между планкой {SAME_PERSON_MAX} и "
                         f"ступенью «другой человек» 0.7137: лицо изменено или "
                         f"закрыто, ArcFace здесь НЕ СУДЬЯ, судит составитель "
                         f"({tail})")}
    return {**tally(1, 1, 0), "median": med,
            "seconds": round(time.perf_counter() - t0, 3),
            "note": (f"медиана {med} выше ступени «другой человек» 0.7137: "
                     f"промт ПЕРЕРИСОВАЛ человека, это не наша демо-личность "
                     f"({tail})")}


def render(report: dict) -> str:
    """Печать для человека."""
    return (f"ЭСТЕТИКА: {report['outcome']}  (проверено {report['checked']}, "
            f"нарушений {report['violations']}, не смогли "
            f"{report['unmeasured']})\n  {report.get('note', '')}")
