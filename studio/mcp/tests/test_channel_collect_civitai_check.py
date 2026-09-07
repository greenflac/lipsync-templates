"""Офлайновая проверка канала Civitai: годны ли УЖЕ СОБРАННЫЕ пары.

САМОЕ ВАЖНОЕ ЗДЕСЬ — ПЕРВЫЙ ТЕСТ. Файла с парами в репозитории нет и не будет
(`.gitignore`, чужие промпты), значит на чистом клоне и в CI проверка обязана
сказать «не смогли». Свернуть это в «годно» — та самая ошибка, которую проект
ловит чаще всего: ноль проверенных строк при нуле нарушений выглядит успехом.

НЕГАТИВНЫЙ КОНТРОЛЬ ДВУСТОРОННИЙ (И5): здоровая строка обязана пройти, каждая
из пяти порч — покраснеть поимённо.

Ожидаемое — литералы (Т2), сети нет (Т4), фикстуры с обоих краёв (Т3): нет
файла, пустой файл, здоровая строка, порченые строки.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "collect_civitai", Path(__file__).resolve().parents[3] / "scripts" / "collect_civitai.py"
)
assert _SPEC and _SPEC.loader
cc = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(cc)


def _строка(**поверх) -> dict:
    """Здоровая пара: все обязательные поля, PG-13, четыре слова в промпте."""
    строка = {
        "prompt": "a woman in a coat",
        "image_url": "https://image.civitai.com/one.jpeg",
        "source_url": "https://civitai.com/api/v1/model-versions/1",
        "harvested": "2026-09-01",
        "provenance": "civitai:someone",
        "rights": "owner_authorisation_2026-08-27",
        "nsfw_level": 2,
    }
    строка.update(поверх)
    return строка


class Проверка(unittest.TestCase):
    def _файл(self, строки) -> Path:
        каталог = Path(self.enterContext(tempfile.TemporaryDirectory()))
        путь = каталог / "civitai_prompts.jsonl"
        if строки is not None:
            путь.write_text(
                "".join(json.dumps(с, ensure_ascii=False) + "\n" for с in строки), encoding="utf-8"
            )
        return путь

    def test_данных_нет_значит_не_смогли(self):
        """Честный исход на чистом клоне ровно один, и он не «годно»."""
        итог = cc.проверить_собранное(self._файл(None))
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["checked"], 0)
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 1)

    def test_пустой_файл_тоже_не_смогли(self):
        итог = cc.проверить_собранное(self._файл([]))
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["checked"], 0)

    def test_здоровые_строки_проходят(self):
        итог = cc.проверить_собранное(
            self._файл(
                [
                    _строка(),
                    _строка(image_url="https://image.civitai.com/two.jpeg", nsfw_level=1),
                    _строка(image_url="https://image.civitai.com/three.jpeg", nsfw_level=4),
                ]
            )
        )
        self.assertEqual(итог["outcome"], "pass")
        self.assertEqual(итог["checked"], 3)
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 0)

    def test_строка_без_прав_не_подлежит_точному_удалению(self):
        итог = cc.проверить_собранное(self._файл([_строка(rights="")]))
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)
        self.assertIn("rights", итог["note"])

    def test_уровень_выше_потолка(self):
        """Потолок — 4 (R). Пятая ступень (8, X) не собирается никогда."""
        итог = cc.проверить_собранное(self._файл([_строка(nsfw_level=8)]))
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_промпт_короче_трёх_слов(self):
        итог = cc.проверить_собранное(self._файл([_строка(prompt="two words")]))
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_происхождение_без_префикса_площадки(self):
        """По этому префиксу ищутся строки при требовании об удалении."""
        итог = cc.проверить_собранное(self._файл([_строка(provenance="someone")]))
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_повтор_изображения_значит_дедупликация_отвалилась(self):
        итог = cc.проверить_собранное(self._файл([_строка(), _строка()]))
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)
        self.assertEqual(итог["checked"], 2)

    def test_битая_строка_считается_нарушением(self):
        каталог = Path(self.enterContext(tempfile.TemporaryDirectory()))
        путь = каталог / "civitai_prompts.jsonl"
        путь.write_text("{не json\n", encoding="utf-8")
        итог = cc.проверить_собранное(путь)
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)


if __name__ == "__main__":
    unittest.main()
