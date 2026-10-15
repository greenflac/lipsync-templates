"""Смежный атрибут — не ответ: свойство по ВСЕМ парам тематических семей.

НАЙДЕНО валидатором 5-го круга (2026-10-15): `model_advice("kling-3.0",
"negative_prompt")` отвечал `pass` строкой `prompt_skeleton` — семья
«как писать промт» сводила разные вопросы в один, — а у пяти вариантов Kling
и восьми Veo в базе лежало «accepted» о самом `negative_prompt`.

СВОЙСТВО. Для каждой тематической семьи (`attrfamily.СЕМЬИ` минус
`ОДНА_ВЕЛИЧИНА`) и каждой упорядоченной пары её поимённых членов (a, b), не
равнозначных друг другу: спросили `a`, у модели записан только `b` ->
  * `expand` не возвращает `b` (не ответ);
  * `substitutes` возвращает `b` (смежное названо);
  * `advise` не отвечает `pass`, `b` нет в `claims`, `b` есть в `substitutes`
    с `counts_as_answer: false` и `substitute_for: a`.
"""

from __future__ import annotations

import itertools
import json
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest import mock

from studio.mcp import advice
from studio.selfrag import attrfamily, source_hosts

_VENDOR = {"subst-model": ("vendor.test",), "subst-fam": ("vendor.test",)}


def _пары() -> list[tuple[str, str, str]]:
    пары = []
    for имя_семьи, правило in attrfamily.СЕМЬИ.items():
        if имя_семьи in attrfamily.ОДНА_ВЕЛИЧИНА:
            continue
        члены = [
            ч
            for ч in правило.get("exact", ())
            # Слово самой семьи (`editing`) — вопрос о ТЕМЕ: отвечают все.
            if not attrfamily.семья(ч) and attrfamily.семья_имени(ч) == имя_семьи
        ]
        for а, б in itertools.permutations(члены, 2):
            if not attrfamily.равнозначны(а, б):
                пары.append((имя_семьи, а, б))
    return пары


def _строка(модель: str, атрибут: str, значение: str = "accepted") -> dict:
    return {
        "model": модель,
        "attribute": атрибут,
        "value": значение,
        "source_url": "https://vendor.test/spec",
        "tier": "vendor",
        "stated_on": date.today().isoformat(),
        "note": "",
        "fix": "",
    }


class Свойство(unittest.TestCase):
    def test_пар_достаточно(self) -> None:
        """Р1: пустой перебор прошёл бы, ничего не проверив."""
        self.assertGreater(len(_пары()), 200)
        self.assertIn(("prompt_rule", "negative_prompt", "prompt_skeleton"), _пары())

    def test_смежное_не_разворачивается_и_названо(self) -> None:
        for семья, а, б in _пары():
            with self.subTest(семья=семья, спрошено=а, записано=б):
                self.assertEqual([], attrfamily.expand(а, [б]))
                self.assertEqual([б], attrfamily.substitutes(а, [б]))

    def test_справка_помечает_заменитель(self) -> None:
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(source_hosts.VENDOR_SOURCES, _VENDOR, clear=False),
        ):
            путь = Path(tmp) / "facts.jsonl"
            for семья, а, б in _пары():
                путь.write_text(json.dumps(_строка("subst-model", б)) + "\n", encoding="utf-8")
                ответ = advice.advise("subst-model", а, path=путь)
                with self.subTest(семья=семья, спрошено=а, записано=б):
                    self.assertNotEqual("pass", ответ["outcome"])
                    self.assertNotIn(б, ответ["claims"])
                    self.assertEqual(False, ответ["substitutes"][б]["counts_as_answer"])
                    self.assertEqual(а, ответ["substitutes"][б]["substitute_for"])
                    self.assertIn("RELATED, NOT AN ANSWER", ответ["note"])


class Смежные(unittest.TestCase):
    """Семьи одной величины со смежным членом: тема та же, вопрос другой."""

    def test_смежный_не_отвечает_ни_слову_семьи_ни_члену(self) -> None:
        self.assertTrue(attrfamily.СМЕЖНЫЕ)
        for семья, смежные in attrfamily.СМЕЖНЫЕ.items():
            for смежный in смежные:
                with self.subTest(семья=семья, смежный=смежный):
                    self.assertEqual(семья, attrfamily.семья_имени(смежный))
                    self.assertEqual([], attrfamily.expand(семья, [смежный]))
                    self.assertEqual([смежный], attrfamily.substitutes(семья, [смежный]))
                    # Спрошенный буквально — отвечает сам за себя.
                    self.assertEqual([смежный], attrfamily.expand(смежный, [смежный]))

    def test_язык_промпта_не_языки_речи(self) -> None:
        записано = ["languages", "prompt_language"]
        self.assertEqual(["languages"], attrfamily.expand("languages", записано))
        self.assertEqual(["prompt_language"], attrfamily.substitutes("languages", записано))


class ТотЖеАтрибутУВарианта(unittest.TestCase):
    """Сначала тот же атрибут у варианта (и назван вариант), смежное — после."""

    def test_kling_негатив_из_варианта_а_не_скелет(self) -> None:
        строки = [
            _строка("subst-fam", "prompt_skeleton", "[subject] [action] [camera]"),
            _строка("subst-fam-pro", "negative_prompt", "accepted — schema has the field"),
        ]
        with (
            tempfile.TemporaryDirectory() as tmp,
            mock.patch.dict(
                source_hosts.VENDOR_SOURCES,
                {**_VENDOR, "subst-fam-pro": ("vendor.test",)},
                clear=False,
            ),
        ):
            путь = Path(tmp) / "facts.jsonl"
            путь.write_text("\n".join(json.dumps(с) for с in строки) + "\n", encoding="utf-8")
            ответ = advice.advise("subst-fam", "negative_prompt", path=путь)
        self.assertEqual("answered_by_family", ответ["reason"])
        self.assertEqual(["negative_prompt@subst-fam-pro"], list(ответ["claims"]))
        self.assertIn("subst-fam-pro", ответ["note"])
        self.assertEqual(["prompt_skeleton"], list(ответ["substitutes"]))
        self.assertEqual(False, ответ["substitutes"]["prompt_skeleton"]["counts_as_answer"])

    def test_слово_семьи_по_прежнему_тема(self) -> None:
        """И5: «промт» спрашивает тему — скелет отвечает, заменителей нет."""
        self.assertEqual(["prompt_skeleton"], attrfamily.expand("промт", ["prompt_skeleton"]))
        self.assertEqual([], attrfamily.substitutes("промт", ["prompt_skeleton"]))

    def test_семья_одной_величины_отвечает_собой(self) -> None:
        """И5: цена в минуту — ответ на вопрос о цене в секунду (единица названа)."""
        self.assertEqual(
            ["price_per_minute"], attrfamily.expand("price_per_second_usd", ["price_per_minute"])
        )
        self.assertEqual([], attrfamily.substitutes("price_per_second_usd", ["price_per_minute"]))

    def test_равнозначные_написания(self) -> None:
        self.assertTrue(attrfamily.равнозначны("negative_prompt", "negative_prompts"))
        self.assertTrue(attrfamily.равнозначны("min_vram_gb", "vram_requirements"))
        self.assertFalse(attrfamily.равнозначны("negative_prompt", "prompt_skeleton"))
        self.assertFalse(attrfamily.равнозначны("max_prompt_length", "keyterms_limit"))


if __name__ == "__main__":
    unittest.main()
