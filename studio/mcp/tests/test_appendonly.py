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

    def test_на_каждой_форме_нарушения_прибор_шевелится(self):
        """Половина негативного контроля (И5), на ФИКСТУРАХ, а не на истории.

        История сюда не годится: CI клонирует с `fetch-depth: 1`, её там нет
        вовсе, и опиравшийся на неё контроль был зелёным локально и красным в
        CI. Прибор обязан проверяться тем, что есть в любом окружении.
        """
        self.assertEqual(len(ao.ФОРМЫ_НАРУШЕНИЙ), 6)
        for имя, было, стало, строка in ao.ФОРМЫ_НАРУШЕНИЙ:
            self.assertEqual(
                ao.первое_расхождение(list(было), list(стало)), строка, f"форма: {имя}"
            )

    def test_на_каждой_здоровой_форме_прибор_молчит(self):
        """Вторая половина: без неё прошёл бы прибор, кричащий на всё."""
        self.assertEqual(len(ao.ФОРМЫ_БЕЗ_НАРУШЕНИЙ), 4)
        for имя, было, стало in ao.ФОРМЫ_БЕЗ_НАРУШЕНИЙ:
            self.assertEqual(ao.первое_расхождение(list(было), list(стало)), 0, f"форма: {имя}")

    def test_известные_нарушения_выписаны_и_находятся_там_где_история_есть(self):
        """ИЗМЕРЕННЫЕ нарушения (И6). Без истории — ТРЕТИЙ исход, а не провал.

        Мелкий клон — не «нарушения не было», а «посмотреть было нечем» (Р1).
        """
        self.assertEqual(len(ao.ИЗВЕСТНЫЕ_НАРУШЕНИЯ), 4)
        for path, коммит, строка, _ in ao.ИЗВЕСТНЫЕ_НАРУШЕНИЯ:
            if not ao.строки_в_ревизии(path, f"{коммит}~1"):
                continue  # истории нет: этот исход проверяется тестом ниже
            свои = [
                ш
                for ш in ao.сверить_историю(path, floor=f"{коммит}~1")
                if ш.outcome == FAIL_ and коммит in ш.почему
            ]
            self.assertTrue(свои, f"{path}@{коммит} не найдено")
            self.assertEqual(свои[0].первая_разошедшаяся, строка)

    def test_без_истории_это_третий_исход_а_не_успех(self):
        """Пустой обход не сворачивается ни в годно, ни в не годно."""
        корень, _ = _репо(["a"], ["a"])
        self.assertEqual(ao.сверить_историю("нет-такого.jsonl", floor="", repo=корень), [])
        self.assertEqual(ao.вердикт([])["outcome"], UNMEASURED_)

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


def _репо_со_слиянием(*, теряем: bool) -> tuple[Path, str]:
    """Две ветки дописывали журнал одновременно, потом их слили.

    Сети нет (Т4), это настоящий git во временном каталоге. Возвращает корень и
    коммит-пол — тот, от которого разошлись ветки.
    """
    корень = Path(tempfile.mkdtemp())
    журнал = корень / "log.jsonl"

    def git(*args: str) -> str:
        return subprocess.run(
            ["git", *args], cwd=корень, check=True, capture_output=True, text=True
        ).stdout.strip()

    git("init", "-q")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    журнал.write_text("общая-1\nобщая-2\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "общее")
    пол = git("rev-parse", "HEAD")

    журнал.write_text("общая-1\nобщая-2\nмоя-3\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "моя ветка")
    моя = git("rev-parse", "HEAD")

    git("checkout", "-q", "-b", "чужая", пол)
    журнал.write_text("общая-1\nобщая-2\nчужая-3\n", encoding="utf-8")
    git("add", "-A")
    git("commit", "-qm", "чужая ветка")
    чужая = git("rev-parse", "HEAD")

    git("checkout", "-q", моя)
    # Слияние руками: конфликт в журнале решается человеком, и здесь
    # проверяется РЕЗУЛЬТАТ его решения, а не умение git его получить.
    итог = "общая-1\nобщая-2\nмоя-3\n" if теряем else "общая-1\nобщая-2\nмоя-3\nчужая-3\n"
    журнал.write_text(итог, encoding="utf-8")
    git("add", "-A")
    subprocess.run(
        ["git", "commit", "-qm", "слияние", "-p", моя, "-p", чужая],
        cwd=корень,
        capture_output=True,
    )
    if len(ao.родители("HEAD", repo=корень)) < 2:
        # Старый git не знает `commit -p`; собираем слияние через commit-tree.
        дерево = git("write-tree")
        слитый = git("commit-tree", дерево, "-p", моя, "-p", чужая, "-m", "слияние")
        git("reset", "-q", "--hard", слитый)
    return корень, пол


class Слияние(unittest.TestCase):
    """У слияния два родителя, и правило для него другое.

    Найдено 2026-09-02 на первом же слитом канале: обход истории сравнивал
    коммит с ПРЕДЫДУЩИМ В СПИСКЕ, а `git log --reverse` вытягивает в одну
    линию коммиты разных веток. Соседями оказались версии, которые друг друга
    никогда не видели, и гейт объявил нарушением то, что чужая ветка не
    продолжает мою — а она и не должна.
    """

    def test_слияние_сохранившее_обе_ветки_проходит(self):
        корень, пол = _репо_со_слиянием(теряем=False)
        шаги = ao.сверить_историю("log.jsonl", floor=пол, repo=корень)
        плохие = [ш for ш in шаги if ш.outcome == FAIL_]
        self.assertEqual([ш.почему for ш in плохие], [])

    def test_слияние_потерявшее_чужую_строку_краснеет(self):
        """Половина контроля, ради которой правило и ослаблено осторожно:
        порядок при слиянии меняться может, а пропажа — нет."""
        корень, пол = _репо_со_слиянием(теряем=True)
        шаги = ao.сверить_историю("log.jsonl", floor=пол, repo=корень)
        плохие = [ш for ш in шаги if ш.outcome == FAIL_]
        self.assertEqual(len(плохие), 1, [ш.почему for ш in шаги])
        self.assertIn("слияние потеряло", плохие[0].problems[0])

    def test_пропали_считает_только_исчезнувшее(self):
        """Т2: ожидаемое — литералы. Перестановка пропажей не считается."""
        self.assertEqual(ao.пропали(["a", "b"], ["b", "a"]), [])
        self.assertEqual(ao.пропали(["a", "b"], ["a"]), ["b"])
        self.assertEqual(ao.пропали(["a"], ["a", "b", "c"]), [])
        self.assertEqual(ao.пропали([], ["a"]), [])

    def test_у_обычного_коммита_родитель_один(self):
        корень, _ = _репо(["a"], ["a", "b"])
        subprocess.run(["git", "add", "-A"], cwd=корень, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-qm", "2"], cwd=корень, check=True, capture_output=True)
        self.assertEqual(len(ao.родители("HEAD", repo=корень)), 1)


class СравниваемСоСвоимРодителем(unittest.TestCase):
    """Дыра, найденная мутацией: сверять с ПОЛОМ вместо родителя.

    На прямой цепочке разницы нет, поэтому её не видел ни один тест. Разница
    появляется, когда переписан НЕ первый коммит после пола: строки пола
    остаются на месте, и сверка с полом такое нарушение пропускает.
    """

    def test_переписанный_второй_коммит_виден(self):
        корень = Path(tempfile.mkdtemp())
        журнал = корень / "log.jsonl"

        def git(*args: str) -> str:
            return subprocess.run(
                ["git", *args], cwd=корень, check=True, capture_output=True, text=True
            ).stdout.strip()

        git("init", "-q")
        git("config", "user.email", "t@t")
        git("config", "user.name", "t")
        журнал.write_text("пол-1\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", "пол")
        пол = git("rev-parse", "HEAD")

        журнал.write_text("пол-1\nвторая\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", "дописано")

        # Третий коммит выбрасывает строку ВТОРОГО. Строки пола целы, поэтому
        # сверка с полом молчит, а сверка с родителем обязана покраснеть.
        журнал.write_text("пол-1\nдругая\n", encoding="utf-8")
        git("add", "-A")
        git("commit", "-qm", "переписано")

        шаги = ao.сверить_историю("log.jsonl", floor=пол, repo=корень)
        плохие = [ш for ш in шаги if ш.outcome == FAIL_]
        self.assertEqual(len(плохие), 1, [ш.почему for ш in шаги])
        self.assertIn("переписан, а не дописан", плохие[0].почему)
