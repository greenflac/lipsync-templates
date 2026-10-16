"""«Не знаю», записанное в поле значения, — не факт, а порча базы.

ВОСПРОИЗВЕДЕНО 2026-09-07 (И2), вывод прогона:

    'не знаю'          pass
    'unknown'          pass
    'N/A'              pass
    '—'                pass

и — то, ради чего это чинилось, — рядом с настоящим фактом:

    только настоящий:      pass   ('10 s', best tier probe)
    после мусорной строки: fail   «источники расходятся: '10 s' (probe);
                                   'не знаю' (blog)»

То есть незнание, записанное значением, ОТМЕНЯЕТ измеренное. У проекта есть
третий исход, чтобы говорить «не знаю» исходом; значение для этого не поле.

В ЖИВОЙ БАЗЕ ЭТО БЫЛО: две строки `expands_internally` со значением
`unknown`, обе с тиром `vendor`, обе давали читателю `pass`. Отозваны
2026-09-07 через `withdraw` (не удалены: спор остаётся в файле).

Т2: ожидаемое — литералы. Т4: сети нет, база лежит файлом. Ц2: файл новый.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from studio.mcp import advice
from studio.selfrag.facts import load_facts

#: ЭТОТ СПИСОК ОДИН РАЗ УЖЕ БЫЛ НЕВЕРЕН, И ЗАПИСЬ ОБ ЭТОМ ВАЖНЕЕ САМОГО
#: СПИСКА. 2026-09-07 первая приёмка назвала `none`, `null`, `na` ложными
#: отказами, я согласился и убрал их из двери, а тест — закрепил приём. Вторая
#: приёмка прогнала СТАРУЮ версию двери и показала, что основание было
#: выдумано: дверь сравнивает значение целиком, и «none — no prompt upsampling
#: on klein», «none required», «N/A regions» она пропускала всегда; отвергались
#: только ГОЛЫЕ, а таких в базе 0 строк из 2127. Ложного отказа не случалось ни
#: разу — заплачено было тем, что `str(None)` и JSON `null` стали фактами.
#:
#: Мораль не про слова, а про тест: он закреплял приём значений, которого
#: никто не измерил. Поэтому здесь теперь стоит ИЗМЕРЕННАЯ пара — голое
#: значение отвергается, оно же со словами проходит.
ГОЛЫЕ_НЕ_ОТВЕТЫ = ("none", "None", "null", "NULL", "NA", "na")
СО_СЛОВАМИ_ПРОХОДЯТ = (
    "none — no restrictions",
    "none required",
    "N/A regions",
    "NULL (API returns null when unset)",
)


#: Обе стороны прибора (И5). Слева — то, что обязано быть отвергнуто; справа —
#: то, что обязано пройти. Второй список важнее первого: ложный отказ здесь
#: дороже пропуска, потому что отвергнутый настоящий факт не запишет никто.
НЕ_ОТВЕТЫ = (
    "не знаю",
    "Неизвестно",
    "unknown",
    "UNKNOWN",
    "N/A",
    "n/a",
    "—",
    "не указано",
    "TBD",
    "?",
    "   ",
    "нет данных",
    *ГОЛЫЕ_НЕ_ОТВЕТЫ,
)

НАСТОЯЩИЕ = (
    "10 s",
    "unknown artifacts at 8 s",
    "N/A regions",
    "5",
    "1920x1080",
    "no audio track",
    "non-commercial",
    "none of the seeds held identity",
    "unknown-provenance checkpoint",
    *СО_СЛОВАМИ_ПРОХОДЯТ,
)


def _пустой() -> Path:
    каталог = tempfile.mkdtemp()
    путь = Path(каталог) / "facts.jsonl"
    путь.write_text("", encoding="utf-8")
    return путь


class НеОтветОтвергается(unittest.TestCase):
    def test_каждый_не_ответ_отвергнут_и_не_записан(self) -> None:
        путь = _пустой()
        for значение in НЕ_ОТВЕТЫ:
            итог = advice.record(
                "kling-3.0",
                "max_seconds",
                значение,
                "https://example.com/x",
                "blog",
                "2026-09-01",
                path=путь,
            )
            self.assertEqual("fail", итог["outcome"], значение)
            self.assertIsNone(итог["written"], значение)
        self.assertEqual("", путь.read_text(encoding="utf-8"))

    def test_причина_названа_словами(self) -> None:
        """Р2: отказ без названной причины чинить нечем."""
        нота = advice.record(
            "kling-3.0",
            "max_seconds",
            "не знаю",
            "https://example.com/x",
            "blog",
            "2026-09-01",
            path=_пустой(),
        )["note"]
        self.assertIn("не-ответ", нота)
        self.assertIn("не записывайте ничего", нота)


class НастоящееЗначениеПроходит(unittest.TestCase):
    """Вторая половина контроля (И5): прибор, отвергающий всё, ловит все
    не-ответы и не измеряет ничего."""

    def test_ни_одно_настоящее_значение_не_отвергнуто(self) -> None:
        путь = _пустой()
        for номер, значение in enumerate(НАСТОЯЩИЕ):
            итог = advice.record(
                "kling-3.0",
                f"attr_{номер}",
                значение,
                "https://example.com/x",
                "blog",
                "2026-09-01",
                path=путь,
            )
            self.assertEqual("pass", итог["outcome"], значение)

    def test_подстрока_не_считается(self) -> None:
        """Сравнение целым значением, а не вхождением: «unknown artifacts at
        8 s» — это наблюдение, а не пожатие плечами."""
        self.assertEqual("", advice.не_ответ("unknown artifacts at 8 s"))
        self.assertEqual("unknown", advice.не_ответ("  Unknown  "))


class ИзмереннаяПричинаПочинки(unittest.TestCase):
    """То, ради чего правило существует: не-ответ ОТМЕНЯЛ измеренное."""

    def test_мусорная_строка_больше_не_переводит_факт_в_fail(self) -> None:
        путь = _пустой()
        advice.record(
            "kling-3.0",
            "max_seconds",
            "10 s",
            "https://api.klingai.com/doc",
            "probe",
            "2026-09-01",
            path=путь,
        )
        до = advice.store_for(путь).claims("kling-3.0", "max_seconds")
        self.assertEqual("pass", до["outcome"])

        отказ = advice.record(
            "kling-3.0",
            "max_seconds",
            "не знаю",
            "https://example.com/x",
            "blog",
            "2026-09-01",
            path=путь,
        )
        self.assertEqual("fail", отказ["outcome"])

        после = advice.store_for(путь).claims("kling-3.0", "max_seconds")
        self.assertEqual("pass", после["outcome"])
        self.assertEqual(["10 s"], после["values"])


class ГолоеЗначениеОтличаетсяОтОтвета(unittest.TestCase):
    """И5 обеими сторонами на одном и том же слове.

    `none` голым — это невыставленное поле, `str(None)` или JSON `null`,
    приведённый к строке. `none — no restrictions` — настоящий ответ. Дверь
    обязана различать их, а не выбирать одну сторону.
    """

    def test_голое_отвергается_со_словами_проходит(self) -> None:
        self.assertTrue(advice.не_ответ("none"))
        self.assertFalse(advice.не_ответ("none — no restrictions"))
        self.assertTrue(advice.не_ответ("NA"))
        self.assertFalse(advice.не_ответ("N/A regions"))

    def test_отказ_называет_выход(self) -> None:
        """Отказ без выхода — это ловушка: писавший не узнает, как записать
        настоящий ответ, и не запишет его вовсе."""
        нота = advice.record(
            "kling-3.0",
            "requires_inputs",
            "none",
            "https://example.com/x",
            "blog",
            "2026-09-01",
            path=_пустой(),
        )["note"]
        self.assertIn("none — no restrictions", нота)


class ЖиваяБазаЧиста(unittest.TestCase):
    """Ц7: то, что обязано выполняться всегда, — тест, а не строка правил.

    Дверь закрыта, но база правится и руками, и скриптами сбора. Этот сторож
    считает не-ответы в том, что база УТВЕРЖДАЕТ сегодня.
    """

    def test_ни_одного_не_ответа_среди_живых_утверждений(self) -> None:
        факты = load_facts()
        self.assertGreater(len(факты), 1000, "база не загрузилась — считать нечего")
        плохие = [
            f"{f.model}.{f.attribute} = {f.value!r} ({f.source_url})"
            for f in факты
            if advice.не_ответ(f.value)
        ]
        self.assertEqual([], плохие, f"проверено {len(факты)}, не-ответов {len(плохие)}")


if __name__ == "__main__":
    unittest.main()
