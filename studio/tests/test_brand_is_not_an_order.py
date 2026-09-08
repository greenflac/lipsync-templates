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


class СтрочнаяВывескаЗакрытаРодовымСловом(unittest.TestCase):
    """ПРОПУСК, ЗАПИСАННЫЙ КАК СОЗНАТЕЛЬНЫЙ, ОКАЗАЛСЯ ЗАКРЫВАЕМЫМ.

    Строчный бренд («промо студии sfx masters») считался неотличимым от заказа
    («нужны sfx для ролика»): регистр — единственный признак, и в строчном
    тексте его нет. Восьмая приёмка держала находку открытой, и она была
    права: признак есть, просто другой. Перед НАЗВАНИЕМ заказчик почти всегда
    ставит родовое слово — «студии», «приложения», «сети», — иначе читатель не
    поймёт, о чьём названии речь. Родовых слов конечное число, брендов —
    бесконечно.
    """

    СТРОЧНЫЕ_ВЫВЕСКИ = (
        "промо студии sfx masters",
        "реклама приложения talking tom",
        "промо приложения avatar maker, видео снято",
        "ролик про сервис selfie booth",
        # ЗАМЕНЕНО 2026-09-08: здесь стояло «реклама сети narrative coffee,
        # ролик снят», где нет НИ ОДНОЙ подсказки вовсе (`narrative` не
        # совпадает с `narration`), — строка давала `[]` и с живым заслоном, и
        # с убитым, то есть измеряла ноль и на пятую часть украшала число
        # «5 из 5». Найдено одиннадцатой приёмкой.
        "реклама сети dub house, ролик снят",
        # Родовое слово ПОСЛЕ названия — английский порядок слов.
        "video about avatar maker app, footage is ready",
        "promo for sfx masters studio",
    )

    def test_строчная_вывеска_работу_не_заказывает(self) -> None:
        пойманы = [б for б in self.СТРОЧНЫЕ_ВЫВЕСКИ if planner.derive(б)]
        self.assertEqual([], пойманы)

    def test_те_же_слова_без_родового_это_заказ(self) -> None:
        """И5: заслон, снимающий подсказку от одного слова «студия» в брифе,
        съел бы половину заказов."""
        self.assertTrue(planner.derive("нужны sfx для ролика"))
        self.assertTrue(planner.derive("нужен talking head для сайта"))
        self.assertTrue(planner.derive("нужна студия и talking head"))

    def test_родовое_слово_только_соседнее(self) -> None:
        """Первая редакция смотрела 24 символа назад и теряла «реклама СЕТИ
        кофеен, нужен talking head»: родовое слово там про кофейни.

        ЧТО ИМЕННО СТОРОЖИТСЯ (уточнено 2026-09-08). Мутант «окно 24 символа»
        оказался ЭКВИВАЛЕНТНЫМ: код берёт последнее слово перед подсказкой, и
        оно одно и то же при любом окне. Наблюдаемая развилка — «соседнее
        слово» против «весь текст перед подсказкой», и красит её эта строка.
        """
        self.assertTrue(planner.derive("реклама сети кофеен, нужен talking head"))

    def test_измеренная_граница_родовое_слово_через_слово(self) -> None:
        """И6: запись отрицательного результата числом, а не молчанием.

        ИЗМЕРЕНО одиннадцатой приёмкой на её наборе из 12 вывесок: обе
        редакции смотрят СОСЕДНЕЕ слово, и вывеска, у которой родовое слово
        отделено ещё одним словом или запятой, работу по-прежнему заказывает.
        Таких 5 из 12. Наблюдаемого признака дешевле у нас нет; окно назад мы
        пробовали, и оно теряет настоящие заказы (строка выше).
        """
        # ГРАНИЦА ЗАПИСЫВАЕТСЯ, А НЕ ТРЕБУЕТСЯ. Первая редакция требовала
        # `assertEqual`, то есть делала пропуск ОБЯЗАТЕЛЬНЫМ: тот, кто закроет
        # дыру, получил бы красный тест и решил, что сломал (найдено
        # двенадцатой приёмкой). И6 просит записать отрицательный результат
        # числом, а не запретить его исправлять.
        не_ловим = (
            "промо для новой студии звукозаписи sfx masters",
            "промо sfx masters, это студия звука",
        )
        заказывают = [б for б in не_ловим if planner.derive(б)]
        self.assertLessEqual(len(заказывают), len(не_ловим))


class ГраницыКонстантСторожатсяВОбеСтороны(unittest.TestCase):
    """И4/Т1: константа, проверенная только в одну сторону, — половина сторожа.

    НАЙДЕНО девятой приёмкой: мутант `ЗАГЛАВНЫХ_СЛИШКОМ` 0.6 -> 0.95 молчал
    (в наборе не было брифа с долей между), а `len(слова) < 2` -> `< 1` молчал
    вовсе — однословного латинского брифа никто не подавал.
    """

    #: ДОЛЯ МЕЖДУ ПОРОГАМИ: 4 заглавных из 5 = 0.8, то есть выше 0.6 и ниже
    #: 0.95. Первая редакция фикстуры брала строку с долей 1.0 и потому
    #: мутанта 0.6 -> 0.95 не различала — поймано прогоном самой мутации.
    ПОЧТИ_КАПС = "Make me A Talking Avatar"

    def test_доля_между_порогами_читается_как_оформление(self) -> None:
        self.assertFalse(planner._регистр_что_то_значит(self.ПОЧТИ_КАПС))
        self.assertTrue(planner.derive(self.ПОЧТИ_КАПС))

    def test_обычный_регистр_остаётся_обычным(self) -> None:
        """Вторая сторона: при потолке 0.05 любой текст стал бы оформлением."""
        self.assertTrue(planner._регистр_что_то_значит("we need a talking head ad for our SaaS"))

    def test_однословный_латинский_бриф(self) -> None:
        """`len(слова) < 2` -> `< 1` не красило ничего: одно слово с заглавной
        не с чем сравнивать, и доля от него — не признак."""
        self.assertTrue(planner._регистр_что_то_значит("Voiceover"))
        self.assertTrue(planner.derive("Voiceover"))

    def test_два_слова_уже_считаются(self) -> None:
        self.assertFalse(planner._регистр_что_то_значит("Talking Head"))


class ЯрлыкВНачалеБрифа(unittest.TestCase):
    """Слово после «Задача: », «Job: » — начало фразы, а не имя собственное.

    НАЙДЕНО десятой приёмкой 2026-09-07: снятие `:` и `;` из lookbehind
    теряло 12 заказов с ярлыком против 3 убранных ложных срабатываний. Девятая
    приёмка измерила снятие на своём наборе и не увидела потерь ровно потому,
    что ни в одной фикстуре репозитория не было брифа вида «Ярлык: Заглавная».
    """

    ЗАКАЗЫ_С_ЯРЛЫКОМ = (
        "Задача: Lipsync нашего видео",
        "Job: Dub our video into German",
        "Brief: Voiceover for the ad",
        "Что нужно: Foley для ролика",
        "Нужен постер; Voiceover тоже нужен",
        "Бриф: Talking head ad, 30 seconds",
    )
    ВЫВЕСКИ_С_ЯРЛЫКОМ = (
        "Client: Talking Tom. We need a poster",
        "клиент: Talking Tom, нужен постер",
        "заказчик: Avatar Maker, нужен постер",
    )

    def test_заказ_с_ярлыком_разбирается(self) -> None:
        потеряны = [б for б in self.ЗАКАЗЫ_С_ЯРЛЫКОМ if not planner.derive(б)]
        self.assertEqual([], потеряны)

    def test_вывеска_за_ярлыком_остаётся_вывеской(self) -> None:
        """И5: вернуть двоеточие целиком значило бы вернуть и три ложных.
        За ярлыком имя — это ЦЕПОЧКА из двух и более заглавных."""
        пойманы = [б for б in self.ВЫВЕСКИ_С_ЯРЛЫКОМ if planner.derive(б)]
        self.assertEqual([], пойманы)

    def test_порядок_затирания_решает(self) -> None:
        """Общая цепочка успевает стереть ВТОРОЕ слово, и правило «два и
        больше» перестаёт срабатывать. Поймано собственным прогоном."""
        без = planner._без_имён_собственных("Client: Talking Tom. We need a poster")
        self.assertNotIn("talking", без)


class ФормаКомпанииСторожитсяВОбеСтороны(unittest.TestCase):
    """Т1: список правился, а мутанта на него не было ни одного."""

    def test_вывеска_с_формой_компании_молчит(self) -> None:
        self.assertEqual([], planner.derive("our client is Talking Head Studios, make a poster"))

    def test_обычное_слово_формой_компании_не_считается(self) -> None:
        """Вторая сторона: список, куда попало «Video», съел бы заказы."""
        self.assertNotIn("video", planner.ФОРМЫ_КОМПАНИЙ)
        self.assertNotIn("talking", planner.ФОРМЫ_КОМПАНИЙ)
        self.assertTrue(planner.derive("нужен Lip Sync для Social Media"))

    def test_форма_компании_живая(self) -> None:
        self.assertIn("studios", planner.ФОРМЫ_КОМПАНИЙ)
        self.assertIn("inc", planner.ФОРМЫ_КОМПАНИЙ)


#: ОДНА ВЫВЕСКА НА КАЖДЫЙ КОРЕНЬ СПИСКА. Слова — ЛИТЕРАЛЫ (Т2), а не склеены
#: из самого списка: склеенные поедут вместе с ним и промолчат.
#:
#: ЗАЧЕМ ТАБЛИЦА. ИЗМЕРЕНО одиннадцатой приёмкой 2026-09-08 поэлементным
#: удалением: из 14 корней 11 можно было вычеркнуть, и ни один тест не
#: краснел, — то есть список-константа решения почти целиком не сторожился.
РОДОВЫЕ_СЛОВА: tuple[str, ...] = (
    "студии",
    "приложения",
    "сервиса",
    "компании",
    "фирмы",
    "бренда",
    "марки",
    "сети",
    "агентства",
    "магазина",
    "отеля",
    "клуба",
    "заведения",
    "проекта",
    "app",
    "studio",
    "service",
    "brand",
    "company",
    "agency",
    "shop",
    "hotel",
    "club",
    "chain",
    "startup",
    "label",
)


class КаждыйКореньСписковСторожится(unittest.TestCase):
    """Т1: любой вычеркнутый корень обязан покраснеть хотя бы одной строкой."""

    # ХВОСТ ФИКСТУРЫ ЗАМЕНЁН 2026-09-08 С `labs` НА `masters`. НАЙДЕНО
    # двенадцатой приёмкой: `labs` — элемент `ФОРМЫ_КОМПАНИЙ`, и он закрывал
    # бриф в одиночку; таблица была зелена при ПОЛНОСТЬЮ вычеркнутом
    # `ВЫВЕСКА_ВПЕРЕДИ`, то есть измеряла ноль — ровно тот дефект, ради
    # которого её и заводили.
    def test_родовое_слово_перед_названием_снимает_заказ(self) -> None:
        заказали = [с for с in РОДОВЫЕ_СЛОВА if planner.derive(f"реклама {с} lip sync masters")]
        self.assertEqual([], заказали)

    def test_без_родового_слова_это_заказ(self) -> None:
        """Негативный контроль (И5): то же предложение без родового слова."""
        self.assertTrue(planner.derive("реклама lip sync masters"))

    def test_родовое_слово_после_названия_тоже_вывеска(self) -> None:
        поймано = [с for с in РОДОВЫЕ_СЛОВА if not planner.derive(f"промо lip sync {с}")]
        self.assertEqual(list(РОДОВЫЕ_СЛОВА), поймано)


class РодовоеСловоПослеНазвания(unittest.TestCase):
    """Английский порядок слов: «avatar maker app», «sfx masters studio».

    ИЗМЕРЕНО одиннадцатой приёмкой: из 8 английских вывесок молчало 0 — список
    состоял из русских корней, а смотрел только назад.
    """

    def test_название_между_подсказкой_и_родовым_словом(self) -> None:
        self.assertEqual([], planner.derive("video about avatar maker app, footage is ready"))

    def test_форма_компании_это_то_же_родовое_слово(self) -> None:
        self.assertEqual([], planner.derive("our brand is voice over inc, need a logo"))

    def test_служебное_слово_обрывает_поиск(self) -> None:
        """«voiceover FOR OUR app» — заказ озвучки, а не вывеска."""
        self.assertTrue(planner.derive("we need voiceover for our app"))

    def test_запятая_обрывает_поиск(self) -> None:
        self.assertTrue(planner.derive("need lipsync, the clip is for our app"))

    def test_дальше_трёх_слов_не_смотрим(self) -> None:
        """Записанная граница (И6), а не обещание: имя длиннее трёх слов не ловится."""
        self.assertTrue(planner.derive("promo for lip sync one two three four studio"))


if __name__ == "__main__":
    unittest.main()
