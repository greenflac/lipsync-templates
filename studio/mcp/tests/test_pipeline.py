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
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from studio import pipeline as pl
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
            "лицо клиента доходит до результата",
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
                "apache-2.0",
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
        факты = здоровые("модель-а", price="2.50") + [
            факт("модель-а", "max_frames", "0", url="https://example.test/c")
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
