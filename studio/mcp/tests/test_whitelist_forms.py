"""Заявка на whitelist: обе формы домена, а не одна.

Одной строки `*.domain` не хватило вживую: владелец внёс сгенерированный
список, и 22 из 28 хостов продолжили отдавать 403 — потому что `*.example.com`
матчит поддомен и НЕ матчит сам домен. Выглядело как «правка не применилась»,
хотя применилась. Проверено замером: `x.ai` 403 при `docs.x.ai` 200.
"""

from __future__ import annotations

import importlib.util
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


if __name__ == "__main__":
    unittest.main()
