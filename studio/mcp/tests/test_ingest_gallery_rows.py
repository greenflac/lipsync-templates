"""Строка галереи: без слов это не строка, а сбой разбора выше по течению.

ЗАЧЕМ. Смысл файла — ФОРМУЛИРОВКА промпта. Строка без неё не «короткий
промпт», а обломок разбора, и попав в базу она даёт вид записи там, где записи
нет: ретривер её найдёт, покажет и ничего не скажет.

ИЗМЕРЕНО 2026-09-06: у `normalise` не было ни одного теста — `MIN_WORDS = 1`
держал все три набора зелёными. Отдельно проверено, что этот модуль НЕ участвует
в гейте, то есть его не сторожил и гейт.

Ожидаемое — литералы (Т2), диска и сети нет (Т4, Т5).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

# Загрузка ПО ПУТИ: рядом с каталогом `studio/knowledge/` лежит модуль
# `studio/knowledge.py`, и обычный импорт разрешается в модуль, а не в каталог.
# Та же ловушка уже стоила красного гейта на mypy 2026-09-06.
_SPEC = importlib.util.spec_from_file_location(
    "ingest_gallery",
    Path(__file__).resolve().parents[3] / "studio" / "knowledge" / "ingest_gallery.py",
)
assert _SPEC and _SPEC.loader
галерея = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(галерея)


class БезФормулировкиСтрокиНет(unittest.TestCase):
    def test_две_слова_это_обломок_разбора(self):
        """Граница снизу (Т3): два слова — не формулировка."""
        self.assertIsNone(галерея.normalise({"prompt": "amber bottle"}))

    def test_три_слова_уже_формулировка(self):
        """Та же граница сверху: на трёх словах строка обязана появиться."""
        строка = галерея.normalise({"prompt": "amber glass bottle"})
        self.assertIsNotNone(строка)
        assert строка is not None
        self.assertEqual("amber glass bottle", строка["prompt"])

    def test_порог_названо_числом(self):
        self.assertEqual(3, галерея.MIN_WORDS)

    def test_пустая_строка_не_проходит(self):
        self.assertIsNone(галерея.normalise({}))
        self.assertIsNone(галерея.normalise({"prompt": "   "}))

    def test_формулировка_ищется_во_всех_трёх_полях(self):
        """Источники называют одно и то же поле по-разному, и молчаливая
        потеря текста здесь неотличима от отсутствия текста."""
        for поле in ("prompt", "text", "wording"):
            строка = галерея.normalise({поле: "amber glass bottle"})
            self.assertIsNotNone(строка, поле)

    def test_адрес_страницы_не_теряется_как_бы_его_ни_звали(self):
        """Адрес — механизм точного удаления по просьбе владельца галереи.
        Сборщик, называвший поле `page`, однажды терял его здесь молча."""
        for поле in ("source_url", "url", "page"):
            строка = галерея.normalise({"prompt": "amber glass bottle", поле: "https://x.test/p"})
            assert строка is not None
            self.assertEqual("https://x.test/p", строка["source_url"], поле)


if __name__ == "__main__":
    unittest.main()
