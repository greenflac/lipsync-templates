"""The Civitai collector: does it keep the origin, the ceiling and the third outcome?

No test here reaches the network. The fetcher is injected and the payloads are
literals shaped like the ones MEASURED on 2026-08-27 — a test that needs
civitai.com goes red when somebody else's site has a bad day, and green off a
cache, and it measures neither (house rule T4).

Expected values are literals, never imported from the module under test: an
expectation that moves with the code checks nothing (house rule T2).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Callable
from pathlib import Path

from studio.mcp import civitai

HARVESTED = "2026-08-27"
RIGHTS = "owner_authorisation_2026-08-27"


def _image(**over: object) -> dict:
    """One image as the version endpoint really returns it."""
    row: dict = {
        "url": "https://image.civitai.com/abc/original=true/1.jpeg",
        "width": 1096,
        "height": 1648,
        "nsfwLevel": 1,
        "hasMeta": True,
        "hasPositivePrompt": True,
        "meta": {
            "prompt": "a portrait of a woman in a red coat",
            "negativePrompt": "blurry, low quality",
            "seed": 132340247,
            "steps": 28,
            "sampler": "DPM++ 2M Karras",
            "cfgScale": 7,
            "Size": "512x768",
            "Model": "DreamShaper8_pruned",
            "clipSkip": 2,
            "ADetailer model": "face_yolov8n.pt",
        },
    }
    row.update(over)
    return row


def _version(images: list[dict] | None = None) -> dict:
    return {
        "id": 128713,
        "baseModel": "SD 1.5",
        "images": images if images is not None else [_image()],
    }


def _listing(model_over: dict | None = None, **over: object) -> dict:
    version: dict = {
        "id": 128713,
        "baseModel": "SD 1.5",
        "images": [{"hasPositivePrompt": True}, {"hasPositivePrompt": True}],
    }
    version.update(over)
    model: dict = {
        "name": "DreamShaper",
        "creator": {"username": "Lykon"},
        "nsfwLevel": 3,
        "modelVersions": [version],
    }
    model.update(model_over or {})
    return {"items": [model], "metadata": {}}


REF = {
    "version_id": 128713,
    "model_name": "DreamShaper",
    "creator": "Lykon",
    "base_model": "SD 1.5",
    "images_claiming_prompt": 2,
}


class _Fetcher:
    """A fetcher that answers from a table, and counts what it was asked for."""

    def __init__(self, table: dict[str, object]) -> None:
        self.table = table
        self.calls: list[str] = []

    def __call__(self, url: str, **_: object) -> dict:
        self.calls.append(url)
        for fragment, payload in self.table.items():
            if fragment in url:
                if payload is None:
                    return {"outcome": "fail", "note": "refused", "text": ""}
                return {"outcome": "pass", "text": json.dumps(payload), "status": 200}
        return {"outcome": "could not measure", "note": "not in the table", "text": ""}


class ReadingOneVersion(unittest.TestCase):
    def test_a_pair_carries_its_prompt_its_image_and_its_origin(self) -> None:
        out = civitai.pairs_from_version(_version(), REF, HARVESTED, RIGHTS)
        assert out["outcome"] == "pass"
        row = out["rows"][0]
        assert row["prompt"] == "a portrait of a woman in a red coat"
        assert row["negative_prompt"] == "blurry, low quality"
        assert row["image_url"] == "https://image.civitai.com/abc/original=true/1.jpeg"
        assert row["source_url"] == "https://civitai.com/api/v1/model-versions/128713"
        assert row["harvested"] == "2026-08-27"
        assert row["rights"] == "owner_authorisation_2026-08-27"

    def test_the_provenance_is_the_uploader_and_not_the_platform(self) -> None:
        """One uploader is one author. Tagging every row `civitai` would make the
        whole corpus one source, and the retriever admits two records per
        source — the defect already recorded against the gallery rows."""
        out = civitai.pairs_from_version(_version(), REF, HARVESTED, RIGHTS)
        assert out["rows"][0]["provenance"] == "civitai:Lykon"

    def test_an_uploader_with_no_name_is_named_unknown_not_left_blank(self) -> None:
        """A blank origin field is a row this module refuses to write, so the
        one field that can legitimately be missing gets a value that says so."""
        ref = {**REF, "creator": ""}
        out = civitai.pairs_from_version(_version(), ref, HARVESTED, RIGHTS)
        assert out["rows"][0]["provenance"] == "civitai:unknown"

    def test_the_workflow_specific_parameters_are_dropped(self) -> None:
        """ADetailer and Hires settings are the uploader's tooling, not the
        prompt. Seven keys are kept and they are named in the module."""
        out = civitai.pairs_from_version(_version(), REF, HARVESTED, RIGHTS)
        assert sorted(out["rows"][0]["parameters"]) == [
            "Model",
            "Size",
            "cfgScale",
            "clipSkip",
            "sampler",
            "seed",
            "steps",
        ]

    def test_an_image_above_the_nsfw_ceiling_is_dropped_and_counted(self) -> None:
        out = civitai.pairs_from_version(_version([_image(nsfwLevel=8)]), REF, HARVESTED, RIGHTS)
        assert out["outcome"] == "could not measure", "zero usable is never a pass"
        assert out["too_explicit"] == 1
        assert out["rows"] == []

    def test_the_ceiling_admits_pg_pg13_and_R(self) -> None:
        """The owner's ruling 2026-08-31, as literals: 1, 2 and 4 in."""
        kept = civitai.pairs_from_version(
            _version(
                [
                    _image(nsfwLevel=1),
                    _image(nsfwLevel=2, url="https://i/2.jpeg"),
                    _image(nsfwLevel=4, url="https://i/4.jpeg"),
                ]
            ),
            REF,
            HARVESTED,
            RIGHTS,
        )
        assert [r["nsfw_level"] for r in kept["rows"]] == [1, 2, 4]

    def test_the_ceiling_still_refuses_X_and_XXX(self) -> None:
        """The other direction, and the line that does not move with the
        ruling: 8 and 16 are a different category and are not collected."""
        for level in (8, 16):
            out = civitai.pairs_from_version(
                _version([_image(nsfwLevel=level)]), REF, HARVESTED, RIGHTS
            )
            assert out["rows"] == [], f"уровень {level} не должен собираться"
            assert out["too_explicit"] == 1

    def test_the_model_bitmask_follows_the_ceiling_instead_of_repeating_it(self) -> None:
        """One knowledge, one place (rule E1). The bitmask is every rung up to
        the ceiling OR-ed together; written as a literal here so it cannot move
        together with the code it is checking (rule T2)."""
        assert civitai.MAX_NSFW_LEVEL == 4
        assert civitai.ALLOWED_MODEL_LEVELS == 7

    def test_a_model_publishing_X_is_still_recognised_as_above_the_ceiling(self) -> None:
        """The gate is off by default, but when switched on it must still fire:
        bitmask 31 spans XXX even when the model's own boolean says otherwise."""
        assert civitai._publishes_above_ceiling({"model_nsfw_level": 31}) is True
        assert civitai._publishes_above_ceiling({"model_nsfw_level": 7}) is False

    def test_a_missing_nsfw_level_is_dropped_rather_than_assumed_safe(self) -> None:
        """Absent is not zero. An unrated image is unrated, not PG."""
        out = civitai.pairs_from_version(_version([_image(nsfwLevel=None)]), REF, HARVESTED, RIGHTS)
        assert out["rows"] == []
        assert out["too_explicit"] == 1

    def test_a_prompt_too_short_to_be_one_is_dropped_and_counted(self) -> None:
        out = civitai.pairs_from_version(
            _version([_image(meta={"prompt": "a woman"})]), REF, HARVESTED, RIGHTS
        )
        assert out["no_prompt"] == 1
        assert out["rows"] == []

    def test_three_words_is_enough_and_two_is_not(self) -> None:
        """The constant in both directions, as literals."""
        three = civitai.pairs_from_version(
            _version([_image(meta={"prompt": "one two three"})]), REF, HARVESTED, RIGHTS
        )
        two = civitai.pairs_from_version(
            _version([_image(meta={"prompt": "one two"})]), REF, HARVESTED, RIGHTS
        )
        assert len(three["rows"]) == 1
        assert two["rows"] == []

    def test_a_stripped_meta_is_could_not_measure_and_says_where_to_look(self) -> None:
        """The shape /api/v1/images already has. If this endpoint is stripped
        too, the collector must say so rather than report a clean empty run."""
        out = civitai.pairs_from_version(
            _version([_image(meta=None), _image(meta=None)]), REF, HARVESTED, RIGHTS
        )
        assert out["outcome"] == "could not measure"
        assert out["checked"] == 2, "it looked at two images and says so"
        assert out["no_prompt"] == 2

    def test_a_version_with_no_images_is_could_not_measure_not_pass(self) -> None:
        out = civitai.pairs_from_version(_version([]), REF, HARVESTED, RIGHTS)
        assert out["outcome"] == "could not measure"
        assert out["checked"] == 0


class ReadingTheListing(unittest.TestCase):
    def test_the_creator_is_carried_from_the_model_because_the_version_lacks_it(self) -> None:
        """MEASURED: `creator` is on the model and absent from every version
        payload, so a collector that fetched versions alone could not name an
        uploader at all."""
        refs = civitai.version_refs(_listing())
        assert refs[0]["creator"] == "Lykon"
        assert refs[0]["model_name"] == "DreamShaper"
        assert refs[0]["base_model"] == "SD 1.5"

    def test_the_listings_own_flag_says_how_many_images_claim_a_prompt(self) -> None:
        refs = civitai.version_refs(_listing())
        assert refs[0]["images_claiming_prompt"] == 2

    def test_a_body_that_is_not_a_listing_yields_nothing_rather_than_raising(self) -> None:
        assert civitai.version_refs(None) == []
        assert civitai.version_refs({"items": "not a list"}) == []
        assert civitai.version_refs({"items": [{"modelVersions": [{}]}]}) == []


class Collecting(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.path = Path(self._dir.name) / "civitai.jsonl"
        self.slept: list[float] = []

    def _collect(self, fetcher: Callable[..., dict], **over: object) -> dict:
        kwargs: dict = {
            "harvested": HARVESTED,
            "rights": RIGHTS,
            "path": self.path,
            "fetcher": fetcher,
            "sleeper": self.slept.append,
        }
        kwargs.update(over)
        return civitai.collect(**kwargs)

    def test_a_version_claiming_no_prompt_is_never_requested(self) -> None:
        """The whole reason walking two endpoints is affordable."""
        listing = _listing(images=[{"hasPositivePrompt": False}])
        fetcher = _Fetcher({"/api/v1/models": listing, "/model-versions/": _version()})
        out = self._collect(fetcher)
        assert not any("model-versions" in call for call in fetcher.calls)
        assert out["outcome"] == "could not measure", "nothing collected is not a pass"
        assert "1 skipped as claiming no prompt" in out["note"]

    def test_a_good_walk_writes_rows_and_reports_the_count(self) -> None:
        fetcher = _Fetcher({"/api/v1/models": _listing(), "/model-versions/": _version()})
        out = self._collect(fetcher)
        assert out["outcome"] == "pass"
        assert out["written"] == 1
        written = [json.loads(line) for line in self.path.read_text(encoding="utf-8").splitlines()]
        assert len(written) == 1
        assert written[0]["provenance"] == "civitai:Lykon"

    def test_running_twice_does_not_collect_the_same_image_twice(self) -> None:
        fetcher = _Fetcher({"/api/v1/models": _listing(), "/model-versions/": _version()})
        self._collect(fetcher)
        again = self._collect(fetcher)
        assert again["written"] == 0
        assert len(self.path.read_text(encoding="utf-8").splitlines()) == 1
        assert again["outcome"] == "pass", "already held is not a failure"

    def test_it_waits_between_requests_by_default(self) -> None:
        """A collector that hammers an API it has permission to use loses the
        permission. The interval is CHOSEN, not measured, and never zero."""
        listing = _listing(images=[{"hasPositivePrompt": True}])
        listing["items"][0]["modelVersions"].append(
            {"id": 999, "baseModel": "SD 1.5", "images": [{"hasPositivePrompt": True}]}
        )
        fetcher = _Fetcher({"/api/v1/models": listing, "/model-versions/": _version()})
        self._collect(fetcher)
        assert self.slept, "two version requests went out back to back"
        assert min(self.slept) >= 1.0

    def test_a_capped_collect_actually_requests_across_models(self) -> None:
        """The wiring, not the helper: `collect` must APPLY the reordering.

        Written because the mutation that removed the call from `collect`
        stayed green — every test of the spread was calling the helper
        directly, so nothing checked that the walk used it."""
        listing = {
            "items": [
                {
                    "name": "A",
                    "creator": {"username": "a"},
                    "modelVersions": [
                        {"id": 11, "baseModel": "x", "images": [{"hasPositivePrompt": True}]},
                        {"id": 12, "baseModel": "x", "images": [{"hasPositivePrompt": True}]},
                    ],
                },
                {
                    "name": "B",
                    "creator": {"username": "b"},
                    "modelVersions": [
                        {"id": 21, "baseModel": "x", "images": [{"hasPositivePrompt": True}]}
                    ],
                },
            ],
            "metadata": {},
        }
        fetcher = _Fetcher({"/api/v1/models": listing, "/model-versions/": _version()})
        self._collect(fetcher, max_versions=2)
        asked = [c.rsplit("/", 1)[-1] for c in fetcher.calls if "model-versions" in c]
        assert asked == ["11", "21"], f"the cap took two versions of one model: {asked}"

    def test_max_versions_caps_the_requests(self) -> None:
        listing = _listing()
        listing["items"][0]["modelVersions"].append(
            {"id": 999, "baseModel": "SD 1.5", "images": [{"hasPositivePrompt": True}]}
        )
        fetcher = _Fetcher({"/api/v1/models": listing, "/model-versions/": _version()})
        self._collect(fetcher, max_versions=1)
        assert sum(1 for c in fetcher.calls if "model-versions" in c) == 1

    def test_a_model_that_publishes_above_the_ceiling_is_counted_and_kept(self) -> None:
        """The image gate cannot see the checkpoint. MEASURED by looking at a
        collected row: it passed at image level 2 while its model was named
        "NSFW MASTER" with nsfwLevel 31. The count goes out by default; the
        skipping does not, because that is a product judgement (rule P1)."""
        listing = _listing(model_over={"nsfwLevel": 31})
        fetcher = _Fetcher({"/api/v1/models": listing, "/model-versions/": _version()})
        out = self._collect(fetcher)
        assert out["outcome"] == "pass", "kept by default"
        assert out["written"] == 1
        assert "1 of them from models that publish above the ceiling" in out["note"]
        assert "were KEPT" in out["note"]

    def test_safe_models_only_actually_skips_them(self) -> None:
        listing = _listing(model_over={"nsfwLevel": 31})
        fetcher = _Fetcher({"/api/v1/models": listing, "/model-versions/": _version()})
        out = self._collect(fetcher, safe_models_only=True)
        assert out["written"] == 0
        assert not any("model-versions" in c for c in fetcher.calls), "not even requested"
        assert "were SKIPPED" in out["note"]

    def test_a_CUT_listing_is_reported_as_cut_and_not_as_bad_json(self) -> None:
        """The defect that killed a real run 2026-08-31. A body cut at the
        ceiling is not JSON either, and blaming the format sends the reader
        after the wrong thing (rule E2)."""

        def cut(url: str, **_: object) -> dict:
            return {
                "outcome": "pass",
                "status": 200,
                "text": '{"items":[{"id":1,"name":"cut here',
                "truncated": True,
                "max_bytes": 3_000_000,
            }

        out = self._collect(cut)
        assert out["outcome"] == "fail"
        assert "CUT at 3000000" in out["note"], out["note"]
        assert "fewer models per page" in out["note"]

    def test_JUNK_that_is_not_cut_is_still_reported_as_bad_json(self) -> None:
        """The negative control (rule I5). If everything unparseable were
        called truncation, the message would be as misleading as the one it
        replaced, just in the other direction."""

        def junk(url: str, **_: object) -> dict:
            return {
                "outcome": "pass",
                "status": 200,
                "text": "<html>rate limited</html>",
                "truncated": False,
                "max_bytes": 3_000_000,
            }

        out = self._collect(junk)
        assert out["outcome"] == "fail"
        assert "not JSON" in out["note"], out["note"]
        assert "CUT" not in out["note"]

    def test_the_listing_ceiling_clears_the_largest_measured_listing(self) -> None:
        """Literals, not an import of the thing being checked (rule T2).
        ИЗМЕРЕНО 2026-08-31: limit=100 is 6 516 550 bytes."""
        assert civitai.LISTING_MAX_BYTES > 6_516_550

    def test_the_bitmask_is_read_as_a_bitmask_not_a_rating(self) -> None:
        """The discriminator, and it flipped when the owner raised the ceiling
        to R on 2026-08-31.

        7 is 1|2|4 — every rung at or below the ceiling — so as a BITMASK it
        passes, while as a plain rating 7 > 4 would drop it. 9 is 1|8: it looks
        small and contains X. 31 contains everything. Read as numbers, 7 and 9
        would both be refused and 31 would be too — but a model at 31 also
        contains rung 1, and an earlier comparison-based reading let exactly
        those through."""
        for level, kept in ((3, 1), (7, 1), (9, 0), (31, 0), (1, 1)):
            with self.subTest(level=level):
                path = self.path.with_name(f"n{level}.jsonl")
                listing = _listing(model_over={"nsfwLevel": level})
                fetcher = _Fetcher({"/api/v1/models": listing, "/model-versions/": _version()})
                out = self._collect(fetcher, safe_models_only=True, path=path)
                assert out["written"] == kept, f"level {level}"

    def test_a_model_with_no_level_is_treated_as_unsafe_not_as_safe(self) -> None:
        """Absent is unrated, not PG."""
        listing = _listing(model_over={"nsfwLevel": None})
        fetcher = _Fetcher({"/api/v1/models": listing, "/model-versions/": _version()})
        assert self._collect(fetcher, safe_models_only=True)["written"] == 0

    def test_a_base_model_filter_reaches_the_request(self) -> None:
        """Without it the harvest is the Stable Diffusion ecosystem: MEASURED,
        750 pairs by Most Downloaded gave 368 SD 1.5 and zero rows on any
        family this project targets."""
        fetcher = _Fetcher({"/api/v1/models": _listing(), "/model-versions/": _version()})
        self._collect(fetcher, base_model="Flux.1 D")
        assert "baseModels=Flux.1%20D" in fetcher.calls[0]

    def test_no_filter_asks_for_no_filter(self) -> None:
        """The negative control: the parameter must not appear when unset."""
        fetcher = _Fetcher({"/api/v1/models": _listing(), "/model-versions/": _version()})
        self._collect(fetcher)
        assert "baseModels" not in fetcher.calls[0]

    def test_an_empty_harvest_under_a_filter_blames_the_filter(self) -> None:
        """A name Civitai does not recognise returns 200 and an empty list, so
        a typo is silent. The note is the only place that silence gets
        explained."""
        empty: dict = {"items": [], "metadata": {}}
        fetcher = _Fetcher({"/api/v1/models": empty})
        out = self._collect(fetcher, base_model="flux.1 d")
        assert out["outcome"] == "could not measure"
        assert "case-sensitive" in out["note"]
        assert "flux.1 d" in out["note"]

    def test_a_refused_listing_is_fail_and_writes_nothing(self) -> None:
        fetcher = _Fetcher({"/api/v1/models": None})
        out = self._collect(fetcher)
        assert out["outcome"] == "fail"
        assert not self.path.exists()

    def test_a_refused_version_is_counted_and_the_rest_still_collect(self) -> None:
        listing = _listing()
        listing["items"][0]["modelVersions"].append(
            {"id": 999, "baseModel": "SD 1.5", "images": [{"hasPositivePrompt": True}]}
        )
        fetcher = _Fetcher({"/api/v1/models": listing, "/model-versions/128713": _version()})
        out = self._collect(fetcher)
        assert out["outcome"] == "pass"
        assert "1 refused" in out["note"]

    def test_a_row_without_its_origin_stops_the_whole_write(self) -> None:
        """The one thing this file must not contain. Nothing is written at all,
        rather than the good rows landing and the bad one vanishing quietly."""
        fetcher = _Fetcher({"/api/v1/models": _listing(), "/model-versions/": _version()})
        out = self._collect(fetcher, rights="   ")
        assert out["outcome"] == "fail"
        assert out["written"] == 0
        assert not self.path.exists()


class SpreadingTheWalk(unittest.TestCase):
    """OBSERVED on the first real run: 29 pairs, one uploader, because the
    listing arrives grouped by model and the ceiling cut inside the first one."""

    def _refs(self) -> list[dict]:
        return [
            {"version_id": 1, "creator": "a", "model_name": "A", "images_claiming_prompt": 1},
            {"version_id": 2, "creator": "a", "model_name": "A", "images_claiming_prompt": 1},
            {"version_id": 3, "creator": "a", "model_name": "A", "images_claiming_prompt": 1},
            {"version_id": 4, "creator": "b", "model_name": "B", "images_claiming_prompt": 1},
            {"version_id": 5, "creator": "c", "model_name": "C", "images_claiming_prompt": 1},
        ]

    def test_a_capped_run_reaches_every_model_before_a_second_version(self) -> None:
        order = [r["version_id"] for r in civitai._one_model_at_a_time(self._refs())]
        assert order[:3] == [1, 4, 5], f"the first three touched one model: {order}"

    def test_nothing_is_dropped_or_duplicated_by_the_reordering(self) -> None:
        """Only the ORDER changes. An uncapped run must collect the same set,
        which is what makes this safe to apply on every run."""
        order = [r["version_id"] for r in civitai._one_model_at_a_time(self._refs())]
        assert sorted(order) == [1, 2, 3, 4, 5]

    def test_two_models_by_one_author_are_still_two_queues(self) -> None:
        """Grouping by creator alone would merge them, and a prolific author
        would again fill a capped run — the same defect one level up."""
        refs = [
            {"version_id": 1, "creator": "a", "model_name": "A", "images_claiming_prompt": 1},
            {"version_id": 2, "creator": "a", "model_name": "A", "images_claiming_prompt": 1},
            {"version_id": 3, "creator": "a", "model_name": "Z", "images_claiming_prompt": 1},
        ]
        order = [r["version_id"] for r in civitai._one_model_at_a_time(refs)]
        assert order == [1, 3, 2], f"model A and model Z must alternate: {order}"

    def test_the_same_model_name_from_two_authors_is_two_queues(self) -> None:
        """Model names on Civitai are not unique — "Realistic Vision" style
        names get reused. Keying the queues on the name alone would merge two
        strangers' work into one queue and starve one of them."""
        refs = [
            {"version_id": 1, "creator": "a", "model_name": "Same", "images_claiming_prompt": 1},
            {"version_id": 2, "creator": "a", "model_name": "Same", "images_claiming_prompt": 1},
            {"version_id": 3, "creator": "b", "model_name": "Same", "images_claiming_prompt": 1},
        ]
        order = [r["version_id"] for r in civitai._one_model_at_a_time(refs)]
        assert order == [1, 3, 2], f"two authors were merged into one queue: {order}"

    def test_order_within_one_model_is_preserved(self) -> None:
        order = [r["version_id"] for r in civitai._one_model_at_a_time(self._refs())]
        assert [v for v in order if v in (1, 2, 3)] == [1, 2, 3]


class Summarising(unittest.TestCase):
    def test_it_names_how_concentrated_the_corpus_is(self) -> None:
        rows = [
            {"provenance": "civitai:a"},
            {"provenance": "civitai:a"},
            {"provenance": "civitai:b"},
        ]
        out = civitai.summarise(rows)
        assert out["outcome"] == "pass"
        assert out["by_provenance"] == {"civitai:a": 2, "civitai:b": 1}

    def test_an_empty_corpus_is_could_not_measure(self) -> None:
        assert civitai.summarise([])["outcome"] == "could not measure"


if __name__ == "__main__":
    unittest.main()
