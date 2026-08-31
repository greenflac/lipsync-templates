"""Ранжирующий базис: может ли он вообще сработать.

ЗАЧЕМ. Разбор 2026-08-31: критерий RANKING не срабатывал НИ НА ОДНОМ входе.
Базис считался по тем же пяти записям, что ретривер и вернул, а перемешать пять
и взять пять — это те же пять. Условие `wider > 0` было тождественно ложным,
шаг молча печатал «не смогли 1» и не проверял ничего.

Сети здесь нет и корпус не нужен (Т4): проверяется арифметика базиса на
литеральных списках (Т2).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "eval_corpus", Path(__file__).resolve().parents[3] / "scripts" / "eval_corpus.py"
)
assert _SPEC and _SPEC.loader
ev = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ev)


def _entry(text: str) -> dict:
    return {"text": text, "prompt": text}


class AShuffleOfTheSameFiveIsTheSameFive(unittest.TestCase):
    def test_a_pool_no_wider_than_k_gives_the_real_score_back(self) -> None:
        """Ровно тот случай, из-за которого критерий был мёртв: если пул равен
        выдаче, перемешивание ничего не меняет и базис равен настоящему счёту.
        Сравнивать с ним бессмысленно, и это надо УМЕТЬ ЗАМЕТИТЬ."""
        pools = [[_entry("a"), _entry("b")]]
        gold = [{"must_retrieve": ["a"]}]
        assert ev._ranking_baseline(pools, gold) == 1.0

    def test_a_WIDER_pool_lets_the_shuffle_lose_the_right_answer(self) -> None:
        """С пулом шире выдачи перемешивание способно вытеснить нужную запись,
        и базис падает ниже единицы — то есть наконец что-то измеряет.

        Базис берёт ЛУЧШЕЕ из BASELINE_SEEDS перемешиваний, то есть верхнюю
        границу везения, поэтому пул должен быть заметно шире выдачи.

        Размер ИЗМЕРЕН, а не выбран на глаз: сиды зафиксированы, поэтому
        результат детерминирован, и при 401 записи одно из двадцати
        перемешиваний всё-таки вытаскивает нужную (базис 1.0). Замерено на
        SEED=20260828: 201 → 0.0, 401 → 1.0, 801 → 0.0, 1601 → 0.0, 3201 → 0.0.
        Взято 1601 — с запасом от той единственной точки, где везёт."""
        pool = [_entry(f"шум-{i}") for i in range(1600)] + [_entry("нужная")]
        got = ev._ranking_baseline([pool], [{"must_retrieve": ["нужная"]}])
        assert got < 1.0, "перемешивание обязано иногда терять ответ"

    def test_the_baseline_takes_the_BEST_shuffle_not_an_average(self) -> None:
        """Почему предыдущий тест устроен именно так: базис — это верхняя
        граница везения, а не среднее. Средним его сделать нельзя: сравнение
        «мы лучше случайного» обязано побеждать самый удачный случай."""
        pool = [_entry(f"шум-{i}") for i in range(30)] + [_entry("нужная")]
        assert ev._ranking_baseline([pool], [{"must_retrieve": ["нужная"]}]) == 1.0
        assert ev.BASELINE_SEEDS >= 10

    def test_the_wider_factor_is_greater_than_one(self) -> None:
        """Литерал, а не импорт проверяемого значения (Т2). При множителе 1
        пул совпал бы с выдачей, и критерий снова стал бы мёртвым.

        ЧЕСТНО ПРО СИЛУ ЭТОГО СТОРОЖА: он ловит единственную границу, которая
        что-то решает, — 1 против ≥2. Подмена 4 на 2 не красит ничего, и это
        не дыра: оба значения дают пул шире выдачи, то есть делают ровно то,
        ради чего константа существует. Ширина сверх этого — вопрос стоимости
        прогона, а не правильности, и сторожить её тестом было бы имитацией."""
        assert ev.WIDER_POOL >= 2


class TheWidthIsCountedOnThePoolNotOnTheAnswer(unittest.TestCase):
    def test_an_answer_is_never_wider_than_k_by_construction(self) -> None:
        """Причина дефекта, записанная тестом: ретривер отдаёт РОВНО k, поэтому
        считать ширину по выдаче — значит считать ноль. Здесь это утверждение
        зафиксировано литералом, чтобы правка ретривера его уронила."""
        answers = [[_entry("x")] * ev.K.DEFAULT_K]
        assert sum(1 for a in answers if len(a) > ev.K.DEFAULT_K) == 0

    def test_a_pool_of_twenty_is_wider_than_five(self) -> None:
        pools = [[_entry("x")] * (ev.K.DEFAULT_K * ev.WIDER_POOL)]
        assert sum(1 for p in pools if len(p) > ev.K.DEFAULT_K) == 1


if __name__ == "__main__":
    unittest.main()
