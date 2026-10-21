"""Сохранность дерева при обрыве мутационного прогона.

ЗАЧЕМ ЭТИ ТЕСТЫ. 2026-09-04 рабочий процесс сессии был убит сигналом посреди
прогона мутаций. `finally`, который возвращает исходник на место, не исполнился,
и в дереве осталась подмена `цели_открыты = []` в `scripts/check_golden.py` —
прибор, считающий регрессы голден-сета, молча перестал их считать. Гейт при
этом был ЗЕЛЁНЫМ: изувечили ровно того, кто должен был бы возмутиться. Заметил
`git diff`, а не проверка.

Т2: ожидаемое — литералы. Т4: сети здесь нет и быть не может.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import tempfile
import unittest
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[3]


def _модуль():
    сп = importlib.util.spec_from_file_location(
        "mutate_channels", КОРЕНЬ / "scripts" / "mutate_channels.py"
    )
    м = importlib.util.module_from_spec(сп)
    assert сп.loader is not None
    сп.loader.exec_module(м)
    return м


m = _модуль()

#: Файл-жертва берётся НЕ из репозитория: тест, который правит настоящий
#: исходник, повторил бы ровно ту аварию, от которой сторожит.
#: Имя нарочно несёт двойное подчёркивание: первая редакция кодировала путь
#: заменой `/` на `__`, и обратная замена превращала такой путь в ЧУЖОЙ —
#: возврат писал бы файл не туда. Поймано этим тестом до коммита.
ЖЕРТВА = "studio/mcp/tests/__не_существует__.py"


class СлепокПереживаетОбрыв(unittest.TestCase):
    def setUp(self) -> None:
        # КАТАЛОГ СЛЕПКОВ — СВОЙ, ВРЕМЕННЫЙ, А НЕ ЖИВОЙ (исправлено 2026-09-05).
        #
        # ВОСПРОИЗВЕДЕНО: гейт прервался посреди мутаций, в живом
        # `.mutate.backup` остался слепок `scripts/check_golden.py`, и
        # `test_без_слепков_возвращать_нечего` покраснел — не потому, что
        # механизм сломан, а потому, что тест смотрел на состояние ДЕРЕВА.
        # Хуже того, он при этом ВОССТАНАВЛИВАЛ чужой файл посреди чужого
        # прогона: тест, который лечит дерево, — это второй мутатор, о котором
        # никто не просил.
        каталог = Path(tempfile.mkdtemp())
        живой = m.СЛЕПОК
        m.СЛЕПОК = каталог
        self.addCleanup(lambda: setattr(m, "СЛЕПОК", живой))
        self.addCleanup(lambda: shutil.rmtree(каталог, ignore_errors=True))
        self.путь = КОРЕНЬ / ЖЕРТВА
        self.addCleanup(lambda: self.путь.unlink(missing_ok=True))
        self.addCleanup(lambda: m.забыть(ЖЕРТВА))

    def test_слепок_возвращает_изувеченный_файл(self) -> None:
        self.путь.write_text("ПОРОГ = 5\n", encoding="utf-8")
        m.отложить(ЖЕРТВА, "ПОРОГ = 5\n")
        self.путь.write_text("ПОРОГ = 0\n", encoding="utf-8")

        вернули = m.вернуть_недовосстановленное()

        self.assertEqual([ЖЕРТВА], вернули)
        self.assertEqual("ПОРОГ = 5\n", self.путь.read_text(encoding="utf-8"))

    def test_возврат_называет_файлы_вслух(self) -> None:
        """Молча восстановить почти так же плохо: следующий читатель не узнает,
        что дерево побывало изувеченным."""
        self.путь.write_text("x = 1\n", encoding="utf-8")
        m.отложить(ЖЕРТВА, "x = 1\n")
        self.assertIn(ЖЕРТВА, m.вернуть_недовосстановленное())

    def test_без_слепков_возвращать_нечего(self) -> None:
        self.assertEqual([], m.вернуть_недовосстановленное())

    def test_слепок_убирается_после_удачного_возврата(self) -> None:
        self.путь.write_text("y = 2\n", encoding="utf-8")
        m.отложить(ЖЕРТВА, "y = 2\n")
        m.вернуть_недовосстановленное()
        self.assertEqual([], m.вернуть_недовосстановленное())


class ЗамокОтЖивого(unittest.TestCase):
    """Замок обязан держать ЖИВОЙ прогон и не держать покойника."""

    def setUp(self) -> None:
        self.addCleanup(lambda: m.ЗАМОК.unlink(missing_ok=True))

    def test_свой_живой_pid_считается_занятым(self) -> None:
        m.ЗАМОК.write_text(f"pid {os.getpid()}", encoding="utf-8")
        self.assertNotEqual("", m._занято())

    def test_мёртвый_pid_замком_не_считается(self) -> None:
        """Оборванный прогон оставлял замок навсегда, и следующий запуск
        отказывался работать, пока человек не снимет файл руками."""
        m.ЗАМОК.write_text("pid 999999999", encoding="utf-8")
        self.assertEqual("", m._занято())
        self.assertFalse(m.ЗАМОК.exists(), "мёртвый замок обязан сниматься сам")


if __name__ == "__main__":
    unittest.main()
