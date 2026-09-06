"""Ступень `paper` требует адреса, по которому статью можно перепроверить.

ЗАЧЕМ. Ступени-МЕТОДЫ (`probe`, `operator`, `paper`, `benchmark`) берутся на
слово: никакой адрес не докажет, что у утверждения есть проверяемый метод.
Независимая проверка каналов 2026-09-05 показала, чем это кончается — три
строки на `probe` оказались чужим тредом обсуждения. Для `probe` дыра закрыта
в тот же день; здесь она закрывается для `paper`, у которого признак в адресе
ЕСТЬ: статья почти всегда несёт свой идентификатор.

ИЗМЕРЕНО на живой базе 2026-09-06: из 184 строк тира `paper` признак несут 183.

Первая версия признака была одновременно СЛИШКОМ СТРОГОЙ и СЛИШКОМ СЛАБОЙ, и
обе стороны назвала независимая проверка: отвергались NeurIPS, `dl.acm.org/doi`,
IEEE, CVF, Springer, MLR, bioRxiv и старый формат arxiv (`abs/cs/0501001`) —
это отказ записать настоящую статью; и принимались любой `.pdf` (включая
рекламную презентацию), любой сегмент вида `NNNN.NNNNN` и чужой блог, в адресе
которого `openreview.net` стоит подстрокой.

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

    def test_настоящие_площадки_проходят(self):
        """Отказ по этим адресам — отказ записать настоящую статью. Взяты и
        краю списка, и его середина (Т3)."""
        for url in (
            "https://doi.org/10.1145/3592433",
            "https://openreview.net/forum?id=abc",
            "https://aclanthology.org/2024.acl-long.1/",
            "https://arxiv.org/abs/cs/0501001",
            "https://dl.acm.org/doi/10.1145/3592433",
            "https://proceedings.neurips.cc/paper_files/paper/2024/hash/a.html",
            "https://openaccess.thecvf.com/content/CVPR2024/papers/x.pdf",
            "https://ieeexplore.ieee.org/document/10123456",
            "https://link.springer.com/article/10.1007/s11263-024-02001",
            "https://proceedings.mlr.press/v235/smith24a.html",
            "https://www.biorxiv.org/content/10.1101/2024.01.01.573",
        ):
            self.assertEqual(self.записать(url)["outcome"], "pass", url)

    def test_рекламная_презентация_это_не_статья(self):
        """`.pdf` сам по себе не признак: у вендора в PDF лежат презентации.
        Признак — площадка, DOI или идентификатор arxiv."""
        итог = self.записать("https://vendor.example/decks/marketing-2026.pdf")
        self.assertEqual(итог["outcome"], "fail")

    def test_имя_площадки_подстрокой_в_чужом_адресе_не_считается(self):
        """Сравнение идёт по РЕГИСТРИРУЕМОМУ ДОМЕНУ. Раньше блог, у которого в
        пути стоит `openreview.net`, проходил как статья с OpenReview."""
        итог = self.записать("https://blog.example.com/why-openreview.net-is-broken")
        self.assertEqual(итог["outcome"], "fail")

    def test_число_похожее_на_идентификатор_не_идентификатор(self):
        """`9912.34567` — месяц 12 бывает, а вот `build-9912.34567` не сегмент
        пути целиком; и месяца 34 не существует."""
        for url in (
            "https://example.test/build-9912.34567/notes",
            "https://example.test/2434.09262/notes",
        ):
            self.assertEqual(self.записать(url)["outcome"], "fail", url)

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
