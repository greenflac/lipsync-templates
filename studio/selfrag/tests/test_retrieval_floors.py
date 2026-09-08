"""Два пола ретривера: чем он вправе ответить и что вправе усилить.

ЗАЧЕМ. `studio/selfrag/retrieval.py` решает по двум константам, и ни одну из
них не сторожил ни один мутант: `scripts/check_mutants_cover.py` числил модуль
в «без мутантов».

* `MIN_TERM_HITS` — сколько РАЗЛИЧАЮЩИХ терминов запроса должна нести запись,
  чтобы вообще попасть в выдачу. Опусти его до единицы, и ретривер перестанет
  уметь говорить «здесь ничего нет»: у любого вопроса найдётся запись с одним
  общим словом. Ретривер, который всегда отвечает, ничего не измеряет — и
  негативный контроль оценщика (`ABSTENTION_FLOOR`) молча станет проходимым
  не потому, что поиск хорош.
* `RATING_PRIOR_FLOOR` — с какой оценки запись едет на канале рейтинга.
  Опусти его, и середина шкалы начнёт усиливать сама себя; подними — и
  канал опустеет, а выдача станет одноканальной, чего никто не заметит,
  потому что записи всё равно находятся.

Ожидаемые числа — литералы (Т2). Проверяется обе стороны каждой границы (Т1):
значение НА полу работает, значение под полом — нет.
"""

from __future__ import annotations

import unittest

from lipsync.fork_identity import FAIL, PASS
from studio.selfrag.corpus import CorpusRecord
from studio.selfrag.retrieval import build_corpus_index, search


class ПолДопуска(unittest.TestCase):
    """`MIN_TERM_HITS`: одного общего слова мало, двух — достаточно."""

    def setUp(self) -> None:
        self.idx = build_corpus_index(
            [
                CorpusRecord("r1", "crimson neon alley hazy texture mysterious mood"),
                CorpusRecord("r2", "emerald forest floor low-key light serene mood"),
                CorpusRecord("r3", "slate corridor fluorescent flicker uneasy mood"),
            ]
        )
        self.addCleanup(self.idx.close)

    def test_два_различающих_термина_находят(self) -> None:
        out = search("crimson alley", index=self.idx, widened=True)
        self.assertEqual(out["outcome"], PASS)
        self.assertEqual([h.record.record_id for h in out["hits"]], ["r1"])
        self.assertEqual(out["hits"][0].term_hits, 2)

    def test_одного_термина_мало_и_это_отказ_а_не_выдача(self) -> None:
        """Расширенный запрос с одним словом обязан вернуть пусто.

        `widened=True` снимает поблажку для короткого запроса, который человек
        набрал сам: здесь проверяется именно пол допуска, а не поблажка.
        """
        out = search("crimson", index=self.idx, widened=True)
        self.assertEqual(out["outcome"], FAIL)
        self.assertEqual(out["hits"], [])


class ПолРейтинга(unittest.TestCase):
    """`RATING_PRIOR_FLOOR`: шестёрка едет на канале рейтинга, пятёрка — нет."""

    def setUp(self) -> None:
        self.idx = build_corpus_index(
            [
                CorpusRecord("шесть", "crimson neon alley hazy texture", rating=6),
                CorpusRecord("пять", "crimson neon alley misty texture", rating=5),
            ]
        )
        self.addCleanup(self.idx.close)

    def test_на_полу_едет_под_полом_не_едет(self) -> None:
        out = search("crimson alley", index=self.idx, widened=True)
        каналы = {h.record.record_id: h.channels for h in out["hits"]}
        self.assertIn("rating", каналы["шесть"])
        self.assertNotIn("rating", каналы["пять"])

    def test_обе_записи_всё_равно_найдены(self) -> None:
        """Негативный контроль к предыдущему (И5): пол рейтинга РАНЖИРУЕТ, а не
        выбрасывает. Если бы пятёрка исчезала из выдачи, предыдущий тест
        краснел бы по другой причине, чем думает его название."""
        out = search("crimson alley", index=self.idx, widened=True)
        self.assertEqual(sorted(h.record.record_id for h in out["hits"]), ["пять", "шесть"])


if __name__ == "__main__":
    unittest.main()
