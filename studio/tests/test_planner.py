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

import tempfile
import unittest
from datetime import date
from pathlib import Path

from PIL import Image

from studio import planner as pn
from studio import pricing
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

    def test_относительная_цена_ценой_не_считается(self) -> None:
        # `price_relative = "50% lower"` проходит подстроечный фильтр
        # валидатора (`pipeline.PRICE_MARKERS` содержит "price") и ценой НЕ
        # является: разборщик однажды прочёл эту строку как 50.0. Отбор имён
        # делает `studio/selfrag/attrfamily.py`, и он её выбрасывает.
        свои = list(ЗДОРОВЫЕ) + [
            факт("тестовая-i2v", "price_relative", "50% lower price per character", "vendor"),
            факт("тестовая-i2v", "storage_cost", "$0.01 per GB per month", "vendor"),
        ]
        self.assertEqual([f.attribute for f in pn.price_facts(свои)], [])


class РазборБюджета(unittest.TestCase):
    """Т5: потолок разбирается из фразы заказчика, и не выдумывается (И5)."""

    def test_единица_названа_числом_и_словом(self) -> None:
        b = pn.budget_from("нужен липсинк, бюджет 0.5 доллара")
        self.assertEqual(b.amount, 0.5)
        self.assertEqual(b.unit, "usd")
        self.assertEqual(b.outcome, "pass")

    def test_доллар_значком_и_запятой(self) -> None:
        b = pn.budget_from("нужен липсинк, бюджет $0,05 за секунду")
        self.assertEqual(b.amount, 0.05)
        self.assertEqual(b.per, ("second",))

    def test_за_что_названо_словами(self) -> None:
        b = pn.budget_from("не дороже 2 долларов за ролик")
        self.assertEqual(b.amount, 2.0)
        self.assertEqual(sorted(b.per), ["generation", "run"])

    def test_за_что_не_названо_принимается_за_прогон(self) -> None:
        b = pn.budget_from("бюджет 1 доллар")
        # Литерал (Т2): «за прогон шага» — это то, куда уходит число.
        self.assertEqual(sorted(b.per), ["generation", "run"])
        self.assertIn("за прогон шага", b.note)

    def test_число_без_единицы_третий_исход(self) -> None:
        # И5, негативный контроль: 50 чего — из брифа не следует.
        b = pn.budget_from("оживить фото клиента, бюджет 50")
        self.assertIsNone(b.amount)
        self.assertEqual(b.outcome, "could not measure")
        self.assertIn("бюджет", b.note)

    def test_бюджета_нет_вовсе(self) -> None:
        b = pn.budget_from("оживить фото клиента, 10 секунд")
        self.assertIsNone(b.amount)
        self.assertEqual(b.outcome, "could not measure")

    def test_два_третьих_исхода_различимы(self) -> None:
        # «сказано, но нечитаемо» и «не сказано» — РАЗНЫЕ ноты: человеку в них
        # отвечают разное. Свернуть их в одну значит потерять, что переспросить.
        сказано = pn.budget_from("бюджет ограничен")
        молчание = pn.budget_from("оживить фото")
        self.assertNotEqual(сказано.note, молчание.note)

    def test_число_длительности_не_бюджет(self) -> None:
        # Негативный контроль на разборщик: «15 секунд» и «10 секунд» — числа,
        # но не деньги, и потолком стать не должны.
        for бриф in ("с нуля: видео 15 секунд", "оживить фото, 10 секунд, крупный план"):
            self.assertIsNone(pn.budget_from(бриф).amount, бриф)


class ЦенаВОтборе(unittest.TestCase):
    """Четыре положения по цене и их порядок. Т5: ключ достижим без базы."""

    @staticmethod
    def _к(имя: str, состояние: str, применимость: int = 0) -> pn.Candidate:
        return pn.Candidate(
            model=имя,
            evidence=(),
            applicability=применимость,
            capability=1,
            unresolved=0,
            price="",
            anchored=1,
            price_state=состояние,
        )

    def test_положений_ровно_четыре_и_они_названы_литералами(self) -> None:
        self.assertEqual(
            sorted(pn.PRICE_ORDER),
            sorted(
                [
                    "в бюджете",
                    "цена записана, но с бюджетом несравнима",
                    "цена не записана",
                    "дороже бюджета",
                ]
            ),
        )

    def test_в_бюджете_впереди_незаписанной_цены(self) -> None:
        # Главное требование: кандидат с НЕЗАПИСАННОЙ ценой не обходит того,
        # чья цена измерена и в потолок укладывается, — даже имея больше
        # строк применимости.
        дешёвый = self._к("а-дешёвый", "в бюджете", применимость=0)
        немой = self._к("б-немой", "цена не записана", применимость=5)
        порядок = sorted([немой, дешёвый], key=pn.by_evidence)
        self.assertEqual([c.model for c in порядок], ["а-дешёвый", "б-немой"])

    def test_записанная_но_несравнимая_впереди_незаписанной(self) -> None:
        # Это и был второй дефект: два РАЗНЫХ состояния печатались одинаково.
        есть = self._к("а-есть-число", "цена записана, но с бюджетом несравнима")
        нет = self._к("б-нет-строки", "цена не записана")
        порядок = sorted([нет, есть], key=pn.by_evidence)
        self.assertEqual([c.model for c in порядок], ["а-есть-число", "б-нет-строки"])

    def test_дороже_бюджета_последний_но_не_выброшен(self) -> None:
        дорогой = self._к("а-дорогой", "дороже бюджета", применимость=9)
        немой = self._к("я-немой", "цена не записана", применимость=0)
        порядок = sorted([дорогой, немой], key=pn.by_evidence)
        self.assertEqual([c.model for c in порядок], ["я-немой", "а-дорогой"])

    def test_без_потолка_цена_не_решает_ничего(self) -> None:
        # Потолка нет — поле пустое у всех, и порядок возвращается к доводам.
        измерен = self._к("я-измерен", "", применимость=3)
        нет = self._к("а-нет", "", применимость=0)
        порядок = sorted([нет, измерен], key=pn.by_evidence)
        self.assertEqual([c.model for c in порядок], ["я-измерен", "а-нет"])

    def test_положение_считается_по_записанной_цене(self) -> None:
        свои = [
            факт("м", "price_per_run_usd", "$0.10 per run", "vendor"),
            факт("м", "license", "apache-2.0", "vendor"),
        ]
        дёшево = pn.budget_from("бюджет 1 доллар за ролик")
        дорого = pn.budget_from("бюджет 0.01 доллара за ролик")
        self.assertEqual(pn.price_stance(свои, дёшево)[0], "в бюджете")
        self.assertEqual(pn.price_stance(свои, дорого)[0], "дороже бюджета")

    def test_другое_за_что_несравнимо_а_не_дороже(self) -> None:
        # $/секунда против потолка «за ролик» — сравнить НЕЛЬЗЯ, и это третий
        # исход, а не отказ и не проход.
        свои = [факт("м", "price_per_second_usd", "$0.05 per second", "vendor")]
        состояние, _ = pn.price_stance(свои, pn.budget_from("бюджет 1 доллар за ролик"))
        self.assertEqual(состояние, "цена записана, но с бюджетом несравнима")

    def test_ни_строки_о_цене(self) -> None:
        состояние, _ = pn.price_stance(list(ЗДОРОВЫЕ), pn.budget_from("бюджет 1 доллар"))
        self.assertEqual(состояние, "цена не записана")


#: Настоящий креатив владельца: вертикальный кадр 1536x2752. На нём и найден
#: дефект — замеры креатива были украшением, до отбора кандидата не доезжали.
СЕЛФИ = Path(__file__).resolve().parents[2] / "assets" / "fork_client_selfie_f.png"

#: Модели с записанными пределами кадра: одна берёт 4K, одна упирается в 1280,
#: одна написана так, что разобрать нельзя. Т3: края и середина.
ПРЕДЕЛЫ: tuple[Fact, ...] = (
    факт("берёт-4k", "max_resolution", "4K", "vendor"),
    факт("берёт-4k", "architecture", "image-to-video i2v", "vendor"),
    факт("не-берёт", "max_resolution", "1280x720", "vendor"),
    факт("не-берёт", "architecture", "image-to-video i2v", "vendor"),
    факт("не-разобрать", "max_resolution", "up to 4MP output", "vendor"),
    факт("не-разобрать", "architecture", "image-to-video i2v", "vendor"),
    факт("молчит", "architecture", "image-to-video i2v", "vendor"),
)


class ЗамерКреатива(unittest.TestCase):
    """Т5: кадр меряется отдельно от плана, и «не смогли» здесь настоящее."""

    def test_креатив_не_подан(self) -> None:
        кадр, нота = pn.frame_of("")
        self.assertIsNone(кадр)
        self.assertIn("не подан", нота)

    def test_файла_нет_третий_исход(self) -> None:
        # Не исключение и не «принимает»: названная причина.
        кадр, нота = pn.frame_of("/нет/такого/файла.png")
        self.assertIsNone(кадр)
        self.assertTrue(нота)

    def test_настоящий_креатив_измерен(self) -> None:
        self.assertTrue(СЕЛФИ.is_file(), СЕЛФИ)
        кадр, нота = pn.frame_of(str(СЕЛФИ))
        # Литералы (Т2): стороны файла владельца, а не импорт из модуля.
        self.assertEqual(кадр, (1536, 2752))
        self.assertIn("1536x2752", нота)

    def test_меряет_тот_же_прибор_что_analyse_creative(self) -> None:
        # Е1: своего измерителя нет. Если поле выдачи `analyse_creative`
        # поедет, оно обязано поехать здесь в тот же миг, а не молча.
        from studio.mcp import creative as _creative

        итог = _creative.analyse(str(СЕЛФИ))
        замеры = итог["parts"]["look"]["measurements"]
        кадр, _ = pn.frame_of(str(СЕЛФИ))
        self.assertEqual(кадр, (int(замеры["width"]), int(замеры["height"])))


class КадрПротивПредела(unittest.TestCase):
    """Четыре положения по кадру, и «предел не записан» — не «принимает»."""

    def test_кадр_не_подан_положение_пустое(self) -> None:
        состояние, _ = pn.fit_stance(list(ПРЕДЕЛЫ), None)
        self.assertEqual(состояние, "")

    def test_предела_нет_вовсе(self) -> None:
        свои = [f for f in ПРЕДЕЛЫ if f.model == "молчит"]
        состояние, нота = pn.fit_stance(свои, (1536, 2752))
        # Литерал (Т2): текст положения — часть контракта.
        self.assertEqual(состояние, "предел кадра не записан")
        self.assertIn("0", нота)

    def test_кадр_принимается(self) -> None:
        свои = [f for f in ПРЕДЕЛЫ if f.model == "берёт-4k"]
        состояние, нота = pn.fit_stance(свои, (1536, 2752))
        self.assertEqual(состояние, "кадр принимается")
        # Требование владельца: креатив, предел и ИСХОДНАЯ строка источника.
        self.assertIn("1536x2752", нота)
        self.assertIn("max_resolution", нота)
        self.assertIn("example.invalid", нота)

    def test_кадр_не_принимается(self) -> None:
        свои = [f for f in ПРЕДЕЛЫ if f.model == "не-берёт"]
        состояние, нота = pn.fit_stance(свои, (1536, 2752))
        self.assertEqual(состояние, "кадр НЕ принимается")
        self.assertIn("1536x2752", нота)
        self.assertIn("1280", нота)

    def test_предел_записан_но_не_разобран(self) -> None:
        свои = [f for f in ПРЕДЕЛЫ if f.model == "не-разобрать"]
        состояние, _ = pn.fit_stance(свои, (1536, 2752))
        self.assertEqual(состояние, "предел записан, но не разобран")

    def test_неразобранная_строка_не_даёт_отказа(self) -> None:
        # Сильное утверждение «ни один режим не берёт этот кадр» требует, чтобы
        # неразобранных строк не осталось: неразобранная оставляет место режиму,
        # которого мы не прочли.
        свои = [
            факт("м", "max_resolution", "1280x720", "vendor"),
            факт("м", "resolution_note", "up to 4MP output", "vendor"),
        ]
        состояние, _ = pn.fit_stance(свои, (1536, 2752))
        self.assertEqual(состояние, "предел записан, но не разобран")

    def test_один_принимающий_режим_решает(self) -> None:
        # Строки модели описывают разные режимы: если хоть один берёт кадр,
        # модель его берёт. Брать строжайшую строку значило бы отвергать модель
        # за то, что у неё есть ещё и мелкий режим.
        свои = [
            факт("м", "max_resolution", "4K", "vendor"),
            факт("м", "resolution_enum", "1280x720", "vendor"),
        ]
        состояние, _ = pn.fit_stance(свои, (1536, 2752))
        self.assertEqual(состояние, "кадр принимается")

    def test_разрешение_обучения_пределом_не_считается(self) -> None:
        свои = [факт("м", "training_resolution", "512x512", "vendor")]
        self.assertEqual([f.attribute for f in pn.limit_facts(свои)], [])
        состояние, _ = pn.fit_stance(свои, (1536, 2752))
        self.assertEqual(состояние, "предел кадра не записан")

    def test_положений_ровно_четыре_и_названы_литералами(self) -> None:
        self.assertEqual(
            sorted(pn.FIT_ORDER),
            sorted(
                [
                    "кадр принимается",
                    "предел записан, но не разобран",
                    "предел кадра не записан",
                    "кадр НЕ принимается",
                ]
            ),
        )

    def test_порядок_положений_по_кадру(self) -> None:
        def к(имя: str, состояние: str) -> pn.Candidate:
            return pn.Candidate(имя, (), 0, 1, 0, "", anchored=1, fit_state=состояние)

        # ИМЕНА НАРОЧНО В ОБРАТНОМ АЛФАВИТНОМ ПОРЯДКЕ к ожидаемому. Первая
        # версия этого теста называла их «а-принимает»…«г-не-принимает», и
        # алфавит сам давал нужный ответ: мутация «четыре положения сливаются в
        # одно» не покраснила НИ ОДИН тест (Т1, 2026-09-02). Тест, который
        # проходит и без проверяемой развилки, не сторожит ничего.
        порядок = sorted(
            [
                к("а-не-принимает", "кадр НЕ принимается"),
                к("б-не-записан", "предел кадра не записан"),
                к("в-не-разобран", "предел записан, но не разобран"),
                к("г-принимает", "кадр принимается"),
            ],
            key=pn.by_evidence,
        )
        self.assertEqual(
            [c.model for c in порядок],
            ["г-принимает", "в-не-разобран", "б-не-записан", "а-не-принимает"],
        )

    def test_кадр_старше_цены(self) -> None:
        # Модель, которая кадра не принимает, не запустится вовсе; модель дороже
        # потолка запустится и сделает работу, просто дорого.
        дешёвый_но_мелкий = pn.Candidate(
            "а-мелкий",
            (),
            9,
            9,
            0,
            "",
            anchored=9,
            fit_state="кадр НЕ принимается",
            price_state="в бюджете",
        )
        дорогой_но_берёт = pn.Candidate(
            "я-берёт",
            (),
            0,
            0,
            0,
            "",
            anchored=1,
            fit_state="кадр принимается",
            price_state="дороже бюджета",
        )
        порядок = sorted([дешёвый_но_мелкий, дорогой_но_берёт], key=pn.by_evidence)
        self.assertEqual([c.model for c in порядок], ["я-берёт", "а-мелкий"])

    def test_без_кадра_порядок_не_меняется_вовсе(self) -> None:
        # НЕГАТИВНЫЙ КОНТРОЛЬ (а): без креатива не должно измениться ни строки,
        # ни порядка.
        без = pn.plan("оживить селфи клиента", facts=list(ПРЕДЕЛЫ), today=СЕГОДНЯ)
        шаг = без["steps"][0]
        self.assertEqual(шаг["chosen"]["fit_state"], "")
        for а in шаг["alternatives"]:
            self.assertEqual(а["fit_state"], "")
        self.assertIsNone(без["creative"]["width"])
        self.assertNotIn("      кадр:", pn.render(без))

    def test_с_кадром_не_принимающий_уходит_вниз(self) -> None:
        # НЕГАТИВНЫЙ КОНТРОЛЬ (б), первая половина: отказ обязан быть виден и
        # обязан быть последним.
        with_ = pn.plan(
            "оживить селфи клиента",
            facts=list(ПРЕДЕЛЫ),
            creative=str(СЕЛФИ),
            today=СЕГОДНЯ,
        )
        шаг = with_["steps"][0]
        self.assertEqual(шаг["chosen"]["model"], "берёт-4k")
        self.assertEqual(шаг["chosen"]["fit_state"], "кадр принимается")
        # Проверяется ВЕСЬ порядок, а не три показанных: `alternatives` короче
        # набора по `CANDIDATES_SHOWN`, и «последний из показанных» — не то же
        # самое, что «последний из найденных».
        весь = pn.candidates_for(
            next(o for o in pn.OPERATIONS if o.name == "оживление"),
            FactIndex(facts=list(ПРЕДЕЛЫ)),
            None,
            None,
            (1536, 2752),
        )
        self.assertEqual([c.model for c in весь][-1], "не-берёт")
        self.assertNotIn("не-берёт", [а["model"] for а in шаг["alternatives"]])
        # Отвергнутый уходит в конец и потому НЕ попадает в показанные — но
        # молчать о нём нельзя: одна строка на шаг называет его поимённо.
        напечатано = pn.render(with_)
        self.assertIn("КАДР ОТВЁРГ КАНДИДАТОВ", напечатано)
        self.assertIn("не-берёт", напечатано)
        self.assertIn("1536x2752", напечатано)
        self.assertIn("1280", шаг["rejected_by_frame"])

    def test_кадр_который_влезает_всем_не_даёт_ни_отказа_ни_шума(self) -> None:
        # НЕГАТИВНЫЙ КОНТРОЛЬ (б), вторая половина: на маленьком кадре ни одна
        # модель не отвергается, и прибор об этом молчит вместо того, чтобы
        # находить проблему там, где её нет.
        мелкий = Path(tempfile.mkdtemp()) / "мелкий.png"
        Image.new("RGB", (64, 64), (128, 128, 128)).save(мелкий)
        итог = pn.plan(
            "оживить селфи клиента",
            facts=list(ПРЕДЕЛЫ),
            creative=str(мелкий),
            today=СЕГОДНЯ,
        )
        шаг = итог["steps"][0]
        состояния = [шаг["chosen"]["fit_state"]] + [а["fit_state"] for а in шаг["alternatives"]]
        self.assertNotIn("кадр НЕ принимается", состояния)
        self.assertIn("кадр не принимают 0", итог["note"])
        # И ни одной строки об отказе: находить беду там, где её нет, — шум.
        self.assertEqual(шаг["rejected_by_frame"], "")
        self.assertNotIn("КАДР ОТВЁРГ", pn.render(итог))


class ОтвергнутыеКадром(unittest.TestCase):
    """Т5: строка об отвергнутых кадром считается без базы и без плана."""

    @staticmethod
    def _к(имя: str, состояние: str) -> pn.Candidate:
        return pn.Candidate(имя, (), 0, 1, 0, "", anchored=1, fit_state=состояние, fit_note="нота")

    def test_отвергать_некого_молчит(self) -> None:
        свои = [self._к("а", "кадр принимается"), self._к("б", "предел кадра не записан")]
        self.assertEqual(pn.frame_rejects_line(свои), "")

    def test_один_отвергнутый_назван(self) -> None:
        свои = [self._к("а", "кадр принимается"), self._к("б", "кадр НЕ принимается")]
        сказано = pn.frame_rejects_line(свои)
        self.assertTrue(сказано.startswith("КАДР ОТВЁРГ КАНДИДАТОВ"))
        self.assertIn("б", сказано)
        self.assertNotIn("и ещё", сказано)

    def test_остальные_числом_а_не_списком(self) -> None:
        свои = [self._к(и, "кадр НЕ принимается") for и in ("а", "б", "в")]
        сказано = pn.frame_rejects_line(свои)
        self.assertIn("и ещё 2", сказано)
        self.assertNotIn("в", сказано.split(" — ")[0].replace("КАДР ОТВЁРГ КАНДИДАТОВ", ""))


class КлючиЗаказчика(unittest.TestCase):
    """`CUSTOMER_KEYS` — сколько первых полей ключа приходят СНАРУЖИ."""

    def test_их_ровно_столько_сколько_названо(self) -> None:
        # Литералы (Т2): два первых поля — кадр и цена.
        self.assertEqual(pn.CUSTOMER_KEYS, 2)
        self.assertEqual(
            list(pn.KEY_FIELDS[: pn.CUSTOMER_KEYS]),
            ["принимает ли кадр", "положение по цене"],
        )

    def test_ни_кадр_ни_цена_не_решают_кто_доказан(self) -> None:
        # Регрессия 2026-09-02: `proven` роняла один первый ключ, кадр встал
        # перед ценой — и цена вернулась в выбор вытесненного молча.
        слабый_но_удобный = pn.Candidate(
            "а-удобный",
            (),
            1,
            1,
            0,
            "",
            anchored=1,
            fit_state="кадр принимается",
            price_state="в бюджете",
        )
        сильный_но_неудобный = pn.Candidate(
            "я-сильный",
            (),
            5,
            5,
            0,
            "",
            anchored=5,
            fit_state="кадр НЕ принимается",
            price_state="дороже бюджета",
        )
        порядок = pn.proven([слабый_но_удобный, сильный_но_неудобный])
        self.assertEqual([c.model for c in порядок], ["я-сильный", "а-удобный"])


class ПереводЗаЧто(unittest.TestCase):
    """Точный перевод внутри одного измерения — и запрет на всё остальное.

    Найдено чтением выдачи 2026-09-02 (П3): на «дубляж..., бюджет $0.10 за
    секунду» прибор говорил «цена записана, но с бюджетом НЕСРАВНИМА» о цене
    `0.6 usd за minute`, то есть о $0.01 за секунду — в потолок с десятикратным
    запасом.

    Здесь проверяются ДВА РАЗНЫХ запрета, которые до этого были слиты в один:
    единица (кредиты -> доллары) не переводится НИКОГДА, потому что курс
    назначает вендор; «за что» (минута -> секунда) переводится, потому что
    шестьдесят — определение единицы.
    """

    @staticmethod
    def _цена(amount: float, unit: str, per: str) -> pricing.Price:
        return pricing.Price(
            amount=amount, unit=unit, per=per, conditional=False, outcome="годно", note=""
        )

    def test_минута_переводится_в_секунду(self) -> None:
        сколько, откуда = pn.to_budget_per(
            self._цена(0.6, "usd", "minute"), pn.budget_from("бюджет $0.10 за секунду")
        )
        self.assertIsNotNone(сколько)
        # Литерал (Т2): 0.6 / 60 = 0.01, и делитель здесь не импортируется.
        self.assertAlmostEqual(float(сколько or 0.0), 0.01, places=9)
        self.assertIn("ПЕРЕВЕДЕНО НАМИ", откуда)
        # Исходная строка обязана стоять рядом с переведённой.
        self.assertIn("0.6", откуда)
        self.assertIn("minute", откуда)
        self.assertIn("second", откуда)

    def test_секунда_переводится_в_минуту(self) -> None:
        сколько, откуда = pn.to_budget_per(
            self._цена(0.01, "usd", "second"), pn.budget_from("бюджет $1 за минуту")
        )
        self.assertAlmostEqual(float(сколько or 0.0), 0.6, places=9)
        self.assertIn("ПЕРЕВЕДЕНО НАМИ", откуда)

    def test_совпавшее_за_что_переводом_не_называется(self) -> None:
        сколько, откуда = pn.to_budget_per(
            self._цена(0.05, "usd", "second"), pn.budget_from("бюджет $0.10 за секунду")
        )
        self.assertEqual(сколько, 0.05)
        # Ничего не считали — и говорить о переводе нечего: иначе пометка
        # обесценится там, где она действительно нужна.
        self.assertEqual(откуда, "")

    def test_кредиты_в_доллары_не_переводятся_никогда(self) -> None:
        # НЕГАТИВНЫЙ КОНТРОЛЬ, ради которого запреты и разведены: курс кредита
        # к доллару — решение вендора, оно нигде не записано, и «курс по
        # умолчанию» обязан ронять этот тест.
        for за_что in ("second", "minute", "run"):
            сколько, откуда = pn.to_budget_per(
                self._цена(40.0, "credits", за_что), pn.budget_from("бюджет $0.10 за секунду")
            )
            self.assertIsNone(сколько, за_что)
            self.assertEqual(откуда, "")

    def test_картинка_и_мегапиксель_не_переводятся(self) -> None:
        # Сколько мегапикселей в картинке — свойство картинки, а не определение.
        сколько, _ = pn.to_budget_per(
            self._цена(0.03, "usd", "megapixel"), pn.budget_from("бюджет $0.10 за кадр")
        )
        self.assertIsNone(сколько)

    def test_знаки_и_токены_не_переводятся(self) -> None:
        # Сколько знаков в токене — свойство модели и текста, у разных разное.
        сколько, _ = pn.to_budget_per(
            self._цена(0.1, "usd", "1000_chars"), pn.budget_from("бюджет $0.10 за секунду")
        )
        self.assertIsNone(сколько)

    def test_таблица_перевода_закрытая_и_известная_разборщику(self) -> None:
        # Каждое «за что» таблицы обязано существовать у разборщика цен (Ц10),
        # и единицы в таблице нет вовсе — переводить её нечем и незачем.
        for из_, в in pn.PER_CONVERSION:
            self.assertIn(из_, pricing.PER)
            self.assertIn(в, pricing.PER)
        плоско = {p for пара in pn.PER_CONVERSION for p in пара}
        self.assertEqual(плоско, {"minute", "second"})
        self.assertNotIn("credits", плоско)
        self.assertNotIn("usd", плоско)

    def test_положение_считается_по_переведённой_цене(self) -> None:
        свои = [факт("м", "price_per_minute", "$0.6 per minute", "vendor")]
        # 0.6/мин = 0.01/с: в потолок 0.10/с укладывается...
        состояние, нота = pn.price_stance(свои, pn.budget_from("бюджет $0.10 за секунду"))
        self.assertEqual(состояние, "в бюджете")
        self.assertIn("ПЕРЕВЕДЕНО НАМИ", нота)
        # ...и в потолок 0.001/с — нет. Перевод обязан работать в обе стороны.
        строже, _ = pn.price_stance(свои, pn.budget_from("бюджет $0.001 за секунду"))
        self.assertEqual(строже, "дороже бюджета")

    def test_потолок_за_секунду_валидатору_не_передаётся(self) -> None:
        # Поле `pipeline.Step.budget_usd` — бюджет ШАГА, и посекундный потолок
        # в нём даёт класс `цена` там, где модель укладывается десятикратно.
        свои = [
            факт("м-lipsync", "price_per_minute", "$0.6 per minute", "vendor"),
            факт("м-lipsync", "architecture", "lipsync talking-head", "vendor"),
            факт("м-lipsync", "license", "apache-2.0", "vendor"),
        ]
        посекундный = pn.plan(
            "из готового ролика сделай липсинк под другой язык, бюджет $0.10 за секунду",
            facts=свои,
            today=СЕГОДНЯ,
        )
        self.assertNotIn("цена", посекундный["classes"])
        self.assertIn("НЕ передан", посекундный["budget"]["note"])

    def test_потолок_за_ролик_валидатору_передаётся(self) -> None:
        # Обратная сторона (И5): пошаговый потолок обязан доезжать до
        # валидатора, иначе «класс цена не сработал» означало бы «его выключили».
        свои = [
            факт("м-lipsync", "price_per_run_usd", "$9.00 per run", "vendor"),
            факт("м-lipsync", "architecture", "lipsync talking-head", "vendor"),
            факт("м-lipsync", "license", "apache-2.0", "vendor"),
        ]
        пошаговый = pn.plan(
            "из готового ролика сделай липсинк под другой язык, бюджет $0.10 за ролик",
            facts=свои,
            today=СЕГОДНЯ,
        )
        self.assertIn("цена", пошаговый["classes"])
        self.assertNotIn("НЕ передан", пошаговый["budget"]["note"])


class ПочемуНеСосед(unittest.TestCase):
    """Строка «почему выбран этот, а не соседний» считается из самого ключа."""

    def test_называется_первое_разошедшееся_поле(self) -> None:
        первый = pn.Candidate("а", (), 3, 1, 0, "", anchored=5)
        второй = pn.Candidate("б", (), 1, 1, 0, "", anchored=5)
        сказано = pn.why_not(первый, второй)
        self.assertIn("строк применимости", сказано)
        self.assertIn("3 против 1", сказано)

    def test_поля_ключа_и_имена_совпадают_числом(self) -> None:
        c = pn.Candidate("а", (), 0, 0, 0, "")
        self.assertEqual(len(pn.by_evidence(c)), len(pn.KEY_FIELDS))

    def test_неразличимые_названы_неразличимыми(self) -> None:
        a = pn.Candidate("одинаково", (), 1, 1, 0, "", anchored=1)
        сказано = pn.why_not(a, a)
        self.assertIn("неразличимы", сказано)


#: Дешёвая непроверенная модель и дорогая проверенная — набор, на котором
#: видно ОБА направления: без потолка выбирается проверенная, с потолком её
#: отодвигает цена, и ровно тогда обязана появиться строка о вытесненном.
#: Оба имени несут якорь `lipsync`, чтобы отбор решался доводами, а не именем.
ЦЕНА_ПРОТИВ_ДОКАЗАТЕЛЬСТВА: tuple[Fact, ...] = (
    факт("дешёвый-lipsync", "price_per_run_usd", "$0.01 per run", "vendor"),
    факт("дешёвый-lipsync", "architecture", "lipsync talking-head", "vendor"),
    факт("дешёвый-lipsync", "license", "apache-2.0", "vendor"),
    факт(
        "проверенный-lipsync",
        "observed_behaviour",
        "lipsync talking-head: запустили, губы держат синхрон всю реплику",
        "operator",
    ),
    факт("проверенный-lipsync", "architecture", "lipsync talking-head", "vendor"),
    факт("проверенный-lipsync", "license", "apache-2.0", "vendor"),
)


class ВытесненныйЦеной(unittest.TestCase):
    """Проверенный кандидат, которого цена отодвинула, обязан быть НАЗВАН.

    Найдено чтением выдачи 2026-09-02 (П3): на брифе с потолком все три
    показанных кандидата шли с неизмеренной применимостью, а четыре
    проверенных уехали вниз из двадцати восьми и в выдачу не попали вовсе.
    Каждая строка была правдой; неверен был заголовок.
    """

    @staticmethod
    def _к(имя: str, применимость: int, состояние: str = "") -> pn.Candidate:
        return pn.Candidate(
            model=имя,
            evidence=(),
            applicability=применимость,
            capability=1,
            unresolved=0,
            price="цена не записана",
            anchored=1,
            price_state=состояние,
        )

    def test_выбранный_сам_проверен_строки_нет(self) -> None:
        # Негативный контроль (а): строка здесь была бы шумом.
        выбран = self._к("выбран", 2, "цена не записана")
        сосед = self._к("сосед", 1, "в бюджете")
        self.assertEqual(pn.rival_line(выбран, [выбран, сосед]), "")

    def test_кандидата_нет_вовсе_строки_нет(self) -> None:
        self.assertEqual(pn.rival_line(None, []), "")

    def test_проверенный_есть_и_назван(self) -> None:
        выбран = self._к("дешёвый", 0, "в бюджете")
        сильный = self._к("проверенный", 2, "цена не записана")
        слабый = self._к("тоже-проверенный", 1, "цена не записана")
        сказано = pn.rival_line(выбран, [выбран, слабый, сильный])
        # Литералы (Т2): текст пометки — часть контракта.
        self.assertTrue(сказано.startswith("ПРОВЕРЕННЫЙ ЕСТЬ, НО ЦЕНА ЕГО ОТОДВИНУЛА"))
        self.assertIn("проверенный", сказано)
        # Назван СИЛЬНЕЙШИЙ из проверенных, а не первый попавшийся.
        self.assertNotIn("тоже-проверенный", сказано)
        # И сказано, ЧЕМ он проиграл.
        self.assertIn("положение по цене", сказано)

    def test_проверенных_нет_другими_словами(self) -> None:
        # Негативный контроль (б): положение ДРУГОЕ, и молчание тут было бы
        # неотличимо от молчания в случае «проверенный выбран».
        выбран = self._к("дешёвый", 0, "в бюджете")
        сосед = self._к("тоже-дешёвый", 0, "в бюджете")
        сказано = pn.rival_line(выбран, [выбран, сосед])
        self.assertTrue(сказано.startswith("ПРОВЕРЕННЫХ НЕТ ВОВСЕ"))
        self.assertNotIn("ОТОДВИНУЛА", сказано)
        self.assertIn("2", сказано)

    def test_три_положения_печатаются_по_разному(self) -> None:
        проверен = self._к("а", 2, "в бюджете")
        дешёвый = self._к("б", 0, "в бюджете")
        сильный = self._к("в", 3, "цена не записана")
        пусто = pn.rival_line(проверен, [проверен, дешёвый])
        есть = pn.rival_line(дешёвый, [дешёвый, сильный])
        нету = pn.rival_line(дешёвый, [дешёвый])
        self.assertEqual(len({пусто, есть, нету}), 3)

    def test_сам_себя_вытесненным_не_называет(self) -> None:
        # Порог мутируем; при RIVAL_MIN_APPLICABILITY = 0 выбранный попал бы в
        # список проверенных и назвал бы вытесненным сам себя.
        выбран = self._к("выбран", 0, "в бюджете")
        сказано = pn.rival_line(выбран, [выбран])
        self.assertNotIn("выбран —", сказано)
        self.assertTrue(сказано.startswith("ПРОВЕРЕННЫХ НЕТ ВОВСЕ"))

    def test_порог_проверенности_ровно_одна_строка(self) -> None:
        одна = self._к("одна-строка", 1)
        ноль = self._к("ноль-строк", 0)
        self.assertEqual([c.model for c in pn.proven([одна, ноль])], ["одна-строка"])

    def test_сильнейший_проверенный_выбирается_без_цены(self) -> None:
        # Вопрос «кто сильнее доказан» решается доводами, а не ценой: иначе
        # вытесненным назывался бы тот же, кого цена и подняла наверх.
        дешёвый_слабый = self._к("а-дешёвый", 1, "в бюджете")
        дорогой_сильный = self._к("я-дорогой", 5, "дороже бюджета")
        self.assertEqual(
            [c.model for c in pn.proven([дешёвый_слабый, дорогой_сильный])],
            ["я-дорогой", "а-дешёвый"],
        )

    def test_без_потолка_вытеснить_некому(self) -> None:
        # Ветка «выбран непроверенный, а проверенный есть» достижима ТОЛЬКО
        # когда цена переставила порядок, и это следует из ключа, а не из
        # отдельного флага. Без потолка старшим ключом становится применимость.
        итог = pn.plan(
            "нужен липсинк на готовое видео",
            facts=list(ЦЕНА_ПРОТИВ_ДОКАЗАТЕЛЬСТВА),
            today=СЕГОДНЯ,
        )
        шаг = итог["steps"][0]
        self.assertEqual(шаг["chosen"]["model"], "проверенный-lipsync")
        self.assertEqual(шаг["proven_rival"], "")

    def test_с_потолком_вытесненный_назван(self) -> None:
        # Та же база, тот же бриф плюс потолок: цена переставляет порядок, и
        # строка обязана появиться.
        итог = pn.plan(
            "нужен липсинк на готовое видео, бюджет 1 доллар за ролик",
            facts=list(ЦЕНА_ПРОТИВ_ДОКАЗАТЕЛЬСТВА),
            today=СЕГОДНЯ,
        )
        шаг = итог["steps"][0]
        self.assertEqual(шаг["chosen"]["model"], "дешёвый-lipsync")
        self.assertTrue(шаг["proven_rival"].startswith("ПРОВЕРЕННЫЙ ЕСТЬ, НО ЦЕНА ЕГО ОТОДВИНУЛА"))
        self.assertIn("проверенный-lipsync", шаг["proven_rival"])

    def test_числа_вытеснения_стоят_в_ноте(self) -> None:
        итог = pn.plan(
            "нужен липсинк на готовое видео, бюджет 1 доллар за ролик",
            facts=list(ЦЕНА_ПРОТИВ_ДОКАЗАТЕЛЬСТВА),
            today=СЕГОДНЯ,
        )
        self.assertIn("проверенный вытеснен ценой 1", итог["note"])
        self.assertIn("проверенных нет вовсе 0", итог["note"])

    def test_строка_печатается_сразу_под_моделью(self) -> None:
        итог = pn.plan(
            "нужен липсинк на готовое видео, бюджет 1 доллар за ролик",
            facts=list(ЦЕНА_ПРОТИВ_ДОКАЗАТЕЛЬСТВА),
            today=СЕГОДНЯ,
        )
        строки = pn.render(итог).splitlines()
        под_моделью = next(i for i, s in enumerate(строки) if "шаг липсинк:" in s) + 1
        self.assertIn("ПРОВЕРЕННЫЙ ЕСТЬ", строки[под_моделью])


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

    def test_отбор_строк_предела_идёт_из_одного_места(self) -> None:
        """DEBT(2026-09-02) ЗАКРЫТ, и тест переписан под то, что стало.

        Долг был записан так: подстрока и исключение повторены в
        `studio/planner.py` и `scripts/creative_fit.py`, потому что `scripts/`
        не пакет. Верно — но копировать было и не нужно: тот же вопрос решает
        семья `studio/selfrag/attrfamily.py`, и она лежит в пакете. Оба места
        спрашивают её, и разъехаться им теперь нечем.

        Сторожится не совпадение двух копий, а ОТСУТСТВИЕ второй копии:
        значения берутся у семьи, и подмена семьи меняет обе стороны разом.
        """
        # Литералы (Т2): ожидаемое набрано здесь, а не взято из проверяемого
        # модуля — иначе обе половины поехали бы вместе.
        self.assertEqual(pn.LIMIT_ATTRIBUTE_MARKER, "resolution")
        self.assertEqual(pn.LIMIT_ATTRIBUTES_EXCLUDED, frozenset({"training_resolution"}))
        # Планировщик и семья отбирают ОДНИ И ТЕ ЖЕ имена — на живой базе, а
        # не на выдуманном списке.
        from studio.selfrag import attrfamily
        from studio.selfrag.facts import load_facts

        свои = {ф.attribute for ф in pn.limit_facts(load_facts())}
        семья = set(attrfamily.expand("resolution", [ф.attribute for ф in load_facts()]))
        self.assertEqual(свои, семья)
        self.assertNotIn("training_resolution", свои, "разрешение обучения — не предел входа")

    def test_контрольный_набор_читается_целиком(self) -> None:
        # ГЛАВНОЕ здесь — равенство двух чисел: строка, которую загрузчик
        # отбросил (опечатка в коде причины, неизвестный класс), не должна
        # пропадать молча.
        self.assertEqual(pn.rows_in(), len(pn.briefs()))
        # А это — ПОЛ, а не точное число, и это исправление ложной ловушки.
        # Точный литерал стоял здесь дважды (8, потом 10) и дважды краснел на
        # ЗДОРОВОМ дереве просто оттого, что в набор добавили случай: таблица
        # мутаций Т1 при этом строилась поверх красного и не значила ничего.
        # Тест обязан ловить ПОТЕРЮ контроля, а не его пополнение (Т6: красное
        # «не запускалось» и красное «упало» — разные вещи, и красное
        # «добавили случай» не является ни тем, ни другим).
        self.assertGreaterEqual(len(pn.briefs()), 8)


if __name__ == "__main__":
    unittest.main()
