"""Pick the device the one local model runs on: ArcFace, through onnxruntime."""

from __future__ import annotations

#: CHOSEN, from the two contexts insightface actually distinguishes. Every
#: answer `detect` can give, best first — and the source it answers from, so
#: the set of answers is declared in one place rather than spelled out again at
#: each return. Only two entries, because only two are reachable:
#: `insightface_ctx` maps everything that is not CUDA onto the CPU context
#: anyway, so an `xpu`/`mps` answer would have changed nothing while reading as
#: a supported path.
DEVICE_ORDER = ("cuda", "cpu")

#: MEASURED 2026-08-27 against the installed onnxruntime 1.28.0: this spelling
#: is the one `onnxruntime.get_all_providers()` returns, so it is the provider
#: name the runtime answers to and not a name we invented for it. It is the
#: provider whose presence means the card is usable by the model we run.
CUDA_PROVIDER = "CUDAExecutionProvider"

#: CHOSEN, as the subset of `DEVICE_ORDER` that earns a non-negative ctx_id.
#: Kept as a set rather than an equality test so adding a second accelerated
#: device is one edit here instead of a new branch in `insightface_ctx`.
INSIGHTFACE_GPU_DEVICES = ("cuda",)


def detect() -> str:
    """Return the device the identity model can use right now.

    The question is put to onnxruntime rather than to torch, because
    onnxruntime is what executes ArcFace here. Torch was the oracle in the
    research tree, where it also did the sampling; in this product torch is not
    a dependency at all, so asking it answered "cpu" on every machine including
    one with a working card — a verdict about a package that was not there,
    not about the hardware.

    Example:
        >>> detect() in ("cuda", "cpu")
        True
    """
    try:
        import onnxruntime  # type: ignore
    except ImportError:
        return "cpu"
    try:
        available = list(onnxruntime.get_available_providers())
    except Exception:  # noqa: BLE001 — a broken install must not stop a run that can go on CPU
        return "cpu"
    return DEVICE_ORDER[0] if CUDA_PROVIDER in available else DEVICE_ORDER[-1]


def insightface_ctx(device: str) -> int:
    """Return the ctx_id for insightface. -1 means CPU, which is not always a defeat.

    Example:
        >>> insightface_ctx("cuda"), insightface_ctx("cpu")
        (0, -1)
    """
    return 0 if device in INSIGHTFACE_GPU_DEVICES else -1
