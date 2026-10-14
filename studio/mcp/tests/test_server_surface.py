"""Числа в докстроке сервера обязаны совпадать с живым списком инструментов.

ЗАЧЕМ. Разбор 2026-08-31: первая строка объявляла «Twelve tools, three of which
write», а инструментов было четырнадцать и писали семь. Докстрока разъехалась
тихо, потому что её никто не сверял. Правило Ц7: то, что обязано выполняться
всегда, — это тест, а не абзац.
"""

from __future__ import annotations

import asyncio
import inspect
import unittest

from studio.mcp import server as S

#: Слова-числа, которыми написана первая строка. Литералы (Т2): импортировать
#: их из проверяемого модуля значило бы сверять число само с собой.
WORDS = {
    12: "Twelve",
    13: "Thirteen",
    14: "Fourteen",
    15: "Fifteen",
    16: "Sixteen",
    3: "three",
    4: "four",
    5: "five",
    6: "six",
    7: "seven",
    8: "eight",
}

#: Инструменты, которые трогают диск: три пишут знание, четыре — журнал отказов
#: как побочный эффект похода в сеть. ИЗМЕРЕНО 2026-08-31 чтением исходников.
#: ВОСЬМОЙ — `model_advice`: пишет каждый вопрос в журнал промахов
#: (`misses.note_question`). Найдено аудитом 2026-10-14: строка говорила «seven».
WRITERS = frozenset(
    {
        "model_advice",
        "record_model_fact",
        "withdraw_model_fact",
        "propose_measurement",
        "fetch_url",
        "search_web",
        "reachable_hosts",
        "probe_model_limit",
    }
)


def _tools() -> list:
    return asyncio.run(S.server.list_tools())


class TheDocstringCountsMustMatchTheServer(unittest.TestCase):
    def test_the_tool_count_in_the_first_line_is_true(self) -> None:
        names = [t.name for t in _tools()]
        first_line = (S.__doc__ or "").splitlines()[0]
        assert WORDS[len(names)] in first_line, f"инструментов {len(names)}, а строка: {first_line}"

    def test_the_writer_count_in_the_first_line_is_true(self) -> None:
        first_line = (S.__doc__ or "").splitlines()[0]
        assert WORDS[len(WRITERS)] in first_line, f"пишут {len(WRITERS)}, а строка: {first_line}"

    def test_every_named_writer_is_a_real_tool(self) -> None:
        """Негативный контроль на список: имя, которого нет среди инструментов,
        сделало бы счёт правдоподобным и ложным."""
        names = {t.name for t in _tools()}
        assert WRITERS <= names, sorted(WRITERS - names)

    def test_a_named_writer_really_touches_the_disk(self) -> None:
        """И проверка не по имени, а по коду: инструмент из списка обязан
        где-то писать — иначе список превратится в предание."""
        touching = (
            "record_",
            "withdraw_",
            "propose_",
            "fetch.fetch",
            "fetch.page",
            "reachability",
            "search(",
            "advise_and_note",
        )
        for name in sorted(WRITERS):
            fn = getattr(S, name)
            source = inspect.getsource(getattr(fn, "fn", fn))
            assert any(w in source for w in touching), name

    def test_a_read_only_tool_is_NOT_in_the_writer_list(self) -> None:
        """Другая сторона: если бы в список попало всё подряд, число «семь»
        ничего бы не значило."""
        names = {t.name for t in _tools()}
        readers = names - WRITERS
        assert readers, "хотя бы один инструмент обязан быть только читающим"
        assert "measurement_proposals" in readers

    def test_model_advice_really_writes_the_misses_journal(self) -> None:
        """Почему он в списке: свидетельство по коду, а не по имени."""
        source = inspect.getsource(S.advise_and_note)
        assert "misses.note_question" in source


if __name__ == "__main__":
    unittest.main()
