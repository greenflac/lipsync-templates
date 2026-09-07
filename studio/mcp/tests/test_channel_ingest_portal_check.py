"""Офлайновая проверка канала портала: годно ли записанное с карточек fal.ai.

ЧТО СТОРОЖИТСЯ. Карточка площадки — это `portal`-тир и ничто иное: условия
ПЕРЕПРОДАЖИ, поданные как вендорское утверждение, дают ложный зелёный на Ц5,
который требует прочитать лицензию весов до встраивания. И цена без единой
цифры — это слова о цене, а не цена: разбор в число возьмёт из неё ничего.

ПОЛ `ПОЛ_БЕЗ_ЦЕНЫ` СТОРОЖИТСЯ В ОБЕ СТОРОНЫ (Т1). Модель без строки о цене —
это «цена НЕ ПОКАЗАНА» (портал прячет её флагом `hidePricing`), а не
«бесплатно»; накопленное печатается числом, рост уходит в третий исход.

Ожидаемое — литералы (Т2), сети нет (Т4), фикстуры с обоих краёв (Т3).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from studio.selfrag.facts import Fact

_SPEC = importlib.util.spec_from_file_location(
    "ingest_portal", Path(__file__).resolve().parents[3] / "scripts" / "ingest_portal.py"
)
assert _SPEC and _SPEC.loader
ip = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ip)

#: Моделей портала без единой строки о цене. Литерал (Т2).
ПОЛ = 21


def _факт(модель: str, атрибут: str, значение: str, **поверх) -> Fact:
    поля: dict[str, object] = {
        "model": модель,
        "attribute": атрибут,
        "value": значение,
        "source_url": f"https://fal.ai/models/vendor/{модель}",
        "tier": "portal",
        "stated_on": "2026-09-02",
    }
    поля.update(поверх)
    return Fact(**поля)  # type: ignore[arg-type]  # DEBT(2026-09-07): фикстура строит Fact из словаря; типизировать — переписывать конструктор


class Проверка(unittest.TestCase):
    def test_ни_одной_строки_канала_это_не_смогли(self):
        итог = ip.проверить_собранное(факты=[])
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["checked"], 0)
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 1)

    def test_строка_схемы_каналу_карточек_не_принадлежит(self):
        """Адрес OpenAPI — соседний канал, и его строки здесь не считаются."""
        чужая = Fact(
            model="one",
            attribute="accepts_inputs",
            value="текст",
            source_url="https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=one",
            tier="portal",
            stated_on="2026-09-03",
        )
        итог = ip.проверить_собранное(факты=[чужая])
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["checked"], 0)

    def test_здоровые_строки_молчат(self):
        итог = ip.проверить_собранное(
            факты=[
                _факт("one", "price_per_second_usd", "$0.07 per second of output video"),
                _факт("one", "positioning", "turns a still into a talking character"),
                _факт("one", "availability", "портал отметил модель deprecated"),
            ]
        )
        self.assertEqual(итог["outcome"], "pass")
        self.assertEqual(итог["checked"], 3)
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 0)

    def test_карточка_портала_в_вендорском_тире(self):
        итог = ip.проверить_собранное(
            факты=[_факт("one", "price_per_second_usd", "$0.07 per second", tier="vendor")]
        )
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_цена_без_единой_цифры(self):
        итог = ip.проверить_собранное(факты=[_факт("one", "price_per_second_usd", "по запросу")])
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_пустое_значение(self):
        итог = ip.проверить_собранное(факты=[_факт("one", "positioning", "   ")])
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_строка_без_даты_источника(self):
        итог = ip.проверить_собранное(
            факты=[_факт("one", "positioning", "talking character", stated_on="")]
        )
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_ровно_на_поле_ещё_годно(self):
        факты = [_факт(f"m{н}", "positioning", "модель без показанной цены") for н in range(ПОЛ)]
        факты.append(_факт("paid", "price_per_second_usd", "$0.07 per second"))
        итог = ip.проверить_собранное(факты=факты)
        self.assertEqual(итог["outcome"], "pass")
        self.assertEqual(итог["unmeasured"], 21)
        self.assertEqual(итог["violations"], 0)

    def test_на_единицу_выше_пола_уже_не_смогли(self):
        факты = [
            _факт(f"m{н}", "positioning", "модель без показанной цены") for н in range(ПОЛ + 1)
        ]
        итог = ip.проверить_собранное(факты=факты)
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["unmeasured"], 22)
        self.assertEqual(итог["violations"], 0)


if __name__ == "__main__":
    unittest.main()
