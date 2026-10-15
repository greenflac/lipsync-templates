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
)

BS = "studio/brief_spec.py"
PN = "studio/planner.py"
PR = "studio/pricing.py"
HN = "studio/hardneed.py"
L10N = "studio/l10n.py"
EP = "studio/endpoints.py"
ER = "scripts/endpoint_report.py"

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
    (BS, '    if "speech" in spec.outputs and "video" in spec.outputs and spec.audio is None', "    if False", "голос поверх картинки не назван допущением"),
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
    (PN, "            if (\n                not узел.orderable\n                and not (hard is not None and hard.self_host and узел.self_hostable)\n", "            if (\n                False\n                and not (hard is not None and hard.self_host and узел.self_hostable)\n", "узел семьи снова кандидат"),
    (PN, "    if not реестр.orderable_for(работа) and op.name in ЗАПАСНАЯ_РАБОТА:", "    if False:", "оборот без запасной работы"),
    (PN, "    if предел_прогона(все) is not None:\n        return None\n", "", "допущение поверх своей записи"),
    (PN, "        op.name in ТОЛЬКО_РЕЕСТР or any(реестр.orderable_for(р) for р in работы)", "        op.name in ТОЛЬКО_РЕЕСТР", "неустановленные остаются при известной работе"),
    (PN, "        op.name in ТОЛЬКО_РЕЕСТР or any(реестр.orderable_for(р) for р in работы)", "        any(реестр.orderable_for(р) for р in работы)", "работы пятого круга снова из слов"),
    (PN, '        "раскраска",\n        "интерполяция_кадров",\n', '        "раскраска",\n', "интерполяция не только из реестра"),
    (ER, 'GUARDED: tuple[str, ...] = ("orderable", "priced", "with_run_length")', 'GUARDED: tuple[str, ...] = ("orderable", "with_run_length")', "гейт не держит число с ценой"),
    (ER, 'GUARDED: tuple[str, ...] = ("orderable", "priced", "with_run_length")', 'GUARDED: tuple[str, ...] = ("orderable", "priced", "with_run_length", "video")', "гейт держит лишнее поле"),
    (ER, 'BASELINE = ROOT / "studio" / "knowledge" / "endpoint_coverage.json"', 'BASELINE = ROOT / "studio" / "knowledge" / "endpoint_coverage_missing.json"', "гейт без базы"),
    (BS, '    "restore": (("video", "реставрация"),),\n', "", "реставрация снова без маршрута"),
    (BS, '                return Маршрут((шаг,), {шаг: NOTE_CAPTIONS} if задача == "captions" else {})', "                return Маршрут((шаг,), {})", "субтитры без пометки монтажа"),
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
