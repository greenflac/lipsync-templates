"""Чужая вывеска в брифе — не заказ, а наш термин с заглавных — заказ.

ДВЕ СТОРОНЫ ОДНОЙ РУЧКИ, И ОБЕ СТОИЛИ ДЕНЕГ В ОДИН ДЕНЬ.

Сначала латинские подсказки искались подстрокой: «ролик про отель в Dubai»
заказывал ДУБЛЯЖ, «промо студии SFX Masters» — фоновый звук, «Talking Tom» —
липсинк. Девять ложных срабатываний.

Потом маска имён собственных вычёркивала ЛЮБОЕ латинское слово с заглавной — и
канонический заказ студии переставал разбираться: «нужен Lip Sync на готовое
видео», «BRIEF: TALKING HEAD AD», «Make Me A Talking Avatar Ad» давали
«совпало 0». ИЗМЕРЕНО восьмой приёмкой на собственном наборе коммита: как есть
11 из 11, Title Case 6 из 11, КАПС 6 из 11.

НАБОР ДЕРЖИТ ОБЕ СТОРОНЫ РАЗОМ (И5): по отдельности каждую легко удовлетворить
неправильно — «не ловить бренды» пустым словарём, «не терять заказы» снятием
маски.
"""

from __future__ import annotations

import unittest

from studio import planner

#: Заказы, которые обязаны разбираться. Регистр — как пишет живой человек.
ЗАКАЗЫ: tuple[str, ...] = (
    "нужен Lip Sync на готовое видео",
    "сделайте Voice Over для ролика",
    "нужен Talking Head ролик",
    "нужен Talking Head для нашего SaaS",
    "BRIEF: TALKING HEAD AD, 30 SECONDS",
    "Product ad for skincare\nTalking head, 30 seconds",
    "Make Me A Talking Avatar Ad, 15 Seconds",
    "need a talking head ad for our SaaS",
    "Dub our existing commercial into Spanish",
    "Add sound effects and ambience to our clip",
    "Localise our ad for Spain",
    "нужны sfx для ролика",
    # СЛОВОФОРМЫ. Жёсткая граница справа оставила от английских подсказок
    # только точную форму: ИЗМЕРЕНО машинным перебором — было 168 форм из 168,
    # стало 16. Заказчику отвечали «назовите работу словом `voiceover`» — его
    # же словом в единственном числе.
    "we need voiceovers for the ad",
    "two narrators reading the script",
    "we need dubbing into German",
    "the clip must be dubbed",
    "three presenters on camera",
    "lip syncing on existing footage",
    "selfies to animate",
    "replace characters in the scene",
    "background sounds for the scene",
    "we need avatars",
)

#: Чужие вывески. Ни одна не заказывает работу.
ВЫВЕСКИ: tuple[str, ...] = (
    "ролик про отель в Dubai, видео снято",
    "промо для Talking Tom, видео готово",
    "реклама сети Narrative Coffee, ролик снят",
    "ролик про сервис Selfie Booth, съёмка есть",
    "промо для клуба Dubstep Nation, видео снято",
    "реклама Dublin Pub, видео снято",
    "промо приложения Avatar Maker, видео снято",
    "реклама студии Localise Ltd, видео снято",
    # БРЕНД, СОВПАДАЮЩИЙ С НАШИМ ТЕРМИНОМ, — ТОЖЕ БРЕНД. Спасение цепочки
    # составной подсказкой открывало её целиком.
    "our client is Talking Head Studios, make a poster",
    "клиент — Talking Head Studios, нужен постер",
    "клиент Voice Over Inc, нужна визитка",
    "the brand is Lip Sync Records, design a logo",
    # ДВОЕТОЧИЕ В LOOKBEHIND было разменом ни на что: заказов не спасало,
    # вывески пропускало.
    "Client: Talking Tom. We need a poster",
    "клиент: Talking Tom, нужен постер",
)


class ЗаказРазбирается(unittest.TestCase):
    def test_ни_один_заказ_не_потерян(self) -> None:
        потеряны = [б for б in ЗАКАЗЫ if not planner.derive(б)]
        self.assertEqual([], потеряны)

    def test_регистр_всего_брифа_снимает_признак_имени(self) -> None:
        """Заглавная говорит об имени только в тексте обычного регистра."""
        self.assertTrue(planner._регистр_что_то_значит("Product ad for skincare, talking head"))
        self.assertFalse(planner._регистр_что_то_значит("BRIEF: TALKING HEAD AD, 30 SECONDS"))
        self.assertFalse(planner._регистр_что_то_значит("Make Me A Talking Avatar Ad"))

    def test_в_русском_брифе_доля_не_считается(self) -> None:
        """«Talking Tom» — два латинских слова, оба с заглавной, доля 1.0. Это
        имя, а не оформление: доля по латинским словам в русском брифе всегда
        единица (поймано собственным прогоном сразу за починкой)."""
        self.assertTrue(planner._регистр_что_то_значит("промо для Talking Tom, видео готово"))

    def test_составная_подсказка_спасает_цепочку_заглавных(self) -> None:
        """Чем «Lip Sync» отличается от «Talking Tom» в русском брифе: наш
        термин заказчик пишет ЦЕЛИКОМ, бренд цепляется за одно общее слово."""
        без = planner._без_имён_собственных("нужен Lip Sync на готовое видео")
        self.assertIn("lip sync", без)
        без2 = planner._без_имён_собственных("промо для Talking Tom, видео готово")
        self.assertNotIn("talking", без2)


class ВывескаНеЗаказ(unittest.TestCase):
    def test_ни_одна_вывеска_не_заказала_работу(self) -> None:
        пойманы = [(б, [o.name for o in planner.derive(б)]) for б in ВЫВЕСКИ if planner.derive(б)]
        self.assertEqual([], пойманы)

    def test_латиница_ищется_по_обеим_границам(self) -> None:
        """Граница стояла только слева, и `dub` находился внутри «Dubai»."""
        self.assertFalse(planner._подсказка_есть("dub", "отель в dubai", "отель в dubai"))
        self.assertTrue(planner._подсказка_есть("dub", "dub our ad", "dub our ad"))

    def test_приставка_объявляется_звёздочкой(self) -> None:
        """`localis*` ловит «localisation», `dub` — только целое слово. Приставка
        видна в самом списке подсказок, а не подразумевается."""
        self.assertTrue(planner._подсказка_есть("localis*", "localisation", "localisation"))
        self.assertFalse(planner._подсказка_есть("localis", "localisation", "localisation"))

    def test_английская_словоформа_ловится(self) -> None:
        """Хвост закрытый: `s`, `es`, `ed`, `ing` и удвоение последней
        согласной. Именно закрытость оставляет «Dubai» за бортом."""
        for текст in ("we need voiceovers", "dubbing into german", "the clip was dubbed"):
            self.assertTrue(planner.derive(текст), текст)

    def test_закрытость_хвоста_держит_топоним(self) -> None:
        """И5: хвост «что угодно» вернул бы «Dubai» и «Dublin»."""
        self.assertFalse(planner._подсказка_есть("dub", "hotel in dubai", "hotel in dubai"))
        self.assertFalse(planner._подсказка_есть("dub", "dublin pub", "dublin pub"))

    def test_форма_компании_сильнее_составной_подсказки(self) -> None:
        без = planner._без_имён_собственных("клиент Voice Over Inc, нужна визитка")
        self.assertNotIn("voice over", без)

    def test_русская_подсказка_по_прежнему_подстрокой(self) -> None:
        """Русское слово склоняется, и граница справа потеряла бы «озвучки»."""
        self.assertTrue(planner._подсказка_есть("озвучк", "нужна озвучки", "нужна озвучки"))


class ИзмеренныйПропуск(unittest.TestCase):
    """И6: пропуск, выбранный сознательно и записанный числом.

    Бренд, написанный СТРОЧНЫМИ («промо студии sfx masters»), от заказа
    неотличим: «нужны sfx для ролика» — настоящий заказ теми же буквами.
    Регистр — единственный наблюдаемый признак, и в строчном тексте его нет.
    Пропуск оставлен намеренно: доктрина продукта говорит, в какую сторону
    ошибаться, а лишний шаг заказчик увидит в плане и снимет.
    """

    def test_строчный_бренд_по_прежнему_ловится(self) -> None:
        self.assertTrue(planner.derive("промо студии sfx masters"))
        self.assertTrue(planner.derive("реклама приложения talking tom"))


if __name__ == "__main__":
    unittest.main()
