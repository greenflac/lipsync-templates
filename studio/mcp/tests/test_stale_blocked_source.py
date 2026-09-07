"""Очередь «протухшего» не просит перечитать страницу, которую нечем открыть.

Та же болезнь, что уже лечилась в этом же приборе для ДАТЫ ПУБЛИКАЦИИ: очередь
наполняется строками, по которым названное ею действие выполнить нельзя, — и
тогда её читают по диагонали ВМЕСТЕ с теми строками, где работа настоящая.

ИЗМЕРЕНО 2026-09-07 на живой базе: из 38 протухших строк 1 стоит на хосте,
закрытом политикой окружения (the-decoder.com). «Поищи в сети и запиши, что
найдёшь» для неё — работа, которую нельзя сделать, а обходить запрет нельзя
(Ц3). Строка не выбрасывается: утверждение стареет по-прежнему.

Т2: ожидаемое — литералы. Т4: журнал отказов читается файлом, сети нет.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from studio.mcp import advice, fetch

ДАВНО = (date.today() - timedelta(days=400)).isoformat()


def _база(хосты: tuple[str, ...]) -> Path:
    путь = Path(tempfile.mkdtemp()) / "facts.jsonl"
    with путь.open("w", encoding="utf-8") as h:
        for номер, хост in enumerate(хосты):
            h.write(
                json.dumps(
                    {
                        "model": "kling-3.0",
                        "attribute": f"attr_{номер}",
                        "value": "10 s",
                        "source_url": f"https://{хост}/page",
                        "tier": "blog",
                        "stated_on": ДАВНО,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return путь


def _журнал(закрытые: tuple[str, ...]) -> Path:
    путь = Path(tempfile.mkdtemp()) / "denied.jsonl"
    with путь.open("w", encoding="utf-8") as h:
        for хост in закрытые:
            h.write(
                json.dumps(
                    {
                        "host": хост,
                        "url": f"https://{хост}/",
                        "reason": "Tunnel connection failed: 403",
                        "why_wanted": "нужен предел",
                        "incidental": False,
                        "state": "refused",
                        "first_seen": "2026-09-01",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    return путь


class ЗакрытыйИсточникОтделён(unittest.TestCase):
    def _очередь(self, закрытые: tuple[str, ...]) -> dict:
        база = _база(("the-decoder.com", "openweb.example"))
        with mock.patch.object(fetch, "DENIED_PATH", _журнал(закрытые)):
            return advice.stale(path=база)

    def test_строка_на_закрытом_хосте_уходит_из_работы(self) -> None:
        итог = self._очередь(("the-decoder.com",))
        self.assertEqual(["https://openweb.example/page"], [с["source_url"] for с in итог["stale"]])
        self.assertEqual(
            ["https://the-decoder.com/page"],
            [с["source_url"] for с in итог["blocked_source"]],
        )
        self.assertEqual(1, итог["violations"], "закрытая строка не считается работой")

    def test_сказано_словами_и_числом(self) -> None:
        """Р2: исход без числа и причины чинить нечем."""
        нота = self._очередь(("the-decoder.com",))["note"]
        self.assertIn("Ещё 1 строк", нота)
        self.assertIn("закрытых политикой", нота)
        self.assertIn("обходить запрет нельзя", нота)

    def test_открытый_хост_остаётся_работой(self) -> None:
        """Вторая сторона (И5): прибор, уносящий всё, дал бы пустую очередь."""
        итог = self._очередь(())
        self.assertEqual(
            sorted(["https://openweb.example/page", "https://the-decoder.com/page"]),
            sorted(с["source_url"] for с in итог["stale"]),
        )
        self.assertEqual([], итог["blocked_source"])
        self.assertNotIn("закрытых политикой", итог["note"])


class ВсеПротухшиеЗакрытыЭтоНеУспех(unittest.TestCase):
    """Найдено приёмкой 2026-09-07 и воспроизведено ею же.

    Строки уносились из `stale` и не досчитывались никуда, поэтому случай «все
    протухшие стоят на закрытых хостах» давал `pass` и ноту «all 2 claim(s)
    are within 90 days» — прямую неправду над строками 2024 года. Р2 дословно:
    ноль нарушений при нуле отработавших проверок — не успех.
    """

    def _очередь_только_закрытых(self) -> dict:
        база = _база(("the-decoder.com", "the-decoder.com"))
        with mock.patch.object(fetch, "DENIED_PATH", _журнал(("the-decoder.com",))):
            return advice.stale(path=база)

    def test_исход_не_годно_и_не_pass(self) -> None:
        итог = self._очередь_только_закрытых()
        self.assertEqual("could not measure", итог["outcome"], итог)

    def test_числа_сходятся(self) -> None:
        итог = self._очередь_только_закрытых()
        self.assertEqual(2, итог["checked"])
        self.assertEqual(2, итог["unmeasured"], "закрытые обязаны считаться, а не исчезать")
        self.assertEqual(2, len(итог["blocked_source"]))
        self.assertEqual([], итог["stale"])

    def test_нота_не_говорит_что_всё_свежо(self) -> None:
        нота = self._очередь_только_закрытых()["note"]
        self.assertNotIn("are within", нота)
        self.assertIn("перечитать их здесь НЕЧЕМ", нота)


if __name__ == "__main__":
    unittest.main()
