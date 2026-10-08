"""Скомпилированный план → граф ComfyUI API для MiniMax H3 reference-to-video со звуком.

Повторяет шаблон Comfy-Org `video_minimax_h3_r2v` (ComfyUI 0.35): R2V-кондиционинг,
BasicGuider, res_multistep, 20 шагов, декод видео и звука, mp4 24 fps.

Веса по умолчанию — полные int8 (`minimax_h3_ref2va_int8_convrot` + текстовый
энкодер int8). НАБЛЮДЕНО 2026-10-07 на RTX PRO 6000 (драйвер 595.91, CUDA 13.2):
5-секундный план 768×1344 за ~186 с. Pruned fp8 + nvfp4 остаются контрольным
набором; на A/B звук и картинка не отличались на слух владельца.

Realism-LoRA (fal) по умолчанию выключена. НАБЛЮДЕНО 2026-10-07, sk_R2 и sk_R5:
у Августа кожа почти та же, у Адгара крупный план замылился и поплыл глаз —
лок личности по рефу важнее «реализма» сверху.
"""

from __future__ import annotations

from typing import Any

from studio.shoot.compile import Compiled

UNET = "minimax_h3_ref2va_int8_convrot.safetensors"
CLIP = "qwen3vl_32b_minimax_h3_int8_convrot.safetensors"
VIDEO_VAE = "minimax_h3_video_vae_fp16.safetensors"
AUDIO_VAE = "minimax_h3_audio_vae_fp32.safetensors"
TURBO_LORA = "minimax_h3_ref2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors"
REALISM_LORA = "h3-realism-people-t2v-i2v-r2v.safetensors"
FPS = 24


def frames(seconds: float) -> int:
    """Длина в кадрах на сетке 17k+5, на которой H3 принимает латент."""
    n = max(5, round(seconds * FPS))
    return n + (5 - n % 17) % 17


def build(
    c: Compiled,
    prefix: str,
    *,
    uploaded: dict[str, str] | None = None,
    steps: int = 20,
    scheduler: str = "simple",
    realism: float = 0.0,
    turbo: bool = False,
    unet: str = UNET,
    clip: str = CLIP,
) -> dict[str, Any]:
    """`uploaded` — имя файла на сервере для каждого локального пути из `c.refs`."""
    up = uploaded or {}
    g: dict[str, Any] = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": unet, "weight_dtype": "default"}},
        "2": {
            "class_type": "CLIPLoader",
            "inputs": {"clip_name": clip, "type": "minimax", "device": "default"},
        },
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VIDEO_VAE}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": AUDIO_VAE}},
    }
    model: list[Any] = ["1", 0]
    if turbo:
        g["5"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": model, "lora_name": TURBO_LORA, "strength_model": 1.0},
        }
        model = ["5", 0]
    if realism:
        g["6"] = {
            "class_type": "LoraLoaderModelOnly",
            "inputs": {"model": model, "lora_name": REALISM_LORA, "strength_model": realism},
        }
        model = ["6", 0]
    cond: dict[str, Any] = {
        "clip": ["2", 0],
        "vae": ["3", 0],
        "audio_vae": ["4", 0],
        "prompt": c.prompt,
        "width": c.width,
        "height": c.height,
        "length": frames(c.seconds),
        "ref_image_size": "match",
    }
    for i, ref in enumerate(c.refs):
        node = f"2{i}0"
        g[node] = {"class_type": "LoadImage", "inputs": {"image": up.get(ref, ref)}}
        cond[f"ref_images.ref_image_{i}"] = [node, 0]
    g["10"] = {"class_type": "MiniMaxH3ReferenceToVideo", "inputs": cond}
    g["11"] = {"class_type": "BasicGuider", "inputs": {"model": model, "conditioning": ["10", 0]}}
    g["12"] = {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "res_multistep"}}
    g["13"] = {
        "class_type": "BasicScheduler",
        "inputs": {"model": model, "scheduler": scheduler, "steps": steps, "denoise": 1.0},
    }
    g["14"] = {"class_type": "RandomNoise", "inputs": {"noise_seed": c.seed}}
    g["15"] = {
        "class_type": "SamplerCustomAdvanced",
        "inputs": {
            "noise": ["14", 0],
            "guider": ["11", 0],
            "sampler": ["12", 0],
            "sigmas": ["13", 0],
            "latent_image": ["10", 1],
        },
    }
    g["16"] = {"class_type": "VAEDecode", "inputs": {"samples": ["15", 0], "vae": ["3", 0]}}
    g["17"] = {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["15", 0], "vae": ["4", 0]}}
    g["18"] = {
        "class_type": "CreateVideo",
        "inputs": {"images": ["16", 0], "audio": ["17", 0], "fps": FPS},
    }
    g["19"] = {
        "class_type": "SaveVideo",
        "inputs": {
            "video": ["18", 0],
            "filename_prefix": prefix,
            "format": "mp4",
            "codec": "auto",
        },
    }
    return g
