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

import socket as _socket_модуль

from studio.mcp import advice, probe

#: Настоящий класс сокета, взятый ДО того, как раннер его подменит.
_НАСТОЯЩИЙ_СОКЕТ = (
    _socket_модуль.socket.__mro__[1]
    if _socket_модуль.socket.__name__ == "_БезСети"
    else _socket_модуль.socket
)

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
            # Прогон идёт под раннером, отобравшим сеть, и по этому признаку
            # `note_probe` записи НЕ делает — см. `test_под_раннером_журнал_не_пишется`.
            # Здесь проверяется само письмо, поэтому признак снимается явно.
            mock.patch.object(probe, "_под_тестами", return_value=False),
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
            mock.patch.object(probe, "_под_тестами", return_value=False),
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


class ЖурналНеПишетсяИзПодТестов(unittest.TestCase):
    """ВОСПРОИЗВЕДЕНО 2026-09-07, через несколько часов после заведения журнала.

    В живом `studio/knowledge/probes.jsonl` оказалось 526 строк: 462 к
    `api.vendor.test` и 68 к `api.klingai.com` — и НИ ОДНОЙ настоящей. Их
    написали тесты: `probe_limit` с подменённым `urlopen` доходит до записи
    так же, как настоящий вызов.

    Цена ровно та, против которой журнал и заводился: `зонд_был(
    "api.klingai.com")` отвечал True, то есть журнал ПОРУЧИЛСЯ за зонд,
    которого не было, и снял бы пометку с факта тира probe.
    """

    def test_под_раннером_журнал_не_пишется(self) -> None:
        путь = _журнал()
        ошибка = urllib.error.HTTPError(
            "https://api.klingai.com/v1/videos", 400, "Bad Request", Message(), None
        )
        ошибка.read = lambda *_: ОТВЕТ_ПРЕДЕЛА  # type: ignore[method-assign]

        class _БезСети(_socket_модуль.socket):  # имя ровно то, что ставит раннер
            pass

        with (
            mock.patch.object(probe, "PROBES_PATH", путь),
            # ПРИЗНАК СТАВИТСЯ ЗДЕСЬ, А НЕ БЕРЁТСЯ ИЗ ОКРУЖЕНИЯ: иначе тест
            # проверял бы способ запуска — зелёный под `scripts/run_tests.py`
            # и красный под `python -m unittest`, — а не механизм.
            mock.patch.object(_socket_модуль, "socket", _БезСети),
            mock.patch.object(probe.credentials, "find", return_value=("ключ", "KLING_KEY")),
            mock.patch("urllib.request.urlopen", side_effect=ошибка),
        ):
            итог = probe.probe_limit("https://api.klingai.com/v1/videos", "duration", 1_000_000)
        self.assertEqual("pass", итог["outcome"], "измерение прибора остаётся прежним")
        self.assertFalse(путь.exists(), "записи о зонде, который не уходил, быть не должно")

    def test_признак_берётся_у_раннера_а_не_у_имени_файла(self) -> None:
        """Е2: верим свидетельству — сокет подменён, значит запрос не уходил.

        Проверяется МЕХАНИЗМ, а не окружение. Первая редакция утверждала
        `probe._под_тестами() is True` — и была бы красной при запуске
        `python -m unittest` напрямую, то есть отличала бы не дефект, а способ
        запуска. Обе стороны (И5): подменённый сокет — признак есть, настоящий
        — признака нет.
        """
        import socket

        class _БезСети(socket.socket):  # имя ровно то, что ставит раннер
            pass

        with mock.patch.object(socket, "socket", _БезСети):
            self.assertTrue(probe._под_тестами())
        # Второй признак — `unittest` в загруженных модулях — под тестами
        # истинен ВСЕГДА, и это правильно: он и заведён затем, что прямой
        # `python -m unittest` сокет не подменяет. Поэтому «признака нет»
        # проверяется на пустом наборе модулей, а не в этом процессе.
        with (
            mock.patch.object(socket, "socket", _НАСТОЯЩИЙ_СОКЕТ),
            mock.patch.dict("sys.modules", {}, clear=False),
        ):
            import sys as _sys

            без_unittest = {и: м for и, м in _sys.modules.items() if not и.startswith("unittest")}
            with mock.patch.object(_sys, "modules", без_unittest):
                self.assertFalse(probe._под_тестами())


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


class ДвеПометкиНеЗатираютДругДруга(unittest.TestCase):
    """Найдено приёмкой 2026-09-07: пометка про чтение стояла через `=`, а не
    `+=`, и затирала пометку про зонд — ровно в самом подозрительном
    сочетании, где заявлены И зонд, И чтение закрытого политикой хоста.
    Читатель базы видел одну претензию из двух.
    """

    def _записать(self) -> dict:
        база = Path(tempfile.mkdtemp()) / "facts.jsonl"
        база.write_text("", encoding="utf-8")
        журнал = Path(tempfile.mkdtemp()) / "denied.jsonl"
        журнал.write_text(
            json.dumps(
                {
                    "host": "the-decoder.com",
                    "url": "https://the-decoder.com/",
                    "reason": "Tunnel connection failed: 403",
                    "why_wanted": "нужен предел",
                    "incidental": False,
                    "state": "refused",
                    "first_seen": "2026-09-01",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        with (
            mock.patch.object(probe, "зонд_был", return_value=False),
            mock.patch.object(advice.fetch, "DENIED_PATH", журнал),
        ):
            return advice.record(
                "sora-2",
                "max_seconds",
                "12 s",
                "https://the-decoder.com/api",
                "probe",
                "2026-09-01",
                read_directly=True,
                path=база,
            )

    def test_обе_пометки_стоят_в_записи(self) -> None:
        нота = str(self._записать()["written"]["note"])
        self.assertIn("ЗОНДА В ЖУРНАЛЕ НЕТ", нота)
        self.assertIn("ЗАЯВЛЕНО ЧТЕНИЕ", нота)

    def test_пометка_доезжает_до_записавшего(self) -> None:
        """Пометка, живущая только в файле, не видна тому, кто записал, — и
        поправить он её не может."""
        self.assertIn("ПОМЕТКА К ЭТОЙ ЗАПИСИ", self._записать()["note"])


if __name__ == "__main__":
    unittest.main()
