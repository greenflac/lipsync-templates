"""Тесты валидатора-2 (`studio/pipeline.py`).

Ожидаемое здесь — ЛИТЕРАЛ, а не импорт из проверяемого модуля (Т2): имя класса
провала, слово исхода и число-порог написаны буквами. Импортированное ожидание
поехало бы вместе с кодом и промолчало.

Сети нет (Т4): все факты собираются здесь же, живая база не читается ни одним
тестом. Дата, от которой считается возраст факта, передаётся явно — иначе тест
класса `устарел` начал бы падать сам собой через полгода после написания.

Мутации констант-решений (Т1) стоят отдельным классом внизу и делаются В ОБЕ
СТОРОНЫ: строже и слабее. Сужение — та сторона, которую на этой ветке уже
пропускали, и там находились зелёные дыры.
"""

from __future__ import annotations

import json
import re
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from studio import pipeline as pl
from studio import pricing
from studio.selfrag.facts import Fact

СЕГОДНЯ = date(2026, 8, 31)


def факт(
    model,
    attribute,
    value,
    url="https://example.test/a",
    tier="vendor",
    stated_on="2026-08-20",
    witnessed="",
):
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url=url,
        tier=tier,
        stated_on=stated_on,
        witnessed=witnessed,
    )


def здоровые(model, price="0.039", licence="apache-2.0", stated_on="2026-08-20"):
    """Лицензия, цена и одно свидетельство — минимум, на котором шаг проходит."""
    return [
        факт(model, "license", licence, stated_on=stated_on),
        факт(model, "price_per_image_usd", price, stated_on=stated_on),
        факт(
            model,
            "holds_identity",
            # Значение отвечает НА ТРЕБОВАНИЕ шага, а не просто относится к
            # модели: с 2026-09-02 `step_verdict` спрашивает, о том ли эта
            # строка, и подача, где ни одна строка не про требование, честно
            # получает «не смогли». Прежняя фикстура проходила ровно потому,
            # что требование не читалось.
            "лицо клиента доходит до результата; губы совпадают со звуком; "
            "движение держится; кожа не мылится; требование шага закрыто",
            url="владелец, чат",
            tier="operator",
            stated_on=stated_on,
            witnessed="прогнал на пяти селфи, лицо то же самое",
        ),
    ]


def шаг(model="модель-а", requires=(), produces=(), budget=0.30, use="коммерческое"):
    return pl.Step(
        name="шаг",
        model=model,
        requirement="лицо клиента не должно подмениться",
        requires=tuple(requires),
        produces=tuple(produces),
        budget_usd=budget,
        use=use,
    )


def план(*steps, name="план"):
    return pl.Pipeline(name=name, steps=tuple(steps))


def исход(steps, facts, today=СЕГОДНЯ):
    return pl.pipeline_report(план(*steps), list(facts), today)


class СемьКлассов(unittest.TestCase):
    """Каждый класс срабатывает на своём дефекте и НЕ срабатывает на здоровом."""

    def test_здоровый_план_проходит_без_единого_класса(self):
        отчёт = исход([шаг(requires=["селфи"], produces=["кадр"])], здоровые("модель-а"))
        self.assertEqual(отчёт["outcome"], "pass")
        self.assertEqual(отчёт["classes"], [])

    def test_нет_модели_называется_и_несёт_третий_исход(self):
        отчёт = исход([шаг(model="модель-которой-нет", requires=["селфи"])], [])
        self.assertEqual(отчёт["classes"], ["нет_модели"])
        self.assertEqual(отчёт["outcome"], "could not measure")

    def test_разрыв_между_шагами_виден_только_на_границе(self):
        первый = pl.Step("кадр", "модель-а", "лицо держится", ("селфи",), ("кадр",), 0.30)
        второй = pl.Step(
            "липсинк", "модель-б", "губы совпадают", ("кадр", "аудио"), ("видео",), 0.30
        )
        отчёт = исход([первый, второй], здоровые("модель-а") + здоровые("модель-б"))
        self.assertEqual(отчёт["classes"], ["разрыв"])
        self.assertEqual(отчёт["outcome"], "fail")
        # Каждый шаг по отдельности безупречен — в этом весь смысл класса.
        self.assertEqual(отчёт["steps"][0]["classes"], [])

    def test_разрыва_нет_когда_артефакт_даёт_не_предыдущий_шаг_а_первый(self):
        а = pl.Step("кадр", "модель-а", "лицо держится", ("селфи",), ("кадр",), 0.30)
        б = pl.Step("видео", "модель-б", "движение держится", ("кадр",), ("видео",), 0.30)
        в = pl.Step("апскейл", "модель-в", "кожа не мылится", ("кадр",), ("кадр-4k",), 0.30)
        факты = здоровые("модель-а") + здоровые("модель-б") + здоровые("модель-в")
        self.assertEqual(исход([а, б, в], факты)["outcome"], "pass")

    def test_требование_закрытое_только_схемой_даёт_третий_исход(self):
        только_схема = [
            факт("модель-а", "license", "commercial terms"),
            факт("модель-а", "price_per_image_usd", "0.039"),
            факт("модель-а", "max_seconds", "15"),
        ]
        отчёт = исход([шаг(requires=["селфи"])], только_схема)
        self.assertEqual(отчёт["classes"], ["применимость"])
        self.assertEqual(отчёт["outcome"], "could not measure")

    def test_свидетельство_против_шага_даёт_не_годно_через_тот_же_класс(self):
        факты = здоровые("модель-а") + [
            факт(
                "модель-а",
                "failure_mode",
                "лицо уплывает на длинных планах",
                tier="probe",
            )
        ]
        отчёт = исход([шаг(requires=["селфи"])], факты)
        self.assertEqual(отчёт["classes"], ["применимость"])
        self.assertEqual(отчёт["outcome"], "fail")

    def test_лицензия_запрещающая_коммерцию_валит_коммерческий_шаг(self):
        факты = здоровые("модель-а", licence="research-only, non-commercial")
        отчёт = исход([шаг(requires=["селфи"])], факты)
        self.assertEqual(отчёт["classes"], ["лицензия"])
        self.assertEqual(отчёт["outcome"], "fail")

    def test_та_же_лицензия_не_валит_исследовательский_шаг(self):
        факты = здоровые("модель-а", licence="research-only, non-commercial")
        отчёт = исход([шаг(requires=["селфи"], use="исследование")], факты)
        self.assertEqual(отчёт["classes"], [])
        self.assertEqual(отчёт["outcome"], "pass")

    def test_лицензия_неизвестна_это_не_смогли_а_не_годно(self):
        факты = [
            факт("модель-а", "price_per_image_usd", "0.039"),
            факт(
                "модель-а",
                "holds_identity",
                "лицо держится",
                url="владелец",
                tier="operator",
                witnessed="прогнал и увидел",
            ),
        ]
        отчёт = исход([шаг(requires=["селфи"])], факты)
        self.assertEqual(отчёт["outcome"], "could not measure")
        self.assertEqual(отчёт["classes"], [])

    def test_цена_выше_бюджета_валит_шаг_по_нижней_границе(self):
        факты = здоровые("модель-а", price="2.50")
        отчёт = исход([шаг(requires=["селфи"], budget=0.30)], факты)
        self.assertEqual(отчёт["classes"], ["цена"])
        self.assertEqual(отчёт["outcome"], "fail")

    def test_цена_сравнивается_с_самой_дешёвой_известной(self):
        факты = здоровые("модель-а", price="2.50") + [
            факт("модель-а", "price_per_image_usd", "0.10", url="https://example.test/b")
        ]
        self.assertEqual(исход([шаг(requires=["селфи"], budget=0.30)], факты)["outcome"], "pass")

    def test_бюджет_не_заявлен_считается_отдельно_от_трёх_исходов(self):
        отчёт = исход([шаг(requires=["селфи"], budget=None)], здоровые("модель-а"))
        self.assertEqual(отчёт["outcome"], "pass")
        self.assertEqual(отчёт["not_declared"], 1)

    def test_модель_снятая_площадкой_валит_шаг(self):
        факты = здоровые("модель-а") + [факт("модель-а", "lifecycle", "deprecated by the platform")]
        отчёт = исход([шаг(requires=["селфи"])], факты)
        self.assertEqual(отчёт["classes"], ["устарел"])
        self.assertEqual(отчёт["outcome"], "fail")

    def test_самое_свежее_утверждение_старше_порога_валит_шаг(self):
        отчёт = исход([шаг(requires=["селфи"])], здоровые("модель-а", stated_on="2019-06-01"))
        self.assertEqual(отчёт["classes"], ["устарел"])
        self.assertEqual(отчёт["outcome"], "fail")

    def test_расхождение_в_решающем_атрибуте_это_третий_исход_а_не_голосование(self):
        факты = здоровые("модель-а") + [
            факт("модель-а", "max_seconds", "15", url="https://vendor.test/a"),
            факт("модель-а", "max_seconds", "10", url="https://portal.test/b", tier="portal"),
        ]
        отчёт = исход([шаг(requires=["селфи"])], факты)
        self.assertEqual(отчёт["classes"], ["противоречие"])
        self.assertEqual(отчёт["outcome"], "could not measure")
        # Ни одна из сторон не выбрана: обе названы.
        нота = отчёт["steps"][0]["probes"][-1]["note"]
        self.assertIn("10", нота)
        self.assertIn("15", нота)

    def test_расхождение_в_нерешающем_атрибуте_не_останавливает_план(self):
        факты = здоровые("модель-а") + [
            факт("модель-а", "best_for", "портреты", url="https://vendor.test/a"),
            факт("модель-а", "best_for", "типографика", url="https://portal.test/b", tier="portal"),
        ]
        self.assertEqual(исход([шаг(requires=["селфи"])], факты)["outcome"], "pass")


class ФормаВердикта(unittest.TestCase):
    def test_классов_ровно_семь_и_имена_литералами(self):
        self.assertEqual(
            list(pl.CLASSES),
            [
                "нет_модели",
                "разрыв",
                "применимость",
                "лицензия",
                "цена",
                "устарел",
                "противоречие",
            ],
        )

    def test_три_класса_из_семи_несут_третий_исход(self):
        self.assertEqual(pl.CLASS_OUTCOME["нет_модели"], "could not measure")
        self.assertEqual(pl.CLASS_OUTCOME["противоречие"], "could not measure")
        self.assertEqual(pl.CLASS_OUTCOME["разрыв"], "fail")
        self.assertNotIn("применимость", pl.CLASS_OUTCOME)

    def test_пустой_план_это_не_смогли_а_не_годно(self):
        отчёт = pl.pipeline_report(pl.Pipeline("пусто", ()), [], СЕГОДНЯ)
        self.assertEqual(отчёт["outcome"], "could not measure")
        self.assertEqual(отчёт["unmeasured"], 1)

    def test_исход_плана_это_слабейшее_звено(self):
        целый = pl.Step("кадр", "модель-а", "лицо держится", ("селфи",), ("кадр",), 0.30)
        битый = pl.Step("видео", "модель-б", "движение", ("аудио",), ("видео",), 0.30)
        отчёт = исход([целый, битый], здоровые("модель-а") + здоровые("модель-б"))
        self.assertEqual(отчёт["steps"][0]["outcome"], "pass")
        self.assertEqual(отчёт["outcome"], "fail")

    def test_не_годно_сильнее_чем_не_смогли(self):
        нет_модели = pl.Step("а", "неизвестная", "требование", ("селфи",), (), None)
        дорогой = pl.Step("б", "модель-а", "требование", ("селфи",), (), 0.01)
        отчёт = исход([нет_модели, дорогой], здоровые("модель-а", price="2.50"))
        self.assertEqual(отчёт["outcome"], "fail")
        self.assertEqual(отчёт["classes"], ["нет_модели", "цена"])

    def test_печать_несёт_три_числа_рядом_с_исходом(self):
        текст = pl.render(исход([шаг(requires=["селфи"])], здоровые("модель-а")))
        self.assertIn("проверено", текст)
        self.assertIn("нарушений", текст)
        self.assertIn("не смогли", текст)

    def test_пустая_база_не_зажигает_чужие_классы(self):
        отчёт = исход([шаг(model="никому-не-известная", requires=["селфи"])], [])
        сработали = [p["class"] for p in отчёт["steps"][0]["probes"] if p["fired"]]
        self.assertEqual(сработали, ["нет_модели"])
        неприменимые = [p["class"] for p in отчёт["steps"][0]["probes"] if not p["applicable"]]
        self.assertEqual(len(неприменимые), 5)


class ЧтениеКонтроля(unittest.TestCase):
    def test_негодная_строка_пропускается_и_видна_разницей_чисел(self):
        строки = [
            {
                "id": "годная",
                "kind": "чужак",
                "expect_outcome": "pass",
                "expect_classes": [],
                "pipeline": {"name": "п", "steps": []},
            },
            {"id": "без-исхода", "kind": "мутант", "pipeline": {"name": "п", "steps": []}},
            {
                "id": "чужой-класс",
                "kind": "мутант",
                "expect_outcome": "fail",
                "expect_classes": ["выдуманный"],
                "pipeline": {"name": "п", "steps": []},
            },
            {"нет": "ключей"},
        ]
        with tempfile.TemporaryDirectory() as d:
            путь = Path(d) / "controls.jsonl"
            путь.write_text(
                "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in строки), encoding="utf-8"
            )
            self.assertEqual(pl.rows_in(путь), 4)
            self.assertEqual(len(pl.load_controls(путь)), 1)

    def test_файла_нет_это_ноль_а_не_взрыв(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(pl.load_controls(Path(d) / "нет.jsonl"), [])
            self.assertEqual(pl.rows_in(Path(d) / "нет.jsonl"), 0)

    def test_живой_набор_несёт_и_мутантов_и_чужаков(self):
        набор = pl.load_controls()
        self.assertEqual(len(набор), pl.rows_in())
        self.assertTrue([c for c in набор if c.kind == "мутант"])
        self.assertTrue([c for c in набор if c.kind == "чужак"])
        посеяно = {k for c in набор if c.kind == "мутант" for k in c.expect_classes}
        self.assertEqual(len(посеяно), 7)


class МутацииКонстант(unittest.TestCase):
    """Т1: каждая константа-решение подменяется В ОБЕ СТОРОНЫ.

    Строже — прибор обязан отвергнуть здоровое; слабее — обязан пропустить
    сломанное. Мутация, не изменившая ни одного исхода, означает, что константу
    не сторожит ничто, и такой тест сам был бы украшением.
    """

    def здоровый(self):
        return исход([шаг(requires=["бриф"], produces=["кадр"])], здоровые("модель-а"))

    def test_min_facts_строже_отвергает_здоровое(self):
        факты = [
            факт(
                "модель-а",
                "license",
                # Единственная строка подачи обязана отвечать на требование
                # шага («лицо клиента не должно подмениться»), иначе шаг —
                # честное «не смогли». `witnessed` здесь не спасает: поиск
                # смотрит в значение, а не в это поле (ИЗМЕРЕНО 2026-09-02).
                "apache-2.0 (прочитан LICENSE; лицо клиента на прогоне не подменилось)",
                url="владелец",
                tier="operator",
                witnessed="открыл LICENSE в корне: apache-2.0",
            )
        ]
        шажок = шаг(requires=["селфи"], budget=None, use="исследование")
        self.assertEqual(исход([шажок], факты)["outcome"], "pass")
        with mock.patch.object(pl, "MIN_FACTS_PER_MODEL", 2):
            self.assertEqual(исход([шажок], факты)["classes"], ["нет_модели"])

    def test_min_facts_слабее_пропускает_сломанное(self):
        сломанный = [шаг(model="никому-не-известная", requires=["селфи"])]
        self.assertEqual(исход(сломанный, [])["classes"], ["нет_модели"])
        with mock.patch.object(pl, "MIN_FACTS_PER_MODEL", 0):
            self.assertEqual(исход(сломанный, [])["steps"][0]["probes"][0]["fired"], False)

    def test_ambient_строже_отвергает_здоровое(self):
        self.assertEqual(self.здоровый()["outcome"], "pass")
        with mock.patch.object(pl, "AMBIENT_ARTEFACTS", frozenset({"селфи"})):
            self.assertEqual(self.здоровый()["classes"], ["разрыв"])

    def test_ambient_слабее_пропускает_сломанное(self):
        битый = [шаг(requires=["аудио"])]
        self.assertEqual(исход(битый, здоровые("модель-а"))["classes"], ["разрыв"])
        with mock.patch.object(pl, "AMBIENT_ARTEFACTS", frozenset({"бриф", "аудио"})):
            self.assertEqual(исход(битый, здоровые("модель-а"))["outcome"], "pass")

    def test_lookback_строже_отвергает_законную_перемычку(self):
        а = pl.Step("кадр", "модель-а", "лицо", ("селфи",), ("кадр",), 0.30)
        б = pl.Step("видео", "модель-б", "движение", ("кадр",), ("видео",), 0.30)
        в = pl.Step("апскейл", "модель-в", "кожа", ("кадр",), ("кадр-4k",), 0.30)
        факты = здоровые("модель-а") + здоровые("модель-б") + здоровые("модель-в")
        self.assertEqual(исход([а, б, в], факты)["outcome"], "pass")
        with mock.patch.object(pl, "PRODUCES_LOOKBACK", 1):
            self.assertEqual(исход([а, б, в], факты)["classes"], ["разрыв"])

    def test_запрещающие_маркеры_строже_отвергают_здоровое(self):
        self.assertEqual(self.здоровый()["outcome"], "pass")
        with mock.patch.object(pl, "FORBIDDING_LICENCE_MARKERS", ("apache",)):
            self.assertEqual(self.здоровый()["classes"], ["лицензия"])

    def test_запрещающие_маркеры_слабее_пропускают_сломанное(self):
        факты = здоровые("модель-а", licence="research-only, non-commercial")
        битый = [шаг(requires=["бриф"])]
        self.assertEqual(исход(битый, факты)["classes"], ["лицензия"])
        with mock.patch.object(pl, "FORBIDDING_LICENCE_MARKERS", ("cc-by-nc",)):
            self.assertEqual(исход(битый, факты)["outcome"], "pass")

    def test_допуск_бюджета_строже_отвергает_попадание_в_бюджет(self):
        впритык = [шаг(requires=["бриф"], budget=0.039)]
        self.assertEqual(исход(впритык, здоровые("модель-а"))["outcome"], "pass")
        with mock.patch.object(pl, "BUDGET_TOLERANCE", -0.5):
            self.assertEqual(исход(впритык, здоровые("модель-а"))["classes"], ["цена"])

    def test_допуск_бюджета_слабее_пропускает_превышение(self):
        дорого = [шаг(requires=["бриф"], budget=0.30)]
        факты = здоровые("модель-а", price="2.50")
        self.assertEqual(исход(дорого, факты)["classes"], ["цена"])
        with mock.patch.object(pl, "BUDGET_TOLERANCE", 100.0):
            self.assertEqual(исход(дорого, факты)["outcome"], "pass")

    def test_порог_устаревания_строже_отвергает_свежее(self):
        self.assertEqual(self.здоровый()["outcome"], "pass")
        with mock.patch.object(pl, "STALE_AFTER_DAYS", 1):
            self.assertEqual(self.здоровый()["classes"], ["устарел"])

    def test_порог_устаревания_слабее_пропускает_семилетнее(self):
        старьё = здоровые("модель-а", stated_on="2019-06-01")
        битый = [шаг(requires=["бриф"])]
        self.assertEqual(исход(битый, старьё)["classes"], ["устарел"])
        with mock.patch.object(pl, "STALE_AFTER_DAYS", 36500):
            self.assertEqual(исход(битый, старьё)["outcome"], "pass")

    def test_маркеры_снятия_строже_отвергают_доступную_модель(self):
        факты = здоровые("модель-а") + [факт("модель-а", "lifecycle", "generally available")]
        битый = [шаг(requires=["бриф"])]
        self.assertEqual(исход(битый, факты)["outcome"], "pass")
        with mock.patch.object(pl, "DEPRECATION_MARKERS", ("available",)):
            self.assertEqual(исход(битый, факты)["classes"], ["устарел"])

    def test_маркеры_снятия_слабее_пропускают_снятую_модель(self):
        факты = здоровые("модель-а") + [факт("модель-а", "lifecycle", "deprecated by the platform")]
        битый = [шаг(requires=["бриф"])]
        self.assertEqual(исход(битый, факты)["classes"], ["устарел"])
        with mock.patch.object(pl, "DEPRECATION_MARKERS", ("retired",)):
            self.assertEqual(исход(битый, факты)["outcome"], "pass")

    def test_решающие_атрибуты_строже_отвергают_безобидное_расхождение(self):
        факты = здоровые("модель-а") + [
            факт("модель-а", "best_for", "портреты", url="https://vendor.test/a"),
            факт("модель-а", "best_for", "типографика", url="https://portal.test/b", tier="portal"),
        ]
        битый = [шаг(requires=["бриф"])]
        self.assertEqual(исход(битый, факты)["outcome"], "pass")
        with mock.patch.object(pl, "CONTRADICTION_ATTRIBUTES", frozenset({"best_for"})):
            self.assertEqual(исход(битый, факты)["classes"], ["противоречие"])

    def test_решающие_атрибуты_слабее_пропускают_спор_о_длине(self):
        факты = здоровые("модель-а") + [
            факт("модель-а", "max_seconds", "15", url="https://vendor.test/a"),
            факт("модель-а", "max_seconds", "10", url="https://portal.test/b", tier="portal"),
        ]
        битый = [шаг(requires=["бриф"])]
        self.assertEqual(исход(битый, факты)["classes"], ["противоречие"])
        with mock.patch.object(pl, "CONTRADICTION_ATTRIBUTES", frozenset({"license"})):
            self.assertEqual(исход(битый, факты)["outcome"], "pass")

    def test_маркеры_лицензии_строже_теряют_строку_лицензии(self):
        # Сужение до `licence` (британское написание) оставляет американское
        # `license` живой базы неопознанным — и класс молча перестаёт мерить.
        факты = здоровые("модель-а", licence="research-only, non-commercial")
        битый = [шаг(requires=["бриф"])]
        self.assertEqual(исход(битый, факты)["classes"], ["лицензия"])
        with mock.patch.object(pl, "LICENCE_MARKERS", ("licence",)):
            self.assertEqual(исход(битый, факты)["outcome"], "could not measure")

    def test_запрещающие_маркеры_сужение_до_одной_формулировки_теряет_research_only(self):
        # ДЫРА, НАЙДЕННАЯ МУТАЦИЕЙ 2026-08-31: у настоящей лицензии LTX-Video в
        # контрольном наборе написано и «Research-Only», и «non-commercial»,
        # поэтому изъятие первой формулировки проходило гейт ЗЕЛЁНЫМ. Здесь
        # лицензия несёт ТОЛЬКО research-only, и изъятие краснеет.
        факты = здоровые("модель-а", licence="research-only community license")
        битый = [шаг(requires=["бриф"])]
        self.assertEqual(исход(битый, факты)["classes"], ["лицензия"])
        with mock.patch.object(pl, "FORBIDDING_LICENCE_MARKERS", ("non-commercial",)):
            self.assertEqual(исход(битый, факты)["outcome"], "pass")

    def test_маркеры_цены_слабее_топят_нижнюю_границу(self):
        # Вторая дыра той же мутации: расширение PRICE_MARKERS само по себе
        # ненаблюдаемо, потому что сравнение идёт по МИНИМУМУ и лишний большой
        # разбор ничего не двигает. Двигает лишний МАЛЕНЬКИЙ: строка про число
        # кадров со значением 0, принятая за цену, обнуляет нижнюю границу и
        # пропускает шаг за два с половиной доллара при бюджете в тридцать
        # центов. Ровно это и сторожится.
        #
        # Фикстура сменена 2026-09-02 с `max_frames` на `max_frames_per_second`
        # и это НЕ косметика: оракул теперь сравнивает с бюджетом только то, у
        # чего сошлись единица и «за что», а у `max_frames` «за что» не
        # выводится вовсе — прежняя фикстура перестала быть дырой и потому
        # перестала бы сторожить. `..._per_second` даёт «за что» = second, и
        # дыра снова наблюдаема: ноль, принятый за цену, топит нижнюю границу.
        факты = здоровые("модель-а", price="2.50") + [
            факт("модель-а", "max_frames_per_second", "0", url="https://example.test/c")
        ]
        дорого = [шаг(requires=["бриф"], budget=0.30)]
        self.assertEqual(исход(дорого, факты)["classes"], ["цена"])
        with mock.patch.object(pl, "PRICE_MARKERS", ("price", "cost", "цена", "стоимост", "max_")):
            self.assertEqual(исход(дорого, факты)["outcome"], "pass")

    def test_маркеры_цены_слабее_ловят_нецену(self):
        # Расширение до `usd` заставило бы разбирать как цену любую строку с
        # долларами в имени; здесь это видно исходом, а не рассуждением.
        факты = здоровые("модель-а", price="2.50")
        битый = [шаг(requires=["бриф"], budget=0.30)]
        self.assertEqual(исход(битый, факты)["classes"], ["цена"])
        with mock.patch.object(pl, "PRICE_MARKERS", ("не-встречается-нигде",)):
            self.assertEqual(исход(битый, факты)["outcome"], "could not measure")


# Ценовые строки, СНЯТЫЕ С ЖИВОЙ БАЗЫ 2026-09-02 без правки хоть одного знака.
# Литералы, а не выборка из `model_facts.jsonl` (Т2 и Т4): прочитанная база
# поехала бы вместе с базой и промолчала бы ровно там, где сторожить и надо.
# Каждая форма — своя, и каждая ломала прежний оракул СВОИМ способом:
ЦЕНА_ПРОЗОЙ = "0.039 per image"  # прежний брал верно и только здесь
ЦЕНА_С_ИМЕНЕМ_МОДЕЛИ = (
    "FLUX.2 [pro]: $0.03 for the first generated megapixel, $0.015 for each additional"  # noqa: E501
)
ЦЕНА_В_КРЕДИТАХ = "40 credits/s with audio, 20 credits/s without"
ЦЕНА_ПРОЦЕНТОМ = "50% lower price per character for API generations"
ЦЕНА_ДИАПАЗОНОМ = "0.10 at 720p, 0.15 at 1080p"
ЦЕНА_ЗА_МИЛЛИОН_ТОКЕНОВ = "4.00 (cached 0.40; output 20.00)"
ЦЕНА_ЗА_МЕГАПИКСЕЛЬ = "0.02 per megapixel"
ЦЕНА_С_РАЗРЕШЕНИЕМ_ВПЕРЕДИ = "360p 0.025/0.035, 540p 0.035/0.045, 720p 0.045/0.060"

#: Что прежний оракул (первое число строки) объявлял долларами на этих же
#: строках. ИЗМЕРЕНО 2026-09-02 прогоном `_price_of` по живой базе до его
#: удаления: 45 строк из 82 разбирались неверно, «не смогли» он не сказал ни
#: разу. Числа стоят здесь литералами, чтобы разница была видна, а не описана.
ПРЕЖНИЙ_РАЗБОР = {
    ЦЕНА_С_ИМЕНЕМ_МОДЕЛИ: 2.0,
    ЦЕНА_В_КРЕДИТАХ: 40.0,
    ЦЕНА_ПРОЦЕНТОМ: 50.0,
    ЦЕНА_С_РАЗРЕШЕНИЕМ_ВПЕРЕДИ: 360.0,
}


def ценовой(model, attribute, value, budget):
    """Шаг с бюджетом и модель ровно с ОДНОЙ ценовой строкой. Больше ничего."""
    факты = [
        факт(model, "license", "apache-2.0"),
        факт(model, attribute, value),
        факт(
            model,
            "holds_identity",
            # Значение отвечает НА ТРЕБОВАНИЕ шага, а не просто относится к
            # модели: с 2026-09-02 `step_verdict` спрашивает, о том ли эта
            # строка, и подача, где ни одна строка не про требование, честно
            # получает «не смогли». Прежняя фикстура проходила ровно потому,
            # что требование не читалось.
            "лицо клиента доходит до результата; губы совпадают со звуком; "
            "движение держится; кожа не мылится; требование шага закрыто",
            url="владелец",
            tier="operator",
            witnessed="прогнал и увидел",
        ),
    ]
    return исход([шаг(model=model, requires=["селфи"], budget=budget)], факты)


class ЦенаИзПрозыЖивойБазы(unittest.TestCase):
    """Оракул цены на формах, которые база несёт на самом деле.

    ДЕФЕКТ, ВОСПРОИЗВЕДЁН 2026-09-02 до починки: `_price_of` брал ПЕРВОЕ число
    строки и звал его долларами. «FLUX.2 [pro]: $0.03…» давало цену 2.0 (двойка
    из имени модели), «50% lower price» — цену 50.0 (процент скидки), «40
    credits/s» — цену 40.0 (кредиты вендора). 45 живых строк из 82, и ни на
    одной оракул не сказал «не смогли»: Р1, свёрнутый в одну сторону.

    Разбор теперь ОДИН на репозиторий — `studio/pricing.py` (Е1).
    """

    def test_второго_разборщика_цены_в_валидаторе_больше_нет(self):
        # Е1 наблюдаемо, а не на словах: вернувшийся `_price_of` красит тест.
        self.assertFalse(hasattr(pl, "_price_of"))
        self.assertFalse(hasattr(pl, "_NUMBER"))

    def test_двойка_из_имени_модели_не_становится_ценой(self):
        self.assertEqual(ПРЕЖНИЙ_РАЗБОР[ЦЕНА_С_ИМЕНЕМ_МОДЕЛИ], 2.0)
        отчёт = ценовой("модель-flux", "price_per_image", ЦЕНА_С_ИМЕНЕМ_МОДЕЛИ, 1.00)
        self.assertEqual(отчёт["outcome"], "pass")
        self.assertEqual(отчёт["classes"], [])

    def test_процент_скидки_не_становится_ценой_а_даёт_третий_исход(self):
        self.assertEqual(ПРЕЖНИЙ_РАЗБОР[ЦЕНА_ПРОЦЕНТОМ], 50.0)
        отчёт = ценовой("модель-процент", "price_relative", ЦЕНА_ПРОЦЕНТОМ, 0.30)
        self.assertEqual(отчёт["outcome"], "could not measure")
        self.assertEqual(отчёт["classes"], [])

    def test_кредиты_вендора_с_долларовым_бюджетом_не_сравниваются(self):
        self.assertEqual(ПРЕЖНИЙ_РАЗБОР[ЦЕНА_В_КРЕДИТАХ], 40.0)
        отчёт = ценовой("модель-кредиты", "price_per_second_reseller", ЦЕНА_В_КРЕДИТАХ, 0.30)
        self.assertEqual(отчёт["outcome"], "could not measure")

    def test_доллары_за_миллион_токенов_с_бюджетом_шага_не_сравниваются(self):
        # Единица та же, «за что» — другое. Сложить их значит повторить дефект
        # аккуратнее, а не убрать его.
        отчёт = ценовой(
            "модель-токены", "price_per_million_input_usd", ЦЕНА_ЗА_МИЛЛИОН_ТОКЕНОВ, 0.30
        )
        self.assertEqual(отчёт["outcome"], "could not measure")

    def test_разрешение_перед_числом_не_становится_ценой(self):
        self.assertEqual(ПРЕЖНИЙ_РАЗБОР[ЦЕНА_С_РАЗРЕШЕНИЕМ_ВПЕРЕДИ], 360.0)
        отчёт = ценовой("модель-360p", "price_per_second_usd", ЦЕНА_С_РАЗРЕШЕНИЕМ_ВПЕРЕДИ, 0.30)
        self.assertEqual(отчёт["outcome"], "could not measure")

    def test_цена_прозой_вокруг_числа_разбирается_и_пропускает_шаг(self):
        отчёт = ценовой("модель-проза", "price_per_image_usd", ЦЕНА_ПРОЗОЙ, 0.039)
        self.assertEqual(отчёт["outcome"], "pass")

    def test_цена_прозой_вокруг_числа_валит_шаг_когда_дороже(self):
        отчёт = ценовой("модель-проза-дорогая", "price_per_image_usd", "2.50 per image", 0.30)
        self.assertEqual(отчёт["outcome"], "fail")
        self.assertEqual(отчёт["classes"], ["цена"])

    def test_цена_за_мегапиксель_разбирается(self):
        отчёт = ценовой("модель-мегапиксель", "price_per_megapixel_usd", ЦЕНА_ЗА_МЕГАПИКСЕЛЬ, 0.05)
        self.assertEqual(отчёт["outcome"], "pass")

    def test_условная_цена_в_бюджете_это_третий_исход_а_не_годно(self):
        # Нижняя укладывается, но строка сама говорит, что при 1080p платят
        # больше. «Годно» здесь было бы обещанием, которого никто не давал.
        отчёт = ценовой("модель-диапазон", "price_per_second_usd", ЦЕНА_ДИАПАЗОНОМ, 0.12)
        self.assertEqual(отчёт["outcome"], "could not measure")
        self.assertEqual(отчёт["classes"], [])

    def test_условная_цена_выше_потолка_остаётся_не_годно(self):
        # Вторая половина того же (И5): условность НЕ превращает превышение в
        # «не смогли» — нижняя граница уже выше потолка, и это неопровержимо.
        отчёт = ценовой("модель-диапазон-дорогая", "price_per_second_usd", ЦЕНА_ДИАПАЗОНОМ, 0.05)
        self.assertEqual(отчёт["outcome"], "fail")
        self.assertEqual(отчёт["classes"], ["цена"])

    def test_оракул_цены_различает_все_три_исхода(self):
        # Р2 и И5 разом: прибор, у которого исход один на все входы, меряет не
        # то. Здесь три разных ценовых входа обязаны дать три разных исхода.
        исходы = {
            ценовой("м1", "price_per_image_usd", ЦЕНА_ПРОЗОЙ, 0.039)["outcome"],
            ценовой("м2", "price_per_image_usd", "2.50 per image", 0.30)["outcome"],
            ценовой("м3", "price_relative", ЦЕНА_ПРОЦЕНТОМ, 0.30)["outcome"],
        }
        self.assertEqual(исходы, {"pass", "fail", "could not measure"})

    def test_числа_разбора_печатаются_рядом_с_исходом(self):
        # Е3: «в бюджет уложились» по одной сравнимой строке из двух читается
        # как проверенное, если рядом не стоит числа.
        факты = [
            факт("модель-две-цены", "license", "apache-2.0"),
            факт("модель-две-цены", "price_per_image_usd", ЦЕНА_ПРОЗОЙ),
            факт(
                "модель-две-цены",
                "price_per_second_reseller",
                ЦЕНА_В_КРЕДИТАХ,
                url="https://example.test/c",
            ),
        ]
        проба = pl.probe_price(шаг(model="модель-две-цены", budget=0.039), факты)
        self.assertIn("строк о цене 2", проба.note)
        self.assertIn("сравнимых с бюджетом 1", проба.note)


class МутацииРазбораЦены(unittest.TestCase):
    """Т1 в обе стороны на всём, что тронуто в оракуле цены."""

    def test_единица_бюджета_подменена_на_кредиты_возвращает_дефект(self):
        # Слабее в опасную сторону: с BUDGET_UNIT="credits" кредиты вендора
        # снова встают рядом с долларовым бюджетом — 40 против 0.30 — и шаг
        # объявляется дорогим. Это ровно тот дефект, который убран.
        подача = ("модель-кредиты", "price_per_second_reseller", ЦЕНА_В_КРЕДИТАХ, 0.30)
        self.assertEqual(ценовой(*подача)["outcome"], "could not measure")
        with mock.patch.object(pl, "BUDGET_UNIT", "credits"):
            отчёт = ценовой(*подача)
            self.assertEqual(отчёт["outcome"], "fail")
            self.assertEqual(отчёт["classes"], ["цена"])

    def test_единица_бюджета_подменена_на_пустую_обнуляет_оракул(self):
        # Строже до бессмысленности: сравнимого не остаётся ничего, и здоровый
        # шаг уходит в третий исход. Мутация обязана краснеть и здесь.
        self.assertEqual(ценовой("м", "price_per_image_usd", ЦЕНА_ПРОЗОЙ, 0.039)["outcome"], "pass")
        with mock.patch.object(pl, "BUDGET_UNIT", ""):
            отчёт = ценовой("м", "price_per_image_usd", ЦЕНА_ПРОЗОЙ, 0.039)
            self.assertEqual(отчёт["outcome"], "could not measure")

    def test_список_за_что_расширен_сравнивает_цену_за_миллион_токенов(self):
        # Слабее: стоит признать «million» единицей счёта, и цена за миллион
        # входных токенов начинает сравниваться с бюджетом одного шага.
        подача = ("модель-токены", "price_per_million_input_usd", ЦЕНА_ЗА_МИЛЛИОН_ТОКЕНОВ, 0.30)
        self.assertEqual(ценовой(*подача)["outcome"], "could not measure")
        with mock.patch.object(pricing, "PER", pricing.PER + ("million",)):
            self.assertEqual(ценовой(*подача)["classes"], ["цена"])

    def test_список_за_что_сужен_обнуляет_оракул(self):
        # Строже: пустой список «за что» не оставляет сравнимым ничего.
        self.assertEqual(ценовой("м", "price_per_image_usd", ЦЕНА_ПРОЗОЙ, 0.039)["outcome"], "pass")
        with mock.patch.object(pricing, "PER", ()):
            self.assertEqual(
                ценовой("м", "price_per_image_usd", ЦЕНА_ПРОЗОЙ, 0.039)["outcome"],
                "could not measure",
            )

    def test_якорь_ведущего_числа_ослаблен_возвращает_разрешение_вместо_цены(self):
        # Ведущее число обязано кончаться разделителем, а не буквой. Снимите
        # это требование — и «360p 0.025/...» снова даёт 360 долларов.
        подача = ("модель-360p", "price_per_second_usd", ЦЕНА_С_РАЗРЕШЕНИЕМ_ВПЕРЕДИ, 0.30)
        self.assertEqual(ценовой(*подача)["outcome"], "could not measure")
        слабый = re.compile(r"^\s*~?\s*(\d+(?:\.\d+)?)")
        with mock.patch.object(pricing, "_LEAD", слабый):
            отчёт = ценовой(*подача)
            self.assertEqual(отчёт["classes"], ["цена"])

    def test_ведущее_число_выключено_теряет_живую_форму_цены(self):
        # Строже в другую сторону: без ветки ведущего числа форма «0.039 per
        # image», которой в базе 22 строки, уходит в «не смогли».
        self.assertEqual(ценовой("м", "price_per_image_usd", ЦЕНА_ПРОЗОЙ, 0.039)["outcome"], "pass")
        никогда = re.compile(r"(?!x)x")
        with mock.patch.object(pricing, "_LEAD", никогда):
            self.assertEqual(
                ценовой("м", "price_per_image_usd", ЦЕНА_ПРОЗОЙ, 0.039)["outcome"],
                "could not measure",
            )


# Даты границы устаревания. ИЗМЕРЕНО календарём от СЕГОДНЯ (2026-08-31):
# 2026-03-04 — ровно 180 дней назад, 2026-03-03 — 181 день, 2026-06-02 — 90.
# Литералы, а не `СЕГОДНЯ - timedelta(pl.STALE_AFTER_DAYS)` (Т2): вычисленная
# из порога дата поехала бы вместе с порогом и промолчала бы ровно там, где
# сторожить и надо. Сами числа возраста сторожатся отдельным тестом ниже (И5).
РОВНО_НА_ПОРОГЕ = "2026-03-04"
ЗА_ПОРОГОМ_НА_ДЕНЬ = "2026-03-03"
СЕРЕДИНА_ДИАПАЗОНА = "2026-06-02"

#: Бюджет и цены для границы бюджета. Доллар выбран круглым намеренно: при
#: budget=1.00 потолок с допуском 0.01 равен 1.01 БИТ В БИТ, и цена 1.01
#: перестаёт быть превышением — то есть соседняя мутация допуска наблюдаема.
БЮДЖЕТ_РОВНО = 1.00
ЦЕНА_РОВНО_В_БЮДЖЕТ = "1.00"
ЦЕНА_НА_ПРОЦЕНТ_ДОРОЖЕ = "1.01"
ЦЕНА_ЗАВЕДОМО_ДЕШЁВАЯ = "0.50"


class ГраницыПорогов(unittest.TestCase):
    """Т3: у каждого числового порога есть фикстура НА границе, за ней и в середине.

    ДЫРА, НАЙДЕННАЯ ПРИЁМКОЙ 2026-08-31: оба числовых порога были промутированы
    только крайностями (180 -> 1 и 180 -> 36500, 0.0 -> -0.5 и 0.0 -> 100.0), и
    крайности краснели. СОСЕДНИЕ значения (180 -> 179, 0.0 -> 0.01) проходили
    и гейт, и тесты ЗЕЛЁНЫМИ: ни одна фикстура не стояла на границе, поэтому
    сдвинуть порог на день или на процент можно было молча. Здесь фикстуры
    стоят по обе стороны каждой границы и в середине диапазона.
    """

    def test_возраст_фикстур_ровно_такой_каким_назван(self):
        # Негативный контроль самих фикстур (И5): дата, съехавшая на день,
        # превратила бы всё остальное в этом классе в проверку не того.
        self.assertEqual((СЕГОДНЯ - date.fromisoformat(РОВНО_НА_ПОРОГЕ)).days, 180)
        self.assertEqual((СЕГОДНЯ - date.fromisoformat(ЗА_ПОРОГОМ_НА_ДЕНЬ)).days, 181)
        self.assertEqual((СЕГОДНЯ - date.fromisoformat(СЕРЕДИНА_ДИАПАЗОНА)).days, 90)

    def test_утверждение_ровно_на_ста_восьмидесяти_днях_ещё_годится(self):
        факты = здоровые("модель-а", stated_on=РОВНО_НА_ПОРОГЕ)
        отчёт = исход([шаг(requires=["селфи"])], факты)
        self.assertEqual(отчёт["classes"], [])
        self.assertEqual(отчёт["outcome"], "pass")

    def test_утверждение_на_сто_восемьдесят_первом_дне_устарело(self):
        факты = здоровые("модель-а", stated_on=ЗА_ПОРОГОМ_НА_ДЕНЬ)
        отчёт = исход([шаг(requires=["селфи"])], факты)
        self.assertEqual(отчёт["classes"], ["устарел"])
        self.assertEqual(отчёт["outcome"], "fail")

    def test_утверждение_из_середины_диапазона_годится(self):
        факты = здоровые("модель-а", stated_on=СЕРЕДИНА_ДИАПАЗОНА)
        отчёт = исход([шаг(requires=["селфи"])], факты)
        self.assertEqual(отчёт["classes"], [])
        self.assertEqual(отчёт["outcome"], "pass")

    def test_шаг_ровно_по_бюджету_проходит(self):
        факты = здоровые("модель-а", price=ЦЕНА_РОВНО_В_БЮДЖЕТ)
        отчёт = исход([шаг(requires=["селфи"], budget=БЮДЖЕТ_РОВНО)], факты)
        self.assertEqual(отчёт["classes"], [])
        self.assertEqual(отчёт["outcome"], "pass")

    def test_шаг_на_процент_дороже_бюджета_отвергнут_классом_цена(self):
        факты = здоровые("модель-а", price=ЦЕНА_НА_ПРОЦЕНТ_ДОРОЖЕ)
        отчёт = исход([шаг(requires=["селфи"], budget=БЮДЖЕТ_РОВНО)], факты)
        self.assertEqual(отчёт["classes"], ["цена"])
        self.assertEqual(отчёт["outcome"], "fail")

    def test_заведомо_дешёвый_шаг_проходит(self):
        факты = здоровые("модель-а", price=ЦЕНА_ЗАВЕДОМО_ДЕШЁВАЯ)
        отчёт = исход([шаг(requires=["селфи"], budget=БЮДЖЕТ_РОВНО)], факты)
        self.assertEqual(отчёт["classes"], [])
        self.assertEqual(отчёт["outcome"], "pass")


class СоседниеМутацииПорогов(unittest.TestCase):
    """Т1 соседним значением, а не крайностью: 180 -> 179/181, 0.0 -> 0.01/-0.01.

    Крайности красили и раньше; эти четыре подмены — те самые, что проходили
    зелёными. Тест смотрит на фикстуры, стоящие ВПРИТЫК к границе, и потому
    видит сдвиг на единицу.
    """

    def test_порог_устаревания_на_день_строже_валит_факт_ровно_на_пороге(self):
        факты = здоровые("модель-а", stated_on=РОВНО_НА_ПОРОГЕ)
        битый = [шаг(requires=["селфи"])]
        self.assertEqual(исход(битый, факты)["outcome"], "pass")
        with mock.patch.object(pl, "STALE_AFTER_DAYS", 179):
            self.assertEqual(исход(битый, факты)["classes"], ["устарел"])

    def test_порог_устаревания_на_день_слабее_пропускает_сто_восемьдесят_первый(self):
        факты = здоровые("модель-а", stated_on=ЗА_ПОРОГОМ_НА_ДЕНЬ)
        битый = [шаг(requires=["селфи"])]
        self.assertEqual(исход(битый, факты)["classes"], ["устарел"])
        with mock.patch.object(pl, "STALE_AFTER_DAYS", 181):
            self.assertEqual(исход(битый, факты)["outcome"], "pass")

    def test_допуск_бюджета_на_процент_слабее_пропускает_превышение_на_процент(self):
        факты = здоровые("модель-а", price=ЦЕНА_НА_ПРОЦЕНТ_ДОРОЖЕ)
        битый = [шаг(requires=["селфи"], budget=БЮДЖЕТ_РОВНО)]
        self.assertEqual(исход(битый, факты)["classes"], ["цена"])
        with mock.patch.object(pl, "BUDGET_TOLERANCE", 0.01):
            self.assertEqual(исход(битый, факты)["outcome"], "pass")

    def test_допуск_бюджета_на_процент_строже_валит_попадание_ровно_в_бюджет(self):
        факты = здоровые("модель-а", price=ЦЕНА_РОВНО_В_БЮДЖЕТ)
        битый = [шаг(requires=["селфи"], budget=БЮДЖЕТ_РОВНО)]
        self.assertEqual(исход(битый, факты)["outcome"], "pass")
        with mock.patch.object(pl, "BUDGET_TOLERANCE", -0.01):
            self.assertEqual(исход(битый, факты)["classes"], ["цена"])


class ИсходШагаНеПересчитывается(unittest.TestCase):
    """Е1: оракул применимости берёт вердикт у `factaxis.step_verdict` как есть."""

    def test_вердикт_совпадает_с_исходом_второй_оси(self):
        факты = здоровые("модель-а")
        проба = pl.probe_applicability(шаг(), факты)
        from studio import factaxis as fa

        свой = fa.step_verdict("шаг", "требование", fa.mark_all(факты))
        self.assertEqual(проба.outcome, свой["outcome"])
        self.assertEqual(проба.note, свой["note"])


if __name__ == "__main__":
    unittest.main()
