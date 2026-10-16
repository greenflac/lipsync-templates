"""Канал `scripts/import_litellm_prices.py`: разбор ключа, имя модели, сводка
условий в одно значение на провайдера, идемпотентная запись, офлайн-проверка.

Сети нет (Т4): таблица — словарь в тесте, запись — во временный файл.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from scripts import import_litellm_prices as L
from studio.selfrag.facts import Fact, load_facts

ТАБЛИЦА = {
    "gemini/veo-3.1-fast-generate-preview": {
        "litellm_provider": "gemini",
        "mode": "video_generation",
        "output_cost_per_second": 0.15,
        "deprecation_date": "2026-11-17",
    },
    "fal_ai/low/1024-x-1024/openai/gpt-image-2": {
        "litellm_provider": "fal_ai",
        "mode": "image_generation",
        "output_cost_per_image": 0.006,
    },
    "fal_ai/high/1024-x-1024/openai/gpt-image-2": {
        "litellm_provider": "fal_ai",
        "mode": "image_generation",
        "output_cost_per_image": 0.211,
    },
    "fal_ai/openai/gpt-image-2": {
        "litellm_provider": "fal_ai",
        "mode": "image_generation",
        "output_cost_per_image": 0.145,
    },
    "gpt-5": {"litellm_provider": "openai", "mode": "chat", "input_cost_per_token": 1e-6},
    "bedrock/some-unrelated-image-model": {
        "litellm_provider": "bedrock",
        "mode": "image_generation",
        "output_cost_per_image": 0.04,
    },
}


def _как_есть(имя: str) -> tuple[str, str]:
    return имя, ""


class Разбор(unittest.TestCase):
    def test_ключ_делится_на_путь_и_условие(self) -> None:
        self.assertEqual(
            L.разобрать_ключ("fal_ai/high/1024-x-1536/openai/gpt-image-2/edit", "fal_ai"),
            ("openai/gpt-image-2/edit", "high 1024x1536"),
        )

    def test_хвост_выпуска_снимается(self) -> None:
        self.assertEqual(L.имя_модели("veo-3.1-fast-generate-preview", "gemini")[0], "veo-3.1-fast")
        self.assertEqual(L.имя_модели("gpt-image-2-2026-04-21", "azure")[0], "gpt-image-2")

    def test_путь_fal_ai_идёт_через_таблицу_портала(self) -> None:
        self.assertEqual(L.имя_модели("openai/gpt-image-2/edit", "fal_ai")[0], "gpt-image-2-edit")


class Сводка(unittest.TestCase):
    def test_одна_находка_на_модель_провайдера_и_единицу(self) -> None:
        находки, счёт = L.находки(ТАБЛИЦА, set(), _как_есть)
        self.assertEqual(счёт["строк_медиа"], 5)
        self.assertEqual(счёт["вне_охвата"], 1)
        по_ключу = {(н.модель, н.атрибут): н.значение for н in находки}
        self.assertEqual(
            по_ключу[("gpt-image-2", "price_per_image_usd_via_fal_ai")],
            "$0.145; high 1024x1024 $0.211; low 1024x1024 $0.006",
        )
        self.assertEqual(по_ключу[("veo-3.1-fast", "price_per_second_usd_via_gemini")], "$0.15")
        self.assertEqual(по_ключу[("veo-3.1-fast", "deprecation_date_via_gemini")], "2026-11-17")
        self.assertTrue(all(н.нота.startswith(L.МЕТКА) for н in находки))


class Запись(unittest.TestCase):
    def test_повтор_не_растит_файл_а_новая_цена_отзывает_старую(self) -> None:
        находки, _ = L.находки(ТАБЛИЦА, set(), _как_есть)
        with tempfile.TemporaryDirectory() as каталог:
            путь = Path(каталог) / "facts.jsonl"
            путь.write_text("", encoding="utf-8")
            первый = L.записать(находки, "2026-10-13", путь)
            self.assertEqual(первый["отказано"], 0, первый["причины"])
            self.assertEqual(первый["записано"], len(находки))
            строк = len(путь.read_text(encoding="utf-8").splitlines())
            второй = L.записать(находки, "2026-10-13", путь)
            self.assertEqual(второй["записано"], 0)
            self.assertEqual(len(путь.read_text(encoding="utf-8").splitlines()), строк)

            таблица = dict(ТАБЛИЦА)
            таблица["gemini/veo-3.1-fast-generate-preview"] = {
                **ТАБЛИЦА["gemini/veo-3.1-fast-generate-preview"],
                "output_cost_per_second": 0.1,
            }
            новые, _ = L.находки(таблица, set(), _как_есть)
            третий = L.записать(новые, "2026-10-14", путь)
            self.assertEqual(третий["отозвано"], 1)
            цены = {
                ф.value
                for ф in load_facts(путь)
                if ф.attribute == "price_per_second_usd_via_gemini"
            }
            self.assertEqual(цены, {"$0.1"})
            self.assertEqual(L.проверить_собранное(load_facts(путь))["outcome"], PASS)


class ОфлайнПроверка(unittest.TestCase):
    def test_пусто_это_не_смогли(self) -> None:
        self.assertEqual(L.проверить_собранное([])["outcome"], UNMEASURED)

    def test_атрибут_без_провайдера_ловится(self) -> None:
        ф = Fact(
            model="veo-3.1-fast",
            attribute="price_per_second_usd",
            value="$0.15",
            source_url=L.ИСТОЧНИК,
            tier="blog",
            stated_on="2026-10-13",
            note=L.МЕТКА + ": ключи x",
            read_directly=True,
        )
        итог = L.проверить_собранное([ф])
        self.assertEqual(итог["outcome"], FAIL)
        self.assertIn("провайдера", итог["note"])


if __name__ == "__main__":
    unittest.main()
