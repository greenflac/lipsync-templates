"""Отказ авторизации — не измерение предела модели.

ВОСПРОИЗВЕДЕНО 2026-09-05 независимым аудитом: подменённый `urlopen`, отдающий
`HTTPError 401 {"error":"invalid api key"}`, давал

    outcome: pass
    suggested_fact: tier 'probe', attribute 'duration', source_url вендора,
                    note «probe: sent duration=10000000, got 401»

То же на 403, 404, 429 и 500: PASS выдавался на ЛЮБОЙ ответ хоста. Докстрока
объясняет, почему 4xx это хорошо — «ошибка валидации И ЕСТЬ измерение», — и это
верно для 400/422, где сервер называет предел. Но 401 говорит про КЛЮЧ, 404 про
АДРЕС, 429 про частоту, 5xx про самочувствие сервера: о пределах модели они не
говорят ничего.

ЧЕМ ОПАСНО. Ассистент, следующий подсказке инструмента, запишет в базу фактов
вендорский предел, выведенный из отказа авторизации. Это уверенное и неверное
утверждение о модели, у которого при этом ПРАВИЛЬНАЯ ссылка на вендора —
самый убедительный вид вранья.

Коды — литералы (Т2).
"""

from __future__ import annotations

import io
import unittest
import urllib.error
from unittest import mock

from studio.mcp import probe as pb

ИЗМЕРЯЮТ = (400, 422)
НЕ_ИЗМЕРЯЮТ = (401, 403, 404, 429, 500, 503)


def _ответ(код: int, тело: str):
    def подмена(*_a, **_k):
        raise urllib.error.HTTPError(
            "https://api.vendor.test/v1/videos", код, "err", {}, io.BytesIO(тело.encode())
        )

    return подмена


def _прогон(код: int, тело: str) -> dict:
    with mock.patch.object(pb, "_key_for", lambda host: ("k", "TEST_KEY")):
        with mock.patch("urllib.request.urlopen", _ответ(код, тело)):
            return pb.probe_limit(
                "https://api.vendor.test/v1/videos",
                "duration",
                10_000_000,
                payload={"model": "m"},
                why_wanted="предел длительности",
            )


class ОтказыРазныеПоРоду(unittest.TestCase):
    def test_валидация_остаётся_измерением(self) -> None:
        """Негативный контроль (И5): починка не должна отключить сам зонд."""
        for код in ИЗМЕРЯЮТ:
            with self.subTest(код=код):
                итог = _прогон(код, '{"error":"duration must be <= 15"}')
                self.assertEqual(итог["outcome"], "pass")
                self.assertIsNotNone(итог["suggested_fact"])

    def test_чужие_отказы_это_третий_исход_без_подсказки_факта(self) -> None:
        for код in НЕ_ИЗМЕРЯЮТ:
            with self.subTest(код=код):
                итог = _прогон(код, '{"error":"invalid api key"}')
                self.assertEqual(итог["outcome"], "could not measure", код)
                self.assertIsNone(итог["suggested_fact"], код)

    def test_нота_называет_что_именно_помешало(self) -> None:
        итог = _прогон(401, '{"error":"invalid api key"}')
        self.assertIn("401", итог["note"])
        self.assertIn("о пределе модели он не говорит", итог["note"])


if __name__ == "__main__":
    unittest.main()
