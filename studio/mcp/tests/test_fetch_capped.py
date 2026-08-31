"""Truncation has to be visible, or a cut body gets blamed on its format.

Nothing here opens a socket (rule T4): the fork was moved out of `fetch` so a
test could reach it with a fake reader.
"""

from __future__ import annotations

import io
import unittest

from studio.mcp.fetch import read_capped


class ACutBodySaysSo(unittest.TestCase):
    def test_a_body_longer_than_the_cap_is_reported_as_cut(self) -> None:
        """The real case, in miniature: a listing longer than the ceiling came
        back as invalid JSON and the run blamed the format."""
        body, truncated = read_capped(io.BytesIO(b"0123456789"), 4)
        assert body == b"0123"
        assert truncated is True

    def test_a_body_shorter_than_the_cap_is_NOT_reported_as_cut(self) -> None:
        """The negative control (rule I5). A flag that is always up is not a
        flag, and here it would send every reader hunting a phantom."""
        body, truncated = read_capped(io.BytesIO(b"012"), 4)
        assert body == b"012"
        assert truncated is False

    def test_a_body_exactly_the_length_of_the_cap_is_whole(self) -> None:
        """The edge that a naive `read(max_bytes)` cannot tell from a cut one,
        which is the whole reason the read asks for one byte more."""
        body, truncated = read_capped(io.BytesIO(b"0123"), 4)
        assert body == b"0123"
        assert truncated is False

    def test_one_byte_over_the_cap_is_cut(self) -> None:
        """The other side of the same edge."""
        body, truncated = read_capped(io.BytesIO(b"01234"), 4)
        assert body == b"0123"
        assert truncated is True

    def test_an_empty_body_is_whole_not_cut(self) -> None:
        body, truncated = read_capped(io.BytesIO(b""), 4)
        assert body == b""
        assert truncated is False


if __name__ == "__main__":
    unittest.main()
