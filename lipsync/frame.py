"""The delivery frame: the one picture size the whole pipeline asks for.

It is one product fact, and it sits under every module that needs it — the
plan, the stand and the gateway — because the alternative, keeping it in the
plan and letting the gateway reach up for it, is the import cycle this package
was carrying. Nothing here imports anything of ours, so anyone may read it.
"""

from __future__ import annotations

#: MEASURED 2026-08-23 on the six shipped clips: Kling returned exactly this
#: size on every one of them, and all six final videos are this size too. It is
#: therefore the frame the product actually delivers, not a frame we would like
#: it to have. It is declared here, once, and every other size in the pipeline
#: is derived from it: the 3:4 default outlived its removal on `compose` alone
#: precisely because the two neighbouring routes held their own copies.
FRAME = (720, 1280)
