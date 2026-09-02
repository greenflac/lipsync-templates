"""Планировщик: три исхода, пометка о неизмеренной применимости и негативный контроль.

Правила дома, которые этот файл соблюдает буквально:

* Т2 — ожидаемое написано ЛИТЕРАЛОМ. Ни одна проверка не сравнивает выдачу с
  константой проверяемого модуля: `NOT_MEASURED_MARK`, коды причин и имена
  классов набраны здесь строками. Импортированное ожидание поедет вместе с
  кодом и промолчит;
* Т3 — фикстуры с обоих краёв и из середины: бриф без единого шага, бриф на
  один шаг, бриф на три шага;
* Т4 — сети нет и живой базы нет: все наборы фактов собраны здесь;
* Т5 — развилки (`derive`, `inputs_of`, `by_evidence`, `cheapest_price`)
  проверяются напрямую, а не через сборку целого плана.

Ветка `pass` сторожится ТОЛЬКО здесь, и это записано вслух: на живой базе её
не даёт ни один из восьми настоящих брифов, потому что применимость в ней
почти всегда записана отрицательным атрибутом. Синтетический набор — не
поддавка, а единственный способ вообще достать эту ветку до теста.
"""

from __future__ import annotations

import unittest
from datetime import date

from studio import planner as pn
from studio.factindex import FactIndex
from studio.selfrag.facts import Fact

СЕГОДНЯ = date(2026, 9, 2)


def факт(model: str, attribute: str, value: str, tier: str, stated_on: str = "2026-08-27") -> Fact:
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url=f"https://example.invalid/{model}",
        tier=tier,
        stated_on=stated_on,
    )


#: Здоровый набор: одна модель оживления, о которой есть НАБЛЮДЕНИЕ оператора
#: (род witness, атрибут не из отрицательных), лицензия без запрета и свежая
#: дата. Ровно то, чего живой базе не хватает для исхода `годно`.
ЗДОРОВЫЕ: tuple[Fact, ...] = (
    факт(
        "тестовая-i2v",
        "observed_behaviour",
        "image-to-video i2v: запустили на селфи, лицо клиента держится всю сцену",
        "operator",
    ),
    факт("тестовая-i2v", "license", "apache-2.0", "vendor"),
    факт("тестовая-i2v", "max_seconds", "10", "vendor"),
)

#: Тот же набор, но единственная строка применимости — ОТРИЦАТЕЛЬНАЯ.
БОЛЬНЫЕ: tuple[Fact, ...] = (
    факт(
        "тестовая-i2v",
        "failure_mode",
        "image-to-video i2v: лицо клиента подменяется на второй секунде",
        "operator",
    ),
    факт("тестовая-i2v", "license", "apache-2.0", "vendor"),
)

#: Набор, где о модели известна ТОЛЬКО вендорская схема: ни измерения, ни
#: свидетельства. Именно на нём обязана появиться пометка.
ТОЛЬКО_СХЕМА: tuple[Fact, ...] = (
    факт("тестовая-i2v", "max_seconds", "image-to-video i2v: 10", "vendor"),
    факт("тестовая-i2v", "license", "apache-2.0", "vendor"),
)


class ВыводШагов(unittest.TestCase):
    """Т5: развилка вывода шагов достижима без базы, без валидатора и без плана."""

    def test_пустой_бриф_не_даёт_шагов(self) -> None:
        self.assertEqual(pn.derive(""), [])
        self.assertEqual(pn.derive("   "), [])

    def test_негативный_контроль_молчит(self) -> None:
        # И5: вход, на котором прибор ОБЯЗАН промолчать.
        self.assertEqual([op.name for op in pn.derive("сделай красиво")], [])
        self.assertEqual(
            [op.name for op in pn.derive("по видеопотоку управлять манипулятором на складе")],
            [],
        )

    def test_негативный_контроль_шевелится(self) -> None:
        # И5, вторая половина: вход, на котором обязан ответить.
        self.assertEqual(
            [op.name for op in pn.derive("с нуля: видео 15 секунд, крупный план")],
            ["генерация_видео"],
        )

    def test_порядок_канонический_а_не_по_словам_брифа(self) -> None:
        # Заказчик назвал липсинк первым, план обязан поставить его последним:
        # иначе валидатор увидит `разрыв` на здоровом плане.
        self.assertEqual(
            [op.name for op in pn.derive("сделай липсинк под мою озвучку")],
            ["озвучка", "липсинк"],
        )

    def test_три_шага_из_настоящего_брифа(self) -> None:
        self.assertEqual(
            [
                op.name
                for op in pn.derive("оживить фото клиента, 10 секунд, он говорит мою озвучку")
            ],
            ["озвучка", "оживление", "липсинк"],
        )


class ВходПлана(unittest.TestCase):
    """Т5: чем решается, что артефакт у заказчика уже есть."""

    def test_слова_брифа(self) -> None:
        self.assertEqual(pn.inputs_of("из готового ролика сделать липсинк"), frozenset({"видео"}))

    def test_поданный_файл(self) -> None:
        self.assertEqual(pn.inputs_of("сделай липсинк", "/tmp/креатив.mp4"), frozenset({"видео"}))

    def test_ни_того_ни_другого(self) -> None:
        self.assertEqual(pn.inputs_of("сделай липсинк"), frozenset())

    def test_картинка_не_считается_видео(self) -> None:
        self.assertEqual(pn.inputs_of("сделай липсинк", "/tmp/креатив.png"), frozenset())


class ПометкаОНеизмеренном(unittest.TestCase):
    """Главное правило дома в одном тесте: модель без доказательства — с пометкой."""

    def test_только_схема_даёт_пометку(self) -> None:
        индекс = FactIndex(facts=list(ТОЛЬКО_СХЕМА))
        оживление = next(op for op in pn.OPERATIONS if op.name == "оживление")
        кандидаты = pn.candidates_for(оживление, индекс)
        self.assertEqual(len(кандидаты), 1)
        # Литерал, а не импорт (Т2): пометку читает человек, и её текст —
        # часть контракта, а не деталь реализации.
        self.assertEqual(кандидаты[0].mark, "применимость не измерена")
        self.assertEqual(кандидаты[0].applicability, 0)

    def test_наблюдение_снимает_пометку(self) -> None:
        индекс = FactIndex(facts=list(ЗДОРОВЫЕ))
        оживление = next(op for op in pn.OPERATIONS if op.name == "оживление")
        кандидаты = pn.candidates_for(оживление, индекс)
        self.assertEqual(len(кандидаты), 1)
        self.assertEqual(кандидаты[0].applicability, 1)
        self.assertNotEqual(кандидаты[0].mark, "применимость не измерена")

    def test_у_кандидата_есть_чем_он_выбран(self) -> None:
        индекс = FactIndex(facts=list(ЗДОРОВЫЕ))
        оживление = next(op for op in pn.OPERATIONS if op.name == "оживление")
        строки = pn.candidates_for(оживление, индекс)[0].evidence
        self.assertTrue(строки)
        первая = строки[0]
        # Четыре поля из требования владельца, каждое непустым.
        self.assertTrue(первая.value)
        self.assertTrue(первая.tier)
        self.assertTrue(первая.stated_on)
        self.assertTrue(первая.kind)
        self.assertTrue(первая.matched)


class ПорядокКандидатов(unittest.TestCase):
    """Т5: ключ порядка достижим отдельно от сортировки и от базы."""

    @staticmethod
    def _кандидат(имя: str, применимость: int, способность: int) -> pn.Candidate:
        return pn.Candidate(
            model=имя,
            evidence=(),
            applicability=применимость,
            capability=способность,
            unresolved=0,
            price="цена не записана",
            anchored=применимость + способность,
        )

    def test_измеренное_впереди_заявленного(self) -> None:
        измерен = self._кандидат("а-измерен", 1, 0)
        заявлен = self._кандидат("я-заявлен", 0, 99)
        порядок = sorted([заявлен, измерен], key=pn.by_evidence)
        self.assertEqual([c.model for c in порядок], ["а-измерен", "я-заявлен"])

    def test_имя_с_якорем_решает_ничью(self) -> None:
        безымянный = pn.Candidate("aaa", (), 0, 1, 0, "", anchored=1, named=False)
        именованный = pn.Candidate("zzz-replace", (), 0, 1, 0, "", anchored=1, named=True)
        порядок = sorted([безымянный, именованный], key=pn.by_evidence)
        self.assertEqual([c.model for c in порядок], ["zzz-replace", "aaa"])


#: Пять моделей оживления и у первой из них четыре якорных строки: набор,
#: на котором видны ОБЕ границы печати — сколько кандидатов и сколько
#: доказательств. Оба числа до 2026-09-02 не сторожил никто: мутация в обе
#: стороны не покраснила ни один тест (Т1), и эти два класса заведены ею.
МНОГО: tuple[Fact, ...] = (
    факт("модель-а", "architecture", "image-to-video i2v один", "vendor"),
    факт("модель-а", "max_seconds", "image-to-video i2v два", "vendor"),
    факт("модель-а", "aspect_ratio", "image-to-video i2v три", "vendor"),
    факт("модель-а", "resolution_enum", "image-to-video i2v четыре", "vendor"),
    факт("модель-б", "architecture", "image-to-video i2v", "vendor"),
    факт("модель-в", "architecture", "image-to-video i2v", "vendor"),
    факт("модель-г", "architecture", "image-to-video i2v", "vendor"),
    факт("модель-д", "architecture", "image-to-video i2v", "vendor"),
)


class ГраницыПечати(unittest.TestCase):
    """Сколько кандидатов и сколько доказательств доходит до читателя."""

    def _план(self) -> dict:
        return pn.plan("оживить селфи клиента", facts=list(МНОГО), today=СЕГОДНЯ)

    def test_кандидатов_печатается_ровно_три(self) -> None:
        шаг = self._план()["steps"][0]
        # Пять найдено, показан выбранный плюс ДВЕ запасные: три всего.
        self.assertEqual(шаг["candidates_found"], 5)
        self.assertEqual(len(шаг["alternatives"]), 2)

    def test_доказательств_печатается_ровно_три(self) -> None:
        выбран = self._план()["steps"][0]["chosen"]
        self.assertEqual(выбран["model"], "модель-а")
        self.assertEqual(len(выбран["evidence"]), 3)
        # Е3: счётчики считают ВСЕ строки, а не показанные три.
        self.assertEqual(выбран["capability"] + выбран["unresolved"], 4)


class Цена(unittest.TestCase):
    """Цена не выдумывается: нет сравнимой строки — так и сказано."""

    def test_нет_цены_сказано_словами(self) -> None:
        сказано = pn.cheapest_price(list(ЗДОРОВЫЕ))
        self.assertTrue(сказано.startswith("цена не записана"))

    def test_цена_разобрана(self) -> None:
        свои = list(ЗДОРОВЫЕ) + [
            факт("тестовая-i2v", "price_per_second_usd", "$0.05 per second", "vendor")
        ]
        self.assertIn("usd", pn.cheapest_price(свои))


class ТриИсхода(unittest.TestCase):
    """Р1: годно / не годно / не смогли, и каждый достижим."""

    def test_годно(self) -> None:
        итог = pn.plan(
            "оживить селфи клиента",
            facts=list(ЗДОРОВЫЕ),
            today=СЕГОДНЯ,
        )
        self.assertEqual(итог["outcome"], "pass")
        self.assertEqual(итог["reason"], "план_подтверждён")
        self.assertEqual([s["step"] for s in итог["steps"]], ["оживление"])
        self.assertEqual(итог["classes"], [])

    def test_не_годно_валидатор_назвал_класс(self) -> None:
        итог = pn.plan("оживить селфи клиента", facts=list(БОЛЬНЫЕ), today=СЕГОДНЯ)
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["reason"], "валидатор_отверг")
        self.assertIn("применимость", итог["classes"])
        # План возвращается ВМЕСТЕ с классом: «не годно» без плана нечего чинить.
        self.assertEqual(итог["steps"][0]["chosen"]["model"], "тестовая-i2v")

    def test_не_смогли_шаги_не_выведены(self) -> None:
        итог = pn.plan("сделай красиво", facts=list(ЗДОРОВЫЕ), today=СЕГОДНЯ)
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["reason"], "шаги_не_выведены")
        self.assertEqual(итог["steps"], [])
        self.assertEqual(итог["unmeasured"], 1)

    def test_не_смогли_шаг_без_кандидатов(self) -> None:
        # План НЕ пуст: первый шаг собран, второй назван пустым. Свернуть это в
        # «шагов нет» значило бы потерять то, что человек должен увидеть.
        итог = pn.plan(
            "оживить селфи и добавить фоновые звуки",
            facts=list(ЗДОРОВЫЕ),
            today=СЕГОДНЯ,
        )
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["reason"], "шаг_без_кандидатов")
        self.assertEqual([s["step"] for s in итог["steps"]], ["оживление", "звук_фон"])
        self.assertIsNone(итог["steps"][1]["chosen"])

    def test_модель_по_умолчанию_не_подставляется(self) -> None:
        итог = pn.plan("добавить фоновые звуки, foley", facts=list(ЗДОРОВЫЕ), today=СЕГОДНЯ)
        self.assertEqual(итог["reason"], "шаг_без_кандидатов")
        self.assertIsNone(итог["steps"][0]["chosen"])
        # И в собранной трубе модель шага пустая, а не «какая-нибудь».
        труба = pn.to_pipeline("проба", [(pn.OPERATIONS[5], None)])
        self.assertEqual(труба.steps[0].model, "")

    def test_разрыв_виден_как_не_годно(self) -> None:
        # Липсинку нужно видео, его никто не производит и заказчик о нём не
        # сказал: единственный класс, недостижимый посшаговым вердиктом.
        свои = list(ЗДОРОВЫЕ) + [
            факт("тестовый-липсинк", "architecture", "lipsync talking-head", "vendor"),
            факт("тестовый-липсинк", "license", "apache-2.0", "vendor"),
        ]
        итог = pn.plan("сделай липсинк", facts=свои, today=СЕГОДНЯ)
        self.assertEqual(итог["outcome"], "fail")
        self.assertIn("разрыв", итог["classes"])

    def test_вход_плана_закрывает_разрыв(self) -> None:
        # Видео приходит готовым (его закрывает `inputs_of`), аудио делает
        # шаг дубляжа. Оба требования липсинка закрыты — класса `разрыв` быть
        # не должно, хотя видео не производит ни один шаг плана.
        свои = list(ЗДОРОВЫЕ) + [
            факт("тестовый-липсинк", "architecture", "lipsync talking-head", "vendor"),
            факт("тестовый-липсинк", "license", "apache-2.0", "vendor"),
            факт("тестовый-дубляж", "architecture", "dubbing dub", "vendor"),
            факт("тестовый-дубляж", "license", "apache-2.0", "vendor"),
        ]
        итог = pn.plan(
            "из готового ролика сделай липсинк под другой язык", facts=свои, today=СЕГОДНЯ
        )
        self.assertNotIn("разрыв", итог["classes"])
        липсинк = next(s for s in итог["steps"] if s["step"] == "липсинк")
        self.assertEqual(липсинк["input_of_plan"], ["видео"])


class Контракт(unittest.TestCase):
    """Что обязано держаться, чтобы модуль вообще имел смысл."""

    def test_коды_причин_названы_литералами(self) -> None:
        self.assertEqual(
            sorted(pn.REASONS),
            sorted(
                [
                    "шаги_не_выведены",
                    "шаг_без_кандидатов",
                    "валидатор_отверг",
                    "план_не_подтверждён",
                    "план_подтверждён",
                ]
            ),
        )

    def test_каждая_операция_производит_то_что_требует_следующая(self) -> None:
        # Порядок словаря — порядок плана. Всё, что требуется, обязано быть
        # либо входом плана, либо произведено РАНЬШЕ по словарю.
        доступно = {"бриф", "селфи", "референс"}
        for op in pn.OPERATIONS:
            for нужно in op.requires:
                self.assertIn(нужно, доступно, f"{op.name} требует {нужно} раньше, чем его делают")
            доступно.update(op.produces)

    def test_класс_а_не_модель_в_кандидаты_не_идёт(self) -> None:
        свои = list(ЗДОРОВЫЕ) + [
            факт("*", "failure_mode", "image-to-video i2v ломается у всех", "paper")
        ]
        индекс = FactIndex(facts=свои)
        оживление = next(op for op in pn.OPERATIONS if op.name == "оживление")
        имена = [c.model for c in pn.candidates_for(оживление, индекс)]
        self.assertNotIn("*", имена)

    def test_контрольный_набор_читается_целиком(self) -> None:
        self.assertEqual(pn.rows_in(), len(pn.briefs()))
        self.assertEqual(len(pn.briefs()), 8)


if __name__ == "__main__":
    unittest.main()
