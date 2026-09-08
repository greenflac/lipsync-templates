"""Мониторинг вендорских страниц: что считается изменением, а что — вёрсткой.

Сети нет (Т4), ожидаемое — литералы (Т2). Половина этих тестов — негативный
контроль (И5): канал, который сообщает об изменении на каждом прогоне, учит
себя не читать, и это ровно так же плохо, как канал, который молчит.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
from types import SimpleNamespace
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


class ТриПоложенияХоста(unittest.TestCase):
    """Р1 на карте достижимости. До 2026-09-03 положений было два: `open` и
    всё остальное. Хост, который ни разу не отказывал, в карту не попадал —
    карта строилась из ОТКАЗОВ, — и канал молча пропускал ровно те хосты, что
    всегда работали: 348 вендорских утверждений из 624, то есть 56%.
    """

    def _карта(self, строки: list[dict]) -> Path:
        путь = Path(tempfile.mkdtemp()) / "denied_hosts.jsonl"
        путь.write_text(
            "\n".join(json.dumps(с, ensure_ascii=False) for с in строки) + "\n",
            encoding="utf-8",
        )
        return путь

    def test_три_положения_различимы(self):
        путь = self._карта(
            [
                {"host": "открытый.test", "state": "open"},
                {"host": "закрытый.test", "state": "refused"},
            ]
        )
        карта = rv.состояние_хостов(путь)
        self.assertEqual(rv.положение("открытый.test", карта), "открыт")
        self.assertEqual(rv.положение("закрытый.test", карта), "закрыт")
        # Хоста нет в карте — это НЕ «закрыт». Ровно на этом слипании канал
        # и не видел huggingface.co.
        self.assertEqual(rv.положение("незнакомый.test", карта), "не записан")

    def test_не_записан_не_равен_закрыт(self):
        """Литералами (Т2): если эти две строки когда-нибудь совпадут,
        различие исчезнет молча."""
        self.assertNotEqual(rv.НЕ_ЗАПИСАН, rv.ЗАКРЫТ)
        self.assertNotEqual(rv.НЕ_ЗАПИСАН, rv.ОТКРЫТ)

    def test_последняя_строка_журнала_по_прежнему_побеждает(self):
        путь = self._карта(
            [{"host": "х.test", "state": "refused"}, {"host": "х.test", "state": "open"}]
        )
        self.assertEqual(rv.положение("х.test", rv.состояние_хостов(путь)), "открыт")


class КудаКаналИдёт(unittest.TestCase):
    """Цели обхода и то, что осталось за бортом, — с числами (Р2)."""

    def _факт(self, url: str, tier: str = "vendor"):
        return SimpleNamespace(tier=tier, source_url=url)

    def test_хост_вне_карты_это_цель_а_не_пропуск(self):
        """ИЗМЕРЕНО 2026-09-03: так канал не видел huggingface.co — 275
        утверждений, больше трети вендорского тира."""
        цели, мимо = rv.адреса(
            факты=[self._факт("https://новый.test/страница")],
            карта={},
        )
        self.assertEqual(цели, {"https://новый.test/страница": 1})
        self.assertEqual(мимо["закрыт"], {})

    def test_закрытый_политикой_хост_в_цели_не_попадает(self):
        """Ц3: закрытое не обходится ни запросом, ни зеркалом — оно
        называется отдельной строкой с числом утверждений за ним."""
        цели, мимо = rv.адреса(
            факты=[self._факт("https://нельзя.test/а"), self._факт("https://нельзя.test/б")],
            карта={"нельзя.test": "закрыт"},
        )
        self.assertEqual(цели, {})
        self.assertEqual(мимо["закрыт"], {"нельзя.test": 2})

    def test_открытый_хост_цель(self):
        цели, _ = rv.адреса(
            факты=[self._факт("https://можно.test/а")],
            карта={"можно.test": "открыт"},
        )
        self.assertEqual(цели, {"https://можно.test/а": 1})

    def test_число_утверждений_едет_вместе_с_адресом(self):
        цели, _ = rv.адреса(
            факты=[self._факт("https://х.test/а"), self._факт("https://х.test/а")],
            карта={},
        )
        self.assertEqual(цели, {"https://х.test/а": 2})

    def test_чужой_тир_не_берётся(self):
        цели, _ = rv.адреса(факты=[self._факт("https://х.test/а", tier="paper")], карта={})
        self.assertEqual(цели, {})


class ОбрезанныйОтветНеСтраница(unittest.TestCase):
    """ИЗМЕРЕНО 2026-09-03 на `kling.ai/quickstart/text-to-video-prompt-guide`:
    ответ 200, ровно 400 000 байт, `truncated: True`, и в них один
    открывающий `<style>` без закрывающего — то есть сплошной CSS. Отпечаток
    такого куска стабилен, и канал говорил бы «страница не менялась» про
    таблицу стилей, пока три утверждения за ней стареют."""

    def test_обрезанный_не_даёт_отпечатка_и_идёт_в_третий_исход(self):
        ответы = {
            "https://целая.test/a": {"outcome": "pass", "text": "<h1>текст</h1>"},
            "https://обрезанная.test/b": {
                "outcome": "pass",
                "truncated": True,
                "text": '<style>@charset "UTF-8";:root{--x:1}',
            },
        }
        прежний = rv.fetch.fetch
        rv.fetch.fetch = lambda url, **kw: ответы[url]
        try:
            итог = rv.обойти({u: 1 for u in ответы}, {})
        finally:
            rv.fetch.fetch = прежний
        self.assertEqual([с["url"] for с in итог["строки"]], ["https://целая.test/a"])
        self.assertEqual(итог["обрезаны"], ["https://обрезанная.test/b"])
        вердикт = rv.свести(итог, 2)
        self.assertEqual(вердикт["unmeasured"], 2, "обрезанная + заведённое основание")

    def test_необрезанный_отпечаток_снимается(self):
        """Негативный контроль (И5): починка не смеет глушить целые страницы."""
        прежний = rv.fetch.fetch
        rv.fetch.fetch = lambda url, **kw: {"outcome": "pass", "text": "<h1>текст</h1>"}
        try:
            итог = rv.обойти({"https://целая.test/a": 1}, {})
        finally:
            rv.fetch.fetch = прежний
        self.assertEqual(len(итог["строки"]), 1)
        self.assertEqual(итог["обрезаны"], [])


class СтраницаСравниваетсяСамаССобой(unittest.TestCase):
    """Список известного шума — это память о хостах, которые уже подводили;
    новый хост приносит свой. ИЗМЕРЕНО 2026-09-03: HuggingFace подставляет своё
    имя класса на каждый запрос (`hf-sanitized-<случайное>`), и канал объявил
    изменившимися 74 страницы из 214 — почти все ложно. Теперь на расхождении
    делается второй запрос: два свежих чтения, разошедшихся между собой, — это
    «нестабильна», а не «вендор что-то поменял»."""

    def _канал(self, ответы: list[dict]):
        очередь = list(ответы)

        def подмена(url, **kw):
            return очередь.pop(0)

        return подмена

    def test_два_чтения_разошлись_это_не_изменение(self):
        прежний = rv.fetch.fetch
        rv.fetch.fetch = self._канал(
            [{"outcome": "pass", "text": "<p>раз</p>"}, {"outcome": "pass", "text": "<p>два</p>"}]
        )
        try:
            итог = rv.обойти(
                {"https://шумит.test/a": 3},
                {
                    "https://шумит.test/a": {
                        "fingerprint": "прежний",
                        "method": rv.СПОСОБ,
                        "seen_on": "2026-09-02",
                    }
                },
            )
        finally:
            rv.fetch.fetch = прежний
        self.assertEqual(итог["изменились"], [])
        self.assertEqual(итог["нестабильны"], ["https://шумит.test/a"])
        self.assertEqual(итог["строки"], [], "отпечаток нестабильной страницы не записывается")

    def test_два_чтения_сошлись_это_изменение(self):
        """Негативный контроль (И5): починка не смеет глушить настоящие
        изменения — иначе канал перестаёт работать целиком."""
        прежний = rv.fetch.fetch
        rv.fetch.fetch = self._канал(
            [
                {"outcome": "pass", "text": "<p>новое</p>"},
                {"outcome": "pass", "text": "<p>новое</p>"},
            ]
        )
        try:
            итог = rv.обойти(
                {"https://менялась.test/a": 3},
                {
                    "https://менялась.test/a": {
                        "fingerprint": "прежний",
                        "method": rv.СПОСОБ,
                        "seen_on": "2026-09-02",
                    }
                },
            )
        finally:
            rv.fetch.fetch = прежний
        self.assertEqual([с["url"] for с in итог["изменились"]], ["https://менялась.test/a"])
        self.assertEqual(итог["нестабильны"], [])

    def test_имя_класса_huggingface_вычищается(self):
        """Дословно с живой страницы `black-forest-labs/FLUX.1-dev`, и форма
        здесь важна: класс приходит НЕ атрибутом тега (тот бы снялся вместе с
        тегом), а внутри экранированного JSON в теле страницы. Первый вариант
        этого теста был написан тегом — и мутация «убрать образец» молчала,
        потому что работу делал очиститель тегов."""
        шаблон = "текст &quot;classnames&quot;:&quot;hf-sanitized hf-sanitized-{}&quot; текст"
        self.assertEqual(
            rv.отпечаток(шаблон.format("1uctzfwuvqirhkdmmcnlx")),
            rv.отпечаток(шаблон.format("l7v71eqxhylxdbqrekv9t")),
        )


class ОбрезанноеПереспрашивается(unittest.TestCase):
    """ИЗМЕРЕНО 2026-09-03 на `kling.ai/quickstart/text-to-video-prompt-guide`:
    при потолке 400 000 приходит ровно потолок и в нём один сплошной CSS — ни
    одного слова гида; при 1 600 000 страница приходит целиком (839 711 байт)
    и все пять слов записанного скелета промпта на месте. Объявлять такую
    страницу непрочитанной значило бы терять её навсегда."""

    def _канал(self, ответы: list[dict]):
        очередь = list(ответы)

        def подмена(url, **kw):
            от = очередь.pop(0)
            от = dict(от)
            от["_потолок"] = kw.get("max_bytes")
            следы.append(от["_потолок"])
            return от

        следы: list = []
        подмена.следы = следы  # type: ignore[attr-defined]
        return подмена

    def test_второй_запрос_с_большим_потолком_спасает_страницу(self):
        канал = self._канал(
            [
                {"outcome": "pass", "truncated": True, "text": "<style>css"},
                {"outcome": "pass", "text": "<h1>тело статьи</h1>"},
            ]
        )
        прежний = rv.fetch.fetch
        rv.fetch.fetch = канал
        try:
            итог = rv.обойти({"https://толстая.test/a": 3}, {})
        finally:
            rv.fetch.fetch = прежний
        self.assertEqual([с["url"] for с in итог["строки"]], ["https://толстая.test/a"])
        self.assertEqual(итог["обрезаны"], [])
        self.assertEqual(итог["добрано"], 1)
        self.assertEqual(канал.следы[1], rv.ПОТОЛОК_ПОВТОРА, "второй запрос — с большим потолком")

    def test_не_влезла_и_во_второй_это_третий_исход(self):
        """Лестница из потолков означала бы, что канал сам решает, сколько
        чужого трафика занять. Переспрос ровно один."""
        канал = self._канал(
            [
                {"outcome": "pass", "truncated": True, "text": "<style>css"},
                {"outcome": "pass", "truncated": True, "text": "<style>css ещё"},
            ]
        )
        прежний = rv.fetch.fetch
        rv.fetch.fetch = канал
        try:
            итог = rv.обойти({"https://огромная.test/a": 3}, {})
        finally:
            rv.fetch.fetch = прежний
        self.assertEqual(итог["обрезаны"], ["https://огромная.test/a"])
        self.assertEqual(итог["строки"], [])
        self.assertEqual(len(канал.следы), 2, "переспрос ровно один, лестницы нет")


if __name__ == "__main__":
    unittest.main()
