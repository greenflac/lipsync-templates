"""Канал `scripts/sync_fal_catalog.py`: имя эндпоинта, охват, разбор страницы,
обход через подменённый получатель, идемпотентная запись и офлайн-проверка.

Сети нет (Т4): весь обход идёт через получатель, который здесь — словарь
ответов. Запись идёт во временный файл фактов, не в базу.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from scripts import sync_fal_catalog as S
from studio.selfrag.facts import load_facts

СЕГОДНЯ = "2026-10-14"


def _страница(эндпоинт: str, цена_текстом: str, единица: str, цена: float, статус: str) -> str:
    """Кусок страницы fal.ai в том виде, в каком Next.js кладёт данные: JSON в JS-строке."""
    тело = (
        f'"status":"{статус}","pricingInfoOverride":{json.dumps(цена_текстом)},'
        '"deprecated":false,"removed":false,"hidePricing":false,'
        f'"category":"image-to-video","publicEndpointBilling":{{"endpoint":"{эндпоинт}",'
        f'"billing_unit":"{единица}","price":{цена},"provider_type":"partner"}}'
    )
    return "self.__next_f.push([1," + json.dumps("x:{" + тело + "}") + "])"


def _схема(поля: dict[str, Any], обязательные: list[str]) -> str:
    return json.dumps(
        {
            "components": {
                "schemas": {
                    "Input": {"properties": поля, "required": обязательные},
                    "Output": {"properties": {"video": {"type": "object"}}},
                }
            }
        }
    )


class ИмяЭндпоинта(unittest.TestCase):
    def test_вариант_семьи_пишется_как_в_базе(self) -> None:
        self.assertEqual(
            S.имя_по_таблице("fal-ai/veo3.1/fast/image-to-video")[0], "veo-3.1-fast-i2v"
        )
        self.assertEqual(
            S.имя_по_таблице("bytedance/seedance-2.0/mini/reference-to-video")[0],
            "seedance-2.0-mini-r2v",
        )

    def test_голый_эндпоинт_многорежимной_семьи_получает_режим_из_категории(self) -> None:
        self.assertEqual(S.имя_по_таблице("fal-ai/veo3.1", "text-to-video")[0], "veo-3.1-t2v")
        self.assertEqual(
            S.имя_по_таблице("fal-ai/veo3.1/fast", "text-to-video")[0], "veo-3.1-fast-t2v"
        )

    def test_операция_с_именем_не_получает_режим(self) -> None:
        self.assertEqual(
            S.имя_по_таблице("fal-ai/ltx-2.3-quality/deblur", "video-to-video")[0],
            "ltx-2.3-quality-deblur",
        )

    def test_картиночная_семья_без_суффикса_t2i(self) -> None:
        self.assertEqual(
            S.имя_по_таблице("fal-ai/nano-banana-pro", "text-to-image")[0], "nano-banana-pro"
        )
        self.assertEqual(S.имя_по_таблице("fal-ai/nano-banana-pro/edit")[0], "nano-banana-pro-edit")

    def test_базовый_режим_однородной_семьи_не_пишется(self) -> None:
        self.assertEqual(
            S.имя_по_таблице("bytedance/seedream/v5/pro/text-to-image")[0], "seedream-5-pro"
        )

    def test_эндпоинт_вне_таблицы_берёт_имя_из_адреса_и_говорит_это(self) -> None:
        имя, нота = S.имя_по_таблице("fal-ai/flashvsr/upscale/video")
        self.assertEqual(имя, "flashvsr-upscale-video")
        self.assertIn("из адреса", нота)

    def test_оговорка_только_у_эндпоинта_без_версии(self) -> None:
        self.assertTrue(S.имя_по_таблице("alibaba/happy-horse/text-to-video")[1])
        self.assertEqual(S.имя_по_таблице("alibaba/happy-horse/v1.1/text-to-video")[1], "")

    def test_известное_имя_эндпоинта_выигрывает(self) -> None:
        def разрешитель(имя: str) -> tuple[str, str]:
            return имя, ""

        известные = {
            "fal-ai/kling-video/o3/pro/image-to-video": "kling-video-o3-pro-image-to-video"
        }
        имя, новая, _ = S.разрешить_имя(
            "fal-ai/kling-video/o3/pro/image-to-video", известные, разрешитель
        )
        self.assertEqual((имя, новая), ("kling-video-o3-pro-image-to-video", False))

    def test_имя_всей_семьи_не_продолжается_на_эндпоинт_режима(self) -> None:
        def разрешитель(имя: str) -> tuple[str, str]:
            return имя, ""

        имя, _, _ = S.разрешить_имя(
            "fal-ai/veo3.1", {"fal-ai/veo3.1": "veo-3.1"}, разрешитель, "text-to-video"
        )
        self.assertEqual(имя, "veo-3.1-t2v")

    def test_отказ_слоя_имён_даёт_новую_модель_с_нотой(self) -> None:
        def разрешитель(имя: str) -> tuple[str, str]:
            return имя, "сосед"

        имя, новая, нота = S.разрешить_имя("fal-ai/veo3.1/image-to-video", {}, разрешитель)
        self.assertEqual((имя, новая), ("veo-3.1-i2v", True))
        self.assertIn("отдельный вариант", нота)


class Охват(unittest.TestCase):
    def test_надстройки_и_не_медиа_вне_охвата(self) -> None:
        self.assertTrue(S.в_охвате("fal-ai/veo3.1/image-to-video", "image-to-video"))
        self.assertFalse(S.в_охвате("fal-ai/ltx-2.3-22b/image-to-video/lora", "image-to-video"))
        self.assertFalse(S.в_охвате("minimax/h3/t2v/trainer", "training"))
        self.assertFalse(S.в_охвате("fal-ai/veo3.1", "llm"))
        self.assertFalse(S.в_охвате("fal-ai/some-unrelated-model", "text-to-image"))

    def test_апскейлер_в_охвате_без_таблицы(self) -> None:
        self.assertTrue(S.в_охвате("clarityai/crystal-video-upscaler", "video-to-video"))


class РазборСтраницы(unittest.TestCase):
    def test_цена_статус_и_биллинг(self) -> None:
        э = "fal-ai/veo3.1/fast/image-to-video"
        текст = 'Charged **$0.10** without audio, "quoted" or **$0.15** with audio.'
        разбор = S.разобрать_страницу(_страница(э, текст, "seconds", 0.15, "unlisted"), э)
        self.assertEqual(разбор["status"], "unlisted")
        self.assertEqual(разбор["pricingInfoOverride"], текст)
        self.assertIs(разбор["deprecated"], False)
        self.assertEqual(разбор["billing"], {"unit": "seconds", "price": 0.15})

    def test_нулевая_цена_биллинга_не_пишется(self) -> None:
        э = "fal-ai/creative-upscaler"
        разбор = S.разобрать_страницу(_страница(э, "", "compute seconds", 0, "public"), э)
        находки, _ = S.находки_страницы("creative-upscaler", э, "image-to-image", разбор, None)
        self.assertEqual([н.атрибут for н in находки], ["availability"])

    def test_биллинг_чужого_эндпоинта_не_берётся(self) -> None:
        страница = _страница("fal-ai/other", "x", "seconds", 0.15, "public")
        self.assertIsNone(S.разобрать_страницу(страница, "fal-ai/veo3.1")["billing"])


def _получатель(ответы: dict[str, str]) -> S.Получатель:
    def получить(url: str, заголовки: dict[str, str] | None) -> dict[str, Any]:
        for начало, текст in ответы.items():
            if url.startswith(начало):
                return {"outcome": PASS, "text": текст, "status": 200}
        return {"outcome": FAIL, "status": 404, "text": "", "note": "нет такого"}

    return получить


class Обход(unittest.TestCase):
    def _обойти(self) -> S.Отчёт:
        э = "fal-ai/veo3.1/fast/image-to-video"
        ответы = {
            "https://api.fal.ai/v1/models?limit=100&cursor=2": json.dumps(
                {
                    "models": [{"endpoint_id": "x/llm", "metadata": {"category": "llm"}}],
                    "has_more": False,
                }
            ),
            "https://api.fal.ai/v1/models?limit=100": json.dumps(
                {
                    "models": [{"endpoint_id": э, "metadata": {"category": "image-to-video"}}],
                    "has_more": True,
                    "next_cursor": "2",
                }
            ),
            "https://api.fal.ai/v1/models/pricing": json.dumps(
                {"prices": [{"endpoint_id": э, "unit_price": 0.15, "unit": "seconds"}]}
            ),
            "https://fal.ai/models/": _страница(
                э, "For every second you pay **$0.10** without audio", "seconds", 0.15, "unlisted"
            ),
            "https://fal.ai/api/openapi/": _схема(
                {
                    "prompt": {"type": "string"},
                    "image_url": {"type": "string"},
                    "duration": {"enum": ["4s", "6s", "8s"]},
                    "generate_audio": {"type": "boolean", "default": True},
                    "negative_prompt": {"type": "string"},
                },
                ["prompt", "image_url"],
            ),
        }

        def разрешитель(имя: str) -> tuple[str, str]:
            return имя, ""

        return S.собрать(_получатель(ответы), разрешитель, {}, "ключ", пауза=0)

    def test_каталог_по_страницам_и_находки_одного_эндпоинта(self) -> None:
        отчёт = self._обойти()
        self.assertEqual(
            (отчёт.эндпоинтов, отчёт.в_охвате, отчёт.страниц, отчёт.схем), (2, 1, 1, 1)
        )
        атрибуты = {н.атрибут: н.значение for н in отчёт.находки}
        self.assertEqual(атрибуты["price_unit_second_usd"], "$0.15 per second")
        self.assertIn("listing status unlisted", атрибуты["availability"])
        self.assertEqual(атрибуты["requires_inputs"], "изображение, текст")
        self.assertEqual(атрибуты["duration_enum_seconds"], "4s, 6s, 8s")
        self.assertIn("generate_audio", атрибуты["audio_output"])
        self.assertIn("accepted", атрибуты["negative_prompt"])
        self.assertEqual({н.модель for н in отчёт.находки}, {"veo-3.1-fast-i2v"})
        self.assertEqual(отчёт.расхождения_цен, [])

    def test_запись_идемпотентна_и_старое_значение_отзывается(self) -> None:
        отчёт = self._обойти()
        with tempfile.TemporaryDirectory() as каталог:
            путь = Path(каталог) / "facts.jsonl"
            путь.write_text("", encoding="utf-8")
            первый = S.записать(отчёт.находки, СЕГОДНЯ, путь)
            self.assertEqual(первый["отказано"], 0, первый["причины"])
            self.assertEqual(первый["записано"], len(отчёт.находки))
            строк = len(путь.read_text(encoding="utf-8").splitlines())
            второй = S.записать(отчёт.находки, СЕГОДНЯ, путь)
            self.assertEqual((второй["записано"], второй["не_изменилось"]), (0, len(отчёт.находки)))
            self.assertEqual(len(путь.read_text(encoding="utf-8").splitlines()), строк)

            цена = next(н for н in отчёт.находки if н.атрибут == "price_unit_second_usd")
            новая = S.Находка(цена.модель, цена.атрибут, "$0.2 per second", цена.url, цена.нота)
            третий = S.записать([новая], СЕГОДНЯ, путь)
            self.assertEqual((третий["записано"], третий["отозвано"]), (1, 1))
            стоят = {ф.value for ф in load_facts(путь) if ф.attribute == "price_unit_second_usd"}
            self.assertEqual(стоят, {"$0.2 per second"})
            self.assertEqual(S.проверить_собранное(load_facts(путь))["outcome"], PASS)

    def test_чужая_строка_той_же_площадки_не_перебивается(self) -> None:
        with tempfile.TemporaryDirectory() as каталог:
            путь = Path(каталог) / "facts.jsonl"
            чужая = {
                "model": "veo-3.1-fast-i2v",
                "attribute": "max_seconds",
                "value": "8",
                "source_url": "https://fal.ai/models/fal-ai/veo3.1",
                "tier": "portal",
                "stated_on": "2026-09-01",
                "note": "чужой канал",
            }
            путь.write_text(json.dumps(чужая, ensure_ascii=False) + "\n", encoding="utf-8")
            находка = S.Находка(
                "veo-3.1-fast-i2v",
                "max_seconds",
                "6",
                "https://fal.ai/models/fal-ai/veo3.1/fast/image-to-video",
                "страница эндпоинта fal.ai",
            )
            итог = S.записать([находка], СЕГОДНЯ, путь)
            self.assertEqual((итог["записано"], итог["отказано"]), (0, 1))
            self.assertIn("спор с", итог["споры"][0])


class ОфлайнПроверка(unittest.TestCase):
    def test_пустая_база_это_не_смогли(self) -> None:
        self.assertEqual(S.проверить_собранное([])["outcome"], UNMEASURED)

    def test_неверный_тир_ловится(self) -> None:
        from studio.selfrag.facts import Fact

        ф = Fact(
            model="veo-3.1-fast-i2v",
            attribute="availability",
            value="on fal.ai",
            source_url="https://fal.ai/models/fal-ai/veo3.1/fast/image-to-video",
            tier="vendor",
            stated_on=СЕГОДНЯ,
            note="страница эндпоинта fal.ai: status",
            read_directly=True,
        )
        итог = S.проверить_собранное([ф])
        self.assertEqual(итог["outcome"], FAIL)
        self.assertIn("тир", итог["note"])


if __name__ == "__main__":
    unittest.main()
