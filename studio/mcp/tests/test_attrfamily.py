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


class ПоведениеМоделиПодЛюбымИменем(unittest.TestCase):
    """Семья поведения. Заведена по находке голден-сета 2026-09-03: вопрос
    «на что жалуются практики» получал «ничего не записано» при тринадцати
    живых строках ровно об этом в базе."""

    ЗАПИСАНО = (
        "observed_behaviour",
        "failure_mode",
        "degrades_when",
        "limitation",
        "artifact_taxonomy",
        "metric_blind_spot",
        "lipsync_identity_failure_mode",
        "upscale_artifacts",
        "fvd_blind_spot_spatial_bias",
    )
    #: Имена, которые ЛЕЖАТ РЯДОМ В БАЗЕ и поведением не являются: это числа
    #: API. Т2 — литералы, а не выборка из проверяемого модуля.
    ЧИСЛА_API = (
        "character_limit",
        "prompt_length_limit",
        "text_input_limit",
        "file_size_limits",
        "upload_limits",
        "concurrency_limits",
        "keyterms_limit",
        "input_image_limits",
    )

    def test_родственные_имена_отвечают_на_вопрос_о_поведении(self):
        подошли = attrfamily.expand("observed_behaviour", list(self.ЗАПИСАНО))
        self.assertEqual(sorted(self.ЗАПИСАНО), sorted(подошли))

    def test_спрошенное_имя_стоит_первым(self):
        подошли = attrfamily.expand("observed_behaviour", ["failure_mode", "observed_behaviour"])
        self.assertEqual("observed_behaviour", подошли[0])

    def test_числа_api_поведением_не_становятся(self):
        """И5, негативный контроль семьи: семья, ловящая подстроку «limit»,
        ответила бы на «на что жалуются» строкой «character_limit = 5000»."""
        подошли = attrfamily.expand("observed_behaviour", list(self.ЧИСЛА_API))
        self.assertEqual([], подошли)

    def test_параметры_модели_поведением_не_становятся(self):
        подошли = attrfamily.expand("observed_behaviour", ["strength", "cloning_strength"])
        self.assertEqual([], подошли)

    def test_слова_вопроса_доводят_до_семьи(self):
        for слово in ("проблемы", "жалобы", "issues", "problems", "behaviour", "применимость"):
            self.assertEqual(
                "observed_behaviour", attrfamily.семья(слово), f"слово {слово} не доводит"
            )

    def test_семья_поведения_не_перетекает_в_цену_и_лицензию(self):
        подошли = attrfamily.expand("observed_behaviour", ["price", "license", "max_seconds"])
        self.assertEqual([], подошли)


class ВходИВыходРазныеВопросы(unittest.TestCase):
    """Семьи входа и выхода. Заведены системным замером 2026-09-03: из 287 имён
    базы семьями достижимы были 62, и на естественный вопрос «inputs» продукт
    отвечал «ничего не записано» при 92 строках `requires_inputs`."""

    ЗАПИСАНО = (
        "accepts_inputs",
        "requires_inputs",
        "accepts_images",
        "accepts_input_video",
        "input_modalities",
        "reference_images",
        "produces_outputs",
        "output_formats",
        "price_per_input_second",
        "price_per_million_input_usd",
        "price_per_output_second",
        "license_restriction",
        "max_seconds",
    )

    def test_вопрос_о_входе_доводит_до_записанных_имён(self) -> None:
        подошли = attrfamily.expand("inputs", list(self.ЗАПИСАНО))
        self.assertEqual(
            [
                "accepts_images",
                "accepts_input_video",
                "accepts_inputs",
                "input_modalities",
                "reference_images",
                "requires_inputs",
            ],
            sorted(подошли),
        )

    def test_выход_отдельный_вопрос_а_не_тот_же(self) -> None:
        """«Что принимает» и «что отдаёт» — разные вопросы. Ответить на один
        другим значило бы солгать тем же способом, от которого семьи заведены."""
        вход = set(attrfamily.expand("inputs", list(self.ЗАПИСАНО)))
        выход = set(attrfamily.expand("outputs", list(self.ЗАПИСАНО)))
        self.assertEqual(set(), вход & выход)
        self.assertEqual({"output_formats", "produces_outputs"}, выход)

    def test_чужая_приставка_сильнее_своей_подстроки(self) -> None:
        """И5: `price_per_input_second` содержит «input», и без этого правила
        семья входов отвечала бы на «что принимает модель» ценой в долларах."""
        подошли = attrfamily.expand("inputs", ["price_per_input_second", "accepts_inputs"])
        self.assertEqual(["accepts_inputs"], подошли)

    def test_семья_с_приставкой_берёт_своё_веткой_приставки(self) -> None:
        """Ценовая семья отбирает свои имена приставкой, и правило занятых
        приставок ей не мешает: ветка приставки стоит раньше подстрочной."""
        подошли = attrfamily.expand("price", ["price_per_input_second", "accepts_inputs"])
        self.assertEqual(["price_per_input_second"], подошли)

    def test_слова_вопроса_доводят_до_семей(self) -> None:
        for слово, ждём in (
            ("вход", "accepts_inputs"),
            ("что принимает", "accepts_inputs"),
            ("выход", "produces_outputs"),
            ("что отдаёт", "produces_outputs"),
        ):
            self.assertEqual(ждём, attrfamily.семья(слово), f"слово {слово} не доводит")


class ПределТекстаНеЛюбоеСловоПроТекст(unittest.TestCase):
    """Сколько текста влезает в модель. 28 моделей это записывают."""

    ОТВЕЧАЮТ = (
        "character_limit",
        "max_text_length",
        "context_window_tokens",
        "prompt_length_limit",
        "text_input_limit",
        "keyterms_limit",
        "max_prompt_length",
        "max_script_characters",
    )
    #: Имена, которые ЛЕЖАТ РЯДОМ и на этот вопрос не отвечают. Т2 — литералы.
    #: Подстрочная семья по «text» или «character» втянула бы все шесть.
    ШУМ = (
        "text_rendering",
        "text_rendering_non_latin",
        "text_normalization_default",
        "ratio_enum_text_to_video",
        "character_orientation",
        "long_context_surcharge",
    )

    def test_записанные_пределы_отвечают(self) -> None:
        self.assertEqual(
            sorted(self.ОТВЕЧАЮТ), sorted(attrfamily.expand("предел текста", list(self.ОТВЕЧАЮТ)))
        )

    def test_слова_про_текст_пределом_не_становятся(self) -> None:
        self.assertEqual([], attrfamily.expand("предел текста", list(self.ШУМ)))

    def test_предел_выхода_это_другой_вопрос(self) -> None:
        """Вход и выход в этом модуле разведены; держать одно правило во входах
        и другое здесь значило бы иметь два представления об одном."""
        self.assertEqual([], attrfamily.expand("предел текста", ["max_output_tokens_recommended"]))

    def test_цена_за_символы_это_не_предел(self) -> None:
        """Правило занятых приставок работает и здесь: `price_per_1000_chars`
        отвечает на вопрос о ДЕНЬГАХ."""
        self.assertEqual(
            [], attrfamily.expand("предел текста", ["price_per_1000_chars", "price_per_token"])
        )

    def test_слова_вопроса_доводят_до_семьи(self) -> None:
        for слово in ("предел текста", "сколько текста", "character_limit", "context_window"):
            self.assertEqual("text_limit", attrfamily.семья(слово), f"слово {слово} не доводит")


class СемьиЗаведённыеПоЗамеруНедостижимости(unittest.TestCase):
    """Пять семей, закрывших 400 строк базы, и их негативные контроли.

    ИЗМЕРЕНО 2026-09-04: до них недостижимо 594 строки из 2099 (28.3%), после —
    194 (9.2%) при пороге R3 в 10%. Одна только `adoption` держала 256 строк:
    «насколько это популярно» спросить было НЕЧЕМ.
    """

    def test_популярность_спрашивается_и_по_русски(self) -> None:
        записаны = ["adoption", "price_per_second"]
        for слово in ("adoption", "популярность", "downloads"):
            self.assertEqual(["adoption"], attrfamily.expand(слово, записаны), слово)

    def test_вопрос_о_лице_приносит_и_плохую_новость(self) -> None:
        """Спросивший «держит ли лицо» обязан узнать, что оно НЕ держится."""
        записаны = ["holds_identity", "lipsync_identity_failure_mode", "price"]
        итог = attrfamily.expand("лицо", записаны)
        self.assertIn("holds_identity", итог)
        self.assertIn("lipsync_identity_failure_mode", итог)
        self.assertNotIn("price", итог)

    def test_бренд_площадки_на_вопрос_о_лице_не_отвечает(self) -> None:
        """И5 у семьи лица: `product_identity` — про бренд, а не про кадр."""
        self.assertEqual([], attrfamily.expand("лицо", ["product_identity"]))

    def test_снята_ли_модель_спрашивается_пятью_именами(self) -> None:
        """Блюпринт называл эту дыру самой опасной: канал специально собирает
        «снята ли», а спросить это было нечем."""
        записаны = ["availability", "status", "end_of_life", "lifecycle", "deprecation"]
        self.assertEqual(sorted(записаны), sorted(attrfamily.expand("снята", записаны)))

    def test_насыщение_бенчмарка_не_выдаётся_за_оценку(self) -> None:
        """И5 у семьи бенчмарка, и это главный её заслон.

        `faithfulness_benchmark_saturation` говорит, что бенчмарк НАСЫТИЛСЯ, —
        это утверждение ПРОТИВ числа, а не число. Подстрока «benchmark»
        затянула бы его, и на вопрос «что у неё на бенчмарках» пришёл бы ответ,
        отвечающий на другой вопрос.
        """
        записаны = ["benchmark_score", "faithfulness_benchmark_saturation"]
        self.assertEqual(["benchmark_score"], attrfamily.expand("бенчмарк", записаны))

    def test_железо_собрано_одной_семьёй(self) -> None:
        записаны = ["min_vram_gb", "runs_on", "parameter_count", "price"]
        итог = attrfamily.expand("железо", записаны)
        self.assertEqual(["min_vram_gb", "parameter_count", "runs_on"], sorted(итог))

    def test_цена_не_течёт_ни_в_одну_новую_семью(self) -> None:
        """Сквозной негативный контроль: цена — самая частая приставка базы, и
        любая широкая подстрока тянет её первой."""
        for слово in ("популярность", "лицо", "снята", "бенчмарк", "железо", "языки"):
            self.assertNotIn(
                "price_per_second_usd", attrfamily.expand(слово, ["price_per_second_usd"]), слово
            )


class СемьиЗаведённыеРадиR3(unittest.TestCase):
    """Тринадцать семей, заведённых 2026-09-05, чтобы довести достижимость базы
    до 100%. Каждая проверяется С ДВУХ СТОРОН: что она отвечает на свой вопрос
    и что она НЕ забирает похоже названное чужое (И5). Ожидаемое — литералы
    (Т2): имена атрибутов написаны руками, а не взяты из `СЕМЬИ`, иначе тест
    поедет вместе с семьёй и промолчит.

    Входы — настоящие имена из живой базы 2026-09-05, а не выдуманные: семья,
    проверенная на придуманном имени, меряет мою фантазию.
    """

    #: Все имена атрибутов живой базы на день заведения семей.
    ИМЕНА = (
        "aspect_ratio_enum",
        "ratio_enum",
        "aspect_ratios_vertex",
        "duration_range_seconds",
        "moderation",
        "generation_time",
        "price_per_generation",
        "fps",
        "frame_rate",
        "first_last_frame",
        "keyframe_conditioning_tradeoff",
        "native_resolution_and_frames",
        "voice_controls",
        "max_audio_seconds",
        "price_per_audio_second",
        "speed_range",
        "editing",
        "prompt_rule_edit",
        "extension_constraints",
        "expands_internally",
        "expander_evidence",
        "prompt_skeleton",
        "max_prompt_length",
        "arena_rank_vs_prompt_adherence",
        "min_seconds",
        "max_seconds",
        "price_relative",
        "portal_license",
        "license_restriction",
        "training_resolution",
        "resolution_enum",
    )

    def полe(self, вопрос: str) -> set[str]:
        return set(attrfamily.expand(вопрос, list(self.ИМЕНА)))

    def test_пропорции_кадра_не_тянут_длительность_и_модерацию(self):
        поля = self.полe("aspect_ratio")
        self.assertIn("aspect_ratio_enum", поля)
        self.assertIn("ratio_enum", поля)
        self.assertIn("aspect_ratios_vertex", поля)
        # Подстрока `ratio` тянула бы всё это — 26 имён вместо 9.
        self.assertNotIn("duration_range_seconds", поля)
        self.assertNotIn("moderation", поля)
        self.assertNotIn("generation_time", поля)
        self.assertNotIn("price_per_generation", поля)

    def test_частота_кадров_не_тянет_монтаж_и_разрешение(self):
        поля = self.полe("frame_rate")
        self.assertIn("fps", поля)
        self.assertIn("frame_rate", поля)
        self.assertNotIn("first_last_frame", поля, "это монтаж, а не частота")
        self.assertNotIn("keyframe_conditioning_tradeoff", поля, "это находка бенчмарка")
        self.assertNotIn("native_resolution_and_frames", поля, "там разрешение")

    def test_голос_не_тянет_цену_звука(self):
        поля = self.полe("voice")
        self.assertIn("voice_controls", поля)
        self.assertIn("max_audio_seconds", поля)
        self.assertIn("speed_range", поля, "темп РЕЧИ живёт здесь, а не в скорости")
        self.assertNotIn("price_per_audio_second", поля, "это цена")

    def test_правка_готового_не_тянет_расширение_ПРОМПТА(self):
        """Найдено чтением выдачи глазами (П3): префикс `expand` приводил на
        вопрос «умеет ли править готовое» строку «длина промпта коррелирует с
        качеством на -0.07». Это про переписывание промпта, а не про продление
        ролика."""
        поля = self.полe("editing")
        self.assertIn("editing", поля)
        self.assertIn("extension_constraints", поля)
        self.assertNotIn("expands_internally", поля)
        self.assertNotIn("expander_evidence", поля)
        self.assertNotIn("prompt_rule_edit", поля, "это правило написания промпта")

    def test_правило_промпта_забрало_расширение_промпта(self):
        """Обратная сторона того же: выброшенное из `editing` не потерялось."""
        поля = self.полe("prompt_rule")
        self.assertIn("expands_internally", поля)
        self.assertIn("expander_evidence", поля)
        self.assertIn("prompt_skeleton", поля)
        self.assertNotIn("max_prompt_length", поля, "это предел текста")
        self.assertNotIn("arena_rank_vs_prompt_adherence", поля, "это бенчмарк")

    def test_минимум_длительности_не_смешан_с_максимумом(self):
        self.assertIn("min_seconds", self.полe("duration_floor"))
        self.assertNotIn("min_seconds", self.полe("max_seconds"))
        self.assertNotIn("max_seconds", self.полe("duration_floor"))

    def test_условия_оплаты_забрали_относительную_цену(self):
        """`price_relative` («на 50% дешевле») исключена из `price` с самого
        начала: сколько платят, из неё не следует. Но и молчать она не должна."""
        self.assertIn("price_relative", self.полe("billing"))
        self.assertNotIn("price_relative", self.полe("price"))

    def test_лицензия_площадки_отвечает_на_вопрос_об_оплате(self):
        self.assertIn("portal_license", self.полe("billing"))

    def test_разрешение_обучения_не_отвечает_на_вопрос_о_разрешении(self):
        """Прежнее решение модуля сохранено: `training_resolution` — предел
        ОБУЧЕНИЯ голоса/модели, а не предел входа."""
        self.assertNotIn("training_resolution", self.полe("resolution"))
        self.assertIn("training_resolution", self.полe("image_size"))
