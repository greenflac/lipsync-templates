#!/usr/bin/env python3
"""Give a video case a face: a contact sheet the reader can actually look at.

A reader agent cannot watch an mp4. Handing it a path and hoping is not a
measurement. So every video case gets a strip of frames sampled across the clip,
and the reader is told the mp4 is there too if it wants more.

The sheet is drawn from the STRIPPED clip, never the original — otherwise the
strip would be undone at the last step by the very tool meant to present it.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import PASS, UNMEASURED  # noqa: E402

BANK = Path(__file__).resolve().parents[1] / "work" / "casebank"

#: Frames per sheet. ВЫБРАНО: six across the clip shows motion and still leaves
#: each frame large enough to judge texture at a glance.
FRAMES = 6


def sheet(clip: Path) -> Path | None:
    import imageio_ffmpeg

    out = clip.with_name(clip.stem + "_sheet.jpg")
    probe = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-i", str(clip)],
        capture_output=True,
        text=True,
        check=False,
    )
    seconds = 5.0
    for line in probe.stderr.splitlines():
        if "Duration:" in line:
            stamp = line.split("Duration:")[1].split(",")[0].strip()
            h, m, s = stamp.split(":")
            seconds = int(h) * 3600 + int(m) * 60 + float(s)
            break
    step = max(seconds / FRAMES, 0.2)
    subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(clip),
            "-vf",
            f"fps=1/{step:.3f},scale=380:-1,tile={FRAMES}x1",
            "-frames:v",
            "1",
            "-fflags",
            "+bitexact",
            str(out),
        ],
        capture_output=True,
        check=False,
    )
    return out if out.is_file() and out.stat().st_size > 5000 else None


def main() -> int:
    truth = BANK / "TRUTH.json"
    if not truth.is_file():
        print(f"\nпроверено 0\nнарушений 0\nне смогли 1\n\n{UNMEASURED}: нет {truth}")
        return 2
    cases = json.loads(truth.read_text(encoding="utf-8"))
    made = failed = 0
    for case in cases:
        if case["media"] != "video":
            continue
        clip = BANK.parent.parent / case["path"]
        if not clip.is_file():
            failed += 1
            continue
        got = sheet(clip)
        if got:
            case["sheet"] = str(got.relative_to(BANK.parent.parent))
            made += 1
        else:
            failed += 1
    truth.write_text(json.dumps(cases, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nпроверено {made + failed}\nнарушений 0\nне смогли {failed}")
    print(f"\n{PASS if made else UNMEASURED}: раскадровок сделано {made}, не смогли {failed}")
    return 0 if made else 2


if __name__ == "__main__":
    sys.exit(main())
