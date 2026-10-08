"""Верхняя строка ответа против его же тела и против базы.

ЗАЧЕМ. За 2026-09-02 в проекте семь раз нашлось одно и то же: ответ ЧЕСТЕН В
ДЕТАЛЯХ и НЕВЕРЕН В ЗАГОЛОВКЕ. Самый дорогой пример:

    model_advice("sync-lipsync-2", "price") -> "nothing is recorded"
    в базе                                  -> price_per_minute = "$3 per minute"

Гейт против этого написан, но обе его константы — слова, которыми ответ
объявляет пустоту, и слова, которыми он называет третий исход, — были достижимы
только через живую базу и живой `advise`. Ни один тест не мог подменить в них
ни слова: ратчет R7 нашёл модуль без единого мутанта 2026-09-06.

Ожидаемое — литералы (Т2), сети нет (Т4), развилка вызывается функцией (Т5).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_headline", Path(__file__).resolve().parents[3] / "scripts" / "check_headline.py"
)
assert _SPEC and _SPEC.loader
гейт = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(гейт)

#: Настоящая ложная выдача 2026-09-02, дословно (И2: вход сохранён).
ПУСТОЙ_ЗАГОЛОВОК = {
    "outcome": "could not measure",
    "checked": 0,
    "violations": 0,
    "unmeasured": 1,
    # НОТА ВЗЯТА С ЖИВОГО ОТВЕТА, А НЕ СОКРАЩЕНА ДО ПЕРВОЙ ФРАЗЫ: настоящий
    # `advise` называет третий исход тут же («could not measure» про ось
    # доступности), и фикстура без этих слов ловила бы ВТОРУЮ беду — «нота
    # молчит о неизмеренном», — то есть мерила бы мою обрезку, а не продукт.
    "note": (
        "nothing is recorded about sync-lipsync-2.price. The model itself IS in the "
        "fact base. Availability is a SEPARATE axis, and it says 'could not measure'"
    ),
    "claims": {},
}


class ЗаголовокСверяетсяСБазой(unittest.TestCase):
    def test_пустой_заголовок_при_непустой_базе_это_беда(self):
        беды = гейт.расхождения("sync-lipsync-2", "price", ПУСТОЙ_ЗАГОЛОВОК, ["price_per_minute"])
        self.assertEqual(len(беды), 1)
        self.assertIn("ничего не записано", беды[0])
        self.assertIn("price_per_minute", беды[0])

    def test_пустой_заголовок_при_пустой_базе_это_правда(self):
        """Негативный контроль (И5): гейт обязан не только ловить, но и
        МОЛЧАТЬ — иначе он краснеет на каждой модели, о которой и правда
        ничего не записано."""
        self.assertEqual([], гейт.расхождения("модель", "price", ПУСТОЙ_ЗАГОЛОВОК, ["max_seconds"]))

    def test_русские_слова_пустоты_тоже_ловятся(self):
        ответ = {
            **ПУСТОЙ_ЗАГОЛОВОК,
            "note": "про эту модель ничего не записано; доступность — не смогли",
        }
        self.assertEqual(1, len(гейт.расхождения("м", "price", ответ, ["price_per_second"])))

    def test_годно_при_нуле_проверенных_это_беда(self):
        """Р2: ноль проверенных рядом с «годно» — не успех, а ничего не
        измеренное."""
        ответ = {
            "outcome": "pass",
            "checked": 0,
            "violations": 0,
            "unmeasured": 0,
            "note": "",
            "claims": {"price": {"values": ["$3"]}},
        }
        беды = гейт.расхождения("м", "price", ответ, ["price_per_minute"])
        self.assertTrue(any("checked=0" in б for б in беды), беды)

    def test_годно_без_единого_значения_это_беда(self):
        ответ = {
            "outcome": "pass",
            "checked": 1,
            "violations": 0,
            "unmeasured": 0,
            "note": "",
            "claims": {"price": {"values": []}},
        }
        беды = гейт.расхождения("м", "price", ответ, ["price_per_minute"])
        self.assertTrue(any("без единого значения" in б for б in беды), беды)

    def test_годно_при_нарушениях_это_беда(self):
        ответ = {
            "outcome": "pass",
            "checked": 1,
            "violations": 1,
            "unmeasured": 0,
            "note": "",
            "claims": {"price": {"values": ["$3"]}},
        }
        беды = гейт.расхождения("м", "price", ответ, ["price_per_minute"])
        self.assertTrue(any("violations>0" in б for б in беды), беды)

    def test_неизмеренное_обязано_быть_названо_в_ноте(self):
        молчит = {
            "outcome": "could not measure",
            "checked": 1,
            "violations": 0,
            "unmeasured": 1,
            "note": "всё хорошо",
            "claims": {},
        }
        беды = гейт.расхождения("м", "price", молчит, [])
        self.assertTrue(any("нота об этом молчит" in б for б in беды), беды)

    def test_названный_третий_исход_беды_не_даёт(self):
        """Второй негативный контроль: слова третьего исхода обязаны
        засчитываться, иначе гейт краснеет на честном ответе."""
        for слово in ("could not measure", "не смогли", "weakly", "gap", "unknown", "не измер"):
            честный = {
                "outcome": "could not measure",
                "checked": 1,
                "violations": 0,
                "unmeasured": 1,
                "note": f"ответ: {слово}",
                "claims": {},
            }
            self.assertEqual([], гейт.расхождения("м", "price", честный, []), слово)


if __name__ == "__main__":
    unittest.main()
