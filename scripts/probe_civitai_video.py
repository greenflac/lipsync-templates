#!/usr/bin/env python3
"""Сколько роликов Civitai несут МОДЕЛЬ в своих метаданных, а не в подписи страницы.

ЗАЧЕМ. Банк валидатора упёрся в отсутствие негативного контроля: все видео в нём
сделаны Kling, поэтому «угадал семейство» там всегда верно и ничего не измеряет.
Владелец предложил Civitai — роликов там действительно много. Вопрос не в
количестве, а в ГРАДЕ ИСТИНЫ: у Kling истина была серверным логом задач самой
площадки, а у Civitai подпись ставит загрузчик.

ИЗМЕРЕНО 2026-08-30, три страницы «Most Downloaded / Month», 60 версий с видео:

    роликов просмотрено                 191
    с полем модели в СВОИХ метаданных    11  (5.8%)
    истина = подпись страницы           180  (94.2%)
    встретившиеся ключи: resources 6, civitaiResources 5, workflow 5

    baseModel страниц: Illustrious 35, MiniMax H3 32, Pony 32, LTXV 2.5 20,
    Wan Video 14B i2v 480p 17, Wan Video 14B t2v 15, Anima 13,
    Wan Video 14B i2v 720p 11, Krea 2 6, ZImageTurbo 4, Flux.1 D 2, NoobAI 2

ЧТО ИЗ ЭТОГО СЛЕДУЕТ. Ролики не-Kling там есть и в количестве — Wan прямо в
нашем списке кандидатов, MiniMax это закрытый вендор. Но 94% из них помечены
словом загрузчика, а не записью исполнения. Это ДРУГОЙ грейд истины, и смешивать
его с логом Kling молча нельзя: процент, посчитанный по шумной метке, шумный.

Скрипт оставлен, чтобы число можно было перепроверить, а не поверить.
"""

import json
import subprocess
import time
import collections

UA = "Mozilla/5.0"
MODEL_KEYS = (
    "Model",
    "model",
    "baseModel",
    "civitaiResources",
    "resources",
    "Model hash",
    "engine",
    "comfy",
    "workflow",
    "extra",
)


def get(url):
    r = subprocess.run(
        ["curl", "-sL", "-A", UA, "--max-time", "60", url], capture_output=True, check=False
    )
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}


version_ids, base_of = [], {}
for page in (1, 2, 3):
    d = get(
        f"https://civitai.com/api/v1/models?limit=40&page={page}&sort=Most%20Downloaded&period=Month"
    )
    for m in d.get("items", []):
        for v in m.get("modelVersions", []):
            if any(i.get("type") == "video" for i in v.get("images", [])):
                version_ids.append(v["id"])
                base_of[v["id"]] = v.get("baseModel") or "?"
    time.sleep(0.4)

version_ids = version_ids[:60]
print(f"версий с видео найдено: {len(version_ids)}")

total = with_model = 0
keyhits = collections.Counter()
bases = collections.Counter()
for vid in version_ids:
    d = get(f"https://civitai.com/api/v1/model-versions/{vid}")
    for item in d.get("images", []):
        if item.get("type") != "video":
            continue
        total += 1
        bases[base_of.get(vid, "?")] += 1
        meta = item.get("meta") or {}
        hit = [k for k in MODEL_KEYS if k in meta]
        if hit:
            with_model += 1
            for k in hit:
                keyhits[k] += 1
    time.sleep(0.4)

print(f"\nроликов просмотрено:            {total}")
print(f"с полем модели в СВОИХ метаданных: {with_model}")
print(f"без него (истина = подпись страницы): {total - with_model}")
print(f"ключи, которые встретились: {dict(keyhits)}")
print("\nbaseModel страницы, к которой ролик приложен:")
for b, n in bases.most_common(12):
    print(f"  {b:24} {n}")
