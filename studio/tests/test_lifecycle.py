"""Снятая с обслуживания модель: что считается снятием, а что — словом в тексте.

Все входы ниже — СТРОКИ ЖИВОЙ БАЗЫ, а не выдуманные. Половина тестов —
негативный контроль (И5): пометить рабочую модель мёртвой значит выбросить
рабочую модель, и эта ошибка дороже пропущенной.
"""

from __future__ import annotations

import unittest
from datetime import date

from studio import lifecycle as L

СЕГОДНЯ = date(2026, 9, 2)


class ЭтоСнятие(unittest.TestCase):
    def test_дата_в_прошлом_это_отказ(self):
        итог = L.разобрать(
            "deprecated; Gemini API shutdown Aug 17 2026; Vertex endpoints follow",
            "deprecation",
            сегодня=СЕГОДНЯ,
        )
        self.assertEqual(итог.outcome, "не годно")
        self.assertEqual(итог.когда, "2026-08-17")

    def test_дата_впереди_это_предупреждение_а_не_отказ(self):
        """Модель ещё отвечает. Отказать по ней — выбросить рабочую; смолчать —
        дать человеку начать пайплайн, который через три недели встанет."""
        итог = L.разобрать(
            "Sora 2 and the Videos API are deprecated with a hard shutdown on 2026-09-24",
            "limitation",
            сегодня=СЕГОДНЯ,
        )
        self.assertEqual(итог.outcome, "не смогли")
        self.assertEqual(итог.когда, "2026-09-24")

    def test_снятие_без_даты_это_третий_исход(self):
        итог = L.разобрать("deprecated; replacement eleven_flash_v2_5", "status", сегодня=СЕГОДНЯ)
        self.assertEqual(итог.outcome, "не смогли")
        self.assertEqual(итог.когда, "")

    def test_срок_берётся_у_ЛЮБОГО_слова_о_снятии(self):
        """`imagen-4`: «DISCONTINUED on Vertex AI. ... listed as discontinued with
        discontinuation date June 30, 2026». Срок стоит у ВТОРОГО слова, в ста
        сорока знаках от первого, и по первому терялся."""
        итог = L.разобрать(
            "DISCONTINUED on Vertex AI. All three Imagen 4 endpoints (imagen-4.0-generate-001, "
            "imagen-4.0-fast-generate-001) are listed as discontinued with discontinuation "
            "date June 30, 2026 — already past.",
            "availability",
            сегодня=СЕГОДНЯ,
        )
        self.assertEqual(итог.когда, "2026-06-30")
        self.assertEqual(итог.outcome, "не годно")


class ЭтоНеСнятие(unittest.TestCase):
    """И5: слово находится и там, где речь не о модели."""

    def test_слово_в_тексте_промпта(self):
        итог = L.разобрать(
            "a rusty metal roof, sunset background. 15. A weak black cat", "observed_behaviour"
        )
        self.assertEqual(итог.outcome, "годно")

    def test_устарел_класс_библиотеки_а_не_модель(self):
        итог = L.разобрать(
            "FutureWarning: `Transformer2DModelOutput` is deprecated and will be removed "
            "in version 1.0.0",
            "observed_behaviour",
        )
        self.assertEqual(итог.outcome, "годно")

    def test_модель_зовётся_хотя_и_устарела(self):
        """`gpt-5`: «Still callable but superseded ... the only snapshot ... is
        marked Deprecated». Устарел СНИМОК, а не модель."""
        итог = L.разобрать(
            "Still callable but superseded: OpenAI labels it the previous model; the only "
            "snapshot, gpt-5-2025-08-07, is marked Deprecated. Sep 30 2024 knowledge cutoff.",
            "availability",
            сегодня=СЕГОДНЯ,
        )
        self.assertEqual(итог.outcome, "годно")

    def test_обучающая_отсечка_сроком_не_становится(self):
        """Дата стоит в шестидесяти знаках от слова `Deprecated`, то есть
        близость её НЕ отсекает. Отсекает то, что стоит сразу ПОСЛЕ неё."""
        self.assertEqual(
            L.дата_в_тексте("model is Deprecated. Sep 30 2024 knowledge cutoff.", 9), ""
        )

    def test_снят_один_эндпоинт_а_не_модель(self):
        """`sora-2 / remix_endpoint_status`: составное имя атрибута говорит об
        ОДНОМ эндпоинте. Пометить модель мёртвой по нему значит выбросить
        работающую модель."""
        итог = L.разобрать("deprecated, replaced by /v1/videos/edits", "remix_endpoint_status")
        self.assertEqual(итог.outcome, "годно")

    def test_пустое_значение_снятием_не_является(self):
        self.assertEqual(L.разобрать("", "status").outcome, "годно")


class МестаСнятия(unittest.TestCase):
    def test_находятся_все(self):
        места = L.все_места_снятия("deprecated now and discontinued later", "status")
        self.assertEqual(len(места), 2, места)

    def test_у_работающей_модели_мест_нет(self):
        self.assertEqual(L.все_места_снятия("still callable but deprecated", "status"), [])


if __name__ == "__main__":
    unittest.main()
