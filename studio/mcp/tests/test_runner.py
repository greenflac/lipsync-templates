"""Раннер тестов и его запрет сети (правило Т4, критерий R8).

Т2: ожидаемое — литералы. Слова исходов и адрес-заглушка написаны руками.

ЗАЧЕМ ТЕСТ НА ПРИБОР, КОТОРЫЙ ЗАПУСКАЕТ ТЕСТЫ. Запрет, который не установился,
выглядит как защита и ею не является — это худший исход из трёх. Проверяется он
здесь тем же способом, каким его проверяет сам раннер, но снаружи: функции
берутся из файла, а глобальные подмены не делаются, иначе тест испортил бы
прогон соседям.
"""

from __future__ import annotations

import importlib.util
import socket
import unittest
import unittest.mock
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[3]


def _модуль():
    сп = importlib.util.spec_from_file_location("run_tests", КОРЕНЬ / "scripts" / "run_tests.py")
    м = importlib.util.module_from_spec(сп)
    assert сп.loader is not None
    сп.loader.exec_module(м)
    return м


r = _модуль()

#: Адрес из RFC 5737 (TEST-NET-1): маршрутизировать его некуда, поэтому даже
#: при снятом запрете сюда не уйдёт настоящий трафик.
ЗАГЛУШКА = ("192.0.2.1", 80)


class ЗапретСети(unittest.TestCase):
    def test_соединение_отказано_и_причина_названа(self) -> None:
        с = r._БезСети(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(с.close)
        with self.assertRaises(AssertionError) as поймано:
            с.connect(ЗАГЛУШКА)
        self.assertIn("Т4", str(поймано.exception))
        self.assertIn("run_tests.py", str(поймано.exception))

    def test_connect_ex_тоже_закрыт(self) -> None:
        """Вторая дверь. `connect_ex` не бросает исключений по своей природе,
        поэтому забыть её — значит оставить проход, о котором никто не узнает."""
        с = r._БезСети(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(с.close)
        with self.assertRaises(AssertionError):
            с.connect_ex(ЗАГЛУШКА)

    def test_объект_сокета_всё_ещё_создаётся(self) -> None:
        """И5 с другой стороны: запрет обязан ШЕВЕЛИТЬСЯ, но не ломать импорты.

        Первая редакция подменяла сам класс функцией, и прогон рассыпался на 32
        ошибках импорта: `unittest.mock` тянет `asyncio`, а тот берёт у
        `socket.socket` атрибуты класса.
        """
        с = r._БезСети(socket.AF_INET, socket.SOCK_STREAM)
        self.addCleanup(с.close)
        self.assertTrue(hasattr(с, "fileno"))

    def test_негативный_контроль_видит_ОТКРЫТУЮ_сеть(self) -> None:
        """`сеть_закрыта` обязана вернуть «нет», когда соединение проходит.

        Настоящий сокет здесь НЕ ставится намеренно: адрес TEST-NET-1
        никуда не маршрутизируется, и проверка висела бы до таймаута — тест,
        который ждёт сеть, нарушает то самое правило, которое сторожит.
        Вместо этого подставляется сокет, у которого `connect` просто
        возвращает управление: это ровно тот случай, который прибор обязан
        назвать открытым.
        """

        # Базовый класс берётся из раннера через `getattr`, а не именем: имя
        # разрешается проверкой типов на этапе разбора, а тут оно приходит из
        # модуля, загруженного по пути. Поведение то же, вранья о типе нет.
        основа = getattr(r, "_НАСТОЯЩИЙ_СОКЕТ")

        class _Проходной(основа):  # type: ignore[misc,valid-type]
            def connect(self, *_а, **_к):
                return None

        было = socket.socket
        try:
            socket.socket = _Проходной  # type: ignore[misc]
            self.assertFalse(r.сеть_закрыта())
        finally:
            socket.socket = было  # type: ignore[misc]

    def test_негативный_контроль_видит_поставленный_запрет(self) -> None:
        настоящий_класс, настоящее_соединение = socket.socket, socket.create_connection
        try:
            r.запретить_сеть()
            self.assertTrue(r.сеть_закрыта())
        finally:
            socket.socket = настоящий_класс  # type: ignore[misc]
            socket.create_connection = настоящее_соединение


class ТриИсхода(unittest.TestCase):
    def test_каталога_нет_это_не_смогли_а_не_успех(self) -> None:
        self.assertEqual(2, r.main(["каталог/которого/нет"]))

    def test_неустановившийся_запрет_останавливает_прогон(self) -> None:
        """Мутант «выключить негативный контроль» промолчал, пока этого не было.

        Прибор обязан ОСТАНОВИТЬСЯ, а не пойти гонять тесты без запрета: молча
        снятая защита выглядит как защита, и это худший из трёх исходов.
        Каталог берётся настоящий — иначе проверка упёрлась бы в «нет
        каталога» и ничего бы не доказала.
        """
        настоящий_класс, настоящее_соединение = socket.socket, socket.create_connection
        звали: list[str] = []
        try:
            with unittest.mock.patch.object(r, "сеть_закрыта", lambda: False):
                with unittest.mock.patch.object(
                    r.unittest.defaultTestLoader,
                    "discover",
                    lambda *a, **k: звали.append("перебор"),
                ):
                    код = r.main(["studio/mcp/tests"])
        finally:
            socket.socket = настоящий_класс  # type: ignore[misc]
            socket.create_connection = настоящее_соединение
        self.assertEqual(1, код)
        self.assertEqual([], звали, "прогон пошёл дальше без установленного запрета")

    def test_каталог_не_назван_это_не_смогли(self) -> None:
        self.assertEqual(2, r.main([]))


if __name__ == "__main__":
    unittest.main()


class ПустойПрогонНеУспех(unittest.TestCase):
    """Ноль собранных тестов — третий исход, а не «OK».

    ВОСПРОИЗВЕДЕНО 2026-09-05 независимым аудитом: `wasSuccessful()` на пустом
    наборе отвечает True, раннер печатал «Ran 0 tests ... OK» и возвращал 0.
    Это тот самый дефект, ради которого раннер написан: «не запускалось»
    выглядело как «прошло». Достаточно переименовать файл набора в форму, о
    которой не знает `discover` (например `advice_checks.py`), — и тесты
    исчезают из прогона, никого не разбудив.
    """

    def test_каталог_без_тестов_это_не_смогли(self) -> None:
        import subprocess
        import sys
        import tempfile
        from pathlib import Path

        корень = Path(__file__).resolve().parents[3]
        пустой = Path(tempfile.mkdtemp(dir=корень)) / "пусто"
        пустой.mkdir()
        (пустой / "__init__.py").write_text("", encoding="utf-8")
        # Файл с тестом ЕСТЬ, но назван так, что discover его не подберёт —
        # ровно тот случай из аудита.
        (пустой / "проверки.py").write_text(
            "import unittest\n\n\nclass Т(unittest.TestCase):\n    def test_я_есть(self):\n        pass\n",
            encoding="utf-8",
        )
        self.addCleanup(lambda: __import__("shutil").rmtree(пустой.parent, ignore_errors=True))
        готово = subprocess.run(
            [sys.executable, "scripts/run_tests.py", str(пустой.relative_to(корень))],
            cwd=корень,
            capture_output=True,
            text=True,
        )
        self.assertEqual(готово.returncode, 2, готово.stdout + готово.stderr)
        self.assertIn("НИ ОДНОГО теста", готово.stdout + готово.stderr)
