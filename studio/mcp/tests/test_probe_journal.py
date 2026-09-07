"""«Их API ответил» — утверждение о событии, и у события теперь есть журнал.

П1: СЧЁТЧИК РАНЬШЕ РУЧКИ. Ручка (зонд) существовала с 2026-08-27, счётчика не
было: тир `probe` объявлялся вызывающим и сверять его было НЕ С ЧЕМ. Та же
дыра уже была у флага `read_directly` («я открыл эту страницу» про хост,
закрытый политикой) и чинилась ровно так же — журналом, а не обещанием.

Т4: сеть здесь не открывается — `urlopen` подменяется. Т2: ожидаемое —
литералы. Ц2: файл новый.
"""

from __future__ import annotations

import json
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest import mock

from studio.mcp import advice, probe

ОТВЕТ_ПРЕДЕЛА = json.dumps({"message": "duration must be between 5 and 10"}).encode()


def _журнал() -> Path:
    return Path(tempfile.mkdtemp()) / "probes.jsonl"


class ЗондЗаписываетСебя(unittest.TestCase):
    def test_состоявшийся_зонд_оставляет_строку(self) -> None:
        путь = _журнал()
        ошибка = urllib.error.HTTPError(
            "https://api.klingai.com/v1/videos", 400, "Bad Request", Message(), None
        )
        ошибка.read = lambda *_: ОТВЕТ_ПРЕДЕЛА  # type: ignore[method-assign]
        with (
            mock.patch.object(probe, "PROBES_PATH", путь),
            mock.patch.object(probe.credentials, "find", return_value=("ключ", "KLING_KEY")),
            mock.patch("urllib.request.urlopen", side_effect=ошибка),
        ):
            итог = probe.probe_limit("https://api.klingai.com/v1/videos", "duration", 1_000_000)
            self.assertEqual("pass", итог["outcome"], итог)
            self.assertTrue(probe.зонд_был("https://api.klingai.com/other/path", journal=путь))

        строки = [json.loads(с) for с in путь.read_text(encoding="utf-8").splitlines() if с]
        self.assertEqual(1, len(строки))
        self.assertEqual("api.klingai.com", строки[0]["host"])
        self.assertEqual("duration", строки[0]["field"])
        self.assertEqual(400, строки[0]["status"])

    def test_записывается_контакт_а_не_вердикт(self) -> None:
        """401 про ключ — предела из него не следует, но зонд СОСТОЯЛСЯ.

        И5: если бы журнал писался только на измеряющих кодах, он отвечал бы
        на другой вопрос, чем тот, ради которого заведён.
        """
        путь = _журнал()
        ошибка = urllib.error.HTTPError(
            "https://api.fal.ai/v1/x", 401, "Unauthorized", Message(), None
        )
        ошибка.read = lambda *_: b'{"detail":"invalid api key"}'  # type: ignore[method-assign]
        with (
            mock.patch.object(probe, "PROBES_PATH", путь),
            mock.patch.object(probe.credentials, "find", return_value=("ключ", "FAL_KEY")),
            mock.patch("urllib.request.urlopen", side_effect=ошибка),
        ):
            итог = probe.probe_limit("https://api.fal.ai/v1/x", "width", 1_000_000)
            self.assertEqual("could not measure", итог["outcome"], итог)
            self.assertIsNone(итог["suggested_fact"])
        self.assertTrue(probe.зонд_был("https://api.fal.ai/v1/x", journal=путь))

    def test_несостоявшийся_зонд_строки_не_оставляет(self) -> None:
        """Вторая сторона (И5): без ключа запрос не уходит — и журнал пуст."""
        путь = _журнал()
        with (
            mock.patch.object(probe, "PROBES_PATH", путь),
            mock.patch.object(probe.credentials, "find", return_value=("", "")),
        ):
            итог = probe.probe_limit("https://api.klingai.com/v1/x", "duration", 1_000_000)
            self.assertEqual("could not measure", итог["outcome"])
        self.assertFalse(путь.exists())
        self.assertFalse(probe.зонд_был("https://api.klingai.com/v1/x", journal=путь))


class ЗаявкаНаЗондСверяетсяСЖурналом(unittest.TestCase):
    """Е2: при расхождении заявки и свидетельства верим свидетельству —
    но факт при этом НЕ теряется."""

    def _записать(self, был_зонд: bool) -> dict:
        база = Path(tempfile.mkdtemp()) / "facts.jsonl"
        база.write_text("", encoding="utf-8")
        with mock.patch.object(probe, "зонд_был", return_value=был_зонд):
            return advice.record(
                "kling-3.0",
                "max_seconds",
                "10 s",
                "https://api.klingai.com/v1/videos",
                "probe",
                "2026-09-01",
                path=база,
            )

    def test_без_журнала_строка_пишется_но_помечена(self) -> None:
        итог = self._записать(был_зонд=False)
        self.assertEqual("pass", итог["outcome"])
        self.assertIn("ЗОНДА В ЖУРНАЛЕ НЕТ", str(итог["written"]["note"]))

    def test_с_журналом_пометки_нет(self) -> None:
        итог = self._записать(был_зонд=True)
        self.assertEqual("pass", итог["outcome"])
        self.assertNotIn("ЗОНДА В ЖУРНАЛЕ НЕТ", str(итог["written"]["note"]))

    def test_другие_тиры_журнал_не_спрашивают(self) -> None:
        """Пометка про зонд на вендорской строке была бы неправдой о ней."""
        база = Path(tempfile.mkdtemp()) / "facts.jsonl"
        база.write_text("", encoding="utf-8")
        with mock.patch.object(probe, "зонд_был", return_value=False):
            итог = advice.record(
                "kling-3.0",
                "max_seconds",
                "10 s",
                "https://docs.qingque.cn/x",
                "blog",
                "2026-09-01",
                path=база,
            )
        self.assertEqual("pass", итог["outcome"], итог)
        self.assertNotIn("ЗОНДА В ЖУРНАЛЕ НЕТ", str(итог["written"]["note"]))


if __name__ == "__main__":
    unittest.main()
