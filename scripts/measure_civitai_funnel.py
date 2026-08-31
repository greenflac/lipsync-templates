#!/usr/bin/env python3
"""Почему промтов с Civitai всего 473, если там их миллионы.

    python scripts/measure_civitai_funnel.py

Вопрос владельца 2026-08-31. Ответ измерен, а не выведен рассуждением, и он
оказался не тем, что ожидалось: дело не в API и не в размере прогона.

ИЗМЕРЕНО 2026-08-31, три страницы по 100 моделей, Most Downloaded / AllTime:

    версий всего                              4443
    прошло МОДЕЛЬНЫЙ фильтр (nsfwLevel & ~3)   558   (12.6%)
    отсеяно                                   3885   (87.4%)

    у прошедших:  25 версий -> 73 картинки  -> 39 годных промтов = 1.6 на версию
    у отсеянных:  25 версий -> 232 картинки -> 138 годных промтов = 5.5 на версию

    на этих 300 моделях при нынешнем фильтре      ~870 промтов
    без МОДЕЛЬНОГО фильтра, только по картинке  ~22 300 промтов

То есть модельный фильтр стоит примерно 96% доступного объёма. И отсеянные
модели ПРОМТОВЕЕ прошедших втрое с половиной: это популярные общественные
чекпойнты с большими витринами.

ЧТО ИМЕННО ОТСЕИВАЕТСЯ. `ALLOWED_MODEL_LEVELS = 3` роняет версию, если МОДЕЛЬ
хоть где-то публикует материал выше PG-13 — даже когда сама собираемая картинка
имеет уровень 1 или 2. Это второй, куда более грубый фильтр поверх фильтра по
картинке (`MAX_NSFW_LEVEL = 2`), который и так работает поштучно. У 138 из 205
отсеянных промтов картинка сама по себе проходит потолок.

Решение о том, оставлять ли модельный фильтр, принимает владелец: это вопрос
политики сервиса, а не техники. Скрипт печатает числа, чтобы решение принималось
по ним.

СИД зафиксирован, выборка воспроизводится.
"""

import json
import subprocess
import sys
import time
import random

sys.path.insert(0, "/home/user/lipsync-templates")
from studio.mcp import civitai as C

UA = "Mozilla/5.0"


def get(u):
    r = subprocess.run(
        ["curl", "-sL", "-A", UA, "--max-time", "60", u], capture_output=True, check=False
    )
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}


refs = []
for page in (1, 2, 3):
    d = get(
        f"https://civitai.com/api/v1/models?limit=100&page={page}&sort=Most%20Downloaded&period=AllTime"
    )
    refs += C.version_refs(d)
    time.sleep(0.5)

kept = [r for r in refs if not C._publishes_above_ceiling(r)]
blocked = [r for r in refs if C._publishes_above_ceiling(r)]
rng = random.Random(20260831)
sample_k = rng.sample(kept, min(25, len(kept)))
sample_b = rng.sample(blocked, min(25, len(blocked)))


def yield_of(sample, label):
    imgs = prompts = safe_prompts = 0
    for r in sample:
        d = get(C.VERSION_URL.format(id=r["version_id"]))
        for i in d.get("images", []):
            imgs += 1
            meta = i.get("meta") or {}
            text = str(meta.get("prompt") or "")
            if len(text.split()) >= C.MIN_PROMPT_WORDS:
                prompts += 1
                lvl = i.get("nsfwLevel")
                if isinstance(lvl, int) and lvl <= C.MAX_NSFW_LEVEL:
                    safe_prompts += 1
        time.sleep(0.4)
    n = len(sample)
    print(
        f"{label}: версий {n} | картинок {imgs} | с промтом {prompts} | и уровень<=2: {safe_prompts}"
    )
    print(
        f"   -> промтов на версию: {safe_prompts / max(n, 1):.1f} (годных), {prompts / max(n, 1):.1f} (всего с промтом)"
    )
    return safe_prompts / max(n, 1), prompts / max(n, 1)


print(f"версий всего {len(refs)} | прошло модельный фильтр {len(kept)} | отсеяно {len(blocked)}")
ok_rate, _ = yield_of(sample_k, "ПРОШЕДШИЕ модельный фильтр")
bl_ok, bl_all = yield_of(sample_b, "ОТСЕЯННЫЕ моделью (у самих картинок уровень<=2)")
print()
print(
    f"на 300 моделей ({len(refs)} версий) при нынешнем фильтре: ~{ok_rate * len(kept):.0f} промтов"
)
print(
    f"если снять МОДЕЛЬНЫЙ фильтр, оставив только фильтр по КАРТИНКЕ: ~{ok_rate * len(kept) + bl_ok * len(blocked):.0f}"
)
