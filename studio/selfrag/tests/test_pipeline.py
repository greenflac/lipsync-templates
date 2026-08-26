"""The pipeline end to end, and the guarantee that none of it touches the network."""

from __future__ import annotations

import json
import socket
import tempfile
import unittest
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.selfrag.corpus import CorpusRecord, load_corpus
from studio.selfrag.evaluate import DEMO_CORPUS_PATH
from studio.selfrag.pipeline import PromptEngineer, PromptRequest, spec_from_text
from studio.selfrag.spec import MODE_T2V


def demo_records() -> list[CorpusRecord]:
    out = load_corpus(paths=[DEMO_CORPUS_PATH])
    assert out["outcome"] == PASS, out["note"]
    return out["records"]


class NoNetwork(unittest.TestCase):
    """The runner enforces it, not a convention.

    Every socket constructor is replaced for the duration, so a test that
    reaches the network fails loudly here rather than passing on a warm cache
    and failing in somebody else's CI.
    """

    def setUp(self) -> None:
        self.real_socket = socket.socket
        self.real_create = socket.create_connection

        def refuse(*args: object, **kwargs: object) -> None:
            raise AssertionError("a test tried to open a socket")

        setattr(socket, "socket", refuse)
        setattr(socket, "create_connection", refuse)

        def restore() -> None:
            setattr(socket, "socket", self.real_socket)
            setattr(socket, "create_connection", self.real_create)

        self.addCleanup(restore)

    def test_a_full_run_needs_no_socket(self) -> None:
        engineer = PromptEngineer(records=demo_records(), state_path=":memory:")
        self.addCleanup(engineer.close)
        out = engineer.write(
            PromptRequest(
                text="a rain-slick rooftop at dusk, amber golden-hour light, film grain, nostalgic",
                model="veo",
                mode=MODE_T2V,
                subject="a lone cyclist",
                action="rides slowly past",
                camera="slow dolly in, low angle",
                audio="distant traffic and wind",
                duration_seconds=8,
                aspect_ratio="9:16",
            )
        )
        self.assertEqual(out["outcome"], PASS)
        self.assertTrue(out["prompt"])

    def test_the_guard_itself_works(self) -> None:
        """The negative control on the control: if this passes, the guard above
        proves nothing."""
        with self.assertRaises(AssertionError):
            socket.socket()


class EndToEnd(unittest.TestCase):
    def setUp(self) -> None:
        self.engineer = PromptEngineer(records=demo_records(), state_path=":memory:")
        self.addCleanup(self.engineer.close)

    def request(self, **kwargs: object) -> PromptRequest:
        base = dict(
            text="a rain-slick rooftop at dusk, amber golden-hour light, film grain, nostalgic",
            model="veo",
            mode=MODE_T2V,
            subject="a lone cyclist",
            action="rides slowly past",
            camera="slow dolly in, low angle",
            audio="distant traffic and wind",
            duration_seconds=8,
        )
        base.update(kwargs)
        return PromptRequest(**base)  # type: ignore[arg-type]

    def test_a_good_request_produces_a_prompt_and_its_precedents(self) -> None:
        out = self.engineer.write(self.request())
        self.assertEqual(out["outcome"], PASS)
        self.assertIn("a lone cyclist", out["prompt"])
        self.assertTrue(out["examples"])
        self.assertEqual(out["examples"][0]["model"], "veo-3.1")

    def test_the_stage_receipt_says_where_a_run_went(self) -> None:
        out = self.engineer.write(self.request())
        self.assertEqual(
            set(out["stages"]),
            {"availability", "cache", "retrieval", "context", "extract", "reflect"},
        )

    def test_the_second_identical_call_is_served_from_cache(self) -> None:
        request = self.request()
        first = self.engineer.write(request)
        second = self.engineer.write(request)
        self.assertFalse(first["cached"])
        self.assertTrue(second["cached"])
        self.assertEqual(first["prompt"], second["prompt"])

    def test_a_retired_model_is_refused_before_anything_is_spent(self) -> None:
        from datetime import date

        import studio.selfrag.registry as registry

        class Later:
            """A stand-in for `date` whose today is past Sora's end of life."""

            @staticmethod
            def today() -> date:
                return date(2027, 1, 1)

            @staticmethod
            def fromisoformat(value: str) -> date:
                return date.fromisoformat(value)

        real = registry.date
        try:
            setattr(registry, "date", Later)
            out = self.engineer.write(self.request(model="sora"))
        finally:
            setattr(registry, "date", real)
        self.assertEqual(out["outcome"], FAIL)
        self.assertEqual(out["stages"]["availability"]["outcome"], FAIL)
        # Nothing after the first stage ran: the refusal came before the work.
        self.assertNotIn("retrieval", out["stages"])

    def test_a_request_with_no_precedent_says_so_rather_than_inventing_one(self) -> None:
        out = self.engineer.write(
            self.request(
                text="quarterly value-added tax reconciliation for a tractor dealership",
                subject="a tractor",
                action="ploughs slowly",
            )
        )
        self.assertEqual(out["examples"], [])
        self.assertIn("no usable precedent", out["note"])
        self.assertEqual(out["rewrite_step"], 3)

    def test_a_defaulted_style_field_stops_the_run_claiming_a_clean_pass(self) -> None:
        """'the user asked for a calm mood' and 'nobody said, so we picked calm'
        look identical in the finished prompt and must not in the report."""
        out = self.engineer.write(self.request(text="just make it nice"))
        self.assertEqual(out["outcome"], UNMEASURED)
        self.assertIn("this module's choice, not the user's", out["note"])

    def test_the_reviser_converts_a_dead_clause_into_a_real_parameter(self) -> None:
        out = self.engineer.write(
            self.request(
                model="seedance",
                text="rose candlelit dining room, velvet texture, dreamy",
                audio="",
                camera="gentle handheld drift",
                duration_seconds=10,
            )
        )
        self.assertTrue(out["parameters"].get("camera_fixed"))
        self.assertNotIn("handheld drift", out["prompt"])
        self.assertEqual([h["outcome"] for h in out["history"]][0], FAIL)
        self.assertGreaterEqual(len(out["history"]), 2)

    def test_the_journal_records_the_resolved_model_not_the_alias(self) -> None:
        """A report where 'veo', 'veo3' and 'veo-3.1' are three rows cannot
        count how often Veo failed."""
        self.engineer.write(self.request(model="veo"))
        self.engineer.write(self.request(model="veo3", camera="slow pan"))
        report = self.engineer.journal.report()
        self.assertIn("veo-3.1", report["by_model"])
        self.assertNotIn("veo3", report["by_model"])

    def test_feedback_changes_which_precedent_wins(self) -> None:
        before = self.engineer.write(self.request())
        top = before["examples"][0]["record_id"]
        for _ in range(5):
            self.engineer.replay.record(
                record_id=top,
                prompt="p",
                model="veo-3.1",
                outcome=FAIL,
                rating=1,
                artifact="out/bad.mp4",
            )
        after = self.engineer.write(self.request(camera="a slow crane rise"))
        self.assertTrue(after["examples"])
        scores = {e["record_id"]: e["score"] for e in after["examples"]}
        self.assertLess(scores.get(top, 0.0), before["examples"][0]["score"])


class SpecFromText(unittest.TestCase):
    def test_derived_fields_are_separated_from_defaulted_ones(self) -> None:
        request = PromptRequest(text="", model="veo")
        full = spec_from_text(
            "amber golden-hour light, film-grain texture, nostalgic mood", request=request
        )
        self.assertEqual(full["outcome"], PASS)
        self.assertEqual(full["defaulted"], [])
        self.assertEqual(full["spec"].light, "golden-hour")

        sparse = spec_from_text("something nice", request=request)
        self.assertEqual(sparse["outcome"], UNMEASURED)
        self.assertEqual(len(sparse["defaulted"]), 4)

    def test_the_pick_is_deterministic_across_runs(self) -> None:
        request = PromptRequest(text="", model="veo")
        text = "amber and teal, soft studio light, matte and glossy, calm and serene"
        first = spec_from_text(text, request=request)["spec"]
        for _ in range(5):
            self.assertEqual(spec_from_text(text, request=request)["spec"], first)


class Async(unittest.IsolatedAsyncioTestCase):
    async def test_awrite_matches_write(self) -> None:
        engineer = PromptEngineer(records=demo_records(), state_path=":memory:")
        self.addCleanup(engineer.close)
        request = PromptRequest(
            text="emerald forest floor, low-key light, smoky, serene",
            model="veo",
            mode=MODE_T2V,
            subject="a deer",
            action="steps slowly through the ferns",
        )
        out = await engineer.awrite(request)
        self.assertEqual(out["outcome"], PASS)
        self.assertTrue(out["prompt"])


if __name__ == "__main__":
    unittest.main()


class GateIsDeterministic(unittest.TestCase):
    """The CI gate must depend only on committed content.

    It used to fall back to the configured corpus paths when no --corpus was
    given, so the moment an operator dropped their own corpus on disk the gate
    scored the fixture's gold set against a corpus that gold set knows nothing
    about, and CI went red on a file nobody had committed (OBSERVED
    2026-08-26). A gate whose verdict depends on an uncommitted local file is
    not a gate.
    """

    def test_eval_ignores_the_operators_corpus(self) -> None:
        import os
        from unittest import mock

        from studio.selfrag import cli

        with tempfile.TemporaryDirectory() as tmp:
            decoy = Path(tmp) / "operator.jsonl"
            decoy.write_text(
                json.dumps({"prompt": "a decoy nobody's gold set has ever seen"}) + "\n",
                encoding="utf-8",
            )
            with mock.patch.dict(os.environ, {"STUDIO_CORPUS_PATHS": str(decoy)}, clear=False):
                args = cli.build_parser().parse_args(["--state", ":memory:", "--json", "eval"])
                code = cli.cmd_eval(args)
        # 0 is pass. Had the decoy been picked up, the fixture's gold set would
        # have found nothing in it and this would be 1.
        self.assertEqual(code, 0)
