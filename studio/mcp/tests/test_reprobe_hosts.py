"""Гейт карты достижимости: он обязан краснеть, а не только зеленеть.

На живом журнале после перепрощупывания закрытых протухшим отказом семей нет,
и гейт печатает «годно» каждый прогон. Проверка, которая никогда не краснела,
неотличима от проверки, которая не умеет краснеть (И5), поэтому обе стороны
здесь стоят на СВОЁМ журнале во временном файле. Сети нет (Т4).
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

from studio.mcp import routes
from studio.selfrag import source_hosts

SPEC = importlib.util.spec_from_file_location(
    "reprobe_hosts", Path(__file__).resolve().parents[3] / "scripts" / "reprobe_hosts.py"
)
assert SPEC and SPEC.loader
rp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rp)

#: Вымышленная семья с ЕДИНСТВЕННЫМ маршрутом: тогда состояние этого хоста и
#: есть судьба семьи, и проверять нечего, кроме того, что проверяется.
ОДИН_МАРШРУТ = {"одинокая": ("shut.test",)}


def журнал(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
    )


class ГейтУмеетКраснеть(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.log = Path(self._dir.name) / "denied.jsonl"
        patcher = mock.patch.dict(source_hosts.VENDOR_SOURCES, ОДИН_МАРШРУТ, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _отказ(self, дней_назад: int) -> None:
        когда = (date.today() - timedelta(days=дней_назад)).isoformat()
        журнал(self.log, [{"host": "shut.test", "state": "refused", "first_seen": когда}])

    def test_протухший_отказ_считается_числом(self) -> None:
        self._отказ(routes.ГОРИЗОНТ_ДНЕЙ + 30)
        итог = rp.свести(path=self.log)
        self.assertEqual(итог["протухло"], 1)
        # Семья при этом НЕ закрыта: протухший отказ читается как «попробуй»,
        # и в этом весь смысл горизонта. Число печатается, нарушением не
        # становится — иначе гейт краснел бы от календаря, а не от кода.
        self.assertEqual(итог["семей на протухшем отказе"], [])

    def test_гейт_краснеет_если_горизонт_обойдут(self) -> None:
        """ЧТО ИМЕННО СТОРОЖИТ ЭТОТ ГЕЙТ, сказано прямо.

        Пока горизонт работает, семья не может быть закрыта протухшим отказом:
        такой отказ читается как `unknown`. Значит красное состояние достижимо
        РОВНО ОДНИМ способом — если `reachability` перестанет смотреть на дату.
        Здесь это и подделано: подменён сам `reachability`, а не журнал. Без
        этого теста «годно» гейта неотличимо от «нечего проверять» (И5).
        """
        self._отказ(routes.ГОРИЗОНТ_ДНЕЙ + 30)
        with mock.patch.object(routes, "reachability", return_value=routes.REACH_REFUSED):
            итог = rp.свести(path=self.log)
        self.assertEqual(итог["семей на протухшем отказе"], ["одинокая"])

    def test_та_же_семья_на_свежем_отказе_молчит(self) -> None:
        """Вторая половина контроля: свежий отказ — законная причина закрыть
        семью, и краснеть на нём значило бы требовать доступа, которого нам
        только что не дали."""
        self._отказ(0)
        итог = rp.свести(path=self.log)
        self.assertEqual(итог["протухло"], 0)
        self.assertEqual(итог["семей на протухшем отказе"], [])

    def test_нечитаемая_строка_считается_и_не_молчит(self) -> None:
        """Р2: ноль нарушений при нечитаемом журнале — не успех."""
        self.log.write_text('{"host": "a", "state": "refused"}\nне json\n', encoding="utf-8")
        self.assertEqual(rp.свести(path=self.log)["битых строк"], 1)


class ЧтоСчитаетсяОтказом(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.log = Path(self._dir.name) / "denied.jsonl"

    def test_строка_без_state_это_отказ(self) -> None:
        """Конвенция журнала: все строки до 2026-08-27 писались без поля."""
        журнал(self.log, [{"host": "old.test", "first_seen": "2026-08-27"}])
        self.assertEqual(
            rp.протухшие(self.log, today="2026-09-02"), [("old.test", "https://old.test/")]
        )

    def test_открытый_хост_перепрощупывать_не_надо(self) -> None:
        журнал(self.log, [{"host": "ok.test", "state": "open", "first_seen": "2020-01-01"}])
        self.assertEqual(rp.протухшие(self.log, today="2026-09-02"), [])

    def test_последняя_строка_решает(self) -> None:
        """Хост, который отказал, а потом открылся, не перепрощупывается."""
        журнал(
            self.log,
            [
                {"host": "x.test", "state": "refused", "first_seen": "2026-08-01"},
                {"host": "x.test", "state": "open", "first_seen": "2026-08-02"},
            ],
        )
        self.assertEqual(rp.протухшие(self.log, today="2026-09-02"), [])


class ОтказПолитикиИЧужаяАвария(unittest.TestCase):
    """502 от туннеля — не отказ политики, и путать их значит закрыть себе
    хост чужой аварией. ИЗМЕРЕНО 2026-09-02: ровно так ответил docs.hedra.com,
    при том что www.hedra.com в тот же заход отдал 200."""

    def test_403_туннеля_это_отказ(self) -> None:
        self.assertTrue(rp.ОТКАЗ_ПОЛИТИКИ.search("Tunnel connection failed: 403 Forbidden"))

    def test_502_туннеля_это_не_отказ(self) -> None:
        self.assertIsNone(rp.ОТКАЗ_ПОЛИТИКИ.search("Tunnel connection failed: 502 Bad Gateway"))


if __name__ == "__main__":
    unittest.main()
