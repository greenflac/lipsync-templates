"""Канал, инвариантный ко входу: ловится ли, и не ловится ли лишнего.

ЗАЧЕМ. ИЗМЕРЕНО 2026-08-31: `advice.advise(model)['class_findings']` возвращает
12 находок из 171, одни и те же для любого имени модели, включая выдуманное.
Перекрытие 1.00. Выдача правдива (тир `paper`, со ссылками), но канал, дающий
один и тот же ответ на любой вход, несёт ноль бит о входе.

НЕГАТИВНЫЙ КОНТРОЛЬ (И5) — здесь он и есть главный тест. Подложный канал,
ЗАВЕДОМО различающий вход, обязан пройти; подложный, заведомо инвариантный,
обязан покраснеть. Без первого проверка, ругающаяся на всё, выглядела бы
работающей.

Ожидаемое — литералы (Т2); сети и живой базы здесь нет, все каналы подложные
и отвечают из словаря (Т4).
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_channel_signal",
    Path(__file__).resolve().parents[3] / "scripts" / "check_channel_signal.py",
)
assert _SPEC and _SPEC.loader
signal = importlib.util.module_from_spec(_SPEC)
# Модуль регистрируется ДО исполнения: `@dataclass` внутри него ищет свой
# модуль в `sys.modules`, и без этой строки падает на разборе аннотаций.
sys.modules["check_channel_signal"] = signal
_SPEC.loader.exec_module(signal)

#: Три исхода дома, выписанные строками, а не импортированные из проверяемого
#: модуля (Т2): импортированное поедет вместе с кодом и промолчит.
PASS_ = "pass"
FAIL_ = "fail"
UNMEASURED_ = "could not measure"

PAIRS = (("alpha", "beta"), ("gamma", "delta"))


def _channel(name: str, table: dict[str, set]) -> object:
    return signal.Channel(name=name, pairs=PAIRS, elements=lambda x: table[x])


#: Подложный канал, который ЗАВЕДОМО различает вход: у каждого входа свои
#: элементы, ни одного общего.
DISCRIMINATING = {
    "alpha": {"a1", "a2"},
    "beta": {"b1", "b2"},
    "gamma": {"g1"},
    "delta": {"d1"},
}

#: Подложный канал, ЗАВЕДОМО инвариантный: тот же ответ на любой вход. Это
#: форма `class_findings`, сведённая к четырём строкам.
INVARIANT = {name: {"same1", "same2", "same3"} for name in ("alpha", "beta", "gamma", "delta")}


class TheInstrumentHasBothControls(unittest.TestCase):
    def test_a_channel_that_DOES_distinguish_its_input_passes(self) -> None:
        """Негативный контроль (И5): вход, на котором прибор обязан промолчать."""
        got = signal.measure(_channel("fake.discriminating", DISCRIMINATING))
        assert got["outcome"] == PASS_, got
        assert got["overlap"] == 0.0, got
        assert got["pairs"] == 2, got

    def test_a_channel_that_does_NOT_distinguish_its_input_is_caught(self) -> None:
        """Позитивный контроль: вход, на котором прибор обязан шевельнуться."""
        got = signal.measure(_channel("fake.invariant", INVARIANT))
        assert got["outcome"] == FAIL_, got
        assert got["overlap"] == 1.0, got

    def test_THE_REAL_DEFECT_shape_is_caught(self) -> None:
        """Форма настоящего дефекта: 12 неизменных элементов плюс один свой.

        Так выглядит `class_findings`, если кто-то «починит» его подмешиванием
        одного элемента от входа. Канал остаётся инвариантным по существу, и
        порог обязан это видеть — поэтому он не 1.00.
        """
        table = {
            name: {f"class{i}" for i in range(12)} | {f"own-{name}"}
            for name in ("alpha", "beta", "gamma", "delta")
        }
        got = signal.measure(_channel("fake.almost_invariant", table))
        assert got["outcome"] == FAIL_, got
        assert round(got["overlap"], 4) == 0.8571, got


class TheWorstPairDecides(unittest.TestCase):
    def test_invariance_on_ONE_pair_out_of_two_is_still_invariance(self) -> None:
        """Среднее спрятало бы это: 1.00 и 0.00 дают 0.50, то есть «годно»."""
        table: dict[str, set] = {"alpha": {"x"}, "beta": {"x"}, "gamma": {"g"}, "delta": {"d"}}
        got = signal.measure(_channel("fake.mixed", table))
        assert got["outcome"] == FAIL_, got
        assert got["overlap"] == 1.0, got


class NothingMeasuredIsNotSuccess(unittest.TestCase):
    def test_two_empty_outputs_are_not_a_measured_pair(self) -> None:
        """Пустая выдача с обеих сторон — не 1.0 и не 0.0, а «нечего мерить»."""
        assert signal.overlap([], []) is None
        assert signal.overlap({"a"}, set()) == 0.0

    def test_a_channel_that_returned_nothing_at_all_is_unmeasured(self) -> None:
        table: dict[str, set] = {name: set() for name in ("alpha", "beta", "gamma", "delta")}
        got = signal.measure(_channel("fake.silent", table))
        assert got["outcome"] == UNMEASURED_, got
        assert got["pairs"] == 0, got

    def test_a_channel_that_raised_is_unmeasured_and_not_a_failure(self) -> None:
        """Корпуса может не быть в CI. Это честное «не смогли», а не провал."""

        def boom(_: str) -> set:
            raise FileNotFoundError("нет корпуса на диске")

        got = signal.measure(signal.Channel(name="fake.absent", pairs=PAIRS, elements=boom))
        assert got["outcome"] == UNMEASURED_, got
        assert len(got["unmeasurable"]) == 2, got

    def test_zero_working_channels_is_could_not_measure_not_pass(self) -> None:
        """Р2: ноль нарушений при нуле отработавших проверок — не успех."""
        verdict = signal.judge([], {})
        assert verdict["outcome"] == UNMEASURED_, verdict
        assert verdict["checked"] == 0, verdict


class TheKnownListIsGuarded(unittest.TestCase):
    def test_an_EMPTY_known_list_reddens_on_a_live_violator(self) -> None:
        """Список известных нарушителей — константа-решение и сторожится.

        Пустой список при живом нарушителе обязан краснить: иначе его можно
        было бы опустошить, ничего не заметив.
        """
        results = [signal.measure(_channel("advice.advise().class_findings", INVARIANT))]
        assert signal.judge(results, {})["outcome"] == FAIL_
        assert signal.judge(results, {})["violations"] == 1

    def test_the_known_violator_is_a_debt_and_not_a_pass(self) -> None:
        """Известный нарушитель не красит сборку, но и не читается как успех:
        он идёт в `не смогли`, а не в `проверено и годно`."""
        results = [signal.measure(_channel("advice.advise().class_findings", INVARIANT))]
        verdict = signal.judge(results, {"advice.advise().class_findings": "долг"})
        assert verdict["outcome"] == PASS_, verdict
        assert verdict["violations"] == 0, verdict
        assert verdict["unmeasured"] == 1, verdict

    def test_a_NEW_violator_reddens_even_when_the_old_one_is_known(self) -> None:
        results = [
            signal.measure(_channel("advice.advise().class_findings", INVARIANT)),
            signal.measure(_channel("something.new", INVARIANT)),
        ]
        verdict = signal.judge(results, {"advice.advise().class_findings": "долг"})
        assert verdict["outcome"] == FAIL_, verdict
        assert verdict["violations"] == 1, verdict

    def test_the_list_names_the_real_violator_measured_today(self) -> None:
        """Имя канала в списке — литерал, и оно должно совпадать с именем,
        под которым канал зарегистрирован. Разъехавшись, список замолчит."""
        assert "advice.advise().class_findings" in signal.KNOWN_INVARIANT
        assert "advice.advise().class_findings" in {c.name for c in signal.live_channels()}


class TheThresholdSitsInTheMeasuredGap(unittest.TestCase):
    def test_a_channel_sharing_HALF_its_elements_still_passes(self) -> None:
        """Каналы одной предметной области законно делят часть элементов.

        Половина общих — это ещё сигнал о входе, а не его отсутствие; порог,
        опущенный к самой границе измеренного, покрасил бы честный канал.
        """
        table: dict[str, set] = {
            "alpha": {"shared1", "shared2", "a1", "a2"},
            "beta": {"shared1", "shared2", "b1", "b2"},
            "gamma": {"g"},
            "delta": {"d"},
        }
        got = signal.measure(_channel("fake.half_shared", table))
        assert got["outcome"] == PASS_, got
        assert round(got["overlap"], 4) == 0.3333, got

    def test_the_measured_discriminating_values_stay_below_it(self) -> None:
        """ИЗМЕРЕНО 2026-08-31 на живой базе: худший различающий канал дал
        0.17. Порог обязан быть выше — иначе гейт красит честный канал."""
        assert signal.INVARIANT_AT > 0.17
        assert signal.INVARIANT_AT < 1.0
