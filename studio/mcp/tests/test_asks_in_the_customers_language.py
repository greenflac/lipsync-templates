"""Вопрос задаётся на языке брифа, со списком значений и примером под задачу.

ЧТО ЗДЕСЬ ВОСПРОИЗВОДИТСЯ (И2). Продуктовая проверка 2026-09-07, живой прогон
`write_lipsync_prompt(intent="тёплый уютный кофейный ролик, мягкий свет из
окна")` отвечал русскому заказчику по-английски:

    "note": "1 of 4 card slots were filled; palette; texture; saturation
             could not be, and a guess is not a prompt. Ask, then run again."
    "ask":  "Which colours? Name one to three of: amber, charcoal, copper,
             crimson, emerald, gold, indigo, ivory, rose, sand, slate, teal"

и ни «тёплый», ни «кофейный» продукт не читал вовсе, а в списке из двенадцати
цветов заказчик кофейни своего не находит.

Т2: ожидаемое — ЛИТЕРАЛЫ. Списки движка импортируются РОВНО в одном тесте —
там, где смысл теста и есть сверка с источником («пример не заводит нового
значения»).

Т4: сети здесь нет. `write` берёт примеры корпуса параметром, а `ruwords` —
таблица в памяти; ни одна проверка ниже не поднимает индекс.

И5, негативный контроль стоит рядом с каждым положительным: английский бриф
обязан получить английский вопрос (иначе «спрашиваем по-русски» = «всегда
по-русски»), а бриф без узнаваемой темы — вопрос БЕЗ примера (иначе пример
выдумывается всегда).
"""

from __future__ import annotations

import unittest

from studio import ruwords
from studio.mcp import lipsync_prompt as lp
from studio.mcp.server import сведения_о_поиске

#: Тот самый вход продуктовой проверки. Хранится литералом здесь, потому что
#: воспроизведение без сохранённого входа — рассказ о дефекте, а не дефект.
РУССКИЙ_БРИФ = "тёплый уютный кофейный ролик, мягкий свет из окна"
АНГЛИЙСКИЙ_БРИФ = "cozy coffee shop, warm morning light, muted palette"
СМЕШАННЫЙ_БРИФ = "тёплый ролик в стиле film noir"

КИРИЛЛИЦА = set("абвгдеёжзийклмнопрстуфхцчшщъыьэюя")


def есть_кириллица(текст: str) -> bool:
    return any(с in КИРИЛЛИЦА for с in текст.lower())


class ЯзыкОпределяетсяПоТексту(unittest.TestCase):
    """Определять — по тексту, а не по догадке, и не ошибаться на смеси."""

    def test_русский_бриф(self) -> None:
        self.assertEqual("ru", ruwords.язык(РУССКИЙ_БРИФ))

    def test_английский_бриф(self) -> None:
        self.assertEqual("en", ruwords.язык(АНГЛИЙСКИЙ_БРИФ))

    def test_смешанный_бриф_остаётся_русским(self) -> None:
        """Латинский термин внутри русского брифа — это название приёма
        («film noir», «high-key»), а не смена языка заказчика. Доля букв
        ошиблась бы здесь: латиницы больше."""
        self.assertEqual("ru", ruwords.язык(СМЕШАННЫЙ_БРИФ))
        self.assertEqual("ru", ruwords.язык("ролик в стиле film noir, high-key"))

    def test_пустой_бриф_не_роняет_и_отвечает_по_умолчанию(self) -> None:
        self.assertEqual("en", ruwords.язык(""))
        self.assertEqual("en", ruwords.язык("   "))


class ВопросыНаЯзыкеБрифа(unittest.TestCase):
    def test_русскому_заказчику_вопросы_по_русски(self) -> None:
        ответ = lp.write(РУССКИЙ_БРИФ, [])
        self.assertEqual("could not measure", ответ["outcome"])
        self.assertTrue(ответ["unresolved"], "незаполненные слоты обязаны спрашиваться")
        for строка in ответ["unresolved"]:
            self.assertTrue(
                есть_кириллица(строка["ask"]),
                f"вопрос по-английски русскому заказчику: {строка['ask']!r}",
            )
        self.assertTrue(есть_кириллица(ответ["note"]), ответ["note"])
        self.assertIn("Спросите заказчика и запустите снова.", ответ["note"])

    def test_английскому_заказчику_вопросы_по_английски(self) -> None:
        """И5, негативный контроль: продукт, который всегда отвечает
        по-русски, язык не определяет, а угадал один раз."""
        ответ = lp.write(АНГЛИЙСКИЙ_БРИФ, [])
        self.assertEqual("could not measure", ответ["outcome"])
        self.assertTrue(ответ["unresolved"])
        for строка in ответ["unresolved"]:
            self.assertFalse(
                есть_кириллица(строка["ask"]),
                f"русский вопрос англоязычному заказчику: {строка['ask']!r}",
            )
        self.assertFalse(есть_кириллица(ответ["note"]), ответ["note"])
        self.assertIn("of 4 card slots were filled", ответ["note"])

    def test_смешанный_бриф_не_ломается_и_спрашивает_по_русски(self) -> None:
        ответ = lp.write(СМЕШАННЫЙ_БРИФ, [])
        self.assertEqual("could not measure", ответ["outcome"])
        self.assertEqual(
            ["palette", "value_key", "texture", "saturation"],
            [с["slot"] for с in ответ["unresolved"]],
        )
        for строка in ответ["unresolved"]:
            self.assertTrue(есть_кириллица(строка["ask"]), строка["ask"])

    def test_названия_слотов_в_вопросе_тоже_русские(self) -> None:
        """«Вы назвали palette приблизительно» — это вопрос на полутора
        языках, то есть на нулевом."""
        ответ = lp.write(РУССКИЙ_БРИФ, [])
        палитра = next(с for с in ответ["unresolved"] if с["slot"] == "palette")
        self.assertIn("Вы назвали цвет приблизительно", палитра["ask"])
        self.assertIn("цвет; фактура; насыщенность", ответ["note"])


class ПримерОтветаПодЗадачуЗаказчика(unittest.TestCase):
    """Список допустимых значений — ещё не вопрос, на который можно ответить.

    В списке из двенадцати цветов нет ни коричневого, ни кофейного, ни
    бежевого; ближайшее к кофейне — `amber` и `sand`, и заказчик об этом не
    догадается.
    """

    def test_русский_вопрос_несёт_пример(self) -> None:
        ответ = lp.write(РУССКИЙ_БРИФ, [])
        палитра = next(с for с in ответ["unresolved"] if с["slot"] == "palette")
        self.assertIn("Например: amber, sand — тёплый уютный интерьер.", палитра["ask"])

    def test_английский_вопрос_несёт_тот_же_пример_по_английски(self) -> None:
        ответ = lp.write(АНГЛИЙСКИЙ_БРИФ, [])
        палитра = next(с for с in ответ["unresolved"] if с["slot"] == "palette")
        self.assertIn("For example: amber, sand — a warm cosy interior.", палитра["ask"])

    def test_пример_отделён_от_списка_знаком(self) -> None:
        """Читано глазами (П3): без точки выходило «…, watercolour Например»."""
        ответ = lp.write(РУССКИЙ_БРИФ, [])
        фактура = next(с for с in ответ["unresolved"] if с["slot"] == "texture")
        self.assertIn("watercolour. Например: matte", фактура["ask"])

    def test_бриф_без_узнаваемой_темы_остаётся_без_примера(self) -> None:
        """И5, негативный контроль. Пример, который выдаётся всегда, — это
        значение по умолчанию, то есть выбор за заказчика."""
        ответ = lp.write("ролик про монтаж трубопровода", [])
        for строка in ответ["unresolved"]:
            self.assertNotIn("Например", строка["ask"], строка["ask"])

    def test_двусмысленный_бриф_остаётся_без_примера(self) -> None:
        """«тёплый» тянет в интерьер, «noir» — в ночь. Две темы — не тема."""
        ответ = lp.write(СМЕШАННЫЙ_БРИФ, [])
        for строка in ответ["unresolved"]:
            self.assertNotIn("Например", строка["ask"], строка["ask"])

    def test_пример_не_заводит_нового_значения(self) -> None:
        """Единственное место, где импорт списков движка И ЕСТЬ смысл теста:
        значения живут в `studio/style.py`, у которого другой писатель, и
        пример обязан выбираться из них, а не расширять их."""
        from lipsync.fork_style_prompt import SATURATION_WORDS
        from studio.style import LIGHT_WORDS, PALETTE_WORDS, TEXTURE_WORDS

        разрешено = {
            "palette": set(PALETTE_WORDS),
            "texture": set(TEXTURE_WORDS),
            "saturation": set(SATURATION_WORDS),
            "value_key": {"light", "mid", "dark"},
        }
        чужие: list[str] = []
        for тема in lp.ТЕМЫ:
            for слот, значения in тема["значения"].items():
                чужие += [f"{слот}:{з}" for з in значения if з not in разрешено[слот]]
        self.assertEqual([], sorted(чужие), "пример называет значение, которого движок не знает")
        self.assertEqual(
            set(),
            {слово for слово in LIGHT_WORDS} & {"mid"},
            "value_key — это ключ карточки, а не слово света; проверка сторожит подмену",
        )


class РусскиеСловаБрифаЧитаются(unittest.TestCase):
    """«тёплый» -> amber, «кофейный» -> copper: раньше не читались вовсе."""

    def test_тёплый_и_кофейный_доходят_до_вопроса(self) -> None:
        разбор = lp.read_intent(РУССКИЙ_БРИФ)
        self.assertEqual({"кофейн": "copper", "тёпл": "amber"}, разбор["guessed"])
        self.assertEqual({"мягк": "soft"}, разбор["translated"])

    def test_догадка_названа_в_вопросе_а_не_подставлена_в_промт(self) -> None:
        ответ = lp.write(РУССКИЙ_БРИФ, [])
        палитра = next(с for с in ответ["unresolved"] if с["slot"] == "palette")
        self.assertIn("кофейн ~ copper", палитра["ask"])
        self.assertIn("тёпл ~ amber", палитра["ask"])
        self.assertIsNone(ответ["prompt"])
        self.assertNotIn("palette", ответ["chosen"])

    def test_вопрос_о_цвете_называет_только_цветные_догадки(self) -> None:
        """«сзади ~ backlit» в вопросе о цвете — это разговор о другом слоте."""
        ответ = lp.write("тёплый ролик, свет сзади", [])
        палитра = next(с for с in ответ["unresolved"] if с["slot"] == "palette")
        self.assertIn("тёпл ~ amber", палитра["ask"])
        self.assertNotIn("backlit", палитра["ask"])
        свет = next(с for с in ответ["unresolved"] if с["slot"] == "light")
        self.assertIn("сзади ~ backlit", свет["ask"])

    def test_точное_слово_не_переспрашивается_из_за_догадки(self) -> None:
        """И5, обратная сторона: «тёплый ЯНТАРНЫЙ свет» — цвет назван точно,
        и переспрашивать его нельзя, иначе продукт не отвечает никогда."""
        ответ = lp.write("тёплый янтарный свет, мягкие тени, матовый, приглушённые цвета", [])
        self.assertEqual([], ответ["unresolved"])
        self.assertEqual("pass", ответ["outcome"])
        self.assertIn("amber", ответ["prompt"])


class ЧемИскалиГоворитсяВслух(unittest.TestCase):
    """`asked_with` печатает ВЫПОЛНЕННЫЙ запрос, а не разницу с намерением.

    ВОСПРОИЗВЕДЕНО 2026-09-07 живым прогоном на английском намерении:
    `{"outcome": "fail", "note": "nothing in the index clears the relevance
    floor", "asked_with": ""}` — пустая строка читается как «искали пустотой»
    ровно там, где читатель ищет причину, по которой ничего не нашлось.
    """

    НАЙДЕНО = {
        "outcome": "fail",
        "examples": (),
        "below_floor": 9,
        "note": "nothing in the index clears the relevance floor",
    }

    def test_запрос_совпал_со_словами_заказчика(self) -> None:
        свед = сведения_о_поиске(АНГЛИЙСКИЙ_БРИФ, АНГЛИЙСКИЙ_БРИФ.lower(), self.НАЙДЕНО)
        self.assertEqual("cozy coffee shop, warm morning light, muted palette", свед["asked_with"])
        self.assertTrue(свед["owner_words"])

    def test_запрос_дополнен_и_это_видно(self) -> None:
        свед = сведения_о_поиске(РУССКИЙ_БРИФ, РУССКИЙ_БРИФ + " amber copper soft", self.НАЙДЕНО)
        self.assertIn("amber copper soft", свед["asked_with"])
        self.assertFalse(свед["owner_words"])

    def test_исход_и_числа_переносятся_как_есть(self) -> None:
        свед = сведения_о_поиске("x", "x", self.НАЙДЕНО)
        self.assertEqual("fail", свед["outcome"])
        self.assertEqual(0, свед["examples"])
        self.assertEqual(9, свед["below_floor"])
        self.assertEqual("nothing in the index clears the relevance floor", свед["note"])


if __name__ == "__main__":
    unittest.main()
