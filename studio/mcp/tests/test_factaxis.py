"""Вторая ось у факта: род, колонка и ВЫЧИСЛЕННЫЙ исход шага.

Ожидаемое — литералы (Т2): роды, колонки и исходы выписаны строками, а не
импортированы из проверяемого модуля, иначе они поедут вместе с ним и
промолчат. Сети и живой базы здесь нет (Т4): все факты собраны в тестах.

ГЛАВНОЕ ЗДЕСЬ — МУТАЦИЯ КОЛОНКИ В ОБЕ СТОРОНЫ. Колонка, от переворота которой
исход не меняется, декоративна, и никакие числа про 969 размеченных строк
этого не показали бы.
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

from studio import factaxis as fa
from studio.selfrag.facts import Fact

_SPEC = importlib.util.spec_from_file_location(
    "check_fact_axis",
    Path(__file__).resolve().parents[3] / "scripts" / "check_fact_axis.py",
)
assert _SPEC and _SPEC.loader
gate = importlib.util.module_from_spec(_SPEC)
# Модуль регистрируется ДО исполнения: `@dataclass` внутри ищет свой модуль в
# `sys.modules`, и без этой строки падает на разборе аннотаций.
sys.modules["check_fact_axis"] = gate
_SPEC.loader.exec_module(gate)

#: Дом три исхода, выписанные литералами (Т2).
PASS_ = "pass"
FAIL_ = "fail"
UNMEASURED_ = "could not measure"


def факт(model, attribute, value="", tier="vendor", url="https://example.test/p", witnessed=""):
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url=url,
        tier=tier,
        stated_on="2026-08-31",
        witnessed=witnessed,
    )


class Роды(unittest.TestCase):
    def test_параметр_вендора_это_схема(self):
        """`max_seconds` с вендорской страницы — форма входа, не результат."""
        m = fa.mark(факт("kling-3.0", "max_seconds", "15", tier="vendor"))
        self.assertEqual(m.kind, "schema")
        self.assertEqual(m.origin, "РАСЧЁТ")

    def test_вендорская_проза_о_поведении_это_заявление(self):
        """Настоящая строка базы: вендор SVD пишет, что промптом не рулить."""
        m = fa.mark(
            факт(
                "stable-video-diffusion-img2vid-xt",
                "limitation",
                "No text conditioning at all",
                tier="vendor",
            )
        )
        self.assertEqual(m.kind, "claim")

    def test_статья_о_поведении_это_измерение(self):
        m = fa.mark(факт("*", "metric_blind_spot", "FVD едва шевелится", tier="paper"))
        self.assertEqual(m.kind, "measurement")

    def test_бенчмарк_о_поведении_это_измерение(self):
        m = fa.mark(факт("hunyuanvideo", "benchmark_score", "VBench-2.0", tier="benchmark"))
        self.assertEqual(m.kind, "measurement")

    def test_зонд_это_свидетельство_даже_про_параметр(self):
        """`fps`, снятые с выходного файла зондом, — не строка спецификации."""
        m = fa.mark(факт("kling-3.0", "fps", "24", tier="probe"))
        self.assertEqual(m.kind, "witness")
        self.assertEqual(m.origin, "РАСЧЁТ")

    def test_строка_с_witnessed_это_свидетельство_и_единственное_измеренное(self):
        m = fa.mark(
            факт(
                "nano-banana-edit",
                "text_rendering",
                "держит текст",
                tier="operator",
                witnessed="подан кадр с Pillow-текстом, текст дошёл неискажённым",
            )
        )
        self.assertEqual(m.kind, "witness")
        self.assertEqual(m.origin, "ИЗМЕРЕНО")

    def test_невыведенное_это_третий_исход_а_не_догадка(self):
        m = fa.mark(факт("flux-2", "hex_color_control", "hex совпадает точно", tier="vendor"))
        self.assertEqual(m.kind, "")
        self.assertEqual(m.origin, "")
        self.assertFalse(m.resolved)

    def test_выведенная_разметка_никогда_не_измерено(self):
        """И4: выведенное, поданное как наблюдённое, потом никто не трогает."""
        факты = [
            факт("a", "max_seconds", "10"),
            факт("b", "limitation", "no text", tier="vendor"),
            факт("c", "failure_mode", "drift", tier="paper"),
            факт("d", "fps", "24", tier="probe"),
        ]
        for m in fa.mark_all(факты):
            self.assertEqual(m.origin, "РАСЧЁТ", m.fact.model)


class Ортогональность(unittest.TestCase):
    """Ось рода не выводится из оси авторитета — иначе она вторая только на вид."""

    def test_способность_бывает_при_высшем_авторитете(self):
        m = fa.mark(факт("svd", "limitation", "нет текстового кондишенинга", tier="vendor"))
        self.assertEqual(fa.axis(m.kind), "способность")

    def test_применимость_бывает_при_низшем(self):
        m = fa.mark(факт("infinitetalk", "failure_mode", "уносит соседей", tier="probe"))
        self.assertEqual(fa.axis(m.kind), "применимость")

    def test_один_тир_даёт_оба_рода(self):
        схема = fa.mark(факт("kling-3.0", "max_seconds", "15", tier="vendor"))
        проза = fa.mark(факт("kling-3.0", "limitation", "лица плывут", tier="vendor"))
        self.assertEqual([схема.kind, проза.kind], ["schema", "claim"])

    def test_у_неразмеченного_колонки_нет(self):
        self.assertEqual(fa.axis(""), "")


class ИсходШага(unittest.TestCase):
    def шаг(self, факты):
        return fa.step_verdict("шаг", "убийственное требование", fa.mark_all(факты))

    def test_только_схема_это_не_смогли(self):
        """Главное требование пункта: вендор принимает вход ≠ результат держится."""
        v = self.шаг(
            [факт("kling-3.0", "max_seconds", "15"), факт("kling-3.0", "max_resolution", "4K")]
        )
        self.assertEqual(v["outcome"], UNMEASURED_)
        self.assertEqual(v["checked"], 2)
        self.assertEqual(v["violations"], 0)

    def test_схема_плюс_вендорская_проза_всё_ещё_не_смогли(self):
        v = self.шаг(
            [
                факт("kling-3.0", "max_seconds", "15"),
                факт("kling-3.0", "limitation", "лица плывут", tier="vendor"),
            ]
        )
        self.assertEqual(v["outcome"], UNMEASURED_)

    def test_свидетельство_даёт_годно(self):
        v = self.шаг(
            [
                факт("kling-3.0", "max_seconds", "15"),
                факт(
                    "kling-3.0",
                    "text_rendering",
                    "текст дошёл",
                    tier="operator",
                    witnessed="запустили и посмотрели",
                ),
            ]
        )
        self.assertEqual(v["outcome"], PASS_)

    def test_отрицательное_наблюдение_это_не_годно_а_не_годно(self):
        """Свидетельство бывает против шага, и сворачивать его в «годно» нельзя."""
        v = self.шаг([факт("infinitetalk", "failure_mode", "уносит соседей", tier="probe")])
        self.assertEqual(v["outcome"], FAIL_)
        self.assertEqual(v["violations"], 1)

    def test_пустой_шаг_это_не_смогли_с_ненулевым_счётчиком(self):
        """Р2: ноль проверок не равен успеху, и `не смогли` не бывает нулём."""
        v = self.шаг([])
        self.assertEqual(v["outcome"], UNMEASURED_)
        self.assertEqual(v["checked"], 0)
        self.assertEqual(v["unmeasured"], 1)

    def test_неразмеченное_считается_третьим_исходом_а_не_молчит(self):
        v = self.шаг(
            [
                факт("kling-3.0", "max_seconds", "15"),
                факт("flux-2", "hex_color_control", "точно", tier="vendor"),
            ]
        )
        self.assertEqual(v["checked"], 1)
        self.assertEqual(v["unmeasured"], 1)


class МутацияКолонки(unittest.TestCase):
    """Переворот одной строки обязан менять исход. В обе стороны (Т1)."""

    СХЕМА = факт("kling-3.0", "max_seconds", "15", tier="vendor")
    СВИДЕТЕЛЬ = факт(
        "nano-banana-edit",
        "text_rendering",
        "держит текст",
        tier="operator",
        url="владелец, чат 2026-08-31",
        witnessed="подан кадр с Pillow-текстом, текст дошёл неискажённым",
    )

    def test_схему_пометили_свидетельством_и_шаг_позеленел(self):
        было = fa.step_verdict("шаг", "требование", fa.mark_all([self.СХЕМА]))
        self.assertEqual(было["outcome"], UNMEASURED_)
        подмена = {
            fa.axis_key(self.СХЕМА.model, self.СХЕМА.attribute, self.СХЕМА.source_url): (
                "witness",
                "ВЫБРАНО",
                "мутация теста",
            )
        }
        стало = fa.step_verdict("шаг", "требование", fa.mark_all([self.СХЕМА], подмена))
        self.assertEqual(стало["outcome"], PASS_)

    def test_единственного_свидетеля_пометили_схемой_и_шаг_упал_в_не_смогли(self):
        было = fa.step_verdict("шаг", "требование", fa.mark_all([self.СВИДЕТЕЛЬ]))
        self.assertEqual(было["outcome"], PASS_)
        подмена = {
            fa.axis_key(
                self.СВИДЕТЕЛЬ.model, self.СВИДЕТЕЛЬ.attribute, self.СВИДЕТЕЛЬ.source_url
            ): ("schema", "ВЫБРАНО", "мутация теста")
        }
        стало = fa.step_verdict("шаг", "требование", fa.mark_all([self.СВИДЕТЕЛЬ], подмена))
        self.assertEqual(стало["outcome"], UNMEASURED_)


class Рендерер(unittest.TestCase):
    """Ветки, печатающей рекомендацию с одной колонкой, быть не должно."""

    def верни(self, факты):
        return fa.render(fa.step_verdict("шаг", "требование", fa.mark_all(факты)))

    def test_обе_колонки_на_месте_при_каждом_исходе(self):
        случаи = [
            [факт("kling-3.0", "max_seconds", "15")],
            [факт("infinitetalk", "failure_mode", "уносит", tier="probe")],
            [
                факт(
                    "nano-banana-edit",
                    "text_rendering",
                    "держит",
                    tier="operator",
                    witnessed="запустили и посмотрели",
                )
            ],
            [],
        ]
        for случай in случаи:
            текст = self.верни(случай)
            self.assertIn("способность:", текст)
            self.assertIn("применимость:", текст)

    def test_пустая_применимость_печатается_значением(self):
        текст = self.верни([факт("kling-3.0", "max_seconds", "15")])
        self.assertIn("нет свидетельства", текст)

    def test_счётчики_печатаются_рядом(self):
        текст = self.верни([факт("kling-3.0", "max_seconds", "15")])
        self.assertIn("проверено 1, нарушений 0, не смогли 0", текст)

    def test_исход_печатается_по_русски(self):
        текст = self.верни([])
        self.assertIn("исход: не смогли", текст)


class РучныеРазметки(unittest.TestCase):
    def файл(self, *строки):
        каталог = tempfile.mkdtemp()
        путь = Path(каталог) / "fact_axis.jsonl"
        путь.write_text("// заголовок\n" + "\n".join(строки) + "\n", encoding="utf-8")
        return путь

    def test_годная_строка_принимается(self):
        путь = self.файл(
            json.dumps(
                {
                    "model": "*",
                    "attribute": "vlm_judge_human_agreement",
                    "source_url": "https://arxiv.org/abs/2605.03475",
                    "kind": "measurement",
                    "origin": "ВЫБРАНО",
                    "why": "прочитано глазами",
                },
                ensure_ascii=False,
            )
        )
        загружено = fa.load_overrides(путь)
        self.assertEqual(len(загружено), 1)
        self.assertEqual(fa.rows_in(путь), 1)

    def test_чужое_происхождение_не_принимается_и_видно_разницей(self):
        путь = self.файл(
            json.dumps(
                {
                    "model": "*",
                    "attribute": "x",
                    "source_url": "u",
                    "kind": "measurement",
                    "origin": "ПОКАЗАЛОСЬ",
                }
            )
        )
        self.assertEqual(fa.load_overrides(путь), {})
        self.assertEqual(fa.rows_in(путь), 1)

    def test_чужой_род_не_принимается(self):
        путь = self.файл(
            json.dumps(
                {
                    "model": "*",
                    "attribute": "x",
                    "source_url": "u",
                    "kind": "vibes",
                    "origin": "ВЫБРАНО",
                }
            )
        )
        self.assertEqual(fa.load_overrides(путь), {})

    def test_файла_нет_это_пусто_а_не_ошибка(self):
        self.assertEqual(fa.load_overrides(Path("/nonexistent/fact_axis.jsonl")), {})
        self.assertEqual(fa.rows_in(Path("/nonexistent/fact_axis.jsonl")), 0)

    def test_ключ_не_несёт_значения_факта(self):
        """Иначе разметка копировала бы чужую прозу во второй файл (Е1)."""
        self.assertEqual(
            fa.axis_key("Kling-3.0", "Max_Seconds", " u "), ("kling-3.0", "max_seconds", "u")
        )


class Гейт(unittest.TestCase):
    def test_контрольный_набор_даёт_три_разных_исхода(self):
        результаты = gate.control_results()
        исходы = [r["got"] for r in результаты]
        # Проверяется НАБОР исходов, а не их число: шагов больше трёх, потому
        # что два из них добавлены ради констант, а не ради нового исхода.
        # Литералы, не импорт из проверяемого модуля (Т2).
        self.assertEqual(sorted(set(исходы)), ["could not measure", "fail", "pass"])
        self.assertEqual([r["expected"] for r in результаты], исходы)
        self.assertGreaterEqual(len(результаты), 3)
        self.assertEqual(gate.control_verdict(результаты)["outcome"], PASS_)

    def test_прибор_из_одинаковых_случаев_краснеет(self):
        """Негативный контроль негативного контроля (И5)."""
        одинаковые = [
            {"step": "a", "expected": PASS_, "got": PASS_},
            {"step": "b", "expected": PASS_, "got": PASS_},
            {"step": "c", "expected": PASS_, "got": PASS_},
        ]
        v = gate.control_verdict(одинаковые)
        self.assertEqual(v["outcome"], FAIL_)

    def test_пустой_контроль_это_не_смогли(self):
        self.assertEqual(gate.control_verdict([])["outcome"], UNMEASURED_)

    def test_пустая_база_это_не_смогли_а_не_ноль_нарушений(self):
        v = gate.base_verdict([], {})
        self.assertEqual(v["outcome"], UNMEASURED_)
        self.assertEqual(v["checked"], 0)
        self.assertEqual(v["unmeasured"], 1)

    def test_осиротевшая_ручная_разметка_краснеет(self):
        факты = [факт("kling-3.0", "max_seconds", "15")]
        подмена = {
            ("сказочная-модель", "max_seconds", "https://example.test/p"): (
                "witness",
                "ВЫБРАНО",
                "",
            )
        }
        v = gate.base_verdict(факты, подмена)
        self.assertEqual(v["outcome"], FAIL_)
        self.assertEqual(v["violations"], 1)

    def test_ручная_разметка_имеет_право_на_измерено(self):
        """Человек мог быть очевидцем; ловится ВЫВЕДЕННОЕ, а не проставленное."""
        ф = факт("kling-3.0", "max_seconds", "15")
        подмена = {fa.axis_key(ф.model, ф.attribute, ф.source_url): ("schema", "ИЗМЕРЕНО", "")}
        v = gate.base_verdict([ф], подмена)
        self.assertEqual(v["violations"], 0)

    def test_выведенная_разметка_с_пометкой_измерено_краснеет(self):
        """И4 наблюдаемо: если правило начнёт выдавать вывод за наблюдение."""
        ф = факт("kling-3.0", "max_seconds", "15")
        поддельная = [fa.Marked(ф, "schema", "ИЗМЕРЕНО", "поддельная разметка")]
        настоящий = gate.fa.mark_all
        gate.fa.mark_all = lambda facts, overrides=None: поддельная  # type: ignore[assignment]
        try:
            v = gate.base_verdict([ф], {})
        finally:
            gate.fa.mark_all = настоящий  # type: ignore[assignment]
        self.assertEqual(v["outcome"], FAIL_)
        self.assertEqual(v["violations"], 1)


class Константы(unittest.TestCase):
    """Т1: константа-решение сторожится, а не просто существует."""

    def test_колонки_не_пересекаются_и_покрывают_все_роды(self):
        self.assertEqual(sorted(fa.CAPABILITY + fa.APPLICABILITY), sorted(fa.KINDS))
        self.assertEqual(set(fa.CAPABILITY) & set(fa.APPLICABILITY), set())

    def test_состав_колонок_именно_такой(self):
        self.assertEqual(sorted(fa.CAPABILITY), ["claim", "schema"])
        self.assertEqual(sorted(fa.APPLICABILITY), ["measurement", "witness"])

    def test_свидетельские_тиры_именно_эти(self):
        self.assertEqual(sorted(fa.WITNESS_TIERS), ["operator", "probe"])

    def test_измерительные_тиры_именно_эти(self):
        self.assertEqual(sorted(fa.MEASUREMENT_TIERS), ["benchmark", "paper"])

    def test_вендор_и_площадка_не_дают_ни_измерения_ни_свидетельства(self):
        for тир in ("vendor", "portal", "blog"):
            self.assertNotIn(тир, fa.WITNESS_TIERS | fa.MEASUREMENT_TIERS)

    def test_атрибуты_поломки_входят_в_атрибуты_поведения(self):
        self.assertTrue(fa.CONTRA_ATTRIBUTES <= fa.QUALITY_ATTRIBUTES)


if __name__ == "__main__":
    unittest.main()
