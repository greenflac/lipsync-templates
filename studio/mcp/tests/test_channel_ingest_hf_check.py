"""Офлайновая проверка канала HuggingFace: тир решает URL — и после записи тоже.

ЧТО СТОРОЖИТСЯ. Шапка канала говорит «тир решает URL, а не этот скрипт», и до
2026-09-07 это никто не проверял ПОСЛЕ записи. А факт попадает в базу и мимо
`advice.record`: правкой файла, слиянием, переносом при канонизации имени.
Опыт практика из треда, поданный как вендорская спека, — это подмена
применимости способностью, ровно та, ради различения которой канал и заведён.
Лицензия, прочитанная в форуме, — не лицензия (Ц5).

ПОЛ `ПОЛ_ОГРАНИЧЕНИЙ_БЕЗ_ЛИЦЕНЗИИ` СТОРОЖИТСЯ В ОБЕ СТОРОНЫ (Т1).

Ожидаемое — литералы (Т2), сети нет (Т4), фикстуры с обоих краёв (Т3).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from studio.selfrag.facts import Fact

_SPEC = importlib.util.spec_from_file_location(
    "ingest_hf", Path(__file__).resolve().parents[3] / "scripts" / "ingest_hf.py"
)
assert _SPEC and _SPEC.loader
ih = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ih)

#: Моделей с ограничением лицензии и без самой лицензии. Литерал (Т2).
ПОЛ = 2

КАРТОЧКА = "https://huggingface.co/vendor/{}"
ТРЕД = "https://huggingface.co/vendor/{}/discussions/7"


def _карточка(модель: str, атрибут: str, значение: str, **поверх) -> Fact:
    поля: dict[str, object] = {
        "model": модель,
        "attribute": атрибут,
        "value": значение,
        "source_url": КАРТОЧКА.format(модель),
        "tier": "vendor",
        "stated_on": "2026-09-01",
    }
    поля.update(поверх)
    return Fact(**поля)  # type: ignore[arg-type]  # DEBT(2026-09-07): фикстура строит Fact из словаря; типизировать — переписывать конструктор


def _тред(модель: str, атрибут: str, значение: str, **поверх) -> Fact:
    поля: dict[str, object] = {
        "model": модель,
        "attribute": атрибут,
        "value": значение,
        "source_url": ТРЕД.format(модель),
        "tier": "blog",
        "stated_on": "2026-09-01",
    }
    поля.update(поверх)
    return Fact(**поля)  # type: ignore[arg-type]  # DEBT(2026-09-07): см. выше


class Проверка(unittest.TestCase):
    def test_ни_одной_строки_канала_это_не_смогли(self):
        итог = ih.проверить_собранное(факты=[])
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["checked"], 0)
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 1)

    def test_чужой_хост_каналу_не_принадлежит(self):
        чужая = Fact(
            model="one",
            attribute="license",
            value="apache-2.0",
            source_url="https://fal.ai/models/one",
            tier="portal",
            stated_on="2026-09-01",
        )
        итог = ih.проверить_собранное(факты=[чужая])
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["checked"], 0)

    def test_здоровые_строки_молчат(self):
        итог = ih.проверить_собранное(
            факты=[
                _карточка("one", "license", "apache-2.0"),
                _карточка("one", "adoption", "5 362 365 скачиваний на HuggingFace"),
                _тред("one", "failure_mode", "персонажи почти не моргают"),
            ]
        )
        self.assertEqual(итог["outcome"], "pass")
        self.assertEqual(итог["checked"], 3)
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 0)

    def test_тред_поданный_как_спека(self):
        итог = ih.проверить_собранное(
            факты=[_тред("one", "failure_mode", "мелкое лицо разваливается", tier="vendor")]
        )
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_карточка_поданная_как_форум(self):
        итог = ih.проверить_собранное(
            факты=[_карточка("one", "license", "apache-2.0", tier="blog")]
        )
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_лицензия_прочитанная_в_треде(self):
        """Ц5: лицензия читается на карточке, а не в чужой реплике."""
        итог = ih.проверить_собранное(факты=[_тред("one", "license", "apache-2.0")])
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_принятость_из_треда(self):
        итог = ih.проверить_собранное(
            факты=[_тред("one", "adoption", "у меня скачалось миллион раз")]
        )
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_строка_без_даты_источника(self):
        итог = ih.проверить_собранное(
            факты=[_карточка("one", "license", "apache-2.0", stated_on="")]
        )
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_ровно_на_поле_ещё_годно(self):
        факты = [_карточка(f"m{н}", "license_restriction", "нельзя в ЕС") for н in range(ПОЛ)]
        факты.append(_карточка("whole", "license", "apache-2.0"))
        факты.append(_карточка("whole", "license_restriction", "нельзя в ЕС"))
        итог = ih.проверить_собранное(факты=факты)
        self.assertEqual(итог["outcome"], "pass")
        self.assertEqual(итог["unmeasured"], 2)
        self.assertEqual(итог["violations"], 0)

    def test_на_единицу_выше_пола_уже_не_смогли(self):
        факты = [_карточка(f"m{н}", "license_restriction", "нельзя в ЕС") for н in range(ПОЛ + 1)]
        итог = ih.проверить_собранное(факты=факты)
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["unmeasured"], 3)
        self.assertEqual(итог["violations"], 0)


if __name__ == "__main__":
    unittest.main()
