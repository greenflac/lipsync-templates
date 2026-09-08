"""Промпт, собранный БЕЗ единого прецедента, не может быть «годно».

ВОСПРОИЗВЕДЕНО 2026-09-05 независимым аудитом:

    PromptEngineer(records=[]).write(...)  ->  outcome 'pass', examples [], confidence 0.0

Это НЕ экзотика, а состояние СВЕЖЕГО КЛОНА: корпус не коммитится намеренно
(лицензия — промпты чужая работа), и у всякого, кто клонировал репозиторий,
записей ноль. То есть по умолчанию продукт отвечал уверенно и без оснований.

Соседние стадии так не делают: `style` и `availability` при третьем исходе
понижают PASS, `fidelity` вовсе валит. Ветка ретрива только дописывала текст
в конец ноты — и текст этот («no usable precedent») стоял РЯДОМ со словом
«годно», что читается как «мы всё проверили, просто примеров не нашлось».

Навык `.claude/skills/prompt-engineer/SKILL.md` обещает обратное: «a run with
retrieved 0 is a run with no evidence behind it», а CLI отдаёт exit 0 на pass.

Ожидаемые исходы — литералы (Т2).
"""

from __future__ import annotations

import unittest

from studio.selfrag.corpus import CorpusRecord
from studio.selfrag.pipeline import PromptEngineer, PromptRequest

ГОДНО = "pass"
НЕ_СМОГЛИ = "could not measure"

ЗАПРОС = PromptRequest(
    text="amber palette, backlit, film-grain, calm",
    model="veo",
    subject="a woman",
    action="turns to camera",
)


def _прецеденты() -> list[CorpusRecord]:
    """Корпус, из которого ретрив ЧТО-ТО найдёт: контроль другой стороны."""
    return [
        CorpusRecord(
            f"r{i}",
            "amber backlit portrait, film grain, calm mood, shallow depth of field",
            model="veo-3.1",
            tags=("amber", "backlit"),
            rating=9,
            result="looked good",
        )
        for i in range(6)
    ]


class ПустойКорпус(unittest.TestCase):
    def test_без_прецедентов_это_не_годно(self) -> None:
        итог = PromptEngineer(records=[], state_path=":memory:").write(ЗАПРОС)
        self.assertEqual(итог["outcome"], НЕ_СМОГЛИ)
        self.assertEqual(итог.get("examples"), [])

    def test_нота_говорит_что_именно_не_измерено(self) -> None:
        итог = PromptEngineer(records=[], state_path=":memory:").write(ЗАПРОС)
        self.assertIn("no usable precedent", итог["note"])

    def test_с_прецедентами_годно_остаётся_возможным(self) -> None:
        """Негативный контроль (И5): починка не должна запретить «годно» вовсе.

        Прибор, который никогда не говорит «годно», ничем не лучше прибора,
        который говорит его всегда.
        """
        итог = PromptEngineer(records=_прецеденты(), state_path=":memory:").write(ЗАПРОС)
        self.assertNotEqual(итог["outcome"], НЕ_СМОГЛИ, итог["note"])


if __name__ == "__main__":
    unittest.main()
