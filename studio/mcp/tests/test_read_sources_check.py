"""Сверка прохода чтения: что она обязана ловить после сужения 2026-09-02.

Сверка сравнивала НОТЫ побуквенно и объявляла расхождением всякое честное
уточнение. Живой случай: строку `civitai-api.licence` отозвали как
«устаревшую», это оказалось ошибкой, её восстановили — и в новой ноте
записали эту историю. Чтение при этом никуда не делось: то же значение, тот же
URL, `read_directly` по-прежнему True.

Сужение опасно ровно тем, что гейт может перестать ловить настоящее. Поэтому
здесь на КАЖДЫЙ случай, который он обязан ловить, стоит свой тест, и рядом —
тот единственный, на котором он теперь молчит. Сети нет (Т4), ожидаемое —
литералы (Т2).
"""

from __future__ import annotations

import importlib.util
import io
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

from studio.selfrag.facts import Fact, claim_key

SPEC = importlib.util.spec_from_file_location(
    "read_sources", Path(__file__).resolve().parents[3] / "scripts" / "read_sources.py"
)
assert SPEC and SPEC.loader
rs = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rs)

ЧТЕНИЕ = {
    "model": "тест-модель",
    "attribute": "license",
    "value": "apache-2.0",
    "source_url": "https://vendor.test/license",
    "read_directly": True,
    "note": "прочитано первым лицом 2026-09-02",
}


def факт(**правки: object) -> Fact:
    поля = {
        "model": "тест-модель",
        "attribute": "license",
        "value": "apache-2.0",
        "source_url": "https://vendor.test/license",
        "tier": "vendor",
        "stated_on": "2026-09-02",
        "read_directly": True,
        "note": "прочитано первым лицом 2026-09-02",
    }
    поля.update(правки)
    return Fact(**поля)  # type: ignore[arg-type]


def прогнать(факты: list[Fact]) -> tuple[int, str]:
    """Сверка на подставленной базе. Возвращает (код возврата, что напечатано)."""
    стоящие = {
        claim_key(f.model, rs._canonical_attribute(f.attribute), f.value, f.source_url): f
        for f in факты
    }
    буфер = io.StringIO()
    with mock.patch.object(rs, "READINGS", [ЧТЕНИЕ]), mock.patch.object(rs, "WITHDRAWN", []):
        with mock.patch.object(rs, "_standing", lambda: стоящие):
            with redirect_stdout(буфер):
                код = rs.check()
    return код, буфер.getvalue()


class ЧтоСверкаОбязанаЛовить(unittest.TestCase):
    def test_чтение_исчезло_из_базы(self):
        код, напечатано = прогнать([факт(value="cc-by-nc-4.0")])
        self.assertEqual(код, 1)
        self.assertIn("not recorded", напечатано)

    def test_отметка_о_чтении_съехала(self):
        """Самое дорогое: строка на месте, но «прочитано» стало «не прочитано»."""
        код, напечатано = прогнать([факт(read_directly=False)])
        self.assertEqual(код, 1)
        self.assertIn("отметка о чтении съехала", напечатано)

    def test_нота_исчезла_совсем(self):
        код, напечатано = прогнать([факт(note="")])
        self.assertEqual(код, 1)
        self.assertIn("нота исчезла", напечатано)

    def test_база_пуста(self):
        """Р1: нечего сверять — это не успех."""
        код, напечатано = прогнать([])
        self.assertEqual(код, 1)
        self.assertIn("не смогли", напечатано)


class НаЧёмСверкаТеперьМолчит(unittest.TestCase):
    def test_уточнённая_нота_нарушением_не_считается(self):
        код, напечатано = прогнать(
            [факт(note="восстановлено 2026-09-02: строка была отозвана по ошибке")]
        )
        self.assertEqual(код, 0)
        self.assertIn("расхождений 0", напечатано)

    def test_но_расхождение_всё_равно_печатается(self):
        """Молчать о нём нельзя: человек должен видеть, что текст разошёлся."""
        _, напечатано = прогнать([факт(note="другая нота")])
        self.assertIn("нота уточнена (не нарушение)", напечатано)

    def test_совпавшая_нота_ничего_не_печатает(self):
        код, напечатано = прогнать([факт()])
        self.assertEqual(код, 0)
        self.assertNotIn("нота уточнена", напечатано)


if __name__ == "__main__":
    unittest.main()
