#!/usr/bin/env bash
# Развёртывание стека на чистом GPU-поде RunPod с сетевым томом в /workspace.
# Идемпотентно: повторный запуск докачивает только недостающее.
#
#   POD_JUPYTER_PW=… python -m studio.shoot.pod <POD_ID> --file pod_bootstrap.sh 60
#   (скрипт уходит в фон; ход — в /workspace/bootstrap.log)
#
# ПОЧЕМУ ТАК (2026-10-08). У прежних подов /workspace был локальным диском
# хоста: после остановки хост отдал GPU другим, под не стартовал, а две
# миграции диска между хостами зависли. Теперь модели лежат на сетевом томе
# дата-центра, и GPU-под на нём пересоздаётся на любой машине. Всё, что нужно
# для генерации, качается отсюда с закреплённых ревизий — ничего руками.
#
# Образ пода: runpod/comfyui:1.4.0-comfyuiv0.35.0-cuda13.0 (ComfyUI v0.35.0,
# в нём нативные ноды MiniMax H3 и Fun ControlNet).
set -euo pipefail

if [ "${1:-}" != "--fg" ]; then
  cp "$0" /workspace/pod_bootstrap.sh 2>/dev/null || true
  nohup bash /workspace/pod_bootstrap.sh --fg > /workspace/bootstrap.log 2>&1 &
  echo "bootstrap запущен в фоне: tail -f /workspace/bootstrap.log"
  exit 0
fi

H3_REPO=Comfy-Org/MiniMax-H3
H3_REV=e5eb578a89295337b8ff433a035929ce0279e0b6
CN_REPO=alibaba-pai/MiniMax-H3-Fun-Controlnet-Union-2.0
CN_REV=7d2c95de2e351ed6a0b360af45f62daa04c26f88
W=/workspace/models
export HF_XET_HIGH_PERFORMANCE=1

echo "== $(date -u +%T) ждём ComfyUI в /workspace/runpod-slim"
for _ in $(seq 1 120); do [ -d /workspace/runpod-slim/ComfyUI/models ] && break; sleep 5; done
M=/workspace/runpod-slim/ComfyUI/models

echo "== $(date -u +%T) веса H3 ($H3_REPO@${H3_REV:0:8})"
for f in diffusion_models/minimax_h3_ref2va_pruned_fp8_scaled.safetensors \
         text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors \
         vae/minimax_h3_video_vae_fp16.safetensors \
         vae/minimax_h3_audio_vae_fp32.safetensors; do
  [ -s "$W/h3/$f" ] || hf download "$H3_REPO" "$f" --revision "$H3_REV" --local-dir "$W/h3"
done

echo "== $(date -u +%T) Fun ControlNet Union 2.0 ($CN_REPO@${CN_REV:0:8})"
f=MiniMax-H3-Fun-Controlnet-Union-2.0.safetensors
[ -s "$W/cn/$f" ] || hf download "$CN_REPO" "$f" --revision "$CN_REV" --local-dir "$W/cn"

echo "== $(date -u +%T) ссылки в ComfyUI"
find "$M" -xtype l -delete
for d in diffusion_models text_encoders vae; do
  mkdir -p "$M/$d"
  for x in "$W/h3/$d"/*.safetensors; do ln -sf "$x" "$M/$d/$(basename "$x")"; done
done
mkdir -p "$M/model_patches"
ln -sf "$W/cn/$f" "$M/model_patches/$f"

echo "== $(date -u +%T) проверка: ComfyUI видит модели"
for d in diffusion_models text_encoders vae model_patches; do
  echo "$d: $(curl -s localhost:8188/models/$d)"
done
nvidia-smi --query-gpu=name,driver_version,memory.total --format=csv
echo "BOOTSTRAP_OK $(date -u +%T)"
