"""Finding a credential when the name is spelled by a human.

One module, because two modules had already grown the same lookup and the
same defect. `search.py` and `probe.py` both import from here; neither reads
`os.environ` for a credential on its own.

Why this is not `os.environ.get(NAME)`:

OBSERVED 2026-08-27, on the live container. The owner set the Gemini key as
`Gemini_API_KEY`. The package listed `GEMINI_API_KEY`, `os.environ` is
case-sensitive on Linux, and so the agent reported "no key" with a working
53-character key sitting beside it — and a whole session was spent believing
the credential had never arrived.

That is the second time in this package. `probe.py` looked for
`KLING_API_KEY` while the environment set `KLING_KEY`, and reported "no API
key" the same way. Both defects have one shape: **a lookup that guesses at a
name will meet a name somebody else chose.** So the rule here is to match the
listed names loosely, and then report the spelling that was actually found
rather than the spelling that was expected — because the difference between
those two is exactly the thing the owner needs to see.

Exactness still wins where it exists: an exact hit on any listed name beats a
case-folded hit on any other, so listing a preferred name keeps meaning what
it meant. Only when no name matches exactly does the case-folded pass run.
"""

from __future__ import annotations

import os


def find(names: tuple[str, ...]) -> tuple[str, str]:
    """(value, the variable name it actually came from). ("", "") when unset.

    The second element is evidence, not an echo of the argument: it is the
    key as `os.environ` spells it, so a report can show the owner what they
    really typed. Values are stripped; a variable set to whitespace counts as
    unset, since that is what an empty shell substitution leaves behind.

    :param names: candidate variable names, most-preferred first.
    """
    for name in names:
        value = os.environ.get(name, "").strip()
        if value:
            return value, name

    folded = {name.casefold() for name in names}
    # Sorted so that two variables differing only in case resolve the same way
    # on every run; a lookup that picks by dict order is a lookup that changes
    # its mind between processes.
    for actual in sorted(os.environ):
        if actual.casefold() in folded:
            value = os.environ[actual].strip()
            if value:
                return value, actual
    return "", ""
