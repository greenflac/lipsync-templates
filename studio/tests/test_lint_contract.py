"""Judge `studio.template_lint.lint` against `studio/LINTER_CONTRACT.md`.

OWNER: agent B. Written from the contract alone, by an agent that has NOT read
`studio/template_lint.py` or its author's own tests (harness rule И1: the
verdict is not cast by whoever built the thing, and a check that has seen the
implementation measures the implementation instead of the requirement).

The instrument has both poles (И5):

* the planted half asks whether the linter can say YES — a linter that reports
  nothing passes any suite made only of clean templates;
* the clean half asks whether it can say NO — a linter that reports everything
  is exactly as useless, and `base_repeats_*` is the case that separates the
  two designs the contract's 12-repetitions measurement is about.

Both directions are asserted on every planted template: the expected finding
must be there, AND no VIOLATION the control set did not plant may be there.
One direction alone is passable by an instrument stuck at one reading.

Three outcomes, never two (Р1): `no_elements` must come back
`could not measure`, and `combinations == 0` may never be `pass`.
"""

from __future__ import annotations

import socket
import unittest

from studio.fixtures.lint_control_set import (
    CHECKS,
    CLEAN,
    CONTROL_SET,
    FAIL,
    PASS,
    PLANTED,
    RISK_CHECKS,
    UNMEASURED,
    VIOLATION_CHECKS,
    Case,
    combinations_of,
)

# The two severities as LITERALS (Т2). The contract says the linter imports
# them from `studio.selfrag.reflect`; importing them here too would let the
# expectation move with the code it grades, so their VALUES are written out.
SEVERITY_VIOLATION = "violation"
SEVERITY_RISK = "risk"

IMPORT_ERROR = ""
try:  # the module may not exist yet: that is a skip with the reason, not a stub
    from studio.template_lint import lint, lint_catalogue
except Exception as exc:  # pragma: no cover - depends on build order
    IMPORT_ERROR = f"{type(exc).__name__}: {exc}"

_REAL_SOCKET = socket.socket
_REAL_CONNECT = socket.create_connection


class NetworkTouched(AssertionError):
    """Raised when a test reaches for a socket. The linter is offline by contract."""


def setUpModule() -> None:
    """Close the network for the whole module. Enforcement, not agreement (Т4)."""

    def _blocked(*args: object, **kwargs: object) -> None:
        raise NetworkTouched("a test tried to open a socket; the linter must not call out")

    socket.socket = _blocked  # type: ignore[assignment, misc]
    socket.create_connection = _blocked  # type: ignore[assignment]


def tearDownModule() -> None:
    socket.socket = _REAL_SOCKET  # type: ignore[misc]
    socket.create_connection = _REAL_CONNECT


def _field(finding: object, name: str) -> object:
    """Read one field of a Finding.

    The contract shows a frozen dataclass; a mapping is accepted too. That
    tolerance is deliberate and narrow: the shape of the container is not what
    this control set measures, and refusing a dict would fail the linter for
    something the contract does not decide.
    """
    if isinstance(finding, dict):
        if name not in finding:
            raise AssertionError(f"finding {finding!r} has no {name!r}")
        return finding[name]
    if not hasattr(finding, name):
        raise AssertionError(f"finding {finding!r} has no attribute {name!r}")
    return getattr(finding, name)


def _findings(result: object) -> list[object]:
    """The `findings` list out of the judging dict, with the shape asserted once."""
    if not isinstance(result, dict):
        raise AssertionError(f"lint must return a dict, got {type(result).__name__}")
    for key in ("outcome", "findings", "combinations"):
        if key not in result:
            raise AssertionError(f"the judging dict is missing {key!r}: keys are {sorted(result)}")
    found = result["findings"]
    if not isinstance(found, (list, tuple)):
        raise AssertionError(f"findings must be a sequence, got {type(found).__name__}")
    return list(found)


def _triples(findings: list[object]) -> set[tuple[str, str, str]]:
    """(check, element, value) for each finding — what the control set blames."""
    return {
        (str(_field(f, "check")), str(_field(f, "element")), str(_field(f, "value")))
        for f in findings
    }


def _of_severity(findings: list[object], severity: str) -> list[object]:
    return [f for f in findings if str(_field(f, "severity")) == severity]


def _expected_triples(case: Case) -> set[tuple[str, str, str]]:
    """The planted triples, allowing the one blank the contract leaves open.

    `identity_only` is a property of an ELEMENT and no value provokes it, so a
    blank `value` there is honest reporting rather than a defect.
    """
    out: set[tuple[str, str, str]] = set()
    for exp in case.planted:
        out.add((exp.check, exp.element, exp.value))
        if exp.value_may_be_blank:
            out.add((exp.check, exp.element, ""))
    return out


def _severity_for(check: str) -> str:
    return SEVERITY_VIOLATION if check in VIOLATION_CHECKS else SEVERITY_RISK


def _describe(findings: list[object]) -> str:
    """Every finding as text, so a red test says what the linter actually said."""
    if not findings:
        return "(no findings)"
    return "\n".join(
        f"  {_field(f, 'severity')} {_field(f, 'check')} "
        f"element={_field(f, 'element')!r} value={_field(f, 'value')!r} "
        f"message={_field(f, 'message')!r}"
        for f in findings
    )


class LintContractTest(unittest.TestCase):
    """Every assertion here comes from the contract, none from the linter."""

    def setUp(self) -> None:
        if IMPORT_ERROR:
            self.skipTest(f"studio.template_lint is not importable yet: {IMPORT_ERROR}")

    # -- the planted half: can it say YES? ---------------------------------

    def test_planted_defect_is_reported(self) -> None:
        """Each planted defect must be blamed on the right check, element and value."""
        for case in PLANTED:
            with self.subTest(case=case.id, why=case.why):
                result = lint(case.template)
                findings = _findings(result)
                triples = _triples(findings)
                for exp in case.planted:
                    wanted = {(exp.check, exp.element, exp.value)}
                    if exp.value_may_be_blank:
                        wanted.add((exp.check, exp.element, ""))
                    self.assertTrue(
                        triples & wanted,
                        f"{case.template.id}: planted {exp.check} on element {exp.element!r} "
                        f"value {exp.value!r} was NOT reported. Linter said:\n"
                        f"{_describe(findings)}",
                    )

    def test_planted_finding_carries_the_right_severity(self) -> None:
        """repetition/article/seam are VIOLATION; the other three are RISK."""
        for case in PLANTED:
            with self.subTest(case=case.id):
                findings = _findings(lint(case.template))
                for exp in case.planted:
                    matched = [
                        f
                        for f in findings
                        if str(_field(f, "check")) == exp.check
                        and str(_field(f, "element")) == exp.element
                    ]
                    self.assertTrue(matched, f"{case.template.id}: no {exp.check} finding at all")
                    for f in matched:
                        self.assertEqual(
                            str(_field(f, "severity")),
                            _severity_for(exp.check),
                            f"{case.template.id}: {exp.check} has the wrong severity",
                        )

    def test_no_unexpected_violation_on_a_planted_template(self) -> None:
        """The other direction: nothing the control set did not plant may be a VIOLATION."""
        for case in PLANTED:
            with self.subTest(case=case.id):
                findings = _findings(lint(case.template))
                got = _triples(_of_severity(findings, SEVERITY_VIOLATION))
                allowed = {t for t in _expected_triples(case) if t[0] in VIOLATION_CHECKS}
                self.assertEqual(
                    got,
                    allowed,
                    f"{case.template.id} was built to carry exactly one defect "
                    f"({case.why}). Linter said:\n{_describe(findings)}",
                )

    def test_planted_violation_makes_the_outcome_fail(self) -> None:
        for case in PLANTED:
            if not any(e.check in VIOLATION_CHECKS for e in case.planted):
                continue
            with self.subTest(case=case.id):
                result = lint(case.template)
                self.assertEqual(result["outcome"], FAIL, f"{case.template.id}: {result}")

    def test_a_risk_alone_does_not_spoil_a_pass(self) -> None:
        """`RISK findings are reported and do NOT change a pass` — contract, verbatim."""
        for case in PLANTED:
            if any(e.check in VIOLATION_CHECKS for e in case.planted):
                continue
            with self.subTest(case=case.id):
                result = lint(case.template)
                findings = _findings(result)
                self.assertEqual(
                    result["outcome"],
                    PASS,
                    f"{case.template.id} carries only a RISK ({case.why}) and must still "
                    f"pass. Linter said:\n{_describe(findings)}",
                )
                self.assertEqual(_of_severity(findings, SEVERITY_VIOLATION), [])

    # -- the clean half: can it say NO? ------------------------------------

    def test_clean_templates_get_nothing_at_all(self) -> None:
        """Not merely `pass`: the contract says the linter must report NOTHING."""
        for case in CLEAN:
            with self.subTest(case=case.id, why=case.why):
                result = lint(case.template)
                findings = _findings(result)
                self.assertEqual(
                    findings,
                    [],
                    f"{case.template.id} is correct ({case.why}) and the linter "
                    f"invented:\n{_describe(findings)}",
                )
                self.assertEqual(result["outcome"], PASS, f"{case.template.id}: {result}")

    def test_the_base_own_repetition_is_subtracted(self) -> None:
        """The case the whole design exists for, asserted by name so a red test says why.

        A sweep of the shipped catalogue found 12 repetitions of which 10 were
        the base's own (contract, MEASURED 2026-08-26). On these two templates
        the repeated word is out of reach of every element, so it is present
        whatever the user picks and the linter must stay silent.
        """
        for case in CLEAN:
            if not case.template.id.startswith("base_repeats"):
                continue
            with self.subTest(case=case.id):
                findings = _findings(lint(case.template))
                repeats = [f for f in findings if str(_field(f, "check")) == "repetition"]
                self.assertEqual(
                    repeats,
                    [],
                    f"{case.template.id}: the repetition is the BASE'S OWN and no value "
                    f"makes it worse. Reporting it is the 10-lies-in-12 failure:\n"
                    f"{_describe(repeats)}",
                )

    # -- the third outcome (Р1: never folded into either of the others) ----

    def test_a_template_with_no_elements_could_not_be_measured(self) -> None:
        case = next(c for c in CONTROL_SET if c.outcome == UNMEASURED)
        result = lint(case.template)
        _findings(result)
        self.assertEqual(result["outcome"], UNMEASURED, f"{case.template.id}: {result}")
        self.assertEqual(result["combinations"], 0, f"{case.template.id}: {result}")

    def test_zero_combinations_is_never_a_pass(self) -> None:
        """`combinations == 0 is never pass` — contract, verbatim, on every template."""
        for case in CONTROL_SET:
            with self.subTest(case=case.id):
                result = lint(case.template)
                if result["combinations"] == 0:
                    self.assertNotEqual(result["outcome"], PASS, f"{case.template.id}: {result}")

    def test_something_was_actually_rendered(self) -> None:
        """A template that offers values must report having rendered some (Р2)."""
        for case in CONTROL_SET:
            if not case.template.elements:
                continue
            with self.subTest(case=case.id):
                result = lint(case.template)
                self.assertGreater(
                    result["combinations"],
                    0,
                    f"{case.template.id} offers {combinations_of(case.template)} element/value "
                    f"pairs and the linter rendered none: {result}",
                )

    # -- the shape of what comes back --------------------------------------

    def test_every_finding_is_well_formed(self) -> None:
        """A finding names a known check, a real element, and tells a human what to do."""
        names_by_template = {
            c.template.id: {el.name for el in c.template.elements} for c in CONTROL_SET
        }
        for case in CONTROL_SET:
            with self.subTest(case=case.id):
                findings = _findings(lint(case.template))
                for f in findings:
                    self.assertIn(str(_field(f, "check")), CHECKS)
                    self.assertIn(str(_field(f, "severity")), (SEVERITY_VIOLATION, SEVERITY_RISK))
                    self.assertIn(str(_field(f, "element")), names_by_template[case.template.id])
                    self.assertTrue(
                        str(_field(f, "message")).strip(),
                        f"{case.template.id}: a finding with an empty message tells "
                        f"the owner nothing to do about it",
                    )

    def test_every_check_in_the_contract_fires_at_least_once(self) -> None:
        """Six checks are specified; a linter that implements five must not look clean."""
        fired: set[str] = set()
        for case in PLANTED:
            fired |= {t[0] for t in _triples(_findings(lint(case.template)))}
        missing = sorted(set(VIOLATION_CHECKS + RISK_CHECKS) - fired)
        self.assertEqual(missing, [], f"these checks never fired on any planted defect: {missing}")

    def test_lint_catalogue_aggregates_the_whole_set(self) -> None:
        """The catalogue form must fail when any member fails, and count every render."""
        templates = tuple(c.template for c in CONTROL_SET)
        result = lint_catalogue(templates)
        findings = _findings(result)
        self.assertEqual(result["outcome"], FAIL, f"the set contains planted VIOLATIONS: {result}")
        self.assertGreater(result["combinations"], 0)
        planted = set()
        for case in PLANTED:
            planted |= {(e.check, e.element, e.value) for e in case.planted}
        got = _triples(findings)
        missing = sorted(t for t in planted if t not in got and (t[0], t[1], "") not in got)
        self.assertEqual(missing, [], f"lint_catalogue lost planted defects: {missing}")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
