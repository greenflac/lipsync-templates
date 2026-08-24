"""Адаптер стиля: фоторференс -> карточка -> рабочий промт по скелету."""

from __future__ import annotations

import re

from .fork_identity import FAIL, PASS, UNMEASURED


WORDS_TARGET = 24

WORDS_MIN = 9
WORDS_MAX = 67

CLAUSES_TARGET = 5
CLAUSES_MIN = 1
CLAUSES_MAX = 13
CLAUSES_MOST_COMMON = 7

SUBJECT_WORDS = (
    "person", "man", "woman", "girl", "boy", "face", "hair", "body",
    "wearing", "dress", "shirt", "pose", "posing", "dancing", "smiling",
)


VALUE_WORDS = {
    "light": "bright high-key lighting",
    "mid": "even balanced lighting",
    "dark": "low-key shadowed lighting",
}

SATURATION_WORDS = {
    "muted": "desaturated restrained colour",
    "moderate": "natural colour balance",
    "saturated": "rich saturated colour",
}

CLOSING = "photographic look"

PALETTE_WIDTH = 3


def _words(text: str) -> int:
    """Слов в промте. Считается ОДНИМ способом на весь модуль."""
    return len(re.findall(r"[A-Za-z][A-Za-z'-]*", text))


def _clauses(text: str) -> int:
    """Клауз в промте: куски, разделённые запятыми. Пустые не считаются."""
    return len([c for c in text.split(",") if c.strip()])


def subject_leak(text: str) -> list:
    """Какие запретные слова оказались в промте. Пустой список — чисто."""
    low = text.lower()
    return [w for w in SUBJECT_WORDS
            if re.search(r"\b" + re.escape(w) + r"\b", low)]


def compose(card: dict) -> dict:
    """Карточка стиля -> промт. Три исхода, а не два."""
    empty = {"outcome": UNMEASURED, "prompt": None, "words": 0, "clauses": 0,
             "leak": [], "card": card}
    if not isinstance(card, dict):
        return {**empty, "note": "карточка не словарь: стиль НЕ ПРОЧИТАН"}

    colours = card.get("colours") or []
    value = card.get("value_key")
    sat = card.get("saturation")
    tex = card.get("texture")

    missing = [name for name, v in (("colours", colours), ("value_key", value),
                                    ("saturation", sat), ("texture", tex))
               if not v]
    if missing:
        return {**empty, "note": ("в карточке нет полей " + ", ".join(missing) +
                                  ": стиль НЕ ПРОЧИТАН, это не «стиля нет»")}
    if value not in VALUE_WORDS:
        return {**empty, "note": (f"тональность {value!r} не из словаря "
                                  f"{sorted(VALUE_WORDS)}: НЕ ПРОЧИТАНА")}
    if sat not in SATURATION_WORDS:
        return {**empty, "note": (f"насыщенность {sat!r} не из словаря "
                                  f"{sorted(SATURATION_WORDS)}: НЕ ПРОЧИТАНА")}

    taken = list(colours)[:PALETTE_WIDTH]
    if len(taken) > 1:
        palette = "a palette of " + ", ".join(taken[:-1]) + " and " + taken[-1]
    else:
        palette = "a palette of " + taken[0]

    parts = [palette, VALUE_WORDS[value], SATURATION_WORDS[sat], tex, CLOSING]
    prompt = ", ".join(parts)

    w, c = _words(prompt), _clauses(prompt)
    leak = subject_leak(prompt)
    if leak:
        outcome = FAIL
        note = (f"промт задел запретную зону {leak}: стиль обязан описывать "
                f"вид, а не персонажа — персонаж приходит из фото и драйвинга")
    elif not (WORDS_MIN <= w <= WORDS_MAX):
        outcome = FAIL
        note = (f"слов {w}, полоса корпуса {WORDS_MIN}..{WORDS_MAX} "
                f"(медиана {WORDS_TARGET})")
    elif not (CLAUSES_MIN <= c <= CLAUSES_MAX):
        outcome = FAIL
        note = (f"клауз {c}, полоса корпуса {CLAUSES_MIN}..{CLAUSES_MAX} "
                f"(медиана {CLAUSES_TARGET})")
    else:
        outcome = PASS
        note = (f"слов {w} при медиане корпуса {WORDS_TARGET} "
                f"(полоса {WORDS_MIN}..{WORDS_MAX}), клауз {c} при медиане "
                f"{CLAUSES_TARGET} и полосе {CLAUSES_MIN}..{CLAUSES_MAX}; "
                f"запретных слов 0")
    return {"outcome": outcome, "prompt": prompt, "words": w, "clauses": c,
            "leak": leak, "card": card, "note": note}


def from_image(path, *, reader=None) -> dict:
    """Картинка -> промт. `reader` — точка внедрения."""
    if reader is None:
        def reader(p):
            from creative_eval.style import style_card  # noqa: PLC0415
            return style_card(p)
    try:
        card = reader(str(path))
    except Exception as exc:                     # noqa: BLE001
        return {"outcome": UNMEASURED, "prompt": None, "words": 0,
                "clauses": 0, "leak": [], "card": None,
                "note": (f"карточку прочитать не удалось: "
                         f"{type(exc).__name__}: {exc}")}
    out = compose(card)
    out["source"] = str(path)
    return out


def differ(left: dict, right: dict) -> dict:
    """Дают ли две карточки РАЗНЫЕ промты. Негативный контроль адаптера."""
    a, b = compose(left), compose(right)
    if a["outcome"] == UNMEASURED or b["outcome"] == UNMEASURED:
        return {"outcome": UNMEASURED, "same": None,
                "note": "хотя бы одна карточка не прочиталась: сравнивать нечего"}
    same = a["prompt"] == b["prompt"]
    return {"outcome": FAIL if same else PASS, "same": same,
            "left": a["prompt"], "right": b["prompt"],
            "note": ("промты СОВПАЛИ на разных карточках: адаптер не различает"
                     if same else "промты разошлись, адаптер различает")}


def report_text(out: dict) -> str:
    """Человеческий отчёт: вердикт, числа, промт. Числа рядом с вердиктом."""
    head = f"[{out['outcome']:<18}] промт стиля"
    body = f"  {out['note']}"
    tail = f"  промт: {out['prompt']}" if out.get("prompt") else "  промта нет"
    return "\n".join([head, body, tail])
