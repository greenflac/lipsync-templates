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
    order,
    requirement_fps,
    requirement_frame,
    rewrite,
    unmet,
)
from studio.recipes.table import FAILURES, PRIORS, RECIPES, TOOLS  # noqa: F401
