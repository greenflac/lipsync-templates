"""Catalogue of motion templates: the pre-rendered driving clips a user picks from.

A template is a purchase decision frozen into data. The driving footage is the
only input that gets bought (README, "Choosing driving footage"), so its frame
window is chosen once by the owner, measured against the clip, and then reused
by every job — the user never picks frame numbers.

The catalogue deliberately reports what is *not* on disk. A menu entry whose
mp4 is missing is not a crash and not a silent omission: it is listed with
`available: False`, so the shop shows the same set of items whatever the deploy
happens to carry.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

# The engine cuts a 5.0 s product at 30 fps (lipsync.fork_e2e.PRODUCT_SECONDS,
# WINDOW_FPS_PROVEN), so a window is 150 frames long. CHOSEN by the owner per
# clip, not measured: the real numbers land when the clip itself is bought and
# run through `lipsync.fork_intake.driving_intake`, which reports the longest
# cut-free scene.
WINDOW_FRAMES = 150

# Repository root, so a catalogue entry reads as a repo-relative path in one
# place only and the web layer never re-derives it.
ROOT = Path(__file__).resolve().parent.parent

DRIVINGS_DIR = "assets/drivings"


@dataclass(frozen=True)
class MotionTemplate:
    """One pickable driving clip: what the user sees and what the engine cuts."""

    id: str
    name: str
    video_path: str
    first: int
    last: int
    poster_path: str


def _entry(template_id: str, name: str, first: int) -> MotionTemplate:
    """Build one entry from the naming convention, so a path exists in one place."""
    return MotionTemplate(
        id=template_id,
        name=name,
        video_path=f"{DRIVINGS_DIR}/{template_id}.mp4",
        first=first,
        last=first + WINDOW_FRAMES - 1,
        poster_path=f"{DRIVINGS_DIR}/{template_id}.png",
    )


# CHOSEN by the owner: the shortlist the studio offers at launch. `first` is a
# placeholder start frame, not a measurement — see WINDOW_FRAMES above.
#
# RENAMED 2026-08-28, by the owner, after the clips arrived and were OPENED AND
# LOOKED AT rather than trusted by filename (house rule P3). The three ids used
# to read `walk_city` / `turn_smile` / `sit_talk`; not one of the delivered
# clips is any of those. What arrived is three dance clips shot indoors, and a
# catalogue entry saying "Walking down a city street" over a woman dancing in a
# kitchen is a label contradicting its own evidence — the thing rule E2 exists
# to stop. The names below say what the frames show.
#
# OBSERVED at frames 0/50/100/149, which is the window the engine actually cuts:
#   dance_hallway  a man facing the camera in a hallway, face visible throughout
#   dance_kitchen  a woman dancing in a kitchen; full body, the face is small
#   spin_dress     a woman spinning; heavy motion blur, face turned away in 3
#                  of the 4 sampled frames
# The last two are a real concern for a LIPSYNC driving clip and are recorded
# here rather than discovered later: only `dance_hallway` holds a camera-facing
# face across the window. Nobody has measured what that costs the result yet.
CATALOGUE: tuple[MotionTemplate, ...] = (
    _entry("dance_hallway", "Dancing in a hallway, facing camera", 0),
    _entry("dance_kitchen", "Dancing in a kitchen", 0),
    _entry("spin_dress", "Spinning in a dress", 0),
)


def _exists(rel_path: str) -> bool:
    """Answer whether a repo-relative asset is on this deploy's disk."""
    return (ROOT / rel_path).is_file()


def as_dict(template: MotionTemplate) -> dict:
    """Render one template for the API, with its on-disk availability attached.

    Example:
        >>> as_dict(CATALOGUE[0])["id"]
        'dance_hallway'
    """
    data = asdict(template)
    data["available"] = _exists(template.video_path)
    data["poster_available"] = _exists(template.poster_path)
    return data


def catalogue() -> list[dict]:
    """List every template the studio offers, present on disk or not."""
    return [as_dict(t) for t in CATALOGUE]


def get(template_id: str) -> dict | None:
    """Return one template by id, or `None` when the id is not in the catalogue."""
    for template in CATALOGUE:
        if template.id == template_id:
            return as_dict(template)
    return None


def availability() -> dict:
    """Judge whether the declared clips are actually on disk: three outcomes.

    An empty catalogue is UNMEASURED, never PASS: nothing checked cannot be
    a clean bill of health.

    Example:
        >>> availability()["checked"]
        3
    """
    checked = len(CATALOGUE)
    missing = [t.id for t in CATALOGUE if not _exists(t.video_path)]
    if checked == 0:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "missing": [],
            "note": "the catalogue is empty: there was nothing to check",
        }
    outcome = FAIL if missing else PASS
    note = (
        f"{checked - len(missing)} of {checked} driving clips are on disk"
        if not missing
        else (
            f"{len(missing)} of {checked} driving clips are missing from {DRIVINGS_DIR}/: "
            f"{', '.join(missing)}. The menu still lists them, marked unavailable"
        )
    )
    return {
        "outcome": outcome,
        "checked": checked,
        "violations": len(missing),
        "unmeasured": 0,
        "missing": missing,
        "note": note,
    }
