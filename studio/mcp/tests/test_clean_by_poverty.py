"""«Чисто» по одной строке — почти молчание, и наверх не ставится.

ВОСПРОИЗВЕДЕНО 2026-09-07 сбором данных: одна нейтральная строка зонда о
`kling-video-lipsync-audio-to-video` вытеснила `sync-lipsync` (3 строки, 1
плохая) и `latentsync` (4 строки, 3 плохих) ИЗ ВЫБОРА ВОВСЕ. ИЗМЕРЕНО на 33
плановых задачах голден-сета: 23 шага из 71 выбирали кандидата, «чистого»
ровно потому, что о нём измерена одна строка; после ступени `SIGN_THIN` — 1.

Зонд при этом наблюдал, что API ПРИНЯЛ ПАРАМЕТРЫ, то есть СПОСОБНОСТЬ, а не
применимость. Отличать эти два утверждения — вся работа этого продукта.
"""

from __future__ import annotations

import unittest

from studio import planner


def _кандидат(**поля) -> planner.Candidate:
    """Кандидат из литералов. `in_favour` не поле, а разность: считается сам."""
    основа = dict(
        model="m",
        evidence=(),
        applicability=0,
        capability=0,
        unresolved=0,
        price="",
        against=0,
        anchored=0,
        named=False,
    )
    основа.update(поля)
    return planner.Candidate(**основа)  # type: ignore[arg-type]


class СтупениЗнака(unittest.TestCase):
    """Литералы, а не импорт порядка из проверяемого модуля (Т2)."""

    def test_четыре_строки_без_плохих_это_чисто(self) -> None:
        self.assertEqual(0, planner.sign_rank(_кандидат(applicability=4)))

    def test_одна_строка_без_плохих_это_НЕ_чисто(self) -> None:
        self.assertEqual(2, planner.sign_rank(_кандидат(applicability=1)))

    def test_тонкое_чисто_стоит_НИЖЕ_спорного(self) -> None:
        """Кандидат с четырьмя измерениями и одной плохой новостью ПОНЯТ;
        кандидат с одной нейтральной строкой — нет."""
        спорный = planner.sign_rank(_кандидат(applicability=4, against=1))
        тонкий = planner.sign_rank(_кандидат(applicability=1))
        self.assertLess(спорный, тонкий)

    def test_молчание_по_прежнему_хуже_всего(self) -> None:
        молчание = planner.sign_rank(_кандидат(applicability=0))
        только_плохое = planner.sign_rank(_кандидат(applicability=2, against=2))
        self.assertLess(только_плохое, молчание)

    def test_порог_ровно_на_двух_строках(self) -> None:
        """Обе стороны константы `ТОНКО` (И4/Т1): 1 — тонко, 2 — уже нет."""
        self.assertEqual(2, planner.sign_rank(_кандидат(applicability=1)))
        self.assertEqual(0, planner.sign_rank(_кандидат(applicability=2)))

    def test_ступень_названа_словами_заказчику(self) -> None:
        self.assertIn("по бедности", planner.SIGN_WORDS[planner.SIGN_THIN])


class ОтборСтавитИзмеренногоВыше(unittest.TestCase):
    def test_плотно_измеренный_обгоняет_тонко_чистого(self) -> None:
        тонкий = _кандидат(model="тонкий", applicability=1)
        плотный = _кандидат(model="плотный", applicability=4, against=1)
        порядок = sorted([тонкий, плотный], key=planner.by_evidence)
        self.assertEqual("плотный", порядок[0].model)

    def test_вовсе_неизмеренный_остаётся_последним(self) -> None:
        тонкий = _кандидат(model="тонкий", applicability=1)
        молчащий = _кандидат(model="молчащий", applicability=0, capability=99)
        порядок = sorted([молчащий, тонкий], key=planner.by_evidence)
        self.assertEqual("тонкий", порядок[0].model)


class СтрокаОВытесненномНеИсчезает(unittest.TestCase):
    """Вторая половина починки: `chosen.measured` истинно и при одной строке,
    и строка о плотнее измеренном соседе пропадала."""

    def test_у_тонкого_выбранного_сосед_назван(self) -> None:
        тонкий = _кандидат(model="тонкий", applicability=1)
        плотный = _кандидат(model="плотный", applicability=3, against=1)
        строка = planner.rival_line(тонкий, [тонкий, плотный])
        self.assertIn("плотный", строка)

    def test_у_плотного_выбранного_строки_нет(self) -> None:
        """И5: строка на каждом шаге — шум, и тогда её перестают читать."""
        плотный = _кандидат(model="плотный", applicability=3)
        другой = _кандидат(model="другой", applicability=4)
        self.assertEqual("", planner.rival_line(плотный, [плотный, другой]))

    def test_тонкий_среди_тонких_молчит(self) -> None:
        """«Проверенных нет вовсе» здесь было бы ложью: у выбранного измерено."""
        a = _кандидат(model="a", applicability=1)
        b = _кандидат(model="b", applicability=1)
        self.assertEqual("", planner.rival_line(a, [a, b]))


if __name__ == "__main__":
    unittest.main()
