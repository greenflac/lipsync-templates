"""Ступенька «оператор попробовал сам»: доказательство или мнение с ярлыком.

Тир стоит третьим сверху — выше статьи и выше бенчмарка — и платит за это
единственным условием: сказать, ЧТО было запущено и что вышло. Тесты сторожат
ровно это, с обеих сторон.

Сети нет (Т4), ожидаемое — литералы (Т2).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from studio.mcp import advice

WITNESS = "подали nano-banana-edit кадр с текстом, отрисованным Pillow; текст дошёл без искажений"


def _record(tmp: Path, **over: object) -> dict:
    kwargs: dict = {
        "model": "nano-banana-edit",
        "attribute": "text_handling",
        "value": "держит заранее отрисованный текст",
        "source_url": "оператор, чат 2026-08-31",
        "tier": "operator",
        "stated_on": "2026-08-31",
        "witnessed": WITNESS,
        "path": tmp / "facts.jsonl",
    }
    kwargs.update(over)
    return advice.record(**kwargs)  # type: ignore[arg-type]


class AnOperatorClaimNeedsAnObservation(unittest.TestCase):
    def test_an_operator_fact_without_witnessed_is_REFUSED(self) -> None:
        """Не «весит меньше», а не записывается вовсе: вывод без наблюдения —
        это мнение, и тир для мнений уже есть, он называется blog."""
        with tempfile.TemporaryDirectory() as tmp:
            out = _record(Path(tmp), witnessed="")
            assert out["outcome"] == "fail", out["note"]
            assert "witnessed" in out["note"]
            assert out["written"] is None

    def test_whitespace_is_not_an_observation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            assert _record(Path(tmp), witnessed="   ")["outcome"] == "fail"

    def test_an_operator_fact_WITH_witnessed_is_written(self) -> None:
        """Негативный контроль (И5): проверка, которая отвергает всё, — это не
        проверка, а закрытая дверь."""
        with tempfile.TemporaryDirectory() as tmp:
            out = _record(Path(tmp))
            assert out["outcome"] == "pass", out["note"]
            row = json.loads((Path(tmp) / "facts.jsonl").read_text(encoding="utf-8").strip())
            assert row["witnessed"] == WITNESS
            assert row["tier"] == "operator"

    def test_OTHER_tiers_do_not_need_witnessed(self) -> None:
        """Поле обязательно только для этого тира. Иначе правка сломала бы
        запись всех вендорских фактов разом."""
        with tempfile.TemporaryDirectory() as tmp:
            out = _record(
                Path(tmp),
                tier="blog",
                source_url="https://example.com/somebody-wrote-this",
                witnessed="",
            )
            assert out["outcome"] == "pass", out["note"]


class AnOperatorHasNoPageAndNeedsNone(unittest.TestCase):
    def test_a_non_http_reference_is_accepted_for_operator(self) -> None:
        """Страницы у наблюдения нет и быть не может: `source_url` несёт
        отметку самого оператора — дату разговора, номер задачи, путь."""
        with tempfile.TemporaryDirectory() as tmp:
            assert _record(Path(tmp), source_url="чат владельца, 2026-08-31")["outcome"] == "pass"

    def test_a_non_http_reference_is_still_REFUSED_for_every_other_tier(self) -> None:
        """Другая сторона послабления: у факта со страницы ссылка обязана
        остаться ссылкой, иначе его нельзя перечитать."""
        with tempfile.TemporaryDirectory() as tmp:
            out = _record(Path(tmp), tier="blog", source_url="я где-то видел", witnessed="")
            assert out["outcome"] == "fail", out["note"]


class TheRungIsNotJustAWordInAList(unittest.TestCase):
    def test_an_operator_fact_is_not_counted_as_a_blog(self) -> None:
        """Смысл ступеньки: она вытаскивает утверждение из «одни блоги», где
        оно не считается установленным сколько бы блогов его ни повторяли."""
        from studio.selfrag.facts import TIER_BLOG, TIER_OPERATOR, TIERS

        assert TIER_OPERATOR != TIER_BLOG
        assert TIERS.index(TIER_OPERATOR) < TIERS.index(TIER_BLOG)


if __name__ == "__main__":
    unittest.main()
