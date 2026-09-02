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


class ЛицензионнаяСемья(unittest.TestCase):
    """Тот же дефект, что у цены, но в опасную сторону.

    ИЗМЕРЕНО 2026-09-02 ЧЕРЕЗ `advise` (а не по сырым строкам): из 253 моделей
    с лицензионной строкой на вопрос `license` молчали 14, и у 11 записана
    некоммерческая оговорка и больше ничего. Модель, которую нельзя брать в
    коммерческую работу, отвечала «о лицензии ничего не известно» — ровно
    перед решением, которое правило Ц5 велит принимать ПОСЛЕ чтения лицензии.
    """

    def test_оговорка_отвечает_на_вопрос_о_лицензии(self):
        self.assertEqual(
            attrfamily.expand("license", ["license_restriction"]), ["license_restriction"]
        )

    def test_лицензия_хвостом_имени_тоже_находится(self):
        """`architecture_and_license` — два имени пишут лицензию хвостом."""
        self.assertEqual(
            attrfamily.expand("license", ["architecture_and_license"]),
            ["architecture_and_license"],
        )

    def test_условия_площадки_лицензией_модели_не_считаются(self):
        """И5: `portal_license` — условия ПЕРЕПРОДАЖИ. На fal.ai все 57
        карточек `commercial`, и у модели, чьи веса лежат под «research only»,
        такой ответ дал бы ложный зелёный на правиле Ц5."""
        self.assertEqual(attrfamily.expand("license", ["portal_license"]), [])

    def test_британское_написание_спрашивает_то_же(self):
        self.assertEqual(
            attrfamily.expand("licence", ["license_restriction"]), ["license_restriction"]
        )

    def test_цена_лицензией_не_становится(self):
        """Вторая половина: семьи не перетекают друг в друга."""
        self.assertEqual(attrfamily.expand("license", ["price_per_minute"]), [])
        self.assertEqual(attrfamily.expand("price", ["license_restriction"]), [])


class ДлительностьВыходаНеДлительностьВхода(unittest.TestCase):
    """ИЗМЕРЕНО через `advise`: строка о длительности записана у 45 моделей, а
    на вопрос `max_seconds` отвечали 25. «Сколько секунд может выйти» — вопрос
    видеостудии номер два после цены.

    Негативный контроль здесь острее обычного: у соседних имён то же слово
    `seconds` означает ДРУГУЮ длительность, и вернуть их значит ответить
    числом не на тот вопрос.
    """

    def test_перечисление_длительностей_это_ответ(self):
        self.assertEqual(attrfamily.expand("max_seconds", ["duration_enum"]), ["duration_enum"])

    def test_другая_единица_тоже_ответ(self):
        """`max_duration_ms = 600000 ms (10 min)` — тот же вопрос, другая
        единица; она видна в имени, как и у цены."""
        self.assertEqual(
            attrfamily.expand("длительность", ["max_duration_ms"]), ["max_duration_ms"]
        )

    def test_длина_поданного_звука_это_не_длина_ролика(self):
        """`bytedance-omnihuman / max_audio_seconds = 30` — сколько звука можно
        подать, а не сколько видео выйдет."""
        self.assertEqual(attrfamily.expand("max_seconds", ["max_audio_seconds"]), [])

    def test_длина_поданного_видео_и_референса_тоже_не_ответ(self):
        self.assertEqual(attrfamily.expand("max_seconds", ["max_input_seconds"]), [])
        self.assertEqual(attrfamily.expand("max_seconds", ["reference_video_duration_range"]), [])

    def test_кадры_без_частоты_это_не_секунды(self):
        """`max_frames = 161`: без частоты кадров из этого длительность не
        следует, а подставить 24 значило бы решить за вендора."""
        self.assertEqual(attrfamily.expand("max_seconds", ["max_frames"]), [])


class РазрешениеПодЛюбымИменем(unittest.TestCase):
    """ИЗМЕРЕНО через `advise`: строка о разрешении записана у 40 моделей, а на
    вопрос `resolution` отвечали 2 — канонического имени почти ни у кого нет,
    вендоры пишут `max_resolution`, `native_resolution`, `resolutions_vertex`.
    """

    def test_слово_ловится_в_любом_месте_имени(self):
        self.assertEqual(
            attrfamily.expand("resolution", ["max_resolution", "resolutions_vertex"]),
            ["max_resolution", "resolutions_vertex"],
        )

    def test_разрешение_обучения_пределом_входа_не_является(self):
        """И5: `latentsync-1.6` держит только `training_resolution`, и ответить
        им на вопрос «какой кадр модель принимает» значит ответить не на тот
        вопрос. То же исключение стоит в `scripts/creative_fit.py` и берётся
        отсюда (Е1)."""
        self.assertEqual(attrfamily.expand("resolution", ["training_resolution"]), [])

    def test_семьи_не_перетекают(self):
        self.assertEqual(attrfamily.expand("resolution", ["max_seconds"]), [])
        self.assertEqual(attrfamily.expand("max_seconds", ["max_resolution"]), [])
