"""A consented INTERNAL deepfake for security-awareness training is PLANNED, not refused (round 17).

WHY. A company that trains its staff to spot deepfake fraud ("the CEO calls finance and asks for a
wire") needs exactly that clip: its own executive's face and voice, made with the executive's written
consent, shown only inside the company. The people policy refuses a real PUBLIC FIGURE made to deliver
a news statement whatever consent is claimed — and a listed company's CEO is a public figure, and the
drill's script is an announcement. That order is the ordinary consented-likeness case with an internal
audience: what it needs is the consent on record, a visible watermark and disclosure, and an
internal-only distribution — not a refusal.

THE NARROW DOOR, ALL STRUCTURED (no word decides it; the brief's words never open it):

* `spec.domain` names `security-awareness` and `spec.delivery.platform` names ONLY `internal`;
* every person the policy refused is real, with consent "stated", `role` employee or self (the
  customer's own staff or the customer), person-level claim "news", and was refused by the
  public-statement rule only;
* `spec.claims[]` names no political claim (and the brief has no political words, `W_KEEP_REFUSED` —
  words only close the door) and no `real_brand: true` (another organisation's brand);
* the SAME order screened again with those people's claim read as "other" passes every screen — so
  nothing else (no other ban of the topic screen, no other person, no political or endorsement claim)
  was refused.

Then the people refusal is lifted for those people, recorded as `consented_simulation`, and the plan
carries the safeguards (`checklist.consented_simulation_safeguards`: watermark, disclosure, internal-only
distribution, the consent record). A missing consent, an external audience, an endorsement (a celebrity
advert) or a political statement stay refused by the rules that refuse them — this module never reads
or changes the screens themselves (`studio/mcp/screen.py`, `studio/mcp/spec_screen.py`).
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from lipsync.fork_identity import PASS

#: `spec.people[].role` values of the customer's own people (`brief_spec.PERSON_ROLES`).
IN_HOUSE_ROLES: frozenset[str] = frozenset({"employee", "self"})
#: The one policy rule this door lifts (public figure + news statement).
LIFTED_RULE = "public_statement"
#: The person-level claim the drill's script is (an announcement / a request read as news).
LIFTED_CLAIM = "news"
RULE_ID = "consented_simulation"
#: `spec.domain` and `spec.delivery.platform` values that open the door (`brief_spec`).
DOMAIN = "security-awareness"
PLATFORM = "internal"
#: Claim types (`spec.claims[].type`) that keep the refusal.
KEEP_REFUSED_CLAIMS: frozenset[str] = frozenset({"political", "election", "endorsement"})

#: Words that keep the refusal (EN/RU): politics, elections, a candidate — read only to close the door.
W_KEEP_REFUSED = re.compile(
    r"politic|election|candidate|ballot|referendum|vote for|campaign ad|политич|выбор(?:ы|ах|ов)\b|предвыбор"
    r"|кандидат|голосуй|референдум|агитац",
    re.I,
)

DECISION_ALLOW = "allow"
DECISION_NONE = "none"


def _list(raw: Any) -> list[Mapping[str, Any]]:
    if isinstance(raw, Mapping):
        return [raw]
    if isinstance(raw, (list, tuple)):
        return [x for x in raw if isinstance(x, Mapping)]
    return []


def _strings(raw: Any) -> set[str]:
    if isinstance(raw, str):
        return {raw.strip().lower()}
    if isinstance(raw, (list, tuple)):
        return {str(x).strip().lower() for x in raw}
    return set()


def internal_training(spec: Mapping[str, Any]) -> bool:
    """`domain` names security-awareness and `delivery.platform` names ONLY internal."""
    сдача = spec.get("delivery") if isinstance(spec.get("delivery"), Mapping) else {}
    площадки = _strings(сдача.get("platform"))
    return DOMAIN in _strings(spec.get("domain")) and площадки == {PLATFORM}


def in_house(person: Mapping[str, Any]) -> bool:
    return (
        person.get("real") is True
        and str(person.get("consent") or "").lower() == "stated"
        and str(person.get("role") or "").lower() in IN_HOUSE_ROLES
        and str(person.get("claim") or "").lower() == LIFTED_CLAIM
    )


def as_drill(spec: Mapping[str, Any], names: Sequence[str]) -> dict[str, Any]:
    """The same spec with the named people's claim read as "other" (the re-screen)."""
    имена = {str(н).strip().lower() for н in names}
    люди = []
    for п in _list(spec.get("people")):
        if str(п.get("name") or "").strip().lower() in имена:
            п = {**п, "claim": "other"}
        люди.append(dict(п))
    return {**spec, "people": люди}


def decide(
    spec: Mapping[str, Any] | None,
    policy: Mapping[str, Any],
    screened: Mapping[str, Any],
    rescreen: Callable[[Mapping[str, Any]], tuple[Mapping[str, Any], Mapping[str, Any]]],
    brief: str = "",
) -> dict[str, Any]:
    """Whether the people refusal is lifted: {decision, people, why, screened, policy}.

    :param rescreen: screens a spec exactly as the server does (topic screen + people policy +
        `spec_screen`) and returns (screen result, policy) — the door never reimplements a screen.
    """
    нет: dict[str, Any] = {"decision": DECISION_NONE, "people": [], "why": ""}
    if not isinstance(spec, Mapping) or policy.get("decision") != "refuse" or screened.get("outcome") == PASS:
        return нет
    if screened.get("injection") or not internal_training(spec):
        return нет
    # Words only CLOSE the door (never open it): a political statement in any form stays refused.
    if W_KEEP_REFUSED.search(str(brief or "")):
        return нет
    for з in _list(spec.get("claims")):
        if str(з.get("type") or "").lower() in KEEP_REFUSED_CLAIMS or з.get("real_brand") is True:
            return нет
    по_имени = {str(п.get("name") or "").strip().lower(): п for п in _list(spec.get("people"))}
    отказаны = [п for п in _list(policy.get("people")) if str(п.get("verdict")) == "refuse"]
    if not отказаны:
        return нет
    for п in отказаны:
        свой = по_имени.get(str(п.get("name") or "").strip().lower())
        if п.get("rule") != LIFTED_RULE or свой is None or not in_house(свой):
            return нет
    имена = [str(п.get("name") or "") for п in отказаны]
    новый_просев, новая_политика = rescreen(as_drill(spec, имена))
    if новый_просев.get("outcome") != PASS or новая_политика.get("decision") == "refuse":
        return нет
    return {
        "decision": DECISION_ALLOW,
        "people": имена,
        "why": (
            "the customer's own staff (spec.people[].role), consent stated, in a security-awareness drill shown "
            "internally only (spec.domain security-awareness, spec.delivery.platform internal): planned with "
            "a watermark, disclosure and the consent record"
        ),
        "screened": dict(новый_просев),
        "policy": dict(новая_политика),
    }


def apply(
    decision: Mapping[str, Any], screened: Mapping[str, Any], policy: Mapping[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    """(screen result, policy) with the people refusal lifted for the consented in-house people."""
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
        "consented_simulation": sorted(имена),
    }
    новый_просев = {**dict(decision.get("screened") or screened), "outcome": PASS, "banned": [], "violations": 0}
    return новый_просев, новая_политика


def note(decision: Mapping[str, Any], en: bool = True) -> str:
    if decision.get("decision") != DECISION_ALLOW:
        return ""
    кто = ", ".join(decision.get("people") or [])
    if en:
        return (
            f"consented internal simulation ({кто}): your own staff with consent stated, a security-awareness "
            "drill shown internally only — planned with safeguards: a visible 'SIMULATION — AI-generated' "
            "watermark and C2PA credentials, a debrief to every participant, internal-only access with a "
            "deletion date for the clips and the voice clone, and the signed consent kept with the project"
        )
    return (
        f"согласованная внутренняя симуляция ({кто}): ваш сотрудник с заявленным согласием, учения по "
        "безопасности только внутри компании — план с мерами: видимый водяной знак «СИМУЛЯЦИЯ — создано ИИ» и "
        "C2PA, разбор с каждым участником, доступ только внутри и дата удаления роликов и клона голоса, "
        "подписанное согласие хранится с проектом"
    )
