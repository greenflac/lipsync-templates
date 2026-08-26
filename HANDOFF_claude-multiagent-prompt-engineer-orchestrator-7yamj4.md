# HANDOFF — branch claude/multiagent-prompt-engineer-orchestrator-7yamj4

Append-only. Each agent appends its own section and edits nobody else's.

## Agent: orchestrator — 2026-08-26

### Task as received

A multi-track research + code-review + build request: research the 2026 state of
image/video generation models and of Self-RAG architectures, review "my initial
architecture", and deliver a production Self-RAG prompt-engineering pipeline plus
a Claude Code skill, operating instructions and prompt-quality monitoring.

### Two facts the request got wrong, resolved before starting

1. The request says the initial architecture was "presented above". It was not
   included in the message. The architecture that exists is this repository's
   `studio/` package — `studio/knowledge.py` (hybrid retrieval, three outcomes,
   `evaluate`) and `studio/style.py` (StyleSpec extraction, prompt assembly).
   That is what the code review targets.
2. The request says the corpus lives at `./corpus/prompts.jsonl` with fields
   `prompt / result / model / tags / rating`. That path does NOT exist in this
   repo (`ls corpus` -> No such file or directory, MEASURED 2026-08-26). The real
   corpus is `studio/knowledge/` (core_rules.md, eval_set.jsonl, and a
   gallery_prompts.jsonl that also does not exist yet). The new loader accepts
   BOTH shapes so the stated corpus works the day it is dropped in.

### Ownership under CONTRACTS.md

`studio/knowledge.py` and `studio/style.py` have other owners (Ц2). This agent
does NOT edit them. All new work lands in new files under `studio/selfrag/`
plus new docs. Anything the review finds in the owned modules is written up as
a finding for their owner, not patched here.
