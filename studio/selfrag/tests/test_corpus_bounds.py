"""Границы приёмки корпусной строки: оценка 1..10 и потолок длины промпта.

ЗАЧЕМ. `studio/selfrag/corpus.py` решает по трём константам — `RATING_MIN`,
`RATING_MAX`, `PROMPT_MAX_CHARS` — какую строку в корпус пускать. До этого
файла ни одну из них не сторожил ни один тест: `scripts/check_mutants_cover.py`
числил модуль в «без мутантов». Расширь потолок, и в индекс попадёт вставленный
документ, который перевесит любую лексическую выдачу; сузь оценочную полосу, и
корпус молча похудеет.

Проверяется КАЖДАЯ граница с обеих сторон (Т1/Т3): значение на границе обязано
пройти, значение за ней — быть отброшено с названной причиной. Ожидаемые числа
записаны литералами (Т2): импортируй их отсюда — и они переедут вместе с
константой, ради которой файл написан.
"""

from __future__ import annotations

import unittest

from studio.selfrag.corpus import parse_row


def _строка(**поля):
    строка = {"prompt": "a rooftop at dusk"}
    строка.update(поля)
    return строка


class ПолосаОценки(unittest.TestCase):
    def test_края_полосы_принимаются(self) -> None:
        for оценка in (1, 10):
            запись, почему = parse_row(_строка(rating=оценка), source="s", line_no=1)
            self.assertIsNone(почему)
            assert запись is not None
            self.assertEqual(запись.rating, оценка)

    def test_ноль_и_одиннадцать_отброшены_с_причиной(self) -> None:
        for оценка in (0, 11):
            запись, почему = parse_row(_строка(rating=оценка), source="s", line_no=2)
            self.assertIsNone(запись)
            assert почему is not None
            self.assertIn("outside", почему)

    def test_отсутствие_оценки_это_не_нарушение(self) -> None:
        """Третий исход на уровне строки: неоценённая строка — не бракованная."""
        запись, почему = parse_row(_строка(), source="s", line_no=3)
        self.assertIsNone(почему)
        assert запись is not None
        self.assertIsNone(запись.rating)


class ПотолокДлины(unittest.TestCase):
    def test_ровно_потолок_принимается(self) -> None:
        запись, почему = parse_row(_строка(prompt="a" * 4000), source="s", line_no=4)
        self.assertIsNone(почему)
        assert запись is not None
        self.assertEqual(len(запись.prompt), 4000)

    def test_на_символ_длиннее_отброшено_с_причиной(self) -> None:
        запись, почему = parse_row(_строка(prompt="a" * 4001), source="s", line_no=5)
        self.assertIsNone(запись)
        assert почему is not None
        self.assertIn("cap is", почему)


if __name__ == "__main__":
    unittest.main()
