# Core rules — how a prompt for nanobanana-2 is built

Source of truth for prompt shape. This file is `kind=core`: it is never
appended automatically, only by review, and it carries the highest weight in
the index. Every section below becomes one core entry.

Provenance of the rules: the official Google Cloud blog post
"Ultimate prompting guide for Nano Banana", read in full (HTTP 200) on
2026-08-25, plus the Pollinations gateway model registry read the same day.

UNVERIFIED (Ц4), carried from the research report and not re-checked here:
- `ai.google.dev`, `docs.cloud.google.com` and `developers.googleblog.com` were
  blocked by policy and were NOT read. The API reference has not been seen.
- "Nano Banana 2 = Gemini 3.1 Flash Image" comes from the Google Cloud blog,
  not from API docs. That the gateway's `nanobanana-2` is that exact model is
  an inference from the `Google` brand field in the registry.
- The context window figures (131 072 input tokens for Nano Banana 2) come from
  the same blog post and were not confirmed against the API reference.

## The formula

A text-to-image prompt is one connected description assembled in this order:
`[Subject] + [Action] + [Location/context] + [Composition] + [Style]`.
Subject is who or what. Action is what they are doing. Location is where.
Composition is the framing — medium-full shot, center-framed, low angle.
Style is the look, and it has its own internal order (see the next section).
Write it as prose. The model is asked to picture a scene, not to parse a list.

## Order inside the style clause

Inside `[Style]`, order the clauses the way a creative director speaks:
light first, then camera and lens, then colour grade or film stock, then
material and texture. For example: "soft window light from the left, shallow
depth of field (f/1.8), 1980s colour film with slight grain, navy blue tweed".
A style clause that starts with the film stock and ends with the light is
harder for the model to hold together than the same words in this order.

## Positive phrasing only

Say what is in the frame, never what is absent. "An empty street" works;
"no cars" does not. The model has no separate channel for exclusion, so a
negation is read as a mention of the thing being excluded. Every unwanted
element has a positive description that displaces it: instead of "no text",
describe clean untouched surfaces; instead of "no clutter", describe a bare
tabletop.

## No weights, no negative prompt

Nano Banana has no `negative_prompt` field and no weight syntax. The
Pollinations image endpoint documents `model`, `width`, `height`, `seed`,
`safe`, `quality`, `image`, `transparent`, `resolution` — and nothing else.
Anything of the form `(keyword:1.3)`, `[keyword]`, `--no keyword` or
`keyword::2` is Stable Diffusion or Midjourney syntax. In a Nano Banana prompt
it is not an instruction, it is literal punctuation the model has to explain to
itself, and it costs quality.

## Be specific, not generic

"A beautiful woman" is a slot the model fills from its own average.
"A fashion model in a tailored brown dress, posing with a confident, statuesque
stance, slightly turned" is a picture. Specificity is the single largest lever
in the official guide, and it applies to every element: name the colour, name
the material, name the hour of day, name the shot size.

## Speak camera, not adjectives

Control framing and focus with photographic vocabulary the model was trained
on: shot size (extreme close-up, close-up, medium, medium-full, full, wide),
angle (eye level, low angle, top-down, dutch), lens and aperture (35mm,
f/1.8, shallow depth of field), and light direction (backlit, side-lit,
window light from camera left). These words move the image. "Beautiful
composition" does not.

## Start with a strong verb

Open the prompt with the verb that names the operation being asked for —
"Photograph", "Illustrate", "Restore", "Place", "Render". The opening verb
sets what kind of image this is before any noun is read, and it is the
cheapest disambiguation available.

## Text inside the frame

If words must appear in the image, put the exact words in quotes and describe
the typography next to them: `the words "OPEN LATE" in a bold, white,
sans-serif font`. Text that is only described, not quoted, comes back
misspelled. If no text is wanted, describe clean surfaces (see positive
phrasing) rather than asking for its absence.

## Iterate by conversation, not by rewrite

When a frame is close but wrong, change the one clause that is wrong and keep
the rest verbatim. Rewriting the prompt from scratch changes every variable at
once, and then nothing has been learned from the frame that was paid for.

## Length is not the constraint

There is no published length limit for a Nano Banana 2 prompt, and the input
context is very large. "Keep the prompt short" is a habit carried over from
CLIP-based encoders with a 77-token window; it does not apply here. The
practical limit is that every clause added is a clause the model must satisfy,
so length costs precision, not tokens.

## Dead practices — do not carry these over

Quality boosters and magic words ("masterpiece", "8k", "ultra detailed",
"trending on artstation") are noise: they name no visible property, and the
official guidance asks for a described scene instead of a keyword list.
Stable Diffusion weight syntax and negative prompts, and Midjourney's `--no`
and `::` multi-prompts, belong to other pipelines. A corpus of prompts
harvested from Stable Diffusion or Midjourney is partly poison for this model
and its examples must be normalised before use, never pasted.

## Our frame — vertical social video

CHOSEN by us, not from Google: the product ships 9:16 vertical frames for a
phone screen. Keep the top and bottom eighths clear of anything that matters,
because platform UI covers them, and leave the upper third as an even, low
detail field so a headline stays readable over it. Compose the subject in the
lower two thirds. This is a composition constraint and belongs in the
`[Composition]` slot of the formula, phrased positively.
