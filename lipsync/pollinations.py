"""Pollinations — the one gateway (gen.pollinations.ai) for every picture.

Three routes out and one upload, and that is the whole door: `upload` puts a
local file where the gateway can fetch it, `images_edit` redraws one reference,
`compose` redraws two or more. Video does not come through here — Kling Motion
Control through fal.ai makes it — and neither does frame extraction, judging or
speech.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path
from urllib.parse import quote

from . import cure, fork_plan


#: The one default frame every image route asks for: `fork_plan.FRAME`, taken
#: rather than restated. A size that is 9:16 only in arithmetic is not enough —
#: the model MEASURABLY snaps each side to a 16px grid (asked 768x1024, it
#: returned 896x1200), so an off-grid request comes back moved sideways and no
#: longer 9:16, and a frame that is not 9:16 is padded with blurred bands on its
#: way to the client. The delivery frame satisfies both, and taking it from the
#: plan means no route can drift away from it one route at a time, which is how
#: the 3:4 default outlived its removal on `compose` alone.
#:
#: This gateway imports the domain module for it, which points the wrong way
#: across the layers. It is deliberate: the frame is one product fact and it is
#: measured on what the pipeline delivers, so the plan owns it and this module
#: reads it. Hiding it in a neutral leaf module would satisfy the layering and
#: cost the pipeline the single place to look. The edge is safe in practice —
#: `fork_plan` reaches this module only from inside a function, so there is no
#: import cycle, and it pulls in no third-party import at module level.
PLAN_SIZE = fork_plan.FRAME


#: `image` — text to picture, with no reference — has no caller on the paid
#: path: every product picture starts from a photo, so it goes through
#: `images_edit` or `compose`. It is kept and declared because two gates measure
#: it: `test_route_defaults` and `test_fork_e2e` read the default size of all
#: three routes and fail when they disagree. That check is the reason the 3:4
#: default was found on `compose` alone, and it needs a third route to compare
#: against — a route with no caller is exactly what makes the disagreement
#: visible. Delete it and the comparison has two samples instead of three.
INSTRUMENTS = ("image",)


def _base() -> str:
    return os.environ.get("POLLINATIONS_BASE", "https://gen.pollinations.ai").rstrip("/")


def _media() -> str:
    return os.environ.get("POLLINATIONS_MEDIA", "https://media.pollinations.ai").rstrip("/")


def _key() -> str:
    """Return the gateway key, or say how to set it in the shell that is reading.

    The remedy is built by `cure.set_env` rather than written out here: the
    command differs between shells, and a POSIX `export` line printed on
    Windows is a remedy the reader cannot run.
    """
    k = os.environ.get("POLLINATIONS_API_KEY")
    if not k:
        raise RuntimeError(
            "POLLINATIONS_API_KEY not set (sk_ key from enter.pollinations.ai). "
            f"Set it with: {cure.set_env('POLLINATIONS_API_KEY', 'sk_...')}"
        )
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
    width: int = PLAN_SIZE[0],
    height: int = PLAN_SIZE[1],
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
    width: int = PLAN_SIZE[0],
    height: int = PLAN_SIZE[1],
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
    width: int = PLAN_SIZE[0],
    height: int = PLAN_SIZE[1],
    seed: int = 0,
) -> str:
    """Generate from SEVERAL reference images at once. [verified live]

    The default is `PLAN_SIZE`, shared with `image` and `images_edit`. It used
    to be 768x1024 here alone, and that 3:4 was the real reason the styled
    reference arrived letterboxed: two references route here while one routes to
    `images_edit`, so the route choice — not the prompt — decided whether the
    frame came back vertical. The size now lives in one place so a route cannot
    drift away from its siblings again. Callers wanting another frame pass their
    own size; the pipeline's own routes do not — they all ask for one frame.
    """
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
        raise RuntimeError(f"compose: HTTP {r.status_code} {r.text}")
    if "image" not in r.headers.get("content-type", ""):
        raise RuntimeError(
            f"compose: expected image bytes, got {r.headers.get('content-type')}: {r.text!r}"
        )
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(r.content)
    return str(out_path)
