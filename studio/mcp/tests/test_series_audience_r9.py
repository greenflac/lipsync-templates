"""Девятый круг: детский сериал для видеоплощадки — заказ ДЛЯ детей, а не о ребёнке.

Бриф cs02 экспертного набора отвергался текстовым просевом с причиной
`запрещённая_тема`: слово адресата стояло перед названием площадки, а не
перед словом продукта. Ребёнка в кадре бриф не называет — значит, это
аудитория, и заказ планируется. Текст брифа берётся из набора, а не
переписывается сюда.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio.mcp import server as s  # noqa: E402

НАБОР = Path(__file__).resolve().parents[2] / "eval" / "briefs.jsonl"


def строка(префикс: str) -> dict:
    for строка_набора in НАБОР.read_text(encoding="utf-8").splitlines():
        if строка_набора.startswith("//") or not строка_набора.strip():
            continue
        d = json.loads(строка_набора)
        if d["id"].startswith(префикс):
            return d
    raise AssertionError(f"{префикс} нет в наборе")


class SeriesForYoungAudience(unittest.TestCase):
    def test_cs02_plans(self) -> None:
        row = строка("cs02")
        d = json.loads(s.plan_pipeline(row["brief"], spec=row["spec"]))
        self.assertNotEqual(d.get("reason"), "запрещённая_тема")
        self.assertTrue(d.get("steps"), d.get("reason"))

    def test_platform_word_does_not_change_the_audience(self) -> None:
        # Тот же бриф с площадкой и без неё судится одинаково.
        from studio.mcp import screen

        brief = строка("cs02")["brief"]
        без_площадки = " ".join(w for w in brief.split() if w.lower() != "youtube")
        self.assertEqual(screen.просеять(brief)["banned"], screen.просеять(без_площадки)["banned"])
        self.assertEqual(screen.просеять(brief)["banned"], [])


if __name__ == "__main__":
    unittest.main()
