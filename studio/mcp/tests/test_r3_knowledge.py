"""Раунд 3, агент D: база знаний, честность, имена (2026-10-15).

Пункты аудита 11 (опровержение — не провал), 12 (сроки снятия по маршрутам),
15 (окно свежести по атрибуту), имена (`modelnames`) и сторож тестов гейта,
запущенный из рабочей копии `.claude/worktrees/…`.

Ожидаемые значения — литералы (Т2), сети нет (Т4), у каждого правила обе
стороны (И5). Дата «сегодня» задаётся явно там, где решает календарь.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from studio import factaxis as fa
from studio import lifecycle as L
from studio import planner as P
from studio.mcp import advice
from studio.selfrag import modelnames, registry
from studio.selfrag.facts import Fact, load_facts

СЕГОДНЯ = date(2026, 10, 15)
_КОРЕНЬ = Path(__file__).resolve().parents[3]


def факт(model: str, attribute: str, value: str, contra: bool | None = None) -> Fact:
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url=f"https://vendor.example/{attribute}",
        tier="probe",
        stated_on="2026-09-05",
        contra=contra,
    )


def дней_назад(n: int) -> str:
    return (date.today() - timedelta(days=n)).isoformat()


def строка(model: str, attribute: str, value: str, url: str, возраст: int = 5) -> dict:
    return {
        "model": model,
        "attribute": attribute,
        "value": value,
        "source_url": url,
        "tier": "vendor",
        "stated_on": дней_назад(возраст),
    }


class ВременнаяБаза(unittest.TestCase):
    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.путь = Path(self._dir.name) / "facts.jsonl"

    def база(self, *строки: dict) -> None:
        self.путь.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in строки), encoding="utf-8"
        )


# --- пункт 11 ---------------------------------------------------------------


class П11_ОпровержениеНеПровал(unittest.TestCase):
    ОПРОВЕРЖЕНИЕ = "ОПРОВЕРГНУТО: модель моргает, два моргания за 6.59 с"
    ПРОВАЛ = "мелкое лицо теряет структуру"

    def test_знак_едет_в_доказательство(self) -> None:
        строки, *_ = P.evidence_for([факт("m", "failure_mode", self.ОПРОВЕРЖЕНИЕ, False)], {})
        self.assertIs(строки[0].contra, False)

    def test_худшая_новость_не_берёт_опровержение(self) -> None:
        записи: list[dict] = [
            {"attribute": "failure_mode", "value": self.ОПРОВЕРЖЕНИЕ, "contra": False},
            {"attribute": "failure_mode", "value": self.ПРОВАЛ, "contra": None},
        ]
        self.assertEqual(P.худшая_новость(записи)["value"], self.ПРОВАЛ)

    def test_без_знака_failure_mode_остаётся_провалом(self) -> None:
        """Обратная сторона: имя атрибута по-прежнему решает, если знака нет."""
        self.assertTrue(fa.is_contra_row({"attribute": "failure_mode", "value": "x"}))
        self.assertFalse(
            fa.is_contra_row({"attribute": "failure_mode", "value": "x", "contra": False})
        )

    def test_строка_вердикта_несёт_знак(self) -> None:
        m = fa.mark(факт("m", "failure_mode", self.ОПРОВЕРЖЕНИЕ, False))
        self.assertIs(fa._row(m)["contra"], False)


class П11_СоветНеПишетОпровержениеВПровалы(ВременнаяБаза):
    def test_failure_modes_без_опровержения(self) -> None:
        опровержение = строка(
            "m-1", "failure_mode", "ОПРОВЕРГНУТО: моргает", "https://vendor.example/p"
        )
        опровержение["contra"] = False
        self.база(
            опровержение,
            строка("m-1", "failure_mode", "лица плывут", "https://vendor.example/q"),
        )
        провалы = [f["value"] for f in advice.advise("m-1", path=self.путь)["failure_modes"]]
        self.assertEqual(провалы, ["лица плывут"])


class П11_ЖиваяБаза(unittest.TestCase):
    def test_minimax_h3_не_читает_опровержение_как_провал(self) -> None:
        свои = [f for f in load_facts() if f.model == "minimax-h3"]
        строки, *_ = P.evidence_for(свои, {})
        записи = [{"attribute": e.attribute, "value": e.value, "contra": e.contra} for e in строки]
        self.assertNotIn("ОПРОВЕРГНУТО", P.худшая_новость(записи)["value"])
        self.assertNotIn("не моргают", P.худшая_новость(записи)["value"])

    def test_опровержение_в_базе_одно(self) -> None:
        """Две одинаковые строки лога (3354/3369) сводятся загрузкой в одну."""
        опровержения = [
            f for f in load_facts() if f.model == "minimax-h3" and "ОПРОВЕРГНУТО" in f.value
        ]
        self.assertEqual(len(опровержения), 1)
        self.assertIs(опровержения[0].contra, False)


# --- пункт 12 ---------------------------------------------------------------


class П12_СрокиПоМаршрутам(unittest.TestCase):
    ОДИН_ЗАКРЫТ = [
        ("deprecation_date_via_gemini", "2026-06-25"),
        ("deprecation_date_via_vertex_ai_language_models", "2027-05-28"),
    ]

    def test_маршрут_из_имени(self) -> None:
        self.assertEqual(L.маршрут("deprecation_date_via_gemini"), "gemini")
        self.assertEqual(L.маршрут("deprecation_date"), "")
        self.assertIsNone(L.маршрут("price"))

    def test_один_маршрут_закрыт_модель_не_снята(self) -> None:
        итог = L.по_маршрутам(self.ОДИН_ЗАКРЫТ, сегодня=СЕГОДНЯ)
        self.assertEqual(итог.outcome, "не смогли")
        self.assertIn("gemini: закрыт с 2026-06-25", итог.note)
        self.assertIn("vertex_ai_language_models: закрывается 2027-05-28", итог.note)

    def test_все_маршруты_закрыты_модель_снята(self) -> None:
        итог = L.по_маршрутам([("deprecation_date_via_openai", "2026-09-24")], сегодня=СЕГОДНЯ)
        self.assertEqual(итог.outcome, "не годно")

    def test_срок_сегодня_уже_закрыт(self) -> None:
        """Граница: дата, равная сегодняшней, — закрыто (Т1, обе стороны)."""
        self.assertEqual(
            L.по_маршрутам(
                [("deprecation_date_via_gemini", "2026-10-15")], сегодня=СЕГОДНЯ
            ).outcome,
            "не годно",
        )
        self.assertEqual(
            L.по_маршрутам(
                [("deprecation_date_via_gemini", "2026-10-16")], сегодня=СЕГОДНЯ
            ).outcome,
            "не смогли",
        )

    def test_нет_маршрутов_годно(self) -> None:
        self.assertEqual(L.по_маршрутам([("price", "$1")], сегодня=СЕГОДНЯ).outcome, "годно")

    def test_маршрутная_строка_одна_модель_не_снимает(self) -> None:
        итог = L.разобрать("2026-06-25", "deprecation_date_via_gemini", сегодня=СЕГОДНЯ)
        self.assertEqual(итог.outcome, "годно")

    def test_срок_без_маршрута_судит_модель(self) -> None:
        итог = L.разобрать("2026-06-25", "deprecation_date", сегодня=СЕГОДНЯ)
        self.assertEqual((итог.outcome, итог.когда), ("не годно", "2026-06-25"))


class П12_План(unittest.TestCase):
    def test_nano_banana_pro_предупреждение_по_маршрутам(self) -> None:
        факты = [факт("nbp", a, v) for a, v in П12_СрокиПоМаршрутам.ОДИН_ЗАКРЫТ]
        положение, нота = P.life_stance(факты, СЕГОДНЯ)
        self.assertEqual(положение, "снятие объявлено, срок впереди")
        self.assertIn("gemini: закрыт с 2026-06-25", нота)

    def test_veo_lite_срок_впереди(self) -> None:
        факты = [факт("vl", "deprecation_date_via_gemini", "2026-10-22")]
        положение, нота = P.life_stance(факты, СЕГОДНЯ)
        self.assertEqual(положение, "снятие объявлено, срок впереди")
        self.assertIn("gemini: закрывается 2026-10-22", нота)

    def test_все_маршруты_закрыты_снята(self) -> None:
        факты = [факт("s", "deprecation_date_via_openai", "2026-09-24")]
        self.assertEqual(P.life_stance(факты, СЕГОДНЯ)[0], "снята: срок прошёл")

    def test_без_сроков_жива(self) -> None:
        self.assertEqual(P.life_stance([факт("k", "fps", "24")], СЕГОДНЯ)[0], "о снятии не сказано")


class П12_Реестр(unittest.TestCase):
    def test_без_карточки_все_закрыты_это_отказ(self) -> None:
        ответ = registry.availability(
            "no-such-card",
            today=СЕГОДНЯ,
            route_rows=[("deprecation_date_via_openai", "2026-09-24")],
        )
        self.assertEqual((ответ["outcome"], ответ["violations"]), ("fail", 1))

    def test_один_открыт_исход_не_меняется(self) -> None:
        ответ = registry.availability(
            "no-such-card", today=СЕГОДНЯ, route_rows=П12_СрокиПоМаршрутам.ОДИН_ЗАКРЫТ
        )
        self.assertEqual(ответ["outcome"], "could not measure")
        self.assertIn("gemini: закрыт с 2026-06-25", ответ["note"])

    def test_без_строк_ответ_карточки(self) -> None:
        self.assertNotIn("routes", registry.availability("no-such-card", today=СЕГОДНЯ))


class П12_Совет(ВременнаяБаза):
    def test_совет_называет_маршруты_и_не_снимает_модель(self) -> None:
        self.база(
            строка("nbp", "deprecation_date_via_gemini", "2026-06-25", "https://p.example/a"),
            строка("nbp", "deprecation_date_via_vertex_ai", "2099-05-28", "https://p.example/a"),
            строка("nbp", "max_resolution", "4K", "https://vendor.example/b"),
        )
        ответ = advice.advise("nbp", path=self.путь)
        self.assertIn("ПО МАРШРУТАМ", ответ["note"])
        self.assertNotIn("СНЯТА С ОБСЛУЖИВАНИЯ", ответ["note"])
        маршруты = sorted(с.get("route") for с in ответ["lifecycle"])
        self.assertEqual(маршруты, ["gemini", "vertex_ai"])
        self.assertIn("gemini: закрыт с 2026-06-25", ответ["availability"]["note"])


# --- пункт 15 ---------------------------------------------------------------


class П15_ОкноСвежести(ВременнаяБаза):
    def test_окна_литералами(self) -> None:
        self.assertEqual(advice.окно_свежести("price_per_second_usd"), 30)
        self.assertEqual(advice.окно_свежести("license"), 180)
        self.assertEqual(advice.окно_свежести("architecture"), 180)
        self.assertEqual(advice.окно_свежести("fps"), 180)
        self.assertEqual(advice.окно_свежести("max_resolution"), 180)
        self.assertEqual(advice.окно_свежести("failure_mode"), 30)

    def test_лицензия_180_свежая_181_помечена(self) -> None:
        """Т1: граница долгого окна с обеих сторон."""
        self.база(
            строка("m-1", "license", "MIT", "https://vendor.example/a", 180),
            строка("m-1", "max_seconds", "10", "https://vendor.example/b", 1),
            строка("m-2", "license", "MIT", "https://vendor.example/a", 181),
            строка("m-2", "max_seconds", "10", "https://vendor.example/b", 1),
        )
        self.assertEqual(advice.advise("m-1", path=self.путь)["possibly_stale"], [])
        self.assertEqual(advice.advise("m-2", path=self.путь)["possibly_stale"], ["license"])

    def test_цена_по_прежнему_30(self) -> None:
        self.база(
            строка("m-1", "license", "MIT", "https://vendor.example/a", 100),
            строка("m-1", "price_per_second", "$1", "https://vendor.example/c", 31),
            строка("m-1", "fps", "24", "https://vendor.example/d", 100),
        )
        ответ = advice.advise("m-1", path=self.путь)
        self.assertEqual(ответ["possibly_stale"], ["price_per_second"])
        self.assertEqual(ответ["claims"]["license"]["stale_after_days"], 180)


# --- имена ------------------------------------------------------------------


class Имена(unittest.TestCase):
    ИЗВЕСТНЫ = [
        "minimax-hailuo-02",
        "minimax-hailuo-02-pro-i2v",
        "kling-3.0",
        "kling-3.0-pro-i2v",
        "heygen-avatar4-image-to-video",
        "heygen-avatar4-digital-twin",
        "topaz-upscale-video-generative",
        "flux.1-kontext-pro",
    ]

    def разрешить(self, имя: str) -> tuple[str, ...]:
        return modelnames.resolve(имя, self.ИЗВЕСТНЫ).names

    def test_написания_сводятся(self) -> None:
        self.assertEqual(self.разрешить("hailou 02"), ("minimax-hailuo-02",))
        self.assertEqual(self.разрешить("hailuo-02"), ("minimax-hailuo-02",))
        # 4-й круг: «kling 3 pro» — вариант pro, а не корень (аудит имён).
        self.assertEqual(self.разрешить("kling3 pro"), ("kling-3.0-pro-i2v",))
        self.assertEqual(self.разрешить("heygen avatar 4"), ("heygen-avatar4-image-to-video",))
        self.assertEqual(self.разрешить("topaz starlight"), ("topaz-upscale-video-generative",))
        self.assertEqual(self.разрешить("flux-kontext-pro"), ("flux.1-kontext-pro",))

    def test_соседи_не_склеиваются(self) -> None:
        """И5: целые имена не трогают длинных соседей."""
        self.assertEqual(
            self.разрешить("heygen-avatar4-digital-twin"), ("heygen-avatar4-digital-twin",)
        )
        self.assertEqual(self.разрешить("kling-3.0-pro-i2v"), ("kling-3.0-pro-i2v",))
        self.assertEqual(self.разрешить("hailuo-02 pro i2v"), ("minimax-hailuo-02-pro-i2v",))

    def test_у_каждого_тождества_есть_свидетельство(self) -> None:
        for имя in ("hailou 02", "hailuo-02", "kling3 pro", "heygen avatar 4", "topaz starlight"):
            with self.subTest(имя=имя):
                self.assertTrue(modelnames.resolve(имя, self.ИЗВЕСТНЫ).evidence)


# --- сторож тестов гейта ------------------------------------------------------


_СПЕЦ = importlib.util.spec_from_file_location(
    "check_tests_gated_r3", _КОРЕНЬ / "scripts" / "check_tests_gated.py"
)
assert _СПЕЦ and _СПЕЦ.loader
cg = importlib.util.module_from_spec(_СПЕЦ)
_СПЕЦ.loader.exec_module(cg)


class СторожИзРабочейКопии(unittest.TestCase):
    def дерево(self, корень: Path) -> Path:
        (корень / "scripts").mkdir(parents=True)
        гейт = корень / "scripts" / "check"
        гейт.write_text("python -m unittest discover -s studio/tests -t .\n", encoding="utf-8")
        for имя in (
            "studio/__init__.py",
            "studio/tests/__init__.py",
            "studio/tests/test_один.py",
            "studio/.claude/worktrees/чужая/studio/tests/test_чужой.py",
        ):
            (корень / имя).parent.mkdir(parents=True, exist_ok=True)
            (корень / имя).write_text("", encoding="utf-8")
        return гейт

    def test_корень_в_claude_worktrees_считается(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            корень = Path(tmp) / ".claude" / "worktrees" / "agent-x"
            гейт = self.дерево(корень)
            итог = cg.проверить(корень, гейт)
            self.assertEqual((итог["checked"], итог["violations"]), (1, 0))

    def test_вложенная_рабочая_копия_пропускается(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            корень = Path(tmp) / "repo"
            гейт = self.дерево(корень)
            найдено = [п.name for п in cg.файлы_тестов(корень, ("studio",))]
            self.assertEqual(найдено, ["test_один.py"])
            self.assertEqual(cg.проверить(корень, гейт)["checked"], 1)


if __name__ == "__main__":
    unittest.main()
