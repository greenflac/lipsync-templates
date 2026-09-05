"""The validator bench: does it actually cut the answer off the picture?

Everything here runs on files this test makes, so nothing needs the corpus —
which is deliberate, because the corpus is not committed and a test that needs
it passes here and fails in CI (this repository has paid for that three times).

THE ONE PROPERTY THAT MATTERS

A creative arrives carrying its own answer. MEASURED 2026-08-30 on the first row
of our civitai corpus: 6259 characters of ComfyUI graph, the checkpoint name,
the LoRA, the sampler, and the prompt itself — all inside the PNG. Hand that over
and the reader is not reading a picture, it is reading an answer key. If the
strip ever stops stripping, every number the bench produces afterwards is a lie
about the agent's ability, and nothing downstream would notice.
"""

from __future__ import annotations

import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest import mock

from lipsync.fork_identity import FAIL, PASS
from PIL import Image, PngImagePlugin

_SPEC = importlib.util.spec_from_file_location(
    "validator", Path(__file__).resolve().parents[3] / "scripts" / "validator.py"
)
assert _SPEC and _SPEC.loader
bench = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bench)


def _loaded_png(**fields: str) -> bytes:
    meta = PngImagePlugin.PngInfo()
    for key, value in fields.items():
        meta.add_text(key, value)
    buffer = io.BytesIO()
    Image.new("RGB", (48, 48), (30, 60, 120)).save(buffer, "PNG", pnginfo=meta)
    return buffer.getvalue()


def _strip(raw: bytes) -> list[str]:
    """The re-encode the bench performs, and what provenance survives it."""
    out = io.BytesIO()
    Image.open(io.BytesIO(raw)).convert("RGB").save(out, "JPEG", quality=88)
    info = Image.open(io.BytesIO(out.getvalue())).info or {}
    return sorted(str(k) for k in info if k not in bench.ALLOWED_INFO_KEYS)


class TheAnswerIsCutOff(unittest.TestCase):
    def test_a_comfyui_graph_does_not_survive(self) -> None:
        """The real shape: civitai puts the whole workflow in the file."""
        raw = _loaded_png(
            prompt="a woman in a red dress",
            workflow=json.dumps(
                {"nodes": [{"type": "UNETLoader", "widgets_values": ["flux1-dev-fp8.safetensors"]}]}
            ),
        )
        assert _strip(raw) == []

    def test_the_OTHER_carrier_does_not_survive_either(self) -> None:
        """A second real shape, seen on a case pulled 2026-08-30: A1111 writes a
        `parameters` key instead of `workflow`. The guard is an allow-list for
        this reason — a deny-list would have let this one through."""
        raw = _loaded_png(parameters="Steps: 28, Sampler: DPM++ 2M, CFG scale: 3.5")
        assert _strip(raw) == []

    def test_A_CARRIER_NOBODY_ANTICIPATED_does_not_survive(self) -> None:
        """The point of an allow-list, stated as a test: a key invented tomorrow
        must fail closed, not pass unnoticed."""
        raw = _loaded_png(some_future_provenance_field="gemini-3-pro-image, seed 12345")
        assert _strip(raw) == []

    def test_THE_NEGATIVE_CONTROL_the_check_can_see_a_leak(self) -> None:
        """Rule I5, and the load-bearing one. Everything above asserts that a
        list is empty — which a broken reader also returns. This proves the
        reader sees provenance when it IS there."""
        raw = _loaded_png(prompt="a woman in a red dress", workflow="{}")
        carried = sorted(
            k for k in Image.open(io.BytesIO(raw)).info if k not in bench.ALLOWED_INFO_KEYS
        )
        assert carried == ["prompt", "workflow"], carried

    def test_the_gate_itself_passes_and_names_what_it_removed(self) -> None:
        out = bench.check()
        assert out["outcome"] == PASS, out["note"]
        assert out["before"] == ["prompt", "workflow"]
        assert out["after"] == []


class TheSample(unittest.TestCase):
    ROWS = [
        {
            "image_url": f"https://example.invalid/{i}.png",
            "base_model": model,
            "parameters": {"sampler": sampler, "steps": steps},
        }
        for i, (model, sampler, steps) in enumerate(
            [("Flux.1 S", "Euler", 4)] * 40
            + [("Flux.1 D", "DPM++ 2M", 30)] * 25
            + [("Wan Video 14B t2v", "UniPC", 15)] * 10
        )
    ]

    def test_the_sampler_case_does_not_split_a_configuration(self) -> None:
        """`Euler` and `euler` both occur in the real corpus. Treating them as
        two configurations would inflate the count and draw the same case
        twice."""
        upper = bench.config_of({"base_model": "X", "parameters": {"sampler": "Euler", "steps": 4}})
        lower = bench.config_of({"base_model": "X", "parameters": {"sampler": "euler", "steps": 4}})
        assert upper == lower

    def test_the_same_seed_draws_the_same_cases(self) -> None:
        """A bench whose sample moves cannot be used to re-test a claimed sign."""
        with mock.patch.object(bench, "_rows", lambda: list(self.ROWS)):
            first, second = bench.sample(20), bench.sample(20)
        assert [c["id"] for c in first["cases"]] == [c["id"] for c in second["cases"]]

    def test_every_configuration_is_represented_and_the_rest_is_held_back(self) -> None:
        """Stratified, not random: 40 of the 75 rows are one configuration, and a
        plain shuffle would spend the budget on it."""
        with mock.patch.object(bench, "_rows", lambda: list(self.ROWS)):
            out = bench.sample(20)
        assert out["configurations"] == 3
        assert len(out["cases"]) == 3 * bench.PER_CONFIG
        assert out["held_out"] == len(self.ROWS) - len(out["cases"])

    def test_an_absent_corpus_is_COULD_NOT_MEASURE(self) -> None:
        with mock.patch.object(bench, "CORPUS", Path("/nowhere/civitai.jsonl")):
            out = bench.sample(10)
        assert out["outcome"] not in (PASS, FAIL)
        assert out["checked"] == 0


if __name__ == "__main__":
    unittest.main()
