"""Advertising claims policy: health and financial claims are not planned silently (round 10).

WHY. The round-10 holdout found adverts planned in full whose script made a claim no
studio can stand behind on the customer's word: a tea that "cures" a disease, a
supplement that "reverses" diabetes, a fund with "guaranteed" monthly returns. Such
claims are regulated almost everywhere: a disease claim for a food or supplement is
prohibited in the EU (Regulation (EC) No 1924/2006, Art. 10 and 12; Regulation (EU)
No 1169/2011, Art. 7(3)) and needs competent and reliable scientific evidence in the
US (FTC Health Products Compliance Guidance, 2022); an investment advert must be
fair, clear and not misleading and may not present returns as guaranteed without
basis (UK FCA COBS 4.2 / 4.5; US SEC Marketing Rule 206(4)-1). The planner cannot
verify substantiation, so the policy is a fixed rule over what the CALLER says,
with a conservative text fallback that ASKS rather than guesses.

THE CALLER FILLS `spec.claims` (the same list as news claims, other types):
    {type: "health_claim", substantiated: true | false | "unknown"}
        the advert says the product cures, treats, prevents or relieves a disease
        or a medical condition, or makes any health benefit claim;
    {type: "financial_claim", substantiated: true | false | "unknown"}
        the advert promises returns, profit, income or "no risk" for an investment,
        loan or financial product.
`substantiated: true` means the customer SAID the claim is backed (an authorised
health claim, a registered medicine, audited performance with the required risk
warning) — recorded as the customer's word, like consent.

POLICY (worst wins over all claims of the spec):
    substantiated false                     -> REFUSED (an unsubstantiated regulated
                                               claim in an advert is misleading
                                               advertising)
    substantiated unknown / not said        -> QUESTION (evidence and regulatory
                                               status, or drop / rephrase the claim)
    substantiated true                      -> planned, the claim recorded with a note
Without such a claim in `spec.claims`, the BRIEF is read conservatively: a cure /
treat / prevent verb near a disease word, or "guaranteed" / "risk-free" near
returns or profit, is a QUESTION asking the caller to fill `spec.claims` — never a
guessed refusal.

The module is separate from the topic screen on purpose: it owns one rule and its
words, and the screen keeps the rules it already has.
"""

from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

HEALTH = "health_claim"
FINANCIAL = "financial_claim"
#: The claim types this module decides; every other `spec.claims` type stays with the topic screen.
CLAIM_TYPES: tuple[str, ...] = (HEALTH, FINANCIAL)

DECISION_PLAN = "plan"
DECISION_QUESTION = "question"
DECISION_REFUSE = "refuse"
#: Worse decision wins (refuse > question > plan).
DECISION_RANK: dict[str, int] = {DECISION_PLAN: 0, DECISION_QUESTION: 1, DECISION_REFUSE: 2}

#: How many words may stand between a claim verb and its object ("cures your chronic
#: anxiety" — 2). DECISION CONSTANT (T1): wider windows read unrelated sentences together.
CLAIM_WINDOW = 4

SOURCES: tuple[str, ...] = (
    "https://eur-lex.europa.eu/eli/reg/2006/1924/oj",
    "https://eur-lex.europa.eu/eli/reg/2011/1169/oj",
    "https://www.ftc.gov/business-guidance/resources/health-products-compliance-guidance",
    "https://www.handbook.fca.org.uk/handbook/COBS/4/",
    "https://www.sec.gov/rules-regulations/2020/12/investment-adviser-marketing",
)

_W = r"(?:\S+\s+){0,%d}?" % CLAIM_WINDOW

_HEALTH_VERB = (
    r"(?:cures?|cured|curing|heals?|healing|treats?|treating|prevents?|preventing|reverses?|reversing"
    r"|eliminates?|fights?|beats?|gets? rid of|relieves?|relieving|lowers?|reduces?"
    r"|излечива\w*|вылечива\w*|вылечит\w*|лечит|исцеля\w*|избавля\w*|избавит\w*|предотвраща\w*"
    r"|снижа\w*|понижа\w*)"
)
_DISEASE = (
    r"(?:cancer|tumou?rs?|diabetes|anxiety|depression|blood pressure|hypertension|arthritis|covid\S*"
    r"|insomnia|obesity|diseases?|illness\w*|infections?|alzheimer\S*|dementia|asthma|psoriasis|eczema"
    r"|cholesterol|migraines?|flu|influenza|colds?|herpes|acne|adhd|autism|hair loss|baldness"
    r"|диабет\w*|рак(?:а|ом|у|е)?\b|опухол\w*|давлени\w*|гипертони\w*|тревог\w*|тревожност\w*|депресс\w*|артрит\w*"
    r"|бессонниц\w*|ожирени\w*|болезн\w*|заболевани\w*|инфекц\w*|холестерин\w*|мигрен\w*|простуд\w*"
    r"|грипп\w*|псориаз\w*|экзем\w*|облысени\w*|выпадени\w* волос)"
)
HEALTH_TEXT = re.compile(r"\b" + _HEALTH_VERB + r"\s+" + _W + _DISEASE + r"(?![\w])", re.I)

_GUARANTEE = (
    r"(?:guarantee[sd]?|guaranteeing|risk[- ]free|no risk|zero risk|without risk|sure[- ]fire|can'?t lose"
    r"|гарантирован\w*|гарантир\w*|без риска|безрисков\w*)"
)
_RETURNS = (
    r"(?:returns?|profits?|income|yields?|roi|earnings|interest|payouts?|dividends?"
    r"|\d+\s*%\s*(?:a|per|each|every|monthly|annual|yearly|годовых|в месяц|в год|ежемесячно)"
    r"|доход\w*|прибыл\w*|доходност\w*|заработ\w*|выплат\w*)"
)
FINANCIAL_TEXT = re.compile(
    r"\b(?:" + _GUARANTEE + r"\s+" + _W + _RETURNS + r"|" + _RETURNS + r"\s+" + _W + _GUARANTEE + r")",
    re.I,
)
#: "Double your money" and kin — a promised multiple is a returns guarantee in other words.
FINANCIAL_PROMISE = re.compile(r"\bdouble your (?:money|investment|deposit)\b|\bудво\w* (?:ваши |свои )?деньг", re.I)


def _flag(value: Any) -> bool | None:
    """substantiated: True / False / None (unknown)."""
    if isinstance(value, bool):
        return value
    v = str(value or "").strip().lower()
    if v in ("true", "yes", "да"):
        return True
    if v in ("false", "no", "нет"):
        return False
    return None


def split(spec: Mapping[str, Any] | None) -> tuple[Mapping[str, Any] | None, list[Mapping[str, Any]]]:
    """(spec without this module's claims — for the topic screen and the planner; this module's claims)."""
    if not isinstance(spec, Mapping):
        return spec, []
    claims = spec.get("claims")
    if not isinstance(claims, Sequence) or isinstance(claims, (str, bytes)):
        return spec, []
    own = [c for c in claims if isinstance(c, Mapping) and c.get("type") in CLAIM_TYPES]
    if not own:
        return spec, []
    rest = [c for c in claims if not (isinstance(c, Mapping) and c.get("type") in CLAIM_TYPES)]
    out = dict(spec)
    if rest:
        out["claims"] = rest
    else:
        out.pop("claims")
    return out, own


def text_claims(brief: str) -> list[str]:
    """Claim types the brief's own words make (the conservative fallback)."""
    found = []
    text = str(brief or "")
    if HEALTH_TEXT.search(text):
        found.append(HEALTH)
    if FINANCIAL_TEXT.search(text) or FINANCIAL_PROMISE.search(text):
        found.append(FINANCIAL)
    return found


def decide(own: Sequence[Mapping[str, Any]], brief: str) -> dict[str, Any]:
    """The decision: {decision, claims: [{type, substantiated, source}], source}."""
    rows: list[dict[str, Any]] = []
    for c in own:
        rows.append({"type": str(c.get("type")), "substantiated": _flag(c.get("substantiated")), "source": "spec"})
    said = {r["type"] for r in rows}
    for t in text_claims(brief):
        if t not in said:
            rows.append({"type": t, "substantiated": None, "source": "text"})
    decision = DECISION_PLAN
    for r in rows:
        d = (
            DECISION_REFUSE
            if r["substantiated"] is False
            else DECISION_QUESTION
            if r["substantiated"] is None
            else DECISION_PLAN
        )
        if DECISION_RANK[d] > DECISION_RANK[decision]:
            decision = d
    return {"decision": decision, "claims": rows, "sources": list(SOURCES) if rows else []}


_WHAT: dict[str, tuple[str, str]] = {
    HEALTH: ("заявление о здоровье (лечит, предотвращает, облегчает болезнь)", "a health claim (cures, treats, prevents or relieves a disease)"),
    FINANCIAL: ("финансовое обещание (гарантированный доход, «без риска»)", "a financial promise (guaranteed returns, 'no risk')"),
}


def _what(rows: Sequence[Mapping[str, Any]], en: bool) -> str:
    return ", ".join(dict.fromkeys(_WHAT[r["type"]][1 if en else 0] for r in rows))


def refusal_note(result: Mapping[str, Any], en: bool) -> str:
    bad = [r for r in result["claims"] if r["substantiated"] is False]
    if en:
        return (
            f"the advert makes {_what(bad, en)} that the customer says is NOT substantiated — an unsubstantiated "
            "regulated claim is misleading advertising (EU Reg. 1924/2006 Art. 10, FTC health products guidance; "
            "FCA COBS 4, SEC Marketing Rule). The plan is not built; drop or rephrase the claim and ask again"
        )
    return (
        f"в рекламе {_what(bad, en)}, и заказчик говорит, что оно НЕ подтверждено — неподтверждённое "
        "регулируемое заявление в рекламе вводит в заблуждение (Регламент ЕС 1924/2006 ст. 10, руководство FTC; "
        "FCA COBS 4, правило SEC о маркетинге). План не строится; уберите или переформулируйте заявление"
    )


def question(result: Mapping[str, Any], en: bool) -> dict[str, Any]:
    """The question row for an unknown substantiation: {axis, text, why, options}."""
    rows = [r for r in result["claims"] if r["substantiated"] is None]
    what = _what(rows, en)
    by_text = any(r["source"] == "text" for r in rows)
    if en:
        return {
            "axis": "claim_substantiation",
            "text": (
                f"The advert makes {what}. Is it substantiated — an authorised health claim or a registered "
                "medicine; audited figures with the required risk warning — or should it be removed or rephrased?"
            ),
            "why": (
                "regulated advertising claims need evidence the studio cannot check (EU Reg. 1924/2006, FTC "
                "guidance, FCA COBS 4, SEC Marketing Rule); the plan below is a draft until this is answered"
                + (
                    "; the claim was read from the brief's words — fill spec.claims "
                    "[{type: health_claim|financial_claim, substantiated: true|false}]"
                    if by_text
                    else ""
                )
            ),
            "options": ["substantiated (evidence / authorisation named)", "remove or rephrase the claim", "not substantiated"],
        }
    return {
        "axis": "claim_substantiation",
        "text": (
            f"В рекламе {what}. Оно подтверждено — разрешённое заявление о здоровье или зарегистрированное "
            "лекарство; аудированные цифры с обязательным предупреждением о риске — или его убрать либо "
            "переформулировать?"
        ),
        "why": (
            "регулируемым заявлениям в рекламе нужны доказательства, которые студия проверить не может "
            "(Регламент ЕС 1924/2006, руководство FTC, FCA COBS 4, правило SEC); план ниже — черновик до ответа"
            + (
                "; заявление прочитано из слов брифа — заполните spec.claims "
                "[{type: health_claim|financial_claim, substantiated: true|false}]"
                if by_text
                else ""
            )
        ),
        "options": ["подтверждено (названы доказательства или разрешение)", "убрать или переформулировать", "не подтверждено"],
    }


def recorded_note(result: Mapping[str, Any], en: bool) -> str:
    """Note for substantiated claims: recorded as the customer's word."""
    ok = [r for r in result["claims"] if r["substantiated"] is True]
    if not ok:
        return ""
    if en:
        return (
            f"{_what(ok, en)}: substantiation recorded as the customer's word — the script must use the "
            "authorised wording and carry the required disclaimers (risk warning, 'not a medicine')"
        )
    return (
        f"{_what(ok, en)}: подтверждение записано со слов заказчика — текст должен идти разрешённой формулировкой "
        "и с обязательными оговорками (предупреждение о риске, «не является лекарством»)"
    )


def report(result: Mapping[str, Any]) -> dict[str, Any]:
    """The `claims_policy` field of every plan answer."""
    return {
        "decision": result["decision"],
        "claims": [dict(r) for r in result["claims"]],
        "sources": list(result.get("sources") or []),
    }
