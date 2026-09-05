#!/usr/bin/env python3
"""Мутации КАНАЛОВ, разборщиков и ЯДРА ИСХОДА.

С 2026-09-04 набор шире имени файла: к каналам добавлены `studio/pipeline.py`
(валидатор плана) и `studio/factaxis.py` (ось родов) — два модуля из двадцати,
у которых гейт заимствует ИСХОД шага, и до этого дня у них не было ни одного
мутанта. Файл не переименован намеренно: имя стоит в гейте и в трёх отчётах,
а третий мутационный харнесс — второй способ узнать известное (Е1). Долг
записан в HANDOFF.

Набор оправдался тем же прогоном: пять мутантов промолчали, и все пять
оказались разными болезнями — две дыры в тестах (`metric_blind_spot` не
сторожил никто, хотя на нём стоят ВСЕ 11 отказов планировщика; пол
относимости не проверялся на строке под полом), одна слабая фикстура (запрет
лицензии ловился соседом по строке) и две границы данных, названные вслух
(русских имён атрибутов в живой базе 0 из 284).


ЗАЧЕМ ОТДЕЛЬНЫЙ СКРИПТ, А НЕ СТРОКА В ОТЧЁТЕ

За этот день я прогнал руками около полусотни мутаций по семи модулям —
`attrfamily`, `resolution`, `lifecycle`, `ingest_portal`, `ingest_schema`,
`recheck_vendor`, `refill_queue`, — и каждый раз писал в коммит «промолчал
ноль». Это правда ровно на момент прогона: завтра кто-нибудь переставит
константу, тесты останутся зелёными, и никто не узнает. Правило Ц7: то, что
обязано выполняться всегда, — это скрипт, а не строка в отчёте.

Устройство взято у `scripts/mutate_planner.py` (Е1: второй харнесс заводить
незачем), отличается только таблицей и тем, какие тесты гоняются на каждую
мутацию — по модулю, а не всё подряд, иначе прогон занимает минуты.

ЗДОРОВЫЙ ПРОГОН ПЕЧАТАЕТСЯ ПЕРВОЙ СТРОКОЙ. На соседнем скрипте это спасало
дважды: таблица «все покраснели» поверх УЖЕ красного дерева читается как
успех, хотя не значит ничего.

ЧТО ТАКОЕ «ПРОМОЛЧАЛ» И ПОЧЕМУ ЭТО НЕ ВСЕГДА ДЫРА В ТЕСТАХ. Сегодня четыре
мутанта промолчали, и все четыре раза причина была РАЗНОЙ:

    правило близости не сторожил ни один тест        -> дыра, завёл тест
    размер в ключе кэша недостижим тестом            -> вынес функцией (Т5)
    мутация правила литерал, ставший производным     -> мутант бил по КОПИИ
    строка не встречалась в живых данных             -> граница, назвал вслух

Молчание — это вопрос, а не приговор: сначала посмотреть, ЧТО именно не
покраснело.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote, unquote

ROOT = Path(__file__).resolve().parents[1]

#: (файл, что заменить, на что, подпись, какие тесты гонять).
#: Тесты названы поимённо: гонять весь набор на каждую мутацию — минуты вместо
#: секунд, а прибор, которым лень пользоваться, не используется.
MUTANTS: list[tuple[str, str, str, str, str]] = [
    # --- семьи атрибутов: пять вопросов, на которых ответ соврал -----------
    (
        "studio/selfrag/attrfamily.py",
        '"кроме": ("price_relative",),',
        '"кроме": (),',
        "цена: «на 50% дешевле» снова считается ценой",
        "studio.mcp.tests.test_attrfamily",
    ),
    (
        # МУТИРУЕТСЯ ЕДИНСТВЕННЫЙ ЗАСЛОН, А НЕ ОДИН ИЗ ДВУХ. Сначала здесь
        # стояла мутация «убрать `portal_license` из «кроме»» — и она
        # промолчала: имя не начинается с `license`, и от семьи его держала
        # ПРИСТАВКА, а «кроме» было поясом поверх подтяжек. Ненаблюдаемый
        # заслон убран из семьи (см. комментарий там), остался один — и вот он
        # проверяется: стоит семье начать ловить подстрокой, условия площадки
        # станут лицензией модели.
        "studio/selfrag/attrfamily.py",
        '"prefixes": ("license", "licence"),',
        '"подстроки": ("license", "licence"), "prefixes": (),',
        "лицензия: приставка стала подстрокой — условия площадки станут лицензией модели",
        "studio.mcp.tests.test_attrfamily",
    ),
    (
        "studio/selfrag/attrfamily.py",
        '"кроме": ("training_resolution",),',
        '"кроме": (),',
        "разрешение: разрешение ОБУЧЕНИЯ снова предел входа",
        "studio.mcp.tests.test_attrfamily",
    ),
    (
        "studio/selfrag/attrfamily.py",
        '            "duration_quantisation",\n',
        '            "duration_quantisation",\n            "max_audio_seconds",\n',
        "длительность: длина входного ЗВУКА считается длиной ролика",
        "studio.mcp.tests.test_attrfamily",
    ),
    (
        "studio/selfrag/attrfamily.py",
        '    "cost": "price",\n',
        "",
        "синоним `cost` убран",
        "studio.mcp.tests.test_attrfamily",
    ),
    # --- голден-сет как сторож продукта (заведён 2026-09-03) ----------------
    # Мутанты бьют по ПРОДУКТУ, а не по набору: если голден-сет не краснеет от
    # подмены в продукте, он сторожит сам себя и ничего больше.
    (
        "studio/mcp/fetch.py",
        '"question; ask the policy owner rather than routing around them."',
        '"question."',
        "голден: ответ про закрытые хосты перестаёт называть Ц3 — обход на усмотрение читателя",
        "studio.mcp.tests.test_golden",
    ),
    (
        "studio/mcp/contract.py",
        "            f\"names the subject ({', '.join(leak)}): the look is the prompt's \"",
        "            f\"words: ({', '.join(leak)}): the look is the prompt's \"",
        "голден: проверялка промта бракует, но перестаёт называть причину",
        "studio.mcp.tests.test_golden",
    ),
    # --- семьи входа и выхода (заведены 2026-09-03 системным замером) -------
    (
        "studio/selfrag/attrfamily.py",
        '        "подстроки": ("input", "accepts", "reference"),',
        '        "подстроки": ("accepts",),',
        "вход: 92 строки requires_inputs снова не отвечают на вопрос «inputs»",
        "studio.mcp.tests.test_attrfamily",
    ),
    (
        "studio/selfrag/attrfamily.py",
        '        "подстроки": ("output", "produces"),',
        '        "подстроки": ("output", "produces", "input", "accepts"),',
        "выход: «что отдаёт» отвечает тем же, что «что принимает»",
        "studio.mcp.tests.test_attrfamily",
    ),
    (
        "studio/selfrag/attrfamily.py",
        "                and not any(и.lower().startswith(п) for п in занятые)",
        "                and True",
        "чужая приставка: на «что принимает модель» отвечает цена в долларах",
        "studio.mcp.tests.test_attrfamily",
    ),
    (
        "studio/selfrag/attrfamily.py",
        '    return tuple(sorted({п for правило in СЕМЬИ.values() for п in правило.get("prefixes", ())}))',
        "    return ()",
        "занятые приставки: список пуст — цена снова отвечает на вопрос о входе",
        "studio.mcp.tests.test_attrfamily",
    ),
    # --- заголовок опроса портала (заведён 2026-09-03) ----------------------
    (
        "scripts/poll_portal.py",
        '    if опрос["answered"] >= опрос["asked"]:\n        return заголовок',
        "    if True:\n        return заголовок",
        "портал: «база не знает 0» снова печатается одинаково на неполном обходе",
        "studio.mcp.tests.test_poll_portal",
    ),
    (
        "scripts/poll_portal.py",
        '    if опрос["answered"] >= опрос["asked"]:\n        return заголовок',
        "    if False:\n        return заголовок",
        "портал: оговорка о неполноте лепится и к полному обходу",
        "studio.mcp.tests.test_poll_portal",
    ),
    # --- русская дверь к спискам движка (заведена 2026-09-04) ---------------
    (
        "studio/ruwords.py",
        "            if any(н <= начало < к for н, к in занято):\n                continue",
        "            if False:\n                continue",
        "русская дверь: длинная основа не съедает место — «золотой час» даст и свет, и палитру",
        "studio.mcp.tests.test_ruwords",
    ),
    (
        "studio/ruwords.py",
        'for совпадение in re.finditer(r"(?<![а-яё])" + re.escape(основа), низ):',
        "for совпадение in re.finditer(re.escape(основа), низ):",
        "русская дверь: основа ловится внутри чужого слова — «незерновой» даст зерно",
        "studio.mcp.tests.test_ruwords",
    ),
    (
        "studio/ruwords.py",
        '    return низ + " " + " ".join(sorted(set(подставлено.values()))), подставлено',
        '    return " ".join(sorted(set(подставлено.values()))), подставлено',
        "русская дверь: слова заказчика стираются подстановкой",
        "studio.mcp.tests.test_ruwords",
    ),
    (
        "studio/mcp/lipsync_prompt.py",
        '        "translated": dict(sorted(подставлено.items())),',
        '        "translated": {},',
        "русская дверь: подстановка снова молчаливая — не видно, что понял продукт",
        "studio.mcp.tests.test_ruwords",
    ),
    (
        # ЦЕЛЬ — ТЕЛО ФУНКЦИИ, А НЕ СТРОКА ЕЁ ВЫЗОВА, и это записанная граница.
        # Мутант на `запрос = запрос_корпуса(intent)` в теле инструмента
        # ПРОМОЛЧАЛ дважды: тест зовёт функцию напрямую, а точку входа он
        # позвать не может — она грузит модель эмбеддингов, а тесту в сеть
        # нельзя (Т4). Одна строка проводки сторожится обзором, а не тестом, и
        # это сказано вслух, а не спрятано.
        "studio/mcp/server.py",
        "    запрос, _ = ruwords.для_поиска(intent)\n    return запрос",
        "    return intent",
        "русская дверь: запрос корпуса снова идёт по-русски — примеров 1 вместо 30",
        "studio.mcp.tests.test_ruwords",
    ),
    (
        "studio/ruwords.py",
        '    "синий": "indigo",',
        "",
        "догадки: «синий» снова считается точным переводом и едет в промт",
        "studio.mcp.tests.test_ruwords",
    ),
    (
        "studio/mcp/lipsync_prompt.py",
        "    elif цветные_догадки:\n        pass",
        "    elif False:\n        pass",
        "догадки: приблизительный цвет снова вакансия — палитру наберёт корпус",
        "studio.mcp.tests.test_ruwords",
    ),
    (
        "studio/mcp/lipsync_prompt.py",
        "    догадки = {ру: анг for ру, анг in догадки.items() if ру not in подставлено}",
        "    догадки = {}",
        "догадки: приблизительный цвет перестаёт замечаться вовсе",
        "studio.mcp.tests.test_ruwords",
    ),
    (
        "studio/mcp/lipsync_prompt.py",
        '    if not light_word and not догадки_слотов.get("light"):',
        "    if not light_word:",
        "догадки: приблизительный свет снова берётся из корпуса молча",
        "studio.mcp.tests.test_ruwords",
    ),
    (
        "studio/mcp/lipsync_prompt.py",
        '    elif догадки_слотов.get("saturation"):\n        pass',
        "    elif False:\n        pass",
        "догадки: приблизительная насыщенность снова берётся из корпуса",
        "studio.mcp.tests.test_ruwords",
    ),
    (
        "studio/mcp/lipsync_prompt.py",
        "            if анг in словарь:",
        "            if True:",
        "догадки: слово попадает во все слоты сразу — спрашивают не о том",
        "studio.mcp.tests.test_ruwords",
    ),
    # --- предел текста (заведён 2026-09-03) ---------------------------------
    (
        "studio/selfrag/attrfamily.py",
        '            "character_limit",\n            "max_text_length",',
        '            "max_text_length",',
        "предел текста: character_limit выпал — 10 строк снова не отвечают на вопрос",
        "studio.mcp.tests.test_attrfamily",
    ),
    (
        "studio/selfrag/attrfamily.py",
        # ЦЕЛЬ УТОЧНЕНА 2026-09-05: строка `"подстроки": ()` встречалась в файле
        # ОДИН раз, пока семей было 17. С тринадцатью новыми их стало
        # четырнадцать, мутант стал бить в первое попавшееся место, и «цель на
        # месте» перестало доказывать чистоту дерева. Поймала это самопроверка
        # `check_mutants_clean` — тем самым перебором, который заведён утром.
        '            "max_script_characters",\n        ),\n        "подстроки": (),',
        '            "max_script_characters",\n        ),\n        "подстроки": ("text", "character"),',
        "предел текста: семья ловит подстрокой — text_rendering отвечает на «сколько влезает»",
        "studio.mcp.tests.test_attrfamily",
    ),
    # --- приставка версии в имени модели (заведена 2026-09-03) --------------
    (
        "studio/selfrag/modelnames.py",
        '    low = ПРИСТАВКА_ВЕРСИИ.sub("", low)\n',
        "",
        "имена: sync-lipsync-v2 снова не та же модель, что sync-lipsync-2",
        "studio.selfrag.tests.test_modelnames",
    ),
    (
        "studio/selfrag/modelnames.py",
        'ПРИСТАВКА_ВЕРСИИ = re.compile(r"(?:(?<=[-_./ ])|^)v(?=\\d)")',
        'ПРИСТАВКА_ВЕРСИИ = re.compile(r"v(?=\\d)")',
        "имена: `v` ловится где угодно — wav2lip превращается в wa2lip",
        "studio.selfrag.tests.test_modelnames",
    ),
    # --- семья поведения (заведена 2026-09-03 по находке голден-сета) -------
    (
        "studio/selfrag/attrfamily.py",
        '"подстроки": ("failure_mode", "blind_spot", "artifact"),',
        '"подстроки": ("blind_spot", "artifact"),',
        "поведение: «на что жалуются» снова не видит failure_mode — 388 строк мимо",
        "studio.mcp.tests.test_attrfamily",
    ),
    (
        "studio/selfrag/attrfamily.py",
        '        "подстроки": ("failure_mode", "blind_spot", "artifact"),',
        '        "подстроки": ("failure_mode", "blind_spot", "artifact", "limit"),',
        "поведение: подстрока «limit» — и character_limit=5000 отвечает на «на что жалуются»",
        "studio.mcp.tests.test_attrfamily",
    ),
    (
        "studio/selfrag/attrfamily.py",
        '    "проблемы": "observed_behaviour",',
        "",
        "поведение: слово владельца «проблемы» перестаёт доводить до семьи",
        "studio.mcp.tests.test_attrfamily",
    ),
    # --- достижимость тестов гейтом ----------------------------------------
    # Дефект, ради которого проверка написана: гейт называл модули поимённо,
    # и семь файлов не назывался никто. Мутации бьют по обеим сторонам —
    # проверка, ставшая слепой, и проверка, кричащая на здоровом дереве.
    (
        "scripts/check_tests_gated.py",
        "    if путь.match(ОБРАЗЕЦ):\n        for к in корни:",
        "    if True:\n        for к in корни:",
        "достижимость: образец имени файла перестал что-либо значить",
        "studio.mcp.tests.test_tests_gated",
    ),
    (
        "scripts/check_tests_gated.py",
        '    if модуль(путь, корень) in модули:\n        return "назван поимённо"',
        '    if False:\n        return "назван поимённо"',
        "достижимость: поимённый список гейта перестал считаться",
        "studio.mcp.tests.test_tests_gated",
    ),
    (
        "scripts/check_tests_gated.py",
        '        if not (текущий / "__init__.py").is_file():\n            return False',
        "        if False:\n            return False",
        "достижимость: разорванная цепочка пакетов сходит за достижимость",
        "studio.mcp.tests.test_tests_gated",
    ),
    (
        "scripts/check_tests_gated.py",
        '            if any(часть in {".claude", "__pycache__", "node_modules"} for часть in путь.parts):',
        "            if False:",
        "достижимость: чужая рабочая копия считается нашими тестами (Ц2)",
        "studio.mcp.tests.test_tests_gated",
    ),
    # --- сторож пропущенных тестов -----------------------------------------
    (
        "scripts/check_skips.py",
        "SUITES = _наборы()",
        'SUITES = ("lipsync/tests", "studio/mcp/tests", "studio/selfrag/tests")',
        "пропуски: список наборов снова литерал и снова мимо studio/tests",
        "studio.mcp.tests.test_check_skips",
    ),
    (
        "scripts/check_skips.py",
        '    "the prompt fixtures are not on this machine",\n',
        "",
        "пропуски: честная причина «фикстур нет» стала выключенным тестом",
        "studio.mcp.tests.test_check_skips",
    ),
    # --- бриф: как сказал заказчик -----------------------------------------
    (
        "studio/planner.py",
        'кроме=("фотосесси", "фотограф", "фотоаппарат"),',
        "кроме=(),",
        "бриф: фотосессия с фотографом снова заказ на оживление",
        "studio.mcp.tests.test_brief_cues",
    ),
    (
        "studio/planner.py",
        '            "права на голос",\n',
        "",
        "бриф: вопрос юриста о правах на голос снова заказ озвучки",
        "studio.mcp.tests.test_brief_cues",
    ),
    (
        "studio/planner.py",
        '            "говорящ",\n',
        "",
        "бриф: «говорящий аватар» перестал быть липсинком",
        "studio.mcp.tests.test_brief_cues",
    ),
    (
        "studio/planner.py",
        '            "съёмок не",\n',
        "",
        "бриф: «съёмок не будет» перестало значить «с нуля»",
        "studio.mcp.tests.test_brief_cues",
    ),
    (
        "scripts/check_brief_cues.py",
        "    if чужие:",
        "    if False:",
        "счётчик: опечатка в имени операции раздувает дыру молча",
        "studio.mcp.tests.test_brief_cues",
    ),
    # --- замыкание плана по нехватке артефактов ----------------------------
    (
        "studio/planner.py",
        '    ARTEFACT_AUDIO: "озвучка",',
        '    ARTEFACT_AUDIO: "звук_фон",',
        "замыкание: нехватку речи закрывают шумами, под которые губы не двигаются",
        "studio.tests.test_planner",
    ),
    (
        "studio/planner.py",
        "    операции, дописаны = замкнуть(операции, есть)",
        "    дописаны: dict[str, str] = {}",
        "замыкание: выключено — «с нуля» снова даёт неполный план",
        "studio.tests.test_planner",
    ),
    (
        "studio/planner.py",
        '                    f"{дописаны[op.name]} никем не производится и на входе его нет"',
        '                    ""',
        "замыкание: дописанный шаг перестал помечаться — продукт дополняет заказ молча",
        "studio.tests.test_planner",
    ),
    # --- карта достижимости: три положения хоста ---------------------------
    (
        "scripts/recheck_vendor.py",
        "        if где == ЗАКРЫТ:",
        "        if где != ОТКРЫТ:",
        "страницы: «хоста нет в карте» снова равно «закрыт» — 56% базы вне наблюдения",
        "studio.mcp.tests.test_recheck_vendor",
    ),
    (
        "scripts/recheck_vendor.py",
        'НЕ_ЗАПИСАН = "не записан"',
        'НЕ_ЗАПИСАН = "закрыт"',
        "страницы: третье положение хоста слилось со вторым",
        "studio.mcp.tests.test_recheck_vendor",
    ),
    # --- счёт источников и выбор значения в заголовок ----------------------
    (
        "studio/selfrag/facts.py",
        '    return len({str(f.source_url or "") for f in facts})',
        "    return len(facts)",
        "источники: одна страница, прочитанная дважды, снова два источника",
        "studio.selfrag.tests.test_source_count",
    ),
    (
        "studio/selfrag/facts.py",
        "    return max(rows, key=дата)",
        "    return rows[0]",
        "заголовок: в него снова идёт алфавитно первое, а не самое свежее чтение",
        "studio.selfrag.tests.test_source_count",
    ),
    (
        "studio/mcp/advice.py",
        '                адреса.add(str((источник or {}).get("url") or ""))',
        "                адреса.add(str(len(адреса)))",
        "источники: страницы снова считаются по строкам, а не по адресам",
        "studio.mcp.tests.test_advice",
    ),
    # --- очередь: снимок опроса против состояния базы ----------------------
    (
        "scripts/refill_queue.py",
        "    новые = [с for с in все if not уже_знаем(с, имена)]",
        "    новые = list(все)",
        "очередь: снова предлагает семейства, которые база уже знает",
        "studio.mcp.tests.test_refill_queue",
    ),
    (
        "scripts/refill_queue.py",
        "        if modelnames.from_portal_id(эндпоинт) in известные:",
        "        if эндпоинт in известные:",
        "очередь: знание ищется по адресу эндпоинта вместо имени модели",
        "studio.mcp.tests.test_refill_queue",
    ),
    (
        "scripts/refill_queue.py",
        '        if прочитано.get(url, "") >= str(свои[-1].get("seen_on") or ""):',
        '        if прочитано.get(url, "") <= str(свои[-1].get("seen_on") or ""):',
        "очередь: перечитанное ДО изменения засчитывается как сделанное",
        "studio.mcp.tests.test_refill_queue",
    ),
    (
        "scripts/recheck_vendor.py",
        # ЦЕЛЬ УТОЧНЕНА 2026-09-03: строка встречалась в файле ДВАЖДЫ (первая —
        # решение переспросить, вторая — решение записать страницу обрезанной),
        # и мутант бил по первой, а подпись говорила про вторую. Прибор,
        # который не обещает, что именно он мерит, мерит не то.
        '            if ответ.get("truncated"):\n                обрезаны.append(url)',
        "            if False:\n                обрезаны.append(url)",
        "страницы: обрезанный на потолке ответ снова считается страницей",
        "studio.mcp.tests.test_recheck_vendor",
    ),
    (
        "scripts/recheck_vendor.py",
        "            if если_второй is None or если_второй != свежий:",
        "            if False:",
        "страницы: второе чтение перестало сверяться — шум снова изменение",
        "studio.mcp.tests.test_recheck_vendor",
    ),
    (
        "scripts/recheck_vendor.py",
        '    re.compile(r"hf-sanitized-[a-z0-9]{8,}", re.I),',
        "    re.compile(r'НЕ-ВСТРЕТИТСЯ-НИКОГДА'),",
        "страницы: случайный класс HuggingFace снова в отпечатке",
        "studio.mcp.tests.test_recheck_vendor",
    ),
    (
        "scripts/refill_queue.py",
        '                + (f" [сверено с источником {сверено}]" if сверено else ""),',
        '                + "",',
        "очередь: сверка с источником перестала показываться читателю",
        "studio.mcp.tests.test_refill_queue",
    ),
    (
        "scripts/refill_queue.py",
        '            bool(r.get("не кандидат")),',
        "            False,",
        "очередь: строки, которые никуда не доедут, снова наверху",
        "studio.mcp.tests.test_refill_queue",
    ),
    (
        "scripts/recheck_vendor.py",
        "            ответ = fetch.fetch(url, max_bytes=ПОТОЛОК_ПОВТОРА)",
        "            ответ = fetch.fetch(url)",
        "страницы: переспрос идёт с тем же потолком — толстая страница потеряна",
        "studio.mcp.tests.test_recheck_vendor",
    ),
    (
        "scripts/recheck_vendor.py",
        '            if ответ.get("truncated"):\n                обрезаны.append(url)',
        "            if False:\n                обрезаны.append(url)",
        "страницы: не влезшая и во второй потолок снова считается прочитанной",
        "studio.mcp.tests.test_recheck_vendor",
    ),
    (
        "scripts/refill_queue.py",
        '            str(r.get("сверено") or ""),',
        '            "",',
        "очередь: свежесть сверки перестала решать порядок внутри причины",
        "studio.mcp.tests.test_refill_queue",
    ),
    (
        "scripts/refill_queue.py",
        '                "сверено": сверено,',
        '                "сверено": "",',
        "очередь: дата сверки не доезжает до сортировки",
        "studio.mcp.tests.test_refill_queue",
    ),
    # --- разрешение: предел кадра ------------------------------------------
    (
        "studio/resolution.py",
        '        return Предел(None, размер, "годно", f"ступень {лучшая}: {СТОРОНА_НЕ_УГАДЫВАЕТСЯ}")',
        '        return Предел(int(размер * 16 / 9), размер, "годно", "достроено по 16:9")',
        "разрешение: 720p достраивается до 1280x720 за вендора",
        "studio.tests.test_resolution",
    ),
    (
        "studio/resolution.py",
        '    if предел.outcome != "годно":\n        return {"outcome": "не смогли"',
        '    if предел.outcome != "годно":\n        return {"outcome": "годно"',
        "разрешение: неразобранный предел считается «влезает»",
        "studio.tests.test_resolution",
    ),
    (
        "studio/resolution.py",
        "    длинная, короткая = max(кадр), min(кадр)",
        "    длинная, короткая = кадр[0], кадр[1]",
        "разрешение: сравнение по ширине вместо длинной стороны",
        "studio.tests.test_resolution",
    ),
    # --- конец службы -------------------------------------------------------
    (
        "studio/lifecycle.py",
        "    if РАБОТАЕТ.search(текст):\n        return []",
        "    if False:\n        return []",
        "снятие: «всё ещё зовётся» больше не спасает рабочую модель",
        "studio.tests.test_lifecycle",
    ),
    (
        "studio/lifecycle.py",
        "        if СИМВОЛ_КОДА.search(до):\n            continue",
        "        if False:\n            continue",
        "снятие: устаревший класс библиотеки считается снятой моделью",
        "studio.tests.test_lifecycle",
    ),
    (
        "studio/lifecycle.py",
        '        "не годно" if прошло else "не смогли",',
        '        "не годно",',
        "снятие: «отключат через месяц» неотличимо от «уже отключена»",
        "studio.tests.test_lifecycle",
    ),
    # --- канал схем ---------------------------------------------------------
    (
        "scripts/ingest_schema.py",
        'МЕДИА_ПОЛЕ = re.compile(r"_urls?$", re.I)',
        'МЕДИА_ПОЛЕ = re.compile(r"", re.I)',
        "схемы: суффикс `_url` не требуется — флаг становится входом",
        "studio.mcp.tests.test_ingest_schema",
    ),
    (
        "scripts/ingest_schema.py",
        '    if str(тело.get("type") or "") in СКАЛЯР:\n        return ""',
        '    if False:\n        return ""',
        "схемы: `seed` и `duration` считаются артефактом выхода",
        "studio.mcp.tests.test_ingest_schema",
    ),
    (
        "scripts/ingest_schema.py",
        "ПОВТОРОВ = 1",
        "ПОВТОРОВ = 5",
        "схемы: молчащий хост переспрашивается пять раз",
        "studio.mcp.tests.test_ingest_schema",
    ),
    # --- канал портала ------------------------------------------------------
    (
        "scripts/ingest_portal.py",
        '    if запись.get("hidePricing"):\n        return ""',
        '    if False:\n        return ""',
        "портал: скрытая цена пишется как есть",
        "studio.mcp.tests.test_ingest_portal",
    ),
    (
        "scripts/ingest_portal.py",
        "БЛИЗОСТЬ = 60",
        "БЛИЗОСТЬ = 10000",
        "портал: единица цены берётся от ЛЮБОГО тарифа строки",
        "studio.mcp.tests.test_ingest_portal",
    ),
    # --- наблюдение за вендорскими страницами -------------------------------
    (
        "scripts/recheck_vendor.py",
        '    очищено = СКРИПТЫ.sub(" ", текст or "")',
        '    очищено = текст or ""',
        "страницы: тело скриптов снова часть отпечатка",
        "studio.mcp.tests.test_recheck_vendor",
    ),
    (
        "scripts/recheck_vendor.py",
        'прежний = предыдущая.get("fingerprint") if предыдущая.get("method") == СПОСОБ else None',
        'прежний = предыдущая.get("fingerprint")',
        "страницы: отпечатки РАЗНЫХ правил сравниваются между собой",
        "studio.mcp.tests.test_recheck_vendor",
    ),
    # --- очередь ------------------------------------------------------------
    (
        "scripts/refill_queue.py",
        "    CHANGED_SOURCE: 0,",
        "    CHANGED_SOURCE: 3,",
        "очередь: наблюдение об изменении ниже догадки о возрасте",
        "studio.mcp.tests.test_refill_queue",
    ),
    (
        "scripts/refill_queue.py",
        '        if any(о.get("reason") == "answered" for о in ответы):\n            continue',
        "        if False:\n            continue",
        "очередь: промахи не пересчитываются по нынешней базе",
        "studio.mcp.tests.test_refill_queue",
    ),
    # --- голден-сет задач (заведён 2026-09-03) ------------------------------
    (
        "scripts/check_golden.py",
        '    провалы = [с for с in строки if с["исход"] == FAIL and с["ждём"] == СТОРОЖ]',
        '    провалы = [с for с in строки if с["исход"] == FAIL]',
        "голден: провал цели снова красит гейт — набор выключат на второй день",
        "studio.mcp.tests.test_golden",
    ),
    (
        "scripts/check_golden.py",
        '    цели_открыты = [с for с in строки if с["исход"] == FAIL and с["ждём"] == ЦЕЛЬ]',
        "    цели_открыты = []",
        "голден: невзятая цель перестаёт считаться — работа впереди исчезает из отчёта",
        "studio.mcp.tests.test_golden",
    ),
    (
        "scripts/check_golden.py",
        '    if задача.get("оценка") != МАШИННО:',
        "    if False:",
        "голден: «смотрится глазами» сворачивается в машинную проверку",
        "studio.mcp.tests.test_golden",
    ),
    (
        "scripts/check_golden.py",
        "            if прошло == len(соседи):",
        "            if False:",
        "голден: холостая проверка перестаёт ловиться — набор не может не пройти",
        "studio.mcp.tests.test_golden",
    ),
    (
        "scripts/check_golden.py",
        "    raise KeyError(вид)",
        "    return True",
        "голден: опечатка в виде проверки молча считается пройденной",
        "studio.mcp.tests.test_golden",
    ),
    # === ЯДРО ИСХОДА: валидатор пайплайна и ось родов ======================
    # ЗАЧЕМ ЗДЕСЬ, А НЕ ОТДЕЛЬНЫМ СКРИПТОМ: машинерия уже написана, а третий
    # харнесс — второй способ узнать известное (Е1). Имя файла после этого
    # уже́ у́же содержимого; долг записан в HANDOFF.
    #
    # ПОЧЕМУ ЭТИ ДВА МОДУЛЯ ПЕРВЫМИ ИЗ ДВАДЦАТИ БЕЗ МУТАНТОВ: у них гейт
    # заимствует ИСХОД шага. `pipeline.CLASS_OUTCOME` решает, чем кончится
    # план, `factaxis.APPLICABILITY` — считается ли строка свидетельством.
    # Константа, переставленная здесь, красит красное зелёным по всей выдаче.
    # === КАНАЛ CIVITAI (studio/civitai.py) =================================
    (
        "studio/civitai.py",
        "МИНИМУМ_СИМВОЛОВ = 25",
        "МИНИМУМ_СИМВОЛОВ = 0",
        "civitai: реплика в два слова снова считается находкой",
        "studio.tests.test_thresholds_guarded",
    ),
    (
        "studio/civitai.py",
        "МАКСИМУМ_СИМВОЛОВ = 400",
        "МАКСИМУМ_СИМВОЛОВ = 100000",
        "civitai: простыня целиком уезжает в базу как одно утверждение",
        "studio.tests.test_thresholds_guarded",
    ),
    (
        "studio/civitai.py",
        "МИНИМУМ_СИМВОЛОВ = 25",
        "МИНИМУМ_СИМВОЛОВ = 390",
        "строже: осмысленная реплика практика объявлена слишком короткой",
        "studio.tests.test_thresholds_guarded",
    ),
    # === ЗНАНИЕ ПРОМТ-ПОЛОВИНЫ (studio/knowledge.py) =======================
    # Пороги поиска: ошибка здесь не видна в исходе, она видна в том, ЧТО
    # продукт нашёл и о чём промолчал.
    #
    # ЗДЕСЬ ТОЛЬКО НИЖНЯЯ СТОРОНА ПОРОГА, И ЭТО ЗАПИСАННАЯ ГРАНИЦА, А НЕ
    # НЕДОДЕЛКА. Мутации `DENSE_FLOOR = 0.99` и `STRUCTURAL_MIN_FIELDS = 0` на
    # доступной фикстуре молчат: корпус `tiny_index` мал, все его записи
    # проходят лексическими каналами, и плотный со структурным ничего не
    # добавляют (ИЗМЕРЕНО 2026-09-04: находок 4 при полах 0.35, 0.0 и 0.99).
    # Разбор и тест-заметка — в `studio/tests/test_thresholds_guarded.py`.
    (
        "studio/knowledge.py",
        "DENSE_FLOOR = 0.35",
        "DENSE_FLOOR = 0.0",
        "поиск: к запросу относится любая запись корпуса",
        "studio.tests.test_knowledge",
    ),
    # === ОБЕЩАНИЕ В ОПИСАНИИ НАВЫКА (тест-сторож) =========================
    # Мутируется сам сторож: если он перестанет ловить оборот, описание сможет
    # снова пообещать оценённый корпус, и никто не заметит.
    (
        "studio/mcp/tests/test_skill_claims.py",
        "        описание = _описание()",
        '        описание = ""',
        "сторож обещаний: описание больше не читается вовсе",
        "studio.mcp.tests.test_skill_claims",
    ),
    (
        "studio/mcp/tests/test_skill_claims.py",
        'ОБЕЩАНИЕ_ОЦЕНКИ = ("run and rated", "actually rated", "оценённых промптов")',
        'ОБЕЩАНИЕ_ОЦЕНКИ = ("не-встречается-нигде",)',
        "сторож обещаний: список оборотов опустел",
        "studio.mcp.tests.test_skill_claims",
    ),
    # === СУД НАД ПРОМПТОМ ИЗ ЛЮБОГО ИСТОЧНИКА (studio/mcp/contract.py) ====
    (
        "studio/mcp/contract.py",
        "    banned = banned_topics(text)",
        "    banned = []",
        "промпт: запретные темы студии снова не спрашиваются",
        "studio.mcp.tests.test_contract_topics",
    ),
    (
        "studio/mcp/contract.py",
        "    указания = [о for о in ЧУЖИЕ_УКАЗАНИЯ if о in text.lower()]",
        "    указания = []",
        "промпт: указание читателю снова проезжает",
        "studio.mcp.tests.test_contract_topics",
    ),
    (
        "studio/mcp/contract.py",
        '    "ignore all previous",\n    "ignore previous instructions",',
        '    "ignore previous instructions",',
        "промпт: самый частый оборот выпал из списка",
        "studio.mcp.tests.test_contract_topics",
    ),
    # === СКВОЗНОЙ ПРОГОН ФОРКА (lipsync/fork_e2e.py) ======================
    # 12 констант-решений: пороги приёмки готового ролика. Ошибка тут пропускает
    # брак В ВЫДАЧУ ЗАКАЗЧИКУ, а не в базу.
    (
        "lipsync/fork_e2e.py",
        "MIN_SCENE_S = 3.0",
        "MIN_SCENE_S = 0.0",
        "приёмка: сцена нулевой длины считается сценой",
        "lipsync.tests.test_fork_e2e",
    ),
    (
        "lipsync/fork_e2e.py",
        "MAX_CUTS_OUT = 0",
        "MAX_CUTS_OUT = 99",
        "приёмка: склейки в выдаче перестали быть браком",
        "lipsync.tests.test_fork_e2e",
    ),
    (
        "lipsync/fork_e2e.py",
        "STYLE_MARGIN_MIN = 0.05",
        "STYLE_MARGIN_MIN = 0.0",
        "приёмка: запас по стилю перестал требоваться",
        "lipsync.tests.test_fork_e2e",
    ),
    # === ЛИНТЕР ШАБЛОНА (studio/template_lint.py) =========================
    (
        "studio/template_lint.py",
        "REPETITION_MIN_WORD_LETTERS = 3",
        "REPETITION_MIN_WORD_LETTERS = 99",
        "линтер: повтор слова перестал замечаться вовсе",
        "studio.tests.test_template_lint",
    ),
    (
        "studio/template_lint.py",
        "CROSS_ELEMENT_MIN_CHARS = 4",
        "CROSS_ELEMENT_MIN_CHARS = 1",
        "линтер: совпадение в один знак объявлено повтором между элементами",
        "studio.tests.test_template_lint",
    ),
    # === СТОРОЖ «НАЗВАНО, НО НЕ СПРОШЕНО» (studio/named_not_asked.py) =====
    # Тот самый хук, который не даёт закончить ход с именем модели, о котором
    # не спрашивали базу.
    (
        "studio/named_not_asked.py",
        "FAMILY_MIN = 3",
        "FAMILY_MIN = 99",
        "сторож имён: семейное имя перестало опознаваться",
        "studio.tests.test_named_not_asked",
    ),
    (
        "studio/factaxis.py",
        "    if fact.tier in WITNESS_TIERS and (fact.tier != TIER_PROBE or зонд_состоялся(fact)):",
        "    if fact.tier in WITNESS_TIERS:",
        "свидетельство: объявленный тир зонда снова принимается на слово",
        "studio.mcp.tests.test_factaxis",
    ),
    (
        "studio/selfrag/facts.py",
        "    if not 1 <= месяц <= 12:",
        "    if False:",
        "даты: невозможный месяц идентификатора снова становится датой публикации",
        "studio.selfrag.tests.test_published_on",
    ),
    (
        "studio/pricing.py",
        '        if p.outcome != "годно" or p.amount is None or not p.unit or not p.per:',
        '        if p.outcome != "годно" or p.amount is None or not p.unit:',
        "сумма: цены за РАЗНОЕ снова складываются в одно число",
        "studio.mcp.tests.test_pricing",
    ),
    (
        "studio/mcp/fetch.py",
        '        "why_wanted": причина_для_записи(why_wanted),',
        '        "why_wanted": why_wanted,',
        "приватность: текст заказчика снова уезжает в репозиторий дословно",
        "studio.mcp.tests.test_denied_reason_is_safe",
    ),
    (
        "studio/app.py",
        "        if not session_id:",
        "        if False:",
        "доступ: задачу снова отдают тому, кто не назвал сессию",
        "studio.tests.test_app",
    ),
    (
        "studio/app.py",
        "        if чья is not None and чья != session_id:",
        "        if False:",
        "доступ: чужая сессия снова получает результат по идентификатору задачи",
        "studio.tests.test_app",
    ),
    (
        "studio/app.py",
        '    if charged.get("duplicate"):',
        "    if False:",
        "деньги: повтор ключа снова выдаётся за оплату — платное видео без списания",
        "studio.tests.test_app",
    ),
    (
        "scripts/check_mutants_clean.py",
        "        if старое in новое:",
        "        if False:",
        "мутанты: дописывающий мутант снова невидим — 13 из 354 без охраны",
        "studio.mcp.tests.test_mutants_not_leaked",
    ),
    # === ЖУРНАЛ БЕЗ ПЕРЕПИСЫВАНИЯ (studio/appendonly.py) ==================
    (
        "studio/pricing.py",
        '        if not единица and "$" not in текст:',
        "        if False:",
        "цена: голое число без единого признака валюты снова объявляется долларами",
        "studio.mcp.tests.test_price_naming",
    ),
    (
        # Сторож сторожа: этой проверкой держится то, что мутанты вообще
        # что-то значат, и её ослабление обязано краснеть так же, как
        # ослабление любого другого решения.
        "scripts/check_mutants_clean.py",
        "        if сколько == 1:",
        "        if сколько >= 1:",
        "мутанты: цель в двух местах снова считается целой — утечка в неё не видна",
        "studio.mcp.tests.test_mutants_not_leaked",
    ),
    (
        "studio/appendonly.py",
        # ЦЕЛЬ УТОЧНЕНА 2026-09-05: мутант бил по ИМЕНИ константы, а имя
        # встречается в файле дважды — определение и место, где по ней
        # решают. Подменялось первое, второе оставалось со старым именем, и
        # тест краснел от NameError, то есть мерил опечатку, а не охрану.
        # Теперь подменяется значение: оно и есть решение (по нему сверяются
        # прошлая и новая строка журнала), и в файле оно одно.
        'МЕТКА_УДАЛЁННОГО_НИКА = "ник удалён"',
        'МЕТКА_УДАЛЁННОГО_НИКА = "ник убран"',
        "журнал: метка удалённого ника перестала совпадать",
        "studio.mcp.tests.test_appendonly",
    ),
    # === ПОРОГИ ОЦЕНКИ ПОИСКА (studio/selfrag/evaluate.py) ================
    (
        "studio/selfrag/evaluate.py",
        "RECALL_FLOOR = 0.75",
        "RECALL_FLOOR = 0.0",
        "оценка поиска: полнота перестала требоваться",
        "studio.selfrag.tests.test_floors_bite",
    ),
    (
        "studio/selfrag/evaluate.py",
        "ABSTENTION_FLOOR = 1.0",
        "ABSTENTION_FLOOR = 0.0",
        "оценка поиска: молчать на негативном контроле больше не обязательно",
        "studio.selfrag.tests.test_floors_bite",
    ),
    # === ПРИЁМКА КОРПУСНОЙ СТРОКИ (studio/selfrag/corpus.py) ==============
    (
        "studio/selfrag/corpus.py",
        "RATING_MAX = 10",
        "RATING_MAX = 100",
        "корпус: верх оценочной полосы разъехался со шкалой формата",
        "studio.selfrag.tests.test_corpus_bounds",
    ),
    (
        "studio/selfrag/corpus.py",
        "RATING_MIN = 1",
        "RATING_MIN = 2",
        "корпус: единица перестала быть оценкой",
        "studio.selfrag.tests.test_corpus_bounds",
    ),
    (
        "studio/selfrag/corpus.py",
        "PROMPT_MAX_CHARS = 4000",
        "PROMPT_MAX_CHARS = 400000",
        "корпус: потолок длины пускает вставленный документ вместо промпта",
        "studio.selfrag.tests.test_corpus_bounds",
    ),
    # === ПОЛЫ РЕТРИВЕРА (studio/selfrag/retrieval.py) =====================
    (
        "studio/selfrag/retrieval.py",
        "MIN_TERM_HITS = 2",
        "MIN_TERM_HITS = 1",
        "ретривер: одного общего слова снова хватает, чтобы ответить",
        "studio.selfrag.tests.test_retrieval_floors",
    ),
    (
        "studio/selfrag/retrieval.py",
        "RATING_PRIOR_FLOOR = 6",
        "RATING_PRIOR_FLOOR = 5",
        "ретривер: середина шкалы поехала на канале рейтинга",
        "studio.selfrag.tests.test_retrieval_floors",
    ),
    # === ОЦЕНЩИК КАЧЕСТВА ПРОМПТА (studio/selfrag/quality.py) =============
    (
        "studio/selfrag/quality.py",
        "MIN_CORPUS = 50",
        "MIN_CORPUS = 5",
        "качество: перцентиль по горстке строк выдаётся за стандарт корпуса",
        "studio.selfrag.tests.test_quality_floors",
    ),
    (
        "studio/selfrag/quality.py",
        "GOOD_PERCENTILE = 0.10",
        "GOOD_PERCENTILE = 0.0",
        "качество: низ распределения опущен до нуля, брак невозможен",
        "studio.selfrag.tests.test_quality_floors",
    ),
    # === ЗНАК ПРИМЕНИМОСТИ (studio/factaxis.py, studio/selfrag/facts.py) ===
    (
        "studio/factaxis.py",
        "    if fact.contra is not None:\n        return fact.contra",
        "    if False:\n        return fact.contra",
        "знак: объявленный знак факта перестал перебивать имя атрибута",
        "studio.tests.test_sign_is_explicit",
    ),
    (
        "studio/factaxis.py",
        "    if fact.contra is not None:\n        return fact.contra",
        "    if fact.contra is None:\n        return bool(fact.contra)",
        "знак: объявленный знак прочитан наоборот",
        "studio.tests.test_sign_is_explicit",
    ),
    (
        "studio/selfrag/facts.py",
        '                    contra=(None if row.get("contra") is None else bool(row.get("contra"))),',
        '                    contra=bool(row.get("contra")),',
        "знак: «не объявлен» свёрнут в «хорошая новость» при чтении файла",
        "studio.tests.test_sign_is_explicit",
    ),
    # === СНЯТИЕ МОДЕЛИ РЕШАЕТ РАЗБОР (studio/pipeline.py) =================
    (
        "studio/pipeline.py",
        "        if снятие.outcome == lifecycle.НЕ_ГОДНО:",
        "        if снятие.outcome != lifecycle.НЕ_ГОДНО:",
        "снятие: разбор прочитан наоборот — живые модели объявляются снятыми",
        "studio.tests.test_stale_asks_lifecycle",
    ),
    (
        "studio/pipeline.py",
        "        if снятие.outcome == lifecycle.НЕ_СМОГЛИ:",
        "        if False:",
        "снятие: объявленное впереди снятие замолчано — заказчик узнает от вендора",
        "studio.tests.test_stale_asks_lifecycle",
    ),
    # === КОДЫ ВОЗВРАТА ПРИБОРОВ (scripts/run_tests.py, mutate_planner.py) ==
    (
        "scripts/run_tests.py",
        "    if итог.testsRun == 0:",
        "    if False:",
        "раннер: пустой прогон снова считается успехом",
        "studio.mcp.tests.test_runner",
    ),
    (
        "scripts/mutate_planner.py",
        "    return 1 if молчали else 0",
        "    return 0",
        "мутатор планировщика: промолчавший мутант снова не красит гейт",
        "studio.mcp.tests.test_mutate_exit_codes",
    ),
    # === ОТВЕТ ЗАКАЗЧИКУ НАЗЫВАЕТ ПРИЧИНУ (studio/planner.py) =============
    (
        "studio/planner.py",
        '        for проба in _сработавшие(итог, s["step"]):',
        "        for проба in []:",
        "ответ: причина отказа снова не доходит до блока шага",
        "studio.tests.test_render_says_why",
    ),
    (
        "studio/planner.py",
        '            if p.get("fired") and p.get("outcome") == FAIL and p.get("note")',
        '            if p.get("note")',
        "ответ: молчание базы печатается как причина отказа",
        "studio.tests.test_render_says_why",
    ),
    (
        "studio/planner.py",
        '            f", из них {self.against} о том, где ломается"',
        '            f", из них {self.against} строк(и)"',
        "пометка: знак плохих новостей стёрт из витрины",
        "studio.tests.test_mark_carries_sign",
    ),
    # === ЦЕНА ЗА МИЛЛИОН И ПУСТОЙ КОРПУС =================================
    (
        "studio/pricing.py",
        '    if за in ("token", "") and _ЗА_МИЛЛИОН.search(текст):',
        "    if False:",
        "цена: «за 1M токенов» снова читается как «за токен» — ошибка в миллион раз",
        "studio.tests.test_price_per_million",
    ),
    (
        "studio/pipeline.py",
        'PER_NOT_PER_RUN: frozenset[str] = frozenset({"token", "1m_tokens"})',
        "PER_NOT_PER_RUN: frozenset[str] = frozenset()",
        "цена: цена за объём текста снова сравнивается с бюджетом одного прогона",
        "studio.tests.test_price_per_million",
    ),
    (
        "studio/selfrag/pipeline.py",
        "            if outcome == PASS:\n                outcome = UNMEASURED\n        if avail[",
        "            if False:\n                outcome = UNMEASURED\n        if avail[",
        "промпт: сборка без единого прецедента снова объявляется годной",
        "studio.selfrag.tests.test_empty_corpus_is_not_pass",
    ),
    (
        "studio/selfrag/replay.py",
        "                \"WHERE artifact IS NOT NULL AND TRIM(artifact) != '' ORDER BY id\"",
        '                "ORDER BY id"',
        "обратная связь: непроверяемая оценка снова поднимает запись в выдаче",
        "studio.selfrag.tests.test_replay_needs_artifact",
    ),
    # === ДЕНЬГИ ЗАКАЗЧИКА И РОД ОТКАЗА ===================================
    (
        "studio/app.py",
        "    if стадия == STAGE_VIDEO_RUNNING:",
        "    if False:",
        "согласие: второй запуск видео по одному согласию снова оплачивается",
        "studio.tests.test_consent_is_single_use",
    ),
    (
        "studio/app.py",
        "    if стадия == STAGE_DONE:",
        "    if False:",
        "согласие: завершённая работа снова разрешает начать новую за деньги",
        "studio.tests.test_consent_is_single_use",
    ),
    (
        "studio/mcp/probe.py",
        "MEASURING_STATUSES: frozenset[int] = frozenset({400, 422})",
        "MEASURING_STATUSES: frozenset[int] = frozenset(range(400, 600))",
        "зонд: отказ авторизации снова выдаётся за измерение предела модели",
        "studio.mcp.tests.test_probe_refusal_kinds",
    ),
    # === АРИФМЕТИКА КАДРОВ (lipsync/framemath.py) =========================
    (
        "lipsync/framemath.py",
        "SECONDS_MIN = 5.0",
        "SECONDS_MIN = 0.0",
        "кадры: ролик нулевой длины проходит по нижней границе",
        "lipsync.tests.test_fork_looper",
    ),
    (
        "lipsync/framemath.py",
        "SECONDS_MAX = 10.0",
        "SECONDS_MAX = 1000.0",
        "кадры: верхняя граница длины перестала действовать",
        "lipsync.tests.test_fork_looper",
    ),
    # === ВЕБ-ПОТОК СТУДИИ (studio/app.py) =================================
    # Имена стадий — константы-решения самого продукта: по ним решается, что
    # заказчику показать и что ему уже можно запускать.
    (
        "studio/app.py",
        "    if stage in (STAGE_FRAME_SHOWN, STAGE_CONSENTED, STAGE_VIDEO_RUNNING, STAGE_DONE):",
        "    if stage in (STAGE_FRAME_SHOWN, STAGE_CONSENTED, STAGE_VIDEO_RUNNING):",
        "поток: завершённая сессия выпала из разрешённых стадий",
        "studio.tests.test_stage_outcomes",
    ),
    (
        "studio/app.py",
        "    if стадия != STAGE_CONSENTED:",
        "    if False:",
        "поток: согласие заказчика перестало пускать дальше",
        "studio.tests.test_app",
    ),
    # === ОЦЕНКА СЛЕПОГО НАБОРА (scripts/score_validation.py) ==============
    (
        "scripts/score_validation.py",
        "MIN_ANSWERED = 20",
        "MIN_ANSWERED = 0",
        "оценка: слепой набор из нуля ответов считается набором",
        "studio.mcp.tests.test_score_validation",
    ),
    # === ВЫБОР УСТРОЙСТВА (lipsync/device.py) =============================
    (
        "lipsync/device.py",
        'INSIGHTFACE_GPU_DEVICES = ("cuda",)',
        "INSIGHTFACE_GPU_DEVICES = ()",
        "устройство: видеокарта перестала считаться видеокартой",
        "lipsync.tests.test_device",
    ),
    # === РАМКА КАДРА (lipsync/fork_plan.py) ===============================
    # Пороги, по которым кадр объявляется годным для форка: ошибка режет лицо
    # заказчику, и видно это только глазами.
    (
        "lipsync/fork_plan.py",
        "CENTRE_TOL = 0.08",
        "CENTRE_TOL = 1.0",
        "рамка: лицо у самого края считается центрированным",
        "lipsync.tests.test_fork_plan",
    ),
    (
        "lipsync/fork_plan.py",
        "WIDTH_MAX = 0.72",
        "WIDTH_MAX = 0.01",
        "строже: любой кадр объявлен слишком широким",
        "lipsync.tests.test_fork_plan",
    ),
    # === ПРИЁМКА ВХОДА (lipsync/fork_intake.py) ===========================
    (
        "lipsync/fork_intake.py",
        "PHOTO_PEOPLE_EXPECTED = 1",
        "PHOTO_PEOPLE_EXPECTED = 9",
        "приёмка: на селфи ждут девятерых",
        "lipsync.tests.test_fork_intake",
    ),
    (
        "lipsync/fork_intake.py",
        "ORPHAN_WRIST_WARN = 0.10",
        "ORPHAN_WRIST_WARN = 1.1",
        "приёмка: осиротевшее запястье больше не поводом для предупреждения",
        "lipsync.tests.test_fork_intake",
    ),
    # === СВЕДЕНИЕ ГОТОВОГО (lipsync/fork_finish.py) =======================
    (
        "lipsync/fork_finish.py",
        "DIM_MULTIPLE = 2",
        "DIM_MULTIPLE = 1",
        "сведение: нечётный размер кадра перестал выравниваться",
        "lipsync.tests.test_fork_finish",
    ),
    (
        "lipsync/fork_finish.py",
        "BIAS_GAIN_MIN = 1.05",
        "BIAS_GAIN_MIN = 0.0",
        "сведение: любое усиление считается достаточным",
        "lipsync.tests.test_fork_finish",
    ),
    # === МАРШРУТЫ ДОЧИТЫВАНИЯ (studio/mcp/routes.py) ======================
    (
        "studio/mcp/routes.py",
        "ГОРИЗОНТ_ДНЕЙ = 3",
        "ГОРИЗОНТ_ДНЕЙ = 3650",
        "очередь: горизонт растянут на десять лет — срочное перестало быть срочным",
        "studio.mcp.tests.test_routes",
    ),
    (
        "studio/mcp/routes.py",
        "ГОРИЗОНТ_ДНЕЙ = 3",
        "ГОРИЗОНТ_ДНЕЙ = 0",
        "строже: в очередь не попадает ничего",
        "studio.mcp.tests.test_routes",
    ),
    # === ТИР ПО ХОЗЯИНУ СТРАНИЦЫ (studio/selfrag/source_hosts.py) =========
    # Кто написал страницу — вендор или пользователь площадки: от этого зависит
    # тир факта, то есть его вес во всех сравнениях.
    (
        "studio/selfrag/source_hosts.py",
        # МУТАЦИЯ ПЕРЕПИСАНА: первая редакция подставляла
        # `frozenset() or frozenset({...})`, что по-питоновски равно исходному
        # множеству. Мутант был НЕ-ОПЕРАЦИЕЙ, и его молчание не значило ничего.
        '    {"discussions", "issues", "community", "forum", "comments", "pull"}',
        '    {"issues", "community", "forum", "comments", "pull"}',
        "тир: обсуждение на странице модели перестало понижаться до blog",
        "studio.selfrag.tests.test_source_hosts",
    ),
    # === СВЕДЕНИЕ ВИДЕО (lipsync/fork_video.py) ===========================
    (
        "lipsync/fork_video.py",
        "FRAME_COUNT_TOLERANCE = 1",
        "FRAME_COUNT_TOLERANCE = 1000",
        "сведение: расхождение в тысячу кадров считается совпадением",
        "lipsync.tests.test_fork_video",
    ),
    (
        "lipsync/fork_video.py",
        "FPS_TOLERANCE = 0.01",
        "FPS_TOLERANCE = 100.0",
        "сведение: любая частота кадров совпадает с любой",
        "lipsync.tests.test_fork_video",
    ),
    # === ДОКАЗАТЕЛЬСТВО ИЗ КОРПУСА (studio/selfrag/evidence.py) ============
    (
        "studio/selfrag/evidence.py",
        "CRAFT_SHARE = 0.5",
        "CRAFT_SHARE = 0.0",
        "доказательство: любая фраза считается ремесленной",
        "studio.selfrag.tests.test_evidence",
    ),
    (
        "studio/selfrag/evidence.py",
        "MIN_PHRASE_WORDS = 3",
        "MIN_PHRASE_WORDS = 1",
        "доказательство: одно слово объявлено фразой",
        "studio.selfrag.tests.test_bounds_literal",
    ),
    (
        "studio/selfrag/evidence.py",
        "MAX_PHRASE_WORDS = 6",
        "MAX_PHRASE_WORDS = 60",
        "доказательство: целое предложение объявлено фразой",
        "studio.selfrag.tests.test_bounds_literal",
    ),
    # === РЕЕСТР КАРТОЧЕК (studio/selfrag/registry.py) ======================
    (
        "studio/selfrag/registry.py",
        "STALE_AFTER_DAYS = 90",
        "STALE_AFTER_DAYS = 36500",
        "реестр: столетняя карточка модели считается свежей",
        "studio.selfrag.tests.test_bounds_literal",
    ),
    (
        "studio/selfrag/registry.py",
        "STALE_AFTER_DAYS = 90",
        "STALE_AFTER_DAYS = 1",
        "строже: вчерашняя карточка объявлена протухшей",
        "studio.selfrag.tests.test_bounds_literal",
    ),
    # === ПОИСК НОВЫХ МОДЕЛЕЙ (scripts/discover_models.py) =================
    (
        "scripts/discover_models.py",
        "DISTINCT_UPLOADERS = 2",
        "DISTINCT_UPLOADERS = 1",
        "поиск моделей: одного загрузчика хватает, чтобы счесть модель живой",
        "studio.mcp.tests.test_discover_models",
    ),
    # === ЦИКЛ ПО КАДРАМ (lipsync/fork_looper.py) ==========================
    (
        "lipsync/fork_looper.py",
        "MIN_POSE_COVERAGE = 0.8",
        "MIN_POSE_COVERAGE = 0.0",
        "кадры: покрытие позы перестало требоваться",
        "lipsync.tests.test_fork_looper",
    ),
    # === ПЕРЕПИСЫВАТЕЛЬ ЗАПРОСА (studio/selfrag/rewriter.py) ==============
    (
        "studio/selfrag/rewriter.py",
        "MAX_ROUNDS = 2",
        "MAX_ROUNDS = 99",
        "переписывание: кругов столько, сколько захочется",
        "studio.selfrag.tests.test_rewriter",
    ),
    (
        "studio/selfrag/rewriter.py",
        "MIN_INTENT_CONTENT_WORDS = 2",
        "MIN_INTENT_CONTENT_WORDS = 0",
        "переписывание: намерение из нуля слов считается намерением",
        "studio.selfrag.tests.test_rewriter",
    ),
    (
        "studio/selfrag/rewriter.py",
        "GIBBERISH_SHARE = 0.50",
        "GIBBERISH_SHARE = 1.1",
        "переписывание: набор букв больше не опознаётся (Р1)",
        "studio.selfrag.tests.test_rewriter",
    ),
    (
        "studio/selfrag/rewriter.py",
        "CUE_SHARE = 0.30",
        "CUE_SHARE = 0.0",
        "переписывание: любая строка объявлена подсказкой",
        "studio.selfrag.tests.test_rewriter",
    ),
    # === ОЦЕНЩИК КАЧЕСТВА СБОРА (scripts/check_harvest_quality.py) ========
    # Пороги прибора, который судит ДРУГОЙ прибор: ошибка здесь бесшумна
    # вдвойне, потому что оба выглядят зелёными.
    (
        "scripts/check_harvest_quality.py",
        "ПОТОЛОК_ЛОЖНЫХ_РУЧНЫХ = 0",
        "ПОТОЛОК_ЛОЖНЫХ_РУЧНЫХ = 99",
        "оценщик сбора: ручной разбор можно браковать сколько угодно",
        "studio.mcp.tests.test_harvest_quality",
    ),
    (
        "scripts/check_harvest_quality.py",
        "ПОЛ_ОСУЖДЕНИЯ = 0.80",
        "ПОЛ_ОСУЖДЕНИЯ = 0.0",
        "оценщик сбора: пол осуждения перестал что-либо требовать",
        "studio.mcp.tests.test_harvest_quality",
    ),
    # === ОЦЕНКА ОТВЕТА (studio/selfrag/reflect.py) ========================
    (
        "studio/selfrag/reflect.py",
        "MAX_ACTIONS = 2",
        "MAX_ACTIONS = 99",
        "оценка: список правок разрастается вместо двух главных",
        "studio.selfrag.tests.test_slot_and_actions",
    ),
    (
        "studio/selfrag/reflect.py",
        "MAX_ACTIONS = 2",
        "MAX_ACTIONS = 0",
        "строже: правки не показываются вовсе",
        "studio.selfrag.tests.test_slot_and_actions",
    ),
    # === ФОРМА ЗАПРОСА (studio/selfrag/spec.py) ===========================
    (
        "studio/selfrag/spec.py",
        "SLOT_MAX = 120",
        "SLOT_MAX = 100000",
        "запрос: в слот влезает целая страница",
        "studio.selfrag.tests.test_slot_and_actions",
    ),
    (
        "studio/selfrag/spec.py",
        "SLOT_MAX = 120",
        "SLOT_MAX = 5",
        "строже: обычная фраза в слот больше не влезает",
        "studio.selfrag.tests.test_retrieval_spec",
    ),
    (
        "studio/selfrag/spec.py",
        "REFERENCE_MODES: frozenset[str] = frozenset({MODE_I2V, MODE_EDIT})",
        "REFERENCE_MODES: frozenset[str] = frozenset({MODE_I2V})",
        "запрос: правка кадра перестала быть режимом с референсом",
        "studio.selfrag.tests.test_retrieval_spec",
    ),
    # === ПРОМТ СТИЛЯ (lipsync/fork_style_prompt.py) =======================
    (
        "lipsync/fork_style_prompt.py",
        "WORDS_MIN = 9",
        "WORDS_MIN = 0",
        "промт стиля: пустой промт снова годится",
        "lipsync.tests.test_fork_style_prompt",
    ),
    (
        "lipsync/fork_style_prompt.py",
        "WORDS_MAX = 67",
        "WORDS_MAX = 6700",
        "промт стиля: простыня принимается как промт",
        "lipsync.tests.test_fork_style_prompt",
    ),
    (
        "lipsync/fork_style_prompt.py",
        "CLAUSES_MAX = 13",
        "CLAUSES_MAX = 1",
        "строже: обычный промт объявлен слишком сложным",
        "lipsync.tests.test_fork_style_prompt",
    ),
    # === КАНАЛ HUGGINGFACE (scripts/ingest_hf.py) =========================
    # 25 констант-решений — больше, чем у любого модуля репозитория. Решают,
    # что из обсуждений практиков вообще станет фактом.
    (
        "scripts/ingest_hf.py",
        "МИН_ДЛИНА_НАБЛЮДЕНИЯ = 40",
        "МИН_ДЛИНА_НАБЛЮДЕНИЯ = 0",
        "hf: реплика в два слова снова становится наблюдением",
        "studio.mcp.tests.test_ingest_hf",
    ),
    (
        "scripts/ingest_hf.py",
        "МИН_ДЛИНА_НАБЛЮДЕНИЯ = 40",
        "МИН_ДЛИНА_НАБЛЮДЕНИЯ = 400",
        "строже: осмысленный отчёт практика объявлен слишком коротким",
        "studio.mcp.tests.test_ingest_hf",
    ),
    (
        "scripts/ingest_hf.py",
        "LICENCE_MIN_CHARS = 400",
        "LICENCE_MIN_CHARS = 0",
        "hf: обрывок вместо текста лицензии считается лицензией",
        "studio.mcp.tests.test_ingest_hf",
    ),
    (
        "scripts/ingest_hf.py",
        "FOREIGN_TEXT_SHARE = 0.2",
        "FOREIGN_TEXT_SHARE = 1.1",
        "hf: разбор перестал отказываться от чужого языка (Р1)",
        "studio.mcp.tests.test_ingest_hf",
    ),
    (
        "scripts/ingest_hf.py",
        "ДОСЛОВНО_СЛОВ = 15",
        "ДОСЛОВНО_СЛОВ = 1",
        "hf: цитата практика сворачивается до одного слова",
        "studio.mcp.tests.test_ingest_hf",
    ),
    # === КАТАЛОГ ПЛОЩАДОК (studio/mcp/catalog.py) =========================
    (
        "studio/mcp/catalog.py",
        "FOREVER_YEAR = 2090",
        "FOREVER_YEAR = 2026",
        "каталог: «снята навсегда» стало значить «снята в этом году»",
        "studio.mcp.tests.test_catalog",
    ),
    (
        "studio/mcp/catalog.py",
        'GENERATOR_TYPES = frozenset({"text-to-video", "image-to-video", "text-to-image"})',
        'GENERATOR_TYPES = frozenset({"text-to-video"})',
        "каталог: две трети генераторов перестали быть генераторами",
        "studio.mcp.tests.test_catalog_types",
    ),
    # === СЛОВАРЬ СТИЛЯ (studio/style.py) ==================================
    # Границы того, что продукт вообще принимает от заказчика.
    (
        "studio/style.py",
        "PALETTE_MAX = 4",
        "PALETTE_MAX = 99",
        "стиль: палитра из девяноста слов принимается как палитра",
        "studio.tests.test_style",
    ),
    (
        "studio/style.py",
        "PALETTE_MIN = 1",
        "PALETTE_MIN = 3",
        "строже: одно слово палитры перестало быть палитрой",
        "studio.tests.test_style",
    ),
    (
        "studio/style.py",
        "TEXT_MAX = 2000",
        "TEXT_MAX = 20",
        "строже: обычный бриф объявлен слишком длинным",
        "studio.tests.test_style",
    ),
    # === СЕМЬИ ВОПРОСОВ, ЗАВЕДЁННЫЕ ПО ЗАМЕРУ НЕДОСТИЖИМОСТИ (R3) =========
    (
        "studio/selfrag/attrfamily.py",
        '        "кроме": ("product_identity",),',
        "",
        "R3: бренд площадки снова отвечает на вопрос о лице",
        "studio.mcp.tests.test_attrfamily",
    ),
    (
        "studio/selfrag/attrfamily.py",
        '        "exact": ("benchmark_score",),',
        '        "подстроки": ("benchmark",),\n        "exact": (),',
        "R3: насыщение бенчмарка выдаётся за оценку",
        "studio.mcp.tests.test_attrfamily",
    ),
    (
        "studio/selfrag/attrfamily.py",
        '        "подстроки": ("avail", "status", "end_of_life", "lifecycle", "deprecat"),',
        '        "подстроки": ("avail",),',
        "R3: «снята ли модель» снова спрашивается одним именем из пяти",
        "studio.mcp.tests.test_attrfamily",
    ),
    (
        "studio/selfrag/attrfamily.py",
        '        "подстроки": ("vram", "runs_on", "parameter_count"),',
        '        "подстроки": ("vram",),',
        "R3: вопрос о железе перестал доставать половину ответов",
        "studio.mcp.tests.test_attrfamily",
    ),
    (
        "scripts/check_reachability.py",
        "ПОТОЛОК_ДОЛИ = 0.0",
        "ПОТОЛОК_ДОЛИ = 1.0",
        "R3: потолок недостижимости перестал что-либо запрещать",
        "studio.mcp.tests.test_reachability",
    ),
    # === КАЧЕСТВО СБОРА (studio/harvest_quality.py) ========================
    # Двадцать две константы-решения — больше, чем у любого другого модуля
    # продукта. Они решают, попадёт ли строка практика в базу вообще: ошибка
    # здесь не видна ни в одном исходе, потому что отброшенного никто не
    # считает. Мутируются пороги в ОБЕ стороны и по одному признаку формы.
    (
        "studio/harvest_quality.py",
        "МИН_ЗНАКОВ = 24",
        "МИН_ЗНАКОВ = 0",
        "сбор: строка в два знака снова считается утверждением",
        "studio.mcp.tests.test_harvest_quality",
    ),
    (
        "studio/harvest_quality.py",
        "МИН_ЗНАКОВ = 24",
        "МИН_ЗНАКОВ = 300",
        "строже: связный разбор практика объявлен слишком коротким",
        "studio.mcp.tests.test_harvest_quality",
    ),
    (
        "studio/harvest_quality.py",
        "ДОЛЯ_ЗАПЯТЫХ = 0.30",
        "ДОЛЯ_ЗАПЯТЫХ = 1.0",
        "сбор: промпт-салат из запятых снова считается утверждением",
        "studio.mcp.tests.test_harvest_quality",
    ),
    (
        "studio/harvest_quality.py",
        "ДОЛЯ_ЗАПЯТЫХ = 0.30",
        "ДОЛЯ_ЗАПЯТЫХ = 0.05",
        "строже: обычная фраза с запятой объявлена перечислением",
        "studio.mcp.tests.test_harvest_quality",
    ),
    (
        "studio/harvest_quality.py",
        "ДОЛЯ_ЧУЖИХ_БУКВ = 0.5",
        "ДОЛЯ_ЧУЖИХ_БУКВ = 1.1",
        "сбор: прибор больше не отказывается судить чужой язык (Р1)",
        "studio.mcp.tests.test_harvest_quality",
    ),
    (
        "studio/harvest_quality.py",
        "ПОТОЛОК_ЗАГОЛОВКА = 100",
        "ПОТОЛОК_ЗАГОЛОВКА = 10000",
        "сбор: связный разбор судится как заголовок",
        "studio.mcp.tests.test_harvest_quality",
    ),
    (
        "studio/harvest_quality.py",
        "СЛОВ_В_ЗАГОЛОВКЕ = 4",
        "СЛОВ_В_ЗАГОЛОВКЕ = 1",
        "сбор: имя модели с заглавной объявлено титульным регистром",
        "studio.mcp.tests.test_harvest_quality",
    ),
    (
        "studio/harvest_quality.py",
        "ДОЛЯ_ЗАГЛАВНЫХ = 0.5",
        "ДОЛЯ_ЗАГЛАВНЫХ = 0.0",
        "сбор: любая строка объявлена титульным регистром",
        "studio.mcp.tests.test_harvest_quality",
    ),
    # === РАЗБОР КРЕАТИВА (studio/mcp/creative.py) ==========================
    # Пороги, по которым кадр заказчика описывается словами. Ошибка здесь не
    # видна числом: продукт уверенно скажет «высокий ключ» о тёмном кадре.
    (
        "studio/mcp/creative.py",
        "HIGH_KEY_MEAN = 170.0",
        "HIGH_KEY_MEAN = 0.0",
        "креатив: любой кадр объявлен светлым",
        "studio.mcp.tests.test_creative",
    ),
    (
        "studio/mcp/creative.py",
        "LOW_KEY_MEAN = 85.0",
        "LOW_KEY_MEAN = 255.0",
        "креатив: любой кадр объявлен тёмным",
        "studio.mcp.tests.test_creative",
    ),
    (
        "studio/mcp/creative.py",
        "MUTED_CHROMA = 40.0",
        "MUTED_CHROMA = 255.0",
        "креатив: любая палитра объявлена приглушённой",
        "studio.mcp.tests.test_creative",
    ),
    (
        "studio/mcp/creative.py",
        "SATURATED_CHROMA = 120.0",
        "SATURATED_CHROMA = 0.0",
        "креатив: любая палитра объявлена насыщенной",
        "studio.mcp.tests.test_creative",
    ),
    (
        "studio/mcp/creative.py",
        "DOMINANT_COLOURS = 3",
        "DOMINANT_COLOURS = 1",
        "строже: палитра сворачивается до одного слова",
        "studio.mcp.tests.test_creative",
    ),
    # === ЗАЯВКА НА ДЕНЬГИ ВЛАДЕЛЬЦА (studio/mcp/proposal.py) ==============
    # Взят первым из очереди R7 не по числу констант, а по цене ошибки: это
    # единственный модуль, через который продукт просит ДЕНЬГИ. Порог, ниже
    # которого заявка считается пустой, и список состояний решают, что
    # владельцу вообще покажут.
    (
        "studio/mcp/proposal.py",
        "MIN_TEST_CHARS = 60",
        "MIN_TEST_CHARS = 0",
        "заявка: однострочное «попробуйте kling и посмотрите» снова проходит",
        "studio.mcp.tests.test_proposal",
    ),
    (
        "studio/mcp/proposal.py",
        "MIN_TEST_CHARS = 60",
        "MIN_TEST_CHARS = 600",
        "строже: осмысленное описание замера объявлено пустым",
        "studio.mcp.tests.test_proposal",
    ),
    (
        "studio/mcp/proposal.py",
        "MIN_BASIS_CHARS = 12",
        "MIN_BASIS_CHARS = 0",
        "заявка: откуда взята цена, можно не объяснять",
        "studio.mcp.tests.test_proposal",
    ),
    (
        "studio/mcp/proposal.py",
        "MIN_DECIDES_CHARS = 20",
        "MIN_DECIDES_CHARS = 0",
        "заявка: что решит результат, можно не писать",
        "studio.mcp.tests.test_proposal",
    ),
    (
        "studio/mcp/proposal.py",
        "MIN_TASK_CHARS = 8",
        "MIN_TASK_CHARS = 0",
        "заявка: задача может быть не названа вовсе",
        "studio.mcp.tests.test_proposal",
    ),
    (
        "studio/mcp/proposal.py",
        "DECISIONS: tuple[str, ...] = (STATE_APPROVED, STATE_DECLINED)",
        "DECISIONS: tuple[str, ...] = (STATE_APPROVED,)",
        "заявка: отказ владельца перестал быть решением",
        "studio.mcp.tests.test_proposal",
    ),
    (
        "scripts/check_mutants_cover.py",
        "            if из_гита is not None and имя not in из_гита:",
        "            if False:",
        "R7: знаменатель снова считается по рабочему дереву, а не по репозиторию",
        "studio.mcp.tests.test_mutants_cover",
    ),
    (
        "scripts/check_mutants_cover.py",
        "        if isinstance(место, (ast.If, ast.While, ast.IfExp)):",
        "        if False:",
        "R7: ветвление перестало делать константу решающей — долг занижен",
        "studio.mcp.tests.test_mutants_cover",
    ),
    (
        "scripts/check_mutants_cover.py",
        '    if итог["violations"] > ПОТОЛОК:',
        "    if False:",
        "R7: потолок перестал ловить рост долга",
        "studio.mcp.tests.test_mutants_cover",
    ),
    (
        "scripts/check_mutants_cover.py",
        '    if итог["violations"] < ПОТОЛОК:',
        "    if False:",
        "R7: упавший долг больше не требует опустить потолок",
        "studio.mcp.tests.test_mutants_cover",
    ),
    (
        "scripts/run_tests.py",
        "        raise AssertionError(ОТКАЗ)\n\n    def connect_ex",
        "        return None\n\n    def connect_ex",
        "R8: соединение снова разрешено, запрет держится на бумаге",
        "studio.mcp.tests.test_runner",
    ),
    (
        "scripts/run_tests.py",
        "    if not сеть_закрыта():",
        "    if False:",
        "R8: негативный контроль запрета выключен",
        "studio.mcp.tests.test_runner",
    ),
    (
        "scripts/check_golden.py",
        '    "search_web": "сеть по определению",\n',
        "",
        "R2: инструмент выпал из-под присмотра и никто не заметил",
        "studio.mcp.tests.test_golden",
    ),
    (
        "scripts/check_golden.py",
        "        if (провалы or пустые or без_присмотра)",
        "        if (провалы or пустые)",
        "R2: инструмент без присмотра перестал красить исход",
        "studio.mcp.tests.test_golden",
    ),
    (
        "studio/pipeline.py",
        "MIN_FACTS_PER_MODEL = 1",
        "MIN_FACTS_PER_MODEL = 0",
        "слабее: шаг опирается на модель, о которой база молчит",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        "MIN_FACTS_PER_MODEL = 1",
        "MIN_FACTS_PER_MODEL = 2",
        "строже: одного утверждения о модели уже мало",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        'AMBIENT_ARTEFACTS: frozenset[str] = frozenset({"бриф", "селфи", "референс"})',
        'AMBIENT_ARTEFACTS: frozenset[str] = frozenset({"бриф", "референс"})',
        "строже: селфи клиента перестало приходить снаружи",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        "PRODUCES_LOOKBACK = 0",
        "PRODUCES_LOOKBACK = 1",
        "строже: шаг 3 больше не видит кадр от шага 1",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        'LICENCE_MARKERS: tuple[str, ...] = ("license", "licence", "лиценз")',
        'LICENCE_MARKERS: tuple[str, ...] = ("license", "licence")',
        "слабее: русское имя атрибута лицензии не опознаётся",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        '    "non-commercial",\n    "noncommercial",',
        '    "noncommercial",',
        "слабее: `non-commercial` больше не запрещает коммерцию",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        '    "paid subscription",',
        '    "не-встречается-нигде",',
        "условный запрет снова сворачивается в «не годно» (Р1)",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        '    "paid plan",\n    "paid user",',
        '    "paid plan",\n    "paid user",\n    "commercial",',
        "шире: любой запрет объявлен условным",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        '    "research purposes",',
        '    "commercial",',
        "шире: разрешительная лицензия читается как запрет",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        'PRICE_MARKERS: tuple[str, ...] = ("price", "cost", "цена", "стоимост")',
        'PRICE_MARKERS: tuple[str, ...] = ("price", "cost")',
        "слабее: русская ценовая строка перестала быть ценовой",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        "BUDGET_TOLERANCE = 0.0",
        "BUDGET_TOLERANCE = 0.25",
        "слабее: превышение бюджета на четверть считается попаданием",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        "BUDGET_TOLERANCE = 0.0",
        "BUDGET_TOLERANCE = -0.25",
        "строже: попадание в бюджет впритык считается промахом",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        'BUDGET_UNIT = "usd"',
        'BUDGET_UNIT = "credits"',
        "бюджет человека сравнивается с кредитами вендора",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        "STALE_AFTER_DAYS = 180",
        "STALE_AFTER_DAYS = 36500",
        "слабее: столетнее утверждение считается свежим",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        "STALE_AFTER_DAYS = 180",
        "STALE_AFTER_DAYS = 1",
        "строже: вчерашнее утверждение считается протухшим",
        "studio.mcp.tests.test_pipeline",
    ),
    # Мутант «слово deprecated больше не значит снята» УДАЛЁН 2026-09-05 вместе
    # с константой `DEPRECATION_MARKERS`: он искал строку списка, по которому
    # больше ничего не решается, и молчал не потому, что охрана слаба, а потому
    # что искал несуществующее. На его место — мутация настоящей развилки:
    # снятие без названного срока обязано оставаться отказом.
    (
        "studio/pipeline.py",
        "            if снятие.когда:",
        "            if not снятие.когда:",
        "слабее: снятие без срока перестало быть отказом",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        '        "max_seconds",\n        "max_duration_seconds",',
        '        "max_duration_seconds",',
        "слабее: расхождение по `max_seconds` перестало быть противоречием",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        "        if v not in длинное:\n            return True\n    return False",
        "        if v != длинное:\n            return True\n    return False",
        "спор снова объявляется по многословности, а не по существу",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        "    живые = sorted({v for v in значения if v})\n    if len(живые) < 2:\n        return False",
        "    живые = sorted({v for v in значения if v})\n    if len(живые) < 99:\n        return False",
        "шире: спора не бывает вовсе",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        "    CLASS_NO_MODEL: UNMEASURED,",
        "    CLASS_NO_MODEL: FAIL,",
        "незнание базы выдаётся за свидетельство против модели (Р1)",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        "    CLASS_CONTRADICTION: UNMEASURED,",
        "    CLASS_CONTRADICTION: FAIL,",
        "противоречие источников решается за человека (Р1)",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/pipeline.py",
        "    CLASS_GAP: FAIL,",
        "    CLASS_GAP: UNMEASURED,",
        "разрыв в плане сворачивается в «не смогли» (Р1)",
        "studio.mcp.tests.test_pipeline",
    ),
    (
        "studio/factaxis.py",
        "APPLICABILITY: tuple[str, ...] = (KIND_MEASUREMENT, KIND_WITNESS)",
        "APPLICABILITY: tuple[str, ...] = (KIND_WITNESS,)",
        "измерение перестало быть применимостью",
        "studio.mcp.tests.test_factaxis",
    ),
    (
        "studio/factaxis.py",
        "CAPABILITY: tuple[str, ...] = (KIND_SCHEMA, KIND_CLAIM)",
        "CAPABILITY: tuple[str, ...] = (KIND_SCHEMA, KIND_CLAIM, KIND_MEASUREMENT)",
        "измерение засчитано и в способность — колонки слиплись",
        "studio.mcp.tests.test_factaxis",
    ),
    (
        "studio/factaxis.py",
        "WITNESS_TIERS: frozenset[str] = frozenset({TIER_PROBE, TIER_OPERATOR})",
        "WITNESS_TIERS: frozenset[str] = frozenset({TIER_PROBE})",
        "строже: владелец запустил и увидел — уже не свидетельство",
        "studio.mcp.tests.test_factaxis",
    ),
    (
        "studio/factaxis.py",
        "MEASUREMENT_TIERS: frozenset[str] = frozenset({TIER_PAPER, TIER_BENCHMARK})",
        'MEASUREMENT_TIERS: frozenset[str] = frozenset({TIER_PAPER, TIER_BENCHMARK, "vendor"})',
        "слабее: вендорская проза о качестве считается измерением",
        "studio.mcp.tests.test_factaxis",
    ),
    (
        "studio/factaxis.py",
        '        "metric_blind_spot",\n        "artifact_taxonomy",\n    }\n)',
        '        "artifact_taxonomy",\n    }\n)',
        "оговорка о метрике перестала идти против шага",
        "studio.mcp.tests.test_factaxis",
    ),
    (
        "studio/selfrag/modelnames.py",
        '    "infinitalk": "infinitetalk",',
        "",
        "таблица имён: площадка и репозиторий снова разъехались",
        "studio.selfrag.tests.test_modelnames",
    ),
    (
        "studio/selfrag/modelnames.py",
        '    "fluxkontextdev": "flux1kontextdev",',
        '    "fluxkontextdev": "flux1dev",',
        "таблица имён: правка кадра склеена с базовой моделью",
        "studio.selfrag.tests.test_modelnames",
    ),
    (
        "studio/selfrag/modelnames.py",
        '    "bytedanceomnihuman": "omnihuman1",',
        "",
        "таблица имён: лаборатория впереди снова делает другую модель",
        "studio.selfrag.tests.test_modelnames",
    ),
    (
        "studio/selfrag/modelnames.py",
        '    "bytedanceomnihuman15": "omnihuman15",',
        '    "bytedanceomnihuman15": "omnihuman1",',
        "версии склеены между собой: 1.5 объявлена первой",
        "studio.selfrag.tests.test_modelnames",
    ),
    (
        "studio/selfrag/modelnames.py",
        '    "infinitalk": "infinitetalk",',
        '    "infinitalk": "infinitetalk",\n    "multitalk": "infinitetalk",',
        "шире: соседняя модель приписана к чужим наблюдениям",
        "studio.selfrag.tests.test_modelnames",
    ),
    (
        "studio/factaxis.py",
        "RELEVANCE_FLOOR = SCORE_FLOOR",
        "RELEVANCE_FLOOR = 0.0",
        "слабее: к требованию относится любая строка",
        "studio.mcp.tests.test_factaxis",
    ),
    (
        "studio/factaxis.py",
        "RELEVANCE_FLOOR = SCORE_FLOOR",
        "RELEVANCE_FLOOR = 0.9",
        "строже: к требованию не относится почти ничто",
        "studio.mcp.tests.test_factaxis",
    ),
]

#: Файл-замок. Два мутационных прогона в одном дереве подменяют исходники друг
#: другу, и вердикт становится случайным в ОБЕ стороны: прибор может покраснеть
#: на здоровом коде и — что хуже — ПОЗЕЛЕНЕТЬ на мутанте, если тесты успели
#: прочитать файл до подмены. ИЗМЕРЕНО 2026-09-04: 2 прогона из 5 красные,
#: каждый раз с другими тестами, все они поодиночке зелёные, `git status` чист.
ЗАМОК = ROOT / ".mutate.lock"


#: Куда кладётся ЦЕЛЫЙ исходник перед подменой. Не дифф и не строка — файл:
#: восстановление обязано работать, когда о прогоне не осталось ничего, кроме
#: этого каталога.
#:
#: ЗАЧЕМ, ЕСЛИ ВОЗВРАТ И ТАК СТОИТ В `finally`. ИЗМЕРЕНО 2026-09-04: рабочий
#: процесс сессии был убит сигналом посреди прогона, `finally` не исполнился, и
#: в дереве осталась подмена `цели_открыты = []` в `scripts/check_golden.py` —
#: то есть ПРИБОР, считающий регрессы голден-сета, молча перестал их считать.
#: Заметил это `git diff`, а не гейт: гейт был зелёным на изувеченном приборе.
#: `finally` защищает от исключения, но не от `SIGKILL`; файл-копия защищает от
#: обоих, потому что переживает смерть процесса.
СЛЕПОК = ROOT / ".mutate.backup"


def _слепок_для(файл: str) -> Path:
    """Имя слепка — ЗАКОДИРОВАННЫЙ путь, а не путь с заменёнными косыми.

    Первая редакция меняла `/` на `__` и обратно. Она разъезжается на любом
    пути, где `__` уже есть (`__init__.py`, и на нём же тест это и поймал):
    обратная замена превращала имя в чужой путь, и возврат писал бы файл НЕ
    ТУДА. Прибор, который в аварии портит соседний файл, хуже отсутствующего.
    """
    return СЛЕПОК / quote(файл, safe="")


def отложить(файл: str, текст: str) -> None:
    СЛЕПОК.mkdir(exist_ok=True)
    _слепок_для(файл).write_text(текст, encoding="utf-8")


def забыть(файл: str) -> None:
    _слепок_для(файл).unlink(missing_ok=True)
    if СЛЕПОК.exists() and not any(СЛЕПОК.iterdir()):
        СЛЕПОК.rmdir()


def вернуть_недовосстановленное() -> list[str]:
    """Слепки, оставшиеся от оборванного прогона: вернуть и назвать.

    Молча восстановить — почти так же плохо, как не восстановить: следующий
    читатель не узнает, что дерево побывало изувеченным. Возвращается список
    имён, и он печатается.
    """
    if not СЛЕПОК.exists():
        return []
    вернули: list[str] = []
    for слепок in sorted(СЛЕПОК.iterdir()):
        файл = unquote(слепок.name)
        (ROOT / файл).write_text(слепок.read_text(encoding="utf-8"), encoding="utf-8")
        слепок.unlink()
        вернули.append(файл)
    if not any(СЛЕПОК.iterdir()):
        СЛЕПОК.rmdir()
    return вернули


def _занято() -> str:
    """Кто ещё мутирует это дерево. Пустая строка — никто.

    ЗАМОК ОТ ЖИВОГО ПРОГОНА, А НЕ ОТ ПОКОЙНИКА. Оборванный прогон оставлял
    замок навсегда, и следующий запуск отказывался работать, пока человек не
    снимет файл руками. Теперь записан pid, и мёртвый pid замком не считается.
    """
    if not ЗАМОК.exists():
        return ""
    запись = ЗАМОК.read_text(encoding="utf-8").strip()
    номер = "".join(з for з in запись if з.isdigit())
    if номер:
        try:
            os.kill(int(номер), 0)
        except OSError:
            ЗАМОК.unlink(missing_ok=True)
            return ""
    return запись or "неизвестный прогон"


def clean() -> None:
    for d in ROOT.rglob("__pycache__"):
        shutil.rmtree(d, ignore_errors=True)


def run(тесты: str) -> tuple[int, str]:
    p = subprocess.run(
        [sys.executable, "-m", "unittest", тесты], cwd=ROOT, capture_output=True, text=True
    )
    хвост = (p.stdout + p.stderr).strip().splitlines()
    return p.returncode, (хвост[-1] if хвост else "")


def main() -> int:
    если_занято = _занято()
    if если_занято:
        print(f"ОТКАЗ: дерево уже мутирует {если_занято}. Два прогона портят друг другу исходники.")
        print(f"Если прогон оборвался, снимите замок: rm {ЗАМОК}")
        return 2
    вернули = вернуть_недовосстановленное()
    for файл in вернули:
        print(f"ВОССТАНОВЛЕНО из слепка оборванного прогона: {файл}")
    ЗАМОК.write_text(f"pid {os.getpid()}", encoding="utf-8")
    try:
        return _прогон()
    finally:
        ЗАМОК.unlink(missing_ok=True)


def _прогон() -> int:
    clean()
    наборы = sorted({м[4] for м in MUTANTS})
    здоровые = {н: run(н) for н in наборы}
    больные = [f"{н}: {к}" for н, (к, _) in здоровые.items() if к != 0]
    print(
        "ЗДОРОВЫЙ | наборов "
        + str(len(наборы))
        + (" — все зелёные" if not больные else f" — КРАСНЫЕ: {больные}")
    )
    if больные:
        print("Таблица мутаций поверх красного дерева не значит ничего. Прогон остановлен.")
        return 1

    print()
    print(f"{'мутация':64} | тесты | покраснело")
    print("-" * 92)
    молчали: list[str] = []
    for файл, старое, новое, подпись, тесты in MUTANTS:
        путь = ROOT / файл
        было = путь.read_text(encoding="utf-8")
        if старое not in было:
            print(f"{подпись:64} | НЕ НАЙДЕНО в {файл}")
            молчали.append(f"{подпись} (строка не найдена — правило переписали?)")
            continue
        отложить(файл, было)
        путь.write_text(было.replace(старое, новое, 1), encoding="utf-8")
        clean()
        try:
            код, _ = run(тесты)
        finally:
            # ВОЗВРАТ В `finally`, А НЕ ПРЯМОЙ СТРОКОЙ. Скрипт правит ИСХОДНИКИ
            # В РАБОЧЕМ ДЕРЕВЕ, и прерывание оставляло мутацию в файле
            # НАСОВСЕМ. ИЗМЕРЕНО 2026-09-04: в дереве нашлась подмена из
            # оборванного прогона, и заметил её `git status`, а не гейт.
            путь.write_text(было, encoding="utf-8")
            забыть(файл)
            clean()
        print(f"{подпись:64} | rc={код}  | {'тесты' if код else 'НИКТО — константу не сторожат'}")
        if код == 0:
            молчали.append(подпись)

    print()
    print(f"мутантов {len(MUTANTS)}, промолчали на {len(молчали)}")
    for m in молчали:
        print(f"  ПРОМОЛЧАЛИ: {m}")
    return 1 if молчали else 0


if __name__ == "__main__":
    raise SystemExit(main())
