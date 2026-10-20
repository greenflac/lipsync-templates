"""Your own presenter reading your own newsroom's true news is PLANNED, not refused (round 13).

WHY. The people policy refuses a real PUBLIC FIGURE made to say news, whatever
consent is claimed: the studio cannot verify consent, and a realistic statement
a public figure never made is disinformation. A station's own anchor is a
public figure too — and the station asking for an AI version of ITS employee
reading ITS newsroom's true bulletin was refused by that rule. That order is
the ordinary synthetic-presenter case (regional TV, radio, news sites): what
it needs is consent on record and disclosure, not a refusal.

THE NARROW DOOR, ALL STRUCTURED (no word decides it):

* `spec.people[]`: real, consent "stated", claim "news", and `role` in
  `IN_HOUSE_ROLES` ("employee" — on the customer's staff, "self" — the
  customer); EVERY person the policy refused is such a person and was refused
  by the public-statement rule only;
* `spec.claims[]`: a news / real-event claim with `own_brand: true` (the
  customer's own outlet) and `fabricated: false` — and NO claim with
  `real_brand: true` (imitating another broadcaster) or `fabricated` not false;
* nothing else was refused: the text screen's own bans (a news brand +
  "fake", a public figure + political words) and every other policy ban stay.

Then the people refusal is lifted for those people, the decision is recorded as
`in_house_news_consented`, and the plan carries the disclosure notes
(`checklist.in_house_anchor_disclosure`). Fabricated news and imitation of
another broadcaster remain refused by the rules that refuse them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from lipsync.fork_identity import PASS

#: `spec.people[].role` values that make a real person the customer's own (`brief_spec.PERSON_ROLES`).
IN_HOUSE_ROLES: frozenset[str] = frozenset({"employee", "self"})
#: Claim types this door opens for.
NEWS_TYPES: frozenset[str] = frozenset({"news", "real_event"})
#: The one policy rule this door lifts (public figure + news statement).
LIFTED_RULE = "public_statement"
RULE_ID = "in_house_news_consented"

DECISION_ALLOW = "allow"
DECISION_NONE = "none"


def _list(raw: Any) -> list[Mapping[str, Any]]:
    if isinstance(raw, Mapping):
        return [raw]
    if isinstance(raw, (list, tuple)):
        return [x for x in raw if isinstance(x, Mapping)]
    return []


def own_newsroom(claims: Sequence[Mapping[str, Any]]) -> bool:
    """A true report of the customer's own outlet — and nothing imitated or invented."""
    новости = [з for з in claims if str(з.get("type") or "").lower() in NEWS_TYPES]
    if not новости:
        return False
    if any(з.get("real_brand") is True for з in claims):
        return False
    if any(з.get("fabricated") is not False for з in новости):
        return False
    return any(з.get("own_brand") is True for з in новости)


def in_house(person: Mapping[str, Any]) -> bool:
    return (
        person.get("real") is True
        and str(person.get("consent") or "").lower() == "stated"
        and str(person.get("claim") or "").lower() == "news"
        and str(person.get("role") or "").lower() in IN_HOUSE_ROLES
    )


def decide(
    spec: Mapping[str, Any] | None,
    policy: Mapping[str, Any],
    screened: Mapping[str, Any],
    text_screen: Mapping[str, Any],
) -> dict[str, Any]:
    """Whether the people refusal is lifted: {decision, people, why}."""
    нет = {"decision": DECISION_NONE, "people": [], "why": ""}
    if not isinstance(spec, Mapping) or policy.get("decision") != "refuse":
        return нет
    if text_screen.get("banned") or text_screen.get("injection"):
        return нет
    if not own_newsroom(_list(spec.get("claims"))):
        return нет
    if any(str(з.get("verdict")) != "proceed" for з in _list(policy.get("claims"))):
        return нет
    по_имени = {str(п.get("name") or "").strip().lower(): п for п in _list(spec.get("people"))}
    отказаны = [п for п in _list(policy.get("people")) if str(п.get("verdict")) == "refuse"]
    if not отказаны:
        return нет
    for п in отказаны:
        свой = по_имени.get(str(п.get("name") or "").strip().lower())
        if п.get("rule") != LIFTED_RULE or свой is None or not in_house(свой):
            return нет
    # Ничего, кроме этих отказов: число запретов просева равно числу людей.
    if len(list(screened.get("banned") or [])) != len(отказаны) or len(list(policy.get("banned") or [])) != len(отказаны):
        return нет
    имена = [str(п.get("name") or "") for п in отказаны]
    return {
        "decision": DECISION_ALLOW,
        "people": имена,
        "why": (
            "the customer's own staff (spec.people[].role), consent stated, reading the customer's own "
            "true news (spec.claims own_brand=true, fabricated=false): planned with disclosure"
        ),
    }


def apply(
    decision: Mapping[str, Any], screened: Mapping[str, Any], policy: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(screen result, policy) with the people refusal lifted for the in-house people."""
    if decision.get("decision") != DECISION_ALLOW:
        return dict(screened), dict(policy)
    имена = set(decision.get("people") or [])
    люди = []
    for п in _list(policy.get("people")):
        if str(п.get("name") or "") in имена:
            п = {к: з for к, з in п.items() if к != "label"}
            п.update({"verdict": "proceed", "rule": RULE_ID})
        люди.append(dict(п))
    новая_политика = {
        **policy,
        "decision": "proceed",
        "people": люди,
        "banned": [],
        "consent_recorded": sorted(set(policy.get("consent_recorded") or []) | имена),
        "in_house_news": sorted(имена),
    }
    новый_просев = {
        **screened,
        "outcome": PASS,
        "banned": [],
        "violations": 0,
    }
    return новый_просев, новая_политика


def note(decision: Mapping[str, Any], en: bool = True) -> str:
    if decision.get("decision") != DECISION_ALLOW:
        return ""
    кто = ", ".join(decision.get("people") or [])
    if en:
        return (
            f"in-house presenter ({кто}): your own staff with consent stated, reading your own newsroom's true "
            "news — planned with disclosure (label the AI presenter on screen; keep the written consent and the "
            "editorial sign-off)"
        )
    return (
        f"свой ведущий ({кто}): ваш сотрудник с заявленным согласием читает правдивые новости вашей редакции — "
        "план с раскрытием (помечайте ИИ-ведущего в кадре; храните письменное согласие и утверждение редакции)"
    )
