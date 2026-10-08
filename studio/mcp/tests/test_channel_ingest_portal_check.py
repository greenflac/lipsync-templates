"""Офлайновая проверка канала портала: годно ли записанное с карточек fal.ai.

ЧТО СТОРОЖИТСЯ. Карточка площадки — это `portal`-тир и ничто иное: условия
ПЕРЕПРОДАЖИ, поданные как вендорское утверждение, дают ложный зелёный на Ц5,
который требует прочитать лицензию весов до встраивания. И цена, чьё ИМЯ
назвало единицу («за секунду»), обязана нести цифру: имя обещало разборщику
сумму. Голый `price` без цифры — не нарушение, а дословные слова площадки,
которые канал пишет сам.

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

    def test_названная_единица_без_цифры_это_нарушение(self):
        """Половина «прибор обязан сказать нет» (И5): имя обещало сумму."""
        итог = ip.проверить_собранное(факты=[_факт("one", "price_per_second_usd", "по запросу")])
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_названная_минута_без_цифры_это_тоже_нарушение(self):
        итог = ip.проверить_собранное(факты=[_факт("one", "price_per_minute", "по запросу")])
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    # ЛОЖНЫЙ ОТКАЗ, ВОСПРОИЗВЕДЁННЫЙ ПРИЁМКОЙ 2026-09-07. `заявки()` на записи
    # с `pricingInfoOverride = "Free while in beta"` отдаёт ровно
    # `('latentsync', 'price', 'Free while in beta', ...)` — канал пишет такие
    # строки САМ, дословными словами площадки, как велит его шапка, — а
    # проверка их браковала как «цену без единой цифры». Вторая половина
    # негативного контроля (И5): здесь прибор обязан промолчать.
    def test_слова_площадки_вместо_числа_это_не_нарушение(self):
        for текст in ("Free while in beta", "Contact us for pricing"):
            with self.subTest(текст=текст):
                итог = ip.проверить_собранное(факты=[_факт("one", "price", текст)])
                self.assertEqual(итог["outcome"], "pass")
                self.assertEqual(итог["violations"], 0)
                self.assertIn("словами без числа 1", итог["note"])

    def test_канал_пишет_ровно_то_что_проверка_принимает(self):
        """Е1/Е2: ожидание берётся из СОБРАННОГО каналом, а не из головы.

        Если однажды `заявки` начнёт давать таким ценам имя с единицей,
        проверка обязана назвать это нарушением — и тест покраснеет здесь.
        """
        заявка = ip.заявки(
            {"id": "fal-ai/latentsync", "pricingInfoOverride": "Free while in beta"}
        )[0]
        self.assertEqual(заявка[1], "price")
        итог = ip.проверить_собранное(факты=[_факт("latentsync", заявка[1], заявка[2])])
        self.assertEqual(итог["violations"], 0)

    # ПСЕВДО-МОДЕЛЬ ОБЛАСТИ ЗАВЫШАЛА ПОЛ. `fal.ai-*` — утверждение о КАТАЛОГЕ,
    # цены у него не бывает по построению, а в «моделях без цены» оно стояло
    # двадцать вторым и уводило живой прогон в третий исход.
    def test_область_портала_не_модель_и_в_пол_не_идёт(self):
        итог = ip.проверить_собранное(
            факты=[
                _факт(
                    ip.ОБЛАСТЬ_ПОРТАЛА, "portal_license", "licenseType в каталоге (66) — commercial"
                ),
                _факт("paid", "price_per_second_usd", "$0.07 per second"),
            ]
        )
        self.assertEqual(итог["outcome"], "pass")
        self.assertEqual(итог["checked"], 2)
        self.assertEqual(итог["unmeasured"], 0)
        self.assertIn("моделей 1", итог["note"])

    def test_настоящая_модель_без_цены_в_пол_идёт(self):
        """Вторая половина: исключение узкое и на живые модели не распространяется."""
        итог = ip.проверить_собранное(
            факты=[_факт("flashtalk", "positioning", "модель без показанной цены")]
        )
        self.assertEqual(итог["unmeasured"], 1)
        self.assertIn("моделей 1", итог["note"])

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
