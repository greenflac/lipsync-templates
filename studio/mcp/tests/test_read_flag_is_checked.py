"""Утверждение «я эту страницу открыл» против свидетельства о том, что её
открыть было нечем.

ЗАЧЕМ. Независимая проверка 2026-09-05: `read_directly` не сверялся НИ С ЧЕМ.
Выдуманное утверждение с `tier=vendor`, `read_directly=True` и нотой «I never
opened this page» на хосте, закрытом политикой, прошло с исходом `pass`. На
живой базе 2047 строк утверждают чтение, и непустое `witnessed` есть у 13.

Флаг заведён ровно затем, чтобы отличать читанное от нечитанного; не сверяемый
ни с чем, он отличал ноль от ноля.

Ожидаемое — литералы (Т2), сети нет (Т4).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from studio.mcp import advice, fetch


class ФлагЧтенияСверяетсяСЖурналомОтказов(unittest.TestCase):
    def setUp(self) -> None:
        каталог = Path(tempfile.mkdtemp())
        self.цель = каталог / "facts.jsonl"
        self.отказы = каталог / "denied_hosts.jsonl"
        self.отказы.write_text(
            json.dumps({"host": "закрытый.test", "state": "refused"}, ensure_ascii=False)
            + "\n"
            + json.dumps({"host": "открытый.test", "state": "refused"}, ensure_ascii=False)
            + "\n"
            + json.dumps({"host": "открытый.test", "state": "open"}, ensure_ascii=False)
            + "\n",
            encoding="utf-8",
        )

    def записать(self, url: str) -> dict:
        with mock.patch.object(fetch, "DENIED_PATH", self.отказы):
            advice.record(
                "kling-3.0",
                "max_seconds",
                "10",
                url,
                "blog",
                "2026-09-05",
                read_directly=True,
                path=self.цель,
            )
        строки = [
            json.loads(с) for с in self.цель.read_text(encoding="utf-8").splitlines() if с.strip()
        ]
        return строки[-1]

    def test_на_закрытом_хосте_флаг_чтения_снимается(self):
        строка = self.записать("https://закрытый.test/страница")
        self.assertIs(строка["read_directly"], False)
        self.assertIn("ХОСТ ЗАКРЫТ ПОЛИТИКОЙ", строка["note"])

    def test_сам_факт_при_этом_не_отвергается(self):
        """Неверно только утверждение о чтении; значение может быть верным, и
        выбрасывать его значило бы терять данные из-за чужой оплошности."""
        строка = self.записать("https://закрытый.test/страница")
        self.assertEqual(строка["value"], "10")
        self.assertEqual(строка["model"], "kling-3.0")

    def test_на_открытом_хосте_флаг_остаётся(self):
        """Негативный контроль (И5): проверка, снимающая флаг у всех, не
        отличается от отсутствия флага."""
        строка = self.записать("https://открытый.test/страница")
        self.assertIs(строка["read_directly"], True)
        self.assertNotIn("ХОСТ ЗАКРЫТ", строка["note"])

    def test_журнал_отказов_это_журнал_состояний(self):
        """`open` снимает прежний отказ. Считать по любому упоминанию значит
        завышать: у проверяющего это дало 983 строки против 1 настоящей."""
        with mock.patch.object(fetch, "DENIED_PATH", self.отказы):
            self.assertTrue(fetch.закрыт_политикой("https://закрытый.test/x"))
            self.assertFalse(fetch.закрыт_политикой("https://открытый.test/x"))
            self.assertFalse(fetch.закрыт_политикой("https://неизвестный.test/x"))

    def test_нет_журнала_нет_и_поправки(self):
        """Отсутствие журнала — не свидетельство отказа: молчание не улика."""
        with mock.patch.object(fetch, "DENIED_PATH", Path("/нет/такого/файла.jsonl")):
            self.assertFalse(fetch.закрыт_политикой("https://любой.test/x"))


if __name__ == "__main__":
    unittest.main()
