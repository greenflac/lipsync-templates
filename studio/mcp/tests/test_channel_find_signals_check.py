"""Офлайновая проверка канала подсказок: связен ли УЖЕ СНЯТЫЙ прогон банка.

ЧТО СТОРОЖИТСЯ. Короткий список строится склейкой трёх файлов: счёт знает
разбор под настоящим именем, ответы — под слепым, карта связывает одно с
другим. Разъедься карта — и половина разборов молча не найдётся: скрипт
напечатает список по оставшимся и не скажет, что считал по половине.

БАНКА В РЕПОЗИТОРИИ НЕТ (`work/` в `.gitignore`), поэтому первый тест — про то,
что его отсутствие остаётся третьим исходом, а не успехом.

Ожидаемое — литералы (Т2), сети нет (Т4), фикстуры с обоих краёв (Т3).
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "find_signals", Path(__file__).resolve().parents[3] / "scripts" / "find_signals.py"
)
assert _SPEC and _SPEC.loader
fs = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(fs)


class Проверка(unittest.TestCase):
    def _банк(self, файлы: dict[str, object] | None) -> Path:
        каталог = Path(self.enterContext(tempfile.TemporaryDirectory()))
        for имя, тело in (файлы or {}).items():
            (каталог / имя).write_text(json.dumps(тело, ensure_ascii=False), encoding="utf-8")
        return каталог

    def _здоровый(self, **поверх) -> dict[str, object]:
        файлы: dict[str, object] = {
            "TRUTH.json": [{"case_id": "c1"}, {"case_id": "c2"}],
            "ANSWERS.json": [
                {"case_id": "blind-1", "observed": ["видно лицо"]},
                {"case_id": "blind-2", "observed": ["видно руку"]},
            ],
            "SCORE.json": {
                "rows": [
                    {"case_id": "c1", "answered": True, "family_hit": True},
                    {"case_id": "c2", "answered": True, "family_hit": False},
                ]
            },
            "BLIND_MAP.json": {"blind-1": "c1", "blind-2": "c2"},
        }
        файлы.update(поверх)
        return файлы

    def test_банка_нет_значит_не_смогли(self):
        итог = fs.проверить_собранное(self._банк(None))
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["checked"], 0)
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 4)

    def test_связный_прогон_молчит(self):
        итог = fs.проверить_собранное(self._банк(self._здоровый()))
        self.assertEqual(итог["outcome"], "pass")
        self.assertEqual(итог["checked"], 2)
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 0)

    def test_разъехавшаяся_карта_ловится(self):
        """Ровно тот случай, ради которого проверка и заведена."""
        итог = fs.проверить_собранное(
            self._банк(self._здоровый(**{"BLIND_MAP.json": {"blind-1": "c1"}}))
        )
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)
        self.assertIn("c2", итог["note"])

    def test_ответ_без_наблюдений_считать_не_из_чего(self):
        итог = fs.проверить_собранное(
            self._банк(
                self._здоровый(
                    **{
                        "ANSWERS.json": [
                            {"case_id": "blind-1", "observed": ["видно лицо"]},
                            {"case_id": "blind-2", "observed": []},
                        ]
                    }
                )
            )
        )
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_два_слепых_имени_на_один_разбор(self):
        итог = fs.проверить_собранное(
            self._банк(self._здоровый(**{"BLIND_MAP.json": {"blind-1": "c1", "blind-2": "c1"}}))
        )
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 2)

    def test_ни_одного_отвеченного_разбора_это_не_смогли(self):
        итог = fs.проверить_собранное(
            self._банк(
                self._здоровый(
                    **{
                        "SCORE.json": {
                            "rows": [
                                {"case_id": "c1", "answered": False, "family_hit": False},
                                {"case_id": "c2", "answered": False, "family_hit": False},
                            ]
                        }
                    }
                )
            )
        )
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["checked"], 2)
        self.assertEqual(итог["unmeasured"], 1)

    def test_строка_счёта_без_обязательных_полей(self):
        итог = fs.проверить_собранное(
            self._банк(self._здоровый(**{"SCORE.json": {"rows": [{"case_id": "c1"}]}}))
        )
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_счёт_без_списка_строк(self):
        итог = fs.проверить_собранное(self._банк(self._здоровый(**{"SCORE.json": {}})))
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)


if __name__ == "__main__":
    unittest.main()
