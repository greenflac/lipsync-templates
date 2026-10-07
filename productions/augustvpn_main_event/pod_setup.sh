#!/usr/bin/env bash
# Подготовка пода к рендеру после остановки. Выполняется НА ПОДЕ, идемпотентно:
#   POD_JUPYTER_PW=… python -m studio.shoot.pod <POD_ID> --file pod_setup.sh 1800
#
# ПОЧЕМУ ОН НУЖЕН. 2026-10-07 под остановился, когда кончился баланс. Остановка
# стирает диск контейнера, а полные int8-веса и оба VAE лежали в /root/h3 —
# ссылки на них в ComfyUI стали битыми. Постоянный диск /workspace уцелел:
# на нём ComfyUI и контрольный набор весов (pruned fp8 + nvfp4) в /workspace/h3ctl.
# Теперь всё качается только на /workspace.
set -euo pipefail
W=/workspace/h3ctl
M=/workspace/runpod-slim/ComfyUI/models

mkdir -p "$W/vae"
for f in vae/minimax_h3_video_vae_fp16.safetensors vae/minimax_h3_audio_vae_fp32.safetensors; do
  [ -s "$W/$f" ] || hf download Comfy-Org/MiniMax-H3 "$f" --local-dir "$W"
done

# Битые ссылки на стёртый /root/h3 — убрать, чтобы список моделей не врал.
find "$M" -xtype l -print -delete

for d in diffusion_models text_encoders vae; do
  mkdir -p "$M/$d"
  for f in "$W/$d"/*.safetensors; do ln -sf "$f" "$M/$d/$(basename "$f")"; done
done

echo "== веса на месте:"
ls -la "$M/diffusion_models" "$M/text_encoders" "$M/vae" | grep -i minimax
echo "== рендеры, пережившие остановку (S02 мог успеть):"
ls -la /workspace/runpod-slim/ComfyUI/output/h3/ 2>/dev/null | tail -5 || true
ls -la /workspace/runpod-slim/ComfyUI/output/shoot/ 2>/dev/null | tail -5 || true
nvidia-smi --query-gpu=name,driver_version,memory.used --format=csv
