"""The MCP server the owner talks to in chat. Fourteen tools, seven of which write.

THE NUMBERS IN THIS LINE ARE GATED, NOT PROSE

They said "twelve, three" while the server carried fourteen and seven — a
docstring that drifted quietly because nothing checked it. `test_server_surface`
now reads this very line and compares it to the live tool list, so the next
tool that lands either updates this sentence or turns the build red. Three of
the seven write KNOWLEDGE (record_model_fact, withdraw_model_fact,
propose_measurement); the other four write the DENIAL JOURNAL as a side effect
of reaching the network (fetch_url, search_web, reachable_hosts,
probe_model_limit), which is a write nobody asked for and which a reader of
this file deserves to know about.

IT ANSWERS FOR THE FIELD, NOT FOR THIS REPOSITORY

The first line of the instructions a client sees says the agent surveys the
whole field and treats nothing in this repository as a default. That is there
because the opposite happened: asked which stack would put a new character into
an existing scene at photographic realism, the assistant recommended
`lipsync/fork_e2e.py` — which is in this repo, which does motion transfer onto
a character image, and which therefore does NOT preserve the original scene.
The requirement was "the same set"; the recommendation could not deliver it.
It was reached for because it was near, and it was presented as a conclusion.

The owner's words for the rule: the agent is a universal fighter and must not
prioritise what is in the repo. So the clause is in the instructions string,
where every client reads it, and `test_server_instructions.py` asserts it is
still there — a rule that lives only in a docstring is a rule that drifts back
the first time somebody edits the prompt for length (house rule C7).


RUN IT

    python -m studio.mcp.server          # stdio, which is what Claude Code speaks

`.mcp.json` at the repo root registers it, so it appears in the chat with no
further setup.

THE TOOLS THAT WRITE

`record_model_fact` and `withdraw_model_fact` append to
`studio/knowledge/model_facts.jsonl`, and `fetch_url` appends a refused host to
`denied_hosts.jsonl` so the allowlist request assembles itself. Everything else
reads. Neither writer deletes: the fact file is a log where the latest row
about a claim wins, so how a claim was argued stays readable after it changes.

That asymmetry is deliberate and worth stating in the tool list a model sees: an assistant deciding on its own to "tidy" the knowledge base is a
worse outcome than a stale one, because a stale claim announces its age and a
rewritten one does not.

WHAT EVERY TOOL RETURNS

The house judging dict — `outcome` of `pass` / `fail` / `could not measure`,
plus `checked`, `violations` and `unmeasured` — rendered as JSON. The counts
travel with the verdict on purpose: zero violations out of zero checks is not
a success, and a caller that only reads `outcome` can still be shown the
denominator.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer

from studio import knowledge
from studio.selfrag.facts import STALE_AFTER_DAYS  # noqa: E402
from studio.mcp import advice, contract, creative, fetch, misses, probe, proposal, search
from studio.mcp import lipsync_prompt as lp

server = MCPServer(
    name="lipsync-studio",
    instructions=(
        "WHOSE SIDE YOU ARE ON. You survey the whole field. This repository "
        "contains a working engine and a corpus, and NEITHER is a default. When "
        "asked what stack to use, name the candidates that exist in the world, "
        "compare them on the job's own requirements, and let this project's own "
        "tools win only if they win on that comparison — said out loud, with what "
        "they were compared against. Reaching for what is already in the repo and "
        "presenting it as the answer is the failure mode this instruction exists "
        "to stop: it is fast, it reads as expertise, and it is how a project stops "
        "learning that something better shipped last month. If you have not looked "
        "outside, say that you have not, rather than recommending from inside. "
        "AND GROUND IT: call `model_advice` on every candidate you are about to "
        "compare, not only on the one you like, and say what the base knows, at "
        "which tier, and whether anybody read the source. It answers in the "
        "comparison form by default, which is a fifth of the size, so asking "
        "about five candidates is affordable; add `full=True` for the one you "
        "settle on, to read the sources themselves. This is enforced, not "
        "asked: the Stop hook `scripts/stop_named_not_asked.py` refuses to end a "
        "turn that recommends a model name the session never passed to "
        "`model_advice`, and prints which names. A vendor schema proves "
        "CAPABILITY — that the API accepts the input. It does not prove "
        "APPLICABILITY — that the result holds up. Those are different claims and "
        "the second one comes from the corpus and from what practitioners "
        "reported, not from a parameter list. Where the base is empty, record "
        "what you find with `record_model_fact` so the next answer is cheaper, "
        "and say plainly which half of the comparison rests on evidence nobody "
        "has yet. "
        "(0) Two jobs follow. (1) Advise on what a generation model can and cannot do: call "
        "`model_advice` FIRST, before answering from memory, because model limits "
        "change monthly and this base records who said what and when. When it "
        "reports a gap or a stale claim, search the web yourself and call "
        "`record_model_fact` with the value, the source URL, the source tier and "
        "the date the source stated it. `search_web` is the research entry point — "
        "start there rather than from memory. Prefer a VENDOR artefact over an article: "
        "`fetch_url` reaches raw.githubusercontent.com, api.github.com, pypi.org, "
        "huggingface.co and cloud.google.com, so an SDK source or an OpenAPI spec "
        "is readable. For a numeric limit whose documentation host is blocked, use "
        "`probe_model_limit` — the vendor API's own refusal is the measurement, and "
        "it records at `probe` tier. A host the policy refuses is reported, never "
        "routed around: no mirror, no cache, no read-through proxy. "
        "When free sources have run out and only a real generation would settle "
        "the question, do not run it and do not go quiet: call "
        "`propose_measurement` — name the gap, write the exact test, name the "
        "price, and let the operator decide. You cannot approve it yourself, so "
        "file it, answer with what you know today, and say the gap is open. "
        "(2) Write lipsync prompts: call `write_lipsync_prompt`. It fills "
        "the engine's card from the owner's words and the corpus, and refuses "
        "with a question when a slot is unresolved. Do not answer the question "
        "on the owner's behalf — ask them."
    ),
)

_INDEX: Any = None


#: Плотный канал включён на сервере по умолчанию — решение владельца
#: 2026-08-31, принятое по замеру, а не по ощущению:
#:
#:     recall@5 без канала   0.5333
#:     recall@5 с каналом    0.6833      (+0.15, тот же корпус и тот же набор)
#:     сборка индекса        1.2 с → 171.4 с на 13 438 записях
#:
#: Три минуты платятся ОДИН РАЗ на процесс, а не на запрос: индекс строится
#: здесь однажды и живёт в памяти. С 2026-09-02 это уже НЕ три минуты: кэш
#: векторов ключится хешем текста (`VECTOR_CACHE_PATH` в studio/knowledge.py),
#: и вторая сборка ИЗМЕРЕНА в 3.0 с против 160.3 с. Строки выше оставлены как
#: запись о том, чем это было: три минуты платил первый вызов пользователя
#: после каждого старта, и клиенты успевали отвалиться по таймауту.
#:
#: Значение по умолчанию НЕ трогается в самой библиотеке нарочно: `build_index`
#: без аргумента обязан остаться быстрым и офлайновым, иначе каждый тест полезет
#: за весами в сеть (правило Т4).
#:
#: Выключается переменной окружения на случай, когда важнее скорость старта:
#:     STUDIO_MCP_DENSE=0
DENSE_ON_SERVER_ENV = "STUDIO_MCP_DENSE"


def dense_wanted(environ: Mapping[str, str] | None = None) -> bool:
    """Просить ли плотный канал при сборке индекса.

    Вынесено из `_index` (Т5): развилка внутри функции, которая строит индекс
    три минуты, тестом недостижима — а тест, который повторяет её у себя,
    проверяет копию и молчит при подмене оригинала. Поймано на себе
    2026-08-31: первая редакция теста делала именно так, и обе мутации прошли
    мимо.

    Выключает только ЯВНЫЙ ноль: опечатка в переменной не должна тихо ронять
    качество поиска на 0.15.
    """
    source = os.environ if environ is None else environ
    return source.get(DENSE_ON_SERVER_ENV, "1") != "0"


def _index() -> Any:
    """The corpus index, built once per process. 13 438 rows is not a per-call cost.

    Typed `Any` because `studio/knowledge.py` is shadowed for a type checker by
    the same-named directory beside it; see the note in `lipsync_prompt.py`.
    """
    global _INDEX
    if _INDEX is None:
        _INDEX = knowledge.build_index(dense=dense_wanted())  # type: ignore[attr-defined]
    return _INDEX


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, default=str)


def advise_and_note(
    model: str, attribute: str = "", *, log: Path | None = None, brief: bool = False
) -> dict:
    """Проконсультировать и записать, что вопрос БЫЛ задан.

    Вынесено из инструмента (правило Т5): развилка внутри `@server.tool()`
    тестом недостижима, а тест, повторяющий её у себя, проверяет копию.

    Записывается КАЖДЫЙ вопрос, а не только промах: журнал одних промахов
    растёт и когда база улучшается, и когда ухудшается — без попаданий рядом
    у покрытия нет знаменателя. Зачем это нужно — в `misses.py`.
    """
    # Нормализация ОДНА и здесь: дальше `advise` и `misses.evidence` обязаны
    # видеть одну и ту же строку, иначе «атрибут задан» решается двумя
    # способами и они расходятся на пробельном входе.
    attribute = str(attribute or "").strip()
    # Журнал вопросов ведётся по ПОЛНОМУ разбору, а краткая форма — вид на
    # него: иначе покрытие считалось бы двумя разными способами в зависимости
    # от того, как спросили, и знаменатель разъехался бы (Е1).
    answer = advice.advise(model, attribute)
    misses.note_question(
        model,
        attribute,
        str(answer.get("outcome") or ""),
        known=misses.evidence(answer, attribute),
        note=str(answer.get("note") or "")[:200],
        path=log,
    )
    return advice.brief(model, attribute) if brief else answer


@server.tool()
def model_advice(model: str, attribute: str = "", full: bool = False) -> str:
    """What is known about a generation model: values, tiers, dates, disputes.

    Call this before answering any question about what a model can do. It never
    resolves a disagreement for you: sources that disagree come back as `fail`
    with both sides.

    :param model: e.g. "kling-3.0", "veo-3.1", "flux-2".
    :param attribute: one attribute such as "max_seconds"; empty for everything.
    :param full: every source with its URL, note and reading mark, plus the
        class-level findings. Ask for it when you are down to ONE candidate and
        want to read the evidence. The default is the comparison form.

    WHY THE DEFAULT IS THE SHORT FORM. MEASURED 2026-09-02: the full answer for
    `minimax-h3` is 23 751 characters — about ten thousand tokens — and this
    server's own instruction tells you to ask about EVERY candidate you
    compare. Five candidates cost more than the answer you are writing, and an
    assistant that cannot afford the rule stops following it. The short form is
    21-31% of that and keeps what a comparison needs: outcome, reason, values,
    best tier, whether sources disagree, how fresh they are, how many there
    were. Nothing that distinguishes this base from your memory is dropped —
    the third outcome, the dispute and the availability axis are all in it.
    """
    return _json(advise_and_note(model, attribute, brief=not full))


@server.tool()
def record_model_fact(
    model: str,
    attribute: str,
    value: str,
    source_url: str,
    tier: str,
    stated_on: str,
    note: str = "",
    fix: str = "",
    read_directly: bool | None = None,
    witnessed: str = "",
) -> str:
    """Write one thing you found on the web — or ran yourself — into the base.

    Use it after searching, when `model_advice` showed a gap, a contradiction
    or a stale claim.

    Recording something already recorded is an UPDATE, not a second source
    agreeing: a claim is identified by model, attribute, value and URL, and a
    new row supersedes the old one's tier, date, note and reading flag. That is
    how a fact known through a summary becomes one you opened, without the page
    being counted twice. If the page does NOT say what was recorded, use
    `withdraw_model_fact` instead.

    :param witnessed: REQUIRED when `tier` is "operator", ignored otherwise.
        What was actually run and what came out, in observable words. A verdict
        without an observation is an opinion, and there is already a tier for
        opinions — it is called "blog". Compare: "nano-banana keeps text" is an
        opinion; "fed nano-banana-edit a frame with Pillow-rendered text, the
        text survived unchanged" is a fact somebody can go and contradict.
        Without it the record is REFUSED, not merely weighted down.

    :param tier: the ladder is, strongest first — "vendor" (the model vendor's
        own page), "probe" (their API answered), "paper" (arXiv or a venue),
        "benchmark" (an evaluation with a published method), "portal" (a
        platform that runs the model or hosts what people made with it), "blog"
        (everything else). Ten blogs repeating each other stay one blog.

        "vendor", "portal" and "blog" are decided by the URL, not by you: pass
        the one you believe and you will be refused, with the host named, if it
        disagrees. "probe", "paper" and "benchmark" describe how you got the
        fact, so those are yours to state.
    :param stated_on: the ISO date THE SOURCE stated it (YYYY-MM-DD), not
        today. Dating an old article as today is how a stale claim looks fresh.
    :param fix: for a failure mode, what to do about it.
    :param read_directly: True if you opened the page yourself, False if you
        only saw it quoted or summarised. Leave it unset if you did not record
        which — that is a third answer, not a False. Most vendor hosts are
        refused by this environment, so False is the honest answer more often
        than it looks, and it is what stops a summary reading as a vendor
        statement.
    """
    return _json(
        advice.record(
            model,
            attribute,
            value,
            source_url,
            tier,
            stated_on,
            note=note,
            fix=fix,
            read_directly=read_directly,
            witnessed=witnessed,
        )
    )


@server.tool()
def withdraw_model_fact(
    model: str,
    attribute: str,
    value: str,
    source_url: str,
    reason: str,
) -> str:
    """Take back a recorded claim whose own source does not make it.

    Use this and not `record_model_fact` when you opened a page that was cited
    from somebody's summary and found it says nothing of the sort. Re-recording
    a corrected value leaves the wrong one standing beside it and the base
    reports the page as contradicting itself.

    All four of model, attribute, value and URL must match the standing claim
    exactly — together they identify it. Withdrawing something that is not
    there is reported as "could not measure", not as done.

    The row is APPENDED, not deleted: the base stops asserting the claim while
    the file keeps the record that somebody believed it and why it went.

    :param reason: what you checked and what you found. "wrong" tells the next
        reader nothing; "the page does not contain the word Veo" does.
    """
    return _json(advice.withdraw(model, attribute, value, source_url, reason))


@server.tool()
def analyse_creative(path: str, frames_dir: str = "") -> str:
    """Measure a creative you dropped in: what it looks like, what moves in it.

    Point it at an image OR a video — a reference you liked, a driving clip you
    are about to run, a competitor's still. It answers in the SAME vocabulary
    `write_lipsync_prompt` takes, so the palette and lighting words come back
    ready to use.

    :param path: the file. A video (`.mp4`, `.mov`, `.webm`, …) is decoded here
        into six frames: the look is measured on the MIDDLE one — a first frame
        is often a title card or a shot that has not settled — and the motion
        instruments get the whole sequence, so a loop seam or a drift shows up.
        Until 2026-08-31 this said an mp4 could not be decoded here; that was
        true when written and had gone stale, ffmpeg 7.0.2 ships with
        `imageio-ffmpeg`.
    :param frames_dir: frames you extracted yourself, in filename order. Given,
        it wins over decoding `path` — nobody should pay for a second decode.

    Read the `could_not_run` list before trusting a clean answer. Several
    instruments need packages this environment does not have — every face and
    pose axis among them — and they come back named rather than skipped,
    because no violations out of no checks is not a clean creative.

    Two things it will NOT do. It never names a mood: nothing in a histogram
    says "melancholic", and a guess would be indistinguishable in the output
    from a measurement. And it never names a lighting word for an image whose
    histogram supports neither high-key nor low-key — it returns none.
    """
    frames: list[str] | None = None
    if frames_dir.strip():
        directory = Path(frames_dir.strip())
        frames = [str(p) for p in sorted(directory.glob("*")) if p.is_file()]
    return _json(creative.analyse(path, frames=frames))


@server.tool()
def stale_model_facts(days: int = STALE_AFTER_DAYS) -> str:
    """Which recorded claims are old enough to be worth re-checking on the web."""
    return _json(advice.stale(days=days))


@server.tool()
def write_lipsync_prompt(intent: str) -> str:
    """Write a lipsync style prompt from the owner's words plus the corpus.

    The prompt describes the LOOK only — the subject comes from the user's
    photo and the driving clip, and naming it breaks the engine's contract.

    Returns `could not measure` with a question when a card slot cannot be
    filled from what the owner said or from what the corpus agrees on. Put that
    question to the owner; do not answer it for them.

    :param intent: the owner's own words, e.g. "muted ivory and slate,
        low-key light, matte".
    """
    found = knowledge.retrieve(  # type: ignore[attr-defined]
        intent, k=lp.DEFAULT_K, index=_index()
    )
    result = lp.write(intent, found.get("examples", ()))
    result["retrieval"] = {
        "outcome": found["outcome"],
        "examples": len(found.get("examples", ())),
        "below_floor": found.get("below_floor"),
        "note": found.get("note"),
    }
    return _json(result)


@server.tool()
def check_lipsync_prompt(prompt: str) -> str:
    """Judge any lipsync prompt against the engine's contract, from any source.

    Three checks: the forbidden subject zone, the word band and the clause
    band. A violation is reported, never repaired — trimming a prompt into
    shape would report `pass` for text the owner never approved.
    """
    return _json({**contract.gate(prompt), "bands": contract.BANDS})


@server.tool()
def search_web(query: str, site: str = "", count: int = 8) -> str:
    """Search the web. This is the research entry point — start here.

    Two backends, both Google, both reachable through this session's egress
    policy (measured 2026-08-27: Brave, Tavily, Exa, SerpAPI, Serper,
    DuckDuckGo, Bing, SearxNG and Perplexity are all refused; GitHub answers
    but blocks its search paths).

    Gemini grounding is used when GEMINI_API_KEY is set — it searches the whole
    index with no domain list. Programmable Search is the fallback and is
    capped at 50 curated domains, because Google withdrew "search the entire
    web" from new engines in March 2026. `backend` in the result says which
    one answered.

    Every result says whether its host can also be OPENED. A host the policy
    refuses still gives you a title, a snippet and a URL you can cite — you
    just cannot read the page in full, and `fetch_url` will tell you the same.

    Unconfigured, it returns `could not measure` with the two free credentials
    it needs and where to get them. That is not a failure: nothing was
    searched, which differs from searching and finding nothing.

    :param site: restrict to one domain, e.g. "kling.ai" — useful even when
        that domain is blocked, because the snippets still come back.
    """
    return _json(search.search(query, count=count, site=site))


@server.tool()
def fetch_url(url: str, why_wanted: str = "") -> str:
    """Fetch a page or a file from the web through this session's egress policy.

    Use it to read a vendor's own artefact instead of somebody's article about
    it. Measured 2026-08-27, these answer: raw.githubusercontent.com,
    api.github.com, pypi.org, huggingface.co, cloud.google.com,
    api.klingai.com, api.fal.ai. Vendor SDK source and OpenAPI specs on GitHub
    are vendor-tier material and are reachable.

    A host the policy refuses comes back `could not measure` with `denied:
    true` and is recorded for the allowlist request. Do NOT look for a mirror,
    a cache or a read-through proxy for it — report it instead.

    :param why_wanted: what you were trying to learn. It is carried into the
        denial record, so the allowlist request explains itself.
    """
    return _json(fetch.fetch(url, why_wanted=why_wanted))


@server.tool()
def blocked_hosts() -> str:
    """The allowlist request, assembled from hosts the policy actually refused.

    Hand this to whoever owns the egress policy. Every row under `hosts` is a
    host something real needed, with the reason it was wanted.

    `also_refused` is the other pile: hosts that were refused while a bulk
    probe swept past them — search results being tagged with whether they
    open, say. Nobody asked for those, so they are NOT part of the ask, and
    passing them off as one is how a request a human has to justify turns into
    noise. They are still listed, because a refusal is never swallowed.
    """
    return _json(fetch.wanted())


@server.tool()
def reachable_hosts(hosts: str = "", why_wanted: str = "") -> str:
    """Re-probe which documentation and API hosts answer right now.

    The reachability map is a measurement with a date on it; this refreshes the
    date instead of trusting a comment.

    :param hosts: comma-separated hosts to probe instead of the default map.
    :param why_wanted: the question you are probing these hosts FOR. Give it
        when you are checking specific hosts you actually need — the refusals
        then join the allowlist request under that reason, which is what makes
        the request worth reading. Leave it empty for a plain map refresh:
        nobody asked for those hosts, and their refusals stay out of the ask.
    """
    named = tuple(h.strip() for h in str(hosts or "").split(",") if h.strip())
    return _json(fetch.reachability(named or None, why_wanted=why_wanted))


@server.tool()
def probe_model_limit(
    url: str, field: str, absurd_value: str, payload_json: str = "{}", why_wanted: str = ""
) -> str:
    """Ask a vendor's API for an impossible value and read the real limit out of its refusal.

    This is how a numeric limit gets a `probe`-tier source when the vendor's
    documentation host is blocked. The refusal text IS the measurement.

    The value must be absurd — a number at or above 1000000, or a string
    containing "absurd-probe". Anything a vendor could plausibly honour is
    refused before a request is built, because a honoured request is a billed
    one. Do not lower that floor; raise the value.

    Returns `suggested_fact` — a draft row for `record_model_fact`. Read the
    response and write the real value into it yourself; do not record the
    draft as it stands.

    :param absurd_value: sent as a number when it parses as one, else as a string.
    :param payload_json: the rest of the request body, as JSON.
    """
    try:
        payload = json.loads(payload_json or "{}")
    except ValueError as error:
        return _json(
            {
                "outcome": "fail",
                "checked": 0,
                "violations": 1,
                "unmeasured": 0,
                "note": f"payload_json is not JSON: {error}",
            }
        )
    try:
        value: Any = float(absurd_value) if "." in absurd_value else int(absurd_value)
    except ValueError:
        value = absurd_value
    return _json(probe.probe_limit(url, field, value, payload=payload, why_wanted=why_wanted))


@server.tool()
def propose_measurement(
    model: str,
    attribute: str,
    task: str,
    gap: str,
    test: str,
    cost_usd: float,
    cost_basis: str,
    decides: str,
) -> str:
    """Ask the operator to pay for a generation you cannot answer without.

    Free sources run out. When the only way to settle a question is to run the
    thing and look at it, that costs money on the operator's account, and the
    ruling is that such a measurement happens per concrete task and with their
    approval each time. So you file; a person decides.

    This never runs anything and never writes a fact. The outcome is
    `could not measure` with an id, because a filed proposal has measured
    nothing. There is deliberately NO tool here to approve it: approval is a
    command the operator runs. Do not wait in a loop for it — say what you have
    filed, answer with what you know today, and mark the gap.

    A proposal is refused if the base already answers this freshly and
    uncontested. Contested or stale is exactly when measuring is worth paying
    for.

    :param task: the concrete job needing this. Approval is per task, not a
        standing budget.
    :param gap: what the base cannot answer today, and why free sources cannot
        close it.
    :param test: the exact request to send and what to look at afterwards —
        enough that somebody else could run it and get your number.
    :param cost_usd: what it will cost, in dollars. 0.0 is allowed and still
        goes past the operator.
    :param cost_basis: where that price came from — a published rate, an
        invoice. A price with no basis is a guess.
    :param decides: what each possible result would mean for the task. If both
        answers lead to the same next step, the measurement buys nothing.
    """
    return _json(
        proposal.propose(
            model,
            attribute,
            task=task,
            gap=gap,
            test=test,
            cost_usd=cost_usd,
            cost_basis=cost_basis,
            decides=decides,
        )
    )


@server.tool()
def measurement_proposals(state: str = "") -> str:
    """What measurements have been filed, and what is waiting on the operator.

    :param state: "proposed", "approved", "declined" or "recorded"; empty for
        all of them.
    """
    return _json(proposal.proposals(state=state))


def main() -> None:
    server.run()


if __name__ == "__main__":
    main()
