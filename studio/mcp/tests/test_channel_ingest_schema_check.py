"""Офлайновая проверка канала схем: связны ли уже записанные входы и выходы.

ЧТО СТОРОЖИТСЯ. Канал пишет об одном эндпоинте три строки, и они держатся друг
за друга: обязательные поля схемы лежат СРЕДИ её же свойств, поэтому «требует»
обязано быть подмножеством «принимает». Разъедься это — и планировщик получит
модель, которая требует вход, который она же, по базе, не принимает.

ПОЛ `ПОЛ_БЕЗ_ПРИНИМАЕТ` СТОРОЖИТСЯ В ОБЕ СТОРОНЫ (Т1): ровно на поле — годно,
на единицу выше — не смогли.

Ожидаемое — литералы (Т2), сети нет (Т4), фикстуры с обоих краёв (Т3): пустая
база, здоровая пара строк, порченые.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from studio.selfrag.facts import Fact

_SPEC = importlib.util.spec_from_file_location(
    "ingest_schema", Path(__file__).resolve().parents[3] / "scripts" / "ingest_schema.py"
)
assert _SPEC and _SPEC.loader
sc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(sc)

#: Моделей с «требует» и без «принимает», накопленных базой. Литерал (Т2).
ПОЛ = 44

АДРЕС = "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id={}"


def _факт(модель: str, атрибут: str, значение: str, **поверх) -> Fact:
    поля: dict[str, object] = {
        "model": модель,
        "attribute": атрибут,
        "value": значение,
        "source_url": АДРЕС.format(модель),
        "tier": "portal",
        "stated_on": "2026-09-03",
    }
    поля.update(поверх)
    return Fact(**поля)  # type: ignore[arg-type]  # DEBT(2026-09-07): фикстура строит Fact из словаря; типизировать — переписывать конструктор


class Проверка(unittest.TestCase):
    def test_ни_одной_строки_канала_это_не_смогли(self):
        итог = sc.проверить_собранное(факты=[])
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["checked"], 0)
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 1)

    def test_чужие_строки_не_считаются_своими(self):
        """Строка с другого хоста каналу не принадлежит и его не спасает."""
        чужая = Fact(
            model="m",
            attribute="accepts_inputs",
            value="текст",
            source_url="https://huggingface.co/m",
            tier="vendor",
            stated_on="2026-09-03",
        )
        итог = sc.проверить_собранное(факты=[чужая])
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["checked"], 0)

    def test_согласованная_пара_молчит(self):
        итог = sc.проверить_собранное(
            факты=[
                _факт("one", "accepts_inputs", "аудио, видео, текст"),
                _факт("one", "requires_inputs", "видео, текст"),
                _факт("one", "produces_outputs", "видео"),
            ]
        )
        self.assertEqual(итог["outcome"], "pass")
        self.assertEqual(итог["checked"], 3)
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 0)

    def test_требует_то_чего_не_принимает(self):
        итог = sc.проверить_собранное(
            факты=[
                _факт("one", "accepts_inputs", "текст"),
                _факт("one", "requires_inputs", "аудио, текст"),
            ]
        )
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)
        self.assertIn("аудио", итог["note"])

    def test_проза_вместо_вида(self):
        """В поле видов однажды уже приехала прозаическая оговорка."""
        итог = sc.проверить_собранное(
            факты=[
                _факт("one", "accepts_inputs", "только T2V (текст) и I2V — референсы «coming soon»")
            ]
        )
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_схема_не_становится_вендорским_утверждением(self):
        итог = sc.проверить_собранное(
            факты=[_факт("one", "accepts_inputs", "текст", tier="vendor")]
        )
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_строка_без_даты_источника(self):
        итог = sc.проверить_собранное(факты=[_факт("one", "accepts_inputs", "текст", stated_on="")])
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_ровно_на_поле_ещё_годно(self):
        факты = [_факт(f"m{н}", "requires_inputs", "текст") for н in range(ПОЛ)]
        факты.append(_факт("whole", "accepts_inputs", "текст"))
        факты.append(_факт("whole", "requires_inputs", "текст"))
        итог = sc.проверить_собранное(факты=факты)
        self.assertEqual(итог["outcome"], "pass")
        self.assertEqual(итог["unmeasured"], 44)
        self.assertEqual(итог["violations"], 0)

    def test_на_единицу_выше_пола_уже_не_смогли(self):
        факты = [_факт(f"m{н}", "requires_inputs", "текст") for н in range(ПОЛ + 1)]
        итог = sc.проверить_собранное(факты=факты)
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["unmeasured"], 45)
        self.assertEqual(итог["violations"], 0)


if __name__ == "__main__":
    unittest.main()
