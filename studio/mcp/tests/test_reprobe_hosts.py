"""Пере-щуп закрытых хостов: чужая авария не должна закрывать хост навсегда.

ЗАЧЕМ. Журнал отказов решает, какие страницы этот агент считает недоступными.
Записать туда 502 от шлюза значит закрыть себе хост ЧУЖОЙ аварией — и никто
этого не заметит, потому что «закрыт» выглядит одинаково независимо от причины.

Подпись отказа ПОЛИТИКИ узкая нарочно: `tunnel connection failed: 403|407`.

ИЗМЕРЕНО 2026-09-06 независимой приёмкой: модуль не был покрыт ничем, и я же
объявил его непокрываемым, не проверив. Покрывается подменой `urlopen` —
ни сети, ни диска (Т4).
"""

from __future__ import annotations

import importlib.util
import unittest
import urllib.error
from pathlib import Path
from unittest import mock

_SPEC = importlib.util.spec_from_file_location(
    "reprobe_hosts", Path(__file__).resolve().parents[3] / "scripts" / "reprobe_hosts.py"
)
assert _SPEC and _SPEC.loader
щуп = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(щуп)


def при_ошибке(ошибка: Exception):
    return mock.patch.object(щуп.urllib.request, "urlopen", side_effect=ошибка)


class ЧужаяАварияНеЗакрываетХост(unittest.TestCase):
    def test_отказ_политики_это_отказ(self):
        with при_ошибке(OSError("Tunnel connection failed: 403 Forbidden")):
            исход, _ = щуп.прощупать("https://docs.example.test/")
        self.assertEqual("refused", исход)

    def test_407_тоже_отказ_политики(self):
        with при_ошибке(OSError("Tunnel connection failed: 407 Proxy Authentication Required")):
            исход, _ = щуп.прощупать("https://docs.example.test/")
        self.assertEqual("refused", исход)

    def test_502_от_шлюза_это_НЕ_отказ(self):
        """Негативный контроль (И5) и вся причина существования узкой подписи:
        авария шлюза, записанная отказом, закрывает хост навсегда."""
        with при_ошибке(OSError("Tunnel connection failed: 502 Bad Gateway")):
            исход, причина = щуп.прощупать("https://docs.example.test/")
        self.assertEqual("не смогли", исход)
        self.assertIn("502", причина)

    def test_обрыв_связи_это_третий_исход(self):
        with при_ошибке(TimeoutError("timed out")):
            исход, _ = щуп.прощупать("https://docs.example.test/")
        self.assertEqual("не смогли", исход)

    def test_404_значит_хост_ДОСТУПЕН(self):
        """Ответил 404 — путь другой, а хост открыт: это ровно то, что здесь
        измеряется. Записать его закрытым значило бы соврать в свою пользу."""
        ошибка = urllib.error.HTTPError("https://x.test/", 404, "Not Found", {}, None)  # type: ignore[arg-type]
        with при_ошибке(ошибка):
            исход, причина = щуп.прощупать("https://x.test/")
        self.assertEqual("open", исход)
        self.assertIn("404", причина)

    def test_подпись_отказа_названа_литералом(self):
        """Т2: подпись обязана оставаться УЗКОЙ. Расширить её значит начать
        закрывать хосты чужими авариями, и заметить это будет нечем."""
        self.assertTrue(щуп.ОТКАЗ_ПОЛИТИКИ.search("tunnel connection failed: 403"))
        self.assertTrue(щуп.ОТКАЗ_ПОЛИТИКИ.search("Tunnel Connection Failed: 407 x"))
        self.assertIsNone(щуп.ОТКАЗ_ПОЛИТИКИ.search("tunnel connection failed: 502"))
        self.assertIsNone(щуп.ОТКАЗ_ПОЛИТИКИ.search("403 Forbidden"))


if __name__ == "__main__":
    unittest.main()
