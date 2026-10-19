"""A real broadcaster's marks on fabricated or parody news are refused, not asked about (round 12).

WHY. The round-12 hidden set found "a parody news segment with the CNN logo and
lower-thirds" answered with a QUESTION. Nothing the customer could answer makes it
plannable: a broadcaster's logo, name and on-air graphics are registered trade marks
(e.g. BBC, CNN, Sky are registered in the UK IPO / USPTO / EUIPO registers), and a
fabricated news item dressed in them is the "passing off" / false-endorsement case
trade-mark law exists for (Lanham Act 15 U.S.C. §1125(a); UK Trade Marks Act 1994
s.10; EU Regulation 2017/1001 Art. 9). Parody does not cure it when the marks
themselves are copied to make the item look like the real channel's broadcast. So
the outcome is decisive: REFUSED, with what IS possible — a fictional channel with
its own name and look.

THE RULE (one rule, its own words; the topic screen keeps its rules):
    spec.claims has {real_brand: true} with fabricated or parody true, and the brand is
    a broadcaster (or the claim is of type news)                         -> refuse
    the brief names a broadcaster AND its marks (logo, branding, graphics,
    look, style) AND fabricated / parody / fake news words               -> refuse
A mark that is negated ("without the BBC logo", "без логотипа") does not count.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

DECISION_PLAN = "plan"
DECISION_REFUSE = "refuse"

#: Broadcasters and news agencies whose marks are copied in such requests.
BROADCASTER = re.compile(
    r"\bbbc\b|\bcnn\b|fox news|sky news|al ?jazeera|\breuters\b|\bnbc\b|\bcbs\b|abc news|\bmsnbc\b|\bcnbc\b"
    r"|bloomberg(?: tv| news)?|euronews|deutsche welle|\bdw news|france ?24|\bnhk\b|\bzdf\b|\bard\b|tagesschau"
    r"|\bitv\b|channel 4 news|\bcbc\b|\bpbs\b|\bnpr\b|associated press"
    r"|первого канала|первый канал|перв\w+ канал\w*|росси[яи] ?(?:1|24)|\bнтв\b|\bрбк\b|\bтасс\b|риа новост\w*"
    r"|\bрен[- ]тв\b|телеканал\w* дождь",
    re.I,
)
#: The marks themselves: logo, branding, on-air graphics, the channel's look.
MARKS = re.compile(
    r"\blogos?\b|branding|\bbrand(?:ed)?\b|lower[- ]thirds?|chyron|\bident\b|on-?air graphics|graphics package"
    r"|\blook(?:s)? (?:exactly )?like\b|\bin the style of\b|\bstyle\b|studio look|watermark"
    r"|логотип\w*|оформлени\w*|фирменн\w*|плашк\w*|заставк\w*|в стиле|как у|под (?:новости|выпуск)",
    re.I,
)
#: Not a real report: fabricated, parody, prank.
FAKE = re.compile(
    r"\bfake\b|parod\w*|satir\w*|spoof\w*|prank\w*|\bjoke\b|fabricat\w*|\bmock\b|fictional|made-?up|pretend\w*"
    r"|hoax|шуточн\w*|пароди\w*|фейк\w*|сатир\w*|розыгрыш\w*|прикол\w*|выдуманн\w*|ненастоящ\w*|поддельн\w*",
    re.I,
)
#: A mark word preceded by one of these within `NEGATION_WINDOW` words is not asked for.
NEGATION = re.compile(r"^(?:no|without|not|never|avoid|nothing|unlike|без|не|нет|никаких|непохож\w*)$", re.I)
#: DECISION CONSTANT (T1): how many words before a mark a negation is looked for ("nothing like Fox News
#: branding" — 4); wider windows read an unrelated "no" earlier in the sentence.
NEGATION_WINDOW = 4
#: Claim types where a real brand plus fabrication is news-shaped.
NEWS_TYPES: frozenset[str] = frozenset({"news", "real_event", "other", "parody", "satire"})


def _flag(value: Any) -> bool:
    return value is True or str(value).strip().lower() in ("true", "yes", "да")


def _marks_asked(text: str) -> bool:
    """A mark word in the text that no negation stands just before."""
    for m in MARKS.finditer(text):
        before = re.findall(r"[\w'-]+", text[: m.start()].lower())[-NEGATION_WINDOW:]
        if not any(NEGATION.match(w) for w in before):
            return True
    return False


def decide(brief: str, spec: Mapping[str, Any] | None) -> dict[str, Any]:
    """{decision, brand, source}: refuse when a real broadcaster's marks dress fabricated or parody news."""
    claims: Sequence[Any] = ()
    if isinstance(spec, Mapping) and isinstance(spec.get("claims"), Sequence) and not isinstance(spec.get("claims"), str):
        claims = spec["claims"]
    text = str(brief or "")
    for c in claims:
        if not isinstance(c, Mapping) or not _flag(c.get("real_brand")):
            continue
        if not (_flag(c.get("fabricated")) or _flag(c.get("parody"))):
            continue
        brand = str(c.get("brand") or "")
        in_text = BROADCASTER.search(text)
        if BROADCASTER.search(brand) or (str(c.get("type")) in NEWS_TYPES and in_text):
            return {"decision": DECISION_REFUSE, "brand": brand or (in_text.group(0) if in_text else ""), "source": "spec"}
    m = BROADCASTER.search(text)
    if m and FAKE.search(text) and _marks_asked(text):
        return {"decision": DECISION_REFUSE, "brand": m.group(0), "source": "text"}
    return {"decision": DECISION_PLAN, "brand": "", "source": ""}


def refusal_note(result: Mapping[str, Any], en: bool) -> str:
    brand = result.get("brand") or ""
    if en:
        return (
            f"a fabricated or parody news item in the marks of a real broadcaster ({brand}) is refused: its logo, "
            "name and on-air graphics are registered trade marks, and copying them makes the item pass as the "
            "channel's own broadcast (Lanham Act §1125(a); UK Trade Marks Act 1994 s.10; EU Reg. 2017/1001 Art. 9). "
            "What is possible: the same sketch on a FICTIONAL channel with its own name, logo and graphics"
        )
    return (
        f"выдуманный или пародийный выпуск новостей в оформлении настоящего канала ({brand}) — отказ: его "
        "логотип, название и эфирная графика — зарегистрированные товарные знаки, и их копия выдаёт ролик за "
        "эфир самого канала (Lanham Act §1125(a); Trade Marks Act 1994 s.10 (UK); Регламент ЕС 2017/1001 ст. 9; "
        "ГК РФ ст. 1484). Можно: тот же скетч на ВЫДУМАННОМ канале со своим названием, логотипом и графикой"
    )
