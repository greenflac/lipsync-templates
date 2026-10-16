#!/usr/bin/env python3
"""Т1: мутация констант-решений ШЕСТОГО КРУГА реестра и цены — в обе стороны.

    python scripts/mutate_registry_r6.py

Что мутируется: подпись работы (`endpoints.SIGNATURES`, `consistent`),
маршрут и заказываемость (`own_routes`), каналы работы шестого круга (путь
площадки старше категории, задача хаба, единица цены в имени атрибута, ответ
канала против схемы уступает следующему), единицы цены (`compute_second`,
«единица биллинга не названа», минута вверх, допущенная частота кадров),
выбор строки по привязке и спор только внутри ступени (`planner.стоимость`),
ничья по цене (`by_evidence`), 8K (`родной_кадр_или_ближайший`,
`родной_предел`, `семья_и_версия`), кадр цены плана и чужая работа на шаге
только из реестра.

Скрипт правит файл на диске, гоняет `НАБОРЫ` через `python -B` со снесённым
`__pycache__`, ВОЗВРАЩАЕТ файл как был. Первой строкой — ЗДОРОВЫЙ прогон.

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
    "studio.tests.test_registry_r6",
    "studio.tests.test_endpoints_r5",
    "studio.tests.test_prices_round4",
    "studio.tests.test_integration_r6",
)
BS = "studio/brief_spec.py"

EP = "studio/endpoints.py"
PR = "studio/pricing.py"
PN = "studio/planner.py"
DU = "studio/duration.py"

#: (файл, было, стало, что ломается). Каждая константа — строже и слабее.
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # --- подпись работы и схема
    (EP, "    T2V: (frozenset({_ТЕКСТ}), frozenset({_ВИДЕО})),", "    T2V: (frozenset({_ТЕКСТ, _КАРТИНКА}), frozenset({_ВИДЕО})),", "t2v вправе требовать снимок"),
    (EP, "    I2V: (frozenset({_КАРТИНКА, _ТЕКСТ}), frozenset({_ВИДЕО})),", "    I2V: (frozenset({_КАРТИНКА, _ТЕКСТ, _ЗВУК}), frozenset({_ВИДЕО})),", "i2v вправе требовать звук"),
    (EP, "    I2V: (frozenset({_КАРТИНКА, _ТЕКСТ}), frozenset({_ВИДЕО})),", "    I2V: (frozenset({_КАРТИНКА}), frozenset({_ВИДЕО})),", "i2v не вправе требовать текст"),
    (EP, "    if нужны and вправе and not нужны <= вправе:\n        return False", "    if False:\n        return False", "обязательные входы не проверяются"),
    (EP, "    return not (выходы and отдаёт and not (выходы & отдаёт))", "    return True", "выход не проверяется"),
    (EP, "        if not годные:\n            отвергнуто.append(", "        if not годные and False:\n            отвергнуто.append(", "ответ против схемы не уступает"),
    (EP, "            continue\n        хвост = ", "            return (), \"\", \"\"\n        хвост = ", "ответ против схемы обрывает разбор"),
    # --- каналы шестого круга
    (EP, "        if из_категории and режимы_площадки and not (режимы_площадки & из_категории):", "        if False:", "путь площадки не старше категории"),
    (EP, '    "text-to-image": (T2I,),\n    "image-to-image": (IMAGE_EDIT,),\n    "text-to-video"', '    "image-to-image": (IMAGE_EDIT,),\n    "text-to-video"', "задача хаба text-to-image не читается"),
    (EP, '    "text-to-video": (T2V,),\n    "image-to-video": (I2V,),\n    "video-to-video": (V2V_EDIT,),\n    "text-to-speech"', '    "text-to-video": (T2V,),\n    "image-to-video": (I2V,),\n    "video-to-video": (V2V_EDIT,),\n    "text-generation": (T2V,),\n    "text-to-speech"', "LLM хаба становится t2v"),
    (EP, '    (r"^price_per_image(?:_usd)?(?:_via_|$)", (T2I,)),', '    (r"^price_per_(?:input_)?image(?:_usd)?(?:_via_|$)", (T2I,)),', "цена за ВХОДНУЮ картинку — тоже t2i"),
    (EP, '    (r"^price_per_image(?:_usd)?(?:_via_|$)", (T2I,)),', "", "единица цены не канал работы"),
    (EP, "        r\"(?:ai-)?avatars?\\d*|talking-?heads?", "        r\"(?:ai-)?avatars?|talking-?heads?", "avatar4 не аватар"),
    (EP, "|flf2v|i2vgen\", (I2V,)),", "|flf2v\", (I2V,)),", "i2vgen не i2v"),
    (EP, '    (r"coloriz\\w*|colouriz\\w*|colorization|ddcolor|deoldify", (COLORIZE,)),', '    (r"coloriz\\w*|colouriz\\w*|colorization|ddcolor|deoldify", (COLORIZE, RESTORE)),', "раскраска снова реставрация"),
    (EP, '    (r"restor\\w*", (RESTORE,)),', '    (r"restor\\w*", (RESTORE, COLORIZE)),', "реставратор раскрашивает"),
    # --- маршрут и заказываемость
    (EP, "        orderable = bool(маршруты_ид)", "        orderable = True", "узел без маршрута заказывается"),
    (EP, "        if ид and family and \"price\" not in f.attribute and fold(ид) != fold(model):\n            continue", "        if False:\n            continue", "схема соседа — маршрут семьи"),
    (EP, "        if ид and family and \"price\" not in f.attribute and fold(ид) != fold(model):\n            continue", "        if ид and \"price\" not in f.attribute and fold(ид) != fold(model):\n            continue", "схема своего эндпоинта не маршрут"),
    (EP, "    if not family:\n        for f in rows:\n            if f.tier != \"vendor\":", "    if True:\n        for f in rows:\n            if f.tier != \"vendor\":", "страница вендора — маршрут и семьи"),
    (EP, "            if f.tier != \"vendor\":\n                continue", "            if f.tier not in (\"vendor\", \"portal\"):\n                continue", "страница портала — маршрут вендора"),
    (EP, "                and hn._repo_page(f.source_url)\n", "", "поиск по каталогу HF — страница весов"),
    (EP, "            priced=any(r.unit == \"usd\" and r.amount > 0 and r.per in pricing.PER for r in ставки),", "            priced=any(r.unit == \"usd\" and r.amount > 0 for r in ставки),", "ставка без единицы — цена"),
    # --- единицы цены
    (PR, '    "compute_second",\n    "second",', '    "second",', "секунда вычисления не единица"),
    (PR, "    if re.match(r\"^[^$]{0,30}?(?:/|per)\\s*(?:gpu\\s+)?compute[\\s-]+seconds?\\b\", голова):\n        return \"compute_second\", 1.0, None, вид", "", "секунда вычисления читается секундой ролика"),
    (PR, "        if сек is None or need.compute_ratio is None:\n            return None", "        if сек is None:\n            return None", "без отношения — секунды ролика"),
    (PR, "            if r.per == \"second\" and (маршрут, round(r.amount, 9)) in вычисления:", "            if False:", "близнец вычисления — секунда ролика"),
    (PR, "            if r.per == \"second\" and (маршрут, round(r.amount, 9)) in вычисления:", "            if r.per == \"second\" and round(r.amount, 9) in {a for _, a in вычисления}:", "близнец через чужой маршрут"),
    (PR, "    if _ЕДИНИЦА_НЕ_НАЗВАНА.search(текст):\n        # «$1 per unit", "    if False:\n        # «$1 per unit", "заглушка $1 per unit — ставка"),
    (PR, "    if _ЕДИНИЦА_НЕ_НАЗВАНА.search(текст):\n        return Price(", "    if False:\n        return Price(", "заглушка $1 per unit — цена разбора"),
    (PR, "ASSUMED_FPS = 30.0", "ASSUMED_FPS = 24.0", "допущенная частота ниже"),
    (PR, "ASSUMED_FPS = 30.0", "ASSUMED_FPS = 60.0", "допущенная частота выше"),
    (PR, "        частота = need.fps or ASSUMED_FPS", "        частота = need.fps or 0.0", "без частоты кадров нет"),
    (PR, "    if _ВВЕРХ_ДО_МИНУТЫ.search(текст):", "    if False:", "минута не округляется вверх"),
    (PR, "    if нужно is None:\n        return 0\n    if r.audio is None:\n        return 1", "    if нужно is None:\n        return 0\n    if r.audio is None:\n        return 0", "голая ставка равна привязанной к звуку"),
    (PR, r"(?:[a-z]+\s+)?(?:characters?|chars?)\b", r"(?:characters?|chars?)\b", "знаки превью не читаются"),
    (PR, r"(\d+)\s*(?:s|-\s*seconds?)\b\s*:?", r"(\d+)\s*s\b\s*:?", "«10-second job» не прогон"),
    # --- выбор строки и спор
    (PN, "            точнейшая = min(з[1].fit for з in все_записи)\n            записи = [з for з in все_записи if з[1].fit == точнейшая]", "            записи = list(все_записи)", "привязка не старше ступени"),
    (PN, "                if (з[1].resolution, з[1].audio) == (главная[1].resolution, главная[1].audio)", "                if True", "разные ступени — спор"),
    (PN, "            одна_ставка = len(ставки_записей) == 1 and all(з[1].rate is not None for з in записи)", "            одна_ставка = False", "одна ставка с округлением — спор"),
    (PN, "    if need.compute_ratio is None:\n        отношение = compute_ratio(facts)", "    if False:\n        отношение = compute_ratio(facts)", "записанное отношение не читается"),
    # --- ничья, 8K, поколение, кадр плана, чужая работа
    (PN, "        int(not цена_есть(c)),\n", "", "при равных доводах цена не старше"),
    (PN, "        int(not цена_есть(c)),\n        # Подтверждённые", "        0,\n        # Подтверждённые", "поле цены в ключе мёртвое"),
    (PN, "    дотягивают = (op is not None and ARTEFACT_VIDEO in op.requires) or any(", "    дотягивают = True or any(", "8K: ниже записанных всегда исключают"),
    (PN, "    дотягивают = (op is not None and ARTEFACT_VIDEO in op.requires) or any(", "    дотягивают = any(", "липсинк спасает ниже записанных"),
    (PN, "NATIVE_NEAREST_RANK = 1.5", "NATIVE_NEAREST_RANK = 2.5", "ближайший родной ниже «не записано»"),
    (PN, "NATIVE_NEAREST_RANK = 1.5", "NATIVE_NEAREST_RANK = 0.5", "ближайший родной выше подтверждённого"),
    (PN, "NATIVE_NEAREST_SCALE = 4320.0", "NATIVE_NEAREST_SCALE = 2160.0", "шкала родного кадра 4K"),
    (PN, "    return max(1, min(семейные) - 1) if семейные else 1", "    return min(семейные) if семейные else 1", "предел семьи равен своему"),
    (PN, "    семья = re.sub(r\"[-_]video$\", \"\", семья)", "", "kling-video — другая семья"),
    (PN, "    if re.match(r\"\\s*[kp]\\b\", хвост[числа.end() :], re.I):\n        return None", "", "4k — версия"),
    (PN, "        or any(OUTPUT_KINDS.get(а) == \"видео\" for оп in операции for а in оп.produces)\n", "", "кадр цены плана не допускается для генерации"),
    (PN, "        and op.name not in ТОЛЬКО_РЕЕСТР\n", "", "Bria — чужая работа по описанию"),
    (DU, "НЕ_СЕКУНДЫ.sub(\" \", КОДЕК_ИЛИ_ВЕРСИЯ.sub(\" \", текст))", "НЕ_СЕКУНДЫ.sub(\" \", текст)", "H.264 — 264 секунды"),
    (DU, "av1|mp[34]|m4a|", "av1|", "MP4 — 4 секунды"),
    (EP, "        r\"|audio-driven\",", "        r\"\",", "audio-driven не аватар"),
    (EP, "|talking-?heads?|talking-?videos?|", "|talking-?heads?|", "«talking video» не аватар"),
    (EP, "|lipsync|latentsync\", (LIPSYNC,)),", "|lipsync\", (LIPSYNC,)),", "latentsync не липсинк"),
    # --- интеграция шестого круга: что правит шаг правки видео (`spec.edit`)
    (EP, 'NOT_AN_EDIT = r"extend|extend-video|reference|motion-control|3d-to-video|draft|insert-video"', 'NOT_AN_EDIT = r"draft"', "продление и референс — правка"),
    (EP, '    EDIT_REFRAME: r"reframe|outpaint",', '    EDIT_REFRAME: r"outpaint",', "reframe не рефрейм"),
    (EP, '    EDIT_REMOVE_OBJECT: _ПРАВКА_ПО_ИНСТРУКЦИИ + r"|clean-plate|object-removal|remove-object",', '    EDIT_REMOVE_OBJECT: _ПРАВКА_ПО_ИНСТРУКЦИИ,', "clean-plate не удаление"),
    (EP, '    EDIT_STABILISE: r"stabili[sz]\\w*",', '    EDIT_STABILISE: _ПРАВКА_ПО_ИНСТРУКЦИИ,', "правка по инструкции — стабилизация"),
    (EP, "    if not итог and not any(_звено(NOT_AN_EDIT, _звенья(т)) for т in тексты):", "    if False:", "голое v2v не перерисовка"),
    (PN, "EDIT_DEFAULT_INTENTS: tuple[str, ...] = (ep.EDIT_REPLACE_OBJECT,)", "EDIT_DEFAULT_INTENTS: tuple[str, ...] = (ep.EDIT_RESTYLE,)", "правка без spec.edit — перерисовка"),
    (PN, "        if ep.not_an_edit(что):", "        if False:", "продление не отсеивается как не-правка"),
    (PN, "        if not set(нужно) <= умеет:", "        if умеет and not set(нужно) & умеет:", "правка: хватает одной из названных или ни одной"),
    (PN, '    {"правка_видео", "реставрация", "раскраска", "удаление_фона_видео", "интерполяция_кадров"}', '    {"реставрация", "раскраска", "удаление_фона_видео", "интерполяция_кадров"}', "правка до апскейла по кадру заказа"),
    (PN, "    кадр_исходника = bs.source_frame(понято) or bs.frame(", "    кадр_исходника = None or bs.frame(", "кадр исходника не читается"),
    (BS, '    # Интеграция шестого круга: ЧТО правится в `video-edit` (`endpoints.EDIT_INTENTS`).\n    "edit",\n', "", "spec.edit — неизвестное поле"),
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
        print(f"{'покраснел' if rc else 'ПРОМОЛЧАЛ'} | {что}", flush=True)
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
