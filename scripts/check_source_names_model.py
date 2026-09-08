#!/usr/bin/env python3
"""Утверждение о модели X, снятое со страницы модели Y.

ЗАЧЕМ. Карточка модели на HuggingFace — страница ОДНОЙ модели. Утверждение о
другой модели, процитированное с неё, приписывает чужой странице то, чего она
про эту модель не говорит; на ступени `vendor` это ещё и выдаётся за слова
самого вендора.

ИЗМЕРЕНО 2026-09-05 независимой проверкой и перепроверено здесь: из 951 живой
строки с карточки HuggingFace у 21 имя модели не совпадает с карточкой. Пять из
них стоят на ступени `vendor`, среди них:

    wan2.1-t2v-1.3b   <- карточка Wan2.1-T2V-14B      (другая модель семейства)
    latentsync-1.5    <- карточка LatentSync-1.6      (другая версия)
    gpt-5             <- карточка Kimi-K2-Thinking    (карточка КОНКУРЕНТА)

Последнее — сравнительная таблица, которую вендор написал ПРО ЧУЖУЮ модель, и
она лежит в базе как утверждение об этой чужой модели.

ЧТО СЧИТАЕТСЯ НАРУШЕНИЕМ. Только адрес вида `huggingface.co/ВЛАДЕЛЕЦ/МОДЕЛЬ`, и
только когда имя модели строки после свёртки написаний (`modelnames.fold`) не
совпадает с именем карточки и не содержится в нём. Общий поиск «имя из адреса
против имени строки» здесь НЕ годится: на живой базе он даёт 868 срабатываний,
почти все ложные — у блогов и порталов путь адреса не имя модели.

ТРИ ИСХОДА (Р1)

    годно      расхождений не больше потолка
    не годно   больше потолка
    не смогли  база не прочиталась — считать нечего

НЕГАТИВНЫЙ КОНТРОЛЬ (И5): `--самопроверка` подкладывает заведомо чужую строку и
требует, чтобы проверка её нашла. Без этого «нарушений 0» неотличимо от
«ничего не искали».
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.selfrag import modelnames  # noqa: E402
from studio.selfrag.facts import Fact, load_facts  # noqa: E402

PASS = "pass"
FAIL = "fail"
UNMEASURED = "could not measure"

#: Карточка модели: владелец и имя. `huggingface.co/models`, `/papers`,
#: `/datasets`, `/spaces`, `/buckets` — не карточки, а разделы площадки.
КАРТОЧКА = re.compile(r"^https?://huggingface\.co/([^/]+)/([^/?#]+)", re.I)
#: `api` — это JSON-эндпоинт `huggingface.co/api/models/ВЛАДЕЛЕЦ/МОДЕЛЬ`, где имя
#: модели стоит на два сегмента правее; общий разбор читал бы его как «модель
#: models» и объявлял чужой каждую такую строку. Четыре ложных срабатывания на
#: живой базе, поймано чтением собственной выдачи (П3).
НЕ_ВЛАДЕЛЬЦЫ = frozenset(
    {"models", "papers", "datasets", "spaces", "buckets", "blog", "docs", "api"}
)

#: ПОТОЛОК. Это ратчет: он обязан только падать. ИЗМЕРЕНО 2026-09-05 — 10 строк
#: из 961 (первый замер дал 21, из них 11 оказались ложными: JSON-эндпоинт
#: `api/models/...` читался как «модель models», поймано чтением выдачи
#: глазами). Ноль сюда не ставится сегодня НАРОЧНО: десять существующих строк —
#: это работа по перечитыванию страниц, а не правка кода, и обнулить потолок
#: раньше этой работы значило бы держать гейт красным ради красного.
ПОТОЛОК = 10


def чужая_карточка(факт: Fact) -> str:
    """Имя карточки, если строка приписана НЕ ей. Пусто — всё в порядке."""
    совпало = КАРТОЧКА.match(str(факт.source_url or ""))
    if not совпало or совпало.group(1).lower() in НЕ_ВЛАДЕЛЬЦЫ:
        return ""
    имя = modelnames.fold(str(факт.model or "").lower())
    if not имя or имя == "*":
        return ""
    карточка = modelnames.fold(совпало.group(2).lower())
    if имя == карточка or имя in карточка or карточка in имя:
        return ""
    return совпало.group(2)


def свести(факты: list[Fact] | None = None) -> dict[str, Any]:
    строки = load_facts() if факты is None else факты
    if not строки:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "база пуста или не прочиталась",
            "чужие": [],
        }
    карточные = [ф for ф in строки if КАРТОЧКА.match(str(ф.source_url or ""))]
    чужие = [(ф, чужая_карточка(ф)) for ф in карточные]
    чужие = [(ф, к) for ф, к in чужие if к]
    исход = PASS if len(чужие) <= ПОТОЛОК else FAIL
    return {
        "outcome": исход,
        "checked": len(карточные),
        "violations": len(чужие),
        "unmeasured": 0,
        "чужие": [(ф.model, ф.attribute, ф.tier, к) for ф, к in чужие],
        "на_вендоре": sum(1 for ф, _ in чужие if ф.tier == "vendor"),
    }


def самопроверка() -> int:
    """Возвращает 1, если проверка слепа: подложенная чужая строка не найдена."""
    подделка = Fact(
        model="kling-3.0",
        attribute="max_seconds",
        value="10",
        source_url="https://huggingface.co/ByteDance/LatentSync-1.6",
        tier="vendor",
        stated_on="2026-09-05",
    )
    своя = Fact(
        model="latentsync-1.6",
        attribute="max_seconds",
        value="10",
        source_url="https://huggingface.co/ByteDance/LatentSync-1.6",
        tier="vendor",
        stated_on="2026-09-05",
    )
    плохо = bool(чужая_карточка(своя)) or not чужая_карточка(подделка)
    print(
        "негативный контроль: подложенная чужая карточка "
        + ("НЕ НАЙДЕНА или своя объявлена чужой — проверка слепа" if плохо else "найдена")
    )
    return 1 if плохо else 0


def main(argv: list[str]) -> int:
    дано = argparse.ArgumentParser(description=__doc__)
    дано.add_argument("--check", action="store_true")
    дано.add_argument("--top", type=int, default=10)
    разобрано = дано.parse_args(argv)

    if самопроверка():
        print("\nпроверено 0\nнарушений 0\nне смогли 1")
        return 2

    итог = свести()
    for модель, атрибут, тир, карточка in итог["чужие"][: разобрано.top]:
        print(f"  ЧУЖАЯ КАРТОЧКА [{тир}] {модель}.{атрибут} <- карточка {карточка}")
    хвост = len(итог["чужие"]) - разобрано.top
    if хвост > 0:
        print(f"  … и ещё {хвост}")
    print(
        f"\nпроверено {итог['checked']}\nнарушений {итог['violations']}\nне смогли {итог['unmeasured']}"
    )
    print(
        f"\n{итог['outcome']}: со страницы чужой модели {итог['violations']} строк(и) из "
        f"{итог['checked']} при потолке {ПОТОЛОК}; из них на ступени vendor "
        f"{итог.get('на_вендоре', 0)}"
    )
    if итог["violations"] < ПОТОЛОК:
        print(
            f"ПОТОЛОК УСТАРЕЛ: {итог['violations']} при потолке {ПОТОЛОК} — опустите "
            f"ПОТОЛОК до {итог['violations']}, иначе он перестанет ловить рост."
        )
        return 1 if разобрано.check else 0
    return (1 if итог["outcome"] == FAIL else 0) if разобрано.check else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
