#!/usr/bin/env python3
"""Гейт планировщика: план из брифа, и негативный контроль в обе стороны.

    python scripts/check_planner.py --check
    python scripts/check_planner.py --brief "оживить фото клиента, он говорит мою озвучку"

ЧТО ЗДЕСЬ СТОРОЖИТСЯ, И ПОЧЕМУ ИМЕННО ЭТО

1. ВОСЕМЬ НАСТОЯЩИХ БРИФОВ (`studio/fixtures/planner_briefs.jsonl`). У каждого
   выписан ожидаемый состав шагов, исход и КОД ПРИЧИНЫ. Сравнивается кортеж
   шагов целиком, а не вхождение: прибор, собирающий «что-нибудь похожее»,
   читается как работающий и не работает.

2. НЕГАТИВНЫЙ КОНТРОЛЬ В ОБЕ СТОРОНЫ (И5). Вход, где прибор обязан МОЛЧАТЬ:
   «сделай красиво» и бриф про промышленный манипулятор — ни одного шага, и
   исход третий. Вход, где обязан ШЕВЕЛЬНУТЬСЯ: шесть брифов со шагами. Без
   первой половины прибор, выдающий план на что угодно, прошёл бы приёмку; без
   второй — прибор, молчащий всегда.

3. ТРЕТИЙ ИСХОД ОТДЕЛЬНО ОТ ПУСТОГО ПЛАНА (Р1). `фоли-к-оживлению` обязан дать
   «не смогли» с НЕПУСТЫМ планом: операция словарю известна, база о ней молчит.
   Свернуть это в «шагов нет» значило бы потерять ровно то, что человек должен
   увидеть — какой шаг некем закрыть.

4. МОДЕЛЬ БЕЗ ДОКАЗАТЕЛЬСТВА ТОЛЬКО С ПОМЕТКОЙ. У каждого выбранного кандидата
   обязаны стоять строки доказательства, и если среди них нет ни одной строки
   ПРИМЕНИМОСТИ, пометка `planner.NOT_MEASURED_MARK` обязана стоять в выдаче.
   Проверяется на всех кандидатах всех брифов разом, числом.

5. ЗНАМЕНАТЕЛЬ. Строк в файле контроля и разобранных строк — два числа рядом:
   молча пропавший контроль не должен читаться как зелёный прогон.

Сети здесь нет (Т4): читается только `studio/knowledge/model_facts.jsonl`.
"""

from __future__ import annotations

import argparse
import json
import sys
from types import SimpleNamespace
from typing import cast
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import UNMEASURED  # noqa: E402

from studio import planner as pn  # noqa: E402
from studio.factindex import FactIndex  # noqa: E402

#: Дата, на которую судится свежесть фактов. ВЫБРАНО фиксированной: гейт,
#: зависящий от `date.today()`, краснеет однажды сам по себе, и разбирать это
#: будет тот, кто ничего не менял.
TODAY = "2026-09-02"


def run(path: Path = pn.DEFAULT_BRIEFS_PATH) -> dict:
    """Прогон всего набора. Возвращает числа, а не булев флаг (Е3)."""
    from datetime import date

    сегодня = date.fromisoformat(TODAY)
    индекс = FactIndex()
    разметка = None
    набор = pn.briefs(path)
    случаи = []
    for row in набор:
        начало = time.perf_counter()
        итог = pn.plan(
            str(row["brief"]),
            creative=str(row.get("creative") or ""),
            budget_usd=row.get("budget_usd"),
            today=сегодня,
            overrides=разметка,
            index=индекс,
        )
        шаги = tuple(s["step"] for s in итог["steps"])
        ждали = tuple(str(x) for x in (row.get("expect_steps") or ()))
        беды = []
        if шаги != ждали:
            беды.append(f"шаги {list(шаги)}, ждали {list(ждали)}")
        if итог["outcome"] != row["expect_outcome"]:
            беды.append(f"исход {итог['outcome']}, ждали {row['expect_outcome']}")
        if итог["reason"] != row["expect_reason"]:
            беды.append(f"причина {итог['reason']}, ждали {row['expect_reason']}")
        # Вхождение, а не равенство: база живая, и в неё дописывают. Почему
        # именно так — записано в шапке `planner_briefs.jsonl`.
        нет = [k for k in (row.get("expect_classes") or ()) if k not in итог["classes"]]
        if нет:
            беды.append(f"классы {итог['classes']} не содержат {нет}")
        # Потолок, вычитанный ИЗ БРИФА. `null` в ожидании — это тоже ожидание,
        # и оно сильнее прочих: выдуманный бюджет хуже отсутствующего.
        # Строка о проверенных кандидатах: три положения, три разных ожидания.
        # Пустое ожидание — тоже ожидание: строка там была бы шумом.
        if "expect_rival" in row:
            строки_о_проверенных = [str(s.get("proven_rival") or "") for s in итог["steps"]]
            ждали_строку = str(row["expect_rival"])
            если = {
                "вытеснен": lambda t: t.startswith(pn.RIVAL_MARK),
                "нет": lambda t: t.startswith(pn.NO_RIVAL_MARK),
                "": lambda t: t == "",
            }
            годен = если.get(ждали_строку)
            if годен is None:
                беды.append(f"expect_rival={ждали_строку!r} — такого положения нет")
            elif not any(годен(t) for t in строки_о_проверенных):
                беды.append(f"строка о проверенных: {строки_о_проверенных}, ждали {ждали_строку!r}")
        # Перевод «за что»: посчитанное нами число обязано называться
        # посчитанным нами, и ожидание на это есть отдельное.
        if "expect_converted" in row:
            переведено = [
                str((s.get("chosen") or {}).get("price_note") or "")
                for s in итог["steps"]
                if s.get("chosen")
            ]
            есть = any(pn.CONVERTED_MARK in t for t in переведено)
            ждали_перевод = str(row["expect_converted"]) == "да"
            if есть != ждали_перевод:
                беды.append(
                    f"перевод «за что»: {'есть' if есть else 'нет'}, "
                    f"ждали {'есть' if ждали_перевод else 'нет'}"
                )
        # Кадр: три ожидания, и пустое — тоже ожидание (без креатива не должно
        # измениться ни строки, ни порядка).
        if "expect_fit" in row:
            состояния = [
                str((s.get("chosen") or {}).get("fit_state") or "")
                for s in итог["steps"]
                if s.get("chosen")
            ]
            отказы = [str(s.get("rejected_by_frame") or "") for s in итог["steps"]]
            ждали_кадр = str(row["expect_fit"])
            если_кадр = {
                "принимает": lambda: pn.FIT_IN in состояния,
                # «Отвергнуты» — про ОТКАЗЫ и только про них. Раньше сюда была
                # подмешана проверка, что выбранный сам влезает; после того как
                # в ключе появился выход, выбранным законно стал кандидат с
                # НЕЗАПИСАННЫМ пределом кадра, и ожидание покраснело на верном
                # поведении. Два разных вопроса в одном ожидании — дефект
                # ожидания, а не прибора.
                "отвергнуты": lambda: any(t for t in отказы),
                "": lambda: состояния == [""] * len(состояния) and not any(отказы),
            }
            годен_кадр = если_кадр.get(ждали_кадр)
            if годен_кадр is None:
                беды.append(f"expect_fit={ждали_кадр!r} — такого положения нет")
            elif not годен_кадр():
                беды.append(
                    f"кадр: состояния {состояния}, отказов {sum(1 for t in отказы if t)}, "
                    f"ждали {ждали_кадр!r}"
                )
        # Запрет на вход: сколько кандидатов отклонено. 0 — тоже ожидание.
        if "expect_banned" in row:
            отклонено = sum(int(s.get("banned_count") or 0) for s in итог["steps"])
            if отклонено != int(row["expect_banned"]):
                беды.append(f"запретом отклонено {отклонено}, ждали {row['expect_banned']}")
        # Выход шага: подтверждён ли он у выбранного, и отсекал ли кто-то.
        if "expect_output" in row:
            выходы = [
                str((s.get("chosen") or {}).get("out_state") or "")
                for s in итог["steps"]
                if s.get("chosen")
            ]
            отсечено = sum(int(s.get("wrong_output_count") or 0) for s in итог["steps"])
            ждали_выход = str(row["expect_output"])
            если_выход = {
                "подтверждён": lambda: pn.OUT_YES in выходы,
                "отсечён": lambda: отсечено > 0,
                "": lambda: pn.OUT_YES not in выходы and отсечено == 0,
            }
            годен_выход = если_выход.get(ждали_выход)
            if годен_выход is None:
                беды.append(f"expect_output={ждали_выход!r} — такого положения нет")
            elif not годен_выход():
                беды.append(
                    f"выход: состояния {выходы}, отсечено {отсечено}, ждали {ждали_выход!r}"
                )
        if "expect_budget" in row:
            снято = (итог.get("budget") or {}).get("amount")
            if снято != row["expect_budget"]:
                беды.append(f"бюджет из брифа {снято}, ждали {row['expect_budget']}")
        случаи.append(
            {
                "id": str(row["id"]),
                "outcome": итог["outcome"],
                "reason": итог["reason"],
                "steps": list(шаги),
                "faults": беды,
                "ms": round((time.perf_counter() - начало) * 1000, 1),
                "plan": итог,
            }
        )

    # Пометка на кандидате без применимости — числом по всем брифам разом.
    кандидатов = 0
    без_применимости = 0
    без_пометки = 0
    без_доказательства = 0
    for c in случаи:
        for s in c["plan"]["steps"]:
            выбран = s["chosen"]
            if выбран is None:
                continue
            кандидатов += 1
            if not выбран["evidence"]:
                без_доказательства += 1
            if выбран["applicability"] == 0:
                без_применимости += 1
                if выбран["mark"] != pn.NOT_MEASURED_MARK:
                    без_пометки += 1

    # ПОРЯДОК ПО ЦЕНЕ, проверенный на всех брифах разом. Требование прямое:
    # кандидат с незаписанной ценой не должен молча обходить того, чья цена
    # измерена и в потолок укладывается. Проверяется структурно — по рангу
    # `planner.PRICE_ORDER` у выбранного против каждого из показанных рядом.
    #
    # СРАВНИВАЕТСЯ ТОЛЬКО ПРИ РАВНЫХ СТАРШИХ КЛЮЧАХ, И ЭТО ПОЧИНКА 2026-09-03.
    # Раньше проверка смотрела на цену ОДНУ, а в ключе планировщика перед ней
    # стоят два поля: «нельзя ли этим воспользоваться» (`blocked_rank`) и
    # «принимает ли кадр». Пока фикстуры не давали шага, где старший ключ
    # различает кандидатов, дыра не проявлялась. Проявилась на дописанном шаге
    # озвучки: выбран `elevenlabs-tts-eleven-v3` с `blocked_rank == (1, -2)`
    # против `eleven_v3` с `(1, -1)` — то есть у выбранного ПОДТВЕРЖДЕНО на
    # одно препятствие больше, и он законно старше, хотя по цене младше.
    # Проверка, требующая не того порядка, что модуль, — это не проверка.
    цена_нарушена: list[str] = []
    шагов_с_потолком = 0
    почему_не_сосед = 0
    for c in случаи:
        потолок_есть = (c["plan"].get("budget") or {}).get("amount") is not None
        for s in c["plan"]["steps"]:
            выбран = s["chosen"]
            if выбран is None:
                continue
            if s.get("why_not_next"):
                почему_не_сосед += 1
            if not потолок_есть:
                continue
            шагов_с_потолком += 1
            мой = pn.PRICE_ORDER.get(выбран.get("price_state", ""), 0)
            мои_старшие = старшие_ключи(выбран)
            for a in s["alternatives"]:
                чужой = pn.PRICE_ORDER.get(a.get("price_state", ""), 0)
                if старшие_ключи(a) != мои_старшие:
                    continue
                if чужой < мой:
                    цена_нарушена.append(
                        f"{c['id']}/{s['step']}: выбран {выбран['model']} "
                        f"({выбран.get('price_state')}), а рядом {a['model']} "
                        f"({a.get('price_state')}) — по цене он старше"
                    )

    # СТРОКА О ПРОВЕРЕННЫХ, проверенная структурно на всех брифах разом.
    # Два требования, и оба в обе стороны (И5): у непроверенного выбранного
    # строка ОБЯЗАНА быть, у проверенного — обязана отсутствовать.
    вытеснен = нет_проверенных = 0
    строка_пропущена: list[str] = []
    строка_лишняя: list[str] = []
    for c in случаи:
        for s in c["plan"]["steps"]:
            выбран = s["chosen"]
            if выбран is None:
                continue
            про_проверенных = str(s.get("proven_rival") or "")
            if выбран["applicability"] == 0:
                if not про_проверенных:
                    строка_пропущена.append(f"{c['id']}/{s['step']} ({выбран['model']})")
                elif про_проверенных.startswith(pn.RIVAL_MARK):
                    вытеснен += 1
                elif про_проверенных.startswith(pn.NO_RIVAL_MARK):
                    нет_проверенных += 1
            elif про_проверенных:
                строка_лишняя.append(f"{c['id']}/{s['step']} ({выбран['model']})")

    # ПЕРЕВОД «ЗА ЧТО», числом по всем брифам разом, и негативный контроль к
    # нему: ни одно переведённое число не смеет появиться без пометки о том,
    # что его посчитали мы, и ни одна цена в кредитах не смеет быть переведена
    # в доллары (курс — решение вендора, его нигде не записано).
    переводов = 0
    перевод_без_пометки: list[str] = []
    кредиты_переведены: list[str] = []
    for c in случаи:
        for s in c["plan"]["steps"]:
            выбран = s["chosen"]
            if выбран is None:
                continue
            нота = str(выбран.get("price_note") or "")
            записано = str(выбран.get("price") or "")
            if pn.CONVERTED_MARK in нота:
                переводов += 1
            # Переведённое число всегда несёт исходную строку рядом: если в
            # ноте стоит «за second», а записана цена «за minute», пометка о
            # переводе обязана быть.
            if " за second" in нота and " за minute" in записано:
                if pn.CONVERTED_MARK not in нота:
                    перевод_без_пометки.append(f"{c['id']}/{s['step']} ({выбран['model']})")
            if "credits" in нота and pn.CONVERTED_MARK in нота:
                кредиты_переведены.append(f"{c['id']}/{s['step']} ({выбран['model']})")

    # КАДР, числом по всем брифам разом, и негативный контроль в обе стороны:
    # без креатива не должно быть НИ ОДНОГО непустого положения по кадру, а с
    # креативом отвергнутый кандидат обязан быть назван, а не тихо уехать вниз.
    кадр_измерен = 0
    кадр_принят = 0
    кадр_отверг = 0
    кадр_без_креатива: list[str] = []
    отказ_без_строки: list[str] = []
    for c in случаи:
        подан = bool((c["plan"].get("creative") or {}).get("width"))
        if подан:
            кадр_измерен += 1
        for s in c["plan"]["steps"]:
            выбран = s["chosen"]
            if выбран is None:
                continue
            по_кадру = str(выбран.get("fit_state") or "")
            if not подан:
                if по_кадру or s.get("rejected_by_frame"):
                    кадр_без_креатива.append(f"{c['id']}/{s['step']}")
                continue
            if по_кадру == pn.FIT_IN:
                кадр_принят += 1
            if по_кадру == pn.FIT_OVER and not s.get("rejected_by_frame"):
                отказ_без_строки.append(f"{c['id']}/{s['step']}")
            if s.get("rejected_by_frame"):
                кадр_отверг += 1

    # ЗАПРЕТ НА ВХОД, числом по всем брифам разом, и негативный контроль в обе
    # стороны: отклонённый обязан быть НАЗВАН (он уходит в конец порядка и
    # выпадает из показанных), а строка-запрет не смеет печататься доводом.
    запретом_отклонено = 0
    снятых = 0
    не_тот_выход = 0
    выход_подтверждён = 0
    выбран_не_тот: list[str] = []
    объявлено_снятие = 0
    выбран_снятый: list[str] = []
    шагов_с_запретом = 0
    запрет_без_строки: list[str] = []
    запрет_как_довод: list[str] = []
    выбран_запрещённый: list[str] = []
    for c in случаи:
        for s in c["plan"]["steps"]:
            выбран = s["chosen"]
            if выбран is None:
                continue
            снятых += int(s.get("retired_count") or 0)
            не_тот_выход += int(s.get("wrong_output_count") or 0)
            выход_шага = str(выбран.get("out_state") or "")
            if выход_шага == pn.OUT_YES:
                выход_подтверждён += 1
            if выход_шага == pn.OUT_NO:
                выбран_не_тот.append(f"{c['id']}/{s['step']} ({выбран['model']})")
            # Считается по ВСЕМ найденным, а не по выбранному: `sora-2` на
            # живой базе объявлен к снятию И запрещён по входу, поэтому
            # выбранным не бывает никогда — счёт по выбранному показал бы 0 и
            # соврал бы, что оракул не подключён.
            объявлено_снятие += int(s.get("announced_count") or 0)
            если_объявлено = str(выбран.get("life_state") or "")
            if если_объявлено == pn.LIFE_RETIRED:
                выбран_снятый.append(f"{c['id']}/{s['step']} ({выбран['model']})")
            сколько = (
                int(s.get("banned_count") or 0)
                + int(s.get("retired_count") or 0)
                + int(s.get("wrong_output_count") or 0)
            )
            запретом_отклонено += сколько
            if сколько:
                шагов_с_запретом += 1
                if not s.get("banned_input"):
                    запрет_без_строки.append(f"{c['id']}/{s['step']}")
            if выбран.get("ban_state") == pn.BAN_FORBIDS:
                выбран_запрещённый.append(f"{c['id']}/{s['step']} ({выбран['model']})")
            for e in выбран.get("evidence", []):
                if e.get("forbids"):
                    запрет_как_довод.append(
                        f"{c['id']}/{s['step']} ({выбран['model']}: {e['attribute']})"
                    )

    молчащие = [c for c in случаи if not c["steps"]]
    заговорившие = [c for c in случаи if c["steps"]]
    исходы = {c["outcome"] for c in случаи}
    причины = {c["reason"] for c in случаи}
    провалы = [c for c in случаи if c["faults"]]

    return {
        "rows_in_file": pn.rows_in(path),
        "parsed": len(набор),
        "cases": случаи,
        "faults": провалы,
        "silent": len(молчащие),
        "spoke": len(заговорившие),
        "outcomes_seen": sorted(исходы),
        "reasons_seen": sorted(причины),
        "candidates": кандидатов,
        "candidates_without_applicability": без_применимости,
        "candidates_unmarked": без_пометки,
        "candidates_without_evidence": без_доказательства,
        "steps_with_ceiling": шагов_с_потолком,
        "price_order_broken": цена_нарушена,
        "why_not_next_printed": почему_не_сосед,
        "rival_displaced": вытеснен,
        "rival_none_at_all": нет_проверенных,
        "rival_line_missing": строка_пропущена,
        "rival_line_spurious": строка_лишняя,
        "banned_candidates": запретом_отклонено,
        "retired_candidates": снятых,
        "wrong_output_candidates": не_тот_выход,
        "output_confirmed": выход_подтверждён,
        "chosen_wrong_output": выбран_не_тот,
        "shutdown_announced": объявлено_снятие,
        "chosen_is_retired": выбран_снятый,
        "steps_with_ban": шагов_с_запретом,
        "ban_unspoken": запрет_без_строки,
        "ban_as_evidence": запрет_как_довод,
        "chosen_is_banned": выбран_запрещённый,
        "frame_measured": кадр_измерен,
        "frame_accepted": кадр_принят,
        "frame_rejected_steps": кадр_отверг,
        "frame_without_creative": кадр_без_креатива,
        "frame_reject_unspoken": отказ_без_строки,
        "per_converted": переводов,
        "converted_unmarked": перевод_без_пометки,
        "credits_converted": кредиты_переведены,
    }


def старшие_ключи(строка: dict) -> tuple:
    """Поля ключа планировщика, стоящие ПЕРЕД ценой, по строке кандидата.

    Считаются теми же функциями планировщика (Е1): второй способ вычислить
    порядок разъехался бы с первым, а именно на разъезде эта проверка и
    погорела. `blocked_rank` берёт `Candidate`, поэтому подставляется лёгкая
    заглушка с тремя полями, из которых он и считает.
    """

    заглушка = cast(
        "pn.Candidate",
        SimpleNamespace(
            ban_state=str(строка.get("ban_state", "")),
            life_state=str(строка.get("life_state", "")),
            out_state=str(строка.get("out_state", "")),
        ),
    )
    return (pn.blocked_rank(заглушка), pn.FIT_ORDER.get(строка.get("fit_state", ""), 0))


def verdict(итог: dict) -> tuple[int, list[str]]:
    """Код возврата и причины. Три исхода, и третий не сворачивается (Р1)."""
    беды: list[str] = []
    if итог["parsed"] == 0:
        return 2, ["контрольный набор пуст: мерить нечем"]
    if итог["parsed"] != итог["rows_in_file"]:
        беды.append(
            f"строк в файле {итог['rows_in_file']}, разобрано {итог['parsed']}: "
            "контроль пропал молча"
        )
    for c in итог["faults"]:
        беды.append(f"{c['id']}: " + "; ".join(c["faults"]))
    if not итог["silent"]:
        беды.append("ни на одном входе прибор не промолчал: негативного контроля нет")
    if not итог["spoke"]:
        беды.append("ни на одном входе прибор не собрал плана: он мёртв")
    if len(итог["outcomes_seen"]) < 2:
        беды.append(f"различённых исходов {len(итог['outcomes_seen'])}, нужно не меньше двух")
    if итог["candidates_unmarked"]:
        беды.append(
            f"кандидатов без применимости {итог['candidates_without_applicability']}, "
            f"из них БЕЗ ПОМЕТКИ «{pn.NOT_MEASURED_MARK}» {итог['candidates_unmarked']}"
        )
    if not итог["steps_with_ceiling"]:
        беды.append(
            "ни на одном брифе потолок не был вычитан: разборщик бюджета не проверен "
            "(негативного контроля мало — нужен и вход, где он срабатывает)"
        )
    for строка in итог["price_order_broken"]:
        беды.append(f"порядок по цене нарушен — {строка}")
    for где in итог["rival_line_missing"]:
        беды.append(
            f"выбран кандидат без измеренной применимости, а о проверенных не сказано: {где}"
        )
    for где in итог["rival_line_spurious"]:
        беды.append(f"выбранный сам проверен, а строка о вытесненном всё равно напечатана: {где}")
    for где in итог["chosen_wrong_output"]:
        беды.append(f"ВЫБРАНА модель, которая нужного шагу вида не отдаёт: {где}")
    if not итог["wrong_output_candidates"]:
        беды.append(
            f"ни на одном шаге выход не отсёк кандидата: ветка «{pn.OUT_NO}» не проверена вовсе"
        )
    if not итог["output_confirmed"]:
        беды.append(
            f"ни у одного выбранного выход не подтверждён: ветка «{pn.OUT_YES}» не проверена вовсе"
        )
    for где in итог["chosen_is_retired"]:
        беды.append(f"ВЫБРАНА модель, у которой срок службы уже прошёл: {где}")
    if not итог["shutdown_announced"]:
        беды.append(
            "ни на одном шаге не сработало предупреждение о будущем снятии: ветка "
            f"«{pn.LIFE_ANNOUNCED}» не проверена вовсе"
        )
    for где in итог["chosen_is_banned"]:
        беды.append(f"ВЫБРАН кандидат, чей вход база запрещает: {где}")
    for где in итог["ban_unspoken"]:
        беды.append(f"запрет отклонил кандидата и об этом не сказано ни строки: {где}")
    for где in итог["ban_as_evidence"]:
        беды.append(f"строка-запрет напечатана как ДОВОД «чем выбран»: {где}")
    if not итог["banned_candidates"]:
        беды.append(
            f"ни на одном шаге запрет на вход не отклонил кандидата: ветка "
            f"«{pn.BAN_FORBIDS}» не проверена вовсе"
        )
    for где in итог["frame_without_creative"]:
        беды.append(f"креатив не подан, а кадр всё равно повлиял на отбор: {где}")
    for где in итог["frame_reject_unspoken"]:
        беды.append(f"кадр отверг кандидата и об этом не сказано ни строки: {где}")
    if not итог["frame_measured"]:
        беды.append("ни на одном брифе креатив не измерен: ветка кадра не проверена вовсе")
    if not итог["frame_rejected_steps"]:
        беды.append(
            f"ни на одном шаге кадр никого не отверг: ветка «{pn.REJECTED_BY_FRAME_MARK}» "
            "не проверена вовсе"
        )
    for где in итог["converted_unmarked"]:
        беды.append(f"цена переведена и не названа переведённой: {где}")
    for где in итог["credits_converted"]:
        беды.append(f"КРЕДИТЫ ПЕРЕВЕДЕНЫ В ДОЛЛАРЫ — курса не записано нигде: {где}")
    if not итог["per_converted"]:
        беды.append(
            "ни на одном шаге «за что» не переводилось: ветка перевода не проверена вовсе "
            f"(«{pn.CONVERTED_MARK}»)"
        )
    if not итог["rival_displaced"]:
        беды.append(
            "ни на одном шаге цена не вытеснила проверенного кандидата: ветка "
            f"«{pn.RIVAL_MARK}» не проверена вовсе"
        )
    if not итог["rival_none_at_all"]:
        беды.append(
            "ни на одном шаге не сказано, что проверенных нет вовсе: ветка "
            f"«{pn.NO_RIVAL_MARK}» не проверена вовсе"
        )
    if итог["candidates"] > 1 and not итог["why_not_next_printed"]:
        беды.append("ни у одного шага не напечатано, почему выбран этот, а не сосед")
    if итог["candidates_without_evidence"]:
        беды.append(
            f"кандидатов без единой строки доказательства {итог['candidates_without_evidence']}: "
            "чем выбран — не сказано"
        )
    return (1 if беды else 0), беды


def render(итог: dict) -> str:
    строки = [
        f"брифов в файле {итог['rows_in_file']}, разобрано {итог['parsed']}",
        (
            f"молчал на {итог['silent']}, собрал план на {итог['spoke']}; "
            f"исходов различено {len(итог['outcomes_seen'])} {итог['outcomes_seen']}; "
            f"причин {len(итог['reasons_seen'])} {итог['reasons_seen']}"
        ),
        (
            f"кандидатов выбрано {итог['candidates']}, из них без применимости "
            f"{итог['candidates_without_applicability']} (все с пометкой: "
            f"{итог['candidates_unmarked'] == 0}), без доказательства "
            f"{итог['candidates_without_evidence']}"
        ),
        (
            f"по выходу: не тот вид у {итог['wrong_output_candidates']} кандидат(ов), "
            f"выход подтверждён у {итог['output_confirmed']} выбранных, "
            f"выбран не тот {len(итог['chosen_wrong_output'])}"
        ),
        (
            f"по концу службы: уже снятых {итог['retired_candidates']}, "
            f"предупреждений о будущем снятии {итог['shutdown_announced']}, "
            f"выбрана снятая {len(итог['chosen_is_retired'])}"
        ),
        (
            f"запретом на вход отклонено {итог['banned_candidates']} кандидат(ов) "
            f"на {итог['steps_with_ban']} шаг(ах); выбран запрещённый "
            f"{len(итог['chosen_is_banned'])}, отказ без строки {len(итог['ban_unspoken'])}, "
            f"запрет как довод {len(итог['ban_as_evidence'])}"
        ),
        (
            f"креатив измерен на {итог['frame_measured']} брифе(ах), "
            f"кадр принят на {итог['frame_accepted']} шаг(ах), "
            f"отвергнуты на {итог['frame_rejected_steps']}, "
            f"влияние без креатива {len(итог['frame_without_creative'])}, "
            f"отказ без строки {len(итог['frame_reject_unspoken'])}"
        ),
        (
            f"«за что» переведено на {итог['per_converted']} шаг(ах), "
            f"без пометки {len(итог['converted_unmarked'])}, "
            f"кредитов переведено в доллары {len(итог['credits_converted'])}"
        ),
        (
            f"проверенный вытеснен ценой на {итог['rival_displaced']} шаг(ах), "
            f"проверенных нет вовсе на {итог['rival_none_at_all']}, "
            f"строка пропущена {len(итог['rival_line_missing'])}, "
            f"лишняя {len(итог['rival_line_spurious'])}"
        ),
        (
            f"шагов с вычитанным потолком {итог['steps_with_ceiling']}, "
            f"нарушений порядка по цене {len(итог['price_order_broken'])}, "
            f"строк «почему не сосед» {итог['why_not_next_printed']}"
        ),
        "",
    ]
    for c in итог["cases"]:
        знак = "!" if c["faults"] else ("?" if c["outcome"] == UNMEASURED else ".")
        строки.append(
            f"  {знак} {c['id']:20} {c['outcome']:18} [{c['reason']:22}] "
            f"шаги: {', '.join(c['steps']) or '—'} ({c['ms']} мс)"
        )
        for f in c["faults"]:
            строки.append(f"      ПРОВАЛ: {f}")
    return "\n".join(строки)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="прогнать контрольный набор")
    ap.add_argument("--brief", default="", help="собрать план по одному брифу")
    ap.add_argument("--creative", default="", help="путь к поданному креативу")
    ap.add_argument("--json", action="store_true", help="выдать машиночитаемо")
    args = ap.parse_args()

    if args.brief:
        итог = pn.plan(args.brief, creative=args.creative)
        print(json.dumps(итог, ensure_ascii=False, indent=2) if args.json else pn.render(итог))
        return 0

    итог = run()
    код, беды = verdict(итог)
    if args.json:
        print(json.dumps({**итог, "exit": код, "faults_named": беды}, ensure_ascii=False, indent=2))
    else:
        print(render(итог))
        for b in беды:
            print(f"ПРОВАЛ: {b}")
        print("ok" if код == 0 else ("не смогли" if код == 2 else "провал"))
    return код


if __name__ == "__main__":
    raise SystemExit(main())
