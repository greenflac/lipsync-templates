#!/usr/bin/env python3
"""Т1: мутация констант-решений структурного разбора брифа (`studio/brief_spec.py`)
и того, как его числа проходят в план и в цену, — в обе стороны.

    python scripts/mutate_brief_spec.py

Скрипт правит файл на диске, гоняет `НАБОРЫ` через `python -B` со снесённым
`__pycache__` (мутант не должен прочитаться из скомпилированного), ВОЗВРАЩАЕТ
файл как был. Первой строкой — ЗДОРОВЫЙ прогон: таблица поверх красного дерева
не значит ничего. Мутант, после которого всё зелёное, — константа, которую
никто не сторожит; исход скрипта тогда «не годно».

ТРИ ИСХОДА (Р1): годно — здоровый прогон зелёный и покраснели все мутанты;
не годно — здоровый красный или хоть один мутант промолчал; не смогли — цели
мутанта нет в файле (мутант устарел и ничего не проверяет).
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

НАБОРЫ = (
    "studio.tests.test_brief_spec_r4",
    # Интеграция круга 4: жёсткие требования из той же спецификации
    # (`brief_spec.hard` -> `hardneed.Hard`) и язык ответа (`studio/l10n.py`).
    # Только модульные классы — секунды, а не минуты на мутанта.
    "studio.tests.test_integration_r4.ОднаСпецификация",
    "studio.tests.test_hard_constraints_r4.ТребованияИзБрифа",
    "studio.tests.test_hard_constraints_r4.ВесаИПамять",
    "studio.tests.test_hard_constraints_r4.ЦенаСвоегоЗапуска",
    "studio.tests.test_localisation.Прибор",
    # Пятый круг: реестр эндпоинтов и отбор по нему.
    "studio.tests.test_endpoints_r5",
    # Шестой круг: план только по полной spec, черновик, новые работы.
    "studio.tests.test_spec_contract_r6",
    # Седьмой круг: словарь spec и маршруты (монтаж, пробелы, частота, бюджет).
    "studio.tests.test_routes_r7",
    # Интеграция седьмого круга: цена за миллион знаков, «только свои веса»,
    # скорость речи по письму, краткий ответ (G11).
    "studio.tests.test_integration_r7",
)

BS = "studio/brief_spec.py"
PN = "studio/planner.py"
PR = "studio/pricing.py"
HN = "studio/hardneed.py"
L10N = "studio/l10n.py"
EP = "studio/endpoints.py"
ER = "scripts/endpoint_report.py"
SV = "studio/mcp/server.py"

#: (файл, было, стало, что ломается). Каждая константа — строже и слабее.
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # --- hardneed: память, веса, цель (через `brief_spec.hard` — в отбор)
    (HN, "BYTES_PER_PARAM_FLOOR = 1.0", "BYTES_PER_PARAM_FLOOR = 2.0", "оценка памяти по FP16, а не по FP8"),
    (HN, "BYTES_PER_PARAM_FLOOR = 1.0", "BYTES_PER_PARAM_FLOOR = 0.5", "оценка памяти по 4 битам"),
    (HN, '"rtx-4090": 24.0,', '"rtx-4090": 16.0,', "память RTX 4090 из таблицы меньше паспортной"),
    (HN, 'r"quality over (?:price|cost)",', 'r"quality over nothing",', "«quality over price» больше не цель"),
    (HN, '"huggingface.co", "github.com"', '"github.com"', "страница весов на HF не считается"),
    # --- l10n: прибор утечек и глосс
    (L10N, 'GLOSS_MARK = "[ru:"', 'GLOSS_MARK = "[en:"', "глосс русской цитаты не узнаётся"),
    (L10N, '        "step",\n        "requires",', '        "requires",', "имя шага — код — снова в счёт утечек"),
    (
        L10N,
        'GLOSS_DEFAULT = "operator\'s note in Russian, kept as recorded"',
        'GLOSS_DEFAULT = "Russian note"',
        "глосс по умолчанию другой",
    ),
    (BS, "POSSESSIVE_WINDOW = 3", "POSSESSIVE_WINDOW = 2", "окно притяжательного уже"),
    (BS, "POSSESSIVE_WINDOW = 3", "POSSESSIVE_WINDOW = 4", "окно притяжательного шире"),
    (BS, "OBJECT_WINDOW = 4", "OBJECT_WINDOW = 3", "окно объекта уже"),
    (BS, "OBJECT_WINDOW = 4", "OBJECT_WINDOW = 5", "окно объекта шире"),
    (BS, "EACH_WINDOW = 1", "EACH_WINDOW = 0", "«по» только вплотную"),
    (BS, "EACH_WINDOW = 1", "EACH_WINDOW = 2", "«по» дальше от числа"),
    (BS, "MULTI_CHARACTER_MIN = 2", "MULTI_CHARACTER_MIN = 1", "кадры и у одного персонажа"),
    (BS, "MULTI_CHARACTER_MIN = 2", "MULTI_CHARACTER_MIN = 3", "двоим кадров не делают"),
    (BS, 'DEFAULT_VIDEO_RESOLUTION = "1080p"', 'DEFAULT_VIDEO_RESOLUTION = "720p"', "кадр по умолчанию ниже"),
    (BS, "ASSUMED_SHOT_S = 8.0", "ASSUMED_SHOT_S = 7.0", "допущенный шот короче"),
    (BS, "ASSUMED_SHOT_S = 8.0", "ASSUMED_SHOT_S = 10.0", "допущенный шот длиннее"),
    (
        BS,
        'ROUTE_FIRST_WITH: dict[str, str] = {"dub-translate": "video", "face-replace": "video"}',
        'ROUTE_FIRST_WITH: dict[str, str] = {"face-replace": "video"}',
        "перевод своего видео снова собирают подсказки",
    ),
    (
        BS,
        'ROUTE_FIRST_WITH: dict[str, str] = {"dub-translate": "video", "face-replace": "video"}',
        'ROUTE_FIRST_WITH: dict[str, str] = {"dub-translate": "", "face-replace": "video"}',
        "перевод маршрутом и без своего видео",
    ),
    (
        BS,
        'ROUTE_FIRST_WITHOUT: dict[str, tuple[str, ...]] = {"avatar": ("video", "photo")}',
        "ROUTE_FIRST_WITHOUT: dict[str, tuple[str, ...]] = {}",
        "аватар без снимка снова TTS + t2v + липсинк",
    ),
    (
        BS,
        'ROUTE_FIRST_WITHOUT: dict[str, tuple[str, ...]] = {"avatar": ("video", "photo")}',
        'ROUTE_FIRST_WITHOUT: dict[str, tuple[str, ...]] = {"avatar": ("video",)}',
        "аватар маршрутом и при принесённом снимке",
    ),
    (BS, '    "avatar": ("video", "speech"),\n', "", "работа аватара не говорит, что выходит видео"),
    (BS, '    elif "speech" in spec.outputs and "video" in spec.outputs and spec.audio is None', "    elif False", "голос поверх картинки не назван допущением"),
    (BS, '"video" not in spec.inputs:\n        поля["resolution"] = DEFAULT_VIDEO_RESOLUTION', 'True:\n        поля["resolution"] = DEFAULT_VIDEO_RESOLUTION', "кадр по умолчанию и у принесённого видео"),
    (BS, "            return Маршрут()\n        if \"photo\" in входы:\n            шаги.append(\"оживление\")", "            pass\n        if \"photo\" in входы:\n            шаги.append(\"оживление\")", "генерация поверх своего видео"),
    (BS, 'cartoon|\\bclaymation|\\bstop', 'cartoon|\\bstop', "пластилин перестаёт быть генерируемым стилем"),
    (PN, '    поштучно = "генерация_изображения" in имена_плана and "оживление" in имена_плана', "    поштучно = False", "ключевых кадров снова один"),
    (PN, "клипов if поштучно else 0) or 1", "0) or 1", "кадров меньше шотов"),
    (PN, "    if bs.GENERATED_STYLE.search(_norm(brief)):\n        return True\n", "", "стиль не отвечает на «уже снято?»"),
    (PN, "    if понято.task in (None, \"generate\") and чужое_ремесло(brief):", "    if чужое_ремесло(brief):", "чужое ремесло глушит и названную работу"),
    (PN, "    if not операции and вопрос is None and ARTEFACT_VIDEO not in есть and not чужое_ремесло(brief):", "    if False:", "пустой план снова без вопроса"),
    (PN, '    просят_кадр = None if понято.source.get("resolution") == bs.SOURCE_DEFAULT else заказанный_кадр', "    просят_кадр = заказанный_кадр", "кадр-допущение дописывает апскейл"),
    (PR, "        if сек and need.shots > 1:", "        if False:", "шоты снова одним куском в цене"),
    (PR, "            прогонов = need.shots * прогонов_на_шот", "            прогонов = прогонов_на_шот", "цена за один шот вместо всех"),
    # --- реестр эндпоинтов (пятый круг): работа из свидетельства, узел семьи,
    # прогоны, «самое дешёвое», новые работы маршрута
    (EP, '    (r"lip-?sync(?:ing)?|lipsync|latentsync", (LIPSYNC,)),\n', "", "липсинк в пути больше не работа"),
    (EP, "    if работы:\n        yield _порядок(работы), EVIDENCE_ID", "    if False:\n        yield _порядок(работы), EVIDENCE_ID", "работа в пути не старше режима"),
    (EP, "AUDIO_DRIVEN: frozenset[str] = frozenset({LIPSYNC, AVATAR})", "AUDIO_DRIVEN: frozenset[str] = frozenset()", "обязательный звук не подпись работы"),
    (EP, "AUDIO_DRIVEN: frozenset[str] = frozenset({LIPSYNC, AVATAR})", "AUDIO_DRIVEN: frozenset[str] = frozenset({LIPSYNC})", "аватар по звуку не узнаётся"),
    (EP, 'frozenset(нужны - {"текст"})', "frozenset(нужны)", "текст рядом со звуком меняет работу"),
    (EP, 'DOC_TIERS: frozenset[str] = frozenset({"vendor", "portal"})', 'DOC_TIERS: frozenset[str] = frozenset({"vendor", "portal", "blog"})', "блог — свидетельство работы"),
    (EP, 'DOC_TIERS: frozenset[str] = frozenset({"vendor", "portal"})', 'DOC_TIERS: frozenset[str] = frozenset({"portal"})', "документация вендора не свидетельство"),
    (EP, "ATTRIBUTE_MODES: frozenset[str] = frozenset({T2V, I2V, R2V})", "ATTRIBUTE_MODES: frozenset[str] = frozenset()", "имя атрибута не читается"),
    (EP, "ATTRIBUTE_MODES: frozenset[str] = frozenset({T2V, I2V, R2V})", "ATTRIBUTE_MODES: frozenset[str] = frozenset({T2V, I2V, R2V, IMAGE_EDIT})", "правка из имени атрибута"),
    (EP, "FAMILY_MODES: frozenset[str] = frozenset({T2V, I2V, R2V, T2I, IMAGE_EDIT})", "FAMILY_MODES: frozenset[str] = frozenset()", "семья с ценой без работы"),
    (EP, "FAMILY_MODES: frozenset[str] = frozenset({T2V, I2V, R2V, T2I, IMAGE_EDIT})", "FAMILY_MODES: frozenset[str] = frozenset({T2V, I2V, R2V, T2I, IMAGE_EDIT, LIPSYNC})", "работа варианта становится работой семьи"),
    # Шестой круг: заказываемость — «есть маршрут» (`own_routes`), семья —
    # параметр маршрута, а не отдельная развилка.
    (EP, "            family=bool(мои_варианты),", "            family=False,", "узел семьи заказывается"),
    (EP, "    for кто in price_routes:\n        if кто not in продавцы:", "    for кто in ():\n        if кто not in продавцы:", "семья со своей ценой не заказывается"),
    (EP, "    if имя_курированное:\n", "    if False:\n", "курированное не перекрывает каналы"),
    (EP, "    if IMAGE_EDIT in режимы and (", "    if False and (", "правка видео читается правкой картинки"),
    (EP, 'if _звено("video|vsr", звенья) or', "if", "апскейл всегда видео"),
    (EP, "CACHE_LIMIT = 8", "CACHE_LIMIT = 2", "кэш реестра мельче"),
    (EP, "CACHE_LIMIT = 8", "CACHE_LIMIT = 100", "кэш реестра без предела"),
    (PN, "RUN_DEFAULT_S = 5.0", "RUN_DEFAULT_S = 4.0", "допущенный прогон короче"),
    (PN, "RUN_DEFAULT_S = 5.0", "RUN_DEFAULT_S = 6.0", "допущенный прогон длиннее"),
    (PN, "UNCLASSIFIED_RANK = 1", "UNCLASSIFIED_RANK = 0", "неустановленная работа наравне с установленной"),
    (PN, "FOREIGN_RANK = 2", "FOREIGN_RANK = 1", "чужая работа наравне с неустановленной"),
    (PN, "    if c.unpriced_last and not цена_есть(c):", "    if False:", "без цены не последним при «самом дешёвом»"),
    (PN, "    if not set(работы) & ep.FAMILY_MODES:\n        return False\n", "", "аватар берёт строки генератора"),
    (PN, "    if семья is None or семья.orderable:", "    if семья is None:", "заказываемая семья одалживает"),
    (PN, "            elif узел.functions and not set(узел.functions) & set(работы):", "            elif False:", "видеомодель снова кандидат на липсинк"),
    (PN, "            if (\n                (not узел.orderable or только_у_себя)\n                and not (hard is not None and hard.self_host and узел.self_hostable)\n", "            if (\n                False\n                and not (hard is not None and hard.self_host and узел.self_hostable)\n", "узел семьи снова кандидат"),
    (PN, "    if not реестр.orderable_for(работа) and op.name in ЗАПАСНАЯ_РАБОТА:", "    if False:", "оборот без запасной работы"),
    (PN, "    if предел_прогона(все) is not None:\n        return None\n", "", "допущение поверх своей записи"),
    (PN, "        op.name in ТОЛЬКО_РЕЕСТР\n        or any(not семья_только_у_себя(у) for р in работы for у in реестр.orderable_for(р))", "        op.name in ТОЛЬКО_РЕЕСТР", "неустановленные остаются при известной работе"),
    (PN, "        op.name in ТОЛЬКО_РЕЕСТР\n        or any(not семья_только_у_себя(у) for р in работы for у in реестр.orderable_for(р))", "        any(not семья_только_у_себя(у) for р in работы for у in реестр.orderable_for(р))", "работы пятого круга снова из слов"),
    (PN, '        "перенос_движения",\n        "интерполяция_кадров",\n', '        "перенос_движения",\n', "интерполяция не только из реестра"),
    (ER, 'GUARDED: tuple[str, ...] = ("orderable", "priced", "with_run_length")', 'GUARDED: tuple[str, ...] = ("orderable", "with_run_length")', "гейт не держит число с ценой"),
    (ER, 'GUARDED: tuple[str, ...] = ("orderable", "priced", "with_run_length")', 'GUARDED: tuple[str, ...] = ("orderable", "priced", "with_run_length", "video")', "гейт держит лишнее поле"),
    (ER, 'BASELINE = ROOT / "studio" / "knowledge" / "endpoint_coverage.json"', 'BASELINE = ROOT / "studio" / "knowledge" / "endpoint_coverage_missing.json"', "гейт без базы"),
    (BS, '    "restore": (("video", "реставрация"), ("photo", "реставрация_изображения")),\n', "", "реставрация снова без маршрута"),
    (BS, "                    return Маршрут((шаг,), {шаг: NOTE_CAPTIONS}, сборка=(NOTE_CAPTIONS,))", "                    return Маршрут((шаг,), {шаг: NOTE_CAPTIONS})", "субтитры без пометки монтажа"),
    # --- шестой круг: контракт «план только по spec», форма spec, новые работы
    (SV, "    if not по_тексту and not ошибки_spec and нехватка:", "    if False:", "неполная spec снова план из текста"),
    (PN, '    if spec_only:\n        brief = ""\n', "", "текст снова решает поверх полной spec"),
    (BS, "ASPECT_LIMIT = 10.0", "ASPECT_LIMIT = 11.0", "соотношение шире 10:1 принимается"),
    (BS, "ASPECT_LIMIT = 10.0", "ASPECT_LIMIT = 9.0", "10:1 отвергается"),
    (BS, "RECORDED_RATES: dict[str, tuple[float, str, str]] = {}", 'RECORDED_RATES: dict[str, tuple[float, str, str]] = {"EUR": (1.0, "x", "y")}', "выдуманный курс евро"),
    (BS, 'LANGUAGE_TASKS: frozenset[str] = frozenset({"dub-translate", "transcribe", "captions", "voice-clone"})', 'LANGUAGE_TASKS: frozenset[str] = frozenset({"dub-translate", "captions", "voice-clone"})', "расшифровка без языка"),
    (BS, 'LANGUAGE_TASKS: frozenset[str] = frozenset({"dub-translate", "transcribe", "captions", "voice-clone"})', 'LANGUAGE_TASKS: frozenset[str] = frozenset({"dub-translate", "transcribe", "captions", "voice-clone", "restore"})', "реставрация требует языка"),
    (BS, 'TIMED_OUTPUTS: frozenset[str] = frozenset({"video", "speech", "music", "sfx", "text"})', 'TIMED_OUTPUTS: frozenset[str] = frozenset({"video", "speech", "music", "sfx"})', "текст без длины"),
    (BS, 'TIMED_OUTPUTS: frozenset[str] = frozenset({"video", "speech", "music", "sfx", "text"})', 'TIMED_OUTPUTS: frozenset[str] = frozenset({"video", "speech", "music", "sfx", "text", "image"})', "картинкам нужна длина"),
    (BS, '        "restore",\n        "interpolate",\n        "remove-background",\n        "transcribe",\n', '        "interpolate",\n        "remove-background",\n        "transcribe",\n', "реставрация не берёт длину из входа"),
    (BS, '        "sing-photo",\n        "colorize",\n    }\n)', '        "sing-photo",\n        "colorize",\n        "generate",\n    }\n)', "генерация берёт длину из входа"),
    (BS, 'VIDEO_EDIT_TASKS: frozenset[str] = frozenset({"video-edit"})', "VIDEO_EDIT_TASKS: frozenset[str] = frozenset()", "правка видео без маршрута"),
    (BS, "HAVE_WINDOW = 8", "HAVE_WINDOW = 4", "окно «we have» уже"),
    (BS, "HAVE_WINDOW = 8", "HAVE_WINDOW = 12", "окно «we have» шире"),
    (BS, '    r"^[a-z]{2,3}(?:-[a-z]{3}){0,3}', '    r"^[a-z]{2,8}(?:-[a-z]{3}){0,3}', "слово длиннее тега — тег"),
    (BS, '            if з.get("owned") is None:', "            if False:", "владение входом не спрашивается"),
    (BS, '    return tuple(ш for в, ш in (("music", "музыка"), ("sfx", "звук_фон")) if в in выходы)', "    return ()", "музыка под свой ролик теряется"),
    (BS, '    if SING.search(низ) and фото:', "    if False:", "поющее фото снова генерация"),
    (PN, "PER_LANGUAGE_STEPS: frozenset[str] = SPEECH_STEPS | {\"клонирование_голоса\"}", "PER_LANGUAGE_STEPS: frozenset[str] = SPEECH_STEPS", "клон голоса один на все языки"),
    (PN, "PER_LANGUAGE_STEPS: frozenset[str] = SPEECH_STEPS | {\"клонирование_голоса\"}", "PER_LANGUAGE_STEPS: frozenset[str] = SPEECH_STEPS | {\"клонирование_голоса\", \"расшифровка\"}", "расшифровка по числу языков"),
    (PN, '    if секунды is not None and языков > 1:', "    if False:", "цена речи не умножается на языки"),
    (PN, 'ON_SOURCE_STEPS: frozenset[str] = frozenset({"расшифровка"})', "ON_SOURCE_STEPS: frozenset[str] = frozenset()", "расшифровка по длине шортсов"),
    (PN, 'APPLE_RUNTIME = re.compile(r"\\bmps\\b|\\bmlx\\b|', 'APPLE_RUNTIME = re.compile(r"\\bmps\\b|', "MLX не читается запуском на Mac"),
    (PN, "        операции = sorted(операции, key=lambda оп: порядок_маршрута.get(оп.name, -1))\n", "", "цепочка не в названном порядке"),
    (PN, 'ORDERED_ROUTES: frozenset[str] = frozenset({"cut-to-shorts"})', "ORDERED_ROUTES: frozenset[str] = frozenset()", "нарезка не в порядке маршрута"),
    (PN, '        сумма = f"{деньги[0]:g}" if деньги is not None and деньги[1].lower() == код else ""', '        сумма = ""', "сумма в чужой валюте не названа"),
    (PN, '    "правка_видео": ep.V2V_EDIT,\n', "", "правка видео не из реестра"),
    (BS, 'AUDIO_DRIVEN_TASKS: frozenset[str] = frozenset({"avatar"})', "AUDIO_DRIVEN_TASKS: frozenset[str] = frozenset()", "аватар под свою дорожку снова без длины"),
    (BS, 'AUDIO_DRIVEN_TASKS: frozenset[str] = frozenset({"avatar"})', 'AUDIO_DRIVEN_TASKS: frozenset[str] = frozenset({"avatar", "generate"})', "генерация берёт длину из дорожки"),
    (L10N, '    (r"правка ВАШЕГО видео \\(стабилизация', '    (r"правка ВАШЕГО ВИДЕО \\(стабилизация', "пометка правки видео по-русски в английском плане"),
    # --- седьмой круг: словарь spec и маршруты как модель пространства работ
    (BS, "SERIES_CHARACTERS_MIN = 1", "SERIES_CHARACTERS_MIN = 0", "серия без персонажа — тоже референс и правки"),
    (BS, "SERIES_CHARACTERS_MIN = 1", "SERIES_CHARACTERS_MIN = 2", "серия с одним персонажем — снова N генераций"),
    (BS, "SERIES_IMAGES_MIN = 2", "SERIES_IMAGES_MIN = 1", "одна картинка — референс и правка"),
    (BS, "SERIES_IMAGES_MIN = 2", "SERIES_IMAGES_MIN = 3", "две картинки персонажа — независимые генерации"),
    (BS, "ASSEMBLY_EDITS: dict[str, str] = {ep.EDIT_STABILISE: NOTE_STABILISE}", "ASSEMBLY_EDITS: dict[str, str] = {}", "стабилизация снова генеративной правкой"),
    (BS, "ASSEMBLY_EDITS: dict[str, str] = {ep.EDIT_STABILISE: NOTE_STABILISE}", "ASSEMBLY_EDITS: dict[str, str] = {ep.EDIT_STABILISE: NOTE_STABILISE, ep.EDIT_REMOVE_OBJECT: NOTE_STABILISE}", "удаление объекта уходит в монтаж"),
    (BS, '{"sgn", "ase", "bfi",', '{"sgn", "bfi",', "ASL тегом снова говорящий аватар"),
    (BS, 'r"sign[- ]language|signing avatar|', 'r"signing avatar|', "«sign language» словами снова аватар"),
    (BS, '    return ("video" in spec.outputs or not spec.outputs) and spec.audio != "voiceover"', "    return True", "каждый дубляж снова с липсинком"),
    (BS, '    return ("video" in spec.outputs or not spec.outputs) and spec.audio != "voiceover"', "    return False", "дубляж видео по умолчанию без губ"),
    (BS, "        if not spec.duration_s:\n            for поле in (\"shots\", \"per_shot_s\"):", "        if True:\n            for поле in (\"shots\", \"per_shot_s\"):", "нарезка снова не берёт duration_s"),
    (BS, '            ("расшифровка", *_подложка(выходы)),\n            {"расшифровка": NOTE_SHORTS_TRANSCRIPT},', '            ("расшифровка", "правка_видео", *_подложка(выходы)),\n            {"расшифровка": NOTE_SHORTS_TRANSCRIPT},', "нарезка снова генеративной правкой"),
    (BS, '    "colorize": (("video", "раскраска"), ("photo", "раскраска_изображения")),\n', "", "раскраска без маршрута"),
    (BS, "        return Маршрут((шаг,), {шаг: NOTE_VISUALISER}, сборка=(NOTE_VISUALISER, NOTE_VISUALISER_SYNC))", "        return Маршрут((шаг,), {шаг: NOTE_VISUALISER})", "визуализатор молчит, что t2v не слышит трек"),
    (BS, '    свой = б.get("usd")', '    свой = None', "пересчёт бюджета вызывающим не читается"),
    (PN, "FPS_RANGE: tuple[int, int] = (8, 240)", "FPS_RANGE: tuple[int, int] = (25, 240)", "24 fps не считается частотой"),
    (PN, "FPS_RANGE: tuple[int, int] = (8, 240)", "FPS_RANGE: tuple[int, int] = (8, 23)", "частоты выше 23 не читаются"),
    (PN, "            if просят <= записано:\n", "            if True:\n", "частота выше записанной без интерполяции"),
    (PN, "        and not маршрут.сборка\n        # ДВЕНАДЦАТЫЙ КРУГ: ролик", "        and True\n        # ДВЕНАДЦАТЫЙ КРУГ: ролик", "нарезка снова «цены ролика нет»"),
    (PN, '    if цена.get("over_ceiling"):\n        out["outcome"] = FAIL', '    if False:\n        out["outcome"] = FAIL', "строка бюджета снова pass при превышении"),
    (PN, '            цена["over_ceiling"] = {"least_known_usd": round(минимум, 4), "ceiling_usd": потолок}\n            цена["note"] += (\n                f" — ПОТОЛОК {потолок:g}: работа столько не стоит, "\n                f"дешевле всего выходит {минимум:.2f} {pl.BUDGET_UNIT}"', '            цена["note"] += (\n                f" — ПОТОЛОК {потолок:g}: работа столько не стоит, "\n                f"дешевле всего выходит {минимум:.2f} {pl.BUDGET_UNIT}"', "бюджет 0 снова не валит план"),
    (PN, "    if bs.sign_language(понято, текст):\n", "    if False:\n", "язык жестов словами брифа снова план"),
    (PN, "    if not маршрут.шаги and маршрут.сборка:\n", "    if False:\n", "монтажная работа снова «шагов нет»"),
    (PR, "    if клоны:\n", "    if False:\n", "плата за клон снова спорит с ценой знаков"),
    (SV, '    if просев["outcome"] == UNMEASURED and (есть_слова(brief) or spec_полна(spec)):', '    if просев["outcome"] == UNMEASURED and spec_полна(spec) and False:', "японский бриф снова «пуст»"),
    (SV, '    if out.get("outcome") == PASS:\n        out["outcome"] = UNMEASURED', '    if False:\n        out["outcome"] = UNMEASURED', "непрочитанный бриф снова pass"),
    # --- интеграция седьмого круга
    (PR, '        return "1000_chars", 0.001, None, вид_доплаты(голова)\n    м = re.match(r"^\\s*(?:/|per)\\s*1\\s*([km])', '        return "1000_chars", 1.0, None, вид_доплаты(голова)\n    м = re.match(r"^\\s*(?:/|per)\\s*1\\s*([km])', "миллион знаков снова как тысяча"),
    (PR, '    "ja": 6.0,\n    "ko": 6.0,\n', '    "ko": 6.0,\n', "японский снова 15 знаков в секунду"),
    (PR, '    "zh": 5.0,\n', '    "zh": 15.0,\n', "китайский снова латинской скоростью"),
    (PR, "        return sum(доля * speech_chars_per_second(я) for я in languages)", "        return seconds * CHARS_PER_SECOND", "языки разной скорости снова одной"),
    (PN, "    return bool(узел.routes) and set(узел.routes) == {ep.ROUTE_SELF_HOST}", "    return bool(узел.variants) and bool(узел.routes) and set(узел.routes) == {ep.ROUTE_SELF_HOST}", "узел «только у себя» снова кандидат API-плана"),
    (PN, '                    op.name in VIDEO_MAKERS\n                    or {OUTPUT_KINDS.get(а) for а in op.produces} & {"видео"}\n', "                    op.name in VIDEO_MAKERS\n", "после раскраски снова апскейл картинки"),
    (PN, "COMPACT_EVIDENCE = 1", "COMPACT_EVIDENCE = 3", "G11: краткий ответ снова несёт простыню доказательств"),
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


def main() -> int:
    здоровый = run()
    print(f"ЗДОРОВЫЙ | тесты rc={здоровый}")
    if здоровый != 0:
        print("не годно: здоровое дерево красное — таблица мутаций ничего не значит")
        return 1
    промолчали: list[str] = []
    нет_цели: list[str] = []
    for файл, было, стало, что in MUTANTS:
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
        print(f"{'покраснел' if rc else 'ПРОМОЛЧАЛ'} | {что}")
        if rc == 0:
            промолчали.append(что)
    clean()
    print(f"мутантов {len(MUTANTS)}, промолчали {len(промолчали)}, без цели {len(нет_цели)}")
    if нет_цели:
        print("не смогли: " + "; ".join(нет_цели))
        return 2
    if промолчали:
        print("не годно: " + "; ".join(промолчали))
        return 1
    print("годно")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
