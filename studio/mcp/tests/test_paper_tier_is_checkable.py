"""Ступень `paper` требует адреса, по которому статью можно перепроверить.

ЗАЧЕМ. Ступени-МЕТОДЫ (`probe`, `operator`, `paper`, `benchmark`) берутся на
слово: никакой адрес не докажет, что у утверждения есть проверяемый метод.
Независимая проверка каналов 2026-09-05 показала, чем это кончается — три
строки на `probe` оказались чужим тредом обсуждения. Для `probe` дыра закрыта
в тот же день; здесь она закрывается для `paper`, у которого признак в адресе
ЕСТЬ: статья почти всегда несёт свой идентификатор.

ИЗМЕРЕНО на живой базе: из 175 строк тира `paper` признак несут 174.

Ожидаемое — литералы (Т2), сети нет (Т4), входы с обоих краёв (Т3).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from studio.mcp import advice


class АдресСтатьиОбязанБытьПроверяемым(unittest.TestCase):
    def setUp(self) -> None:
        self.цель = Path(tempfile.mkdtemp()) / "facts.jsonl"

    def записать(self, url: str) -> dict:
        return advice.record(
            "kling-3.0", "benchmark_score", "0.8", url, "paper", "2026-09-05", path=self.цель
        )

    def test_репозиторий_кода_это_не_адрес_статьи(self):
        """Живая строка базы: содержание научное, а адрес ведёт к коду, и по
        нему статью не перепроверить."""
        итог = self.записать("https://github.com/Vchitect/RAPO")
        self.assertEqual(итог["outcome"], "fail")
        self.assertIn("без признака статьи", итог["note"])
        self.assertIsNone(итог["written"])

    def test_arxiv_проходит(self):
        """Негативный контроль (И5): проверка, отвергающая все статьи, не
        отличается от запрета ступени."""
        self.assertEqual(self.записать("https://arxiv.org/abs/2311.17982")["outcome"], "pass")

    def test_зеркало_arxiv_проходит(self):
        """19 живых строк лежат не на arxiv.org, а на зеркале с тем же
        идентификатором; отвергать их значило бы потерять половину статей."""
        живой = (
            "https://huggingface.co/buckets/huggingchat/papers-content/resolve/2412/2412.09262.md"
        )
        self.assertEqual(self.записать(живой)["outcome"], "pass")

    def test_doi_openreview_acl_и_pdf_проходят(self):
        for url in (
            "https://doi.org/10.1145/3592433",
            "https://openreview.net/forum?id=abc",
            "https://aclanthology.org/2024.acl-long.1/",
            "https://example.test/paper.pdf",
        ):
            self.assertEqual(self.записать(url)["outcome"], "pass", url)

    def test_блог_на_ступени_paper_отвергается(self):
        итог = self.записать("https://someblog.example/why-video-models-fail")
        self.assertEqual(итог["outcome"], "fail")

    def test_другие_ступени_под_это_правило_не_попадают(self):
        """Правило про `paper`, и расширять его на соседей нельзя: у `blog` и
        `portal` ступень решает URL, у `probe` — состоявшийся запрос."""
        итог = advice.record(
            "kling-3.0",
            "max_seconds",
            "10",
            "https://github.com/Vchitect/RAPO",
            "blog",
            "2026-09-05",
            path=self.цель,
        )
        self.assertEqual(итог["outcome"], "pass")


if __name__ == "__main__":
    unittest.main()
