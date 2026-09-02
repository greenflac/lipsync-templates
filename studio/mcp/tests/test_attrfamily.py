"""Разворот спрошенного слова в записанные имена — и его негативный контроль.

Этот модуль заведён по измерению: цена записана у 79 моделей, а на вопрос
`price` отвечали 7. Проверяется ровно то, из-за чего он появился, и ровно то,
чего он делать не должен, — второе важнее: подстроечное совпадение по «time»
или «speed» вернуло бы частоту кадров в ответ на вопрос о скорости работы.
"""

from __future__ import annotations

import unittest

from studio.selfrag import attrfamily


class Разворот(unittest.TestCase):
    def test_цена_под_другим_именем_находится(self):
        """ИЗМЕРЕНО на живой базе: `sync-lipsync-2` держит цену под
        `price_per_minute`, и вопрос `price` возвращал «не записано»."""
        self.assertEqual(
            attrfamily.expand("price", ["price_per_minute", "license"]),
            ["price_per_minute"],
        )

    def test_спрошенное_имя_стоит_первым(self):
        """Читают сверху: ответ на заданный вопрос не должен стоять третьим
        среди родственников."""
        self.assertEqual(
            attrfamily.expand("price", ["price_per_second_usd", "price", "price_per_minute"]),
            ["price", "price_per_minute", "price_per_second_usd"],
        )

    def test_синоним_спрашивает_то_же(self):
        for слово in ("cost", "цена", "PRICING"):
            with self.subTest(слово=слово):
                self.assertEqual(
                    attrfamily.expand(слово, ["price_per_minute"]), ["price_per_minute"]
                )

    def test_разворот_идёт_по_записанному_а_не_по_словарю(self):
        """Иначе ответ распух бы пустыми ключами тех имён, которых у модели
        нет, и `checked` посчитал бы их проверенными."""
        self.assertEqual(attrfamily.expand("price", ["license"]), [])


class НегативныйКонтроль(unittest.TestCase):
    """И5: у семьи есть вход, где она обязана сказать «нет».

    Каждое имя ниже звучит как ответ и означает другое; проверено по ЗНАЧЕНИЮ
    в живой базе, а не по звучанию.
    """

    def test_частота_кадров_не_скорость_работы(self):
        self.assertEqual(attrfamily.expand("скорость", ["fps", "frames_and_fps"]), [])

    def test_темп_речи_и_режим_рендера_не_скорость(self):
        self.assertEqual(attrfamily.expand("speed", ["speed_range", "rendering_speed"]), [])

    def test_обучение_и_индексация_не_генерация(self):
        self.assertEqual(attrfamily.expand("speed", ["training_time", "indexing_latency"]), [])

    def test_насколько_дешевле_это_не_цена(self):
        """`price_relative = "50% lower price per character"` — сколько платят,
        из него не следует, а разборщик цен однажды прочёл его как 50.0."""
        self.assertEqual(attrfamily.expand("price", ["price_relative"]), [])

    def test_семья_шевелится_на_настоящей_скорости(self):
        """Вторая половина негативного контроля: прибор обязан не только
        молчать на чужом, но и срабатывать на своём."""
        self.assertEqual(
            attrfamily.expand("скорость", ["latency", "generation_time"]),
            ["generation_time", "latency"],
        )

    def test_атрибут_без_семьи_не_разворачивается(self):
        """`max_seconds` спрашивается ровно как назван: развернуть его значит
        ответить на другой вопрос."""
        self.assertEqual(
            attrfamily.expand("max_seconds", ["max_seconds", "max_resolution"]), ["max_seconds"]
        )
        self.assertEqual(attrfamily.expand("max_seconds", ["max_resolution"]), [])


class РазворотНазываетсяВслух(unittest.TestCase):
    """Молчаливая подмена спрошенного на похожее — новое враньё вместо
    старого: минуту сравнят с секундой соседней модели."""

    def test_подмена_называется(self):
        нота = attrfamily.как_отвечено("price", ["price_per_minute", "price_per_second_usd"])
        self.assertIn("price_per_minute", нота)
        self.assertIn("price_per_second_usd", нота)
        self.assertIn("сравнивать", нота)

    def test_одно_имя_называет_единицу_а_не_сравнение(self):
        """Предупреждение «единицы разные» при одном имени — шум: сравнивать
        не с чем. Названо должно быть другое: чья это единица."""
        нота = attrfamily.как_отвечено("price", ["price_per_minute"])
        self.assertIn("price_per_minute", нота)
        self.assertNotIn("РАЗНЫЕ", нота)

    def test_совпало_ноты_нет(self):
        self.assertEqual(attrfamily.как_отвечено("price", ["price"]), "")
        self.assertEqual(attrfamily.как_отвечено("", ["price"]), "")


if __name__ == "__main__":
    unittest.main()
