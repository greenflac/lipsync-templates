# Runbook: день рендера после пополнения баланса

Цель — **GPU без простоя**. 2026-10-07 на генерацию ушло около 25 % оплаченного
времени пода (`POSTMORTEM.md`, раздел 3). Под включается, когда всё готово
локально, рендерит одной очередью и сразу выключается.

Оценка (`studio.shoot.render.estimate_usd`, медиана 55 GPU-с на секунду ролика):
11 планов, 71 с видео — **$2.27 GPU**, плюс около 15 минут на подготовку пода.

## 0. До включения пода (бесплатно)

```bash
python -m studio.shoot validate productions/augustvpn_main_event/production.json   # годно
python -m studio.shoot journal  productions/augustvpn_main_event/production.json   # журнал чист
```

Бюджет заказа записать в `production.json` → `budget_usd`. Без него проверка
бюджета выключена, и пакет может снова упереться в нулевой баланс.

## 1. Включить под

Под `lcjxwt6oyt143l` (RTX PRO 6000, $2.09/ч) запускается через MCP RunPod:
`pod-action {"action":"start"}`. Пароль JupyterLab — в `env.JUPYTER_PASSWORD`
из `get-pod`. В журнал и в git он не попадает.

## 2. Подготовить веса (на поде)

```bash
POD_JUPYTER_PW=… python -m studio.shoot.pod lcjxwt6oyt143l \
    --file productions/augustvpn_main_event/pod_setup.sh 1800
```

Скрипт скачивает VAE на постоянный диск, чистит битые ссылки на стёртый
`/root/h3`, подключает контрольный набор весов и показывает, пережил ли
остановку рендер S02.

## 3. Пробный пакет: два плана, проверка исправлений

```bash
export COMFY_URL=https://lcjxwt6oyt143l-8188.proxy.runpod.net GPU_RATE_USD_H=2.09
export H3_UNET=minimax_h3_ref2va_pruned_fp8_scaled.safetensors
export H3_CLIP=qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors
python -m studio.shoot render productions/augustvpn_main_event/production.json OUT S04_faceoff_wide S01_announce
```

Глазами по контактным листам (`OUT/*.sheet.jpg`):

* на канвасе нет UFC/OFC, только SECURITY ARENA (реф канваса);
* у конферансье нет перчатки;
* в S04 Адгар выше Августа, перчатки без букв.

Не годно — исправить `production.json`, повторить шаг 3. Пока это делается,
**под выключить**: правка промпта может занять больше 10 минут.

## 4. Основной пакет

```bash
python -m studio.shoot render productions/augustvpn_main_event/production.json OUT \
    S02_intro_adgar S03_intro_august S05_ots_august S06_adgar_boast S07_bell_lag \
    S08_booth S09_disconnect S10_popups S11_winner
```

Каждая попытка сама пишется в `journal.jsonl`. План, который QA забраковал,
перезапускается с другим `seed` в `production.json`, а не руками в ComfyUI:
иначе журнал не узнает, какой сид дал принятый дубль.

## 5. Сразу после пакета

1. **Выключить под** (`pod-action {"action":"stop"}`).
2. Записать в журнал строку `cost` из `list-pod-billing` за день рендера.
3. Записать приёмку каждого плана: `python -m studio.shoot log … review edit owner|agent "…" shot=… outcome=годно`.
