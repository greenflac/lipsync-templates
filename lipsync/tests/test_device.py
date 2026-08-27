"""Test the device choice — above all, the silent fallback to CPU.

WHY this file shrank on 2026-08-27: everything it used to cover (the nvidia-smi
probe, the driver-versus-build comparison, the torch three-state report, the
onnx provider chains, the report header) served `preflight_gpu.py`, a GPU
doctor that belongs to the research stack and did not cross into this product.
Its code is gone, so its tests are gone with it. What is left is the pair the
product actually calls, from `identity_arcface.py`, and the defect that pair
carried.

Expected values here are literals. Importing them from `device` would let the
module move and these tests follow it in silence.
"""

from __future__ import annotations

import sys
import types
import unittest

from lipsync import device

# The two answers the product can act on, written out rather than imported.
CUDA, CPU = "cuda", "cpu"

# The ctx_id insightface reads: a non-negative number is a GPU index, -1 is CPU.
GPU_CTX, CPU_CTX = 0, -1

# The provider name onnxruntime reports when the card is usable by the model.
CUDA_PROVIDER_NAME = "CUDAExecutionProvider"
CPU_PROVIDER_NAME = "CPUExecutionProvider"


def _install(case: unittest.TestCase, name: str, module) -> None:
    """Install a module for one test and put sys.modules back afterwards."""
    had = name in sys.modules
    saved = sys.modules.get(name)
    sys.modules[name] = module

    def restore() -> None:
        if had:
            sys.modules[name] = saved  # type: ignore[assignment]
        else:
            sys.modules.pop(name, None)

    case.addCleanup(restore)


def _fake_onnxruntime(providers, boom=None):
    ort = types.ModuleType("onnxruntime")

    def get_available_providers():
        if boom is not None:
            raise boom
        return list(providers)

    setattr(ort, "get_available_providers", get_available_providers)
    return ort


class TheRuntimeThatRunsTheModelIsTheOneAsked(unittest.TestCase):
    """MEASURED defect: with torch as the oracle this answered `cpu` everywhere.

    `torch` is not a dependency of this product — it was never declared and is
    not installed by `pip install .`. `detect` imported it, caught the
    ImportError and returned "cpu", so ArcFace was pinned to the CPU context on
    every machine, including one whose onnxruntime reports a CUDA provider.
    The verdict described a missing package, not the hardware.
    """

    def test_a_cuda_provider_is_answered_with_cuda(self) -> None:
        _install(self, "onnxruntime", _fake_onnxruntime([CUDA_PROVIDER_NAME, CPU_PROVIDER_NAME]))
        self.assertEqual(device.detect(), CUDA)

    def test_the_old_oracle_no_longer_decides_the_answer(self) -> None:
        """The negative control on the fix: torch absent, card present."""
        _install(self, "torch", None)
        _install(self, "onnxruntime", _fake_onnxruntime([CUDA_PROVIDER_NAME, CPU_PROVIDER_NAME]))
        self.assertEqual(device.detect(), CUDA)

    def test_a_torch_that_sees_a_card_does_not_override_the_runtime(self) -> None:
        """And the control the other way: torch present and happy, runtime is not."""
        torch = types.ModuleType("torch")
        setattr(torch, "cuda", types.SimpleNamespace(is_available=lambda: True))
        _install(self, "torch", torch)
        _install(self, "onnxruntime", _fake_onnxruntime([CPU_PROVIDER_NAME]))
        self.assertEqual(device.detect(), CPU)

    def test_cpu_only_providers_are_answered_with_cpu(self) -> None:
        _install(self, "onnxruntime", _fake_onnxruntime([CPU_PROVIDER_NAME]))
        self.assertEqual(device.detect(), CPU)

    def test_a_foreign_accelerator_is_not_taken_for_cuda(self) -> None:
        _install(self, "onnxruntime", _fake_onnxruntime(["AzureExecutionProvider"]))
        self.assertEqual(device.detect(), CPU)

    def test_an_absent_runtime_falls_back_rather_than_raising(self) -> None:
        _install(self, "onnxruntime", None)
        self.assertEqual(device.detect(), CPU)

    def test_a_broken_runtime_falls_back_rather_than_raising(self) -> None:
        """A install that imports and then throws must not stop a CPU run."""
        _install(self, "onnxruntime", _fake_onnxruntime([], boom=OSError("libcudart.so.12")))
        self.assertEqual(device.detect(), CPU)

    def test_detection_always_names_something_the_caller_can_act_on(self) -> None:
        self.assertIn(device.detect(), (CUDA, CPU))


class TheCtxIdSaysCpuRatherThanADeviceInsightfaceCannotUse(unittest.TestCase):
    def test_cuda_gets_the_first_gpu(self) -> None:
        self.assertEqual(device.insightface_ctx(CUDA), GPU_CTX)

    def test_cpu_gets_minus_one(self) -> None:
        self.assertEqual(device.insightface_ctx(CPU), CPU_CTX)

    def test_anything_it_cannot_use_gets_minus_one_too(self) -> None:
        """Negative control: an unknown name must not fall through to a GPU index."""
        for name in ("xpu", "mps", "rocm", "", "CUDA"):
            with self.subTest(device=name):
                self.assertEqual(device.insightface_ctx(name), CPU_CTX)

    def test_the_order_prefers_the_accelerator_and_ends_on_the_fallback(self) -> None:
        self.assertEqual(device.DEVICE_ORDER[0], CUDA)
        self.assertEqual(device.DEVICE_ORDER[-1], CPU)

    def test_every_name_the_order_offers_maps_to_a_ctx_id(self) -> None:
        """Three outcomes: mapped / mapped to the wrong kind / not mappable."""
        checked, wrong, unmappable = 0, [], []
        for name in device.DEVICE_ORDER:
            try:
                ctx = device.insightface_ctx(name)
            except Exception as exc:  # noqa: BLE001 — an unmappable name is its own outcome
                unmappable.append(f"{name}: {type(exc).__name__}")
                continue
            checked += 1
            if ctx not in (GPU_CTX, CPU_CTX):
                wrong.append(f"{name}={ctx}")
        verdict = (
            f"checked {checked}, wrong {len(wrong)}, unmappable {len(unmappable)}: "
            f"{wrong or unmappable}"
        )
        self.assertEqual(len(unmappable), 0, verdict)
        self.assertEqual(checked, len(device.DEVICE_ORDER), verdict)
        self.assertEqual(len(wrong), 0, verdict)


class TheDiagnosticBranchIsGoneAndStaysGone(unittest.TestCase):
    """The GPU doctor's names must not creep back in one function at a time.

    Each of these served `preflight_gpu.py` in the research tree. That module
    is not part of this product; a name that comes back without it is dead
    weight that reads as a decision.
    """

    REMOVED = (
        "describe",
        "torch_state",
        "torch_build_cuda",
        "dtype_for",
        "onnx_providers",
        "smi_probe",
        "smi_run",
        "smi_cards",
        "smi_cuda",
        "driver_covers",
        "version_pair",
        "empty_cache",
    )

    def test_none_of_them_is_back(self) -> None:
        back = [name for name in self.REMOVED if hasattr(device, name)]
        self.assertEqual(
            back,
            [],
            f"checked {len(self.REMOVED)}, back {len(back)}: {back}",
        )

    def test_the_sweep_can_see_a_name_that_is_present(self) -> None:
        """Negative control: the check above must be able to say yes."""
        self.assertTrue(hasattr(device, "detect"))


if __name__ == "__main__":
    unittest.main()


class EveryDecisionConstantDeclaresWhereItCameFrom(unittest.TestCase):
    """A chosen number handed over as a measured one is a number nobody dares move.

    This reads the module text on purpose, and it is not the "grep the source
    for a word and call it a behaviour check" defect: provenance lives in a
    comment and has no runtime shadow at all, so the text is the only place
    the claim exists. What the constants DO is guarded by the tests above.
    """

    def test_the_three_device_constants_carry_a_provenance_mark(self):
        import re
        from pathlib import Path

        from lipsync import device as dv

        from lipsync.tests.test_fork_finish import PROVENANCE_MARKS, provenance_block

        src = Path(dv.__file__).read_text(encoding="utf-8")
        for name in ("DEVICE_ORDER", "CUDA_PROVIDER", "INSIGHTFACE_GPU_DEVICES"):
            with self.subTest(constant=name):
                # A word boundary is required: a bare substring test would take
                # the "MEASURED" inside "UNMEASURED" for a provenance mark.
                above = provenance_block(src, name)
                self.assertTrue(
                    any(re.search(rf"\b{m}\b", above) for m in PROVENANCE_MARKS),
                    f"{name}: provenance not marked",
                )
