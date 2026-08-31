"""Стоящие вендорские факты: подтверждает ли URL вендорство ЭТОЙ модели.

ЗАЧЕМ ЭТОТ ГЕЙТ ПОЯВИЛСЯ

Абляция 2026-08-31 показала: если перемешать имена моделей между настоящими
фактами, поиск достанет ТЕ ЖЕ тексты и честно принесёт испорченную атрибуцию.
Инструмент ответит с той же уверенностью — заметить подмену ему нечем.

Оказалось, замечать есть чем, и прибор уже написан: `source_hosts.classify`
решает тир по URL, и у вендорского факта хост обязан принадлежать вендору
именно этой модели. Проверено на живых данных:

    настоящая база     0 расхождений из 452 вендорских
    перемешанная база  346 из 370 (94%)

То есть различитель работает и работает сильно. Не хватало одного: он
применялся ТОЛЬКО при записи факта (`advice.record`) и никогда — к тем, что
уже стоят. Факт, попавший в базу мимо `record` — правкой файла, слиянием,
переносом при канонизации имени, — не проверялся никогда.

ЧТО ЭТОТ ГЕЙТ НЕ ЛОВИТ, И ЭТО НАДО ЗНАТЬ

Только вендорский тир. Портальный и блоговый факт не обязан лежать на хосте,
связанном с моделью, — там связь модели с утверждением ничем не подтверждается
по устройству, и требовать её значило бы выдумать проверку, которой нет.
Значит 94% на перемешанной базе — это потолок ЭТОГО прибора, а не полнота.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402
from studio.selfrag import source_hosts as sh  # noqa: E402
from studio.selfrag.facts import Fact, load_facts  # noqa: E402


#: Скоупы про класс задач: у них нет вендора по устройству, и спрашивать с них
#: вендорский хост бессмысленно.
def is_scope(model: str) -> bool:
    return str(model or "").endswith("*")


def mismatches(facts: list[Fact]) -> list[dict]:
    """Вендорские факты, чей URL вендорства не подтверждает."""
    плохие = []
    for f in facts:
        if f.tier != "vendor" or is_scope(f.model):
            continue
        вышло = sh.classify(
            f.model, f.source_url, vendor_tier="vendor", portal_tier="portal", blog_tier="blog"
        )
        if вышло != "vendor":
            плохие.append(
                {
                    "model": f.model,
                    "attribute": f.attribute,
                    "host": sh.host_of(f.source_url),
                    "got": вышло,
                    "url": f.source_url,
                }
            )
    return плохие


def check(facts: list[Fact] | None = None) -> int:
    rows = facts if facts is not None else load_facts()
    вендорских = [f for f in rows if f.tier == "vendor" and not is_scope(f.model)]
    плохие = mismatches(rows)
    for x in плохие[:12]:
        print(f"  {x['model']:28} {x['attribute']:22} {x['host']:28} → {x['got']}")
    print(f"\nпроверено {len(вендорских)}")
    print(f"нарушений {len(плохие)}")
    print(f"не смогли {len(rows) - len(вендорских)}  (нe вендорский тир или скоуп)")
    if not вендорских:
        print(f"{UNMEASURED}: вендорских фактов нет — проверять нечего")
        return 2
    if плохие:
        print(f"{FAIL}: URL не подтверждает вендорство модели")
        return 1
    print(f"{PASS}: у каждого вендорского факта хост принадлежит вендору этой модели")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.parse_args(argv)
    return check()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
