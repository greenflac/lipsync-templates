"""Прибор, считающий модули без мутантов (R7), и его собственные сторожа.

Т2: ожидаемое — литералы. Числа и слова исходов написаны руками.

ЗАЧЕМ ТЕСТЫ НА СЧЁТЧИК ДОЛГА. Он печатает число, по которому принимают решение
о релизе, и ошибиться в нём легко в обе стороны: занизить (объявить долг
меньшим, чем он есть) и завысить (потребовать мутантов там, где ветвления нет).
Первое опаснее, поэтому и определение, и его границы проверяются здесь.
"""

from __future__ import annotations

import importlib.util
import unittest
import unittest.mock
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[3]


def _модуль():
    сп = importlib.util.spec_from_file_location(
        "check_mutants_cover", КОРЕНЬ / "scripts" / "check_mutants_cover.py"
    )
    м = importlib.util.module_from_spec(сп)
    assert сп.loader is not None
    сп.loader.exec_module(м)
    return м


c = _модуль()


class ЧтоСчитаетсяРешением(unittest.TestCase):
    def test_константа_в_условии_считается(self) -> None:
        исходник = "ПОРОГ = 5\n\n\ndef f(x):\n    if x > ПОРОГ:\n        return 1\n    return 0\n"
        self.assertEqual({"ПОРОГ"}, c.решающие_константы(исходник))

    def test_константа_без_сравнения_тоже_считается(self) -> None:
        """`if ФЛАГ:` — ветвление без сравнения, и оно решает не меньше.

        Дыра, найденная мутацией: первый тест писал `if x > ПОРОГ`, то есть
        внутри `if` стояло ещё и сравнение, и ветку `ast.If` можно было
        выключить незаметно — её работу делал сосед `ast.Compare`.
        """
        исходник = "ФЛАГ = True\n\n\ndef f():\n    if ФЛАГ:\n        return 1\n    return 0\n"
        self.assertEqual({"ФЛАГ"}, c.решающие_константы(исходник))

    def test_константа_в_сравнении_считается(self) -> None:
        исходник = "РЕЖИМ = 'a'\n\n\ndef f(x):\n    return x == РЕЖИМ\n"
        self.assertEqual({"РЕЖИМ"}, c.решающие_константы(исходник))

    def test_константа_в_проверке_вхождения_считается(self) -> None:
        исходник = "СПИСОК = ('a',)\n\n\ndef f(x):\n    return x in СПИСОК\n"
        self.assertEqual({"СПИСОК"}, c.решающие_константы(исходник))

    def test_таблица_данных_решением_НЕ_считается(self) -> None:
        """Граница определения. Иначе счётчик объявил бы долгом каждый словарь
        печати, и число перестало бы значить что-либо."""
        исходник = "ПОДПИСИ = {'a': 'А'}\n\n\ndef f(x):\n    return ПОДПИСИ[x]\n"
        self.assertEqual(set(), c.решающие_константы(исходник))

    def test_строчное_имя_не_считается(self) -> None:
        исходник = "порог = 5\n\n\ndef f(x):\n    if x > порог:\n        return 1\n    return 0\n"
        self.assertEqual(set(), c.решающие_константы(исходник))


class ЧитаемыеТаблицы(unittest.TestCase):
    def test_пути_читаются_из_таблиц_мутантов(self) -> None:
        пути = c.покрытые()
        self.assertIn("studio/planner.py", пути)
        self.assertIn("studio/pipeline.py", пути)

    def test_считаются_только_файлы_из_репозитория(self) -> None:
        """Знаменатель обязан совпадать с тем, что увидит CI.

        Потолок — число; посчитанное по рабочему дереву, оно включало бы файлы,
        которых у читателя нет, и ратчет краснел бы в CI на ровном месте. Тот
        же класс ошибки, что «13 316 промптов» на пустом клоне.
        """
        import subprocess

        из_гита = {
            с
            for с in subprocess.run(
                ["git", "ls-files", "studio", "lipsync", "scripts"],
                cwd=c.ROOT,
                capture_output=True,
                text=True,
            ).stdout.split()
            if с.endswith(".py")
        }
        self.assertTrue(из_гита, "git не ответил — проверка бессмысленна")
        лишние = [
            str(п.relative_to(c.ROOT))
            for п in c.модули()
            if str(п.relative_to(c.ROOT)) not in из_гита
        ]
        self.assertEqual([], лишние, "прибор считает файлы, которых нет в репозитории")

    def test_чужой_файл_в_дереве_в_знаменатель_НЕ_попадает(self) -> None:
        """И5: проверка выше молчит, пока в дереве нет лишних файлов.

        На чистом дереве отсутствие лишних верно ПО ПУСТОЙ ПРИЧИНЕ, и мутация
        «считать по дереву» её не красит. Поэтому лишний файл создаётся здесь —
        с константой-решением, чтобы он попал бы в счёт, если бы фильтра не
        было.
        """
        чужой = c.ROOT / "studio" / "__не_в_репозитории__.py"
        чужой.write_text(
            "ПОРОГ = 5\n\n\ndef f(x):\n    if x > ПОРОГ:\n        return 1\n    return 0\n",
            encoding="utf-8",
        )
        self.addCleanup(lambda: чужой.unlink(missing_ok=True))
        имена = [str(п.relative_to(c.ROOT)) for п in c.модули()]
        self.assertNotIn("studio/__не_в_репозитории__.py", имена)

    def test_счёт_идёт_по_живому_дереву(self) -> None:
        итог = c.свести()
        self.assertGreater(итог["checked"], 50, "модулей с решениями подозрительно мало")
        self.assertEqual(итог["checked"], итог["покрыто"] + итог["violations"])


#: ПОТОЛОК ЛИТЕРАЛОМ (Т2). Раньше эти тесты брали `c.ПОТОЛОК ± 1` — то есть
#: ожидаемое ехало вместе с проверяемым модулем и молчало бы, даже если бы
#: потолок подняли. Опустился ратчет — эта строка правится руками, и это
#: правильно: снижение потолка есть решение, а не побочный эффект.
ПОТОЛОК_ЛИТЕРАЛ = 37


class Потолок(unittest.TestCase):
    """Потолок обязан ловить РОСТ долга и требовать снижения при падении."""

    def _подменить(self, нарушений: int):
        итог = {
            "outcome": "pass" if нарушений == ПОТОЛОК_ЛИТЕРАЛ else "fail",
            "checked": 100,
            "violations": нарушений,
            "unmeasured": 0,
            "покрыто": 100 - нарушений,
            "непокрытые": [],
        }
        return unittest.mock.patch.object(c, "свести", lambda *а, **к: итог)

    def test_потолок_ровно_тридцать_семь(self) -> None:
        """Литерал (Т2): им же пользуются остальные тесты этого класса."""
        self.assertEqual(ПОТОЛОК_ЛИТЕРАЛ, c.ПОТОЛОК)

    def test_рост_долга_краснеет(self) -> None:
        with self._подменить(ПОТОЛОК_ЛИТЕРАЛ + 1):
            self.assertEqual(1, c.main(["--check"]))

    def test_долг_по_потолку_проходит(self) -> None:
        with self._подменить(ПОТОЛОК_ЛИТЕРАЛ):
            self.assertEqual(0, c.main(["--check"]))

    def test_упавший_долг_требует_опустить_потолок(self) -> None:
        """Иначе потолок отрывается от дерева и перестаёт ловить рост."""
        with self._подменить(ПОТОЛОК_ЛИТЕРАЛ - 1):
            self.assertEqual(1, c.main(["--check"]))


class ФлагСовпадаетСоСвидетельством(unittest.TestCase):
    """Е2: печатаемый исход и код возврата обязаны говорить одно и то же.

    Печаталось `fail` при долге ровно по потолку, а возвращался ноль. Читающий
    отчёт видел «fail» там, где гейт зелёный, и переставал верить обоим.
    """

    def test_долг_по_потолку_это_годно(self) -> None:
        итог = c.свести(потолок=None)
        свой = c.свести(потолок=итог["violations"])
        self.assertEqual("pass", свой["outcome"])

    def test_долг_выше_потолка_это_не_годно(self) -> None:
        """Негативный контроль (И5): исход, всегда равный `pass`, не исход."""
        итог = c.свести(потолок=None)
        свой = c.свести(потолок=итог["violations"] - 1)
        self.assertEqual("fail", свой["outcome"])


class НечегоСчитатьЭтоТретийИсход(unittest.TestCase):
    """Р2: ноль нарушений при нуле проверок — не успех.

    Дерево без индекса (свежая распаковка, worktree без checkout) отвечает на
    `git ls-files` нулём файлов с кодом 0. Прежний разбор фильтровал по этому
    ответу ВСЁ и печатал «проверено 0, нарушений 0» с зелёным гейтом.
    """

    def test_пустой_список_файлов_это_не_смогли(self) -> None:
        with unittest.mock.patch.object(c, "модули", lambda: []):
            итог = c.свести()
        self.assertEqual("could not measure", итог["outcome"])
        self.assertNotIn("violations", итог)

    def test_и_код_возврата_у_него_свой(self) -> None:
        """Третий исход не сворачивается ни в первый, ни во второй (Р1)."""
        with unittest.mock.patch.object(c, "модули", lambda: []):
            self.assertEqual(2, c.main(["--check"]))

    def test_пустой_ответ_git_не_принимается_за_ответ(self) -> None:
        class Пусто:
            returncode = 0
            stdout = "  \n"

        with unittest.mock.patch.object(c.subprocess, "run", lambda *а, **к: Пусто()):
            self.assertIsNone(c._в_репозитории())

    def test_настоящий_ответ_git_принимается(self) -> None:
        """Негативный контроль (И5) к предыдущему."""

        class Есть:
            returncode = 0
            stdout = "studio/app.py\nscripts/x.py\nREADME.md\n"

        with unittest.mock.patch.object(c.subprocess, "run", lambda *а, **к: Есть()):
            self.assertEqual({"studio/app.py", "scripts/x.py"}, c._в_репозитории())


if __name__ == "__main__":
    unittest.main()
