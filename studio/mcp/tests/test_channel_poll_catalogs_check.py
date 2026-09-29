"""Офлайновая проверка канала каталогов: сходится ли сводка опроса с каталогом.

ЗАЧЕМ ОНА ЕСТЬ. Канал пишет два файла — сводку и индекс, — и до 2026-09-07 ни
один гейт не спрашивал, говорят ли они одно и то же. Расхождение флага и
свидетельства (Е2) здесь стоит дорого: «openrouter: 395 записей» в сводке при
двенадцати строках в каталоге читается как полный обзор рынка.

НЕГАТИВНЫЙ КОНТРОЛЬ ДВУСТОРОННИЙ (И5): на здоровой паре файлов прибор обязан
ПРОМОЛЧАТЬ, на каждой из четырёх порч — сказать «нет» и назвать, что именно.

Ожидаемое — литералы (Т2), сети нет (её отбирает раннер, Т4), фикстуры взяты с
обоих краёв и из середины (Т3): пустой каталог, здоровая пара, порченая пара.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "poll_catalogs", Path(__file__).resolve().parents[3] / "scripts" / "poll_catalogs.py"
)
assert _SPEC and _SPEC.loader
pc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pc)

#: Четыре каталога, у которых нет ключа. Список НЕ импортируется из скрипта
#: (Т2): импортированное ожидание поехало бы вместе с кодом и промолчало.
БЕЗ_КЛЮЧА = ("replicate", "together", "artificialanalysis", "wavespeed")


def _сводка(**поверх) -> dict:
    """Здоровая сводка опроса: два канала ответили, четыре без ключа."""
    итог = {
        "polled_on": "2026-09-01",
        "channels": [
            {"catalog": "openrouter", "records": 2, "state": "ok"},
            {"catalog": "deepinfra", "records": 1, "state": "ok"},
        ],
        "channels_asked": 2,
        "channels_answered": 2,
        "keyed_out": [{"catalog": имя, "state": "could not measure"} for имя in БЕЗ_КЛЮЧА],
        "checked": 3,
    }
    итог.update(поверх)
    return итог


def _строка(каталог: str, имя: str) -> dict:
    """Запись каталога, проходящая `catalog.validate`."""
    return {
        "catalog": каталог,
        "name": имя,
        "polled_on": "2026-09-01",
        "prices": [],
        "deprecated": False,
        "source_url": "https://openrouter.ai/api/v1/models",
    }


class Проверка(unittest.TestCase):
    def _положить(self, сводка, записи) -> tuple[Path, Path]:
        каталог = Path(self.enterContext(tempfile.TemporaryDirectory()))
        опрос = каталог / "catalog_poll.json"
        индекс = каталог / "catalog.jsonl"
        if сводка is not None:
            опрос.write_text(json.dumps(сводка, ensure_ascii=False), encoding="utf-8")
        if записи is not None:
            индекс.write_text(
                "\n".join(json.dumps(з, ensure_ascii=False) for з in записи) + "\n",
                encoding="utf-8",
            )
        return опрос, индекс

    def test_нет_опроса_это_не_смогли_а_не_годно(self):
        """Ноль проверок при нуле нарушений успехом не считается (Р2)."""
        опрос, индекс = self._положить(None, None)
        итог = pc.проверить_собранное(опрос, индекс)
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["checked"], 0)
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 1)

    def test_здоровая_пара_молчит(self):
        """Другая половина негативного контроля: прибор, отвечающий «нет» на
        всё, ничего не измеряет."""
        опрос, индекс = self._положить(
            _сводка(),
            [_строка("openrouter", "a"), _строка("openrouter", "b"), _строка("deepinfra", "c")],
        )
        итог = pc.проверить_собранное(опрос, индекс)
        self.assertEqual(итог["outcome"], "pass")
        self.assertEqual(итог["violations"], 0)
        # 3 записи + 2 канала. ЧЕТЫРЕ КАТАЛОГА БЕЗ КЛЮЧА СЮДА НЕ ИДУТ: они
        # объявлены НЕИЗМЕРИМЫМИ и стоят в `unmeasured`. До 2026-09-07 здесь
        # стояло 9 — те же четыре считались дважды, и число «проверено»
        # рассказывало, что прибор измерил то, чего измерить нельзя (Р2).
        self.assertEqual(итог["checked"], 5)
        self.assertEqual(итог["unmeasured"], 4)

    def test_проверено_не_включает_неизмеримое(self):
        """Одно и то же число не стоит в N и в K одновременно.

        Негативный контроль к предыдущему: не «checked == 5» на память, а
        «checked + KEYED == 9», то есть ровно те четыре, что уехали в K.
        """
        опрос, индекс = self._положить(
            _сводка(),
            [_строка("openrouter", "a"), _строка("openrouter", "b"), _строка("deepinfra", "c")],
        )
        итог = pc.проверить_собранное(опрос, индекс)
        self.assertEqual(итог["checked"] + len(БЕЗ_КЛЮЧА), 9)
        self.assertEqual(итог["unmeasured"], len(БЕЗ_КЛЮЧА))

    def test_пустой_каталог_и_пустая_сводка_это_не_годно(self):
        """Р2: сверять нечего — значит не «годно», а «не смогли»."""
        опрос, индекс = self._положить(
            _сводка(channels=[], channels_asked=0, channels_answered=0), []
        )
        итог = pc.проверить_собранное(опрос, индекс)
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["checked"], 0)
        self.assertEqual(итог["violations"], 0)

    def test_сводка_обещает_больше_чем_лежит_в_каталоге(self):
        """Тот самый флаг против свидетельства: 2 объявленных, 1 записанная."""
        опрос, индекс = self._положить(
            _сводка(), [_строка("openrouter", "a"), _строка("deepinfra", "c")]
        )
        итог = pc.проверить_собранное(опрос, индекс)
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)
        self.assertIn("openrouter", итог["note"])

    def test_каталог_без_ключа_исчез_из_незакрытых(self):
        """Молчаливый пропуск — сворачивание третьего исхода во второй."""
        опрос, индекс = self._положить(
            _сводка(keyed_out=[{"catalog": "replicate", "state": "could not measure"}]),
            [_строка("openrouter", "a"), _строка("openrouter", "b"), _строка("deepinfra", "c")],
        )
        итог = pc.проверить_собранное(опрос, индекс)
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 3)

    def test_неполный_опрос_это_третий_исход(self):
        опрос, индекс = self._положить(
            _сводка(channels_answered=1),
            [_строка("openrouter", "a"), _строка("openrouter", "b"), _строка("deepinfra", "c")],
        )
        итог = pc.проверить_собранное(опрос, индекс)
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 5)

    def test_сводка_без_обязательного_поля(self):
        сводка = _сводка()
        сводка.pop("channels_asked")
        опрос, индекс = self._положить(сводка, [_строка("openrouter", "a")])
        итог = pc.проверить_собранное(опрос, индекс)
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_битый_json_сводки_это_не_годно(self):
        каталог = Path(self.enterContext(tempfile.TemporaryDirectory()))
        опрос = каталог / "catalog_poll.json"
        опрос.write_text("{не json", encoding="utf-8")
        итог = pc.проверить_собранное(опрос, каталог / "catalog.jsonl")
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)


if __name__ == "__main__":
    unittest.main()
