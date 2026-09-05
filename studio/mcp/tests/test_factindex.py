"""Поиск фактов словами задачи: находит ли он нужное и молчит ли на чужом.

Ожидаемое — литералы (Т2). Сети нет (Т4): все факты подаются в конструктор.
"""

from __future__ import annotations

import unittest

from studio.factindex import DEFAULT_K, SCORE_FLOOR, FactIndex, haystack, tokens, verdict
from studio.selfrag.facts import Fact


def факт(model, attribute="architecture", value="", note="", tier="vendor"):
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url="https://example.test/x",
        tier=tier,
        stated_on="2026-08-31",
        note=note,
    )


КОРПУС = [
    факт(
        "wan-animate-replace",
        "architecture",
        "replaces the character in a reference video, keeping the scene lighting and color tone",
    ),
    факт("kling-3.0", "max_seconds", "10 seconds per generation"),
    факт("elevenlabs-v3", "voice_clone", "clones a voice from thirty seconds of audio"),
    факт("*", "metric_blind_spot", "FVD barely moves under large temporal corruption"),
]


class Tokens(unittest.TestCase):
    def test_a_term_keeps_its_dots_and_dashes(self):
        """`wan-2.2` и `max_seconds` — термины; разбить их значит потерять ключ."""
        self.assertIn("wan-2.2", tokens("сколько секунд у wan-2.2"))
        self.assertIn("max_seconds", tokens("max_seconds limit"))

    def test_service_words_are_dropped_in_both_languages(self):
        self.assertEqual(tokens("и в на the of"), [])

    def test_an_empty_text_yields_nothing(self):
        self.assertEqual(tokens(""), [])


class Haystack(unittest.TestCase):
    def test_the_model_name_is_searchable_too(self):
        """Спрашивают и словами, и именем; второе не должно перестать работать."""
        self.assertIn("kling-3.0", haystack(факт("kling-3.0", "max_seconds", "10")))

    def test_the_attribute_reads_as_words(self):
        self.assertIn("max seconds", haystack(факт("a", "max_seconds", "10")))


class Search(unittest.TestCase):
    def indexed(self):
        return FactIndex(КОРПУС)

    def test_the_task_words_find_the_right_fact(self):
        """Это ровно бриф владельца: заменить персонажа, сохранив цветокор."""
        hits = self.indexed().search("replace a character keeping lighting and color tone")
        self.assertEqual(hits[0].fact.model, "wan-animate-replace")

    def test_an_unrelated_task_finds_nothing(self):
        """Негативный контроль: прибор обязан уметь молчать."""
        self.assertEqual(self.indexed().search("бухгалтерский учёт основных средств"), [])

    def test_a_model_name_still_finds_its_facts(self):
        hits = self.indexed().search("kling-3.0")
        self.assertEqual(hits[0].fact.model, "kling-3.0")

    def test_matched_words_are_reported(self):
        """Читателю видно, ЧЕМ найдено, иначе счёт нечем проверить."""
        hits = self.indexed().search("voice clone")
        self.assertIn("clone", hits[0].matched)

    def test_k_limits_the_answer(self):
        hits = self.indexed().search("video character color seconds voice", k=2)
        self.assertLessEqual(len(hits), 2)

    def test_a_rare_word_outweighs_a_common_one(self):
        """Редкое слово решает, а частое — нет.

        Фикстура построена так, что без веса редкости побеждает НЕ тот факт:
        слово `video` есть у всех четырёх, слово `chroma` — у одного. Первая
        редакция теста этого не различала, и выключение веса проходило молча.
        """
        корпус = [
            факт("частый", "note", "video generation quality speed"),
            факт("шум1", "note", "video editing tool"),
            факт("шум2", "note", "video sound track"),
            факт(
                "редкий",
                "note",
                "chroma subsampling preserved across encoder decoder stage output pipeline",
            ),
        ]
        hits = FactIndex(корпус).search("video chroma")
        self.assertEqual(hits[0].fact.model, "редкий")


class Verdict(unittest.TestCase):
    def test_an_empty_result_is_the_third_outcome(self):
        """Прецедент: retrieve() отдавал `pass` при нуле примеров, а честная
        нота лежала строкой ниже. Поле вердикта читают, ноту — нет."""
        v = verdict([], "бухучёт")
        self.assertEqual(v["outcome"], "could not measure")
        self.assertEqual(v["checked"], 0)
        self.assertEqual(v["unmeasured"], 1)

    def test_an_empty_question_is_could_not_measure_too(self):
        self.assertEqual(verdict([], "")["outcome"], "could not measure")

    def test_a_found_fact_carries_its_tier_and_date(self):
        hits = FactIndex(КОРПУС).search("color tone lighting")
        v = verdict(hits, "color tone lighting")
        self.assertEqual(v["outcome"], "pass")
        self.assertEqual(v["hits"][0]["tier"], "vendor")
        self.assertEqual(v["hits"][0]["stated_on"], "2026-08-31")


class Thresholds(unittest.TestCase):
    def test_the_floor_is_a_real_number_not_zero(self):
        """Порог ноль означал бы, что совпадение одним частым словом — попадание."""
        self.assertGreater(SCORE_FLOOR, 0)

    def test_the_default_answer_fits_a_screen(self):
        self.assertLessEqual(DEFAULT_K, 12)

    def test_raising_the_floor_silences_a_weak_match(self):
        """Сторож порога: при высоком поле даже настоящее совпадение отсекается."""
        строгий = FactIndex(КОРПУС).search("character", floor=99.0)
        self.assertEqual(строгий, [])


if __name__ == "__main__":
    unittest.main()
