#!/usr/bin/env python3
"""Т1: мутация решений маршрутов и раскладок восемнадцатого круга — в обе стороны.

    python scripts/mutate_round18_routes.py          # все мутанты
    python scripts/mutate_round18_routes.py 0 10     # мутанты с 0 по 9

Что мутируется: примерка партией (роль входа, слова о модели, вещи × ракурсы, общая база),
цепочка реставрации (раскраска полем и словами, «оставить чёрно-белым», апскейл по кадру исходника,
интерполяция только по просьбе, лица, названная цепочка, работа реестра лиц), партия реплик (строки,
варианты, голоса, длина реплики по площадке, минимум за запрос), подкаст (речь против песни, аватар
только по просьбе, обложка, субтитры дорожкой / вшитые, цена ролика при сборке), вертикальный рефрейм
(вертикаль, исходник уже вертикальный, названная правка, вшивка для соцсетей, цена эндпоинта),
моушн-комикс (источник, панели, без аватара, без голоса, эффекты), танец (поле, слова, референс на
исполнителя, ведущее видео, отбор моделей), остатки (тур без задачи, порог снимков, озвучка по
сценарию, один ведущий), поля в контракте и вызовы из рецептов и плановщика.

Устройство — как у `scripts/mutate_round17_routes.py`. ТРИ ИСХОДА (Р1).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

НАБОРЫ = ("studio.tests.test_round18_routes",)

R = "studio/routes_r18.py"
BS = "studio/brief_spec.py"
RA = "studio/recipes/apply.py"
PN = "studio/planner.py"
EP = "studio/endpoints.py"

#: (файл, было, стало, что ломается)
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # 1. примерка партией
    (R, '        return bool(роли & {"model", "person"})\n', "        return True\n", "любая роль — своя модель"),
    (R, '        return bool(роли & {"model", "person"})\n', "        return False\n", "роль model не снимает генерацию"),
    (R, "    if W_MODEL_PHOTO.search(слова):\n        return True\n", "", "слова о своей модели не читаются"),
    (R, "    return len(фото) >= 2\n", "    return False\n", "два входа-снимка — не своя модель"),
    (R, '            counts["генерация_изображения"] = ракурсов\n', '            counts["генерация_изображения"] = вещей * ракурсов\n',
     "база модели на каждую вещь"),
    (R, '        counts["примерка"] = вещей * ракурсов\n', '        counts["примерка"] = вещей\n', "ракурсы не множат примерку"),
    (R, "    if штук > вещей and штук % вещей == 0:\n        return штук // вещей\n", "", "ракурсы не из шотов"),
    (R, '            shared.append("генерация_изображения")\n        else:', "        else:", "база модели не общий ассет"),
    (R, 'TRY_ON_TASKS: frozenset[str | None] = frozenset({None, "edit", "generate"})',
     'TRY_ON_TASKS: frozenset[str | None] = frozenset({None, "edit"})', "generate-задача без примерки"),
    # 2. цепочка реставрации
    (R, "    if isinstance(поле, bool):\n        return поле\n    if \"colorize\" in",
     "    if поле:\n        return True\n    if \"colorize\" in", "colorize: false уступает словам"),
    (R, "    return bool(W_COLORIZE.search(слова)) and not W_KEEP_BW.search(слова)\n",
     "    return bool(W_COLORIZE.search(слова))\n", "«оставить чёрно-белым» раскрашивается"),
    (R, "    return bool(W_COLORIZE.search(слова)) and not W_KEEP_BW.search(слова)\n", "    return False\n",
     "слова о раскраске не читаются"),
    (R, "            return цель > исходник\n", "            return цель >= исходник\n", "апскейл до того же кадра"),
    (R, "        return цель >= UNKNOWN_SOURCE_UPSCALE_EDGE and (старьё or spec.task in (\"restore\", \"colorize\"))\n",
     "        return False\n", "архив без кадра исходника не апскейлится"),
    (R, "UNKNOWN_SOURCE_UPSCALE_EDGE = 2160", "UNKNOWN_SOURCE_UPSCALE_EDGE = 720", "скан неизвестного кадра апскейлится до 1080p"),
    (R, "            return float(spec.fps) > max(исходные)\n", "            return True\n", "интерполяция без просьбы"),
    (R, "    if _named(spec, \"task\") and len(работы) > 1:\n        return spec  # the caller named the exact chain\n", "",
     "названная цепочка дописывается"),
    (R, '        return "person" in set(spec.subject or ())\n', "        return True\n", "лица в интерьере"),
    (R, "    return bool(W_FACES.search(_words(spec, text)))\n", "    return False\n", "слова о лицах не читаются"),
    (R, "    return bool(W_FACES.search(_words(spec, text)))\n", "    return True\n", "лица всегда"),
    (EP, '    (r"codeformer|gfpgan|restoreformer|face-?restor\\w*", (FACE_RESTORE,)),\n', "",
     "у реестра нет работы восстановления лиц"),
    (RA, '    "восстановление_лиц": 1.5,\n', '    "восстановление_лиц": 2.5,\n', "лица после раскраски"),
    (BS, "    spec = r18.spec_transform(spec, текст)\n", "", "преобразования восемнадцатого круга не применяются"),
    # 3. партия реплик
    (R, "LINES_MIN = 2\n", "LINES_MIN = 500\n", "партия не узнаётся"),
    (R, '    if spec.shots and set(spec.outputs) <= {"speech", "text"}:\n        return int(spec.shots)\n', "",
     "шоты не считаются репликами"),
    (R, "            дублей = строк * голосов * вариантов\n", "            дублей = строк * вариантов\n", "голоса не множат реплики"),
    (R, '    return int(м.group(1)) if м else 1\n\n\ndef speech_batch', '    return 1\n\n\ndef speech_batch',
     "варианты словами не читаются"),
    (R, 'LINE_S_BY_PLATFORM: dict[str, float] = {"game-engine": 2.0, "telephony": 6.0, "voice-agent": 6.0, "web": 8.0}',
     'LINE_S_BY_PLATFORM: dict[str, float] = {"telephony": 6.0, "voice-agent": 6.0, "web": 8.0}', "реплика игры не короткая"),
    (R, '    if spec.duration_s and spec.source.get("duration_s") == "spec" and takes:',
     "    if spec.duration_s and takes:", "длина по умолчанию делит реплики"),
    (R, "RUNWAY_TTS_MIN_CHARS = 50", "RUNWAY_TTS_MIN_CHARS = 40", "минимум за запрос не записанный"),
    (R, '    if set(spec.inputs) & {"video", "photo"} or spec.task not in (None, "generate", "voice-clone"):\n        return False\n',
     "", "озвучка к видео считается партией"),
    # 4. подкаст
    (R, '        return "speech" in set(spec.audio_content) and not set(spec.audio_content) & {"song"}\n',
     "        return True\n", "песня считается подкастом"),
    (R, "    if spec.task not in PODCAST_TASKS or avatar_asked(spec, text):\n",
     "    if spec.task not in PODCAST_TASKS:\n", "аватар по просьбе всё равно аудиограмма"),
    (R, "    return bool(W_PODCAST.search(слова)) and not W_SONG.search(слова)\n", "    return False\n",
     "слова о подкасте не читаются"),
    (R, '        if "photo" not in set(spec.inputs):\n            новые.append("генерация_изображения")\n', "",
     "без обложки нет обложки"),
    (R, '        if "photo" not in set(spec.inputs):\n            новые.append("генерация_изображения")\n',
     '        if True:\n            новые.append("генерация_изображения")\n', "своя обложка генерируется заново"),
    (R, "        acc.assembly.append(ASSEMBLY_CAPTIONS_SOFT if r17.soft_subtitles(spec) and not social_burn(spec) else ASSEMBLY_CAPTIONS_BURN)\n",
     "        acc.assembly.append(ASSEMBLY_CAPTIONS_BURN)\n", "ютуб получает вшитые субтитры"),
    (PN, "        and not set(рецепт.priors) & r18.ASSEMBLED_CLIP_PRIORS\n", "", "аудиограмма без цены ролика"),
    # 5. вертикальный рефрейм
    (R, "    return r is not None and r < 1\n", "    return r is not None\n", "любой кадр — вертикаль"),
    (R, "    if source_vertical(spec) is True:\n        return spec\n", "", "вертикальный исходник рефреймится"),
    (R, "    if spec.then_tasks or spec.edit or spec.edit_target or not vertical_target(spec):\n",
     "    if spec.then_tasks or spec.edit_target or not vertical_target(spec):\n", "названная правка заменяется рефреймом"),
    (R, 'SOCIAL_BURN_PLATFORMS: frozenset[str] = frozenset({"tiktok", "reels", "instagram", "youtube-shorts"})',
     'SOCIAL_BURN_PLATFORMS: frozenset[str] = frozenset({"tiktok", "reels", "instagram", "youtube-shorts", "youtube"})',
     "ютуб получает вшивку"),
    (R, 'SOCIAL_BURN_PLATFORMS: frozenset[str] = frozenset({"tiktok", "reels", "instagram", "youtube-shorts"})',
     'SOCIAL_BURN_PLATFORMS: frozenset[str] = frozenset({"reels", "instagram", "youtube-shorts"})', "тикток без вшивки"),
    (R, 'REFRAME_USD_PER_S: dict[str, float] = {"720p": 0.10, "1080p": 0.20}',
     'REFRAME_USD_PER_S: dict[str, float] = {"720p": 0.10, "1080p": 0.25}', "цена рефрейма не записанная"),
    # 6. моушн-комикс
    (R, "        return True\n    if any(з.get(\"source\") or з.get(\"role\") for з in фото):\n        return False\n",
     "        return True\n", "чужой источник уступает словам"),
    (R, '    return bool(W_COMIC.search(_words(spec, text)))\n', "    return False\n", "слова о комиксе не читаются"),
    (R, '    {"говорящий_аватар", "липсинк", "генерация_видео", "видео_по_референсу", "генерация_изображения", "перенос_движения"}',
     '    {"липсинк", "генерация_видео", "видео_по_референсу", "генерация_изображения", "перенос_движения"}',
     "аватар в комиксе"),
    (R, '        counts["оживление"] = панелей\n', "", "панели не считаются"),
    (R, "        голос = spec.voiceover is not False and (\n", "        голос = (\n", "voiceover: false не снимает озвучку"),
    (R, '        if spec.audio != "none":\n            if "звук_фон" not in steps:',
     '        if False:\n            if "звук_фон" not in steps:', "комикс без эффектов"),
    # 7. танец
    (R, "    if isinstance(поле, bool):\n        return поле\n    return bool(W_DANCE", "    if поле:\n        return True\n    return bool(W_DANCE",
     "dance: false уступает словам"),
    (R, "    return bool(W_DANCE.search(_words(spec, text)))\n", "    return False\n", "слова о танце не читаются"),
    (R, "        стиллов = max(0, исполнителей - фото)\n", "        стиллов = исполнителей\n", "своё фото исполнителя генерируется"),
    (R, "        стиллов = max(0, исполнителей - фото)\n", "        стиллов = 0\n", "без фото нет референса"),
    (R, "        step_seconds[\"перенос_движения\"] = (исполнителей * секунд, min(секунд, 30.0))\n",
     "        step_seconds[\"перенос_движения\"] = (секунд, min(секунд, 30.0))\n", "исполнители не множат секунды"),
    (R, 'DANCE_AVOID = r"standard-motion-control|animate-move|act-two"', 'DANCE_AVOID = r"pro-motion-control"',
     "отбор моделей не по записанному"),
    (R, '        driver = "video" in set(spec.inputs) or "motion" in _roles(spec)\n', "        driver = False\n",
     "своё видео танца не ведёт"),
    (PN, "                | r18.made_inputs(op.name, рецепт.priors, ARTEFACT_VIDEO)\n", "", "перенос движения без кандидата"),
    # 8. остатки
    (R, "TOUR_PHOTOS_MIN = 20", "TOUR_PHOTOS_MIN = 5", "восемь снимков — уже 3D-тур"),
    (R, "    if getattr(spec, \"reconstruct_3d\", None) is not None or not set(spec.inputs) & {\"photo\", \"video\"}:\n",
     "    if not set(spec.inputs) & {\"photo\", \"video\"}:\n", "reconstruct_3d: false уступает словам"),
    (R, "    if _count(_items(spec, \"photo\")) >= TOUR_PHOTOS_MIN and W_TOUR_3D.search(слова):\n        return True\n", "",
     "слова 3D-тура по набору снимков не читаются"),
    (R, "    обход = \"video\" in set(spec.inputs) and \"photo\" not in set(spec.inputs)\n",
     "    обход = \"video\" in set(spec.inputs)\n", "видео рядом со снимками — съёмка тура"),
    (R, "    return обход and bool(W_TOUR_3D.search(слова) or W_TOUR.search(слова))\n", "    return False\n",
     "видео-обход не идёт в 3D"),
    (BS, "    выведено = r18.derived_task(spec, текст)\n", "    выведено = None\n", "тур без задачи — вопрос"),
    (R, "    return _assume(spec, ASSUMPTION_EXPLAINER_VO, voiceover=True)\n", "    return spec\n", "сценарий без озвучки"),
    (R, "    if spec.voiceover is not None or spec.audio is not None or _named(spec, \"audio_content\"):\n        return spec\n",
     "", "voiceover: false не снимает озвучку сценария"),
    (R, '    if "script" not in set(spec.inputs) or set(spec.outputs) != {"video"} or set(spec.inputs) & {"audio", "video"}:\n',
     '    if set(spec.outputs) != {"video"} or set(spec.inputs) & {"audio", "video"}:\n', "озвучка без сценария"),
    (R, "        and int(spec.characters or 1) <= 1\n", "", "два ведущих — один кадр"),
    (R, '            counts["генерация_изображения"] = 1\n            shared.append("генерация_изображения")\n    return',
     '            shared.append("генерация_изображения")\n    return', "кадр ведущего на ролик"),
    # контракт и вызовы
    (BS, "    _поля_r18(raw, поля, ошибки)\n", "", "поля восемнадцатого круга не разбираются"),
    (BS, '                ошибки.append(f"spec.inputs[{i}].role: {з} not in {\', \'.join(INPUT_ROLES)}")\n',
     "                pass\n", "чужая роль молчит"),
    (BS, "DECISION_FIELDS = (*DECISION_FIELDS, *DECISION_FIELDS_R18)\n", "", "поля восемнадцатого круга не в черновике"),
    (RA, "    steps = r18.rewrite(spec, steps, notes, counts, step_seconds, acc, text, avoid=avoid, shared=shared)\n", "",
     "маршруты не применяются"),
    (RA, "    steps = r17.rewrite(r18.with_tour(spec, text), steps, notes, counts, step_seconds, acc, text)\n",
     "    steps = r17.rewrite(spec, steps, notes, counts, step_seconds, acc, text)\n", "тур без поля не идёт в 3D"),
    (RA, "    drop_assembly = (*drop_assembly, *r18.dropped_assembly(acc.priors))\n", "", "строки визуализатора у подкаста"),
)


def clean() -> None:
    for p in ROOT.rglob("__pycache__"):
        if ".claude" not in p.parts:
            shutil.rmtree(p, ignore_errors=True)


def run() -> int:
    clean()
    return subprocess.run(
        [sys.executable, "-B", "-m", "unittest", *НАБОРЫ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    ).returncode


def main(argv: list[str]) -> int:
    с, по = (int(argv[0]), int(argv[1])) if len(argv) == 2 else (0, len(MUTANTS))
    здоровый = run()
    print(f"ЗДОРОВЫЙ | тесты rc={здоровый}")
    if здоровый != 0:
        print("не годно: здоровое дерево красное — таблица мутаций ничего не значит")
        return 1
    промолчали: list[str] = []
    нет_цели: list[str] = []
    for файл, было, стало, что in MUTANTS[с:по]:
        путь = ROOT / файл
        исходный = путь.read_text()
        if исходный.count(было) != 1:
            нет_цели.append(f"{файл}: {что} (цель найдена {исходный.count(было)} раз)")
            print(f"НЕТ ЦЕЛИ | {что}")
            continue
        try:
            путь.write_text(исходный.replace(было, стало))
            rc = run()
        finally:
            путь.write_text(исходный)
        print(f"{'покраснел' if rc else 'ПРОМОЛЧАЛ'} | {что}", flush=True)
        if rc == 0:
            промолчали.append(что)
    clean()
    print(f"мутантов {по - с}, промолчали {len(промолчали)}, без цели {len(нет_цели)}")
    if нет_цели:
        print("не смогли: " + "; ".join(нет_цели))
        return 2
    if промолчали:
        print("не годно: " + "; ".join(промолчали))
        return 1
    print("годно")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
