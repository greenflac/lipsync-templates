"""Identify which card we are running on — and what that affects beyond the name string."""

from __future__ import annotations

import re

DEVICE_ORDER = ("cuda", "xpu", "mps", "cpu")

ONNX_PROVIDERS = {
    "cuda": ["CUDAExecutionProvider", "CPUExecutionProvider"],
    "xpu": ["OpenVINOExecutionProvider", "DmlExecutionProvider", "CPUExecutionProvider"],
    "mps": ["CoreMLExecutionProvider", "CPUExecutionProvider"],
    "cpu": ["CPUExecutionProvider"],
}

CPU_PROVIDER = "CPUExecutionProvider"

ONNX_ACCELERATORS = {
    dev: tuple(p for p in chain if p != CPU_PROVIDER) for dev, chain in ONNX_PROVIDERS.items()
}

TORCH_ABSENT = "absent"
TORCH_SILENT = "silent"
TORCH_OK = "ok"

INSIGHTFACE_GPU_DEVICES = ("cuda",)


def detect() -> str:
    """Return the device torch can use right now."""
    try:
        import torch  # type: ignore
    except ImportError:
        return "cpu"
    for name in DEVICE_ORDER:
        if name == "cpu":
            continue
        backend = getattr(torch, name, None)
        try:
            if backend is not None and backend.is_available():
                return name
        except Exception:  # noqa: BLE001 — the backend exists but is broken; not ours to fix
            continue
    return "cpu"


def dtype_for(device: str) -> str:
    """Return the dtype for the device, by name so it fits into the JSON report."""
    return "float32" if device == "cpu" else "float16"


def onnx_providers(device: str, available: list | None = None) -> tuple:
    """Return (what we request, what is missing). An empty second half means nothing to complain about."""
    want = ONNX_PROVIDERS.get(device, ONNX_PROVIDERS["cpu"])
    if available is None:
        try:
            import onnxruntime  # type: ignore

            available = list(onnxruntime.get_available_providers())
        except ImportError:
            available = []
    alternatives = ONNX_ACCELERATORS.get(device, ())
    if any(p in available for p in alternatives):
        return tuple(want), ()
    return tuple(want), tuple(alternatives)


def insightface_ctx(device: str) -> int:
    """Return the ctx_id for insightface. -1 means CPU, which is not always a defeat."""
    return 0 if device in INSIGHTFACE_GPU_DEVICES else -1


def empty_cache(device: str | None = None) -> None:
    """Release the accelerator cache, if the accelerator has one."""
    try:
        import torch  # type: ignore
    except ImportError:
        return
    backend = getattr(torch, device or detect(), None)
    fn = getattr(backend, "empty_cache", None)
    if callable(fn):
        fn()


def torch_state(device: str | None = None) -> tuple:
    """Return (state, version, device name, reason the query failed)."""
    device = device or detect()
    try:
        import torch  # type: ignore
    except ImportError:
        return TORCH_ABSENT, "", "", ""
    except Exception as e:  # noqa: BLE001 — the package is present but fails to load
        return TORCH_SILENT, "", "", f"{type(e).__name__}: {e}"
    try:
        version = str(getattr(torch, "__version__", ""))
        backend = getattr(torch, device, None)
    except Exception as e:  # noqa: BLE001 — a broken build can throw on attribute access
        return TORCH_SILENT, "", "", f"{type(e).__name__}: {e}"
    reason = ""
    for attr in ("get_device_name", "get_device_properties"):
        fn = getattr(backend, attr, None)
        if not callable(fn):
            continue
        try:
            got = fn(0)
        except Exception as e:  # noqa: BLE001 — the second method may still survive
            reason = reason or f"{type(e).__name__}: {e}"
            continue
        name = got if isinstance(got, str) else getattr(got, "name", "")
        return TORCH_OK, version, str(name or ""), ""
    if reason:
        return TORCH_SILENT, version, "", reason
    return TORCH_OK, version, "", ""


SMI_TIMEOUT_S = 10

DRIVER_OK = "ok"
DRIVER_OLD_MAJOR = "old_major"
DRIVER_OLD_MINOR = "old_minor"
DRIVER_UNKNOWN = "unknown"


def version_pair(text) -> tuple | None:
    """Turn '13.0' into (13, 0). A non-number gives None, not zero."""
    if not isinstance(text, str):
        return None
    m = re.match(r"\s*(\d+)(?:\.(\d+))?", text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


def smi_cuda(text: str) -> str | None:
    """Return the CUDA version from the nvidia-smi header. That is the one the driver supports."""
    m = re.search(r"CUDA Version:\s*([0-9]+(?:\.[0-9]+)?)", text or "")
    return m.group(1) if m else None


def smi_cards(text: str) -> list:
    """Parse lines of `--query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits`."""
    cards = []
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3 or not parts[0] or parts[0].lower().startswith("name"):
            continue
        mib = version_pair(parts[1])
        cards.append(
            {
                "name": parts[0],
                "vram_gb": round(mib[0] * 1024**2 / 1024**3, 2) if mib else None,
                "driver": parts[2],
            }
        )
    return cards


def smi_run(args: list, timeout: float = SMI_TIMEOUT_S) -> tuple:
    """Return (output, reason). Exactly one of the two halves is non-empty."""
    import shutil
    import subprocess

    exe = shutil.which("nvidia-smi")
    if not exe:
        return "", "nvidia-smi not found in PATH"
    try:
        r = subprocess.run([exe] + list(args), capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return "", (
            f"nvidia-smi did not answer within {timeout:.0f} s — usually a "
            f"hung driver, not a slow machine"
        )
    except OSError as e:  # noqa: BLE001
        return "", f"nvidia-smi fails to start: {type(e).__name__}: {e}"
    if r.returncode != 0:
        return "", (
            f"nvidia-smi returned {r.returncode}: {(r.stderr or r.stdout).strip().splitlines()[:1]}"
        )
    return r.stdout, ""


def smi_probe(run=None) -> dict:
    """Return what the driver knows about the card: name, memory, driver version and its CUDA."""
    run = run or smi_run
    csv_out, csv_why = run(
        ["--query-gpu=name,memory.total,driver_version", "--format=csv,noheader,nounits"]
    )
    head_out, head_why = run([])
    cards = smi_cards(csv_out)
    cuda = smi_cuda(head_out)
    reason = ""
    if not cards and not cuda:
        reason = csv_why or head_why or "nvidia-smi said nothing about the cards"
    elif not cuda:
        reason = head_why or "the nvidia-smi header has no 'CUDA Version:' line"
    return {"cards": cards, "cuda": cuda, "reason": reason}


def driver_covers(driver_cuda, build_cuda) -> str:
    """Tell whether the driver covers the torch build. Four outcomes, see DRIVER_*."""
    d, b = version_pair(driver_cuda), version_pair(build_cuda)
    if d is None or b is None:
        return DRIVER_UNKNOWN
    if d[0] < b[0]:
        return DRIVER_OLD_MAJOR
    if d[0] > b[0]:
        return DRIVER_OK
    return DRIVER_OK if d[1] >= b[1] else DRIVER_OLD_MINOR


def torch_build_cuda():
    """Return the CUDA version torch was built with, per `torch.version.cuda`. None means built with none."""
    try:
        import torch  # type: ignore
    except Exception:  # noqa: BLE001 — no package, or a broken build
        return ""
    try:
        return getattr(getattr(torch, "version", None), "cuda", None)
    except Exception:  # noqa: BLE001
        return ""


def describe(device: str | None = None) -> str:
    """Return a one-line summary of what we compute on — for the report header."""
    device = device or detect()
    state, version, name, reason = torch_state(device)
    line = f"device {device}" + (f" ({name})" if name else "")
    if state == TORCH_ABSENT:
        line += ", torch is not installed"
    elif state == TORCH_SILENT:
        line += (
            f", torch {version or 'of unknown version'} is installed, but "
            f"the device cannot be queried: {reason}"
        )
    else:
        line += f", torch {version}"
    if device == "cuda" and state != TORCH_ABSENT:
        built = torch_build_cuda()
        if built:
            line += f", built with CUDA {built}"
        elif built is None:
            line += (
                ", built WITHOUT CUDA (torch.version.cuda is empty) — this build "
                "will never see the card and must be reinstalled"
            )
    line += f", dtype {dtype_for(device)}"
    _, missing = onnx_providers(device)
    if missing:
        line += (
            f" | no acceleration through any of: {', '.join(missing)} — "
            f"insightface and DWPose will run on CPU"
        )
    return line
