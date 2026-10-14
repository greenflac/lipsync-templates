"""Слой имён моделей и `model_advice` — аудит ae94057 (2026-10-14), пункты 2–7, 9.

Каждый тест на своей ВРЕМЕННОЙ базе (Т5): производственный
`studio/knowledge/model_facts.jsonl` не читается и не пишется. Ожидаемые
значения — литералы (Т2), сети нет (Т4), у каждого правила обе стороны (И5).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

from studio.mcp import advice


def строка(model: str, attribute: str, value: str, url: str, tier: str = "vendor") -> dict:
    return {
        "model": model,
        "attribute": attribute,
        "value": value,
        "source_url": url,
        "tier": tier,
        "stated_on": "2026-10-01",
    }


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

    def строки_файла(self) -> list[dict]:
        return [
            json.loads(x) for x in self.путь.read_text(encoding="utf-8").splitlines() if x.strip()
        ]


class П2_КаноническоеИмяНаЗаписи(База):
    def test_написание_известной_модели_пишется_под_каноническим(self) -> None:
        self.база(строка("seedance-2.0", "max_seconds", "15", "https://seed.bytedance.com/a"))
        got = advice.record(
            "seedance2", "fps", "24", "https://example.org/p", "blog", "2026-10-01", path=self.путь
        )
        self.assertEqual(got["outcome"], "pass")
        последняя = self.строки_файла()[-1]
        self.assertEqual(последняя["model"], "seedance-2.0")
        self.assertEqual(последняя["asked_as"], "seedance2")
        self.assertIn("записано под каноническим id 'seedance-2.0'", got["note"])

    def test_каноническое_написание_не_получает_asked_as(self) -> None:
        """И5: поле не пишется, когда переименовывать нечего."""
        self.база(строка("seedance-2.0", "max_seconds", "15", "https://seed.bytedance.com/a"))
        advice.record(
            "seedance-2.0",
            "fps",
            "24",
            "https://example.org/p",
            "blog",
            "2026-10-01",
            path=self.путь,
        )
        self.assertNotIn("asked_as", self.строки_файла()[-1])

    def test_сосед_по_выводу_отказ_с_указателем(self) -> None:
        self.база(строка("happyhorse_1_0", "max_seconds", "15", "https://example.org/a", "blog"))
        до = self.путь.read_bytes()
        got = advice.record(
            "happyhorse", "fps", "24", "https://example.org/p", "blog", "2026-10-01", path=self.путь
        )
        self.assertEqual(got["outcome"], "fail")
        self.assertIn("'happyhorse_1_0'", got["note"])
        self.assertIn("new_model=True", got["note"])
        self.assertEqual(self.путь.read_bytes(), до, "отказ ничего не пишет")

    def test_new_model_выход_для_настоящей_новой_модели(self) -> None:
        self.база(строка("happyhorse_1_0", "max_seconds", "15", "https://example.org/a", "blog"))
        got = advice.record(
            "happyhorse",
            "fps",
            "24",
            "https://example.org/p",
            "blog",
            "2026-10-01",
            new_model=True,
            path=self.путь,
        )
        self.assertEqual(got["outcome"], "pass")
        self.assertEqual(self.строки_файла()[-1]["model"], "happyhorse")

    def test_незнакомое_имя_пишется_как_названо(self) -> None:
        self.база(строка("kling-3.0", "max_seconds", "15", "https://example.org/a", "blog"))
        advice.record(
            "brand-new-x",
            "fps",
            "24",
            "https://example.org/p",
            "blog",
            "2026-10-01",
            path=self.путь,
        )
        self.assertEqual(self.строки_файла()[-1]["model"], "brand-new-x")

    def test_область_не_разрешается(self) -> None:
        self.assertEqual(advice.каноническое_имя("eleven-*", self.база()), ("eleven-*", ""))


class П3_Семьи(База):
    def семья(self) -> Path:
        return self.база(
            строка("veo-3.1", "price_per_second", "$0.08/s Lite 1080p", "https://ai.google.dev/a"),
            строка("veo-3.1", "max_seconds", "8", "https://ai.google.dev/b"),
            строка("veo-3.1-lite", "resolution_options", "720p, 1080p", "https://ai.google.dev/c"),
            строка("veo-3.1-fast", "max_seconds", "8", "https://ai.google.dev/d"),
            строка("veo-3", "max_seconds", "8", "https://deepmind.google/veo"),
        )

    def test_семья_показывает_варианты_с_пометкой(self) -> None:
        got = advice.advise("veo-3.1", path=self.семья())
        self.assertEqual(got["family"]["role"], "family")
        self.assertEqual(got["family"]["variants"], ["veo-3.1-fast", "veo-3.1-lite"])
        self.assertEqual(
            sorted(got["family_claims"]),
            ["max_seconds@veo-3.1-fast", "resolution_options@veo-3.1-lite"],
        )
        self.assertEqual(got["family_claims"]["max_seconds@veo-3.1-fast"]["scope"], "variant")
        self.assertEqual(got["family_claims"]["max_seconds@veo-3.1-fast"]["about"], "veo-3.1-fast")
        # Свои утверждения — только о самой модели.
        self.assertEqual(sorted(got["claims"]), ["max_seconds", "price_per_second"])

    def test_вариант_отвечает_с_уровня_семьи_и_говорит_это(self) -> None:
        got = advice.advise("veo-3.1-lite", "price", path=self.семья())
        self.assertEqual(got["outcome"], "pass")
        self.assertEqual(got["reason"], "answered_by_family")
        self.assertEqual(list(got["family_claims"]), ["price_per_second@veo-3.1"])
        self.assertEqual(got["family_claims"]["price_per_second@veo-3.1"]["scope"], "family")
        self.assertIn("НЕ измерение спрошенной модели", got["note"])
        # Ответ стоит на утверждениях семьи — они и в `claims`, помеченные;
        # своя пустая попытка — в `own_claims`.
        self.assertEqual(list(got["claims"]), ["price_per_second@veo-3.1"])
        self.assertEqual(
            got["claims"]["price_per_second@veo-3.1"]["values"], ["$0.08/s Lite 1080p"]
        )
        self.assertEqual(got["own_claims"]["price"]["checked"], 0)

    def test_другая_версия_не_семья(self) -> None:
        """И5: veo-3 и veo-3.1 — разные модели."""
        got = advice.advise("veo-3", path=self.семья())
        self.assertEqual(got["family"], {})
        self.assertEqual(got["family_claims"], {})
        self.assertEqual(list(got["claims"]), ["max_seconds"])
        self.assertEqual(
            got["claims"]["max_seconds"]["claims"][0]["sources"][0]["url"],
            "https://deepmind.google/veo",
        )

    def test_незнакомый_вариант_не_получает_ответ_семьи(self) -> None:
        """И5: имени нет в базе — ответ семьи ему не приписывается."""
        got = advice.advise("veo-3.1-ultra", "price", path=self.семья())
        self.assertEqual(got["outcome"], "could not measure")
        self.assertEqual(got["family"], {})
        self.assertEqual(got["family_claims"], {})

    def test_семья_без_своих_строк_отвечает_вариантами(self) -> None:
        self.база(
            строка(
                "seedvr2-3b",
                "license",
                "apache-2.0",
                "https://huggingface.co/ByteDance-Seed/SeedVR2-3B",
            ),
            строка(
                "seedvr2-7b",
                "license",
                "apache-2.0",
                "https://huggingface.co/ByteDance-Seed/SeedVR2-7B",
            ),
            строка("seed_audio", "price", "1", "https://example.org/x", "blog"),
        )
        got = advice.advise("seedvr2", path=self.путь)
        self.assertEqual(got["reason"], "answered_by_family")
        self.assertEqual(sorted(got["family_claims"]), ["license@seedvr2-3b", "license@seedvr2-7b"])
        self.assertNotIn("seed_audio", got["near"])


class П4_РеестрИБаза(База):
    def test_псевдоним_реестра_доходит_до_базы(self) -> None:
        self.база(строка("kling-3.0", "max_seconds", "15", "https://ir.kuaishou.com/x"))
        got = advice.advise("kling", path=self.путь)
        self.assertEqual(got["outcome"], "pass")
        self.assertEqual(list(got["claims"]), ["max_seconds"])
        self.assertEqual(got["resolved_as"]["looked_up_as"], "kling-3.0")
        self.assertIn("псевдоним 'kling-3.0'", got["availability"]["note"])

    def test_написание_карточки_тоже(self) -> None:
        self.база(строка("kling-3.0", "max_seconds", "15", "https://ir.kuaishou.com/x"))
        for имя in ("kling-3", "kling-v3", "Kling 3.0"):
            got = advice.advise(имя, path=self.путь)
            self.assertEqual(list(got["claims"]), ["max_seconds"], имя)
            self.assertEqual((got["availability"]["card"] or {}).get("model_id"), "kling-3.0", имя)

    def test_veo_3_не_получает_карточку_veo_3_1(self) -> None:
        self.база(строка("veo-3", "max_seconds", "8", "https://deepmind.google/veo"))
        got = advice.advise("veo-3", path=self.путь)
        self.assertIsNone(got["availability"]["card"])
        self.assertEqual(list(got["claims"]), ["max_seconds"])

    def test_ось_реестра_не_перечисляет_семь_карточек(self) -> None:
        self.база(строка("test-model", "max_seconds", "8", "https://example.org/x"))
        нота = advice.advise("test-model", path=self.путь)["availability"]["note"]
        self.assertNotIn("Known:", нота)
        self.assertIn("NOT maintained for this one", нота)
        self.assertIn("записей о жизненном цикле", нота)


class П5_СемьяАтрибутов(База):
    def test_ценовое_имя_которого_нет_разворачивается_в_семью(self) -> None:
        self.база(строка("veo-3.1", "price_per_second", "$0.40/s", "https://ai.google.dev/a"))
        got = advice.advise("veo-3.1", "price_per_second_usd", path=self.путь)
        self.assertEqual(got["outcome"], "pass")
        self.assertEqual(list(got["claims"]), ["price_per_second"])
        self.assertIn("price_per_second_usd", got["asked_as"])

    def test_записанное_буквально_не_разворачивается(self) -> None:
        """И5: спросили ровно записанное имя — ровно оно и отвечает."""
        self.база(
            строка("veo-3.1", "price_per_second", "$0.40/s", "https://ai.google.dev/a"),
            строка("veo-3.1", "price_per_image_usd", "$1", "https://ai.google.dev/b"),
        )
        got = advice.advise("veo-3.1", "price_per_second", path=self.путь)
        self.assertEqual(list(got["claims"]), ["price_per_second"])

    def test_неизвестный_атрибут_называет_что_записано(self) -> None:
        self.база(строка("veo-3.1", "max_seconds", "8", "https://ai.google.dev/a"))
        got = advice.advise("veo-3.1", "zzz_attribute", path=self.путь)
        self.assertEqual(got["reason"], "attribute_unknown")
        self.assertIn("Recorded attributes for this model (1): max_seconds.", got["note"])


class П6_Подсказки(База):
    def test_подсказка_называет_настоящий_инструмент(self) -> None:
        got = advice.advise("zzz-nonexistent-model-q", path=self.база())
        self.assertIn("`record_model_fact`", got["note"])
        self.assertNotIn("call `record`", got["note"])

    def test_краткая_форма_называет_параметр_full(self) -> None:
        self.база(строка("veo-3.1", "max_seconds", "8", "https://ai.google.dev/a"))
        got = advice.brief("veo-3.1", path=self.путь)
        self.assertIn("full=True", got["full_answer"])
        self.assertNotIn("`brief`", got["full_answer"])

    def test_очередь_протухшего_называет_настоящий_инструмент(self) -> None:
        self.база(
            {
                **строка("veo-3.1", "max_seconds", "8", "https://example.org/a", "blog"),
                "stated_on": "2020-01-01",
            }
        )
        self.assertIn("`record_model_fact`", advice.stale(path=self.путь)["note"])


class П7_ЗаголовокОтражаетЗнание(База):
    def test_спор_по_части_не_роняет_ответ(self) -> None:
        self.база(
            строка("m", "max_seconds", "15", "https://vendor.example/a"),
            строка("m", "max_seconds", "10", "https://blog.example/b", "blog"),
            строка("m", "fps", "24", "https://vendor.example/c"),
        )
        got = advice.advise("m", path=self.путь)
        self.assertEqual(got["outcome"], "pass")
        self.assertEqual(got["reason"], "answered_some_contested")
        self.assertEqual(got["contested"], ["max_seconds"])
        # `pass` не несёт нарушений (check_headline); спор — среди unmeasured.
        self.assertEqual(got["violations"], 0)
        self.assertEqual(got["unmeasured"], 1)
        self.assertIn("ОСПОРЕНО 1 из 2: max_seconds", got["note"])

    def test_спорно_всё_спрошенное_это_fail(self) -> None:
        """И5: спросили ровно спорный атрибут — ответ на вопрос и есть спор."""
        self.база(
            строка("m", "max_seconds", "15", "https://vendor.example/a"),
            строка("m", "max_seconds", "10", "https://blog.example/b", "blog"),
            строка("m", "fps", "24", "https://vendor.example/c"),
        )
        got = advice.advise("m", "max_seconds", path=self.путь)
        self.assertEqual(got["outcome"], "fail")
        self.assertEqual(got["reason"], "sources_disagree")

    def test_спорен_сам_спрошенный_атрибут_это_fail_даже_при_отвеченных_соседях(self) -> None:
        """`kling-3.0.max_seconds`: семья атрибутов развернула вопрос, сосед
        отвечен, но спрошенное буквально — спорно. Это и есть ответ."""
        self.база(
            строка("m", "max_seconds", "15", "https://vendor.example/a"),
            строка("m", "max_seconds", "10", "https://blog.example/b", "blog"),
            строка("m", "duration_enum", "5, 10, 15", "https://vendor.example/c"),
        )
        got = advice.advise("m", "max_seconds", path=self.путь)
        self.assertIn("duration_enum", got["claims"], "семья развернулась — иначе тест не о том")
        self.assertEqual(got["outcome"], "fail")
        self.assertEqual(got["reason"], "sources_disagree")

    def test_площадка_против_вендора_не_спор(self) -> None:
        self.база(
            строка("m", "max_resolution", "4k", "https://vendor.example/a"),
            строка(
                "m", "max_resolution", "1080p", "https://reseller.example/openapi.json", "portal"
            ),
        )
        got = advice.advise("m", path=self.путь)
        self.assertEqual(got["outcome"], "pass")
        self.assertEqual(got["reason"], "answered")
        self.assertEqual(got["contested"], [])
        self.assertEqual(
            got["claims"]["max_resolution"]["scoped_elsewhere"][0]["venue"], "reseller.example"
        )

    def test_ноль_проверок_не_проходит(self) -> None:
        """Р1: ничего не записано — не `pass` при любой новой развилке."""
        got = advice.advise("m", path=self.база())
        self.assertEqual(got["outcome"], "could not measure")
        self.assertEqual(got["checked"], 0)


class ИмяПоСоседу(База):
    def test_ответ_по_соседу_подсказка_а_не_факт(self) -> None:
        """Голден g15: подсказкой можно, фактом — нет."""
        self.база(строка("minimax-h3-max", "max_seconds", "15", "https://platform.minimax.io/x"))
        got = advice.advise("h3-max", path=self.путь)
        self.assertEqual(got["outcome"], "could not measure")
        self.assertEqual(got["reason"], "name_maybe_mistyped")
        self.assertEqual(got["inferred_answer_outcome"], "pass")
        self.assertEqual(list(got["claims"]), ["max_seconds"])
        self.assertEqual(got["near"], ["minimax-h3-max"])

    def test_точное_написание_остаётся_фактом(self) -> None:
        """И5: та же модель под своим именем — `pass`."""
        self.база(строка("minimax-h3-max", "max_seconds", "15", "https://platform.minimax.io/x"))
        self.assertEqual(advice.advise("minimax-h3-max", path=self.путь)["outcome"], "pass")


class П9_ОчередьПротухшего(База):
    def старая_база(self, n: int) -> Path:
        return self.база(
            *[
                {
                    **строка(f"m{i % 3}", f"a{i}", "1", f"https://example.org/{i}", "blog"),
                    "stated_on": "2020-01-01",
                }
                for i in range(n)
            ]
        )

    def test_отрицательные_дни_отказ(self) -> None:
        got = advice.stale(days=-5, path=self.старая_база(2))
        self.assertEqual(got["outcome"], "fail")
        self.assertEqual(got["checked"], 0)

    def test_не_целые_дни_отказ(self) -> None:
        плохие: tuple[Any, ...] = (1.5, "30", True)  # нарочно не int: агент шлёт JSON
        for плохое in плохие:
            self.assertEqual(advice.stale(days=плохое, path=self.старая_база(2))["outcome"], "fail")

    def test_ноль_дней_законен(self) -> None:
        self.assertEqual(advice.stale(days=0, path=self.старая_база(2))["outcome"], "fail")
        self.assertEqual(advice.stale(days=0, path=self.старая_база(2))["violations"], 2)

    def test_краткая_форма_по_умолчанию(self) -> None:
        got = advice.stale(path=self.старая_база(40))
        self.assertEqual(got["counts"]["stale"], 40)
        self.assertEqual(len(got["stale"]), 15)
        self.assertTrue(got["truncated"])
        self.assertEqual(got["by_model"], {"m0": 14, "m1": 13, "m2": 13})
        self.assertEqual(got["violations"], 40, "счёт — целиком, режется только список")

    def test_полная_форма_по_просьбе(self) -> None:
        got = advice.stale(path=self.старая_база(40), full=True)
        self.assertEqual(len(got["stale"]), 40)
        self.assertNotIn("truncated", got)

    def test_фильтр_по_модели_по_любому_написанию(self) -> None:
        self.база(
            {
                **строка("seedance-2.0", "a", "1", "https://example.org/1", "blog"),
                "stated_on": "2020-01-01",
            },
            {
                **строка("kling-3.0", "a", "1", "https://example.org/2", "blog"),
                "stated_on": "2020-01-01",
            },
        )
        got = advice.stale(path=self.путь, model="seedance2")
        self.assertEqual(got["counts"]["stale"], 1)
        self.assertEqual(got["stale"][0]["model"], "seedance-2.0")

    def test_неизвестная_модель_третий_исход(self) -> None:
        got = advice.stale(path=self.старая_база(2), model="zzz-q")
        self.assertEqual(got["outcome"], "could not measure")


if __name__ == "__main__":
    unittest.main()
