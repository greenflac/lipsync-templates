"""Полный план под потолком ответа: шаги не выпадают никогда, листание названо.

НАЙДЕНО валидатором 5-го круга (2026-10-15): `plan_pipeline(full=True)` —
93 тыс. знаков, общий потолок (40 000) укоротил `steps` до 0 из 5, а
подсказка листания не упоминала `plan_pipeline` вовсе.
"""

from __future__ import annotations

import json
import unittest

from studio.mcp import server as S


def _план(шагов: int = 5, длина: int = 9_000) -> dict:
    return {
        "summary": "PLAN IN SHORT",
        "outcome": "could not measure",
        "reason": "план_не_подтверждён",
        "note": "n",
        "steps": [
            {
                "step": f"шаг{i}",
                "chosen": {"model": f"m{i}", "evidence": ["x" * длина]},
                "alternatives": [{"model": f"a{i}", "why": "y" * длина}],
            }
            for i in range(шагов)
        ],
        "validator": {"steps": [{"v": "z" * длина} for _ in range(шагов)]},
        "native_audio_variant": {"alternatives": ["w" * длина]},
    }


class ШагиНеВыпадают(unittest.TestCase):
    def test_каждая_страница_несёт_все_шаги_с_моделью(self) -> None:
        план = _план()
        offset, увидено = 0, []
        for _ in range(30):
            ответ = json.loads(
                S.cap_response(
                    S.page_full_plan(json.loads(json.dumps(план)), offset), tool="plan_pipeline"
                )
            )
            self.assertEqual(
                ["m0", "m1", "m2", "m3", "m4"], [ш["chosen"]["model"] for ш in ответ["steps"]]
            )
            self.assertLessEqual(len(S._dump(ответ)), S.MAX_RESPONSE_CHARS)
            увидено += ответ["page"]["chunks_here"]
            offset = ответ["page"]["next_offset"]
            if offset is None:
                break
        self.assertEqual(
            [
                "steps[0]",
                "steps[1]",
                "steps[2]",
                "steps[3]",
                "steps[4]",
                "validator",
                "native_audio_variant",
            ],
            увидено,
        )

    def test_свёрнутое_названо(self) -> None:
        ответ = S.page_full_plan(_план(), 0)
        хвост = ответ["steps"][4]
        self.assertEqual(["alternatives"], хвост["paged"]["folded"])
        self.assertEqual(["evidence"], хвост["chosen"]["paged"]["folded"])

    def test_маленький_план_не_листается(self) -> None:
        """И5: влезающий план отдаётся как есть, без `page`."""
        маленький = _план(шагов=2, длина=100)
        self.assertEqual(маленький, S.page_full_plan(маленький, 0))

    def test_потолок_не_режет_шаги_по_счёту(self) -> None:
        ответ = json.loads(S.cap_response(_план(шагов=5, длина=12_000), tool="plan_pipeline"))
        self.assertEqual(5, len(ответ["steps"]))
        self.assertNotIn("steps", [т["field"] for т in ответ["response_cap"]["trimmed"]])

    def test_подсказка_называет_plan_pipeline_и_offset(self) -> None:
        ответ = json.loads(S.cap_response(_план(шагов=5, длина=12_000), tool="plan_pipeline"))
        self.assertTrue(
            ответ["response_cap"]["how_to_page"].startswith(
                "Ask for less or page: plan_pipeline — "
            )
        )
        self.assertIn("offset=page.next_offset", ответ["response_cap"]["how_to_page"])
        self.assertIn("plan_pipeline", S.HOW_TO_PAGE)


class ШестьШаговПодПотолком(unittest.TestCase):
    """Интеграция пятого круга: потолок 40 000 укорачивал список шагов 6-шагового
    плана вдвое. Теперь сворачиваются прочие поля и сами шаги, но не их счёт."""

    def _шесть(self, длина: int = 9_000) -> dict:
        план = _план(шагов=6, длина=длина)
        план["validator"] = {"steps": [{"v": "z" * 1_000} for _ in range(6)]}
        return план

    def test_краткий_вид_шесть_шагов_свёрнуты_не_выброшены(self) -> None:
        ответ = json.loads(S.cap_response(self._шесть(), tool="plan_pipeline"))
        self.assertLessEqual(len(S._dump(ответ)), S.MAX_RESPONSE_CHARS)
        self.assertEqual(
            [f"m{i}" for i in range(6)], [ш["chosen"]["model"] for ш in ответ["steps"]]
        )
        поля = [т["field"] for т in ответ["response_cap"]["trimmed"]]
        self.assertIn("steps.*", поля)
        self.assertNotIn("steps", поля)
        self.assertNotIn("*", поля)
        # Вердикт по каждому шагу тоже не укорачивается по счёту.
        self.assertEqual(6, len(ответ["validator"]["steps"]))
        self.assertIn("steps.* (6 of 6)", ответ["note"])

    def test_полный_вид_каждая_страница_шесть_шагов(self) -> None:
        план = self._шесть()
        offset = 0
        for _ in range(40):
            ответ = json.loads(
                S.cap_response(
                    S.page_full_plan(json.loads(json.dumps(план)), offset), tool="plan_pipeline"
                )
            )
            self.assertEqual(6, len(ответ["steps"]))
            self.assertLessEqual(len(S._dump(ответ)), S.MAX_RESPONSE_CHARS)
            for т in (ответ.get("response_cap") or {}).get("trimmed", []):
                self.assertNotIn(т["field"], ("steps", "validator.steps", "*"))
            offset = ответ["page"]["next_offset"]
            if offset is None:
                break
        self.assertIsNone(offset)

    def test_живой_план_шести_шагов(self) -> None:
        бриф = (
            "40s 9:16 1080x1920 ad with two consistent realistic fighters, English VO with "
            "lipsync and background music, budget $15"
        )
        for full in (False, True):
            ответ = json.loads(S.план_по_тексту(бриф, full=full))
            self.assertLessEqual(len(S._dump(ответ)), S.MAX_RESPONSE_CHARS)
            self.assertEqual(6, len(ответ["steps"]), full)
            self.assertTrue(all((ш.get("chosen") or {}).get("model") for ш in ответ["steps"]))


if __name__ == "__main__":
    unittest.main()
