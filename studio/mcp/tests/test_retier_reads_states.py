"""Журнал отказов — журнал СОСТОЯНИЙ, а не список упоминаний.

ЗАЧЕМ. `scripts/retier_facts.py` обещает в шапке: «повторный прогон безопасен,
это чистая функция файла». Обещание не выполнялось: хосты собирались по ЛЮБОМУ
упоминанию в журнале, а строка `open` снимает прежний отказ.

ИЗМЕРЕНО 2026-09-06: в журнале 274 хоста, закрыты по последнему состоянию 210.
На живой базе это 1007 строк, которым повторный прогон поставил бы
`read_directly = False` ЗРЯ — то есть объявил бы прочитанное непрочитанным.

Тот же класс независимая проверка нашла накануне в собственном подсчёте и
записала числом: «закрыт» без учёта поздних проб завысил ответ в 983 раза.
Здесь он ВТОРЫМ местом (И7: нашёл дефект — грепни по его форме), и разбор
теперь один на весь проект (Е1).

Ожидаемое — литералы (Т2), сети нет (Т4).
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from studio.mcp import fetch

_SPEC = importlib.util.spec_from_file_location(
    "retier_facts", Path(__file__).resolve().parents[3] / "scripts" / "retier_facts.py"
)
assert _SPEC and _SPEC.loader
перетир = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(перетир)


def журнал(строки: list[dict]) -> Path:
    путь = Path(tempfile.mkdtemp()) / "denied_hosts.jsonl"
    путь.write_text(
        "".join(json.dumps(с, ensure_ascii=False) + "\n" for с in строки), encoding="utf-8"
    )
    return путь


class ПоследнееСостояниеПобеждаетПрежнее(unittest.TestCase):
    def test_open_снимает_прежний_отказ(self):
        путь = журнал(
            [
                {"host": "открылся.test", "state": "refused"},
                {"host": "открылся.test", "state": "open"},
            ]
        )
        with mock.patch.object(fetch, "DENIED_PATH", путь):
            self.assertEqual({"открылся.test": "open"}, fetch.последние_состояния())
            self.assertFalse(fetch.закрыт_политикой("https://открылся.test/x"))

    def test_повторный_отказ_после_открытия_снова_закрывает(self):
        """Негативный контроль (И5): «последнее» значит последнее в обе
        стороны, иначе однажды открытый хост навсегда перестанет считаться
        закрытым, и заявка на доступ потеряет строку."""
        путь = журнал(
            [
                {"host": "качается.test", "state": "refused"},
                {"host": "качается.test", "state": "open"},
                {"host": "качается.test", "state": "refused"},
            ]
        )
        with mock.patch.object(fetch, "DENIED_PATH", путь):
            self.assertTrue(fetch.закрыт_политикой("https://качается.test/x"))

    def test_строка_без_состояния_считается_отказом(self):
        """Ранние строки журнала поля `state` не несли: отсутствие — это
        отказ, потому что журнал заводился именно отказами."""
        путь = журнал([{"host": "древний.test"}])
        with mock.patch.object(fetch, "DENIED_PATH", путь):
            self.assertTrue(fetch.закрыт_политикой("https://древний.test/x"))

    def test_битая_строка_не_ломает_разбор(self):
        путь = журнал([{"host": "целый.test", "state": "refused"}])
        путь.write_text(путь.read_text(encoding="utf-8") + "{битое\n", encoding="utf-8")
        with mock.patch.object(fetch, "DENIED_PATH", путь):
            self.assertTrue(fetch.закрыт_политикой("https://целый.test/x"))

    def test_нет_журнала_нет_состояний(self):
        with mock.patch.object(fetch, "DENIED_PATH", Path("/нет/такого.jsonl")):
            self.assertEqual({}, fetch.последние_состояния())
            self.assertFalse(fetch.закрыт_политикой("https://любой.test/x"))

    def test_живой_журнал_знает_и_открытые_и_закрытые(self):
        """Р2: числа рядом с вердиктом. Если бы открытых не было ни одного,
        разбор по состояниям был бы неотличим от разбора по упоминаниям, и
        этот тест ничего бы не сторожил."""
        состояния = fetch.последние_состояния()
        закрытых = sum(1 for с in состояния.values() if с == fetch.STATE_REFUSED)
        self.assertGreater(len(состояния), закрытых, "в живом журнале есть открытые хосты")
        self.assertGreater(закрытых, 0, "и закрытые тоже")


if __name__ == "__main__":
    unittest.main()


class РешениеПоСтрокеБезДискаИСети(unittest.TestCase):
    """`decide` — сердце перетирания, и до 2026-09-06 его не касался ни один тест.

    Модуль обещает в шапке: «повторный прогон безопасен, это ЧИСТАЯ функция
    файла плюс двух источников свидетельства». Обещание держится ровно этой
    функцией, а она жила без охраны: ступень-метод можно было начать
    перезаписывать по URL, а метку пересказа перестать опознавать, и оба
    прогона остались бы зелёными (ИЗМЕРЕНО подменой: OK и OK).
    """

    ВЕНДОР = "https://elevenlabs.io/docs/models"

    def строка(self, **поля) -> dict:
        сырьё = {
            "model": "eleven_v3",
            "attribute": "max_seconds",
            "value": "300",
            "source_url": self.ВЕНДОР,
            "tier": "blog",
            "stated_on": "2026-09-05",
            "note": "",
        }
        сырьё.update(поля)
        return сырьё

    def test_ступень_метода_не_перезаписывается_адресом(self):
        """Никакой URL не докажет, что API спрашивали или что метод опубликован.
        Ступени `probe`, `paper`, `benchmark` — слово записавшего, и переписать
        их по хосту значит решить за него, чем была его находка."""
        for ступень in ("probe", "paper", "benchmark"):
            итог = перетир.decide(self.строка(tier=ступень), set())
            self.assertEqual(ступень, итог["tier"], ступень)

    def test_ступень_личности_считается_по_адресу(self):
        """Негативный контроль (И5): иначе функция просто ничего не делает.
        Вендорский хост поднимает строку с `blog` до `vendor`."""
        итог = перетир.decide(self.строка(tier="blog"), set())
        self.assertEqual("vendor", итог["tier"])

    def test_зонд_считается_прочитанным(self):
        """API ответил нам — это и есть чтение."""
        итог = перетир.decide(self.строка(tier="probe"), set())
        self.assertIs(True, итог["read_directly"])

    def test_метка_пересказа_ставит_непрочитано(self):
        итог = перетир.decide(self.строка(note="Read via summary of the page"), set())
        self.assertIs(False, итог["read_directly"])

    def test_закрытый_хост_ставит_непрочитано(self):
        """В этом окружении такую страницу открыть было нечем."""
        итог = перетир.decide(self.строка(), {"elevenlabs.io"})
        self.assertIs(False, итог["read_directly"])

    def test_открытый_хост_флаг_не_трогает(self):
        """Не записано — не то же самое, что не прочитано: третий ответ (Р1).
        Именно этот случай стоил 1007 строк, объявленных непрочитанными зря."""
        итог = перетир.decide(self.строка(), set())
        self.assertIsNone(итог["read_directly"])

    def test_чужие_поля_строки_сохраняются(self):
        """Перетирание правит две графы и не смеет терять остальные."""
        итог = перетир.decide(self.строка(fix="что делать", witnessed="прогон"), set())
        self.assertEqual("что делать", итог["fix"])
        self.assertEqual("прогон", итог["witnessed"])
