"""Text-screen hits that the caller's STRUCTURED spec decides (round 11).

WHY THIS EXISTS

`screen.просеять` reads WORDS. Two of its topic groups fire on words that
name a subject rather than an act, and on a fresh hidden set they refused
orders an expert plans:

* the minors group fires on a child WORD — also when the child is the
  audience ("a bedtime story for my kids", "an animated series for
  children: a schoolgirl and her robot"), a cartoon character, or a pupil in
  the customer's own training video;
* the likeness group fires on likeness WORDS ("starring", a face-swap word)
  — also when every real person in the clip gave consent the customer
  stated, and when the person is a deceased relative for private family use
  (the people policy plans that with a note on post-mortem rights);

The tool contract already says "YOU ARE THE PARSER … YOU KNOW WHO IS REAL": the
caller fills `spec.people` (real, minor, consent, deceased); `spec.audience`
(who WATCHES) is echoed and keeps "made for children" apart from "a child on
screen". When `spec.people` was filled, these two text hits are DECIDED BY THE SPEC
instead of refusing on a word. Every other screen result (intimate refusals,
injection, news brands, the three text pairs, public-figure endorsement, the
other topic groups) is untouched: this module only removes labels of the two groups below, and only
under the conditions written next to each.

The group labels are taken from `screen` by position and constant name, never
copied here (the screen's word lists are not repeated in this file).
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from studio.mcp import screen

#: The minors topic group (the audience rule's own group).
GROUP_MINORS: str = screen.АУДИТОРИЯ_ГРУППА
#: The likeness group (impersonation / face-swap words).
GROUP_LIKENESS: str = screen.РУССКИЕ_ГРУППЫ[3][0]

#: Why a hit was decided by the spec — (en, ru), printed in the answer's note.
WHY: dict[str, tuple[str, str]] = {
    GROUP_MINORS: (
        "a child word in the brief was decided by spec.people: no real minor is listed on screen "
        "(an audience of children or a fictional character is not a child in the clip)",
        "слово о детях в брифе решено по spec.people: реального несовершеннолетнего в кадре нет "
        "(дети-зрители или вымышленный персонаж — не ребёнок в кадре)",
    ),
    GROUP_LIKENESS: (
        "a likeness word in the brief was decided by spec.people: every real person in the clip has consent "
        "stated by the customer (or is a deceased relative, see the people policy)",
        "слово о подмене образа решено по spec.people: у каждого реального человека в кадре согласие названо "
        "заказчиком (или это умерший родственник — см. политику людей)",
    ),
}


def group_of(label: object) -> str:
    """The group a banned label belongs to: labels are "<group>: <word>"."""
    return str(label).partition(":")[0].strip()


def _people(spec: Mapping[str, Any] | None) -> list[Mapping[str, Any]] | None:
    if not isinstance(spec, Mapping) or not isinstance(spec.get("people"), list):
        return None
    return [п for п in spec["people"] if isinstance(п, Mapping)]


def real_minor(person: Mapping[str, Any]) -> bool:
    """A real person under 18 in the clip: `minor` says so; unsaid — the NAME is a child word."""
    if person.get("real") is False:
        return False
    if isinstance(person.get("minor"), bool):
        return bool(person["minor"])
    name = str(person.get("name") or "").strip()
    if not name:
        return False
    return any(group_of(м) == GROUP_MINORS for м in screen.просеять(name)["banned"])


def decide(
    просев: Mapping[str, Any],
    политика: Mapping[str, Any],
    spec: Mapping[str, Any] | None,
    text: str,
) -> tuple[dict[str, Any], list[str]]:
    """(screen result with the spec-decided labels removed, groups decided).

    Nothing changes unless `spec.people` was passed (an empty list counts:
    "no real people in the clip") and the people policy did not refuse.
    """
    out = dict(просев)
    people = _people(spec)
    if people is None or политика.get("decision") == "refuse" or not isinstance(spec, Mapping):
        return out, []
    banned = list(просев.get("banned") or [])
    if not banned:
        return out, []
    likeness = просев.get("likeness") or {}
    celebrities = bool(likeness.get("celebrities")) or bool(likeness.get("celebrity_endorsement"))
    minors = any(real_minor(п) for п in people)
    real = [п for п in people if п.get("real") is not False]
    consented = all(
        str(п.get("consent") or "").lower() == "stated" or п.get("deceased") is True for п in real
    )
    groups = {group_of(м) for м in banned}
    decided: list[str] = []
    if GROUP_MINORS in groups and not minors:
        decided.append(GROUP_MINORS)
    if GROUP_LIKENESS in groups and consented and not celebrities and not minors:
        decided.append(GROUP_LIKENESS)
    if not decided:
        return out, []
    kept = [м for м in banned if group_of(м) not in decided]
    removed = len(banned) - len(kept)
    out["banned"] = kept
    out["violations"] = max(0, int(просев.get("violations") or 0) - removed)
    if not kept and not просев.get("injection"):
        out["outcome"] = screen.PASS
    return out, decided


def note(decided: Sequence[str], english: bool) -> str:
    """One sentence per decided group, in the answer's language."""
    return "; ".join(WHY[g][0 if english else 1] for g in decided if g in WHY)
