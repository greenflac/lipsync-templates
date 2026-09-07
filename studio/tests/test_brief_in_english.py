"""Английский бриф кончается тем же исходом, что его русский близнец.

ВОСПРОИЗВЕДЕНО 2026-09-07: словарь операций студии (`planner.OPERATIONS`) был
собран из русских подсказок, английские стояли только у липсинка. ИЗМЕРЕНО на
`studio/fixtures/briefs_english.jsonl`: сошлось 6 из 11; после английских
подсказок у семи операций — 11 из 11.

КРИТЕРИЙ — НЕ «ПЛАН СОБРАЛСЯ». Три ожидания, и среднее из них важнее крайних:
там, где по-русски продукт СПРАШИВАЕТ, по-английски он обязан спрашивать, а не
выдумывать шаги. Строки `молчим` — негативный контроль (И5): без них
расширение словаря неотличимо от «подсказки стали ловить что попало».
"""

from __future__ import annotations

import json
import pathlib
import unittest

from studio.mcp import server

ФИКСТУРА = pathlib.Path(__file__).resolve().parents[1] / "fixtures" / "briefs_english.jsonl"


def _набор() -> list[dict]:
    строки = ФИКСТУРА.read_text(encoding="utf-8").splitlines()
    return [json.loads(s) for s in строки if s.strip() and not s.startswith("//")]


def исход(ответ: dict) -> str:
    """Что продукт СДЕЛАЛ: собрал план, спросил или промолчал."""
    if ответ.get("steps"):
        return "план"
    if ответ.get("question"):
        return "вопрос"
    return "молчим"


class АнглийскийБриф(unittest.TestCase):
    def test_каждый_бриф_кончается_ожидаемым(self) -> None:
        расхождения = []
        for строка in _набор():
            ответ = json.loads(server.plan_pipeline(строка["бриф"]))
            факт = исход(ответ)
            if факт != строка["ждём"]:
                расхождения.append(f"{строка['id']}: ждём {строка['ждём']}, вышло {факт}")
        self.assertEqual([], расхождения)

    def test_негативный_контроль_непустой(self) -> None:
        """Набор без строк «молчим» проверял бы только щедрость словаря."""
        молчим = [с for с in _набор() if с["ждём"] == "молчим"]
        self.assertGreaterEqual(len(молчим), 3)

    def test_вопрос_есть_среди_ожиданий(self) -> None:
        self.assertTrue(any(с["ждём"] == "вопрос" for с in _набор()))

    def test_английский_близнец_даёт_те_же_шаги_что_русский(self) -> None:
        """Самая сильная форма критерия: не «план есть», а «план тот же»."""
        англ = json.loads(
            server.plan_pipeline("make a talking avatar ad in english, vertical for tiktok")
        )
        рус = json.loads(
            server.plan_pipeline(
                "сделай ролик с говорящим аватаром на английском, вертикальный для тиктока"
            )
        )
        self.assertEqual(
            [ш["step"] for ш in рус["steps"]],
            [ш["step"] for ш in англ["steps"]],
        )
        self.assertTrue(англ["steps"])

    def test_непонятый_английский_бриф_называет_понятные_обороты(self) -> None:
        """Прежняя нота велела «назвать работу по-русски» — лишняя работа для
        того, кто написал по-английски намеренно."""
        ответ = json.loads(server.plan_pipeline("What is your pricing for enterprise customers?"))
        self.assertEqual([], ответ["steps"])
        self.assertIn("talking head", ответ["note"])
        self.assertNotIn("словарь операций русский", ответ["note"])


if __name__ == "__main__":
    unittest.main()
