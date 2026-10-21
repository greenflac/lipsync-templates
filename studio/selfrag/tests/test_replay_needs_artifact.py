"""Заявка без артефакта не поднимает запись в выдаче.

ВОСПРОИЗВЕДЕНО 2026-09-05 независимым аудитом:

    record(rating=10, artifact='')  -> outcome 'could not measure'
        «nobody can open what this produced, so the rating is a claim
         rather than an observation»
    tally  -> {'r1': (1, 0, 0)}      # засчитано в ХОРОШИЕ
    boost  -> 1.2                    # +20% к рангу
    stats  -> good 1, with_artifact 0

Код сам объявляет запись непроверяемой и тут же конвертирует её в приоритет.
Это прямая дорога для необоснованности: достаточно поставить десятку без
единого файла, и запись поедет вверх в каждой следующей выдаче.

Ранжирование обязано считать ТОЛЬКО наблюдения. Запись при этом не выкидывается
из журнала: она была сделана, и `stats` про неё говорит — но веса ей не даётся.

Числа-ожидания записаны литералами (Т2).
"""

from __future__ import annotations

import unittest

from studio.selfrag.corpus import CorpusRecord
from studio.selfrag.replay import ReplayBuffer

БЕЗ_ВЕСА = 1.0


def _буфер() -> ReplayBuffer:
    return ReplayBuffer(path=":memory:")


class ВесТолькоЗаНаблюдение(unittest.TestCase):
    def test_десятка_без_артефакта_не_даёт_веса(self) -> None:
        буфер = _буфер()
        итог = буфер.record(
            record_id="r1", prompt="p", model="veo", rating=10, outcome="pass", artifact=""
        )
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(буфер.boost()(CorpusRecord("r1", "p")), БЕЗ_ВЕСА)

    def test_единица_без_артефакта_тоже_не_даёт_веса(self) -> None:
        """Обе стороны (Т1): непроверяемое не должно и топить."""
        буфер = _буфер()
        буфер.record(record_id="r1", prompt="p", model="veo", rating=1, outcome="fail", artifact="")
        self.assertEqual(буфер.boost()(CorpusRecord("r1", "p")), БЕЗ_ВЕСА)

    def test_с_артефактом_вес_даётся(self) -> None:
        """Негативный контроль (И5): починка не должна отключить обратную связь."""
        буфер = _буфер()
        буфер.record(
            record_id="r1",
            prompt="p",
            model="veo",
            rating=10,
            outcome="pass",
            artifact="out/rooftop_01.mp4",
        )
        self.assertGreater(буфер.boost()(CorpusRecord("r1", "p")), БЕЗ_ВЕСА)

    def test_запись_остаётся_в_журнале_и_видна_в_статистике(self) -> None:
        """Не давать веса — не то же самое, что стереть: заявка была сделана."""
        буфер = _буфер()
        буфер.record(
            record_id="r1", prompt="p", model="veo", rating=10, outcome="pass", artifact=""
        )
        свод = буфер.stats()
        self.assertEqual(свод["entries"], 1)
        self.assertEqual(свод["with_artifact"], 0)


if __name__ == "__main__":
    unittest.main()
