"""Сторож журналов: прибор обязан краснеть на правке и молчать на дописывании.

Ожидаемые значения здесь — ЛИТЕРАЛЫ, а не импорт из проверяемого модуля (Т2):
импортированное поехало бы вместе с кодом и промолчало. Сети нет (Т4).
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from studio import appendonly as ao

PASS_ = "pass"
FAIL_ = "fail"
UNMEASURED_ = "could not measure"


class ПервоеРасхождение(unittest.TestCase):
    """Фикстуры с ОБОИХ краёв диапазона и из середины (Т3)."""

    def test_дописывание_в_конец_расхождения_не_даёт(self):
        self.assertEqual(ao.первое_расхождение(["a", "b"], ["a", "b", "c"]), 0)

    def test_прежнее_повторено_точь_в_точь(self):
        self.assertEqual(ao.первое_расхождение(["a", "b"], ["a", "b"]), 0)

    def test_пустое_прежнее_проходит_всегда(self):
        self.assertEqual(ao.первое_расхождение([], ["a"]), 0)

    def test_правка_первой_строки(self):
        self.assertEqual(ao.первое_расхождение(["a", "b", "c"], ["X", "b", "c"]), 1)

    def test_правка_в_середине(self):
        self.assertEqual(ao.первое_расхождение(["a", "b", "c"], ["a", "X", "c"]), 2)

    def test_правка_последней_строки(self):
        self.assertEqual(ao.первое_расхождение(["a", "b", "c"], ["a", "b", "X"]), 3)

    def test_удаление_последней_строки(self):
        self.assertEqual(ao.первое_расхождение(["a", "b", "c"], ["a", "b"]), 3)

    def test_вставка_в_середину_ловится_как_правка(self):
        """Для журнала вставка и правка — одно: порядок утверждений изменился."""
        self.assertEqual(ao.первое_расхождение(["a", "b"], ["a", "X", "b"]), 2)

    def test_журнал_опустошён(self):
        self.assertEqual(ao.первое_расхождение(["a", "b"], []), 1)


def _репо(строки_1: list[str], строки_2: list[str] | None) -> tuple[Path, str]:
    """Настоящий git-репозиторий из двух коммитов. Сети тут нет (Т4)."""
    корень = Path(tempfile.mkdtemp())
    журнал = корень / "log.jsonl"
    for cmd in (
        ["git", "init", "-q"],
        ["git", "config", "user.email", "t@t"],
        ["git", "config", "user.name", "t"],
    ):
        subprocess.run(cmd, cwd=корень, check=True, capture_output=True)
    журнал.write_text("\n".join(строки_1) + "\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=корень, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "1"], cwd=корень, check=True, capture_output=True)
    первый = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=корень, capture_output=True, text=True, check=True
    ).stdout.strip()
    if строки_2 is None:
        журнал.unlink()
    else:
        журнал.write_text("\n".join(строки_2) + "\n", encoding="utf-8")
    return корень, первый


class СверкаСДеревом(unittest.TestCase):
    def test_дописанный_журнал_проходит(self):
        корень, _ = _репо(["a", "b"], ["a", "b", "c"])
        с = ao.сверить("log.jsonl", rev="HEAD", repo=корень)
        self.assertEqual(с.outcome, PASS_)
        self.assertEqual(с.добавлено, 1)

    def test_правленый_журнал_краснеет_и_называет_строку(self):
        корень, _ = _репо(["a", "b", "c"], ["a", "X", "c"])
        с = ao.сверить("log.jsonl", rev="HEAD", repo=корень)
        self.assertEqual(с.outcome, FAIL_)
        self.assertEqual(с.первая_разошедшаяся, 2)
        self.assertEqual(len(с.problems), 1)

    def test_исчезнувший_журнал_это_удаление_всех_строк(self):
        корень, _ = _репо(["a", "b"], None)
        self.assertEqual(ao.сверить("log.jsonl", rev="HEAD", repo=корень).outcome, FAIL_)

    def test_журнала_в_ревизии_нет_это_третий_исход(self):
        """Не годно и не годно — разные вещи; несравнённое не сворачивается."""
        корень, _ = _репо(["a"], ["a"])
        с = ao.сверить("нет-такого.jsonl", rev="HEAD", repo=корень)
        self.assertEqual(с.outcome, UNMEASURED_)


class Вердикт(unittest.TestCase):
    def test_ноль_сверок_это_не_успех(self):
        """Р2: ноль нарушений при нуле проверок — третий исход, а не первый."""
        в = ao.вердикт([])
        self.assertEqual(в["outcome"], UNMEASURED_)
        self.assertEqual(в["checked"], 0)

    def test_все_журналы_несравнимы_это_тоже_третий_исход(self):
        в = ao.вердикт([ao.Сверка(path="x", outcome=UNMEASURED_)])
        self.assertEqual(в["outcome"], UNMEASURED_)
        self.assertEqual(в["unmeasured"], 1)

    def test_одна_беда_красит_весь_вердикт(self):
        в = ao.вердикт(
            [
                ao.Сверка(path="x", outcome=PASS_, добавлено=3),
                ao.Сверка(path="y", outcome=FAIL_, problems=["y: строка 2"]),
            ]
        )
        self.assertEqual(в["outcome"], FAIL_)
        self.assertEqual(в["violations"], 1)
        self.assertEqual(в["checked"], 2)


class ИсторияИКонтроль(unittest.TestCase):
    def test_коммит_переписавший_журнал_ловится_обходом_истории(self):
        """Сверки с HEAD мало: переписавший коммит сам становится HEAD."""
        корень, первый = _репо(["a", "b", "c"], ["a", "X", "c"])
        subprocess.run(["git", "add", "-A"], cwd=корень, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "2"], cwd=корень, check=True, capture_output=True)
        с_деревом = ao.сверить("log.jsonl", rev="HEAD", repo=корень)
        self.assertEqual(с_деревом.outcome, PASS_)  # дерево и HEAD совпали
        шаги = ao.сверить_историю("log.jsonl", floor=первый, repo=корень)
        self.assertEqual([ш.outcome for ш in шаги], [FAIL_])
        self.assertEqual(шаги[0].первая_разошедшаяся, 2)

    def test_известные_нарушения_выписаны_и_прибор_их_находит(self):
        """Половина негативного контроля: прибор обязан шевельнуться (И5)."""
        self.assertEqual(len(ao.ИЗВЕСТНЫЕ_НАРУШЕНИЯ), 4)
        for path, коммит, строка, _ in ao.ИЗВЕСТНЫЕ_НАРУШЕНИЯ:
            шаги = ao.сверить_историю(path, floor=f"{коммит}~1")
            свои = [ш for ш in шаги if ш.outcome == FAIL_ and коммит in ш.почему]
            self.assertTrue(свои, f"{path}@{коммит} не найдено")
            self.assertEqual(свои[0].первая_разошедшаяся, строка)

    def test_на_чистом_журнале_прибор_молчит(self):
        """Вторая половина: прибор обязан сказать «нет» там, где нечего искать."""
        шаги = ao.сверить_историю(
            ao.ЧИСТЫЙ_ЖУРНАЛ, floor=ao.коммиты_по(ao.ЧИСТЫЙ_ЖУРНАЛ, floor="")[0]
        )
        self.assertEqual([ш for ш in шаги if ш.outcome == FAIL_], [])

    def test_пол_не_входит_в_обход(self):
        корень, первый = _репо(["a"], ["a", "b"])
        subprocess.run(["git", "add", "-A"], cwd=корень, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "2"], cwd=корень, check=True, capture_output=True)
        self.assertEqual(len(ao.коммиты_по("log.jsonl", floor=первый, repo=корень)), 1)

    def test_список_журналов_не_пуст_и_назван_поимённо(self):
        self.assertEqual(len(ao.ЖУРНАЛЫ), 4)
        self.assertIn("studio/knowledge/misses.jsonl", ao.ЖУРНАЛЫ)
        self.assertIn("studio/knowledge/model_facts.jsonl", ao.ЖУРНАЛЫ)


if __name__ == "__main__":
    unittest.main()
