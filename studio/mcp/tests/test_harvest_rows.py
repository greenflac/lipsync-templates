"""Строка сбора: что не пускается в базу и почему именно это.

ЗАЧЕМ. `_malformed` — единственный автоматический фильтр между машинным сбором
и базой фактов. Аудит отвергает пустые цитаты руками, но аудит — это другой
агент, а агент не заменяет проверку, которая идёт каждый раз.

ИЗМЕРЕНО подменой 2026-09-06: `MIN_EVIDENCE_CHARS = 1` держал весь набор
зелёным — то есть «доказательством» становилась одна буква, и строка с пустой
по смыслу цитатой доезжала до базы под видом процитированной. Функция не была
покрыта ни одним тестом.

Ожидаемое — литералы (Т2), сети и диска нет (Т4, Т5).
"""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(КОРЕНЬ))
# `scripts/ingest_harvest.py` импортирует соседа по имени модуля, как это делает
# сам скрипт при запуске из `scripts/`; тесту нужен тот же путь.
sys.path.insert(0, str(КОРЕНЬ / "scripts"))

_SPEC = importlib.util.spec_from_file_location(
    "ingest_harvest", КОРЕНЬ / "scripts" / "ingest_harvest.py"
)
assert _SPEC and _SPEC.loader
сбор = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(сбор)


def строка(**поля):
    сырьё = {
        "model": "kling-3.0",
        "attribute": "max_seconds",
        "value": "10",
        "source_url": "https://example.test/docs",
        "tier": "vendor",
        "evidence": "maximum duration is 10 seconds",
        "read_directly": True,
    }
    сырьё.update(поля)
    return сырьё


class ЧтоНеДоезжаетДоБазы(unittest.TestCase):
    def test_годная_строка_проходит(self):
        """Негативный контроль (И5): фильтр, отвергающий всё, — это не фильтр,
        а выключенный канал."""
        self.assertEqual("", сбор._malformed(строка()))

    def test_каждое_обязательное_поле_проверяется_поодиночке(self):
        for поле in ("model", "attribute", "value", "source_url", "tier", "evidence"):
            self.assertEqual(f"empty {поле}", сбор._malformed(строка(**{поле: ""})), поле)

    def test_короткая_цитата_это_не_доказательство(self):
        """ГРАНИЦА С ОБЕИХ СТОРОН (Т3). Одиннадцать знаков — не цитата,
        двенадцать — уже цитата; на этом пороге и стоит решение."""
        self.assertEqual(
            "evidence too short to be a quotation", сбор._malformed(строка(evidence="a" * 11))
        )
        self.assertEqual("", сбор._malformed(строка(evidence="a" * 12)))

    def test_порог_цитаты_названо_числом(self):
        """Литерал (Т2): подмена порога обязана менять вердикт, а не молчать."""
        self.assertEqual(12, сбор.MIN_EVIDENCE_CHARS)

    def test_чужая_ступень_не_принимается(self):
        итог = сбор._malformed(строка(tier="слухи"))
        self.assertIn("is not one of", итог)

    def test_адрес_обязан_быть_адресом(self):
        self.assertEqual("source_url is not a URL", сбор._malformed(строка(source_url="docs")))

    def test_непрочитанная_страница_не_доезжает(self):
        """Строка, которую никто не открывал, — это чужой пересказ, и в базе
        он обязан лежать под другим флагом, а не приезжать сбором."""
        self.assertEqual("read_directly is not true", сбор._malformed(строка(read_directly=False)))


if __name__ == "__main__":
    unittest.main()
