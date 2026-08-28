"""The prompt clauses the product sends, in the one place every route reads.

They are owner's decisions about the picture, not knowledge of any one stage,
so they live below every stage: the stand builds a stylization prompt from
them, the plan puts the brand ban into the outpaint prompt and the aesthetic
puts it into every template prompt. Holding them in the stand made the two
modules below it import the stand back, which is why they are here.
"""

from __future__ import annotations

#: CHOSEN by the owner and revised on 2026-08-22: ban the DRAWN mark and the
#: lettering, not the brand word. The earlier wording opened with "no brand
#: names" and so fought the owner's own prompts, which name "Adidas sneakers"
#: and a "Balenciaga trench". A ban that argues with the prompt does not win,
#: and that was MEASURED: on `y2k_f` no logo appeared, on `y2k_m` a readable
#: "adidas" did — the outcome was settled by chance. Stage 2 checks the clause
#: is present in the prompt, which is why the decision lives as a constant and
#: not as a sentence in a document. No instrument here reads lettering off an
#: image: that axis is judged by the owner's eye, and the acceptance says so.
NO_BRANDS_CLAUSE = (
    "no logo, no logos, no brand marks, no lettering or text anywhere in the frame or on clothing"
)

ROLE_CLAUSE = (
    "keep the person from the FIRST image unchanged — same face, "
    "same identity, same clothing, same pose, same accessories; "
    "take ONLY the lighting, colour grade, background and "
    "photographic look from the SECOND image"
)

NO_LOOK_TRANSFER_CLAUSE = (
    "do not copy any garment, accessory, eyewear, "
    "headwear, hairstyle or pose from the second "
    "image; the second image is a colour and lighting "
    "reference only"
)
