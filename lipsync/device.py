"""Какая карта под нами — и на что это влияет, кроме имени строки."""

from __future__ import annotations

import re

DEVICE_ORDER = ("cuda", "xpu", "mps", "cpu")

ONNX_PROVIDERS = {
    "cuda": ["CUDAExecutionProvider", "CPUExecutionProvider"],
    "xpu": ["OpenVINOExecutionProvider", "DmlExecutionProvider",
            "CPUExecutionProvider"],
    "mps": ["CoreMLExecutionProvider", "CPUExecutionProvider"],
    "cpu": ["CPUExecutionProvider"],
}

CPU_PROVIDER = "CPUExecutionProvider"

ONNX_ACCELERATORS = {
    dev: tuple(p for p in chain if p != CPU_PROVIDER)
    for dev, chain in ONNX_PROVIDERS.items()
}

TORCH_ABSENT = "absent"
TORCH_SILENT = "silent"
TORCH_OK = "ok"

INSIGHTFACE_GPU_DEVICES = ("cuda",)


def detect() -> str:
    """Какое устройство доступно torch прямо сейчас."""
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
        except Exception:  # noqa: BLE001 — бэкенд есть, но сломан: не наш
            continue
    return "cpu"


def dtype_for(device: str) -> str:
    """Тип данных под устройство, именем — чтобы попадало в JSON-отчёт."""
    return "float32" if device == "cpu" else "float16"


def onnx_providers(device: str, available: list | None = None) -> tuple:
    """(что просим, чего не хватает). Пустой второй — жаловаться не на что."""
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
    """ctx_id для insightface. -1 значит CPU, и это не всегда поражение."""
    return 0 if device in INSIGHTFACE_GPU_DEVICES else -1


def empty_cache(device: str | None = None) -> None:
    """Освободить кэш ускорителя, если у него такой есть."""
    try:
        import torch  # type: ignore
    except ImportError:
        return
    backend = getattr(torch, device or detect(), None)
    fn = getattr(backend, "empty_cache", None)
    if callable(fn):
        fn()


def torch_state(device: str | None = None) -> tuple:
    """(состояние, версия, имя устройства, причина отказа опроса)."""
    device = device or detect()
    try:
        import torch  # type: ignore
    except ImportError:
        return TORCH_ABSENT, "", "", ""
    except Exception as e:  # noqa: BLE001 — пакет на месте, но не грузится
        return TORCH_SILENT, "", "", f"{type(e).__name__}: {e}"
    try:
        version = str(getattr(torch, "__version__", ""))
        backend = getattr(torch, device, None)
    except Exception as e:  # noqa: BLE001 — битая сборка отвечает на атрибуты
        return TORCH_SILENT, "", "", f"{type(e).__name__}: {e}"
    reason = ""
    for attr in ("get_device_name", "get_device_properties"):
        fn = getattr(backend, attr, None)
        if not callable(fn):
            continue
        try:
            got = fn(0)
        except Exception as e:  # noqa: BLE001 — второй способ ещё может выжить
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
    """'13.0' -> (13, 0). Не число — None, а не ноль."""
    if not isinstance(text, str):
        return None
    m = re.match(r"\s*(\d+)(?:\.(\d+))?", text)
    if not m:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


def smi_cuda(text: str) -> str | None:
    """Версия CUDA из шапки nvidia-smi. Именно её поддерживает драйвер."""
    m = re.search(r"CUDA Version:\s*([0-9]+(?:\.[0-9]+)?)", text or "")
    return m.group(1) if m else None


def smi_cards(text: str) -> list:
    """Строки `--query-gpu=name,memory.total,driver_version --format=csv,noheader,nounits`."""
    cards = []
    for line in (text or "").splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3 or not parts[0] or parts[0].lower().startswith("name"):
            continue
        mib = version_pair(parts[1])
        cards.append({"name": parts[0],
                      "vram_gb": round(mib[0] * 1024 ** 2 / 1024 ** 3, 2)
                      if mib else None,
                      "driver": parts[2]})
    return cards


def smi_run(args: list, timeout: float = SMI_TIMEOUT_S) -> tuple:
    """(вывод, причина). Ровно одна из двух половин непустая."""
    import shutil
    import subprocess

    exe = shutil.which("nvidia-smi")
    if not exe:
        return "", "nvidia-smi не найден в PATH"
    try:
        r = subprocess.run([exe] + list(args), capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired:
        return "", (f"nvidia-smi не ответил за {timeout:.0f} c — обычно это "
                    f"повисший драйвер, а не медленная машина")
    except OSError as e:  # noqa: BLE001
        return "", f"nvidia-smi не запускается: {type(e).__name__}: {e}"
    if r.returncode != 0:
        return "", (f"nvidia-smi вернул {r.returncode}: "
                    f"{(r.stderr or r.stdout).strip().splitlines()[:1]}")
    return r.stdout, ""


def smi_probe(run=None) -> dict:
    """Что драйвер знает о карте: имя, память, версия драйвера и его CUDA."""
    run = run or smi_run
    csv_out, csv_why = run(["--query-gpu=name,memory.total,driver_version",
                            "--format=csv,noheader,nounits"])
    head_out, head_why = run([])
    cards = smi_cards(csv_out)
    cuda = smi_cuda(head_out)
    reason = ""
    if not cards and not cuda:
        reason = csv_why or head_why or "nvidia-smi ничего не сказал о картах"
    elif not cuda:
        reason = head_why or "в шапке nvidia-smi нет строки 'CUDA Version:'"
    return {"cards": cards, "cuda": cuda, "reason": reason}


def driver_covers(driver_cuda, build_cuda) -> str:
    """Потянет ли ДРАЙВЕР сборку torch. Четыре исхода, см. DRIVER_*."""
    d, b = version_pair(driver_cuda), version_pair(build_cuda)
    if d is None or b is None:
        return DRIVER_UNKNOWN
    if d[0] < b[0]:
        return DRIVER_OLD_MAJOR
    if d[0] > b[0]:
        return DRIVER_OK
    return DRIVER_OK if d[1] >= b[1] else DRIVER_OLD_MINOR


def torch_build_cuda():
    """С какой CUDA собран torch, по `torch.version.cuda`. None — ни с какой."""
    try:
        import torch  # type: ignore
    except Exception:  # noqa: BLE001 — нет пакета или битая сборка
        return ""
    try:
        return getattr(getattr(torch, "version", None), "cuda", None)
    except Exception:  # noqa: BLE001
        return ""


def describe(device: str | None = None) -> str:
    """Одна строка про то, на чём считаем — для шапки отчёта."""
    device = device or detect()
    state, version, name, reason = torch_state(device)
    line = f"устройство {device}" + (f" ({name})" if name else "")
    if state == TORCH_ABSENT:
        line += ", torch не установлен"
    elif state == TORCH_SILENT:
        line += (f", torch {version or 'неизвестной версии'} установлен, но "
                 f"устройство не опрашивается: {reason}")
    else:
        line += f", torch {version}"
    if device == "cuda" and state != TORCH_ABSENT:
        built = torch_build_cuda()
        if built:
            line += f", собран с CUDA {built}"
        elif built is None:
            line += (", СОБРАН БЕЗ CUDA (torch.version.cuda пуст) — эта сборка "
                     "карту не увидит никогда, её надо переставить")
    line += f", dtype {dtype_for(device)}"
    _, missing = onnx_providers(device)
    if missing:
        line += (f" | ускорения нет ни через один из: {', '.join(missing)} — "
                 f"insightface и DWPose пойдут на CPU")
    return line
