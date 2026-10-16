"""Реестр, восьмой круг (2026-10-16): валидатор v8, выборка реестра 40 строк — 14 дефектов.

Каждый пункт — литералом (Т2):

1. Переосвещение — свет на объекте и экспозиция; «день -> ночь» — своя
   правка; `hdr` не переосвещение (n13).
2. Замена лица — FaceFusion, roop/inswapper, `fal-ai/face-swap`;
   `animate-replace` меняет весь персонаж — правка видео, не замена лица (n25).
3. Мёржи сообщества, NSFW и стилевые LoRA — в базе, но не кандидаты, пока
   заказчик сам не попросил (x05: `wan2.2_strangenames` на t2i 8 ГБ).

Т4: сети нет, база — синтетическая (кроме сторожа на живой базе в п. 4).
"""

from __future__ import annotations

import unittest

from studio import endpoints as ep
from studio import planner as pn
from studio.factindex import FactIndex
from studio.selfrag.facts import Fact

HF = "https://huggingface.co"
FAL_API = "https://fal.ai/api/openapi/queue/openapi.json?endpoint_id="


def факт(model: str, attribute: str, value: str, url: str = "", tier: str = "portal") -> Fact:
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url=url or f"https://example.invalid/{model}",
        tier=tier,
        stated_on="2026-10-01",
    )


def с_хаба(model: str, repo: str) -> list[Fact]:
    """Карточка из обхода хаба: лицензия, загрузки, задача — и больше ничего."""
    return [
        факт(model, "license", "apache-2.0", f"{HF}/{repo}"),
        факт(model, "adoption", "более 10 тыс. скачиваний", f"{HF}/{repo}"),
        факт(model, "pipeline_tag", "text-to-image", f"{HF}/api/models/{repo}"),
    ]


def операция(имя: str) -> pn.Operation:
    return next(о for о in pn.OPERATIONS if о.name == имя)


# --------------------------------------------------------------------------
# 1. ПРАВКИ: переосвещение против смены времени суток


class Переосвещение(unittest.TestCase):
    def test_relight_это_переосвещение(self) -> None:
        self.assertEqual(frozenset({"relight"}), ep.edit_intents("minimax/h3-max/relight"))

    def test_день_в_ночь_своя_правка(self) -> None:
        self.assertEqual(frozenset({"day-to-night"}), ep.edit_intents("acme/video/day-to-night"))

    def test_hdr_не_переосвещение(self) -> None:
        self.assertNotIn("relight", ep.edit_intents("acme/video/hdr"))

    def test_экспозиция_это_переосвещение(self) -> None:
        self.assertEqual(frozenset({"relight"}), ep.edit_intents("acme/video/exposure"))

    def test_правка_в_словаре_spec(self) -> None:
        self.assertIn("day-to-night", ep.EDIT_INTENTS)


# --------------------------------------------------------------------------
# 2. ЗАМЕНА ЛИЦА


class ЗаменаЛица(unittest.TestCase):
    def работа(self, имя: str, ид: str = "") -> tuple[str, ...]:
        rows = [факт(имя, "availability", f"on fal.ai as {ид} (image-to-image)")] if ид else []
        return ep.classify(имя, rows)[0]

    def test_facefusion(self) -> None:
        self.assertEqual(("face-swap",), self.работа("facefusion"))

    def test_roop_и_inswapper(self) -> None:
        self.assertEqual(("face-swap",), self.работа("roop"))
        self.assertEqual(("face-swap",), self.работа("inswapper_128"))

    def test_fal_face_swap(self) -> None:
        self.assertEqual(("face-swap",), self.работа("fal-face-swap", "fal-ai/face-swap"))

    def test_animate_replace_правка_видео_а_не_лицо(self) -> None:
        self.assertEqual(("v2v-edit",), self.работа("wan-2.2-14b-animate-replace"))
        self.assertEqual(frozenset({"replace-object"}), ep.edit_named("wan-2.2-14b-animate-replace"))


# --------------------------------------------------------------------------
# 3. ПОМЕТКИ ОТБОРА


class Пометки(unittest.TestCase):
    def база(self) -> list[Fact]:
        return [
            *с_хаба("strange-names", "somebody/Strange_Names"),
            *с_хаба("lab-base-1", "black-forest-labs/Lab-Base-1"),
            *с_хаба("pornmaster-x", "someone/pornmaster-x"),
            *с_хаба("illustrious-art", "black-forest-labs/illustrious-art"),
            *с_хаба("pixel-style-lora", "black-forest-labs/pixel-style-lora"),
            # Описанная модель неизвестной орги: строка вендора о работе — не мёрж.
            *с_хаба("documented-1", "newlab/documented-1"),
            факт("documented-1", "positioning", "text-to-image model", f"{HF}/newlab/documented-1", "vendor"),
        ]

    def setUp(self) -> None:
        self.р = ep.build(self.база())

    def test_мёрж_с_хаба_помечен(self) -> None:
        self.assertEqual(("community_checkpoint",), self.р.get("strange-names").flags)

    def test_орга_автора_не_помечена(self) -> None:
        self.assertEqual((), self.р.get("lab-base-1").flags)

    def test_описанная_модель_не_помечена(self) -> None:
        self.assertEqual((), self.р.get("documented-1").flags)

    def test_nsfw_целым_звеном(self) -> None:
        self.assertEqual(("nsfw", "community_checkpoint"), self.р.get("pornmaster-x").flags)
        # `illustrious` содержит «lust», но звеном не является.
        self.assertEqual((), self.р.get("illustrious-art").flags)

    def test_стилевой_lora(self) -> None:
        self.assertEqual(("style_lora",), self.р.get("pixel-style-lora").flags)

    def test_помеченные_не_в_индексе_работы_но_в_покрытии(self) -> None:
        self.assertEqual(
            ["documented-1", "illustrious-art", "lab-base-1"],
            sorted(e.model for e in self.р.by_function["t2i"]),
        )
        self.assertEqual(
            ["pixel-style-lora", "pornmaster-x", "strange-names"],
            sorted(e.model for e in self.р.flagged["t2i"]),
        )
        t2i = next(r for r in ep.coverage(self.р) if r["function"] == "t2i")
        self.assertEqual(6, t2i["orderable"])

    def test_просьба_снимает_пометку(self) -> None:
        self.assertEqual(frozenset(), ep.requested_flags("a picture of a dragon"))
        self.assertEqual(
            frozenset({"community_checkpoint", "style_lora"}), ep.requested_flags("use a civitai LoRA")
        )
        self.assertEqual(frozenset({"nsfw"}), ep.requested_flags("NSFW art, adults only"))
        узел = self.р.get("strange-names")
        self.assertTrue(ep.excluded_by_flags(узел))
        self.assertEqual("", ep.excluded_by_flags(узел, {"community_checkpoint"}))

    def test_плановщик_не_берёт_помеченных(self) -> None:
        найдены = pn.candidates_for(операция("генерация_изображения"), FactIndex(facts=self.база()))
        self.assertEqual(
            ["documented-1", "illustrious-art", "lab-base-1"], sorted(c.model for c in найдены)
        )

    def test_плановщик_берёт_по_просьбе(self) -> None:
        найдены = pn.candidates_for(
            операция("генерация_изображения"),
            FactIndex(facts=self.база()),
            requested_flags=("community_checkpoint", "style_lora"),
        )
        self.assertEqual(
            ["documented-1", "illustrious-art", "lab-base-1", "pixel-style-lora", "strange-names"],
            sorted(c.model for c in найдены),
        )


# --------------------------------------------------------------------------
# 4. ЖИВАЯ БАЗА: строки, которые чинил восьмой круг


class ЖиваяБаза(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.р = ep.build(FactIndex().facts)

    def test_работы_заказываемых_без_работы(self) -> None:
        self.assertEqual(("face-swap",), self.р.get("facefusion").functions)
        self.assertEqual(("t2i", "image-edit"), self.р.get("gpt-image-1").functions)
        self.assertEqual(("talking-avatar",), self.р.get("hallo").functions)
        self.assertEqual(("talking-avatar",), self.р.get("float").functions)

    def test_мусор_x05_помечен(self) -> None:
        self.assertIn("community_checkpoint", self.р.get("wan2.2_strangenames").flags)
        self.assertIn("nsfw", self.р.get("pornmasterpro_noobv3vae").flags)

    def test_mmaudio_звук_по_видео(self) -> None:
        self.assertEqual(("sfx",), self.р.get("mmaudio-v2").functions)

    def test_цена_шумодава_разбирается(self) -> None:
        узел = self.р.get("topaz-denoise-video")
        self.assertEqual((True, ("second",)), (узел.priced, узел.price_units))

    def test_картиночная_реставрация_не_берёт_видео(self) -> None:
        узел = self.р.get("topaz-restore-image")
        self.assertEqual(
            "вход не того вида: шаг подаёт видео, а эндпоинт берёт изображение (схема)",
            ep.input_mismatch(узел, ("видео",)),
        )
        self.assertEqual("", ep.input_mismatch(узел, ("изображение",)))
        self.assertEqual("", ep.input_mismatch(self.р.get("topaz-denoise-video"), ("видео",)))

    def test_открытые_веса_липсинка_с_памятью(self) -> None:
        self.assertEqual(8.0, self.р.get("latentsync-1.5").vram_gb)
        self.assertEqual(18.0, self.р.get("latentsync-1.6").vram_gb)
        self.assertEqual(4.0, self.р.get("musetalk").vram_gb)
        for имя in ("sadtalker", "hallo", "float", "musetalk", "wav2lip"):
            self.assertEqual("веса открыты", self.р.get(имя).open_weights, имя)


if __name__ == "__main__":
    unittest.main()
