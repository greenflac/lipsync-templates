"""Офлайновая проверка канала индексов: цела ли ИЗВЕСТНАЯ сторона разницы.

ЧЕГО ЭТА ПРОВЕРКА НЕ ДЕЛАЕТ. Канал ничего своего на диск не кладёт: он печатает
разницу и забывает её. Значит офлайн проверяема ровно одна её сторона — та, что
лежит в репозитории. Сетевая сторона (индексы HuggingFace и PyPI) не проверена
здесь никак, и это сказано вслух и в скрипте, и в его выдаче.

ЧТО СТОРОЖИТСЯ. Разница считается вычитанием `кандидаты - известные`. Опустей
известная сторона — и КАЖДАЯ модель индекса прочитается как новая: канал
напечатает сотню находок, ни разу не сказав, что сравнивать было не с чем.
Это молча съехавший знаменатель, самый дорогой класс дефекта на этом проекте.

ПОЛ `ПОЛ_ИМЁН` СТОРОЖИТСЯ В ОБЕ СТОРОНЫ (Т1): 500 имён — годно, 499 — не смогли.

Ожидаемое — литералы (Т2), сети нет (Т4), фикстуры с обоих краёв (Т3).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from studio.selfrag.facts import Fact

_SPEC = importlib.util.spec_from_file_location(
    "discover_models", Path(__file__).resolve().parents[3] / "scripts" / "discover_models.py"
)
assert _SPEC and _SPEC.loader
dm = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(dm)

#: Пол на знаменатель разницы: сколько имён база обязана знать. Литерал (Т2).
ПОЛ = 500


def _факты(сколько: int) -> list[Fact]:
    """База из `сколько` РАЗНЫХ имён — по одному факту на каждое."""
    return [
        Fact(
            model=f"family-{н}",
            attribute="license",
            value="apache-2.0",
            source_url="https://huggingface.co/vendor/x",
            tier="vendor",
            stated_on="2026-09-01",
        )
        for н in range(сколько)
    ]


class Проверка(unittest.TestCase):
    def test_пустая_база_это_не_смогли(self):
        """Ноль известных имён — не «нового нет», а «сравнивать не с чем»."""
        итог = dm.проверить_собранное(факты=[], families=set())
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["checked"], 0)
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 1)

    def test_ровно_на_поле_ещё_годно(self):
        итог = dm.проверить_собранное(факты=_факты(ПОЛ), families={"wan", "flux"})
        self.assertEqual(итог["outcome"], "pass")
        self.assertEqual(итог["checked"], 502)
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 0)

    def test_на_единицу_ниже_пола_уже_не_смогли(self):
        итог = dm.проверить_собранное(факты=_факты(ПОЛ - 1), families={"wan", "flux"})
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["checked"], 501)
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 1)

    def test_два_семейства_сворачиваются_в_одно(self):
        """Новая модель второго семейства спряталась бы за первым."""
        итог = dm.проверить_собранное(факты=_факты(ПОЛ), families={"flux-2", "flux.2"})
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_разные_семейства_остаются_разными(self):
        """Негативный контроль с другой стороны (И5): прибор, кричащий на всё,
        ничего не различает."""
        итог = dm.проверить_собранное(
            факты=_факты(ПОЛ), families={"wan", "flux", "veo", "kling", "sora"}
        )
        self.assertEqual(итог["outcome"], "pass")
        self.assertEqual(итог["violations"], 0)

    def test_сетевая_сторона_названа_непроверенной(self):
        """Выдача обязана СКАЗАТЬ, чего она не измеряла (Ц4 на себя)."""
        итог = dm.проверить_собранное(факты=_факты(ПОЛ), families={"wan"})
        self.assertIn("НЕ проверена", итог["note"])


if __name__ == "__main__":
    unittest.main()
