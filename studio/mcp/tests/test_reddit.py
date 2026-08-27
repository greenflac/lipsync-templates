"""The Reddit collector: does it tell a missing credential from an empty subreddit?

Nothing here reaches the network. The fetcher is injected and the payloads are
literals in the shape Reddit documents. The live path has never run — there is
no Reddit credential in this environment — and these tests do not pretend
otherwise: they cover the parsing, the credential handling and the three
outcomes, which is exactly what can be checked without one.

Expected values are literals (house rule T2).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from studio.mcp import reddit

HARVESTED = "2026-08-27"
RIGHTS = "owner_authorisation_2026-08-27"

BODY = " ".join(["word"] * 25)


def _post(**over: object) -> dict:
    data: dict = {
        "title": "My ComfyUI upscale workflow",
        "selftext": BODY,
        "permalink": "/r/comfyui/comments/abc/my_workflow/",
        "author": "someone",
        "link_flair_text": "Workflow Included",
        "score": 120,
        "num_comments": 14,
        "created_utc": 1756300000,
        "over_18": False,
    }
    data.update(over)
    return {"kind": "t3", "data": data}


def _listing(posts: list[dict] | None = None, after: str = "") -> dict:
    return {
        "kind": "Listing",
        "data": {"children": posts if posts is not None else [_post()], "after": after},
    }


class _Fetcher:
    def __init__(self, table: dict[str, object]) -> None:
        self.table = table
        self.calls: list[tuple[str, dict]] = []

    def __call__(self, url: str, **kwargs: object) -> dict:
        self.calls.append((url, dict(kwargs)))
        for fragment, payload in self.table.items():
            if fragment in url:
                if payload is None:
                    return {"outcome": "fail", "note": "refused", "text": ""}
                return {"outcome": "pass", "text": json.dumps(payload), "status": 200}
        return {"outcome": "could not measure", "note": "not in the table", "text": ""}


class TheCredential(unittest.TestCase):
    def test_no_credential_is_could_not_measure_and_never_fail(self) -> None:
        """A gap in this environment is not Reddit refusing us, and the two
        must not print the same — the whole reason there are three outcomes."""
        with mock.patch.dict("os.environ", {}, clear=True):
            out = reddit.token(fetcher=_Fetcher({}))
        assert out["outcome"] == "could not measure"
        assert out["token"] == ""
        assert "REDDIT_CLIENT_ID" in out["note"], "it must name what to set"

    def test_half_a_credential_names_which_half_is_missing(self) -> None:
        with mock.patch.dict("os.environ", {"REDDIT_CLIENT_ID": "abc"}, clear=True):
            out = reddit.token(fetcher=_Fetcher({}))
        assert out["outcome"] == "could not measure"
        assert "client secret" in out["note"]
        assert "client id" not in out["note"]

    def test_a_name_the_owner_spelled_differently_is_still_found_and_reported(self) -> None:
        """This package has twice reported "no key" beside a working one whose
        variable a human named differently. What comes back is the spelling
        that was FOUND, because that is the difference the owner needs to see."""
        env = {"Reddit_Client_Id": "abc", "reddit_client_secret": "xyz"}
        with mock.patch.dict("os.environ", env, clear=True):
            fetcher = _Fetcher({"access_token": {"access_token": "T"}})
            out = reddit.token(fetcher=fetcher)
        assert out["outcome"] == "pass"
        assert out["found_as"] == ["Reddit_Client_Id", "reddit_client_secret"]

    def test_the_credential_goes_out_as_http_basic_and_a_form_body(self) -> None:
        env = {"REDDIT_CLIENT_ID": "abc", "REDDIT_CLIENT_SECRET": "xyz"}
        with mock.patch.dict("os.environ", env, clear=True):
            fetcher = _Fetcher({"access_token": {"access_token": "T"}})
            reddit.token(fetcher=fetcher)
        _url, kwargs = fetcher.calls[0]
        # "abc:xyz" base64-encoded, as a literal.
        assert kwargs["headers"]["Authorization"] == "Basic YWJjOnh5eg=="
        assert kwargs["data"] == b"grant_type=client_credentials"

    def test_a_token_endpoint_that_answers_without_a_token_is_fail(self) -> None:
        env = {"REDDIT_CLIENT_ID": "abc", "REDDIT_CLIENT_SECRET": "xyz"}
        with mock.patch.dict("os.environ", env, clear=True):
            out = reddit.token(fetcher=_Fetcher({"access_token": {"error": "nope"}}))
        assert out["outcome"] == "fail"
        assert out["token"] == ""


class ReadingAListing(unittest.TestCase):
    def test_a_workflow_post_carries_its_wording_its_link_and_its_origin(self) -> None:
        out = reddit.posts_from_listing(_listing(), "comfyui", HARVESTED, RIGHTS)
        assert out["outcome"] == "pass"
        row = out["rows"][0]
        assert row["title"] == "My ComfyUI upscale workflow"
        assert row["permalink"] == "https://www.reddit.com/r/comfyui/comments/abc/my_workflow/"
        assert row["provenance"] == "reddit:someone"
        assert row["rights"] == "owner_authorisation_2026-08-27"
        assert row["harvested"] == "2026-08-27"

    def test_a_link_post_with_no_body_is_dropped_and_counted(self) -> None:
        out = reddit.posts_from_listing(
            _listing([_post(selftext="")]), "comfyui", HARVESTED, RIGHTS
        )
        assert out["outcome"] == "could not measure", "zero usable is never a pass"
        assert out["no_body"] == 1

    def test_twenty_words_is_enough_and_nineteen_is_not(self) -> None:
        """The constant both ways, as literals."""
        twenty = reddit.posts_from_listing(
            _listing([_post(selftext=" ".join(["w"] * 20))]), "comfyui", HARVESTED, RIGHTS
        )
        nineteen = reddit.posts_from_listing(
            _listing([_post(selftext=" ".join(["w"] * 19))]), "comfyui", HARVESTED, RIGHTS
        )
        assert len(twenty["rows"]) == 1
        assert nineteen["rows"] == []

    def test_a_removed_post_is_counted_as_removed_not_as_a_short_one(self) -> None:
        """Reddit blanks the text and keeps the row. Counting a takedown as
        thin content would report other people's removals as our filtering."""
        out = reddit.posts_from_listing(
            _listing([_post(selftext="[removed]"), _post(selftext="[deleted]")]),
            "comfyui",
            HARVESTED,
            RIGHTS,
        )
        assert out["removed"] == 2
        assert out["no_body"] == 0

    def test_the_cursor_is_returned_so_the_next_page_can_be_asked_for(self) -> None:
        out = reddit.posts_from_listing(_listing(after="t3_xyz"), "comfyui", HARVESTED, RIGHTS)
        assert out["after"] == "t3_xyz"

    def test_an_empty_listing_is_could_not_measure(self) -> None:
        out = reddit.posts_from_listing(_listing([]), "comfyui", HARVESTED, RIGHTS)
        assert out["outcome"] == "could not measure"
        assert out["checked"] == 0

    def test_a_body_that_is_not_a_listing_yields_nothing_rather_than_raising(self) -> None:
        assert reddit.posts_from_listing(None, "comfyui", HARVESTED, RIGHTS)["rows"] == []
        assert reddit.posts_from_listing({"data": "x"}, "comfyui", HARVESTED, RIGHTS)["rows"] == []


class Collecting(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "reddit.jsonl"
        self.slept: list[float] = []

    def _collect(self, fetcher: _Fetcher, **over: object) -> dict:
        kwargs: dict = {
            "harvested": HARVESTED,
            "rights": RIGHTS,
            "path": self.path,
            "fetcher": fetcher,
            "sleeper": self.slept.append,
            "bearer": "T",
        }
        kwargs.update(over)
        return reddit.collect(**kwargs)

    def test_a_good_walk_writes_posts_and_sends_the_bearer(self) -> None:
        fetcher = _Fetcher({"/r/comfyui/hot": _listing()})
        out = self._collect(fetcher)
        assert out["outcome"] == "pass"
        assert out["written"] == 1
        assert fetcher.calls[0][1]["headers"]["Authorization"] == "Bearer T"

    def test_no_credential_stops_the_walk_as_could_not_measure(self) -> None:
        """The distinction this whole module is built around: an empty file
        because we could not log in must not read as an empty subreddit."""
        with mock.patch.dict("os.environ", {}, clear=True):
            out = self._collect(_Fetcher({}), bearer="")
        assert out["outcome"] == "could not measure"
        assert out["written"] == 0
        assert not self.path.exists()

    def test_an_authenticated_but_empty_harvest_says_it_was_authenticated(self) -> None:
        fetcher = _Fetcher({"/r/comfyui/hot": _listing([_post(selftext="")])})
        out = self._collect(fetcher)
        assert out["outcome"] == "could not measure"
        assert "authenticated" in out["note"], "it must not read like a login failure"

    def test_running_twice_does_not_collect_the_same_post_twice(self) -> None:
        fetcher = _Fetcher({"/r/comfyui/hot": _listing()})
        self._collect(fetcher)
        again = self._collect(fetcher)
        assert again["written"] == 0
        assert len(self.path.read_text(encoding="utf-8").splitlines()) == 1

    def test_it_follows_the_cursor_and_waits_between_pages(self) -> None:
        fetcher = _Fetcher({"/r/comfyui/hot": _listing(after="t3_next")})
        self._collect(fetcher, pages=2)
        assert len(fetcher.calls) == 2
        assert "after=t3_next" in fetcher.calls[1][0]
        assert self.slept and min(self.slept) >= 1.0

    def test_it_stops_when_the_cursor_runs_out_rather_than_re_reading_page_one(self) -> None:
        fetcher = _Fetcher({"/r/comfyui/hot": _listing(after="")})
        self._collect(fetcher, pages=5)
        assert len(fetcher.calls) == 1

    def test_a_refused_listing_is_fail_and_writes_nothing(self) -> None:
        out = self._collect(_Fetcher({"/r/comfyui/hot": None}))
        assert out["outcome"] == "fail"
        assert not self.path.exists()

    def test_a_row_without_its_origin_stops_the_whole_write(self) -> None:
        fetcher = _Fetcher({"/r/comfyui/hot": _listing()})
        out = self._collect(fetcher, rights="  ")
        assert out["outcome"] == "fail"
        assert out["written"] == 0
        assert not self.path.exists()


if __name__ == "__main__":
    unittest.main()
