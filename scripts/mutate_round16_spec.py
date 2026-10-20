#!/usr/bin/env python3
"""Т1: мутация ветвей ШЕСТНАДЦАТОГО КРУГА (остальные решения — по полям spec) — в обе стороны.

    python scripts/mutate_round16_spec.py          # все мутанты
    python scripts/mutate_round16_spec.py 0 20     # мутанты с 0 по 19 (прогон частями)

Что мутируется: разбор новых полей (`anonymise`, `voiceover`, `delivery` {platform,
dynamic_range, stems, direction, format, markets}, `domain`, `style`, `subject`,
`accessibility`, `display`, `audio_content`, `follows_picture`, `animate_input`,
`community`, `inputs[].source / defects / fps`), их читатели (`studio/spec_first.py`),
поле вместо слов в оговорках чек-листа (`checklist.SPEC_FOR_WORDS`), маршруты
анонимизации (`studio/anonymise.py`, `apply.rewrite`: лица — синтетическое лицо и
замена / размытие / пикселизация; голос — расшифровка и другой голос, не дубляж),
предполагаемый референс лица у замены лица без снимка, шортс без речи по полю,
поля решений в черновике вопроса. Каждая ветвь — в обе стороны: поле проигнорировано
(решают слова) и поле решает всегда одно.

Устройство — как у `scripts/mutate_round15_spec.py`: файл правится на диске, набор
гоняется через `python -B` со снесённым `__pycache__`, файл ВОЗВРАЩАЕТСЯ как был.
Первой строкой — ЗДОРОВЫЙ прогон.

ТРИ ИСХОДА (Р1): годно — здоровый зелёный и покраснели все мутанты; не годно —
здоровый красный или хоть один промолчал; не смогли — цели мутанта нет в файле.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

НАБОРЫ = ("studio.tests.test_round16_spec",)

BS = "studio/brief_spec.py"
SF = "studio/spec_first.py"
AN = "studio/anonymise.py"
CL = "studio/recipes/checklist.py"
AP = "studio/recipes/apply.py"
DL = "studio/recipes/delivery.py"
PN = "studio/planner.py"

#: (файл, было, стало, что ломается).
MUTANTS: tuple[tuple[str, str, str, str], ...] = (
    # --- разбор полей ---------------------------------------------------------------------
    (BS, "    _поля_r16(raw, поля, ошибки)\n", "", "поля шестнадцатого круга не читаются"),
    (BS, '    if raw is False:\n        return {"faces": False, "voice": False, "method": None}',
     "    if raw is False:\n        return None", "anonymise=false не названо — решают слова"),
    (BS, '    if "voice-replace" in методы and запись["voice"] is None:',
     '    if False and запись["voice"] is None:', "метод voice-replace не включает голос"),
    (BS, '        запись["method"] = FACE_ANON_METHODS[0]', '        запись["method"] = "blur"',
     "лица без метода — размытие вместо замены"),
    (BS, '    for ключ, допустимо in (("platform", DELIVERY_PLATFORMS), ("format", DELIVERY_FORMATS)):',
     '    for ключ, допустимо in (("format", DELIVERY_FORMATS),):', "площадка сдачи не читается"),
    (BS, '        запись["markets"] = tuple(dict.fromkeys(з for з in рынки if re.fullmatch(r"[A-Z]{2}", з)))',
     '        запись["markets"] = ()', "рынки сдачи пусты"),
    (BS, '    for ключ in ("voiceover", "follows_picture", "animate_input", "community"):',
     '    for ключ in ("follows_picture", "animate_input", "community"):', "voiceover не читается"),
    (BS, '        ("domain", DOMAINS),\n', "", "domain не читается"),
    (BS, '        for ключ, допустимо in (("source", INPUT_SOURCES), ("defects", INPUT_DEFECTS)):',
     '        for ключ, допустимо in (("source", INPUT_SOURCES),):', "дефекты входа не читаются"),
    (BS, '            if not any(поле.rsplit(".", 1)[1] in в for в in входы):', "            if True:",
     "названное поле записи входа всё равно предлагается"),
    (BS, "DECISION_FIELDS = (*DECISION_FIELDS, *DECISION_FIELDS_R16)", "DECISION_FIELDS = DECISION_FIELDS",
     "поля шестнадцатого круга не в черновике"),
    (BS, "    прочитано.update(_прочитано_словами_r16(brief, низ))\n", "", "запасные слова не подсказывают новых полей"),
    # --- читатели полей -------------------------------------------------------------------------
    (SF, '    return name in (getattr(spec, "source", None) or {})', "    return False",
     "списочные поля никогда не названы"),
    (SF, "    if not площадки:\n        return None\n    return _has_any(площадки, wanted)",
     "    if not площадки:\n        return None\n    return True", "любая площадка — все оговорки площадок"),
    (SF, "    значения = _input_values(spec, \"source\")\n    return None if значения is None else _has_any(значения, wanted)",
     "    значения = _input_values(spec, \"source\")\n    return None", "источник входа не читается"),
    (SF, '    дефект = input_defect(spec, "halftone")\n    if дефект is not None:\n        return дефект\n', "",
     "дефекты входа не решают растр"),
    (SF, "    if голос is not None:\n        return not голос", "    if голос is not None:\n        return голос",
     "voiceover наоборот"),
    (SF, '    return str(анон.get("method") or "swap") if анон.get("faces") else False',
     '    return str(анон.get("method") or "swap") if анон.get("faces") else None', "faces=false — решают слова"),
    (SF, "    return None if стиль is None else стиль in wanted", "    return None", "стиль не читается"),
    (SF, "    return bool(нужды & set(wanted)) if wanted else bool(нужды)", "    return bool(нужды)",
     "субтитры включают тифлокомментарий"),
    (SF, "    рынки = _delivery(spec).get(\"markets\")\n    if not рынки:\n        return None\n    return _has_any(рынки, wanted)",
     "    рынки = _delivery(spec).get(\"markets\")\n    if not рынки:\n        return None\n    return True",
     "любой рынок — французская метка"),
    # --- оговорки чек-листа по полю -------------------------------------------------------------
    (CL, '    W_BROADCAST: lambda spec: sf.platform(spec, "broadcast"),\n', "", "эфир — только словами"),
    (CL, "    W_HALFTONE: sf.halftone,\n", "", "растр — только словами"),
    (CL, "    W_AD: sf.advertising,\n", "", "реклама — только словами"),
    (CL, "    W_NO_SPEECH: sf.no_speech,\n", "", "без речи — только словами"),
    (CL, '    W_COVER: lambda spec: True if {"image", "video"} <= set(spec.outputs) else None,',
     '    W_COVER: lambda spec: True if {"image", "video"} <= set(spec.outputs) else False,',
     "обложка без картинки на выходе глушит слова"),
    (CL, "        return поле and bool(c.steps or c.jobs) and (c.visual or bool(sf.anonymise_faces(c.spec)))",
     "        return bool(c.steps or c.jobs)", "anonymise=false всё равно с оговоркой GDPR"),
    (CL, "    поле = sf.anonymise_voice(c.spec)\n    if поле is not None:\n        return поле\n    return c.says(W_VOICE_ANON)",
     "    return c.says(W_VOICE_ANON)", "голос — только словами"),
    (CL, '    if "дубляж" not in steps and "dub" in работы and steps and anonymise_voice(spec, слова):',
     "    if False:", "анонимизация голоса считается дубляжом"),
    (CL, '    if "shorts" in c.jobs:\n        if c.spec.per_shot_s:', '    if False:\n        if c.spec.per_shot_s:',
     "шортс меряется длиной всей нарезки"),
    (CL, "CINE_FPS_MAX = 20", "CINE_FPS_MAX = 10", "16 кадров/с — не плёнка"),
    (CL, "CINE_FPS_MAX = 20", "CINE_FPS_MAX = 30", "25 кадров/с — плёнка"),
    (CL, '    поле = sf.accessibility(c.spec, "captions")\n    return (c.video and поле) if поле is not None else _a11y_video(c)',
     '    поле = sf.accessibility(c.spec, "captions")\n    return _a11y_video(c)', "субтитры — только словами"),
    (CL, r'    r"(?:disguis|anonymi[sz]|distort|mask|hid)\w*\s+', r'    r"(?:disguis|anonymi[sz]|distort|mask|hid|chang)\w*\s+',
     "«сменить голос» читается анонимизацией"),
    # --- маршруты анонимизации и замена лица ----------------------------------------------------------
    (AP, '    if method and "video" in inputs and (named or set(steps) & ANONYMISE_ROUTES):',
     '    if method and "video" in inputs and set(steps) & ANONYMISE_ROUTES:', "лица по полю — только на шаге правки"),
    (AP, "            anonymise_assembly = (an.ASSEMBLY_PIXELATE[0],)\n            acc.assembly.append(an.ASSEMBLY_PIXELATE)",
     "            anonymise_assembly = (x15.ASSEMBLY_ANON_BLUR[0],)\n            acc.assembly.append(x15.ASSEMBLY_ANON_BLUR)",
     "пикселизация размывает"),
    (AP, '    voice_anon = an.voice(spec, text) and bool(inputs & {"video", "audio"})', "    voice_anon = False",
     "голос не анонимизируется"),
    (AP, "        steps = an.voice_route(steps)\n", "", "голос — дубляж"),
    (AP, "        drop_assembly = (bs.NOTE_DUB_MUX,)\n", "", "строка дубляжа в монтаже остаётся"),
    (AP, "    if anonymise_assembly and not steps:", "    if anonymise_assembly:", "строка монтажа дважды"),
    (AP, '        avoid["озвучка"] = an.CLONE_ONLY_MODELS\n', "", "клон голоса не отодвинут"),
    (AP, '    поле = sf.subject(spec, "logo")\n    if поле is not None:\n        return поле\n', "", "логотип — только словами"),
    (AP, '        return spec.self_host.get("enabled", True) is not False', "        return True",
     "self_host=false — всё равно локально"),
    (AP, '        return поле and not any(п.get("real") for п in spec.people)', "        return True",
     "любой названный предмет — тур"),
    (AP, '    if getattr(spec, "loop", None) is not None:\n        return True\n', "", "петли визуала не двигают обложку"),
    (AP, "        return петля is False", "        return петля is True", "петля читается сценами"),
    (AP, '    поле = sf.flag(spec, "follows_picture")\n    if поле is not None:\n        return поле\n', "",
     "звук по картинке — только словами"),
    (AP, "    поле = sf.mesh_format(spec)\n    if поле is not None:\n        return поле\n", "", "3D — только словами"),
    (AP, "    поле = sf.style(spec, *sf.STYLISED_STYLES)\n    if поле is not None:\n        return поле\n", "",
     "рисованное — только словами"),
    (DL, '    печать = sf.platform(spec, "print")\n    if печать is not None:\n        return печать\n', "",
     "печать — только словами"),
    (AN, '    rest = [s for s in steps if s not in VOICE_DROPS and s not in VOICE_STEPS]',
     "    rest = [s for s in steps if s not in VOICE_STEPS]", "голос: дубляж остаётся"),
    (AN, 'VOICE_DROPS: frozenset[str] = frozenset({"дубляж", "клонирование_голоса", "липсинк"})',
     'VOICE_DROPS: frozenset[str] = frozenset({"дубляж", "клонирование_голоса", "липсинк", "замена_персонажа"})',
     "голос снимает и замену лица"),
    (AN, 'VOICE_STEPS: tuple[str, ...] = ("расшифровка", "озвучка")', 'VOICE_STEPS: tuple[str, ...] = ("озвучка",)',
     "голос без расшифровки"),
    (AN, 'REFERENCE_FACE_STEPS: frozenset[str] = frozenset({"замена_персонажа"})',
     "REFERENCE_FACE_STEPS: frozenset[str] = frozenset()", "референс лица не считается"),
    (AN, '    if step in REFERENCE_FACE_STEPS and getattr(spec, "task", None) == "face-replace":',
     '    if step in REFERENCE_FACE_STEPS and getattr(spec, "task", None) != "edit":', "референс лица у любой работы"),
    # --- плановщик ---------------------------------------------------------------------------------
    (PN, "    if isinstance(поле, bool):\n        return поле\n    return bool(COMMUNITY_ASKED.search(brief))",
     "    return bool(COMMUNITY_ASKED.search(brief))", "сообщество — только словами"),
    (PN, "    elif поле is False:\n        снято -= {ep.FLAG_COMMUNITY, ep.FLAG_STYLE_LORA}\n", "",
     "community=false не закрывает пометки"),
    (PN, '        if "anonymise_voice" in рецепт.recipes:', "        if False:", "голос: озвучка раньше расшифровки"),
    (PN, "                | anonymise.assumed_inputs(op.name, понято, ARTEFACT_IMAGE)\n", "",
     "замена лица без снимка — без кандидата"),
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
