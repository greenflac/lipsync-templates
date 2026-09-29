"""Пороги оценки поиска обязаны КУСАТЬСЯ, а не просто существовать.

ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ. `scripts/mutate_channels.py` подменял в
`studio/selfrag/evaluate.py` два числа — `RECALL_FLOOR = 0.75 -> 0.0` и
`ABSTENTION_FLOOR = 1.0 -> 0.0` — и набор МОЛЧАЛ на обоих (прогон 2026-09-04,
«мутантов 214, промолчали на 2»). Существующие проверки оценщика смотрят на
вход, где ретривер отвечает идеально: там пол не участвует в решении вовсе,
потому и опустить его можно было незаметно. Здесь входы подобраны так, что
ответ прибора решается ИМЕННО порогом (Т3: край и середина, а не одна точка).

Ожидаемые числа — литералы (Т2). Импортировать `RECALL_FLOOR` сюда нельзя:
такое ожидание переедет вместе с константой и промолчит ровно в том случае,
ради которого файл написан.
"""

from __future__ import annotations

import unittest

from lipsync.fork_identity import FAIL, PASS
from studio.selfrag.corpus import CorpusRecord
from studio.selfrag.retrieval import build_corpus_index


def _индекс(случай: unittest.TestCase):
    idx = build_corpus_index(
        [
            CorpusRecord(
                "r1",
                "crimson neon alley, hazy texture, mysterious mood",
                model="kling-3.0",
                tags=("neon",),
                rating=8,
            ),
            CorpusRecord(
                "r2",
                "emerald forest floor, low-key light, serene mood",
                model="veo-3.1",
                tags=("forest",),
                rating=9,
            ),
        ]
    )
    случай.addCleanup(idx.close)
    return idx


#: Негативный контроль, на который корпус обязан промолчать (И5).
МОЛЧАЛИВЫЙ = {
    "id": "n1",
    "query": "kubernetes ingress certificate rotation",
    "expect": "abstain",
    "must_retrieve": [],
}


class ПолПолноты(unittest.TestCase):
    """`RECALL_FLOOR`. Опустить его до нуля обязано покраснеть здесь."""

    def test_половина_найденного_ниже_пола_и_это_отказ(self) -> None:
        from studio.selfrag.evaluate import evaluate

        gold = [
            {
                "id": "p1",
                "query": "crimson neon alley",
                "expect": "hit",
                # Второй оборот в корпусе не встречается ни в одной записи:
                # полнота этого запроса ровно 0.5, и это ВЫБРАНО, а не совпало.
                "must_retrieve": ["crimson", "chartreuse aurora"],
            },
            {
                "id": "p2",
                "query": "emerald forest floor",
                "expect": "hit",
                "must_retrieve": ["emerald", "chartreuse aurora"],
            },
            МОЛЧАЛИВЫЙ,
        ]
        out = evaluate(_индекс(self), gold)
        self.assertEqual(out["recall_at_k"], 0.5)
        self.assertEqual(out["abstention_rate"], 1.0)
        self.assertEqual(out["outcome"], FAIL)
        self.assertIn("recall", out["note"])

    def test_ровно_на_полу_ещё_проходит(self) -> None:
        """Другая сторона мутации (Т1): поднять пол выше 0.75 — и это покраснеет.

        Вход подобран на САМ ПОРОГ: полнота 1.0 у одного запроса и 0.5 у
        другого дают ровно 0.75. Набор из одних идеальных запросов эту сторону
        не сторожит — он проходит и при поле 0.99, то есть молчит на мутации,
        ради которой пол и написан.
        """
        from studio.selfrag.evaluate import evaluate

        gold = [
            {
                "id": "p1",
                "query": "crimson neon alley",
                "expect": "hit",
                "must_retrieve": ["crimson", "neon"],
            },
            {
                "id": "p2",
                "query": "emerald forest floor",
                "expect": "hit",
                "must_retrieve": ["emerald", "chartreuse aurora"],
            },
            МОЛЧАЛИВЫЙ,
        ]
        out = evaluate(_индекс(self), gold)
        self.assertEqual(out["recall_at_k"], 0.75)
        self.assertEqual(out["abstention_rate"], 1.0)
        self.assertEqual(out["outcome"], PASS)


class ПолМолчания(unittest.TestCase):
    """`ABSTENTION_FLOOR`. Ответ на неотвечаемый вопрос — отказ, а не мелочь."""

    def test_ответ_на_негативный_контроль_это_отказ(self) -> None:
        from studio.selfrag.evaluate import evaluate

        gold = [
            {
                "id": "p1",
                "query": "crimson neon alley",
                "expect": "hit",
                "must_retrieve": ["crimson", "neon"],
            },
            # Контроль, который корпус отвечает: это ровно тот случай, из-за
            # которого пол молчания стоит на 1.0.
            {
                "id": "n_ответит",
                "query": "emerald forest floor low-key light",
                "expect": "abstain",
                "must_retrieve": [],
            },
        ]
        out = evaluate(_индекс(self), gold)
        self.assertEqual(out["recall_at_k"], 1.0)
        self.assertEqual(out["abstention_rate"], 0.0)
        self.assertEqual(out["outcome"], FAIL)
        self.assertIn("unanswerable", out["note"])


if __name__ == "__main__":
    unittest.main()
