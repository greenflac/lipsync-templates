"""The agent the owner talks to in chat: a consultant, and a prompt writer.

Two functions, stated by the owner on 2026-08-27:

1. Advise on what a generation model can and cannot do, from a knowledge base
   that keeps being refreshed from the web.
2. Write lipsync prompts that work, that do not break the engine's contract,
   and whose phrasing comes from the corpus of prompts that actually ran.

WHY THIS IS AN MCP SERVER AND NOT A WEB APP

Both functions are things the owner asks for mid-conversation, in the chat he
is already in. Neither needs a page. Both need code to run: the contract gate
is real engine code, the corpus is 4601 rows, and the fact base is written to.

WHAT THIS PACKAGE MAY NOT DO, AND THE MEASUREMENT BEHIND IT

It may not fetch the web. MEASURED 2026-08-27 on this machine:

    curl https://docs.bfl.ai   -> CONNECT tunnel failed, gateway 403
    curl https://arxiv.org     -> CONNECT tunnel failed, gateway 403
    WebFetch https://kling.ai  -> EGRESS_BLOCKED

The egress proxy refuses the vendor domains, and going around it is forbidden
(house rule Ц3). Claude's own search tool is not refused, and Claude is the
one holding this conversation. So the refresh path is: the assistant searches,
and calls `record_claim` to write what it found WITH its source and its date.
The base updates through the chat, which is where the owner already is.

This package composes; it does not re-implement. The word bands, the forbidden
subject words, the fact tiers and the corpus loader all live in the modules
that own them, and are imported (house rule E1).
"""
