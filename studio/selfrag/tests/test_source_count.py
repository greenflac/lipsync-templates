"""Сколько источников стоит за утверждением — и какое значение идёт в заголовок.

Две константы-решения, обе найдены 2026-09-03 чтением живой выдачи (П3).
Ожидаемое здесь литералы (Т2).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from studio.selfrag.facts import FactStore, load_facts


def база(строки: list[dict]) -> FactStore:
    путь = Path(tempfile.mkdtemp()) / "facts.jsonl"
    путь.write_text(
        "\n".join(json.dumps(с, ensure_ascii=False) for с in строки) + "\n", encoding="utf-8"
    )
    return FactStore(load_facts(путь))


def строка(**kw) -> dict:
    основа = {
        "model": "м",
        "attribute": "plan_slots",
        "value": "значение",
        "source_url": "https://вендор.test/страница",
        "tier": "vendor",
        "stated_on": "2026-08-27",
    }
    основа.update(kw)
    return основа


class ОднаСтраницаЭтоОдинИсточник(unittest.TestCase):
    """ИЗМЕРЕНО на живой базе: у 88 пар (модель, атрибут) одна и та же
    страница даёт несколько строк — 147 лишних. Счёт по строкам обещал
    подтверждение, которого никто не давал."""

    def test_два_чтения_одной_страницы_это_один_источник(self):
        b = база(
            [
                строка(value="Scale 3"),
                строка(value="Scale 3; на legacy Scale 1", stated_on="2026-09-03"),
            ]
        )
        итог = b.claims("м", "plan_slots")
        self.assertIn("from 1 source(s)", итог["note"])

    def test_две_разные_страницы_это_два_источника(self):
        """Негативный контроль (И5): починка не должна схлопывать настоящее
        подтверждение вторым источником."""
        b = база(
            [
                строка(value="одно и то же"),
                строка(value="одно и то же", source_url="https://другой.test/стр"),
            ]
        )
        self.assertIn("from 2 source(s)", b.claims("м", "plan_slots")["note"])

    def test_многозначный_атрибут_считает_страницы_а_не_находки(self):
        """Одна страница, назвавшая три отказа, — три находки и ОДИН источник.
        Число значений печатается отдельно и не сливается со счётом."""
        b = база(
            [
                строка(attribute="failure_mode", value="а"),
                строка(attribute="failure_mode", value="б"),
                строка(attribute="failure_mode", value="в"),
            ]
        )
        нота = b.claims("м", "failure_mode")["note"]
        self.assertIn("3 value(s)", нота)
        self.assertIn("from 1 source(s)", нота)


class ВЗаголовокИдётСамоеСвежееЧтение(unittest.TestCase):
    """Когда два чтения одной страницы признаны ОДНИМ ответом разной
    подробности, в заголовок шёл алфавитно первый — то есть обычно прежний.
    Деталь в выдаче была верна, заголовок нет: тот самый класс дефекта, ради
    которого заведён `scripts/check_headline.py`."""

    def test_свежее_чтение_вытесняет_прежнее_из_заголовка(self):
        b = база(
            [
                строка(value="A: Scale 3"),
                строка(value="A: Scale 3, а на legacy Scale 1", stated_on="2026-09-03"),
            ]
        )
        нота = b.claims("м", "plan_slots")["note"]
        self.assertIn("legacy Scale 1", нота)

    def test_порядок_строк_в_файле_ничего_не_решает(self):
        """Тот же набор в обратном порядке даёт тот же заголовок: решает ДАТА,
        а не место в журнале."""
        пары = [
            строка(value="A: Scale 3, а на legacy Scale 1", stated_on="2026-09-03"),
            строка(value="A: Scale 3"),
        ]
        нота = база(пары).claims("м", "plan_slots")["note"]
        self.assertIn("legacy Scale 1", нота)

    def test_обе_записи_остаются_видны_целиком(self):
        """Заголовок выбирает одно, но история не выкидывается: журнал
        append-only, и прежнее чтение обязано остаться в выдаче."""
        b = база(
            [
                строка(value="A: Scale 3"),
                строка(value="A: Scale 3, а на legacy Scale 1", stated_on="2026-09-03"),
            ]
        )
        значения = b.claims("м", "plan_slots")["values"]
        self.assertEqual(len(значения), 2)


if __name__ == "__main__":
    unittest.main()
