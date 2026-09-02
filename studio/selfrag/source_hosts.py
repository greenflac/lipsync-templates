"""Whose page is this? The tier ladder's first rung, decided by the URL.

The owner's rule, 2026-08-27:

    1. the model vendor's own URL
    2. specialised portals for exchanging artifacts, prompts and the like
    3. blogs and everything else

Tiering by WHOSE PAGE IT IS rather than by how well it is written. The middle
rung was missing and it mattered: measured over the 47 recorded facts, the
`blog` tier held **9 vendor pages** (kling.ai, docs.bfl.ai, help.runwayml.com,
docs.byteplus.com, cloud.google.com, bfl.ai) and **11 platform pages**
(wavespeed.ai ×4, piapi.ai ×2, evolink.ai, apiframe.ai, fal.ai, gaga.art,
atlascloud.ai) alongside genuine press. One rung was doing three jobs.

WHY A PORTAL IS NOT A BLOG

A platform that RUNS the model publishes what its own API accepts. That is a
statement about a running system, checkable against a request, and it is a
different kind of claim from an article describing the model from outside. It
is still below the vendor, because a platform exposes its own configuration —
its ceiling may be its plan rather than the model's.

WHY THE MODEL IS PART OF THE QUESTION

`kling.ai` is the vendor for `kling-3.0` and a competitor writing about
`veo-3.1`. A host alone cannot answer "is this the vendor"; the pair (model,
host) can. Nothing in the current base cites a rival vendor, and this is here
so that stays true as it grows.

WHY PATHS APPEAR AND NOT ONLY HOSTS

`github.com/Wan-Video/` is Alibaba's own repository for Wan; `github.com/
Vchitect/RAPO` is a paper's code. Same host, different owners. Where a host is
shared, the entry carries the path prefix that identifies the owner.

WHAT THIS FILE IS NOT

It is not a reachability map — see `studio/mcp/fetch.py` for that, and note
that most of the vendor hosts below are refused by this environment's egress
policy. Being the vendor's URL and having been read are different questions,
and `Fact.read_directly` answers the second one.
"""

from __future__ import annotations

import re

__all__ = [
    "BLOG_PATH_SEGMENTS",
    "USER_WRITTEN_SEGMENTS",
    "PORTALS_WHERE_USERS_ARE_THE_POINT",
    "FAMILY_SEPARATORS",
    "PORTAL_SOURCES",
    "VENDOR_SOURCES",
    "classify",
    "vendor_sources_for",
    "host_of",
]

#: CHOSEN by reading each source URL already in `model_facts.jsonl` on
#: 2026-08-27 and asking "who controls this page". Entries are `host` or
#: `host/path-prefix`; a prefix is used only where the host is shared.
#:
#: Keyed by MODEL FAMILY, not by model id: being the vendor is a relation
#: between a page and a model, but the vendor does not change when the version
#: does. Keyed by version, this table locked every unreleased version out of
#: the first rung until somebody remembered to edit it — OBSERVED 2026-08-27,
#: when the blind control set recorded a `deepmind.google` claim about `veo-3`
#: and was refused because only `veo-3.1` was listed. A rule that needs an edit
#: per version is a rule that will be wrong by the next release.
#:
#: A family matches a model id exactly, or up to one of `FAMILY_SEPARATORS`, so
#: `wan` claims `wan-2.6-flash` and not `wandering-model`. Longest match wins,
#: so a family can be split later if two versions really do change hands.
#: What may separate a family from the rest of a model id. `_` joined `-` and
#: `.` on 2026-08-27: a harvest of 144 models returned vendor-native ids, and
#: vendors write them with underscores — `gen4_turbo`, `act_two`,
#: `gemini_omni_flash`, `seedance2_5`. Without it, Runway's own `gen4_turbo`
#: could not match the `gen4` family and its documentation host classified as
#: `portal` on the vendor's own page.
FAMILY_SEPARATORS: tuple[str, ...] = ("-", ".", "_")

VENDOR_SOURCES: dict[str, tuple[str, ...]] = {
    # ЛАБОРАТОРИИ, ЧЕЙ АККАУНТ НА HUGGINGFACE — ЭТО ИХ СОБСТВЕННАЯ ПУБЛИКАЦИЯ.
    # Добавлены 2026-08-31 после того, как гейт лестницы покраснел: `portal`
    # обогнал `vendor` (602 против 511) на пятой волне разбора HuggingFace.
    # Гейт указал на правду, а не на перебор — карточка, которую лаборатория
    # написала о своей же модели, это ВЕНДОРСКИЙ документ, и записывать её как
    # портальную значит занижать то, что у нас есть из первых рук.
    #
    # Сюда попадает только аккаунт, который И опубликовал модель, И назван
    # именем её разработчика. Перезаливщики и дообучатели (John6666, Lykon,
    # RunDiffusion, digiplay, stablediffusionapi, Comfy-Org, diffusers и ещё
    # сотня таких) СЮДА НЕ ПОПАДАЮТ — их карточка про чужую модель, и `portal`
    # для неё верен. Из 137 разобранных аккаунтов признаны вендорскими 22.
    "kokoro": ("huggingface.co/hexgrad/",),
    "xtts": ("huggingface.co/coqui/", "coqui.ai"),
    "f5-tts": ("huggingface.co/SWivid/",),
    "e2-tts": ("huggingface.co/SWivid/",),
    "higgs": ("huggingface.co/bosonai/", "boson.ai"),
    "s2-pro": ("huggingface.co/fishaudio/", "fish.audio"),
    "csm": ("huggingface.co/sesame/", "sesame.com"),
    "zonos": ("huggingface.co/Zyphra/", "zyphra.com"),
    "orpheus": ("huggingface.co/canopylabs/",),
    "melotts": ("huggingface.co/myshell-ai/",),
    "minicpm": ("huggingface.co/openbmb/",),
    "voxcpm": ("huggingface.co/openbmb/",),
    "moss-tts": ("huggingface.co/OpenMOSS-Team/",),
    "mova": ("huggingface.co/OpenMOSS-Team/",),
    "cosmos": ("huggingface.co/nvidia/", "developer.nvidia.com"),
    "parakeet": ("huggingface.co/nvidia/", "developer.nvidia.com"),
    "bigvgan": ("huggingface.co/nvidia/",),
    "nemotron": ("huggingface.co/nvidia/", "developer.nvidia.com"),
    "mms": ("huggingface.co/facebook/",),
    "seamless": ("huggingface.co/facebook/",),
    "voxtral": ("huggingface.co/mistralai/", "mistral.ai"),
    "speaker-diarization": ("huggingface.co/pyannote/",),
    "indic-parler": ("huggingface.co/ai4bharat/", "huggingface.co/parler-tts/"),
    "parler-tts": ("huggingface.co/parler-tts/",),
    "noobai": ("huggingface.co/Laxhar/",),
    "illustrious": ("huggingface.co/OnomaAIResearch/",),
    "sdxl": ("huggingface.co/stabilityai/", "stability.ai"),
    "sd-turbo": ("huggingface.co/stabilityai/", "stability.ai"),
    "kling": (
        "kling.ai",
        "klingai.com",
        "api.klingai.com",
        "app.klingai.com",
        "ir.kuaishou.com",
    ),
    "flux": (
        "bfl.ai",
        "docs.bfl.ai",
        "api.bfl.ai",
        "blackforestlabs.ai",
        "huggingface.co/black-forest-labs/",
    ),
    # Two keys, and the longer one wins by the longest-match rule: `runway-gen`
    # keeps its own entry so a later split stays possible, while `runway` covers
    # the models that are not Gen-N at all — `aleph2` edits a video, `act_two`
    # transfers a performance, and neither is named gen-anything. Without this
    # they classified as `blog` on Runway's own documentation host.
    "runway": ("runwayml.com", "help.runwayml.com", "docs.dev.runwayml.com"),
    # Runway's own models as its API names them, which is not "runway-anything".
    "gen4": ("runwayml.com", "help.runwayml.com", "docs.dev.runwayml.com"),
    "gen3": ("runwayml.com", "help.runwayml.com", "docs.dev.runwayml.com"),
    "gwm1": ("runwayml.com", "help.runwayml.com", "docs.dev.runwayml.com"),
    "aleph": ("runwayml.com", "help.runwayml.com", "docs.dev.runwayml.com"),
    "act": ("runwayml.com", "help.runwayml.com", "docs.dev.runwayml.com"),
    "ruby": ("runwayml.com", "help.runwayml.com", "docs.dev.runwayml.com"),
    "runway-gen": ("runwayml.com", "help.runwayml.com", "docs.dev.runwayml.com"),
    "seedance": ("docs.byteplus.com", "byteplus.com", "seed.bytedance.com"),
    "omnihuman": ("docs.byteplus.com", "byteplus.com", "seed.bytedance.com"),
    "veo": ("cloud.google.com", "docs.cloud.google.com", "ai.google.dev", "deepmind.google"),
    "sora": ("openai.com", "platform.openai.com", "help.openai.com", "cookbook.openai.com"),
    # OpenAI's other families, added 2026-08-27 when a harvest produced 16 facts
    # from platform.openai.com that the ladder could only call `blog` because
    # nothing declared OpenAI the vendor of anything but Sora.
    "gpt": (
        "openai.com",
        "platform.openai.com",
        "help.openai.com",
        "cdn.openai.com",
        "cookbook.openai.com",
        "huggingface.co/openai/",
    ),
    "imagen": ("cloud.google.com", "ai.google.dev", "deepmind.google"),
    "gemini": ("ai.google.dev", "cloud.google.com", "deepmind.google"),
    # `elevenlabs-*` was declared; their own model ids are `eleven-*`.
    "eleven": ("elevenlabs.io", "help.elevenlabs.io", "docs.elevenlabs.io"),
    # A model card in the AUTHOR'S OWN Hugging Face organisation is the vendor's
    # page, not a platform's. Declared per org and per model family, by path
    # prefix, exactly as `github.com/Wan-Video/` already was — MEASURED: 18
    # facts in the 2026-08-27 harvest were refused because an open-weight
    # model's own card classified as `portal`.
    "hunyuan": ("huggingface.co/tencent/", "huggingface.co/Tencent-Hunyuan/"),
    "ltx": ("huggingface.co/Lightricks/",),
    "mochi": ("huggingface.co/genmo/",),
    "stable-diffusion": ("huggingface.co/stabilityai/", "stability.ai"),
    "qwen": ("huggingface.co/Qwen/", "qwen.ai"),
    "wan": (
        "github.com/Wan-Video/",
        "huggingface.co/Wan-AI/",
        "wan.video",
        "tongyi.aliyun.com",
    ),
    "elevenlabs": ("elevenlabs.io", "help.elevenlabs.io", "docs.elevenlabs.io"),
    # ---- added 2026-08-27 by the applicability harvest, 44 refusals ---------
    #
    # Two kinds of entry, and the difference matters.
    #
    # (a) A SPELLING the family key could not reach. `vendor_sources_for`
    #     matches a key exactly or followed by a separator, so the key
    #     `hunyuan` never matched the model id `hunyuanvideo`, and `wan` never
    #     matched `wan2.1-t2v-1.3b`. Same pages, same vendor, one more key.
    "hunyuanvideo": (
        "huggingface.co/tencent/",
        "huggingface.co/Tencent-Hunyuan/",
        "github.com/Tencent-Hunyuan/",
        "raw.githubusercontent.com/Tencent-Hunyuan/",
    ),
    "hunyuanimage": (
        "huggingface.co/tencent/",
        "huggingface.co/Tencent-Hunyuan/",
        "github.com/Tencent-Hunyuan/",
        "raw.githubusercontent.com/Tencent-Hunyuan/",
    ),
    # `wan2` УДАЛЁН 2026-09-02, и это не уборка, а починка. Ключ существовал
    # только потому, что семья отделялась от версии дефисом и точкой, а вендор
    # пишет `wan2.1-t2v` слитно. С тех пор цифра тоже отделяет — и ключ стал
    # ТЕНЬЮ: он длиннее `wan`, значит побеждает, и все хосты, дописанные к
    # `wan`, до слитных имён не доезжали. ИЗМЕРЕНО на живой базе: 12 имён
    # (wan2.1-*, wan2.2-*) теряли `help.aliyun.com/zh/model-studio/` и
    # `tongyi.aliyun.com` — оба вендорские, оба открылись в тот же день.
    # Найдено не мной, а агентом сбора, который на этот отказ и наткнулся.
    # Инвариант против повторения — `test_ни_один_длинный_ключ_не_беднее_короткого`.
    "qwen3": ("huggingface.co/Qwen/", "github.com/QwenLM/", "qwen.ai"),
    "stable-video": ("huggingface.co/stabilityai/", "stability.ai"),
    #
    # (b) A vendor whose own page is a REPOSITORY. An open-weight model
    #     released by a lab has no docs site; its README in the lab's own org
    #     is the vendor's page in exactly the sense `huggingface.co/Wan-AI/`
    #     already was. Declared per org, by path prefix, never as the bare
    #     host: `raw.githubusercontent.com` as a whole is anybody's writing.
    "cogvideox": ("huggingface.co/THUDM/", "huggingface.co/zai-org/", "github.com/THUDM/"),
    "latentsync": (
        "huggingface.co/ByteDance/",
        "github.com/bytedance/",
        "raw.githubusercontent.com/bytedance/",
    ),
    "wav2lip": ("github.com/Rudrabha/", "raw.githubusercontent.com/Rudrabha/"),
    "musetalk": ("github.com/TMElyralab/", "raw.githubusercontent.com/TMElyralab/"),
    "hallo": (
        "github.com/fudan-generative-vision/",
        "raw.githubusercontent.com/fudan-generative-vision/",
    ),
    "float": (
        "github.com/deepbrainai-research/",
        "raw.githubusercontent.com/deepbrainai-research/",
    ),
    "multitalk": ("github.com/MeiGen-AI/", "raw.githubusercontent.com/MeiGen-AI/"),
    "infinitetalk": ("github.com/MeiGen-AI/", "raw.githubusercontent.com/MeiGen-AI/"),
    "qwen-image": (
        "huggingface.co/Qwen/",
        "github.com/QwenLM/",
        "raw.githubusercontent.com/QwenLM/",
        "qwen.ai",
    ),
    "deepseek": ("huggingface.co/deepseek-ai/", "api-docs.deepseek.com", "deepseek.com"),
    "kimi": ("huggingface.co/moonshotai/", "moonshot.ai", "platform.moonshot.ai"),
    # `platform.minimax.io` добавлен 2026-08-31: это доки самого вендора, и
    # именно там лежит таблица характеристик H3 / H3 Max. Прочитано напрямую
    # (200, dateModified 2026-08-30). Хост не выводится из `minimax.io`
    # автоматически — совпадение здесь точное, и это правильно: поддомен может
    # принадлежать кому угодно. `www.` рядом по той же причине.
    # Аккаунт организации на HuggingFace — это пространство самого вендора, и
    # эти пять добавлены 2026-08-31 ПОСЛЕ чтения их страниц скриптом
    # `ingest_hf.py`: карточка, файлы лицензий и обсуждения открыты у каждого.
    # Без объявления сторож тира отклонял вендорские заявления как `portal`, и
    # он был прав: тир решает URL, а не намерение записывающего.
    # Прочитаны скриптом 2026-08-31 вместе с остальной очередью.
    "anima": ("huggingface.co/circlestone-labs/",),
    "pocket": ("huggingface.co/kyutai/",),
    "gemma": ("huggingface.co/google/", "ai.google.dev", "deepmind.google"),
    "chatterbox": ("huggingface.co/ResembleAI/",),
    "indextts": ("huggingface.co/IndexTeam/",),
    "supertonic": ("huggingface.co/Supertone/",),
    "sensenova": ("huggingface.co/sensenova/",),
    "krea": ("huggingface.co/krea/", "huggingface.co/Comfy-Org/Krea-2"),
    "minimax": (
        "huggingface.co/MiniMaxAI/",
        "minimax.io",
        "www.minimax.io",
        "platform.minimax.io",
        "platform.minimaxi.com",
    ),
    # ---- добавлено 2026-09-02 после перепрощупывания карты достижимости ----
    #
    # Эти хосты стояли в журнале отказов с 2026-08-27 и НЕ перепроверялись,
    # потому что код, увидев `refused`, обходит хост стороной. Прощупывание
    # всех 214 отказанных хостов показало, что 18 из них отвечают, и вот эти
    # пять — документация самих вендоров. Каждая страница открыта и прочитана
    # глазами 2026-09-02, титул приведён рядом: домен, отдающий 200, ещё не
    # доказывает, что за ним вендор, а не припаркованная страница.
    #
    # Без объявления факт с такой страницы ложится на `blog` — нижнюю ступень,
    # — и вендорское заявление весит как чужой пост. Тир решает URL, и это
    # правильно; поэтому цена молчания таблицы измеряется прямо здесь.
    #
    # `mistral` заведён отдельным ключом рядом с `voxtral`: в базе три модели
    # семейства (mistral-large-3, mistral-medium-3.5, mistral-small-4), и ключ
    # `voxtral` до них не дотягивается — совпадение идёт по началу имени.
    "mistral": (
        "huggingface.co/mistralai/",
        "mistral.ai",
        # <title>Documentation - Mistral AI</title>, 200, 2026-09-02
        "docs.mistral.ai",
        "api.mistral.ai",
    ),
    # <title>API Overview | Ideogram | Documentation</title>, 200, 2026-09-02
    "ideogram": ("developer.ideogram.ai", "about.ideogram.ai", "ideogram.ai"),
    # ЛИПСИНК-МОДЕЛИ ALIBABA, не заведённые ни разу, — а репозиторий про липсинк.
    # Найдены агентом сбора на открывшейся странице Model Studio; имена
    # проверены мной там же 2026-09-02 (Ц10: имя доказывается страницей, а не
    # памятью) — `VideoRetalk`, `LivePortrait`, `emoji-v1`,
    # `video-style-transform` присутствуют на
    # help.aliyun.com/zh/model-studio/video-generation.
    #
    # Строк о них в базе НОЛЬ, и это не довод против записи, а довод за: пока
    # семья не объявлена, факт с вендорской страницы ложится на `blog`, то есть
    # первый же сбор обесценит сам себя.
    "videoretalk": ("help.aliyun.com/zh/model-studio/", "tongyi.aliyun.com"),
    "liveportrait": ("help.aliyun.com/zh/model-studio/", "tongyi.aliyun.com"),
    "emoji": ("help.aliyun.com/zh/model-studio/", "tongyi.aliyun.com"),
    "video-style-transform": ("help.aliyun.com/zh/model-studio/", "tongyi.aliyun.com"),
}

#: Хосты, дописанные к УЖЕ ОБЪЯВЛЕННЫМ семьям тем же прощупыванием 2026-09-02.
#: Отдельным словарём, а не правкой строк выше: так видно, что именно принесло
#: перепрощупывание, и одно знание остаётся в одном месте (Е1) — таблица выше
#: не переписывается, а дополняется.
#:
#: `help.aliyun.com` объявлен С ПУТЁМ: под этим хостом лежит вся документация
#: Alibaba Cloud, и объявить его целиком значило бы выдать вендорский тир
#: страницам про базы данных и биллинг. Путь `/zh/model-studio/` — это Model
#: Studio, где живут страницы Wan и Qwen; ровно этот адрес и стоял в журнале
#: отказов («Wan 2.6 Flash supported output resolutions»).
ОТКРЫЛИСЬ_2026_09_02: dict[str, tuple[str, ...]] = {
    # <title>The frontier of visual intelligence - Black Forest Labs</title>
    "flux": ("docs.bfl.ml", "bfl.ml"),
    # <title>Kimi API Platform</title>
    "kimi": ("platform.kimi.ai", "kimi.ai"),
    # <title>…百炼-阿里云…</title> — Model Studio, страницы Wan и Qwen
    "wan": ("help.aliyun.com/zh/model-studio/",),
    # Три ключа, а не один: `vendor_sources_for` берёт САМОЕ ДЛИННОЕ совпадение,
    # поэтому `qwen-image` читает свою запись и запись `qwen` не видит вовсе.
    # Дописать только к короткому ключу значило бы починить одну модель из трёх
    # (И7: чинить по месту — чинить пятую часть).
    "qwen": ("help.aliyun.com/zh/model-studio/", "tongyi.aliyun.com"),
    "qwen3": ("help.aliyun.com/zh/model-studio/", "tongyi.aliyun.com"),
    "qwen-image": ("help.aliyun.com/zh/model-studio/", "tongyi.aliyun.com"),
    # Та же ловушка длинного ключа: `voxtral-small-24b` совпадает с `voxtral`,
    # а до заведённого рядом `mistral` не дотягивается никогда.
    "voxtral": ("docs.mistral.ai", "api.mistral.ai"),
}

for _семья, _хосты in ОТКРЫЛИСЬ_2026_09_02.items():
    VENDOR_SOURCES[_семья] = tuple(dict.fromkeys(VENDOR_SOURCES[_семья] + _хосты))

#: CHOSEN the same way. A portal here is a platform that RUNS models or hosts
#: the artifacts people made with them — it publishes what its own API takes,
#: or the prompts and results themselves. An aggregator that merely resells API
#: access still qualifies: what it documents is a running endpoint.
#:
#: `huggingface.co`, `replicate.com` and `civitai.com` are listed although
#: nothing cites them yet; they are the canonical shape of this rung, and a
#: table that only lists what has already been seen teaches nobody what belongs.
#: `docs.dev.runwayml.com` is on BOTH tables and that is the point: `vendor`
#: is checked first and wins for the `runway-gen` family, so Runway's own API
#: reference is the vendor's page for Gen-4.5 and a platform's page for the
#: Veo, Seedance and Kling endpoints it resells. One host, two rungs, decided
#: by which model the claim is about — which is what "whose page is it" means
#: once a platform starts running other people's models.
#:
#: `reddit.com/r/comfyui/` and not `reddit.com`: a subreddit where people post
#: workflows with the results they got is the middle rung; the rest of Reddit
#: is a forum. This is what the path prefix is for. Add a sibling community the
#: same way — one line, `reddit.com/r/<name>/`.
#:
#: `raw.githubusercontent.com/Comfy-Org/` on the same principle, added
#: 2026-08-30. ComfyUI's official template registry is a platform that RUNS
#: models: its templates are EXECUTABLE graphs, and a closed model appears in
#: them as the node type that calls it, not as a description of one. MEASURED
#: that day — `templates/api_google_nano_banana2_image_edit.json` is three
#: nodes, `LoadImage -> GeminiNanoBanana2V2 -> SaveImage`; the index lists 8
#: nano_banana templates and 84 mentions of Kling. A graph that runs is a
#: statement about a running system, which is what this rung is for.
#:
#: The prefix is the whole point: the rest of `raw.githubusercontent.com` is
#: anybody's repository and stays `blog`. Comfy-Org's own repositories are the
#: platform speaking.
PORTAL_SOURCES: tuple[str, ...] = (
    "apiframe.ai",
    "raw.githubusercontent.com/Comfy-Org/",
    "atlascloud.ai",
    "civitai.com",
    "docs.dev.runwayml.com",
    "api.dev.runwayml.com",
    "evolink.ai",
    "fal.ai",
    "gaga.art",
    "huggingface.co",
    "openart.ai",
    "piapi.ai",
    "prompthero.com",
    "reddit.com/r/comfyui/",
    "old.reddit.com/r/comfyui/",
    "replicate.com",
    "wavespeed.ai",
)

#: A portal's own writing is writing, not its API. `atlascloud.ai/blog/tips/
#: kling-ai-video-length-limit` is an article that happens to sit on a platform,
#: and it earns the platform's rung no more than a vendor's press page earns a
#: measurement. Matched as a whole path segment, so `/blogging-api/` is not one.
#:
#: MEASURED: 1 of the 11 portal URLs in the base is such a page.
BLOG_PATH_SEGMENTS: frozenset[str] = frozenset(
    {"blog", "blogs", "news", "press", "review", "reviews"}
)

#: Path segments where SOMEBODY ELSE wrote the page, on whoever's host.
#:
#: This is a different question from `BLOG_PATH_SEGMENTS` and the distinction
#: is the whole point. A `/blog/` page on a vendor's host was written BY THE
#: VENDOR — it is their word, just a marketing shape of it. A `/discussions/`
#: page on the same host was written by a USER, and the vendor merely hosts it.
#: The ladder asks "whose page is this", and on these paths the answer is not
#: the host's owner however the domain is declared.
#:
#: Found on 2026-08-28 by an independent review of a plan to harvest Hugging
#: Face discussion threads as community evidence. VERIFIED on the shipped code
#: before this existed: `classify("ltx-2.5",
#: "https://huggingface.co/Lightricks/LTX-2.5/discussions/12")` returned
#: `vendor`, because `huggingface.co/Lightricks/` is declared as the vendor's
#: org for the `ltx` family. A user's complaint would have entered the base on
#: the ladder's strongest rung and outranked the vendor's own model card.
USER_WRITTEN_SEGMENTS: frozenset[str] = frozenset(
    {"discussions", "issues", "community", "forum", "comments", "pull"}
)

#: Площадки, ГДЕ ПОЛЬЗОВАТЕЛЬСКОЕ И ЕСТЬ СОДЕРЖАНИЕ. На них сегмент из набора
#: выше ничего не понижает: люди выкладывают воркфлоу с результатами, и это
#: ровно то, ради чего площадка объявлена порталом (решение владельца
#: 2026-08-27 про `reddit.com/r/comfyui/`).
#:
#: Для всех ОСТАЛЬНЫХ порталов обсуждение — не голос площадки, а голос
#: посетителя, и оно понижается. Без этого различия одно и то же обсуждение
#: получало РАЗНЫЙ тир в зависимости от формы ссылки: ИЗМЕРЕНО 2026-08-31,
#: `huggingface.co/MiniMaxAI/MiniMax-H3/discussions/42` давал `blog`, а
#: `huggingface.co/api/models/MiniMaxAI/MiniMax-H3/discussions` — `portal`,
#: потому что понижение применялось только внутри вендорской ветки. Один и тот
#: же текст, две ступени, и решала форма URL, которую записывающий выбрал
#: случайно.
PORTALS_WHERE_USERS_ARE_THE_POINT: frozenset[str] = frozenset(
    {"reddit.com/r/comfyui/", "old.reddit.com/r/comfyui/", "civitai.com", "prompthero.com"}
)

_HOST = re.compile(r"https?://([^/:?#]+)", re.I)


def host_of(url: str) -> str:
    """The host, lowercased and without a leading `www.`. "" when not a URL."""
    match = _HOST.match(str(url or "").strip())
    if not match:
        return ""
    host = match.group(1).lower()
    return host[4:] if host.startswith("www.") else host


def _path_of(url: str) -> str:
    text = str(url or "").strip()
    match = _HOST.match(text)
    if not match:
        return ""
    return text[match.end() :].split("?", 1)[0].split("#", 1)[0]


def _matches(url: str, entry: str) -> bool:
    """Does `url` sit under `entry`, which is a host or a host/path-prefix?"""
    host, _, prefix = entry.partition("/")
    if host_of(url) != host.lower():
        return False
    if not prefix:
        return True
    return _path_of(url).lstrip("/").lower().startswith(prefix.lower())


def vendor_sources_for(model: str) -> tuple[str, ...]:
    """The pages this model's own vendor controls, by family. () when unknown.

    Longest family wins, so a more specific key added later overrides a broader
    one without the broader one having to be touched.

    ЦИФРА ТОЖЕ ОТДЕЛЯЕТ СЕМЬЮ ОТ ВЕРСИИ, и это правка формы, а не места.
    Вендоры пишут версию слитно — `wan2.1`, `flux2-klein`, `qwen2.5-omni`,
    `seedance2_5`, — и разделительное правило такие имена не ловило. Дефект
    чинился ПО МЕСТУ трижды: ключами `wan2`, `hunyuanvideo`, `qwen3`. Ключ на
    каждую слитную версию — это правило, которое будет неверным к следующему
    релизу, а прошлая редакция этой же таблицы уже поймала себя на том же
    (запись про `veo-3` против `veo-3.1` в шапке).

    ИЗМЕРЕНО 2026-09-02 на живой базе (489 моделей): 27 моделей получают
    источники своего вендора и НИ ОДНА не меняет семью на чужую. Совпадение
    идёт только по ЦИФРЕ после ключа, поэтому `sdxl` по-прежнему не читает
    запись `sd`, а `wandering-model` — запись `wan`.

    ЧТО ЭТО НЕ ЧИНИТ, сказано вслух: имя вида `krea2turbonsfwaio` — это
    пользовательская LoRA, названная по модели, и она получает страницы Krea,
    хотя её автор не Krea. Класс не новый: `qwen-edit-skin` получал страницы
    Qwen и по старому правилу. Отличать «версия вендора» от «имени в честь
    вендора» этот прибор не умеет, и границу правильнее держать записанной,
    чем притворяться, что её нет.
    """
    name = str(model or "").strip().lower()
    if not name:
        return ()
    best = ""
    for family in VENDOR_SOURCES:
        low = family.lower()
        слитная_версия = name.startswith(low) and len(name) > len(low) and name[len(low)].isdigit()
        if (
            name == low
            or any(name.startswith(low + sep) for sep in FAMILY_SEPARATORS)
            or слитная_версия
        ):
            if len(low) > len(best):
                best = low
    return VENDOR_SOURCES[best] if best else ()


def classify(model: str, url: str, *, vendor_tier: str, portal_tier: str, blog_tier: str) -> str:
    """Which rung this URL sits on for this model: vendor, portal, or blog.

    The tiers are passed in rather than imported so that this module holds the
    table and `facts.py` holds the ladder; one name for the ladder, one name
    for who owns what, and no second copy of either.

    Anything not named in a table is `blog` — that is what "and everything
    else" means, and an unknown host is exactly the case the third rung is for.
    """
    if not host_of(url):
        return blog_tier
    segments = {s for s in _path_of(url).lower().split("/") if s}
    for entry in vendor_sources_for(model):
        if _matches(url, entry):
            # The vendor's HOST, but not the vendor's WORD: on these paths
            # somebody else wrote the page and the vendor merely hosts it.
            #
            # Applied only here, inside the vendor branch, and that limit was
            # taught by a test rather than chosen: checking it first demoted
            # `reddit.com/r/comfyui/`, which the OWNER declared a portal on
            # 2026-08-27 precisely because people post workflows with the
            # results they got. For a declared community portal, user-written
            # is what it IS and the middle rung was granted knowingly. The
            # question this rule answers is narrower than "who typed it" — it
            # is "is the vendor speaking here", and only the top rung claims
            # that.
            if segments & USER_WRITTEN_SEGMENTS:
                return blog_tier
            return vendor_tier
    for entry in PORTAL_SOURCES:
        if _matches(url, entry):
            if segments & BLOG_PATH_SEGMENTS:
                return blog_tier
            if entry not in PORTALS_WHERE_USERS_ARE_THE_POINT and segments & USER_WRITTEN_SEGMENTS:
                return blog_tier
            return portal_tier
    return blog_tier
