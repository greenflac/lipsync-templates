# Contracts for the studio web layer — read before writing any module

Parallel agents share these EXACTLY. A mismatch here is a broken build, so
copy the names verbatim; do not invent synonyms.

## What the product does (one pass)

    user uploads a selfie
    user picks a motion template (a pre-rendered driving demo)
    user describes the style in free text, in a chat
    agent extracts a StyleSpec, code assembles the prompt
    cheap generation -> styled first frame, shown to the user   (costs cents)
    user consents -> expensive generation -> vertical video     (costs ~$0.70)

## Ownership: one writer per module

| Module | Owner | Never edited by others |
|---|---|---|
| `studio/ledger.py`, `studio/store.py` | agent A | |
| `studio/style.py` | agent B | |
| `studio/app.py`, `studio/jobs.py` | agent C | |
| `studio/static/index.html` | agent D | |
| `lipsync/**` | NOBODY — the engine is frozen for this work | |

## The three outcomes (imported, never re-declared)

    from lipsync.fork_identity import PASS, FAIL, UNMEASURED
    # "pass" / "fail" / "could not measure"

Every function that judges anything returns a dict with at least:
`{"outcome": PASS|FAIL|UNMEASURED, "checked": int, "violations": int,
  "unmeasured": int, "note": str}`. Zero checks is never PASS.

## StyleSpec — the agent's ONLY output shape

The model never writes the final prompt. It fills this structure; the code
assembles the prompt from a template. This is the security boundary: an
injected instruction can change a field value, it cannot change what the
prompt is made of.

```python
@dataclass(frozen=True)
class StyleSpec:
    palette: tuple[str, ...]      # 1-4 colour words, from PALETTE_WORDS
    light: str                    # one of LIGHT_WORDS
    texture: str                  # one of TEXTURE_WORDS
    mood: str                     # one of MOOD_WORDS
    setting: str                  # <= 60 chars, free text, sanitised
    refusal: str | None           # set => nothing is generated
```

Any value outside the allow-list is a `FAIL`, not a silent substitution.
`setting` is the only free-text field and is stripped of anything that is
not a letter, digit, space, comma or hyphen.

## Contract between modules

```python
# studio/style.py       (agent B)
def extract(text: str, *, model=None) -> dict        # {outcome, spec|None, note}
def build_prompt(spec: StyleSpec) -> str             # template lives HERE, in code
def gate_input(spec: StyleSpec) -> dict              # three outcomes

# studio/ledger.py      (agent A)
def balance(user_id: str) -> int                     # sum of the journal, in credits
def charge(user_id: str, credits: int, *, key: str, reason: str) -> dict
def refund(user_id: str, credits: int, *, key: str, reason: str) -> dict
# `key` is the idempotency key: the same key never charges twice.

# studio/store.py       (agent A)
def create_session(user_id: str) -> str              # returns session_id
def get(session_id: str) -> dict | None
def update(session_id: str, **fields) -> dict

# studio/jobs.py        (agent C)
def submit(session_id: str, kind: str) -> str        # kind: "frame" | "video"
def status(job_id: str) -> dict                      # {state, outcome, result|None}
```

## Prices, in credits (CHOSEN by the owner, not measured)

    FRAME_CREDITS = 1     # cheap generation, the styled first frame
    VIDEO_CREDITS = 10    # expensive generation, ~$0.70 of real money

Charge BEFORE the call, refund with a compensating entry when the call
fails. Never update a balance row: the balance is the sum of the journal.

## Rules that hold everywhere

- Tests never touch the network; the runner enforces it, not a convention.
- Secrets come from the environment only, never from a file or the model.
- The engine (`lipsync.fork_e2e.run`) is called with keyword arguments only.
- Every module is English, comments explain WHY, docstrings are imperative.
