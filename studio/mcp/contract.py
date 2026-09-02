"""Does this prompt break the lipsync contract? Three outcomes, no silent repair.

THE CONTRACT, in the engine's own words

A lipsync prompt describes the LOOK. It never describes the subject, because
the subject arrives from two places the prompt has no business touching: the
user's photo, and the driving clip. `lipsync/fork_style_prompt.py` enforces
this with `SUBJECT_WORDS`, and a prompt that names one is a `FAIL` there.

The numeric bands come from the same module and were derived from the corpus:
`WORDS_MIN..WORDS_MAX` and `CLAUSES_MIN..CLAUSES_MAX`. They are IMPORTED here,
never restated. A copy would drift, and a drifted copy would pass prompts the
engine rejects — which is exactly the failure this gate exists to prevent.

WHY A SEPARATE GATE AT ALL, WHEN `compose()` ALREADY GATES

`fork_style_prompt.compose()` gates the prompt IT builds, from a four-field
card over a fixed skeleton. It cannot judge a prompt that came from anywhere
else — from the corpus, from the owner's hand, from this package. This module
judges arbitrary text against the same rules, so a prompt from any source is
answerable to the contract before anyone spends money on it.

WHY IT NEVER REPAIRS

A gate that quietly trims a prompt into band reports `pass` for a prompt the
owner never wrote and cannot review. Repair is the caller's decision, made
with the violation in front of them. So the third outcome is real here: an
empty prompt is `could not measure`, not `fail` — nothing was checked, and
saying "nothing was checked" is not the same as saying "nothing was wrong".
"""

from __future__ import annotations

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from lipsync.fork_style_prompt import (
    CLAUSES_MAX,
    CLAUSES_MIN,
    CLAUSES_TARGET,
    WORDS_MAX,
    WORDS_MIN,
    WORDS_TARGET,
    _clauses,
    _words,
    subject_leak,
)

__all__ = ["gate", "BANDS", "ЛАТИНИЦЫ_НЕ_МЕНЬШЕ"]

# The bands, re-exported for callers that want to show them to a human. This is
# a view onto the engine's constants, not a second copy: change them there and
# this changes with them.
BANDS = {
    "words": (WORDS_MIN, WORDS_MAX, WORDS_TARGET),
    "clauses": (CLAUSES_MIN, CLAUSES_MAX, CLAUSES_TARGET),
}


#: Доля латинских букв, ниже которой прибор объявляет, что судить не может.
#:
#: ЗАЧЕМ. ИЗМЕРЕНО 2026-09-02 чтением собственной выдачи (П3): на промпте
#: «женщина говорит в камеру, тёплый янтарный свет, матовая кожа…» прибор
#: отвечал `fail` со словами «words 0, corpus band 9..67» И `leak: []`. Оба
#: числа — неправда о промпте, а не о нём самом:
#:
#:   * `_words` движка считает только латиницу (`[A-Za-z][A-Za-z'-]*`), поэтому
#:     у любого кириллического промпта слов НОЛЬ, и полоса ломается всегда;
#:   * `subject_leak` сверяется с английским списком, поэтому «женщина» он не
#:     видит — а это и есть та самая запретная зона, ради которой прибор
#:     написан. Опаснее всего сочетание: почини кто-нибудь только счётчик слов,
#:     и промпт, называющий субъекта, получил бы `pass`.
#:
#: Поэтому третий исход (Р1): не «сломано», а «не смогли проверить», и сказано,
#: чем именно. Молчаливое `leak: []` на непроверенном языке — это ровно то
#: «уверенно и неверно», против чего написан весь пакет.
#:
#: ВЫБРАНО 0.5: промпт движка — английский, и латиницы в нём почти 100%;
#: кириллический промпт с парой английских слов («matte кожа») даёт заведомо
#: меньше половины. Полоса широкая нарочно: у неё одна работа — отличить
#: «текст на языке, который прибор знает» от «текст на другом языке».
ЛАТИНИЦЫ_НЕ_МЕНЬШЕ = 0.5


def _латиницы(text: str) -> float:
    """Доля латинских букв среди ВСЕХ букв. Букв нет — считаем, что латиница.

    Текст без единой буквы («720p, 24 fps») прибор судить умеет: полосы у него
    про слова и фразы, и ноль слов там — честный ноль, а не непонятый язык.
    """
    буквы = [c for c in text if c.isalpha()]
    if not буквы:
        return 1.0
    латинских = sum(1 for c in буквы if "a" <= c.lower() <= "z")
    return латинских / len(буквы)


def gate(prompt: str) -> dict:
    """Judge one prompt against the lipsync contract.

    Three checks run on every non-empty prompt, and the count is reported so a
    reader can tell "three checks, no violations" from "no checks at all":

    1. the forbidden subject zone,
    2. the word band,
    3. the clause band.

    :returns: the house judging dict, plus `prompt`, `words`, `clauses`,
        `leak` (the forbidden words found) and `broke` (which checks failed).

    >>> gate("a palette of ivory and slate, even balanced lighting, matte")["outcome"]
    'pass'
    >>> gate("a woman in a red dress")["leak"]
    ['woman', 'dress']
    >>> gate("   ")["outcome"]
    'could not measure'
    """
    text = str(prompt or "").strip()
    if not text:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": (
                "there is no prompt to judge, so nothing was checked. An "
                "unchecked prompt is not a clean one."
            ),
            "prompt": "",
            "words": 0,
            "clauses": 0,
            "leak": [],
            "broke": [],
        }

    if _латиницы(text) < ЛАТИНИЦЫ_НЕ_МЕНЬШЕ:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 3,
            "note": (
                "этот промпт написан не латиницей, а прибор судит по движку: "
                "слова он считает по [A-Za-z], запретную зону сверяет с "
                "английским списком. Значит ни полоса слов, ни запретная зона "
                "здесь НЕ ПРОВЕРЕНЫ — и `leak: []` тут означает «не смотрели», "
                "а не «чисто». Промпт для модели пишется по-английски: "
                "`write_lipsync_prompt` соберёт его из ваших слов."
            ),
            "prompt": text,
            "words": 0,
            "clauses": _clauses(text),
            "leak": [],
            "broke": [],
        }

    words = _words(text)
    clauses = _clauses(text)
    leak = subject_leak(text)

    broke: list[str] = []
    reasons: list[str] = []
    if leak:
        broke.append("subject_zone")
        reasons.append(
            f"names the subject ({', '.join(leak)}): the look is the prompt's "
            "job, the subject comes from the photo and the driving clip"
        )
    if not WORDS_MIN <= words <= WORDS_MAX:
        broke.append("words")
        reasons.append(f"words {words}, corpus band {WORDS_MIN}..{WORDS_MAX}")
    if not CLAUSES_MIN <= clauses <= CLAUSES_MAX:
        broke.append("clauses")
        reasons.append(f"clauses {clauses}, corpus band {CLAUSES_MIN}..{CLAUSES_MAX}")

    if broke:
        return {
            "outcome": FAIL,
            "checked": 3,
            "violations": len(broke),
            "unmeasured": 0,
            "note": "; ".join(reasons),
            "prompt": text,
            "words": words,
            "clauses": clauses,
            "leak": leak,
            "broke": broke,
        }

    return {
        "outcome": PASS,
        "checked": 3,
        "violations": 0,
        "unmeasured": 0,
        "note": (
            f"words {words} (band {WORDS_MIN}..{WORDS_MAX}, median {WORDS_TARGET}), "
            f"clauses {clauses} (band {CLAUSES_MIN}..{CLAUSES_MAX}, median "
            f"{CLAUSES_TARGET}), forbidden words 0"
        ),
        "prompt": text,
        "words": words,
        "clauses": clauses,
        "leak": [],
        "broke": [],
    }
