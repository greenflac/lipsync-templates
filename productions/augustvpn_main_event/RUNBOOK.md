# Runbook: день рендера после пополнения баланса

Цель — **GPU без простоя**. 2026-10-07 на генерацию ушло около 25 % оплаченного
времени пода (`POSTMORTEM.md`, раздел 3). Под включается, когда всё готово
локально, рендерит одной очередью и сразу выключается.

Оценка (`studio.shoot.render.estimate_usd`, медиана 55 GPU-с на секунду ролика):
12 планов, 79 с видео — **$2.52 GPU**, плюс около 15 минут на подготовку пода.

> **СТЕК С 2026-10-08.** Модели на сетевом томе `augustvpn-models`
> (`9n7ddio6vx`, US-NC-2, 200 ГБ). GPU-под `augustvpn-h3-netvol` (`95ukq3ajnnl2f3`,
> RTX PRO 6000, $2.09/ч). Пароль JupyterLab — в `env.JUPYTER_PASSWORD` из
> `get-pod`, в git не попадает. Новый под на этом томе разворачивается
> скриптом `productions/augustvpn_v2/pod_bootstrap.sh` примерно за 1.5 мин:
> он качает модели с закреплённых ревизий Hugging Face и проверяет, что
> ComfyUI их видит.

> **ПРАВИЛО (владелец, 2026-10-08): под не останавливать и не удалять без прямого согласия владельца.**
> Причина: у пода диск локальный, привязан к машине. Агент остановил под посреди
> задачи, машину заняли, а запуск отвечает «not enough free GPUs on the host».
> Проект остался без пода, ручная миграция не прошла. Пауза в работе — это пауза
> очереди задач, а не остановка пода. Остановить под можно только по слову владельца.

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

## 3. Пробный пакет: два плана, проверка исправлений (сценарий v3)

```bash
export COMFY_URL=https://lcjxwt6oyt143l-8188.proxy.runpod.net GPU_RATE_USD_H=2.09
export H3_UNET=minimax_h3_ref2va_pruned_fp8_scaled.safetensors
export H3_CLIP=qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors
python -m studio.shoot render productions/augustvpn_main_event/production.json OUT S01_hook_lookup S05_faceoff
```

Глазами по контактным листам (`OUT/*.sheet.jpg`):

* S01 (хук): крупно глаза Августа, тилт вверх, лицо Адгара сверху — читается за 1,5 с;
* форма как на референсе UFC: один печатный спонсор в центре груди, без россыпи нашивок;
* на канвасе нет UFC/OFC, только SECURITY ARENA (реф канваса);
* в S05 Адгар на голову выше Августа, перчатки без букв.

Не годно — исправить `production.json`, повторить шаг 3. Пока это делается,
**под выключить**: правка промпта может занять больше 10 минут.

## 4. Основной пакет

```bash
python -m studio.shoot render productions/augustvpn_main_event/production.json OUT \
    S02_announce S03_walkout_adgar S04_walkout_august S06_bell_charge S07_pressure \
    S08_booth S09_windup_freeze S10_disconnect S11_logo_reveal S12_winner
```

Каждая попытка сама пишется в `journal.jsonl`. План, который QA забраковал,
перезапускается с другим `seed` в `production.json`, а не руками в ComfyUI:
иначе журнал не узнает, какой сид дал принятый дубль.

## 5. Сразу после пакета

1. **Выключить под** (`pod-action {"action":"stop"}`).
2. Записать в журнал строку `cost` из `list-pod-billing` за день рендера.
3. Записать приёмку каждого плана: `python -m studio.shoot log … review edit owner|agent "…" shot=… outcome=годно`.

## 6. Мастер

```bash
python -m studio.shoot edit productions/augustvpn_main_event/production.json \
    productions/augustvpn_main_event/edit.json OUT master_1080x1920.mp4
```

В монтаж берётся самый свежий файл плана из `OUT`. Если принят не последний
дубль, отбракованные убрать из `OUT`. Точки входа и выхода (`in`/`out`) и время
сбоев (glitches) в S09–S10 подогнать по реальным рендерам: в листе они стоят по
битам сценария. Графика и звуковые эффекты пересобираются командой
`python productions/augustvpn_main_event/render_gfx.py` (эфирный пакет) и
`python productions/augustvpn_main_event/make_assets.py` (звук, печать на форме, проверка QR).
Водяной знак снимается флагом `--no-watermark`.
