"""A fully synthetic presenter reading true content for the broadcaster's OWN programme is planned (round 14).

WHY. A local TV or news station asking for an AI weather presenter — a made-up
person, nobody's likeness — to read its own meteorologists' forecast was
refused: the station named itself (`spec.claims[].real_brand: true`, because
the station IS a real brand), and the claims rule `news_brand` reads every real
news brand as an imitation. The station's own name on its own programme is not
an imitation; what such an order needs is disclosure that the presenter is AI,
not a refusal.

THE NARROW DOOR, ALL STRUCTURED (no word opens it):

* `spec.people[]`: at least one person, and EVERY person `real: false` (a
  synthetic presenter; a real person goes through the people policy and, for
  the customer's own staff, `studio/inhouse_news.py`); the people policy
  refused nobody;
* `spec.claims[]`: every news / real-event claim `fabricated: false`; every
  claim with `real_brand: true` also `own_brand: true` (the customer's own
  outlet) and its brand is not one of the broadcasters `broadcast_marks`
  names; no claim fabricated or parody;
* the only refusals are the claims rule `news_brand` on those own-brand claims
  — the text screen's own bans, any other policy ban, a known broadcaster in
  the brief, and the broadcast-marks rule (`studio/broadcast_marks.py`, run
  before this door) all stay.

Then the claim refusal is lifted for those claims, the decision is recorded as
`synthetic_presenter_own_programme`, and the plan carries the disclosure note
(`checklist.synthetic_presenter_disclosure`). Fabricated news, a real person
without consent and another broadcaster's marks remain refused by the rules
that refuse them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lipsync.fork_identity import PASS
from studio import broadcast_marks

#: Claim types that are news-shaped (a report of real events, a forecast).
NEWS_TYPES: frozenset[str] = frozenset({"news", "real_event"})
#: The one claims-policy rule this door lifts (a real news brand read as imitation).
LIFTED_RULE = "news_brand"
RULE_ID = "synthetic_presenter_own_programme"

DECISION_ALLOW = "allow"
DECISION_NONE = "none"


def _list(raw: Any) -> list[Mapping[str, Any]]:
    if isinstance(raw, Mapping):
        return [raw]
    if isinstance(raw, (list, tuple)):
        return [x for x in raw if isinstance(x, Mapping)]
    return []


def _key(value: Any) -> str:
    return " ".join(str(value or "").split()).lower()


def synthetic_people(people: Sequence[Mapping[str, Any]]) -> bool:
    """At least one person, and every one of them made up (`real: false`)."""
    return bool(people) and all(п.get("real") is False for п in people)


def own_programme(claims: Sequence[Mapping[str, Any]]) -> bool:
    """True content of the customer's own outlet — nothing invented, parodied or another channel's."""
    новости = [з for з in claims if str(з.get("type") or "").lower() in NEWS_TYPES]
    if not новости:
        return False
    for з in claims:
        if з.get("fabricated") is True or з.get("parody") is True:
            return False
        if з.get("real_brand") is True:
            if з.get("own_brand") is not True:
                return False
            if broadcast_marks.BROADCASTER.search(str(з.get("brand") or з.get("name") or "")):
                return False
    if any(з.get("fabricated") is not False for з in новости):
        return False
    return any(з.get("own_brand") is True for з in новости)


def decide(
    spec: Mapping[str, Any] | None,
    policy: Mapping[str, Any],
    screened: Mapping[str, Any],
    text_screen: Mapping[str, Any],
    brief: str = "",
) -> dict[str, Any]:
    """Whether the own-brand news refusal is lifted: {decision, claims, why}."""
    нет = {"decision": DECISION_NONE, "claims": [], "why": ""}
    if not isinstance(spec, Mapping) or policy.get("decision") != "refuse":
        return нет
    if text_screen.get("banned") or text_screen.get("injection"):
        return нет
    if broadcast_marks.BROADCASTER.search(str(brief or "")):
        return нет
    if not synthetic_people(_list(spec.get("people"))):
        return нет
    if any(str(п.get("verdict")) != "proceed" for п in _list(policy.get("people"))):
        return нет
    заявления = _list(spec.get("claims"))
    if not own_programme(заявления):
        return нет
    свои = {
        _key(з.get("brand") or з.get("name")): з
        for з in заявления
        if з.get("real_brand") is True and з.get("own_brand") is True
    }
    отказаны = [з for з in _list(policy.get("claims")) if str(з.get("verdict")) != "proceed"]
    if not отказаны:
        return нет
    for з in отказаны:
        if з.get("rule") != LIFTED_RULE or _key(з.get("name")) not in свои:
            return нет
    # Ничего, кроме этих отказов: число запретов просева равно числу заявлений.
    if len(list(screened.get("banned") or [])) != len(отказаны) or len(list(policy.get("banned") or [])) != len(отказаны):
        return нет
    имена = [str(з.get("name") or "") for з in отказаны]
    return {
        "decision": DECISION_ALLOW,
        "claims": имена,
        "why": (
            "a synthetic presenter (spec.people[].real=false) reading true content (fabricated=false) for the "
            "customer's own programme (own_brand=true): planned with AI disclosure"
        ),
    }


def apply(
    decision: Mapping[str, Any], screened: Mapping[str, Any], policy: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(screen result, policy) with the own-brand claim refusal lifted."""
    if decision.get("decision") != DECISION_ALLOW:
        return dict(screened), dict(policy)
    имена = set(decision.get("claims") or [])
    заявления = []
    for з in _list(policy.get("claims")):
        if str(з.get("name") or "") in имена:
            з = {к: в for к, в in з.items() if к != "label"}
            з.update({"verdict": "proceed", "rule": RULE_ID})
        заявления.append(dict(з))
    новая_политика = {**policy, "decision": "proceed", "claims": заявления, "banned": []}
    новый_просев = {**screened, "outcome": PASS, "banned": [], "violations": 0}
    return новый_просев, новая_политика


def note(decision: Mapping[str, Any], en: bool = True) -> str:
    if decision.get("decision") != DECISION_ALLOW:
        return ""
    чей = ", ".join(decision.get("claims") or [])
    if en:
        return (
            f"synthetic presenter for your own programme ({чей}): a made-up presenter reading your own true "
            "content — planned with AI disclosure (label the AI presenter on screen and in the description; only "
            "your own channel's marks; keep the editorial sign-off)"
        )
    return (
        f"синтетический ведущий для вашей собственной программы ({чей}): вымышленный ведущий читает ваш "
        "правдивый материал — план с раскрытием ИИ (пометка ИИ-ведущего в кадре и в описании; только знаки "
        "вашего канала; утверждение редакции сохраняется)"
    )
