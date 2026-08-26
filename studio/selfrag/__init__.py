"""Self-RAG prompt engineering: corpus, retrieval, reflection, monitoring.

This package is additive. It does not edit `studio/knowledge.py` or
`studio/style.py` — those have other owners under `studio/CONTRACTS.md` — it
imports from them and builds the missing layers on top:

    corpus      the user's prompt+result records, portably loaded
    registry    what each generation model can and cannot be asked for
    spec        a media-aware spec; video needs fields a StyleSpec has no room for
    retrieval   hybrid lexical retrieval over the corpus, stdlib only
    reflect     the Self-RAG grading loop: is this retrieved set usable, is this
                draft supported, is it worth another round
    cache       content-addressed reuse of finished work
    replay      what shipped and what it scored, fed back into ranking
    monitor     a journal of every run and a report over it
    pipeline    the orchestration, sync and async

Nothing here reaches the network at import time, and no test in
`studio/selfrag/tests` may reach it at all.
"""

from studio.selfrag.corpus import CorpusRecord, load_corpus
from studio.selfrag.registry import MODEL_CARDS, ModelCard, card_for
from studio.selfrag.spec import GenSpec, MEDIA_IMAGE, MEDIA_VIDEO

__all__ = [
    "MEDIA_IMAGE",
    "MEDIA_VIDEO",
    "MODEL_CARDS",
    "CorpusRecord",
    "GenSpec",
    "ModelCard",
    "card_for",
    "load_corpus",
]
