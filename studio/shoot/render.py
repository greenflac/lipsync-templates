"""Рендер одного плана на ComfyUI с записью попытки в журнал производства.

Раньше рендер жил в черновиках агента (`run_h3.py`, `run_job.py` в scratchpad)
и не оставлял следа, кроме mp4: какой промпт, сид и веса дали этот файл, можно
было восстановить только по памяти. Для массового контента это неприемлемо —
см. `studio.shoot.journal`. Здесь каждая попытка пишет строку `render`
(сид, хеш промпта, рефы, веса, GPU-секунды, цена) и строку `qa`.

Сеть — через curl: urllib через прокси RunPod 2026-10-07 получал 403, curl —
нет. Тестами не покрыт сетевой путь; покрыта сборка записи (`render_event`).
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from studio.shoot import journal, qa
from studio.shoot.compile import Compiled, compile_shot
from studio.shoot.h3graph import CLIP, UNET, build
from studio.shoot.spec import Production


def _curl(args: list[str], timeout: int = 120) -> str:
    return subprocess.run(
        ["curl", "-sS", "-m", str(timeout), *args], capture_output=True, text=True
    ).stdout


#: Секунд GPU на секунду ролика, если журнал ещё ничего не знает. НАБЛЮДЕНО
#: 2026-10-07 на RTX PRO 6000, int8, 768×1344, 20 шагов: 5 с → 186 с,
#: 6 с → 280 с, 8 с → 413 с, 10 с → 610 с (≈ 37–61 с/с, растёт с длиной).
DEFAULT_GPU_S_PER_S = 55.0


def gpu_s_per_second(rows: list[dict[str, Any]]) -> float:
    """Медиана по уже сделанным рендерам этого производства; иначе — наблюдённое значение."""
    rates = sorted(
        float(r["gpu_s"]) / float(r["seconds"])
        for r in rows
        if r.get("kind") == "render" and r.get("gpu_s") and r.get("seconds")
    )
    return rates[len(rates) // 2] if rates else DEFAULT_GPU_S_PER_S


def estimate_usd(
    prod: Production, ids: list[str], rows: list[dict[str, Any]], rate: float
) -> float:
    """Цена пакета по GPU-секундам. Простой пода сверху не учтён — его видно в строках cost."""
    secs = sum(s.seconds for s in prod.shots if s.id in ids)
    return secs * gpu_s_per_second(rows) / 3600 * rate


def spent_usd(rows: list[dict[str, Any]]) -> float:
    """Сколько уже списал провайдер по строкам cost журнала."""
    return sum(float(r.get("cost_usd") or 0) for r in rows if r.get("kind") == "cost")


def budget_problem(
    budget: float, prod: Production, ids: list[str], rows: list[dict[str, Any]], rate: float
) -> str:
    """Пусто — пакет влезает в бюджет. Иначе — почему нет.

    НАБЛЮДЕНО 2026-10-07: баланс RunPod кончился посреди производства, под
    остановлен в 18:19:48 UTC, рендер S02 потерян, а с диском контейнера — 60 ГБ
    полных весов. Пакет, не влезающий в остаток, теперь не запускается.
    """
    if budget <= 0:
        return ""
    need = estimate_usd(prod, ids, rows, rate)
    have = budget - spent_usd(rows)
    if need > have:
        return f"пакет ≈ ${need:.2f} по GPU, а в бюджете осталось ${have:.2f} из ${budget:.2f}"
    return ""


def preflight(base_url: str, graph: dict[str, Any]) -> list[str]:
    """Сервер жив и нужные веса на месте — до отправки, а не через час ожидания."""
    need = {
        ("diffusion_models", graph["1"]["inputs"]["unet_name"]),
        ("text_encoders", graph["2"]["inputs"]["clip_name"]),
        ("vae", graph["3"]["inputs"]["vae_name"]),
        ("vae", graph["4"]["inputs"]["vae_name"]),
    } | {
        ("loras", n["inputs"]["lora_name"])
        for n in graph.values()
        if n.get("class_type") == "LoraLoaderModelOnly"
    }
    out: list[str] = []
    listed: dict[str, list[str]] = {}
    for folder, name in sorted(need):
        if folder not in listed:
            try:
                listed[folder] = json.loads(_curl([f"{base_url}/models/{folder}"], 30) or "null")
            except ValueError:
                return [f"ComfyUI не отвечает JSON на {base_url}/models/{folder}: под выключен?"]
            if not isinstance(listed[folder], list):
                return [f"ComfyUI недоступен ({base_url})"]
        if name not in listed[folder]:
            out.append(f"на сервере нет {folder}/{name}")
    return out


def render_event(
    c: Compiled,
    rig: str,
    gpu_s: float,
    outcome: str,
    file: str,
    rate_usd_h: float,
    graph: dict[str, Any],
    note: str = "",
) -> dict[str, Any]:
    """Строка журнала о попытке. Отдельно от сети — чтобы её можно было проверить тестом."""
    unet = graph.get("1", {}).get("inputs", {}).get("unet_name", UNET)
    clip = graph.get("2", {}).get("inputs", {}).get("clip_name", CLIP)
    loras = [
        n["inputs"]["lora_name"]
        for n in graph.values()
        if n.get("class_type") == "LoraLoaderModelOnly"
    ]
    return {
        "kind": "render",
        "stage": "render",
        "by": "pipeline",
        "shot": c.shot_id,
        "summary": f"{c.shot_id}: {c.seconds} с, {rig}, сид {c.seed} — {outcome}",
        "outcome": outcome,
        "seed": c.seed,
        "seconds": c.seconds,
        "size": f"{c.width}x{c.height}",
        "rig": rig,
        "prompt_sha": hashlib.sha256(c.prompt.encode()).hexdigest()[:12],
        "refs": [Path(r).name for r in c.refs],
        "weights": {"unet": unet, "clip": clip, "loras": loras},
        "gpu_s": round(gpu_s, 1),
        "rate_usd_h": rate_usd_h,
        "cost_usd": round(gpu_s / 3600 * rate_usd_h, 4),
        "file": file,
        "note": note,
    }


def render_shot(
    prod: Production,
    prod_dir: Path,
    shot_id: str,
    out_dir: Path,
    base_url: str,
    rate_usd_h: float,
    timeout_s: int = 3600,
    unet: str = UNET,
    clip: str = CLIP,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Отрендерить план, прогнать QA, записать обе строки в `prod_dir/journal.jsonl`."""
    shot = next(s for s in prod.shots if s.id == shot_id)
    c = compile_shot(prod, shot)
    out_dir.mkdir(parents=True, exist_ok=True)
    names: dict[str, str] = {}
    for ref in c.refs:
        path = (prod_dir / ref).resolve()
        _curl(
            [
                "-X",
                "POST",
                f"{base_url}/upload/image",
                "-F",
                f"image=@{path};filename={path.name}",
                "-F",
                "overwrite=true",
            ]
        )
        names[ref] = path.name
    stamp = time.strftime("%H%M%S")
    graph = build(c, f"shoot/{shot_id}_{stamp}", uploaded=names, unet=unet, clip=clip)
    jpath = prod_dir / "journal.jsonl"
    missing = preflight(base_url, graph)
    if missing:
        ev = render_event(c, shot.rig, 0, "не смогли", "", rate_usd_h, graph, "; ".join(missing))
        return journal.append(jpath, ev), None
    (out_dir / f"{shot_id}_{stamp}.prompt.txt").write_text(c.prompt + "\n", encoding="utf-8")
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"prompt": graph, "client_id": "studio.shoot"}, f)
    answer = _curl(
        [
            "-X",
            "POST",
            f"{base_url}/prompt",
            "-H",
            "Content-Type: application/json",
            "--data",
            "@" + f.name,
        ]
    )
    os.unlink(f.name)
    t0 = time.time()
    try:
        pid = json.loads(answer)["prompt_id"]
    except (ValueError, KeyError):
        ev = render_event(
            c, shot.rig, 0, "не смогли", "", rate_usd_h, graph, f"отказ: {answer[:300]}"
        )
        return journal.append(jpath, ev), None
    mp4 = out_dir / f"{shot_id}_{stamp}.mp4"
    outcome, note = "не смогли", "таймаут"
    while time.time() - t0 < timeout_s:
        # НАБЛЮДЕНО 2026-10-07: прокси RunPod изредка отдаёт не-JSON (страницу
        # ошибки) — черновой раннер S02 на этом упал, бросив готовый рендер.
        try:
            hist = json.loads(_curl([f"{base_url}/history/{pid}"]) or "{}")
        except ValueError:
            time.sleep(10)
            continue
        if hist:
            v = next(iter(hist.values()))
            o = v.get("outputs", {}).get("19", {})
            files = o.get("images", []) + o.get("videos", [])
            if files:
                x = files[0]
                _curl(
                    [
                        "-o",
                        str(mp4),
                        f"{base_url}/view?filename={x['filename']}"
                        f"&subfolder={x.get('subfolder', '')}&type={x.get('type', 'output')}",
                    ],
                    600,
                )
                outcome, note = "годно", f"prompt_id {pid}"
            else:
                note = f"ComfyUI: {json.dumps(v.get('status', {}))[-300:]}"
            break
        time.sleep(10)
    gpu_s = time.time() - t0
    rep = qa.measure(str(mp4), shot.rig) if mp4.exists() else None
    if rep is not None and rep.outcome != "годно":
        outcome = rep.outcome
    rev = journal.append(
        jpath,
        render_event(
            c, shot.rig, gpu_s, outcome, str(mp4) if mp4.exists() else "", rate_usd_h, graph, note
        ),
    )
    qev = None
    if rep is not None:
        qev = journal.append(
            jpath,
            {
                "kind": "qa",
                "stage": "render",
                "by": "pipeline",
                "shot": shot_id,
                "of": rev["id"],
                "summary": f"{shot_id}: QA {rep.outcome}",
                "outcome": rep.outcome,
                "metrics": {
                    "jitter_pct": rep.jitter_pct,
                    "zoom": rep.zoom,
                    "cuts": rep.cuts,
                    "audio_peak": rep.audio_peak,
                    "audio_rms_db": rep.audio_rms_db,
                },
                "notes": rep.notes,
                "text_seen": rep.text_seen,
                "sheet": rep.sheet,
            },
        )
    return rev, qev
