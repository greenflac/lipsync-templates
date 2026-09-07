"""Спросит ли это ЧЕЛОВЕК — и достанет ли он то, ради чего строка собрана.

ЗАЧЕМ ОТДЕЛЬНО ОТ `test_attrfamily.py`. Тот модуль сторожит РАЗВОРОТ: спрошено
`price` — приехал `price_per_minute`. Здесь сторожится вход в разворот: есть ли
у семьи слово, которым её позовёт спрашивающий, не знающий наших имён.

ИЗМЕРЕНО 2026-09-07, до правки. Гейт `scripts/check_reachability.py --check`
печатал «не покрыто семьёй 0 строк(и) из 2127 = 0%» — и это правда ровно про
то, что он мерит: у каждого из 288 имён атрибутов ЕСТЬ семья. Но входом в 13 из
30 семей служило ТОЛЬКО имя самой семьи — наше внутреннее слово:

    duration_floor  measurement_method  model_identity  image_size  prompt_rule
    aspect_ratio    frame_rate  voice  editing  limits  billing  capabilities
    serving

На корпусе из 76 живых вопросов (ru+en) 51 не доставал НИЧЕГО, а 148 строк базы
из 2127 (7.0%) не доставал ни один из них. Через продукт это выглядело так:

    advise("eleven_v3", "positioning")               -> pass, positioning
    advise("eleven_v3", "для чего")                  -> could not measure
    advise("wan-2.2-a14b-i2v", "aspect_ratio")       -> pass, aspect_ratio_enum
    advise("wan-2.2-a14b-i2v", "пропорции")          -> could not measure
    advise("minimax-h3", "duration_floor")           -> pass, min_seconds
    advise("minimax-h3", "минимальная длительность") -> could not measure

После правки все 76 вопросов достают, недостижимых строк 0.

ЧТО ЗДЕСЬ ВАЖНЕЕ ПОЛОЖИТЕЛЬНОЙ СТОРОНЫ (И5). Синоним, ведущий не в ту семью,
ХУЖЕ пропуска: пропуск молчит, а он отвечает — ценой на вопрос о монтаже,
длиной промпта на вопрос о квотах. Поэтому на каждый заведённый вход здесь
стоит вход, где семья обязана сказать «нет», и отдельный класс проверяет, что
двусмысленные слова («качество», «размер», «формат», «требования») семьи НЕ
получили.

Ожидаемое во всех проверках — ЛИТЕРАЛЫ (Т2): списки имён выписаны руками, а не
взяты из `attrfamily`, иначе они поедут вместе с правкой и промолчат.
Сети здесь нет и быть не может: модуль в неё не ходит, а фактам, через которые
проверяется продукт, отведён временный файл.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date
from pathlib import Path

from studio.mcp import advice
from studio.selfrag import attrfamily

#: КОНСТАНТА-РЕШЕНИЕ ЭТОГО МОДУЛЯ. Сколько слов, КРОМЕ имени самой семьи,
#: обязано вести в семью.
#:
#: 2 — ЭТО ИЗМЕРЕННЫЙ ПОЛ, А НЕ КРУГЛОЕ ЧИСЛО. ИЗМЕРЕНО 2026-09-07 после
#: правки: самые бедные семьи — `resolution` и `image_size`, у них по 2 живых
#: слова; у остальных 28 от 3 до 8. Порог поставлен туда же, куда доехали, и
#: он обязан только расти. Единица пропустила бы семью, у которой живое слово
#: одно: одно слово — это одна догадка спрашивающего, и оно закрывает семью
#: только для того, кто угадал язык (`languages` без «язык» непроизносима для
#: русского вопроса). Ноль вернул бы измеренную дыру: он означает «внутреннего
#: имени достаточно», а именно так и молчали 13 семей.
МИНИМУМ_ЖИВЫХ_ВХОДОВ = 2


def _store(rows: list[dict]) -> Path:
    каталог = Path(tempfile.mkdtemp())
    файл = каталог / "facts.jsonl"
    файл.write_text(
        "\n".join(json.dumps(строка, ensure_ascii=False) for строка in rows) + "\n",
        encoding="utf-8",
    )
    return файл


def _факт(attribute: str, value: str) -> dict:
    return {
        "model": "test-model",
        "attribute": attribute,
        "value": value,
        "source_url": "https://example.test/a",
        "tier": "vendor",
        "stated_on": date.today().isoformat(),
        "note": "",
        "fix": "",
    }


class ЖивойВопросДоводитДоСемьи(unittest.TestCase):
    """Т3: края и середина по величине семьи в живой базе.

    `adoption` — 256 строк (самая крупная дыра замера 2026-09-04),
    `duration_floor` — 3 строки (самая мелкая семья базы),
    `voice` 21 и `editing` 19 — середина. Одним размером проверялся бы один
    размер: набор, собранный из одних крупных семей, был слеп на мелких.
    """

    ВОПРОСЫ = [
        # край: самая крупная семья
        ("сколько скачиваний", "adoption"),
        ("популярность", "adoption"),
        # край: самая мелкая семья
        ("минимальная длительность", "duration_floor"),
        ("минимум секунд", "duration_floor"),
        # середина
        ("голос", "voice"),
        ("озвучка", "voice"),
        ("монтаж", "editing"),
        ("продлить", "editing"),
        # семьи, у которых входом было только внутреннее имя
        ("пропорции", "aspect_ratio"),
        ("частота кадров", "frame_rate"),
        ("как писать промт", "prompt_rule"),
        ("квоты", "limits"),
        ("как платят", "billing"),
        ("как позвать", "model_identity"),
        ("что умеет", "capabilities"),
        ("размер картинки", "image_size"),
        ("чем мерили", "measurement_method"),
        ("где хостится", "serving"),
        # семьи, названные в блюпринте самыми опасными
        ("устарела", "availability"),
        ("для чего", "positioning"),
        ("оценки", "benchmark_score"),
        ("держит ли лицо", "holds_identity"),
    ]

    def test_вопрос_попадает_в_свою_семью(self):
        for вопрос, ожидается in self.ВОПРОСЫ:
            with self.subTest(вопрос=вопрос):
                self.assertEqual(attrfamily.семья(вопрос), ожидается)

    def test_у_каждой_семьи_есть_человеческое_слово(self):
        """Гейт: новая семья обязана приехать со своим живым входом.

        Без него семья считается «покрытой» в `check_reachability.py` и при
        этом непроизносима — ровно то состояние, ради которого писан модуль.
        """
        входов = {имя: 0 for имя in attrfamily.СЕМЬИ}
        for слово, семья in attrfamily.СИНОНИМЫ.items():
            if семья in входов and attrfamily.норма(слово) != семья:
                входов[семья] += 1
        немые = sorted(имя for имя, сколько in входов.items() if сколько < МИНИМУМ_ЖИВЫХ_ВХОДОВ)
        self.assertEqual(немые, [], f"семьи без человеческого входа: {немые}")


class ПробелИПодчёркиваниеОдноИТоЖе(unittest.TestCase):
    """Синоним `для_чего` был записан с подчёркиванием — его никто не наберёт."""

    def test_норма_склеивает_пробел(self):
        self.assertEqual(attrfamily.норма("  Для  Чего "), "для_чего")

    def test_оба_написания_ведут_в_одну_семью(self):
        self.assertEqual(attrfamily.семья("для чего"), "positioning")
        self.assertEqual(attrfamily.семья("для_чего"), "positioning")

    def test_имя_семьи_спрашивается_и_пробелом(self):
        self.assertEqual(attrfamily.семья("aspect ratio"), "aspect_ratio")
        self.assertEqual(attrfamily.семья("frame rate"), "frame_rate")


class ЧужойВопросНичегоНеДостаёт(unittest.TestCase):
    """И5: вход, где прибор обязан сказать «нет».

    Каждое слово ниже звучит как вопрос и означает РАЗНОЕ в двух семьях сразу.
    Если оно когда-нибудь получит семью, ответ станет уверенным и неверным.
    """

    ДВУСМЫСЛЕННЫЕ = [
        "качество",  # и `quality_options`, и `benchmark_score`, и протокол оценки
        "размер",  # и картинка, и вес файла, и число параметров
        "формат",  # и пропорции кадра, и контейнер выхода
        "требования",  # и железо, и `requires_inputs`
        "модель",
        "видео",
        "лучше",
    ]

    def test_двусмысленное_слово_семьи_не_имеет(self):
        for слово in self.ДВУСМЫСЛЕННЫЕ:
            with self.subTest(слово=слово):
                self.assertEqual(attrfamily.семья(слово), "")

    def test_склейка_кусков_не_считается_вопросом(self):
        """`норма` склеивает разделители, а НЕ ищет подстроку.

        «сколько стоит продление» содержит и «сколько стоит» (цена), и
        «продление» (монтаж). Подстрочный поиск ответил бы ценой на вопрос о
        монтаже — и выглядел бы как ответ.
        """
        self.assertEqual(attrfamily.семья("сколько стоит продление"), "")
        self.assertEqual(attrfamily.семья("цена за лицо"), "")
        self.assertEqual(
            attrfamily.expand("сколько стоит продление", ["price_per_minute", "editing"]),
            [],
        )


class НовыйВходНеЗабираетЧужого(unittest.TestCase):
    """Что именно приезжает на новое слово — списком, а не «непусто».

    Списки записаны литералами (Т2). В каждом наборе `recorded` лежат имена
    ДВУХ соседних семей сразу: проверка «пришло непусто» прошла бы и на семье,
    забравшей всё подряд.
    """

    def test_промт_не_забирает_предел_текста(self):
        self.assertEqual(
            attrfamily.expand(
                "промт", ["prompt_skeleton", "max_prompt_length", "prompt_length_limit"]
            ),
            ["prompt_skeleton"],
        )

    def test_квоты_не_забирают_длину_текста(self):
        self.assertEqual(
            attrfamily.expand("квоты", ["concurrency", "character_limit", "text_input_limit"]),
            ["concurrency"],
        )

    def test_голос_не_забирает_цену_звука(self):
        self.assertEqual(
            attrfamily.expand("голос", ["max_speakers", "price_per_audio_second"]),
            ["max_speakers"],
        )

    def test_размер_картинки_не_забирает_вес_файла(self):
        self.assertEqual(
            attrfamily.expand(
                "размер картинки", ["default_short_side", "file_size_limits", "max_image_payload"]
            ),
            ["default_short_side"],
        )

    def test_как_быстро_считает_модель_а_не_служба(self):
        self.assertEqual(
            attrfamily.expand("как быстро", ["generation_time", "queue_latency", "ttfb_by_region"]),
            ["generation_time"],
        )

    def test_очередь_это_служба_а_не_модель(self):
        self.assertEqual(
            attrfamily.expand("очередь", ["queue_latency", "generation_time"]),
            ["queue_latency"],
        )

    def test_пол_длительности_не_отдаёт_потолок(self):
        self.assertEqual(
            attrfamily.expand("минимальная длительность", ["min_seconds", "max_seconds"]),
            ["min_seconds"],
        )

    def test_потолок_длительности_не_отдаёт_пол(self):
        self.assertEqual(
            attrfamily.expand("сколько секунд", ["max_seconds", "min_seconds"]),
            ["max_seconds"],
        )

    def test_пропорции_не_забирают_цену_и_время(self):
        self.assertEqual(
            attrfamily.expand(
                "пропорции", ["aspect_ratio_enum", "price_per_generation", "generation_time"]
            ),
            ["aspect_ratio_enum"],
        )

    def test_кадры_это_частота_а_не_раскадровка(self):
        self.assertEqual(
            attrfamily.expand("кадры", ["fps", "keyframes_max", "first_last_frame"]),
            ["fps"],
        )

    def test_оценки_это_число_а_не_оговорка_о_нём(self):
        self.assertEqual(
            attrfamily.expand("оценки", ["benchmark_score", "faithfulness_benchmark_saturation"]),
            ["benchmark_score"],
        )

    def test_чем_мерили_это_оговорка_а_не_число(self):
        self.assertEqual(
            attrfamily.expand(
                "чем мерили", ["faithfulness_benchmark_saturation", "benchmark_score"]
            ),
            ["faithfulness_benchmark_saturation"],
        )

    def test_как_позвать_не_отвечает_снята_ли(self):
        """Судьбу плана решает второй вопрос, и подменять его первым нельзя."""
        self.assertEqual(
            attrfamily.expand("как позвать", ["model_id", "status", "end_of_life"]),
            ["model_id"],
        )

    def test_снята_ли_не_отвечает_идентификатором(self):
        self.assertEqual(
            attrfamily.expand("устарела", ["status", "end_of_life", "model_id"]),
            ["end_of_life", "status"],
        )


class ПродуктОтвечаетНаЖивойВопрос(unittest.TestCase):
    """Тот же путь, каким идёт пользователь: `advise`, а не `expand`.

    Считать мимо продукта — называть работой то, чего нет (это уже стоило
    замера в шапке `attrfamily`). Факты лежат во временном файле: живая база
    здесь не читается и сеть не трогается.
    """

    def setUp(self):
        self.путь = _store(
            [
                _факт("adoption", "1.2M downloads on Hugging Face"),
                _факт("min_seconds", "2"),
                _факт("aspect_ratio_enum", "16:9, 9:16, 1:1"),
                _факт("end_of_life", "retired on 2026-01-01"),
                _факт("positioning", "dubbing over talking-head footage"),
            ]
        )

    def _спросить(self, слово: str) -> tuple[str, list[str]]:
        итог = advice.advise("test-model", слово, path=self.путь)
        return итог["outcome"], sorted(итог["claims"])

    def test_живой_вопрос_доводит_до_записанного(self):
        for вопрос, ожидается in [
            ("сколько скачиваний", ["adoption"]),
            ("минимальная длительность", ["min_seconds"]),
            ("пропорции", ["aspect_ratio_enum"]),
            ("устарела", ["end_of_life"]),
            ("для чего", ["positioning"]),
        ]:
            with self.subTest(вопрос=вопрос):
                исход, имена = self._спросить(вопрос)
                self.assertEqual(имена, ожидается)
                self.assertEqual(исход, "pass")

    def test_чужой_вопрос_остаётся_третьим_исходом(self):
        """Р1: «не спрашивали такого» не сворачивается в «ответили»."""
        исход, имена = self._спросить("качество")
        self.assertEqual(имена, ["качество"])
        self.assertEqual(исход, "could not measure")


if __name__ == "__main__":
    unittest.main()
