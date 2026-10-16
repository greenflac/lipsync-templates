"""Curated recipe layer: job classes, their step decomposition, free tools,
engineering priors (with sources or the `engineering prior` tag) and failure
modes. Data in `table.py`, how the planner consumes it in `apply.py`."""

from studio.recipes.apply import (  # noqa: F401
    Applied,
    assumption,
    block,
    enabled,
    fps_prior,
    frame_prior,
    native_aspect,
    note_ids,
    notes,
    order,
    requirement_frame,
    rewrite,
    unmet,
    wants_alpha,
)
from studio.recipes.table import FAILURES, NOTES, PRIORS, RECIPES, TOOLS  # noqa: F401
