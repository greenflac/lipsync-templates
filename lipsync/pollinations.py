"""Pollinations — ONE gateway (gen.pollinations.ai) for the whole pipeline."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from urllib.parse import quote


def _base() -> str:
    return os.environ.get("POLLINATIONS_BASE", "https://gen.pollinations.ai").rstrip("/")


def _media() -> str:
    return os.environ.get("POLLINATIONS_MEDIA", "https://media.pollinations.ai").rstrip("/")


def _key() -> str:
    k = os.environ.get("POLLINATIONS_API_KEY")
    if not k:
        raise RuntimeError("POLLINATIONS_API_KEY not set (sk_ key from enter.pollinations.ai).")
    return k


def _auth() -> dict:
    return {"Authorization": f"Bearer {_key()}"}


def upload(path: str | Path) -> str:
    """Upload a local file and return its public media URL. [verified live]"""
    import requests

    with open(path, "rb") as fh:
        r = requests.post(f"{_media()}/upload", headers=_auth(), files={"file": fh}, timeout=180)
    r.raise_for_status()
    data = r.json()
    url = data.get("url") or (f"{_media()}/{data['id']}" if data.get("id") else None)
    if not url:
        raise RuntimeError(f"upload: no url/id in response: {list(data.keys())}")
    return url


def image(
    prompt: str,
    out_path: str | Path,
    *,
    model: str = "flux",
    seed: int = 0,
    width: int = 1080,
    height: int = 1920,
    image_url: str | None = None,
) -> str:
    """Generate a still (text->image). Returns image bytes synchronously."""
    import requests

    url = f"{_base()}/image/" + quote(prompt, safe="")
    params: dict[str, str | int] = {
        "model": model,
        "seed": seed,
        "width": width,
        "height": height,
    }
    if image_url:
        params["image"] = image_url
    r = requests.get(url, params=params, headers=_auth(), timeout=300)
    r.raise_for_status()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)
    return str(out_path)


def images_edit(
    prompt: str,
    ref_path: str | Path,
    out_path: str | Path,
    *,
    model: str = "kontext",
    width: int = 1080,
    height: int = 1920,
) -> str:
    """Image-to-image from a LOCAL reference, no media host needed. [verified live]"""
    import requests

    with open(ref_path, "rb") as fh:
        r = requests.post(
            f"{_base()}/v1/images/edits",
            headers=_auth(),
            data={"model": model, "prompt": prompt, "size": f"{width}x{height}"},
            files={"image": (Path(ref_path).name, fh, "image/jpeg")},
            timeout=300,
        )
    r.raise_for_status()
    item = r.json()["data"][0]
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if item.get("b64_json"):
        out_path.write_bytes(base64.b64decode(item["b64_json"]))
    elif item.get("url"):
        img = requests.get(item["url"], headers=_auth(), timeout=180)
        img.raise_for_status()
        out_path.write_bytes(img.content)
    else:
        raise RuntimeError(f"images_edit: no b64_json/url in response: {item.keys()}")
    return str(out_path)


def compose(
    prompt: str,
    image_urls: list[str],
    out_path: str | Path,
    *,
    model: str = "nanobanana",
    width: int = 768,
    height: int = 1024,
    seed: int = 0,
) -> str:
    """Generate from SEVERAL reference images at once. [verified live]"""
    import requests

    if len(image_urls) < 2:
        raise ValueError("compose() is for 2+ references; use images_edit/image for a single one.")
    url = f"{_base()}/image/" + quote(prompt, safe="")
    r = requests.get(
        url,
        params=dict[str, str | int](
            model=model,
            image="|".join(image_urls),
            width=width,
            height=height,
            seed=seed,
        ),
        headers=_auth(),
        timeout=600,
    )
    if not r.ok:
        raise RuntimeError(f"compose: HTTP {r.status_code} {r.text[:300]}")
    if "image" not in r.headers.get("content-type", ""):
        raise RuntimeError(
            f"compose: expected image bytes, got {r.headers.get('content-type')}: {r.text[:200]!r}"
        )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)
    return str(out_path)


def video(
    prompt: str,
    out_mp4: str | Path,
    *,
    model: str = "seedance-2.0",
    image_url: str | list[str] | None = None,
    duration: int = 4,
    aspect_ratio: str = "9:16",
    audio: bool = False,
    resolution: str | None = None,
    seed: int | None = None,
) -> str:
    """Image-to-video: the start frame drives the motion."""
    import requests

    url = f"{_base()}/video/" + quote(prompt, safe="")
    params: dict[str, str | int] = {
        "model": model,
        "duration": duration,
        "aspectRatio": aspect_ratio,
        "audio": str(audio).lower(),
    }
    if image_url:
        params["image"] = image_url if isinstance(image_url, str) else "|".join(image_url)
    if resolution:
        params["resolution"] = resolution
    if seed is not None:
        params["seed"] = seed
    r = requests.get(url, params=params, headers=_auth(), timeout=900)
    if not r.ok:
        raise RuntimeError(f"video: HTTP {r.status_code} {r.text[:300]}")
    ct = r.headers.get("content-type", "")
    if "video" not in ct and "octet-stream" not in ct:
        raise RuntimeError(
            f"video: expected mp4 bytes, got {ct}: {r.text[:200]!r}. "
            f"If this is a job/URL JSON, add a poll+download branch here."
        )
    out_mp4 = Path(out_mp4)
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    out_mp4.write_bytes(r.content)
    LAST_VIDEO_USAGE.clear()
    LAST_VIDEO_USAGE.update(_usage_of(r))
    return str(out_mp4)


LAST_VIDEO_USAGE: dict = {}


def _usage_of(r) -> dict:
    """Pull the metering headers off a generation response, for the run report."""
    keep = (
        "x-usage-completion-video-seconds",
        "x-model-used",
        "x-request-id",
        "x-usage-completion-audio-seconds",
        "x-cache",
    )
    out = {k: v for k, v in ((k, r.headers.get(k)) for k in keep) if v}
    secs = out.get("x-usage-completion-video-seconds")
    if secs:
        try:
            out["video_seconds"] = float(secs)
        except ValueError:
            pass
    return out


def video_loop(prompt: str, out_mp4: str | Path, start_url: str, **kwargs) -> str:
    """A clip that ends where it began, so it loops without a visible cut."""
    return video(prompt, out_mp4, image_url=[start_url, start_url], **kwargs)


FRAME_PATTERN = "%04d.png"


def frame_names_sort_correctly(count: int, pattern: str = FRAME_PATTERN) -> bool:
    """Tell whether the lexicographic order of names matches the frame order."""
    names = [pattern % i for i in range(1, count + 1)]
    return sorted(names) == names


def extract_frames(mp4_path: str | Path, out_dir: str | Path, *, fps: int = 6) -> list[str]:
    """mp4 -> NNNN.png sequence via ffmpeg, so identity/motion can be measured."""
    import subprocess

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp4_path), "-vf", f"fps={fps}", str(out_dir / FRAME_PATTERN)],
        check=True,
        capture_output=True,
    )
    return sorted(str(p) for p in out_dir.glob("*.png"))


def chat(messages: list[dict], *, model: str = "openai", temperature: float = 0.0) -> str:
    import requests

    r = requests.post(
        f"{_base()}/v1/chat/completions",
        headers=_auth(),
        json={"model": model, "temperature": temperature, "messages": messages},
        timeout=300,
    )
    r.raise_for_status()
    return r.json()["choices"][0]["message"]["content"]


JUDGE_SYSTEM = (
    "You score one vertical 9:16 ad frame. Return STRICT JSON only with keys: "
    '"first_frame_hook","trend_fit","composition","brand_safety" (0-1), '
    '"transcribed_text" (verbatim on-image words or empty), "opinion" (0-1).'
)


def judge_frame(frame_path: str | Path, *, model: str = "claude") -> dict:
    b64 = base64.b64encode(Path(frame_path).read_bytes()).decode("ascii")
    content = chat(
        [
            {"role": "system", "content": JUDGE_SYSTEM},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Score this frame. JSON only."},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{b64}"}},
                ],
            },
        ],
        model=model,
    )
    return _parse_json(content)


def opinion_of(frame_path: str | Path, *, model: str = "claude") -> float:
    return float(judge_frame(frame_path, model=model).get("opinion", 0.0))


def tts(
    text: str, out_path: str | Path, *, voice: str = "nova", model: str = "eleven-multilingual-v2"
) -> str:
    """Russian TTS -> mp3. Language lives here; a lipsync model consumes the wav."""
    import requests

    url = f"{_base()}/audio/" + quote(text, safe="")
    r = requests.get(url, params={"voice": voice, "model": model}, headers=_auth(), timeout=300)
    r.raise_for_status()
    out_path = Path(out_path)
    out_path.write_bytes(r.content)
    return str(out_path)


def _parse_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`")
    s, e = text.find("{"), text.rfind("}")
    if s == -1 or e == -1:
        raise ValueError(f"model returned no JSON: {text[:120]!r}")
    return json.loads(text[s : e + 1])
