"""Слой имён, семей и `model_advice` — находки валидатора G5, G9, G10, G11, G14
(2026-10-14).

Каждый тест на своей ВРЕМЕННОЙ базе (Т5), кроме явно помеченных проверок
кураторской таблицы, которым база не нужна. Ожидаемые значения — литералы
(Т2), сети нет (Т4), у каждого правила обе стороны (И5). Даты источников
считаются от сегодняшнего дня: проверяется ВОЗРАСТ, а не календарь.
"""

from __future__ import annotations

import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from studio.mcp import advice, misses
from studio.selfrag import attrfamily, modelnames
from studio.selfrag.facts import FactStore, load_facts


def дней_назад(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def строка(
    model: str,
    attribute: str,
    value: str,
    url: str,
    tier: str = "vendor",
    возраст: int = 5,
) -> dict:
    return {
        "model": model,
        "attribute": attribute,
        "value": value,
        "source_url": url,
        "tier": tier,
        "stated_on": дней_назад(возраст),
    }


ЦЕНА_VEO = (
    "Standard $0.40/s at 720p and 1080p, $0.60/s at 4k; Fast $0.10/s (720p), $0.12/s "
    "(1080p), $0.30/s (4k); Lite $0.05/s (720p), $0.08/s (1080p), 4k not supported"
)


class База(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.путь = Path(self._dir.name) / "facts.jsonl"

    def база(self, *строки: dict) -> Path:
        self.путь.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in строки), encoding="utf-8"
        )
        return self.путь

    def veo(self) -> Path:
        return self.база(
            строка("veo-3.1", "price_per_second", ЦЕНА_VEO, "https://ai.google.dev/pricing"),
            строка("veo-3.1", "max_seconds", "8", "https://ai.google.dev/b"),
            строка("veo-3.1-lite", "resolution_options", "720p, 1080p", "https://ai.google.dev/c"),
            строка("veo-3", "max_seconds", "8", "https://deepmind.google/veo"),
        )


class G5_ВариантБезЗаписей(База):
    def test_три_написания_fast_это_вариант_veo_31(self) -> None:
        self.veo()
        for имя in ("veo-3.1-fast", "Veo3.1 Fast", "veo-3.1-fast-generate-preview"):
            got = advice.advise(имя, path=self.путь)
            self.assertEqual(got["outcome"], "could not measure", имя)
            self.assertEqual(got["reason"], "variant_not_recorded", имя)
            self.assertEqual(got["near"], [], имя)
            self.assertEqual(got["claims"], {}, имя)
            self.assertEqual(got["family"]["family_name"], "veo-3.1", имя)
            self.assertEqual(got["family"]["variant_words"], ["fast"], имя)

    def test_срез_цены_своей_ступени_помечен_выведенным(self) -> None:
        got = advice.advise("veo-3.1-fast", "price", path=self.veo())
        срез = got["variant_slices"]["price_per_second@veo-3.1"]
        self.assertEqual(срез["value"], "Fast $0.10/s (720p), $0.12/s (1080p), $0.30/s (4k)")
        self.assertIn("DERIVED", срез["derivation"])
        self.assertEqual(срез["about"], "veo-3.1")
        self.assertIn("DERIVED from the family row, not measured", got["note"])

    def test_известный_вариант_получает_свой_срез(self) -> None:
        got = advice.advise("veo-3.1-lite", "price", path=self.veo())
        self.assertEqual(got["reason"], "answered_by_family")
        self.assertEqual(
            got["variant_slices"]["price_per_second@veo-3.1"]["value"],
            "Lite $0.05/s (720p), $0.08/s (1080p), 4k not supported",
        )

    def test_незнакомое_звено_не_вариант(self) -> None:
        """И5: `banana` — не слово-ступень; это не вариант, а незнакомое имя."""
        got = advice.advise("veo-3.1-banana", path=self.veo())
        self.assertNotEqual(got["reason"], "variant_not_recorded")
        self.assertEqual(got.get("family"), {})

    def test_другая_версия_не_семья_варианта(self) -> None:
        """И5: `veo-3-fast` — вариант veo-3, а не veo-3.1."""
        got = advice.advise("veo-3-fast", path=self.veo())
        self.assertEqual(got["family"]["family_name"], "veo-3")

    def test_каждое_слово_ступени_работает(self) -> None:
        """Т1 для `TIER_WORDS`: выкинутое слово — красный тест."""
        known = ["veo-3.1"]
        for слово in sorted(modelnames.TIER_WORDS):
            семья, лишнее = modelnames.unrecorded_variant(f"veo-3.1-{слово}", known)
            self.assertEqual(семья, ["veo-3.1"], слово)
            self.assertEqual(лишнее, (слово,), слово)
        self.assertEqual(
            modelnames.TIER_WORDS,
            frozenset(
                {
                    "fast", "lite", "pro", "turbo", "hd", "max", "standard", "std", "flash",
                    "ultra", "mini", "plus", "preview", "i2v", "t2v", "t2i", "s2v", "r2v", "edit",
                }
            ),
        )  # fmt: skip


class G5_СрезСтроки(unittest.TestCase):
    def test_кусок_по_слову_ступени(self) -> None:
        self.assertEqual(
            attrfamily.variant_slice(ЦЕНА_VEO, ["fast"]),
            "Fast $0.10/s (720p), $0.12/s (1080p), $0.30/s (4k)",
        )

    def test_слово_внутри_слова_не_ступень(self) -> None:
        self.assertEqual(attrfamily.variant_slice("fastest 1; b 2", ["fast"]), "")

    def test_ступень_в_середине_куска_не_его_кусок(self) -> None:
        self.assertEqual(attrfamily.variant_slice("a is fast; b 2", ["fast"]), "")

    def test_один_кусок_нечего_выделять(self) -> None:
        self.assertEqual(attrfamily.variant_slice("Fast $0.10/s", ["fast"]), "")


class G9_Тождества(База):
    def test_hailuo3_это_minimax_h3_со_свидетельством(self) -> None:
        self.база(
            строка("minimax-h3", "max_seconds", "15", "https://platform.minimax.io/x"),
            строка("hailuo3", "max_resolution", "2K", "https://docs.dev.runwayml.com/openapi.json",
                   "portal"),
        )  # fmt: skip
        got = advice.advise("hailuo3", path=self.путь)
        self.assertEqual(got["outcome"], "pass")
        self.assertEqual(got["resolved_as"]["spellings"], ["hailuo3", "minimax-h3"])
        self.assertEqual(sorted(got["claims"]), ["max_resolution", "max_seconds"])
        self.assertIn("Runway openapi", got["resolved_as"]["note"])

    def test_hailuo_23_не_склеивается_с_h3(self) -> None:
        """И5: Hailuo 2.3 — другая модель."""
        self.assertNotEqual(modelnames.fold("minimax-hailuo-2.3"), modelnames.fold("minimax-h3"))
        self.assertEqual(modelnames.fold("Hailuo 3.0"), "minimaxh3")
        self.assertEqual(modelnames.fold("minimax-hailuo-3"), "minimaxh3")

    def test_lipsync_2_pro_имя_самого_sync(self) -> None:
        self.assertEqual(modelnames.fold("lipsync-2-pro"), modelnames.fold("sync-lipsync-v2-pro"))
        self.assertEqual(modelnames.fold("lipsync-2"), modelnames.fold("sync-lipsync-v2"))
        # И5: голое слово — не модель sync.
        self.assertEqual(modelnames.fold("lipsync"), "lipsync")
        self.assertEqual(modelnames.fold("pixverse-lipsync"), "pixverselipsync")

    def test_eleven_music(self) -> None:
        self.assertEqual(modelnames.fold("eleven-music"), modelnames.fold("elevenlabs-music"))
        self.assertNotEqual(modelnames.fold("minimax-music"), modelnames.fold("eleven-music"))

    def test_у_каждой_переписи_есть_свидетельство(self) -> None:
        без = [
            было
            for было, _ in modelnames.ПЕРЕПИСИ_НАЧАЛА
            if было not in modelnames.SYNONYM_EVIDENCE
        ]
        self.assertEqual(без, [])

    def test_chatterbox_семья_и_вариант(self) -> None:
        self.база(
            строка("chatterbox", "license", "MIT", "https://huggingface.co/ResembleAI/chatterbox"),
            строка("chatterbox-tts", "price", "$0.025", "https://fal.ai/models/x", "portal"),
        )
        семья = advice.advise("chatterbox", path=self.путь)
        self.assertEqual(семья["family"]["variants"], ["chatterbox-tts"])
        вариант = advice.advise("chatterbox-tts", path=self.путь)
        self.assertEqual(вариант["family"]["role"], "variant")
        self.assertEqual(вариант["family"]["family_name"], "chatterbox")

    def test_другая_версия_не_опечатка(self) -> None:
        self.база(
            строка("seedream-4.0", "max_resolution", "4K", "https://seed.bytedance.com/a"),
            строка("seedream-4.0-edit", "max_inputs", "10", "https://seed.bytedance.com/b"),
        )
        for имя in ("seedream-4.5", "seedream-5"):
            got = advice.advise(имя, path=self.путь)
            self.assertEqual(got["outcome"], "could not measure", имя)
            self.assertEqual(got["reason"], "version_not_recorded", имя)
            self.assertEqual(got["other_versions"], ["seedream-4.0", "seedream-4.0-edit"], имя)
            self.assertEqual(got["near"], [], имя)
            self.assertEqual(got["claims"], {}, имя)

    def test_ray3_видит_линейку_luma(self) -> None:
        self.база(строка("luma-ray-3.2-i2v", "max_seconds", "10", "https://lumalabs.ai/x"))
        got = advice.advise("ray3", path=self.путь)
        self.assertEqual(got["reason"], "version_not_recorded")
        self.assertEqual(got["other_versions"], ["luma-ray-3.2-i2v"])

    def test_та_же_версия_не_другая(self) -> None:
        """И5: `seedream-4.0-banana` — не «другая версия» `seedream-4.0`."""
        self.assertEqual(
            modelnames.lineage("seedream-4.0-banana", ["seedream-4.0", "seedream-5"]),
            ["seedream-5"],
        )

    def test_опечатка_остаётся_опечаткой(self) -> None:
        """И5: `seedrem-4.0` — не другая версия, а опечатка в имени линейки."""
        self.база(строка("seedream-4.0", "max_resolution", "4K", "https://seed.bytedance.com/a"))
        got = advice.advise("seedreem-4.0", path=self.путь)
        self.assertNotEqual(got["reason"], "version_not_recorded")


class G10_РольВСемье(База):
    def семья(self) -> Path:
        return self.база(
            строка("ltx-2.3", "max_seconds", "20", "https://ltx.io/model"),
            строка("ltx-2.3-fast", "max_seconds", "10", "https://ltx.io/fast"),
            строка(
                "ltx-2-3-all-in-one-workflow-for-rtx-3060",
                "runs_on",
                "3060 12GB",
                "https://civitai.com/models/1",
                "portal",
            ),
            строка("ltx-2.3-distilled-v2", "license", "x", "https://huggingface.co/someone/LTX",
                   "portal"),
            строка("ltx-2.3-controlnet", "inputs", "depth", "https://ltx.io/cn"),
            строка("ltx-2.3-enhancers", "inputs", "x", "https://civitai.com/models/2", "portal"),
        )  # fmt: skip

    def test_роли(self) -> None:
        store = FactStore(load_facts(self.семья()))
        self.assertEqual(store.variant_role("ltx-2.3-fast"), "vendor_variant")
        self.assertEqual(
            store.variant_role("ltx-2-3-all-in-one-workflow-for-rtx-3060"), "community"
        )
        self.assertEqual(store.variant_role("ltx-2.3-distilled-v2"), "community")
        self.assertEqual(store.variant_role("ltx-2.3-controlnet"), "addon")
        # Civitai сильнее надстроечного слова.
        self.assertEqual(store.variant_role("ltx-2.3-enhancers"), "community")

    def test_семья_делит_роли_и_общинное_не_отвечает(self) -> None:
        got = advice.advise("ltx-2.3", path=self.семья())
        семья = got["family"]
        self.assertEqual(семья["variants"], ["ltx-2.3-fast"])
        self.assertEqual(
            семья["community"],
            [
                "ltx-2-3-all-in-one-workflow-for-rtx-3060",
                "ltx-2.3-distilled-v2",
                "ltx-2.3-enhancers",
            ],
        )
        self.assertEqual(семья["addons"], ["ltx-2.3-controlnet"])
        self.assertEqual(sorted(got["family_claims"]), ["max_seconds@ltx-2.3-fast"])
        self.assertEqual(семья["variant_roles"]["ltx-2.3-controlnet"], "addon")

    def test_общинное_не_получает_ответ_семьи(self) -> None:
        got = advice.advise("ltx-2.3-distilled-v2", "max_seconds", path=self.семья())
        self.assertEqual(got["family"]["role_in_family"], "community")
        self.assertEqual(got["family_claims"], {})
        self.assertNotEqual(got["reason"], "answered_by_family")

    def test_вариант_вендора_получает(self) -> None:
        got = advice.advise("ltx-2.3-fast", "license", path=self.база(
            строка("ltx-2.3", "license", "LTX-2 Community", "https://ltx.io/license"),
            строка("ltx-2.3-fast", "max_seconds", "10", "https://ltx.io/fast"),
        ))  # fmt: skip
        self.assertEqual(got["family"]["role_in_family"], "vendor_variant")
        self.assertEqual(got["reason"], "answered_by_family")

    def test_слова_ролей_закреплены(self) -> None:
        """Т1: слово, выкинутое из списка или добавленное, — красный тест."""
        self.assertEqual(
            modelnames.COMMUNITY_WORDS,
            frozenset(
                {
                    "workflow", "workflows", "lora", "loras", "merge", "merged", "uncensored",
                    "nsfw", "finetune", "finetuned", "abliterated", "aio", "gguf", "custom",
                    "hybrid", "fusionx",
                }
            ),
        )  # fmt: skip
        self.assertEqual(
            modelnames.ADDON_WORDS,
            frozenset(
                {"controlnet", "upscaler", "upscale", "encoder", "decoder", "vae", "enhancer",
                 "enhancers", "adapter"}
            ),
        )  # fmt: skip
        self.assertEqual(
            modelnames.name_role("", "flux2-klein-9b-uncensored-text-encoder"), "community"
        )
        self.assertEqual(modelnames.name_role("", "minimax-h3-fun-controlnet-union"), "addon")
        self.assertEqual(modelnames.name_role("", "minimax-h3-max"), "")


class G14_СоветПриСпоре(База):
    def test_вендор_против_площадки_область_эндпоинта(self) -> None:
        self.база(
            строка("m-1", "max_seconds", "15", "https://vendor.example/a", "vendor", 10),
            строка("m-1", "max_seconds", "5", "https://other.example/b", "vendor", 300),
            строка("m-1", "max_seconds", "10", "https://fal.ai/models/m", "portal", 1),
        )
        got = advice.advise("m-1", "max_seconds", path=self.путь)
        self.assertEqual(got["outcome"], "fail", "заголовок спора не меняется (Р1)")
        совет = got["claims"]["max_seconds"]["recommended"]
        self.assertEqual(совет["value"], "15")
        self.assertEqual(совет["tier"], "vendor")
        почему = {o["value"]: o["why_not"] for o in совет["others"]}
        self.assertIn("same tier, older statement", почему["5"])
        self.assertIn("endpoint scope: fal.ai", почему["10"])

    def test_неудавшийся_замер_не_советуется(self) -> None:
        self.база(
            строка("m-1", "max_seconds", "НЕ СМОГЛИ: на счёте нет средств", "https://api.x/p",
                   "probe", 1),
            строка("m-1", "max_seconds", "10", "https://blog.example/b", "blog", 1),
        )  # fmt: skip
        совет = advice.advise("m-1", "max_seconds", path=self.путь)["claims"]["max_seconds"]
        self.assertEqual(совет["recommended"]["value"], "10")

    def test_краткая_форма_несёт_совет(self) -> None:
        self.база(
            строка("m-1", "max_seconds", "15", "https://vendor.example/a", "vendor", 10),
            строка("m-1", "max_seconds", "10", "https://blog.example/b", "blog", 1),
        )
        got = advice.brief("m-1", path=self.путь)
        self.assertEqual(got["claims"]["max_seconds"]["recommended"]["value"], "15")
        self.assertEqual(sorted(got["claims"]["max_seconds"]["values"]), ["10", "15"])


class G14_ВозможноУстарело(База):
    def test_порог_30_дней_с_обеих_сторон(self) -> None:
        """Т1: 30 дней — свежее, 31 — помечено."""
        self.assertEqual(advice.POSSIBLY_STALE_DAYS, 30)
        self.база(
            строка("m-1", "price_per_second", "$1", "https://vendor.example/a", "vendor", 30),
            строка("m-2", "price_per_second", "$1", "https://vendor.example/a", "vendor", 31),
        )
        свежая = advice.advise("m-1", path=self.путь)
        старая = advice.advise("m-2", path=self.путь)
        self.assertEqual(свежая["possibly_stale"], [])
        self.assertFalse(свежая["claims"]["price_per_second"]["possibly_stale"])
        self.assertEqual(старая["possibly_stale"], ["price_per_second"])
        self.assertEqual(старая["outcome"], "pass", "пометка не меняет исход")
        self.assertIn("Possibly stale", старая["possibly_stale_note"])

    def test_не_цена_у_не_видео_не_помечается(self) -> None:
        self.база(строка("m-1", "license", "MIT", "https://vendor.example/a", "vendor", 60))
        self.assertEqual(advice.advise("m-1", path=self.путь)["possibly_stale"], [])

    def test_факт_видеомодели_помечается(self) -> None:
        """Пункт 15 (2026-10-15): у видеомодели помечается факт с коротким окном
        (30 дней), а лицензия в 60 дней — ещё свежая (окно 180)."""
        self.база(
            строка("m-1", "license", "MIT", "https://vendor.example/a", "vendor", 60),
            строка("m-1", "failure_mode", "лица плывут", "https://vendor.example/c", "vendor", 31),
            строка("m-1", "max_seconds", "10", "https://vendor.example/b", "vendor", 1),
        )
        self.assertEqual(advice.advise("m-1", path=self.путь)["possibly_stale"], ["failure_mode"])


class G11_Размер(База):
    def большая(self) -> Path:
        строки = [
            строка(
                "big-1", f"attr_{i:02d}", f"value {i} " + "x" * 200, f"https://vendor.example/{i}"
            )
            for i in range(40)
        ]
        return self.база(*строки)

    def test_краткая_в_потолке_и_заполняет_его(self) -> None:
        """Т1 для BRIEF_MAX_BYTES в обе стороны: не больше потолка и не сильно меньше."""
        self.assertEqual(advice.BRIEF_MAX_BYTES, 6144)
        got = advice.brief("big-1", path=self.большая())
        self.assertLessEqual(got["size_bytes"], 6144)
        self.assertGreater(got["size_bytes"], 6144 - 600)
        self.assertEqual(got["size_bytes"], advice.размер(got))
        self.assertEqual(got["claims_total"], 40)
        self.assertEqual(got["omitted"]["claims"] + len(got["claims"]), 40)
        self.assertIn("full=True", got["omitted"]["how_to_get_more"])

    def test_спорное_не_срезается(self) -> None:
        строки = [
            строка("big-1", f"attr_{i:02d}", "v" * 200, f"https://vendor.example/{i}")
            for i in range(40)
        ] + [
            строка("big-1", "zz_disputed", "15", "https://vendor.example/a"),
            строка("big-1", "zz_disputed", "10", "https://vendor.example/b"),
        ]
        got = advice.brief("big-1", path=self.база(*строки))
        self.assertIn("zz_disputed", got["claims"])
        self.assertEqual(got["contested"], ["zz_disputed"])

    def test_спорное_не_срезается_даже_сверх_потолка(self) -> None:
        """Спор — то, ради чего инструмент: его стороны не режутся ради размера."""
        строки = [
            строка(
                "big-1", f"d_{i:02d}", f"{side}" + "w" * 200, f"https://vendor.example/{i}{side}"
            )
            for i in range(30)
            for side in ("1", "2")
        ]
        got = advice.brief("big-1", path=self.база(*строки))
        self.assertEqual(len(got["claims"]), 30)
        self.assertEqual(len(got["contested"]), 30)

    def test_значение_и_число_значений_в_краткой(self) -> None:
        self.база(
            *[
                строка("m-1", "observed_behaviour", f"{i}" + "y" * 300, f"https://v.example/{i}")
                for i in range(5)
            ],
            *[строка("m-1", "failure_mode", f"f{i}" + "z" * 300, f"https://v.example/f{i}")
              for i in range(5)],
        )  # fmt: skip
        got = advice.brief("m-1", path=self.путь)
        разбор = got["claims"]["observed_behaviour"]
        self.assertEqual(len(разбор["values"]), 3)
        self.assertEqual(разбор["values_total"], 5)
        self.assertEqual(len(разбор["values"][0]), 160)
        self.assertEqual(len(got["failure_modes"]), 3)
        self.assertEqual(got["failure_modes_total"], 5)

    def test_длина_имени(self) -> None:
        """Т1 для MAX_NAME_LENGTH: 120 знаков — имя, 121 — нет."""
        self.база(строка("m-1", "license", "MIT", "https://vendor.example/a"))
        self.assertEqual(modelnames.MAX_NAME_LENGTH, 120)
        длинное = advice.advise("a" * 121, path=self.путь)
        self.assertEqual(длинное["outcome"], "fail")
        self.assertEqual(длинное["reason"], "name_too_long")
        self.assertLess(advice.размер(длинное), 1200)
        self.assertNotEqual(advice.advise("a" * 120, path=self.путь)["reason"], "name_too_long")
        self.assertLess(advice.размер(advice.brief("a" * 5000, path=self.путь)), 1500)

    def test_журнал_не_берёт_не_имя(self) -> None:
        строка_ = {"model": "a" * 121, "attribute": "", "outcome": "fail", "known": 0,
                   "asked_on": "2026-10-14"}  # fmt: skip
        self.assertTrue(any("не имя модели" in p for p in misses.problems(строка_)))
        строка_["model"] = "a" * 120
        self.assertFalse(any("не имя модели" in p for p in misses.problems(строка_)))

    def test_stale_полная_форма_постранична(self) -> None:
        """Т1 для STALE_FULL_PAGE: 150 строк — страница 100 и следующая с 100."""
        self.assertEqual(advice.STALE_FULL_PAGE, 100)
        self.база(
            *[
                строка(f"m{i}", "a", "1", f"https://example.org/{i}", "blog", 400)
                for i in range(150)
            ]
        )
        первая = advice.stale(days=90, path=self.путь, full=True)
        self.assertEqual(len(первая["stale"]), 100)
        self.assertEqual(первая["counts"]["stale"], 150)
        self.assertEqual(первая["next_offset"], 100)
        вторая = advice.stale(days=90, path=self.путь, full=True, offset=100)
        self.assertEqual(len(вторая["stale"]), 50)
        self.assertIsNone(вторая["next_offset"])
        self.assertEqual(вторая["violations"], 150, "счёт целиком, режется только список")
        краткая = advice.stale(days=90, path=self.путь, offset=15)
        self.assertEqual(краткая["next_offset"], 30)
        self.assertEqual(len(краткая["stale"]), 15)


if __name__ == "__main__":
    unittest.main()
