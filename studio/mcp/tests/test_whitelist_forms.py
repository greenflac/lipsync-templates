"""Заявка на whitelist: обе формы домена, а не одна.

Одной строки `*.domain` не хватило вживую: владелец внёс сгенерированный
список, и 22 из 28 хостов продолжили отдавать 403 — потому что `*.example.com`
матчит поддомен и НЕ матчит сам домен. Выглядело как «правка не применилась»,
хотя применилась. Проверено замером: `x.ai` 403 при `docs.x.ai` 200.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location(
    "whitelist_request",
    Path(__file__).resolve().parents[3] / "scripts" / "whitelist_request.py",
)
assert SPEC and SPEC.loader
wl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(wl)


class Forms(unittest.TestCase):
    def test_both_the_wildcard_and_the_bare_domain_are_asked_for(self):
        self.assertEqual(wl.wildcard_forms("x.ai"), ("*.x.ai", "x.ai"))

    def test_the_bare_domain_is_never_dropped(self):
        """Именно эта строка и пропала, и стоила круга с владельцем."""
        for domain in ("minimax.io", "bytedance.com", "voyageai.com"):
            self.assertIn(domain, wl.wildcard_forms(domain))

    def test_the_wildcard_is_never_dropped_either(self):
        for domain in ("minimax.io", "bytedance.com"):
            self.assertIn(f"*.{domain}", wl.wildcard_forms(domain))

    def test_the_printed_request_carries_both_forms_for_every_vendor(self):
        """Проверяется НАПЕЧАТАННОЕ, а не функция: заявку читают глазами."""
        import contextlib
        import io

        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            wl.main(["--tier", "1"])
        printed = out.getvalue()
        asked = {line.strip() for line in printed.splitlines() if line.startswith("  ")}
        vendors = [d for d in wl.VENDOR if f"  *.{d}" in printed]
        self.assertGreater(len(vendors), 0, "тир 1 пуст — проверять нечего")
        missing = [d for d in vendors if d not in asked]
        self.assertEqual(missing, [])


class ЧтоСчитаетсяОтказомВЗаявке(unittest.TestCase):
    """Журнал читается по своей конвенции, а не по одному её половинчатому виду.

    Обе находки ИЗМЕРЕНЫ 2026-09-02 на живом журнале, обе — про хосты, которые
    не попадали в заявку ВООБЩЕ, а не попадали не в тот тир.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.log = Path(self._dir.name) / "denied.jsonl"

    def _журнал(self, rows: list[dict]) -> None:
        self.log.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
        )

    def test_строка_без_state_это_отказ(self) -> None:
        """Все строки до 2026-08-27 писались без поля `state`, потому что
        других состояний не было. Читать их как «не отказ» — значит терять из
        заявки самые старые, то есть самые долго нужные хосты."""
        self._журнал([{"host": "old.test", "url": "https://old.test/"}])
        self.assertEqual(wl.refused_hosts(self.log), {"old.test": ["old.test"]})

    def test_открытый_хост_в_заявку_не_идёт(self) -> None:
        """Вторая половина: заявка, просящая доступ, который уже дали, — это
        причина, по которой следующую не читают."""
        self._журнал([{"host": "ok.test", "state": "open"}])
        self.assertEqual(wl.refused_hosts(self.log), {})

    def test_мазок_узнаётся_по_флагу_а_не_по_формулировке(self) -> None:
        """Причину пишут разные места разными словами. Обновление карты
        достижимости говорит «refreshing the reachability map», и по подстроке
        «search hit is readable» такой хост не узнавался ни как нужный, ни как
        случайный — он выпадал в «не разобрано»."""
        self._журнал(
            [
                {
                    "host": "swept.test",
                    "state": "refused",
                    "incidental": True,
                    "why_wanted": "refreshing the reachability map; nobody asked for this host",
                }
            ]
        )
        self.assertEqual(wl.incidental_domains(self.log), {"swept.test"})

    def test_настоящий_вопрос_перебивает_мазок(self) -> None:
        """Хост, за которым стоит вопрос, обязан остаться в заявке, в каком бы
        порядке строки ни легли."""
        self._журнал(
            [
                {"host": "real.test", "state": "refused", "incidental": True, "why_wanted": "x"},
                {
                    "host": "real.test",
                    "state": "refused",
                    "incidental": False,
                    "why_wanted": "the base cites this page",
                },
            ]
        )
        self.assertEqual(wl.incidental_domains(self.log), set())


if __name__ == "__main__":
    unittest.main()
