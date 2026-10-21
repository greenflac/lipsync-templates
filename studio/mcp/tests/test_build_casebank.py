"""Сборка банка: чей это кейс и сколько их можно взять из одного места.

ДВА РЕШЕНИЯ, КОТОРЫЕ ЗДЕСЬ СТОРОЖАТСЯ.

`CLOSED_MODELS` — какие генераторы вообще спрашиваются. `imagenet` и `docci` —
настоящие фотографии, и вопрос «это фотография?» не тот, на котором меряют
агента: пустив их, мы мерили бы другое и отчитались бы тем же числом.

`CIVITAI_PER_VERSION` — сколько роликов берётся с ОДНОЙ версии модели. Витрина
одного загрузчика — это вкус одного автора; шестнадцать роликов оттуда меряют
автора, а не модель.

ИЗМЕРЕНО 2026-09-06 независимой приёмкой: я объявил модуль непокрываемым «без
банка» — и ошибся. Сеть и диск заменяются дублями (Т4): парчет, чистка снимка
и загрузчик подменяются, и обе константы становятся наблюдаемыми.
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

_SPEC = importlib.util.spec_from_file_location(
    "build_casebank", Path(__file__).resolve().parents[3] / "scripts" / "build_casebank.py"
)
assert _SPEC and _SPEC.loader
сборка = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(сборка)


class ПарчетДубль:
    """Отдаёт по одной строке на каждого генератора, без сети и без файла."""

    def __init__(self, модели: list[str]) -> None:
        self.модели = модели

    def read_row_group(self, group: int, columns=None):  # noqa: ARG002
        строки = [
            {
                "image": {"bytes": f"кадр-{м}-{group}".encode()},
                "model": м,
                "prompt": f"промпт {м}",
                "label": "fake",
                "type": "image",
            }
            for м in self.модели
        ]
        return mock.Mock(to_pylist=lambda: строки)


def собрать(модели: list[str], count: int = 10, *, остаток: list[str] | None = None):
    """Прогон `build_openfake` на дублях. Возвращает собранные кейсы."""
    with TemporaryDirectory() as каталог:
        with (
            mock.patch.multiple(
                сборка.C,
                remote_parquet=lambda *а, **к: ПарчетДубль(модели),
                strip_image=lambda blob, out: {
                    "stripped": ["comment"],
                    "remaining": остаток or [],
                    "bytes": len(blob),
                },
            ),
            mock.patch.object(сборка, "OUT", Path(каталог)),
        ):
            return сборка.build_openfake(count)


class ЧужиеГенераторыВБанкНеЕдут(unittest.TestCase):
    def test_настоящие_фотографии_не_берутся(self):
        собрано = собрать(["veo-3", "imagenet", "docci"])
        self.assertEqual(["veo-3"], sorted({к["truth"]["model"] for к in собрано}))

    def test_негативный_контроль_закрытая_модель_берётся(self):
        """Список, не пускающий никого, — это не список, а выключенный канал."""
        self.assertTrue(собрать(["veo-3"]))

    def test_список_генераторов_содержит_то_что_меряется(self):
        """Т2: имена названы здесь, а не импортированы из проверяемого модуля."""
        self.assertIn("veo-3", сборка.CLOSED_MODELS)
        self.assertIn("sora-2", сборка.CLOSED_MODELS)
        self.assertNotIn("imagenet", сборка.CLOSED_MODELS)
        self.assertNotIn("docci", сборка.CLOSED_MODELS)

    def test_с_одной_модели_берётся_не_больше_двух(self):
        """Тот же довод, что и `MAX_PER_PROVENANCE` у ретривера: иначе банк
        меряет вкус одного автора."""
        собрано = собрать(["veo-3"] * 6, count=10)
        self.assertEqual(2, len(собрано))

    def test_кейс_с_оставшимся_носителем_не_кладётся(self):
        """Чистка отчиталась, что носитель остался, — такой кейс показывать
        слепому оценщику нельзя, и он пропускается, а не правится."""
        self.assertEqual([], собрать(["veo-3"], остаток=["comment"]))

    def test_снятые_носители_записаны_в_истину_кейса(self):
        """Не флагом «почищено», а списком: иначе не перепроверить, что сняли."""
        (кейс,) = собрать(["veo-3"], count=1)
        self.assertEqual(["comment"], кейс["truth"]["stripped_carriers"])
        self.assertFalse(кейс["commercial_ok"])


if __name__ == "__main__":
    unittest.main()
