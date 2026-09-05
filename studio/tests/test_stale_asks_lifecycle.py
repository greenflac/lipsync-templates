"""«Модель снята» решает разбор строки, а не подстрока в ней.

ВОСПРОИЗВЕДЕНО 2026-09-05 на живой базе (2127 строк). `pipeline.probe_stale`
искал слова `deprecated`/`sunset`/`retired`/`снят` в значении ЛЮБОГО атрибута и
объявлял модель снятой. Прогон против `studio/lifecycle.py`, который написан
ровно для этого вопроса и имеет негативные контроли:

    строк с маркером 13; прибор жизненного цикла: годно 7, не годно 2, не смогли 4

Те самые СЕМЬ, где валидатор говорил «снята», а разбор — «признаков снятия
нет»: у `runway-aleph2` снят ENUM соотношения сторон, у `sora-2` снят ОДИН
эндпоинт remix, у `gpt-5` написано «Still callable but superseded», у
`stable-diffusion-xl-base-1.0` слово `sunset` стоит внутри чужого промпта в
README, а у `latentsync` слово «снят» стоит в МОЁМ ЖЕ замере 2026-09-05 про то,
что модель укорачивает ролик.

ЧЕМ ЭТО ОПАСНО ЗАКАЗЧИКУ. Это уверенное и неверное ОТРИЦАНИЕ: рабочая модель
вычёркивается из плана со ссылкой на страницу вендора, и ссылка делает отказ
убедительным. Хуже того, петля замыкается на себе: честно записанный замер о
модели начинает эту же модель отвергать.

ДВА СУДЬИ ОБ ОДНОМ — И ЭТО КОРЕНЬ (Е1). `planner.life_stance` уже спрашивает
`lifecycle`, а валидатор искал подстроку сам. Теперь оба спрашивают один прибор.
"""

from __future__ import annotations

import unittest
from datetime import date

import studio.lifecycle as life
import studio.pipeline as pl
from studio.selfrag.facts import Fact

СЕГОДНЯ = date(2026, 9, 5)

#: Исходы печатаются ЛИТЕРАЛАМИ (Т2) и не импортируются из проверяемого модуля:
#: переименуй их там — и этот набор обязан покраснеть, а не переехать следом.
СНЯТА = "fail"
РАБОТАЕТ = "pass"
НЕ_СМОГЛИ = "could not measure"


def _шаг() -> pl.Step:
    return pl.Step(name="липсинк", model="m", requirement="губы держат синхрон")


def _факт(attribute: str, value: str) -> Fact:
    return Fact(
        model="m",
        attribute=attribute,
        value=value,
        source_url="https://vendor.test/page",
        tier="vendor",
        stated_on="2026-09-01",
    )


class СнятиеРешаетРазбор(unittest.TestCase):
    def test_снят_параметр_а_не_модель(self) -> None:
        """Живой случай runway-aleph2: снят ENUM соотношения сторон."""
        проба = pl.probe_stale(
            _шаг(),
            [_факт("ratio_enum", "16:9, 9:16, 1:1; the 4:3 value is deprecated")],
            СЕГОДНЯ,
        )
        self.assertNotEqual(проба.outcome, СНЯТА)

    def test_снят_один_эндпоинт_а_не_модель(self) -> None:
        """Живой случай sora-2: снят remix, сама модель работает."""
        проба = pl.probe_stale(
            _шаг(),
            [
                _факт(
                    "remix_endpoint_status",
                    "the remix endpoint is deprecated; generation is unaffected",
                )
            ],
            СЕГОДНЯ,
        )
        self.assertNotEqual(проба.outcome, СНЯТА)

    def test_слово_внутри_чужого_текста_не_снимает_модель(self) -> None:
        """Живой случай stable-diffusion-xl: `sunset` внутри промпта в README."""
        проба = pl.probe_stale(
            _шаг(),
            [_факт("failure_mode", "prompt 'a sunset over the sea' renders the sun twice")],
            СЕГОДНЯ,
        )
        self.assertNotEqual(проба.outcome, СНЯТА)

    def test_настоящее_снятие_с_прошедшей_датой_всё_ещё_снимает(self) -> None:
        """Другая сторона (Т1): починка не должна разучить прибор говорить «снята».

        Живой случай imagen-4: дата снятия 2026-06-30 уже прошла.
        """
        проба = pl.probe_stale(
            _шаг(),
            [
                _факт(
                    "availability", "discontinued on Vertex AI, discontinuation date June 30, 2026"
                )
            ],
            СЕГОДНЯ,
        )
        self.assertEqual(проба.outcome, СНЯТА)

    def test_объявленное_впереди_это_третий_исход_а_не_отказ(self) -> None:
        """Живой случай sora-2: API остановят 2026-09-24, сегодня 2026-09-05."""
        проба = pl.probe_stale(
            _шаг(),
            [_факт("limitation", "the API will be deprecated on 2026-09-24")],
            СЕГОДНЯ,
        )
        self.assertEqual(проба.outcome, НЕ_СМОГЛИ)

    def test_валидатор_и_планировщик_судят_одним_прибором(self) -> None:
        """Е1: два ответа на один вопрос — это и есть дефект.

        Сверяется на ЖИВОЙ базе: ни одной строки, где один говорит «снята», а
        другой «признаков снятия нет».
        """
        from studio.selfrag.facts import load_facts

        разошлись = []
        for f in load_facts():
            проба = pl.probe_stale(_шаг(), [f], СЕГОДНЯ)
            разбор = life.разобрать(f.value, f.attribute, сегодня=СЕГОДНЯ)
            # Сверяется ТОЛЬКО ветка снятия: у того же оракула есть вторая,
            # про возраст утверждения («самому свежему 212 дней при пороге
            # 180»), и она к снятию отношения не имеет. Без этого различения
            # тест ловил бы 50 строк протухшего возраста и молчал бы о том,
            # ради чего написан.
            если_снята = проба.outcome == СНЯТА and "объявлена снятой" in проба.note
            если_нет = разбор.outcome == life.ГОДНО
            if если_снята and если_нет:
                разошлись.append((f.model, f.attribute))
        self.assertEqual(
            разошлись, [], "валидатор объявляет снятым то, что разбор снятым не считает"
        )


if __name__ == "__main__":
    unittest.main()
