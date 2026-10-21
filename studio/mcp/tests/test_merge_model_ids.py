"""Одна модель — одно имя: написания, дробящие факты модели надвое.

ЗАЧЕМ, ИЗМЕРЕНО 2026-08-27. База держала 211 имён моделей, и пять из них были
одной моделью дважды или трижды:

    eleven-v3(6), eleven_v3(1), elevenlabs-eleven-v3(4)
    gpt-image-2(13), gpt_image_2(1)

Никто не замечает, потому что ничто не краснеет: спросивший `eleven-v3`
получает ответ по шести фактам, тогда как модель их держит одиннадцать.

Тот же дефект на именах АТРИБУТОВ дороже: `licence` против `license` — это
research-only модель, уехавшая в продакшен, потому что лицензионный факт лёг
под вторым написанием и в ответ не попал.

Обе таблицы стояли без охраны: поймано ратчетом R7 2026-09-06.
Ожидаемое — литералы (Т2), сети нет (Т4), диска не нужно (Т5).
"""

from __future__ import annotations

import importlib.util
import tempfile
import unittest
from dataclasses import dataclass
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "merge_model_ids",
    Path(__file__).resolve().parents[3] / "scripts" / "merge_model_ids.py",
)
assert _SPEC and _SPEC.loader
слияние = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(слияние)


@dataclass(frozen=True)
class Строка:
    model: str
    attribute: str


@dataclass(frozen=True)
class Факт:
    """Ровно те поля, которые перезапись отдаёт обратно в `record`."""

    model: str
    attribute: str
    value: str = "0.8"
    source_url: str = "https://arxiv.org/abs/2311.17982"
    tier: str = "paper"
    stated_on: str = "2026-09-05"
    note: str = ""
    fix: str = ""
    read_directly: bool | None = None


class ЧужоеНаписаниеСводитсяКВендорскому(unittest.TestCase):
    def test_имя_модели_сводится(self):
        self.assertEqual(("eleven_v3", "price"), слияние.canonical_of(Строка("eleven-v3", "price")))
        self.assertEqual(
            ("eleven_v3", "price"),
            слияние.canonical_of(Строка("elevenlabs-eleven-v3", "price")),
        )

    def test_имя_атрибута_сводится(self):
        """`licence` против `license`: пропущенный факт о лицензии — это
        research-only модель, уехавшая в продакшен."""
        self.assertEqual(
            ("kling-3.0", "license"), слияние.canonical_of(Строка("kling-3.0", "licence"))
        )

    def test_сводятся_оба_имени_разом(self):
        self.assertEqual(
            ("eleven_v3", "license"),
            слияние.canonical_of(Строка("eleven-v3", "licence")),
        )

    def test_незнакомое_написание_остаётся_собой(self):
        """Негативный контроль (И5): таблица, переписывающая всё подряд, слила
        бы разные модели в одну — это тот же дефект наоборот и дороже."""
        self.assertEqual(
            ("kling-3.0", "max_seconds"),
            слияние.canonical_of(Строка("kling-3.0", "max_seconds")),
        )
        self.assertEqual(
            ("eleven_v3_conversational", "price"),
            слияние.canonical_of(Строка("eleven_v3_conversational", "price")),
        )

    def test_цель_слияния_сама_не_слита(self):
        """Никакое каноническое имя не стоит слева: иначе слияние зациклится
        или уедет на третье написание, и «одно имя» перестанет быть одним."""
        for чужое, своё in слияние.MERGES.items():
            self.assertNotIn(своё, слияние.MERGES, f"{чужое} -> {своё} -> ещё дальше")
        for чужое, своё in слияние.ATTRIBUTE_MERGES.items():
            self.assertNotIn(своё, слияние.ATTRIBUTE_MERGES, f"{чужое} -> {своё}")

    def test_имя_не_сводится_само_к_себе(self):
        """Запись `x -> x` ничего не делает и читается как сделанная работа."""
        for чужое, своё in слияние.MERGES.items():
            self.assertNotEqual(чужое, своё)

    def test_таблица_написаний_целиком_литералом(self):
        """Все 14 записей литералом (Т2), а не «две из них проверены».

        До 2026-09-06 таблицу охраняли только общие свойства (цель не слита,
        имя не сводится само к себе) плюс два имени, названные поимённо в
        других тестах. ИЗМЕРЕНО подменой: удаление `gpt_image_2 -> gpt-image-2`
        — одного из ДВУХ дефектов, ради которых файл написан, — оставляло все
        тесты зелёными. Двенадцать из четырнадцати записей можно было снять
        молча, и каждая снятая запись возвращает свой измеренный дефект:
        модель отвечает от половины своих фактов.

        Таблица обязана РАСТИ осознанно: новое написание — это новая строка
        и здесь тоже, иначе оно приходит вместе с чьим-то «поправил рядом».
        """
        self.assertEqual(
            {
                "eleven-v3": "eleven_v3",
                "elevenlabs-eleven-v3": "eleven_v3",
                "eleven-flash-v2.5": "eleven_flash_v2_5",
                "eleven-flash-v2-5": "eleven_flash_v2_5",
                "eleven-flash-v2": "eleven_flash_v2",
                "eleven-multilingual-v2": "eleven_multilingual_v2",
                "elevenlabs-multilingual-v2": "eleven_multilingual_v2",
                "eleven-multilingual-sts-v2": "eleven_multilingual_sts_v2",
                "eleven-turbo-v2-5": "eleven_turbo_v2_5",
                "elevenlabs-turbo-v2.5": "eleven_turbo_v2_5",
                "eleven-turbo-v2": "eleven_turbo_v2",
                "eleven-v3-conversational": "eleven_v3_conversational",
                "gpt_image_2": "gpt-image-2",
                "elevenlabs-*": "eleven-*",
            },
            dict(слияние.MERGES),
        )

    def test_атрибут_licence_в_таблице(self):
        """Литерал (Т2). Единственная запись таблицы атрибутов, и её пропажа
        молча вернула бы дефект, который дороже всех прочих в этом файле."""
        self.assertEqual({"licence": "license"}, dict(слияние.ATTRIBUTE_MERGES))


class ОтказПереносаОтличаетсяОтНегодностиСамойСтроки(unittest.TestCase):
    """Р1: третий исход не сворачивается в «не годно».

    Правила записи строже правил, действовавших когда строка легла в базу:
    с 7900a37 ступень `paper` требует адреса, по которому статью перепроверить.
    Старая строка под чужим написанием не переносится НИКОГДА, и без этой
    развилки сведение имён было бы навсегда красным по причине, к сведению имён
    отношения не имеющей.
    """

    def setUp(self) -> None:
        """Каждая проба — в СВОЙ файл. Без явного пробника подмена «пробник по
        умолчанию — живая база» заставила бы эти тесты дописать строки в базу
        прежде, чем покраснеть; наблюдалось 2026-09-06."""
        self._каталог = tempfile.TemporaryDirectory()
        self.addCleanup(self._каталог.cleanup)
        self.пробник = Path(self._каталог.name) / "probe.jsonl"

    def test_строка_негодная_сама_по_себе_опознаётся(self):
        """Адрес — репозиторий кода к статье: не перепроверить, и под прежним
        именем такая строка тоже не запишется."""
        плохая = Факт("eleven-v3", "benchmark_score", source_url="https://github.com/V/RAPO")
        self.assertTrue(слияние.отказ_из_за_самой_строки(плохая, self.пробник))

    def test_годная_строка_не_объявляется_негодной(self):
        """Негативный контроль (И5): развилка, отвечающая «дело в строке» на
        всё подряд, превратила бы любой сбой переноса в третий исход и спрятала
        бы настоящую поломку."""
        хорошая = Факт("eleven-v3", "benchmark_score")
        self.assertFalse(слияние.отказ_из_за_самой_строки(хорошая, self.пробник))

    def test_проба_идёт_в_отдельный_файл_а_не_в_базу(self):
        """Проба — это ЗАПИСЬ. Уйди она в живую базу, сведение имён само
        добавляло бы туда строки под чужими написаниями.

        Смотрим на АРГУМЕНТ вызова, а не на последствие: последствие пришлось
        бы наблюдать по живому файлу, то есть под подменой пачкать базу. Первая
        версия этого теста передавала пробник явно и потому подмену «пробник по
        умолчанию — живая база» не ловила (Т1, измерено 2026-09-06).
        """
        видели: list = []
        настоящий = слияние.advice.record

        def перехват(*args, **kwargs):
            """Перехват НЕ зовёт настоящую запись: иначе под подменой «пробник
            по умолчанию — живая база» тест сам бы и дописал строку в базу,
            прежде чем покраснеть. Проверено: так и было."""
            видели.append(kwargs.get("path"))
            return {"outcome": "pass", "written": None, "note": ""}

        слияние.advice.record = перехват
        try:
            слияние.отказ_из_за_самой_строки(Факт("eleven-v3", "max_seconds"))
        finally:
            слияние.advice.record = настоящий

        self.assertEqual(1, len(видели))
        путь = видели[0]
        self.assertIsNotNone(путь)
        self.assertNotEqual(Path(путь), Path(слияние.DEFAULT_FACTS_PATH))
        self.assertFalse(Path(путь).exists(), "временный каталог обязан быть убран за собой")

    def test_проба_пишет_ровно_одну_строку_в_свой_файл(self):
        with tempfile.TemporaryDirectory() as каталог:
            пробник = Path(каталог) / "probe.jsonl"
            self.assertFalse(
                слияние.отказ_из_за_самой_строки(Факт("eleven-v3", "max_seconds"), пробник)
            )
            записано = [s for s in пробник.read_text(encoding="utf-8").splitlines() if s.strip()]
            self.assertEqual(1, len(записано))
            self.assertIn("eleven-v3", записано[0])


class СведениеПоСвёртке(unittest.TestCase):
    """2026-10-14, аудит ae94057: план берёт ВСЕ группы, которые сводит
    свёртка, применяется только по `--apply`, переносит строку целиком и
    сохраняет прежнее написание в `asked_as`. Всё — на временной базе (Т5)."""

    СТРОКИ = (
        {
            "model": "seedance2",
            "attribute": "max_seconds",
            "value": "15",
            "source_url": "https://docs.dev.runwayml.com/openapi.json",
            "tier": "portal",
            "stated_on": "2026-08-27",
            "note": "исходная нота",
            "read_directly": True,
            "witnessed": "",
            "contra": None,
        },
        {
            "model": "seedance-2.0",
            "attribute": "fps",
            "value": "24",
            "source_url": "https://seed.bytedance.com/x",
            "tier": "vendor",
            "stated_on": "2026-08-27",
        },
        {
            "model": "seedance-2.0",
            "attribute": "fps",
            "value": "24",
            "source_url": "https://seed.bytedance.com/x",
            "tier": "vendor",
            "stated_on": "2026-08-27",
        },
        {
            "model": "kling-3.0",
            "attribute": "fps",
            "value": "24",
            "source_url": "https://kling.example/x",
            "tier": "blog",
            "stated_on": "2026-08-27",
        },
    )

    def setUp(self) -> None:
        import json

        self._каталог = tempfile.TemporaryDirectory()
        self.addCleanup(self._каталог.cleanup)
        self.путь = Path(self._каталог.name) / "facts.jsonl"
        self.путь.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in self.СТРОКИ), encoding="utf-8"
        )

    def test_группа_свёртки_в_плане(self):
        from studio.selfrag.facts import load_facts

        self.assertEqual(
            {"seedance2": "seedance-2.0"}, слияние.canonical_by_fold(load_facts(self.путь))
        )

    def test_по_умолчанию_ничего_не_пишется(self):
        до = self.путь.read_bytes()
        self.assertEqual(0, слияние.main(["--path", str(self.путь)]))
        self.assertEqual(до, self.путь.read_bytes())

    def test_применение_переносит_целиком_и_ничего_не_теряет(self):
        import json

        from studio.selfrag.facts import load_facts

        до = len(load_facts(self.путь))
        self.assertEqual(0, слияние.main(["--apply", "--path", str(self.путь)]))
        стоят = load_facts(self.путь)
        self.assertEqual(до, len(стоят))
        self.assertEqual(
            ["kling-3.0", "seedance-2.0", "seedance-2.0"], sorted(f.model for f in стоят)
        )
        перенесённая = [
            json.loads(x)
            for x in self.путь.read_text(encoding="utf-8").splitlines()
            if '"asked_as"' in x
        ]
        self.assertEqual(1, len(перенесённая))
        self.assertEqual("seedance2", перенесённая[0]["asked_as"])
        self.assertEqual("исходная нота", перенесённая[0]["note"])
        self.assertIs(True, перенесённая[0]["read_directly"])
        self.assertEqual("portal", перенесённая[0]["tier"])
        self.assertEqual(0, слияние._check(self.путь))

    def test_повторный_прогон_ничего_не_дописывает(self):
        слияние.main(["--apply", "--path", str(self.путь)])
        после = self.путь.read_bytes()
        слияние.main(["--apply", "--path", str(self.путь)])
        self.assertEqual(после, self.путь.read_bytes())

    def test_гейт_краснеет_на_неслитом(self):
        """И5: `--check` до применения — красный."""
        self.assertEqual(1, слияние._check(self.путь))


if __name__ == "__main__":
    unittest.main()
