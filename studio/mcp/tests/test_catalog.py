"""Схема каталога и вердикт по записи. Ожидаемое — литералами (правило Т2).

Сети здесь нет вообще: `classify` и `validate` не ходят никуда, а опрос
проверяется в test_catalog_gate.py через подставленный `get` (правило Т4).

Что эти тесты сторожат: НЕ «подсадные отсекаются» — это половина прибора.
Вторая половина, за которой гейт легко теряет смысл, — здоровая запись обязана
пройти. Гейт, отсекающий всё, проходит проверку «подсадные не доехали» на
отлично и не измеряет ничего (правило И5).
"""

from __future__ import annotations

import unittest

from studio.mcp import catalog


def healthy() -> dict:
    """Живой генератор видео из ответа deepinfra 2026-08-31, сокращённый."""
    return {
        "catalog": "deepinfra",
        "name": "Wan-AI/Wan2.6-T2V",
        "polled_on": "2026-08-31",
        "declared_type": "text-to-video",
        "prices": [{"amount": 0.04, "unit": "usd_per_second", "condition": "output second"}],
        "deprecated": False,
    }


class Schema(unittest.TestCase):
    def test_healthy_record_has_no_problems(self) -> None:
        self.assertEqual(catalog.validate(healthy()), [])

    def test_missing_required_field_is_named(self) -> None:
        record = healthy()
        del record["polled_on"]
        self.assertIn("нет обязательного поля polled_on", catalog.validate(record))

    def test_field_outside_the_schema_is_refused(self) -> None:
        # Схема закрытая нарочно: `description` у обеих площадок — чужая проза,
        # а репозиторий публичный. Поля, куда её положить, здесь нет.
        record = healthy()
        record["description"] = "Wan 2.6 is a state-of-the-art video model that..."
        self.assertEqual(catalog.validate(record), ["поля вне схемы: description"])

    def test_price_is_three_fields_and_the_unit_is_checked(self) -> None:
        record = healthy()
        record["prices"] = [{"amount": 0.04, "unit": "центы за секунду", "condition": "sec"}]
        self.assertEqual(
            catalog.validate(record), ["prices[0]: единица 'центы за секунду' вне списка"]
        )

    def test_price_amount_must_be_a_number_not_prose(self) -> None:
        # Ровно то, ради чего каталог отделён от базы фактов: в базе цены лежат
        # прозой и их нельзя сложить. Здесь строка — дефект записи.
        record = healthy()
        record["prices"] = [{"amount": "$0.04", "unit": "usd_per_second", "condition": "sec"}]
        self.assertEqual(catalog.validate(record), ["prices[0]: amount не число"])

    def test_successor_without_the_marketplace_name_is_refused(self) -> None:
        # Правило П4. Пара Llama-3.2-1B -> gemma-4-31B ведёт через ЧУЖОГО
        # вендора: это рекомендация продавца. Без имени продавца рядом она
        # читается как заявление автора модели, чем не является.
        record = healthy()
        record["replaced_by"] = {"name": "google/gemma-4-31B-it"}
        self.assertEqual(catalog.validate(record), ["replaced_by без said_by"])

    def test_deprecated_must_be_boolean_not_a_timestamp(self) -> None:
        record = healthy()
        record["deprecated"] = 1778120282
        self.assertEqual(catalog.validate(record), ["deprecated не булев"])


class Verdict(unittest.TestCase):
    def test_healthy_generator_passes(self) -> None:
        """ОБРАТНЫЙ КОНТРОЛЬ (И5): без этого теста гейт может отсекать всё."""
        self.assertEqual(catalog.classify(healthy())["verdict"], "повод прочитать")

    def test_named_router_is_refused(self) -> None:
        record = healthy()
        record["catalog"], record["name"] = "openrouter", "openrouter/auto"
        got = catalog.classify(record)
        self.assertEqual((got["verdict"], got["rule"]), ("не модель", "router"))

    def test_router_beta_is_refused_too(self) -> None:
        record = healthy()
        record["catalog"], record["name"] = "openrouter", "openrouter/auto-beta"
        self.assertEqual(catalog.classify(record)["rule"], "router")

    def test_negative_price_is_a_marker_not_a_price(self) -> None:
        # ИЗМЕРЕНО 2026-08-31: цена prompt "-1" стоит у пяти записей openrouter,
        # из которых по имени известны две. Правило ловит класс, а не список.
        record = healthy()
        record["name"] = "openrouter/fusion"
        record["prices"] = [{"amount": -1.0, "unit": "usd_per_token", "condition": "prompt"}]
        self.assertEqual(catalog.classify(record)["rule"], "router")

    def test_deprecated_record_is_refused(self) -> None:
        record = healthy()
        record["deprecated"] = True
        record["deprecated_on"] = "2026-05-03"
        got = catalog.classify(record)
        self.assertEqual((got["verdict"], got["rule"]), ("не модель", "deprecated"))
        self.assertIn("2026-05-03", got["why"])

    def test_every_bria_editing_operation_is_refused(self) -> None:
        # Шесть имён из живого среза, все помечены площадкой как text-to-video.
        for name in (
            "Bria/video_mask_by_prompt",
            "Bria/video_eraser",
            "Bria/video_remove_background",
            "Bria/video_increase_resolution",
            "Bria/video_mask_by_key_points",
            "Bria/video_foreground_mask",
        ):
            with self.subTest(name=name):
                record = healthy()
                record["name"] = name
                self.assertEqual(catalog.classify(record)["rule"], "edit_op")

    def test_editing_verb_outside_a_generator_type_is_not_judged_by_this_rule(self) -> None:
        # Негативный контроль правила edit_op: оно спрашивает «генератор ли
        # это» только там, где площадка сказала «генератор». Модель распознавания
        # с тем же словом в имени — не подсадная и проходит.
        record = healthy()
        record["name"], record["declared_type"] = "acme/foreground_mask_detector", "embeddings"
        self.assertEqual(catalog.classify(record)["verdict"], "повод прочитать")

    def test_forever_date_dressed_as_a_date_is_refused(self) -> None:
        record = healthy()
        record["expiration_date"] = "2098-12-31"
        got = catalog.classify(record)
        self.assertEqual((got["verdict"], got["rule"]), ("не модель", "forever_date"))

    def test_a_real_retirement_date_passes(self) -> None:
        """ОБРАТНЫЙ КОНТРОЛЬ: 2 из 6 дат у openrouter настоящие и обязаны жить."""
        for real in ("2026-09-30", "2026-12-31"):
            with self.subTest(date=real):
                record = healthy()
                record["expiration_date"] = real
                self.assertEqual(catalog.classify(record)["verdict"], "повод прочитать")

    def test_unreadable_record_is_the_third_outcome(self) -> None:
        record = healthy()
        record["expiration_date"] = "бессрочно"
        got = catalog.classify(record)
        self.assertEqual(got["verdict"], "не смогли")

    def test_three_verdicts_are_three_distinct_strings(self) -> None:
        self.assertEqual(
            sorted({catalog.ADMIT, catalog.REJECT, catalog.UNJUDGEABLE}),
            ["не модель", "не смогли", "повод прочитать"],
        )


class ControlSet(unittest.TestCase):
    def test_the_control_set_agrees_with_the_instrument(self) -> None:
        report = catalog.control_report()
        self.assertEqual((report["outcome"], report["violations"]), ("pass", 0))
        self.assertEqual(report["checked"], 9)

    def test_the_control_set_exercises_every_rejection_rule(self) -> None:
        rules = {rule for _, verdict, rule, _ in catalog.CONTROL_SET if verdict == catalog.REJECT}
        self.assertEqual(sorted(rules), ["deprecated", "edit_op", "forever_date", "router"])

    def test_the_control_set_contains_records_that_must_pass(self) -> None:
        admitted = [row for row, verdict, _, _ in catalog.CONTROL_SET if verdict == catalog.ADMIT]
        self.assertEqual(len(admitted), 2)


if __name__ == "__main__":
    unittest.main()
