"""Скорер замороженного набора: правило счёта исполняется, а не выбирается.

ЗАЧЕМ. Первая редакция набора правила счёта не имела, и независимая приёмка
показала на ней 4 из 16 против 6 из 16 по двум одинаково защитимым правилам.
Разброс в 50% создавала формулировка, которую выбирает тот, кто отчитывается,
уже увидев результат. Скорер исполняет `scored`, записанное У ВОПРОСА, —
значит сам скорер обязан быть под охраной, иначе правило снова выбирает он.

ИЗМЕРЕНО 2026-09-06: у скорера не было НИ ОДНОГО теста. Подменой проверено,
что это значило: `FLOOR_TIER = "vendor"` (одиннадцать блоговых записей начинают
закрывать вопросы) держал набор зелёным.

Ожидаемое — литералы (Т2), сети и диска нет (Т4, Т5).
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(КОРЕНЬ))

_SPEC = importlib.util.spec_from_file_location(
    "score_frozen", КОРЕНЬ / "scripts" / "score_frozen.py"
)
assert _SPEC and _SPEC.loader
скорер = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(скорер)


class НижняяСтупеньИсточника(unittest.TestCase):
    """Блог вопроса не закрывает. Иначе балл вырастет вчетверо без знания."""

    def test_блоговый_источник_вопроса_не_закрывает(self):
        self.assertFalse(скорер._above_floor({"claims": [{"best_tier": "blog"}]}))

    def test_вендорский_закрывает(self):
        """Негативный контроль (И5): пол, отвергающий всё, — это не пол."""
        self.assertTrue(скорер._above_floor({"claims": [{"best_tier": "vendor"}]}))

    def test_пол_названо_литералом(self):
        self.assertEqual("blog", скорер.FLOOR_TIER)

    def test_один_источник_выше_пола_достаточно(self):
        когти = {"claims": [{"best_tier": "blog"}, {"best_tier": "probe"}]}
        self.assertTrue(скорер._above_floor(когти))


class ПравилоЧитаетсяИзВопроса(unittest.TestCase):
    def test_по_умолчанию_ответом_считается_только_pass(self):
        self.assertEqual(("pass",), скорер.разрешённые_исходы("outcome == pass"))

    def test_спорный_атрибут_разрешает_и_fail(self):
        """q03 говорит «outcome in (pass, fail)» нарочно: у kling-3.0.max_seconds
        источники спорят, и честное `fail` с обеими сторонами — это ОТВЕТ."""
        self.assertEqual(("pass", "fail"), скорер.разрешённые_исходы("outcome in (pass, fail)"))
        self.assertEqual(("pass", "fail"), скорер.разрешённые_исходы("outcome in (pass,fail)"))

    def test_незнакомая_запись_разбирается_СТРОГО(self):
        """Скорер, трактующий неизвестную запись широко, ослабляет набор молча."""
        self.assertEqual(("pass",), скорер.разрешённые_исходы("как-нибудь по-своему"))
        self.assertEqual(("pass",), скорер.разрешённые_исходы(""))

    def test_требуемое_имя_читается(self):
        self.assertEqual(
            "wan-animate-replace", скорер.требуемое_имя("в выдаче есть wan-animate-replace")
        )

    def test_слово_без_дефиса_именем_модели_не_считается(self):
        """Иначе «в выдаче есть что-нибудь» стало бы требованием имени."""
        self.assertEqual("", скорер.требуемое_имя("в выдаче есть модель"))
        self.assertEqual("", скорер.требуемое_имя("непустая выдача"))


class ТриИсходаУКаждогоВопроса(unittest.TestCase):
    def test_неотработавший_канал_это_не_смогли(self):
        """Вопрос, чей канал не отработал, обязан отличаться от вопроса, на
        который база честно не ответила (Р1)."""
        self.assertEqual("не смогли", скорер.score({"kind": "model"}, {"outcome": None}))

    def test_брифу_нужно_именно_то_имя_что_записано(self):
        вопрос = {"kind": "brief", "scored": "в выдаче есть wan-animate-replace"}
        нашлось = {"outcome": "pass", "models": ["Wan-Animate-Replace", "kling-3.0"]}
        мимо = {"outcome": "pass", "models": ["kling-3.0"]}
        self.assertEqual("годно", скорер.score(вопрос, нашлось))
        self.assertEqual("не годно", скорер.score(вопрос, мимо))

    def test_непустая_выдача_без_требования_имени_годна(self):
        вопрос = {"kind": "brief", "scored": "непустая выдача"}
        self.assertEqual("годно", скорер.score(вопрос, {"outcome": "pass", "models": ["любая"]}))
        self.assertEqual("не годно", скорер.score(вопрос, {"outcome": "pass", "models": []}))

    def test_контроль_на_знакомой_модели_может_быть_непустым(self):
        """q22 спрашивает несуществующий атрибут у известной модели: верный
        ответ — «об этом атрибуте не записано ничего», а не «модели нет»."""
        вопрос = {"kind": "control", "attribute": "не_бывает_такого"}
        got = {"outcome": "pass", "models": ["kling-3.0"], "claim": {"checked": 0}, "note": ""}
        self.assertEqual("годно", скорер.score(вопрос, got))

    def test_контроль_с_соседями_в_ноте_не_годен(self):
        вопрос = {"kind": "control"}
        got = {"outcome": "pass", "models": [], "claims": [], "note": "The base does hold ..."}
        self.assertEqual("не годно", скорер.score(вопрос, got))

    def test_атрибут_со_спорным_исходом_читает_своё_правило(self):
        вопрос = {"kind": "model", "attribute": "max_seconds", "scored": "outcome in (pass, fail)"}
        спор = {
            "outcome": "pass",
            "claim": {"outcome": "fail", "claims": [{"best_tier": "vendor"}]},
        }
        self.assertEqual("годно", скорер.score(вопрос, спор))

    def test_тот_же_ответ_под_строгим_правилом_не_годен(self):
        """Та же выдача, другое правило у вопроса — другой вердикт. Это и
        значит «правило исполняется, а не выбирается»."""
        вопрос = {"kind": "model", "attribute": "max_seconds", "scored": "outcome == pass"}
        спор = {
            "outcome": "pass",
            "claim": {"outcome": "fail", "claims": [{"best_tier": "vendor"}]},
        }
        self.assertEqual("не годно", скорер.score(вопрос, спор))


if __name__ == "__main__":
    unittest.main()
