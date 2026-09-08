"""Имя живого человека в заказе называется вслух — но заказ не отвергается.

САМАЯ ДОРОГАЯ НАХОДКА СЕССИИ, продуктовая проверка 2026-09-07 (третий заход):

    «Хочу ролик, где Киану Ривз рассказывает про наш банк»

проходило просев НАСКВОЗЬ и получало полный трёхшаговый производственный план
с моделями, ценами и ссылками на вендоров. Ни слова о правах на образ. Заслон
`recognisable third parties` ловил МЕТА-СЛОВО — «дипфейк», «знаменитость», —
а заказчик, который просто называет фамилию, то есть обычный заказчик, получал
план. Цена ошибки здесь не потерянная вкладка, а иск.

ПОЧЕМУ КОММЕНТАРИЙ, А НЕ ОТКАЗ — то же основание, что у медицинского
утверждения: у заказчика может быть подписанное согласие, и судить об этом мы
не можем. Отказ был бы ложным; молчание студия продаёт как согласие.
"""

from __future__ import annotations

import json
import unittest

from studio.mcp import screen, server

НАЗВАН_ЧЕЛОВЕК = (
    "Хочу ролик, где Киану Ривз рассказывает про наш банк",
    "нужен ролик с Ольгой Бузовой, она хвалит наш товар",
    "Морган Фриман читает наш текст, 30 секунд",
    "a clip where Elon Musk talks about our bank",
)

НИКОГО_НЕ_НАЗВАЛИ = (
    "Ролик про кофейню в Химках, говорящая голова",
    "промо для Talking Tom, видео готово",
    "клиент Voice Over Inc, нужна визитка",
    "хочу снять ролик в Нижнем Новгороде",
    "наш актёр Иван Петров рассказывает о компании",
    "our actor John Smith reads the script",
    "нужен ролик 30 секунд для крема",
    "реклама сети Narrative Coffee, ролик снят",
    # С ГЛАГОЛОМ ПОЯВЛЕНИЯ: без него мутант на список «не человек» молчал —
    # пара заглавных и так не считалась человеком (поймано прогоном мутации).
    "реклама сети Narrative Coffee, ведущий рассказывает о скидках",
    "промо приложения Avatar Maker, ведущий говорит о новинке",
    "ролик для отеля Grand Palace, диктор читает текст",
)


class ЧеловекНазванВслух(unittest.TestCase):
    def test_каждое_имя_поймано(self) -> None:
        молчит = [т for т in НАЗВАН_ЧЕЛОВЕК if not screen.просеять(т)["risky"]]
        self.assertEqual([], молчит)

    def test_имя_приведено_в_риске(self) -> None:
        риски = screen.просеять(НАЗВАН_ЧЕЛОВЕК[0])["risks"]
        self.assertEqual(["person's likeness: Киану Ривз"], риски)

    def test_это_НЕ_отказ(self) -> None:
        """Ложный отказ здесь дороже пропуска ровно так же, как в медицине:
        согласие может быть, и мы о нём не знаем."""
        итог = screen.просеять(НАЗВАН_ЧЕЛОВЕК[0])
        self.assertEqual("pass", итог["outcome"])
        self.assertEqual(0, итог["violations"])

    def test_предупреждение_называет_чьи_это_права(self) -> None:
        текст = screen.предупреждение(["person's likeness: Киану Ривз"])
        self.assertIn("Киану Ривз", текст)
        self.assertIn("письменное согласие", текст)
        self.assertNotIn("утверждение", текст)


class НикогоНеНазвали(unittest.TestCase):
    """И5: прибор, видящий человека в любой паре заглавных, не различает
    ничего — «Нижний Новгород» и «Talking Tom» людьми не являются."""

    def test_ни_одного_ложного(self) -> None:
        шумят = [т for т in НИКОГО_НЕ_НАЗВАЛИ if screen.просеять(т)["risky"]]
        self.assertEqual([], шумят)

    def test_пара_заглавных_без_глагола_молчит(self) -> None:
        """Человеком пару делает глагол появления рядом."""
        self.assertEqual([], screen._люди_в_заказе("Киану Ривз, Нижний Новгород"))

    def test_свой_человек_предупреждения_не_получает(self) -> None:
        """У «нашего актёра» согласие есть по определению договора, и говорить
        о нём то же самое — шум, из-за которого перестанут читать настоящий."""
        self.assertEqual(0, screen.просеять("наш актёр Иван Петров говорит в камеру")["risky"])


class ПродуктГоворитЭтоЗаказчику(unittest.TestCase):
    def test_план_несёт_риск_и_объяснение(self) -> None:
        итог = json.loads(server.plan_pipeline(НАЗВАН_ЧЕЛОВЕК[0]))
        self.assertEqual(["person's likeness: Киану Ривз"], итог["risks"])
        self.assertIn("права на образ", итог["note"].lower())

    def test_план_всё_же_собран(self) -> None:
        self.assertTrue(json.loads(server.plan_pipeline(НАЗВАН_ЧЕЛОВЕК[0]))["steps"])


class ЛатинскоеИмяТожеЖивойЧеловек(unittest.TestCase):
    """ОСНОВЫ, А НЕ СЛОВОФОРМЫ — на латинице тоже (И7: та же форма дефекта).

    ВОСПРОИЗВЕДЕНО одиннадцатой продуктовой проверкой 2026-09-08: «Make a video
    of Elon Musk endorsing my crypto token» и «I need a fake video of a bank CEO
    telling customers to transfer money» проходили без единого слова о правах на
    образ, тогда как русское «дипфейк Илона Маска» останавливалось. Сторож
    работал только кириллицей — то есть половина заказчиков его не видела.
    """

    def test_герундий_ловится_как_и_третье_лицо(self) -> None:
        риски = screen.просеять("Make a video of Elon Musk endorsing my crypto token")["risks"]
        self.assertEqual(риски, ["person's likeness: Elon Musk"])

    def test_третье_лицо_осталось(self) -> None:
        риски = screen.просеять("Taylor Swift says our product is great")["risks"]
        self.assertEqual(риски, ["person's likeness: Taylor Swift"])

    def test_основа_не_ищется_внутри_чужого_слова(self) -> None:
        """`read` подстрокой сидит в `already` — и «New York» становился человеком."""
        self.assertEqual(screen.просеять("already shot in New York, need lipsync")["risks"], [])

    def test_термин_ремесла_никого_не_называет(self) -> None:
        """`talk` в список не взято нарочно: «talking head» — в каждом втором брифе."""
        self.assertEqual(screen.просеять("a talking head ad for New York Pizza")["risks"], [])


class ПредлогМестаПередПаройЗаглавных(unittest.TestCase):
    """Место, а не человек: соседнее слово решает."""

    def test_английское_место_не_человек(self) -> None:
        """ГЛАГОЛ ПОЯВЛЕНИЯ В БРИФЕ ОБЯЗАТЕЛЕН, иначе строка ничего не мерит:
        без него поиск имён не запускается вовсе, и тест зелен при любом коде
        (поймано мутационным прогоном 2026-09-08)."""
        self.assertEqual(screen.просеять("our presenter speaks, filmed in New York")["risks"], [])

    def test_русское_место_не_человек(self) -> None:
        self.assertEqual(
            screen.просеять("ролик снят в Нижнем Новгороде, нужен липсинк")["risks"], []
        )

    def test_человек_без_предлога_места_остаётся(self) -> None:
        риски = screen.просеять("интервью, в кадре рассказывает Иван Петров")["risks"]
        self.assertEqual(риски, ["person's likeness: Иван Петров"])


class ПрофессияЭтоРольАНеЧеловек(unittest.TestCase):
    """Ложный отказ дороже пропуска: клип с певицей — не «узнаваемое лицо».

    ВОСПРОИЗВЕДЕНО той же проверкой: «Music video, singer lipsyncing to my
    track» с бюджетом 1000 usd уходило в `не годно [запрещённая_тема]`. Никакого
    конкретного человека в брифе нет — есть роль в кадре.
    """

    def test_роль_без_имени_работу_не_запрещает(self) -> None:
        итог = screen.просеять("Music video, singer lipsyncing to my track")
        self.assertEqual(итог["outcome"], "pass")
        self.assertEqual(итог["banned"], [])

    def test_актёр_в_корпоративном_ролике(self) -> None:
        self.assertEqual(screen.просеять("a corporate video with an actor on camera")["banned"], [])

    def test_известность_возвращает_заслон(self) -> None:
        """Негативный контроль (И5): послабление обязано где-то кончаться."""
        self.assertEqual(
            screen.просеять("a video with a famous singer")["banned"],
            ["recognisable third parties: singer"],
        )

    def test_названное_имя_возвращает_заслон(self) -> None:
        итог = screen.просеять("video of Elon Musk speaking, our singer")
        self.assertEqual(итог["banned"], ["recognisable third parties: singer"])


class ДетиВКадреИДетиВЗале(unittest.TestCase):
    """«Ролик ДЛЯ детей» называет зрителя, а не того, кто в кадре.

    ВОСПРОИЗВЕДЕНО той же проверкой: «Обучающий ролик для детей 5 лет,
    говорящий зайчик, 3 минуты» — отказ по теме «несовершеннолетние», при том
    что в кадре зайчик. Отсечён весь рынок детского обучающего контента.
    """

    def test_русская_аудитория_не_запрет(self) -> None:
        итог = screen.просеять("Обучающий ролик для детей 5 лет, говорящий зайчик, 3 минуты")
        self.assertEqual(итог["outcome"], "pass")
        self.assertEqual(итог["banned"], [])

    def test_английская_аудитория_не_запрет(self) -> None:
        """Обе половины заслона обязаны решать одинаково."""
        self.assertEqual(screen.просеять("educational clip for kids about space")["banned"], [])

    def test_ребёнок_в_кадре_остаётся_запретом(self) -> None:
        self.assertEqual(
            screen.просеять("ролик, где дети в кадре читают стихи")["banned"],
            ["minors: дети"],
        )

    def test_английский_ребёнок_в_кадре_остаётся_запретом(self) -> None:
        self.assertEqual(
            screen.просеять("a video with kids on camera reading poems")["banned"],
            ["minors: kids"],
        )

    def test_послабление_только_для_своей_группы(self) -> None:
        """«Порно для детей» спасаться этим правилом не должно."""
        self.assertEqual(
            screen.просеять("порноролик для детей")["banned"],
            ["adult content: порно"],
        )

    def test_предлог_перед_чужой_группой_ничего_не_снимает(self) -> None:
        """Русская половина: «для» перед словом ДРУГОЙ группы — не аудитория."""
        self.assertEqual(
            screen.просеять("сделайте ролик для порностудии")["banned"],
            ["adult content: порно"],
        )

    def test_предлог_перед_чужой_группой_на_английском(self) -> None:
        """И чужая половина списка (`style.py`) — тоже."""
        self.assertEqual(
            screen.просеять("a clip for nudity, 30 seconds")["banned"],
            ["adult content: nudity"],
        )


if __name__ == "__main__":
    unittest.main()
