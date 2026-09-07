"""Офлайновая проверка канала вендорских страниц: годно ли снятое основание.

ЗАЧЕМ. Канал ходит в сеть, и потому гейт его не звал вовсе. Но половина его
работы лежит на диске: основание отпечатков — единственный источник ответа на
вопрос «изменилась ли страница». Испортись оно молча — канал будет отвечать
«не менялась» про всё подряд, никуда не сходив.

ПОЛ `ПОЛ_ЧУЖИМ_СПОСОБОМ` СТОРОЖИТСЯ В ОБЕ СТОРОНЫ (Т1): ровно на поле прибор
обязан промолчать, на единицу выше — сказать «не смогли». Подмени константу
любым из двух направлений — один из этих двух тестов покраснеет.

Ожидаемое — литералы (Т2), сети нет (Т4), фикстуры с обоих краёв (Т3).
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "recheck_vendor", Path(__file__).resolve().parents[3] / "scripts" / "recheck_vendor.py"
)
assert _SPEC and _SPEC.loader
rv = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(rv)

#: Пол «не смогли» — сколько страниц имеют свежий отпечаток, снятый ЧУЖИМ
#: способом. Литерал, а не импорт (Т2): импортированное ожидание поехало бы
#: вместе с константой и промолчало.
ПОЛ = 19

ОТПЕЧАТОК = "a" * 64


def _строка(url: str, способ: str | None, **поверх) -> dict:
    запись = {"url": url, "fingerprint": ОТПЕЧАТОК, "claims": 3, "seen_on": "2026-09-03"}
    if способ is not None:
        запись["method"] = способ
    запись.update(поверх)
    return запись


class Проверка(unittest.TestCase):
    def _основание(self, строки) -> Path:
        каталог = Path(self.enterContext(tempfile.TemporaryDirectory()))
        путь = каталог / "vendor_pages.jsonl"
        if строки is not None:
            путь.write_text(
                "// журнал\n" + "".join(json.dumps(с, ensure_ascii=False) + "\n" for с in строки),
                encoding="utf-8",
            )
        return путь

    def _свести(self, строки):
        """Проверка без живой базы и без карты хостов: цели пустые."""
        return rv.проверить_собранное(self._основание(строки), факты=[], карта={})

    def test_основания_нет_значит_не_смогли(self):
        итог = rv.проверить_собранное(self._основание(None), факты=[], карта={})
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["checked"], 0)
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 1)

    def test_здоровое_основание_молчит(self):
        итог = self._свести([_строка(f"https://vendor.example/{н}", rv.СПОСОБ) for н in range(3)])
        self.assertEqual(итог["outcome"], "pass")
        self.assertEqual(итог["checked"], 3)
        self.assertEqual(итог["violations"], 0)
        self.assertEqual(итог["unmeasured"], 0)

    def test_ровно_на_поле_ещё_годно(self):
        """19 страниц чужим способом — накопленное, печатается числом."""
        строки = [_строка(f"https://vendor.example/old{н}", "text-2026-09-02") for н in range(ПОЛ)]
        строки.append(_строка("https://vendor.example/fresh", rv.СПОСОБ))
        итог = self._свести(строки)
        self.assertEqual(итог["outcome"], "pass")
        self.assertEqual(итог["unmeasured"], 19)
        self.assertEqual(итог["violations"], 0)

    def test_на_единицу_выше_пола_уже_не_смогли(self):
        """Смена способа без переснятия основания обнуляет сравнение."""
        строки = [
            _строка(f"https://vendor.example/old{н}", "text-2026-09-02") for н in range(ПОЛ + 1)
        ]
        итог = self._свести(строки)
        self.assertEqual(итог["outcome"], "could not measure")
        self.assertEqual(итог["unmeasured"], 20)
        self.assertEqual(итог["violations"], 0)

    def test_строка_без_способа_считается_чужой(self):
        """68 строк основания записаны до того, как способ вообще писался."""
        итог = self._свести([_строка("https://vendor.example/a", None)])
        self.assertEqual(итог["unmeasured"], 1)
        self.assertEqual(итог["outcome"], "pass")

    def test_отпечаток_не_sha256(self):
        итог = self._свести([_строка("https://vendor.example/a", rv.СПОСОБ, fingerprint="кратко")])
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_дата_не_iso(self):
        итог = self._свести([_строка("https://vendor.example/a", rv.СПОСОБ, seen_on="вчера")])
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_утверждений_за_страницей_ноль(self):
        итог = self._свести([_строка("https://vendor.example/a", rv.СПОСОБ, claims=0)])
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)

    def test_строка_без_адреса(self):
        итог = self._свести([{"fingerprint": ОТПЕЧАТОК, "claims": 1, "seen_on": "2026-09-03"}])
        self.assertEqual(итог["outcome"], "fail")
        self.assertEqual(итог["violations"], 1)


if __name__ == "__main__":
    unittest.main()
