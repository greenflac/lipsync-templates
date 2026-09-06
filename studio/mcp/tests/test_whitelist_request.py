"""Из чего собирается заявка на открытие хостов.

ЗАЧЕМ. Заявка — единственный способ попросить доступ, не обходя политику
(правило Ц3: закрытый хост не обходится ни зеркалом, ни прокси). Её сила в
двух вещах: доменом просят ровно то, что нужно, и просят за НАЗВАННЫЙ повод.

ИЗМЕРЕНО и записано в самом модуле: 44 из 48 доменов, которые не удалось
разобрать руками, оказались тронутыми ОДИН раз — «проверяли, читается ли
найденная ссылка». Просить их — ослаблять заявку; просить страницу, которую
база ЦИТИРУЕТ и никто не смог открыть, — самая сильная её строка.

Три константы-решения модуля стояли без охраны: поймано ратчетом R7 2026-09-06.
Ожидаемое — литералы (Т2), сети нет (Т4), диска не нужно (Т5).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "whitelist_request",
    Path(__file__).resolve().parents[3] / "scripts" / "whitelist_request.py",
)
assert _SPEC and _SPEC.loader
заявка = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(заявка)


class ДоменДляЗвёздочкиБерётсяПоСуффиксу(unittest.TestCase):
    def test_обычный_домен_второго_уровня(self):
        self.assertEqual(
            "kling.ai", заявка.registrable("api.klingai.test".replace("klingai.test", "kling.ai"))
        )
        self.assertEqual("fal.ai", заявка.registrable("queue.fal.ai"))
        self.assertEqual("fal.ai", заявка.registrable("fal.ai"))

    def test_составной_суффикс_берёт_три_части(self):
        """`example.co.uk` — регистрируемый домен; попросить `co.uk` значило бы
        попросить весь британский коммерческий сегмент, и такую заявку
        владельцу нельзя показывать."""
        self.assertEqual("example.co.uk", заявка.registrable("docs.example.co.uk"))
        self.assertEqual("bar.com.cn", заявка.registrable("a.b.bar.com.cn"))
        self.assertEqual("x.co.jp", заявка.registrable("www.x.co.jp"))
        self.assertEqual("y.com.au", заявка.registrable("api.y.com.au"))

    def test_неизвестный_составной_суффикс_режется_как_обычный(self):
        """Негативный контроль (И5) к списку: он КОРОТКИЙ и честно неполный,
        и на неизвестном суффиксе поведение обязано быть предсказуемым, а не
        случайным. Держит его `--check`, падающий на неразобранном."""
        self.assertEqual("co.nz", заявка.registrable("docs.example.co.nz"))

    def test_голое_имя_остаётся_собой(self):
        self.assertEqual("localhost", заявка.registrable("localhost"))
        self.assertEqual("", заявка.registrable(""))

    def test_список_суффиксов_ровно_четыре(self):
        """Литерал (Т2): список видённых в этом журнале, а не полный PSL.
        Дописать в него значит расширить то, о чём просят, — это решение."""
        self.assertEqual({"co.uk", "com.cn", "co.jp", "com.au"}, set(заявка.MULTI_PART_SUFFIXES))


class ОбеФормыЗаписиОбязательны(unittest.TestCase):
    def test_и_звёздочка_и_голый_домен(self):
        """От этого зависит, доедет ли заявка до РАБОТАЮЩЕГО доступа: одной
        формы уже однажды не хватило."""
        self.assertEqual(("*.fal.ai", "fal.ai"), заявка.wildcard_forms("fal.ai"))


class ПоводНазываетсяСловамиЖурнала(unittest.TestCase):
    def test_слова_повода_это_литералы_журнала(self):
        """`cites` и «проверяли, читается ли ссылка» — не наши формулировки, а
        куски того, что записал канал. Разъехавшись с журналом, они молча
        перестанут различать сильную строку заявки и слабую."""
        self.assertEqual("cites", заявка.WANT_CITED)
        self.assertEqual("search hit is readable", заявка.WANT_INCIDENTAL)

    def test_живой_журнал_всё_ещё_несёт_эти_слова(self):
        """Негативный контроль (И5) к предыдущему: литерал, разошедшийся с
        живым журналом, — это тест, который сторожит собственную копию."""
        путь = Path(__file__).resolve().parents[2] / "knowledge" / "denied_hosts.jsonl"
        текст = путь.read_text(encoding="utf-8")
        self.assertIn(заявка.WANT_CITED, текст)
        self.assertIn(заявка.WANT_INCIDENTAL, текст)


if __name__ == "__main__":
    unittest.main()
