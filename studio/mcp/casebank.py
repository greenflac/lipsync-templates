"""Build a case bank: creatives whose origin is known, with the origin cut off.

A case is a picture or a clip handed to a reader that has NO access to the
answer, plus a truth record kept somewhere the reader cannot reach. The reader
guesses; only afterwards is the truth revealed, and the question that matters is
what OBSERVABLE sign would have told it.

WHY THE READER IS A SEPARATE AGENT AND NOT WHOEVER BUILT THIS

Because the person who assembled the bank has seen the answers. Blindness by
promise is not blindness. A fresh agent handed a file path cannot leak what it
was never given, and that is the only guarantee worth having (rule I1).

THE TWO SOURCES, AND WHY THESE

`kling` — 9001 rows of the PLATFORM'S OWN SERVER-SIDE TASK LOG. Not an
uploader's caption: the vendor's record of what it executed. MEASURED
2026-08-30, it carries per item the prompt, the negative prompt, cfg, duration,
camera_json, the task type, the internal engine name, and `kling_version` — 1.0
(3028), 1.5 (4160), 1.6 (95). It also carries the USER'S OWN VERDICT on the
result: 1736 like, 118 dislike, 7147 unrated, with reason tags. That last column
is applicability data, which this project has none of. And 211 of the tasks are
`m2v_video_lip_sync` — our own product.

`openfake` — 80 generators including the closed models our questions are about:
veo-3, kling, midjourney-7, nano-banana-pro, gpt-image-2.0, seedream. Its truth
is the authors' own generation pipeline.

NON-COMMERCIAL IS CARRIED, NOT DROPPED

The owner's ruling 2026-08-30: non-commercial material is processed, and named
in the verdict. So the licence is not a field somebody might read — it changes
the SHAPE of the report. Every case carries `commercial_ok`, the scorer reports
the two populations apart, and a verdict computed over any restricted case must
say so at the top. That is a gate below, not a promise here.

OpenFake's own card contradicts itself on this: the machine field says
`cc-by-nc-4.0` and the prose says `CC-BY-SA-4.0` with proprietary subsets
non-commercial. Believing the evidence over the label (rule E2), the stricter
one wins and every OpenFake case is marked restricted.
"""

from __future__ import annotations

import io
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]

#: A browser agent. ИЗМЕРЕНО 2026-08-30: Python's urllib is refused 403 by
#: image.civitai.com on every try; curl introducing itself gets 200 in 0.77 s.
#: The host is open — it just declines to talk to a library that does not say
#: who it is. This is a header, not a way around a refusal (rule C3).
USER_AGENT = "Mozilla/5.0"

#: Metadata a re-encode is allowed to leave behind. Everything else is treated
#: as a leak, so a carrier nobody anticipated fails closed.
ALLOWED_INFO_KEYS = frozenset({"jfif", "jfif_version", "jfif_unit", "jfif_density", "dpi"})


@dataclass(frozen=True)
class Source:
    """Where cases come from, and under what terms."""

    key: str
    licence: str
    commercial_ok: bool
    why_evidence: str
    media: str  # "image" | "video"


SOURCES: dict[str, Source] = {
    "kling": Source(
        key="kling",
        licence="cc-by-4.0 (bitmind/klingai-videos)",
        commercial_ok=True,
        why_evidence=(
            "серверная запись задачи самой площадки Kling: prompt, negative_prompt, cfg, "
            "duration, camera_json, kling_version. Это лог исполнения на стороне вендора, "
            "а не подпись загрузчика"
        ),
        media="video",
    ),
    "openfake": Source(
        key="openfake",
        licence="cc-by-nc-4.0 (машинное поле карточки; текст той же карточки говорит "
        "CC-BY-SA-4.0 — по Е2 верим строгому)",
        commercial_ok=False,
        why_evidence=(
            "собственная генерация авторов по общему банку промтов через API каждого "
            "провайдера; сами авторы оговаривают, что метки назначены пайплайном и не "
            "выверены человеком поштучно"
        ),
        media="image",
    ),
}

KLING_META = (
    "https://huggingface.co/datasets/bitmind/klingai-videos/resolve/main/video_metadata.parquet"
)
KLING_BATCH = "https://huggingface.co/datasets/bitmind/klingai-videos/resolve/main/{batch}/{name}"


def _curl(url: str, *, ranged: tuple[int, int] | None = None, timeout: int = 120) -> bytes:
    """Fetch bytes with a browser agent, optionally a byte range."""
    command = ["curl", "-sL", "-A", USER_AGENT, "--max-time", str(timeout)]
    if ranged is not None:
        command += ["-r", f"{ranged[0]}-{ranged[1]}"]
    command.append(url)
    done = subprocess.run(command, capture_output=True, check=False)
    if done.returncode != 0:
        raise OSError(f"curl вернул {done.returncode} на {url[:80]}")
    return done.stdout


def kling_batch_url(filename: str) -> str:
    """Join a row to its file.

    THE DEFECT THIS FUNCTION EXISTS FOR, found by a reviewing agent and
    reproduced here: the metadata's own `local_path` column says
    `videos/video_001396.mp4` and that path 404s — the repository lays the clips
    out in `batch_000` … `batch_009`, a thousand each. A naive join on the
    column the dataset supplies produces an empty bank and no error.
    MEASURED on three files: all 200, 1.8-6.0 MB, ~2 s each.
    """
    stem = filename.rsplit(".", 1)[0]
    number = int(stem.split("_")[-1])
    return KLING_BATCH.format(batch=f"batch_{number // 1000:03d}", name=filename)


def strip_image(raw: bytes, out: Path) -> dict:
    """Re-encode an image so its provenance does not travel with it."""
    from PIL import Image

    original = Image.open(io.BytesIO(raw))
    carried = sorted(str(k) for k in (original.info or {}) if k not in ALLOWED_INFO_KEYS)
    buffer = io.BytesIO()
    original.convert("RGB").save(buffer, "JPEG", quality=88)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(buffer.getvalue())
    left = sorted(str(k) for k in (Image.open(out).info or {}) if k not in ALLOWED_INFO_KEYS)
    return {"stripped": carried, "remaining": left, "bytes": len(buffer.getvalue())}


def strip_video(raw: bytes, out: Path) -> dict:
    """Re-mux a clip, dropping every metadata tag.

    Video carries provenance in container tags rather than in an image header,
    so the same rule needs a different tool: `-map_metadata -1` on a stream copy.
    No re-encode, because the pixels are the evidence the reader is being asked
    to judge and transcoding them would put the instrument's own artefacts into
    the thing being measured.

    `-fflags +bitexact` matters and was added after a control caught its absence:
    `-map_metadata -1` alone drops the INPUT's tags and then ffmpeg writes its
    own `encoder: Lavf61.1.100`. Harmless in itself — it names our tool, not the
    source — but a strip that leaves a tag behind is a strip nobody can assert
    is empty, and the assertion is the whole product here. MEASURED: with a clip
    deliberately loaded with `title: kling_version 1.6`, `artist: klingai` and
    the prompt in `comment`, this leaves no tag at all.
    """
    import imageio_ffmpeg

    out.parent.mkdir(parents=True, exist_ok=True)
    raw_path = out.with_suffix(".raw.mp4")
    raw_path.write_bytes(raw)
    before = _video_tags(raw_path)
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(raw_path),
            "-map_metadata",
            "-1",
            "-fflags",
            "+bitexact",
            "-c",
            "copy",
            str(out),
        ],
        capture_output=True,
        check=False,
    )
    after = _video_tags(out) if out.is_file() else ["ffmpeg не создал файл"]
    raw_path.unlink(missing_ok=True)
    return {
        "stripped": before,
        "remaining": after,
        "bytes": out.stat().st_size if out.is_file() else 0,
    }


def _video_tags(path: Path) -> list[str]:
    """Container-level tags, which is where a clip keeps its origin."""
    import imageio_ffmpeg

    done = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(path)],
        capture_output=True,
        text=True,
        check=False,
    )
    tags: list[str] = []
    for line in done.stderr.splitlines():
        stripped = line.strip()
        if ":" in stripped and stripped.split(":")[0].strip() in {
            "title",
            "artist",
            "comment",
            "encoder",
            "description",
            "software",
            "prompt",
        }:
            tags.append(stripped.split(":")[0].strip())
    return sorted(set(tags))


class HttpRange(io.RawIOBase):
    """A seekable file over HTTP byte ranges.

    Needed because the OpenFake shards are 5.1 GB each and the whole set is
    207 GB, while the answer we want — the `model` column — is measured at 0.0 MB
    per row group against 102.4 MB for the images beside it. Reading the footer
    and then only the groups we want turns a 207 GB download into a few hundred
    megabytes.

    `readinto` and `readall` are not optional: without them pyarrow raises a bare
    NotImplementedError with no hint of which method it wanted, which cost a
    detour on 2026-08-30.
    """

    def __init__(self, url: str, size: int) -> None:
        self.url, self.size, self.pos = url, size, 0

    def readable(self) -> bool:
        return True

    def seekable(self) -> bool:
        return True

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = (
            offset if whence == 0 else (self.pos + offset if whence == 1 else self.size + offset)
        )
        return self.pos

    def tell(self) -> int:
        return self.pos

    def _pull(self, count: int) -> bytes:
        end = min(self.pos + count, self.size) - 1
        if end < self.pos:
            return b""
        data = _curl(self.url, ranged=(self.pos, end), timeout=180)
        self.pos += len(data)
        return data

    def readinto(self, buffer) -> int:  # type: ignore[override]
        data = self._pull(len(buffer))
        buffer[: len(data)] = data
        return len(data)

    def readall(self) -> bytes:
        return self._pull(self.size - self.pos)


def remote_parquet(url: str, size: int):
    """Open a parquet file that lives behind HTTP, without downloading it."""
    import pyarrow.parquet as pq

    return pq.ParquetFile(io.BufferedReader(HttpRange(url, size), buffer_size=1 << 20))


@dataclass
class Case:
    """One creative, its file, and the truth kept apart from it."""

    case_id: str
    source: str
    media: str
    path: str
    truth: dict[str, Any] = field(default_factory=dict)
    commercial_ok: bool = True
    licence: str = ""
