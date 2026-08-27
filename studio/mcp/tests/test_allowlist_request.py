"""The allowlist request generator: does the wildcard form say what we mean?

The generator lives in `scripts/` because it is a tool, not a library, but the
decisions inside it are real — how wide an ask is, and whether the block a
human pastes is pasteable — so they are gated here rather than described in a
comment (house rule C7).

Expected values are literals. Importing the script's own tables to check the
script would check nothing.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "allowlist_request",
    Path(__file__).resolve().parents[3] / "scripts" / "allowlist_request.py",
)
assert _SPEC and _SPEC.loader
gen = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(gen)


class RegistrableDomain(unittest.TestCase):
    def test_a_subdomain_resolves_to_the_domain_a_wildcard_is_written_against(self) -> None:
        assert gen.registrable("docs.bfl.ai") == "bfl.ai"
        assert gen.registrable("api.dev.runwayml.com") == "runwayml.com"

    def test_an_apex_is_already_the_domain(self) -> None:
        assert gen.registrable("arxiv.org") == "arxiv.org"

    def test_a_tld_that_looks_like_a_name_is_still_a_tld(self) -> None:
        """`.dev` and `.google` are real TLDs; two labels is still the answer."""
        assert gen.registrable("ai.google.dev") == "google.dev"
        assert gen.registrable("deepmind.google") == "deepmind.google"


class TheBlockAHumanPastes(unittest.TestCase):
    def test_nothing_but_hostnames_reaches_the_paste_block(self) -> None:
        """OBSERVED 2026-08-27: the exceptions were rendered INSIDE the fence.

        A block that has to be edited before it is pasted is a block that gets
        pasted wrong.
        """
        lines, notes = gen.wildcard_form()
        assert notes, "the exceptions must exist somewhere"
        for line in lines:
            assert line.strip(), "no blank lines in a list somebody pastes"
            assert " " not in line, f"{line!r} is prose, not a host"
            assert not line.startswith("-"), f"{line!r} is a note, not a host"

    def test_a_wildcard_is_asked_for_alongside_its_apex(self) -> None:
        """A wildcard does not always cover the apex, and for several of these
        the apex is itself a host we asked for."""
        lines, _ = gen.wildcard_form()
        assert "*.civitai.com" in lines
        assert "civitai.com" in lines

    def test_the_broadest_domain_is_refused_a_wildcard(self) -> None:
        """`*.google.com` is Search, Mail and Drive for the sake of one docs host."""
        lines, _ = gen.wildcard_form()
        assert "*.google.com" not in lines, "this would ask for all of Google"
        assert "*.cloud.google.com" in lines, "the narrow form, under a host already open"

    def test_every_wanted_host_is_covered_by_something_in_the_block(self) -> None:
        """The whole point: paste this and no host in the request stays shut."""
        lines, _ = gen.wildcard_form()
        exact = {line for line in lines if not line.startswith("*.")}
        suffixes = {line[1:] for line in lines if line.startswith("*.")}
        for _group, host, _why in gen.WANTED:
            covered = host in exact or any(host.endswith(s) for s in suffixes)
            assert covered, f"{host} is asked for but nothing in the block covers it"

    def test_the_block_is_built_from_the_hosts_still_refused_not_the_seed_list(self) -> None:
        """OBSERVED 2026-08-27, the day after the grant landed.

        `WANTED` is the seed list the generator probes and a host stays in it
        forever. The block was built from it, so once 21 hosts were granted the
        document offered fourteen already-granted domains under a header saying
        sixteen hosts — the two halves of one page disagreeing, which is the
        third time this generator has produced that shape.

        The test above still checks the seed default. This one checks that a
        measured ask REPLACES it, and the assertion runs both ways: what is
        asked for is covered, and what is not asked for is absent.
        """
        lines, _ = gen.wildcard_form(["www.atlascloud.ai", "gaga.art"])
        assert sorted(lines) == ["*.atlascloud.ai", "*.gaga.art", "atlascloud.ai", "gaga.art"]
        assert "*.civitai.com" not in lines, "a granted domain leaked in from the seed list"
        assert "*.arxiv.org" not in lines, "a granted domain leaked in from the seed list"

    def test_an_empty_ask_renders_an_empty_block_rather_than_the_seed(self) -> None:
        """Nothing left to ask for must not silently print the original request:
        asking for access already granted is the failure this file exists to
        avoid, and it is worse than saying nothing."""
        lines, notes = gen.wildcard_form([])
        assert lines == []
        assert notes == []

    def test_the_block_would_not_cover_a_host_of_a_vendor_we_never_asked_about(self) -> None:
        """The negative control: a block that covers everything measures nothing."""
        lines, _ = gen.wildcard_form()
        exact = {line for line in lines if not line.startswith("*.")}
        suffixes = {line[1:] for line in lines if line.startswith("*.")}
        for stranger in ("evil.example.com", "mail.google.com", "some-blog.test"):
            covered = stranger in exact or any(stranger.endswith(s) for s in suffixes)
            assert not covered, f"{stranger} must not be covered"


if __name__ == "__main__":
    unittest.main()
