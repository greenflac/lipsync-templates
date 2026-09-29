"""Плотный канал на сервере: включён по умолчанию и выключается переменной.

Индекс здесь НЕ строится (Т4): проверяется решение о флаге, а не сборка, —
иначе тест полез бы за весами в сеть и стал бы трёхминутным.
"""

from __future__ import annotations

import unittest

from studio.mcp import server as S


#: НАСТОЯЩАЯ развилка из server.py, а не её копия здесь. Первая редакция
#: этого файла повторяла условие у себя — и обе мутации оригинала прошли мимо,
#: потому что тест проверял сам себя.
_decide = S.dense_wanted


class TheServerAsksForDenseUnlessToldOtherwise(unittest.TestCase):
    def test_it_is_on_when_nothing_is_set(self) -> None:
        """Решение владельца 2026-08-31, принятое по замеру 0.5333 → 0.6833."""
        assert _decide({}) is True

    def test_zero_turns_it_off(self) -> None:
        """Негативный контроль (И5): выключатель, который не выключает, — это
        не выключатель, а надпись."""
        assert _decide({S.DENSE_ON_SERVER_ENV: "0"}) is False

    def test_anything_else_leaves_it_on(self) -> None:
        """Выключает только явный ноль. Опечатка не должна тихо ронять
        качество поиска на 0.15 — это ровно тот случай, когда «примерно
        похоже на выключение» хуже, чем ничего."""
        for value in ("1", "true", "", "yes", "00"):
            assert _decide({S.DENSE_ON_SERVER_ENV: value}) is True, value

    def test_the_library_default_is_NOT_touched(self) -> None:
        """`build_index` без аргумента обязан остаться быстрым и офлайновым:
        иначе каждый тест в репозитории полезет за весами (Т4). Литерал, а не
        импорт проверяемого значения (Т2)."""
        import inspect

        from studio import knowledge

        signature = inspect.signature(knowledge.build_index)  # type: ignore[attr-defined]
        assert signature.parameters["dense"].default is None

    def test_the_env_name_is_what_the_docs_say(self) -> None:
        assert S.DENSE_ON_SERVER_ENV == "STUDIO_MCP_DENSE"


if __name__ == "__main__":
    unittest.main()
