"""Мониторинг вендорских страниц: что считается изменением, а что — вёрсткой.

Сети нет (Т4), ожидаемое — литералы (Т2). Половина этих тестов — негативный
контроль (И5): канал, который сообщает об изменении на каждом прогоне, учит
себя не читать, и это ровно так же плохо, как канал, который молчит.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "recheck_vendor", Path(__file__).resolve().parents[3] / "scripts" / "recheck_vendor.py"
)
assert SPEC and SPEC.loader
rv = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(rv)


class ЧтоСчитаетсяИзменением(unittest.TestCase):
    def test_текст_поменялся_отпечаток_поменялся(self):
        self.assertNotEqual(
            rv.отпечаток("Veo 3.1 costs $0.40 per second"),
            rv.отпечаток("Veo 3.1 costs $0.50 per second"),
        )

    def test_вёрстка_поменялась_отпечаток_прежний(self):
        """Иначе канал сообщал бы об изменении там, где вендор не поменял ни
        слова — а перевёрстка случается чаще, чем смена цены."""
        self.assertEqual(
            rv.отпечаток("<p>Veo costs <b>$0.40</b> per second</p>"),
            rv.отпечаток("<div><span>Veo costs $0.40   per second</span></div>"),
        )

    def test_регистр_и_пробелы_это_оформление(self):
        self.assertEqual(rv.отпечаток("COSTS  $0.40"), rv.отпечаток("costs $0.40"))

    def test_метка_времени_страницы_не_изменение(self):
        """Страницы печатают время ответа сами. Не вычистив его, канал сообщал
        бы об изменении на КАЖДОМ прогоне, то есть не сообщал бы ни о чём."""
        self.assertEqual(
            rv.отпечаток("costs $0.40 generated 2026-09-02T10:00:00Z"),
            rv.отпечаток("costs $0.40 generated 2026-09-02T18:44:11Z"),
        )

    def test_идентификатор_сессии_не_изменение(self):
        self.assertEqual(
            rv.отпечаток("costs $0.40 nonce='a1b2c3d4'"),
            rv.отпечаток("costs $0.40 nonce='z9y8x7w6'"),
        )

    def test_длинный_шестнадцатеричный_ключ_не_изменение(self):
        self.assertEqual(
            rv.отпечаток("costs $0.40 " + "a" * 40), rv.отпечаток("costs $0.40 " + "b" * 40)
        )


class ТриИсхода(unittest.TestCase):
    def _обойти(self, страница: str, было: dict) -> dict:
        with mock.patch.object(
            rv.fetch, "fetch", lambda url: {"outcome": "pass", "text": страница}
        ):
            return rv.обойти({"https://vendor.test/pricing": 3}, было)

    def test_первый_прогон_не_измеряет_изменение(self):
        """Отпечатков со времени записи фактов никто не снимал, поэтому вопрос
        «изменилось ли» на первом прогоне честного ответа не имеет."""
        итог = self._обойти("цена $0.40", {})
        вердикт = rv.свести(итог, 1)
        self.assertEqual(вердикт["outcome"], "could not measure")
        self.assertIn("первом прогоне", вердикт["note"])

    def test_страница_прежняя_это_успех(self):
        было = {
            "https://vendor.test/pricing": {
                "fingerprint": rv.отпечаток("цена $0.40"),
                # Способ обязателен: отпечаток без него — из прошлого правила,
                # и сравнивать его не с чем (см. `ОтпечатокЧужогоСпособа...`).
                "method": rv.СПОСОБ,
                "seen_on": "2026-09-01",
            }
        }
        вердикт = rv.свести(self._обойти("цена $0.40", было), 1)
        self.assertEqual(вердикт["outcome"], "pass")
        self.assertEqual(вердикт["violations"], 0)

    def test_страница_изменилась_это_работа(self):
        """Вторая половина негативного контроля: прибор обязан не только
        молчать на вёрстке, но и срабатывать на смене цены."""
        было = {
            "https://vendor.test/pricing": {
                "fingerprint": rv.отпечаток("цена $0.40"),
                # Способ обязателен: отпечаток без него — из прошлого правила,
                # и сравнивать его не с чем (см. `ОтпечатокЧужогоСпособа...`).
                "method": rv.СПОСОБ,
                "seen_on": "2026-09-01",
            }
        }
        итог = self._обойти("цена $0.50", было)
        вердикт = rv.свести(итог, 1)
        self.assertEqual(вердикт["outcome"], "fail")
        self.assertEqual(вердикт["violations"], 1)
        self.assertIn("3 утверждений", вердикт["note"], "число утверждений за страницей — в ноте")

    def test_страница_не_ответила_это_не_изменение(self):
        with mock.patch.object(
            rv.fetch, "fetch", lambda url: {"outcome": "could not measure", "text": ""}
        ):
            итог = rv.обойти({"https://vendor.test/pricing": 3}, {})
        вердикт = rv.свести(итог, 1)
        self.assertEqual(вердикт["outcome"], "could not measure")
        self.assertEqual(вердикт["violations"], 0, "молчание хоста — не смена цены")


class ЧтоБерётсяВОбход(unittest.TestCase):
    def _карта(self, строки: list[dict]) -> Path:
        путь = Path(tempfile.mkdtemp()) / "denied_hosts.jsonl"
        путь.write_text(
            "\n".join(json.dumps(с, ensure_ascii=False) for с in строки) + "\n", encoding="utf-8"
        )
        return путь

    def test_последняя_строка_журнала_побеждает(self):
        """Карта хостов — журнал: хост, который открылся, был раньше закрыт, и
        читать его первую строку значит считать закрытым навсегда."""
        путь = self._карта(
            [
                {"host": "vendor.test", "state": "refused"},
                {"host": "vendor.test", "state": "open"},
            ]
        )
        self.assertEqual(rv.открытые_хосты(путь), {"vendor.test"})

    def test_закрытый_хост_в_обход_не_идёт(self):
        """Ц3: закрытое политикой не обходится ни запросом, ни зеркалом."""
        путь = self._карта([{"host": "vendor.test", "state": "refused"}])
        self.assertEqual(rv.открытые_хосты(путь), set())

    def test_битая_строка_карты_не_роняет_чтение(self):
        путь = Path(tempfile.mkdtemp()) / "denied_hosts.jsonl"
        путь.write_text('не json\n{"host": "vendor.test", "state": "open"}\n', encoding="utf-8")
        self.assertEqual(rv.открытые_хосты(путь), {"vendor.test"})


if __name__ == "__main__":
    unittest.main()


class ТелоСкриптаНеТекстСтраницы(unittest.TestCase):
    """ИЗМЕРЕНО на живом втором прогоне: канал объявил изменившимися 12 страниц
    из 68 за десять минут — заведомо ложно. Диагноз снят сравнением страницы с
    самой собой: CDN тасует список флагов эксперимента внутри `<script>` на
    каждый запрос, текст при этом не меняется ни на слово.
    """

    def test_флаги_эксперимента_в_скрипте_не_изменение(self):
        шаблон = 'Veo costs $0.40<script>window.flags=["{}"]</script>'
        self.assertEqual(
            rv.отпечаток(шаблон.format("enable_profile_collections")),
            rv.отпечаток(шаблон.format("enable_completequiz_endpoint")),
        )

    def test_стиль_тоже_не_текст(self):
        self.assertEqual(
            rv.отпечаток("цена<style>.a{color:red}</style>"),
            rv.отпечаток("цена<style>.b{color:blue}</style>"),
        )

    def test_текст_рядом_со_скриптом_остаётся_значимым(self):
        """Вторая половина (И5): вычистив скрипт, нельзя вычистить страницу.
        Иначе канал молчал бы обо всём."""
        self.assertNotEqual(
            rv.отпечаток("цена $0.40<script>x=1</script>"),
            rv.отпечаток("цена $0.50<script>x=1</script>"),
        )


class ОтпечатокЧужогоСпособаЭтоНеИзменение(unittest.TestCase):
    """Правило нормализации уже менялось один раз. Отпечатки, снятые разными
    правилами, сравнивать нельзя: смена правила прочиталась бы как смена ВСЕХ
    страниц разом — двенадцать ложных тревог превратились бы в семьдесят.
    """

    def _обойти(self, было: dict) -> dict:
        with mock.patch.object(
            rv.fetch, "fetch", lambda url: {"outcome": "pass", "text": "цена $0.40"}
        ):
            return rv.обойти({"https://vendor.test/pricing": 3}, было)

    def test_прежний_способ_не_сравнивается(self):
        итог = self._обойти(
            {
                "https://vendor.test/pricing": {
                    "fingerprint": "чтотоиз прошлого",
                    "method": "старое-правило",
                    "seen_on": "2026-09-01",
                }
            }
        )
        self.assertEqual(итог["изменились"], [], "чужой способ — не изменение")
        self.assertEqual(итог["заведено"], 1, "основание заводится заново")

    def test_свой_способ_сравнивается(self):
        итог = self._обойти(
            {
                "https://vendor.test/pricing": {
                    "fingerprint": rv.отпечаток("цена $0.40"),
                    "method": rv.СПОСОБ,
                    "seen_on": "2026-09-01",
                }
            }
        )
        self.assertEqual(итог["как прежде"], 1)

    def test_способ_едет_в_журнал(self):
        строка = self._обойти({})["строки"][0]
        self.assertEqual(строка["method"], rv.СПОСОБ)
