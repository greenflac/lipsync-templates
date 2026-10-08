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
from studio.factindex import FactIndex
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
    """Исход выносится ПРО ЗАДАННОЕ требование, а не про модель вообще.

    Требования здесь подобраны так, чтобы делить строки: `лимит` относится к
    строкам о секундах и разрешении, `текст` — к строкам о тексте. Требование,
    не относящееся ни к чему из поданного, — отдельный случай ниже.
    """

    def шаг(self, факты, требование="lipsync 15 seconds"):
        return fa.step_verdict("шаг", требование, fa.mark_all(факты))

    def test_только_схема_это_не_смогли(self):
        """Главное требование пункта: вендор принимает вход ≠ результат держится."""
        v = self.шаг(
            [
                факт("kling-3.0", "max_seconds", "15 seconds"),
                факт("kling-3.0", "max_resolution", "4K, 15 seconds at most"),
            ]
        )
        self.assertEqual(v["outcome"], UNMEASURED_)
        self.assertEqual(v["checked"], 2)
        self.assertEqual(v["violations"], 0)
        self.assertEqual(v["off_topic"], 0)

    def test_схема_плюс_вендорская_проза_всё_ещё_не_смогли(self):
        v = self.шаг(
            [
                факт("kling-3.0", "max_seconds", "15 seconds"),
                факт("kling-3.0", "limitation", "lipsync drifts", tier="vendor"),
            ]
        )
        self.assertEqual(v["outcome"], UNMEASURED_)

    def test_свидетельство_даёт_годно(self):
        v = self.шаг(
            [
                факт("kling-3.0", "max_seconds", "15 seconds"),
                факт(
                    "kling-3.0",
                    "text_rendering",
                    "lipsync held for 15 seconds",
                    tier="operator",
                    witnessed="запустили и посмотрели",
                ),
            ]
        )
        self.assertEqual(v["outcome"], PASS_)

    def test_отрицательное_наблюдение_это_не_годно_а_не_годно(self):
        """Свидетельство бывает против шага, и сворачивать его в «годно» нельзя."""
        v = self.шаг([факт("infinitetalk", "failure_mode", "lipsync drift", tier="probe")])
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
                факт("kling-3.0", "max_seconds", "15 seconds"),
                факт("flux-2", "hex_color_control", "lipsync hex", tier="vendor"),
            ]
        )
        self.assertEqual(v["checked"], 1)
        self.assertEqual(v["unmeasured"], 1)


class ТребованиеРешает(unittest.TestCase):
    """ГЛАВНОЕ ЗДЕСЬ. До 2026-09-02 требование принималось параметром,
    возвращалось эхом и не читалось ни разу: на одном наборе фактов «губы
    держат синхрон», «вылечить рак» и пустая строка давали один и тот же
    исход. Прибор отвечал на вопрос «что вообще известно про модель», а выдавал
    это за ответ на «годится ли она ДЛЯ ЭТОГО».
    """

    ОТРИЦАТЕЛЬНОЕ = факт(
        "infinitetalk",
        "failure_mode",
        "In V2V lipsync the sampler rebuilds the entire frame, so people who are NOT the "
        "audio target visibly drift",
        tier="probe",
    )
    ПОЛОЖИТЕЛЬНОЕ = факт(
        "nano-banana-edit",
        "text_rendering",
        "держит заранее отрисованный текст, поданный картинкой",
        tier="operator",
        witnessed="подан кадр с Pillow-текстом, текст дошёл неискажённым",
    )

    def test_относящееся_требование_и_чужое_дают_разные_исходы(self):
        """Негативный контроль прибора (И5): он обязан РАЗЛИЧАТЬ, а не краснеть."""
        размечено = fa.mark_all([self.ОТРИЦАТЕЛЬНОЕ])
        своё = fa.step_verdict("шаг", "V2V lipsync не должен уносить молчащих", размечено)
        чужое = fa.step_verdict("шаг", "вылечить рак", размечено)
        self.assertEqual(своё["outcome"], FAIL_)
        self.assertEqual(чужое["outcome"], UNMEASURED_)
        self.assertNotEqual(своё["outcome"], чужое["outcome"])

    def test_чужое_требование_не_превращает_свидетельство_в_годно(self):
        """Вторая половина: отбросив строку как чужую, нельзя зачесть её в плюс."""
        размечено = fa.mark_all([self.ПОЛОЖИТЕЛЬНОЕ])
        своё = fa.step_verdict("шаг", "заранее отрисованный текст доходит", размечено)
        чужое = fa.step_verdict("шаг", "вылечить рак", размечено)
        self.assertEqual(своё["outcome"], PASS_)
        self.assertEqual(чужое["outcome"], UNMEASURED_)

    def test_пустое_требование_это_третий_исход_а_не_подходит_всё(self):
        размечено = fa.mark_all([self.ПОЛОЖИТЕЛЬНОЕ, self.ОТРИЦАТЕЛЬНОЕ])
        v = fa.step_verdict("шаг", "", размечено)
        self.assertEqual(v["outcome"], UNMEASURED_)
        self.assertEqual(v["checked"], 0)
        self.assertEqual(v["off_topic"], 2)

    def test_отброшенные_строки_печатаются_числом_а_не_молчат(self):
        """Р2: узкий ответ, поданный как полный, — это то же враньё числом."""
        размечено = fa.mark_all([self.ПОЛОЖИТЕЛЬНОЕ, self.ОТРИЦАТЕЛЬНОЕ])
        v = fa.step_verdict("шаг", "V2V lipsync не должен уносить молчащих", размечено)
        self.assertEqual(v["outcome"], FAIL_)
        self.assertEqual(v["off_topic"], 1)

    def test_relates_делит_строки_и_не_теряет_ни_одной(self):
        размечено = fa.mark_all([self.ПОЛОЖИТЕЛЬНОЕ, self.ОТРИЦАТЕЛЬНОЕ])
        относятся, мимо = fa.relates("V2V lipsync уносит молчащих", размечено)
        self.assertEqual(len(относятся), 1)
        self.assertEqual(len(мимо), 1)
        self.assertEqual(относятся[0].fact.attribute, "failure_mode")

    def test_порог_отношения_это_ручка_и_она_сторожится(self):
        """Т1 на RELEVANCE_FLOOR: поднятый до непроходимого порог гасит исход."""
        размечено = fa.mark_all([self.ОТРИЦАТЕЛЬНОЕ])
        обычный = fa.step_verdict("шаг", "V2V lipsync уносит молчащих", размечено)
        задранный = fa.step_verdict("шаг", "V2V lipsync уносит молчащих", размечено, floor=99.0)
        опущенный = fa.step_verdict("шаг", "вылечить рак", размечено, floor=0.0)
        self.assertEqual(обычный["outcome"], FAIL_)
        self.assertEqual(задранный["outcome"], UNMEASURED_)
        # Порог в ноль НЕ делает чужое требование своим: общих слов нет вовсе,
        # и вес такой строки не «мал», а отсутствует.
        self.assertEqual(опущенный["outcome"], UNMEASURED_)


class МутацияКолонки(unittest.TestCase):
    """Переворот одной строки обязан менять исход. В обе стороны (Т1)."""

    СХЕМА = факт("kling-3.0", "max_seconds", "15 seconds", tier="vendor")
    СВИДЕТЕЛЬ = факт(
        "nano-banana-edit",
        "text_rendering",
        "держит текст",
        tier="operator",
        url="владелец, чат 2026-08-31",
        witnessed="подан кадр с Pillow-текстом, текст дошёл неискажённым",
    )

    def test_схему_пометили_свидетельством_и_шаг_позеленел(self):
        было = fa.step_verdict("шаг", "15 seconds одним прогоном", fa.mark_all([self.СХЕМА]))
        self.assertEqual(было["outcome"], UNMEASURED_)
        подмена = {
            fa.axis_key(self.СХЕМА.model, self.СХЕМА.attribute, self.СХЕМА.source_url): (
                "witness",
                "ВЫБРАНО",
                "мутация теста",
            )
        }
        стало = fa.step_verdict(
            "шаг", "15 seconds одним прогоном", fa.mark_all([self.СХЕМА], подмена)
        )
        self.assertEqual(стало["outcome"], PASS_)

    def test_единственного_свидетеля_пометили_схемой_и_шаг_упал_в_не_смогли(self):
        было = fa.step_verdict("шаг", "текст доходит неискажённым", fa.mark_all([self.СВИДЕТЕЛЬ]))
        self.assertEqual(было["outcome"], PASS_)
        подмена = {
            fa.axis_key(
                self.СВИДЕТЕЛЬ.model, self.СВИДЕТЕЛЬ.attribute, self.СВИДЕТЕЛЬ.source_url
            ): ("schema", "ВЫБРАНО", "мутация теста")
        }
        стало = fa.step_verdict(
            "шаг", "текст доходит неискажённым", fa.mark_all([self.СВИДЕТЕЛЬ], подмена)
        )
        self.assertEqual(стало["outcome"], UNMEASURED_)


class Рендерер(unittest.TestCase):
    """Ветки, печатающей рекомендацию с одной колонкой, быть не должно."""

    def верни(self, факты, требование="lipsync 15 seconds"):
        return fa.render(fa.step_verdict("шаг", требование, fa.mark_all(факты)))

    def test_обе_колонки_на_месте_при_каждом_исходе(self):
        случаи = [
            [факт("kling-3.0", "max_seconds", "15 seconds")],
            [факт("infinitetalk", "failure_mode", "lipsync уносит", tier="probe")],
            [
                факт(
                    "nano-banana-edit",
                    "text_rendering",
                    "lipsync 15 seconds держит",
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
        текст = self.верни([факт("kling-3.0", "max_seconds", "15 seconds")])
        self.assertIn("нет свидетельства", текст)

    def test_счётчики_печатаются_рядом(self):
        текст = self.верни([факт("kling-3.0", "max_seconds", "15 seconds")])
        self.assertIn("проверено 1, нарушений 0, не смогли 0, не относится к требованию 0", текст)

    def test_отброшенное_как_чужое_печатается_рядом_со_счётчиками(self):
        """Узкий ответ, поданный как полный, читается как ответ на весь вопрос."""
        текст = self.верни([факт("kling-3.0", "max_seconds", "15 seconds")], "вылечить рак")
        self.assertIn("проверено 0, нарушений 0, не смогли 1, не относится к требованию 1", текст)
        self.assertIn("ни одна строка не относится к требованию", текст)

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

    def test_оговорка_о_метрике_идёт_против_шага(self):
        """Т1: мутация «убрать `metric_blind_spot` из CONTRA» молчала.

        Это не мелочь списка: на живой базе 2026-09-04 таких строк 74, и
        абляция того же дня показала, что ВСЕ 11 отказов планировщика по
        применимости стоят на них одних. Константа, решающая исход продукта
        целиком, не сторожилась ничем — состав множества был проверен только
        включением в QUALITY_ATTRIBUTES, то есть с другой стороны.

        Проверяется ИСХОДОМ, а не составом множества (Т2): измерение с этим
        атрибутом обязано давать «не годно», а не «годно».
        """
        размечено = fa.mark_all(
            [
                факт(
                    "kling-3.0",
                    "metric_blind_spot",
                    "FVD едва шевелится там, где губы уезжают на полкадра",
                    tier="paper",
                )
            ]
        )
        v = fa.step_verdict("шаг", "губы должны совпадать со звуком", размечено)
        self.assertEqual(v["outcome"], FAIL_)
        self.assertEqual(v["violations"], 1)

    def test_порог_относимости_отбрасывает_строку_ПОД_полом(self):
        """Мутация «пол = 0.0» промолчала и на предыдущем тесте — и правильно.

        СОВСЕМ чужая строка отбрасывается не полом, а нулевым весом: пол ей
        безразличен. Пол виден только на строке, у которой вес НЕ ноль, но
        ниже порога — именно ради неё он и стоит. Такой фикстуры в наборе не
        было, поэтому константу, названную в модуле константой-решением, не
        сторожил никто.

        Вес проверяется прямо здесь: тест, у которого фикстура уехала выше
        пола, замолчал бы молча и снова выглядел бы зелёным.
        """
        строка = факт(
            "kling-3.0",
            "holds_identity",
            "лицо держится на длинных планах и не подменяется при монтаже сцены " * 6,
            tier="operator",
            witnessed="прогнал и увидел",
        )
        индекс = FactIndex([строка])
        (попадание,) = индекс.search("монтаже", k=5, floor=0.0)
        self.assertGreater(попадание.score, 0.0)
        self.assertLess(попадание.score, 0.12)

        размечено = fa.mark_all([строка])
        v = fa.step_verdict("шаг", "монтаже", размечено)
        self.assertEqual(v["outcome"], UNMEASURED_)
        self.assertEqual(v["off_topic"], 1)

    def test_совсем_чужая_строка_уходит_в_мимо(self):
        """Т1 с другой стороны: мутация «порог = 0.0» тоже молчала.

        Фикстуры набора все были ОТНОСЯЩИМИСЯ, поэтому опустить пол было
        некуда — прибор не проверялся на том, ради чего пол стоит. Негативный
        контроль (И5): строка не о требовании обязана уйти в `off_topic`, а
        исход — стать третьим, а не «годно».
        """
        размечено = fa.mark_all(
            [
                факт(
                    "kling-3.0",
                    "holds_identity",
                    "лицо держится на длинных планах",
                    tier="operator",
                    witnessed="прогнал и увидел",
                )
            ]
        )
        v = fa.step_verdict("шаг", "счёт за электричество приходит вовремя", размечено)
        self.assertEqual(v["outcome"], UNMEASURED_)
        self.assertEqual(v["off_topic"], 1)


if __name__ == "__main__":
    unittest.main()


class ЗондОбъявленныйНоНеСостоявшийся(unittest.TestCase):
    """Тир `probe` значит «мы спросили работающий API и он ответил».

    До 2026-09-05 это принималось на слово: достаточно было написать в строке
    `tier: probe`, и она становилась вторым по силе свидетельством — выше
    статьи. ИЗМЕРЕНО на живой базе: из 16 строк с этим тиром ТРИ ведут на тред
    обсуждения `github.com/kijai/ComfyUI-WanVideoWrapper/issues/2048`, то есть
    чужая жалоба на форуме объявлялась «наблюдением работающей системы».

    Ожидаемое — литералы (Т2), сети нет (Т4). Входы настоящие, скопированы из
    базы вместе с адресом и тиром.
    """

    def строка(self, url: str, witnessed: str = "") -> fa.Fact:
        return fa.Fact(
            model="infinitetalk",
            attribute="failure_mode",
            value="в V2V сэмплер перерисовывает весь кадр",
            source_url=url,
            tier="probe",
            stated_on="2026-09-05",
            witnessed=witnessed,
        )

    def test_тред_обсуждения_это_не_состоявшийся_зонд(self):
        живой = "https://github.com/kijai/ComfyUI-WanVideoWrapper/issues/2048"
        self.assertFalse(fa.зонд_состоялся(self.строка(живой)))
        self.assertNotEqual(fa.mark(self.строка(живой)).kind, "witness")

    def test_адрес_апи_это_состоявшийся_зонд(self):
        """Негативный контроль (И5): правка не смеет обесценить тир целиком —
        иначе настоящие зонды перестанут отказывать шагам, и «не смогли» будет
        означать сломанный прибор, а не честный вердикт."""
        живой = "https://queue.fal.run/fal-ai/latentsync"
        self.assertTrue(fa.зонд_состоялся(self.строка(живой)))
        self.assertEqual(fa.mark(self.строка(живой)).kind, "witness")

    def test_witnessed_перевешивает_форму_адреса(self):
        """Наблюдение, записанное в строке, — самое сильное, что у неё есть, и
        адрес его не отменяет."""
        живой = "https://github.com/kijai/ComfyUI-WanVideoWrapper/issues/2048"
        строка = self.строка(живой, witnessed="один POST, HTTP 429, code 1102")
        self.assertTrue(fa.зонд_состоялся(строка))
        self.assertEqual(fa.mark(строка).kind, "witness")

    def test_другие_формы_документа_тоже_не_зонд(self):
        for адрес in (
            "https://github.com/x/y/discussions/12",
            "https://github.com/x/y/blob/main/README.md",
            "https://example.test/docs/limits.html",
            "https://example.test/paper.pdf",
        ):
            self.assertFalse(fa.зонд_состоялся(self.строка(адрес)), адрес)

    def test_оператор_под_это_правило_не_попадает(self):
        """Второй негативный контроль: правило про `probe`, и расширять его на
        `operator` нельзя — там наблюдение обеспечено обязательным `witnessed`,
        а не формой адреса."""
        строка = fa.Fact(
            model="x",
            attribute="failure_mode",
            value="v",
            source_url="https://github.com/x/y/issues/1",
            tier="operator",
            stated_on="2026-09-05",
            witnessed="владелец запустил и увидел",
        )
        self.assertEqual(fa.mark(строка).kind, "witness")
