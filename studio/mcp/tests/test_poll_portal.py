"""Опрос портала: имя, разница и НЕПОЛНОТА.

Сети здесь нет (Т4): портал подменяется, ожидаемое — литералы (Т2). Проверяется
то, из-за чего канал вообще заводился, и то, что он обязан говорить о себе,
когда ответил не целиком.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "poll_portal", Path(__file__).resolve().parents[3] / "scripts" / "poll_portal.py"
)
assert SPEC and SPEC.loader
pp = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(pp)

PASS_ = "pass"
FAIL_ = "fail"
UNMEASURED_ = "could not measure"


class ИмяМодели(unittest.TestCase):
    """Разница считается по ИМЕНАМ, поэтому неверное имя — это выдуманная работа."""

    def test_префикс_вендора_не_часть_имени(self):
        self.assertEqual(pp.имя_модели("fal-ai/sync-lipsync/v3"), "sync-lipsync-v3")

    def test_чужой_вендор_остаётся_в_имени(self):
        """`veed/lipsync/v2` — это VEED, и выбросить его имя значит слить
        разных вендоров в одно."""
        self.assertEqual(pp.имя_модели("veed/lipsync/v2"), "veed-lipsync-v2")

    def test_пустое_остаётся_пустым(self):
        self.assertEqual(pp.имя_модели(""), "")
        self.assertEqual(pp.имя_модели("///"), "")


class Разница(unittest.TestCase):
    def test_известное_базе_в_очередь_не_идёт(self):
        with mock.patch.object(pp, "load_facts", lambda: [_факт("sync-lipsync-v3")]):
            найдено = {
                "sync-lipsync-v3": {
                    "name": "sync-lipsync-v3",
                    "title": "",
                    "url": "",
                    "keyword": "x",
                },
                "heygen-v3-lipsync-speed": {
                    "name": "heygen-v3-lipsync-speed",
                    "title": "",
                    "url": "",
                    "keyword": "x",
                },
            }
            self.assertEqual([з["name"] for з in pp.разница(найдено)], ["heygen-v3-lipsync-speed"])

    def test_другое_написание_известного_тоже_не_идёт(self):
        """Сравнение по свёрнутому имени: иначе `sync_lipsync_v3` попал бы в
        очередь как новинка, и человек пошёл бы читать то, что уже записано."""
        with mock.patch.object(pp, "load_facts", lambda: [_факт("sync-lipsync-v3")]):
            найдено = {
                "sync_lipsync_v3": {
                    "name": "sync_lipsync_v3",
                    "title": "",
                    "url": "",
                    "keyword": "x",
                }
            }
            self.assertEqual(pp.разница(найдено), [])


class НеполныйОпрос(unittest.TestCase):
    """Наблюдено на первом живом прогоне: одно слово из трёх не ответило,
    очередь записалась и выглядела полной. Пробел в такой очереди неотличим от
    отсутствия модели на портале — а это разные вещи."""

    def _файл(self, payload: dict) -> Path:
        путь = Path(tempfile.mkdtemp()) / "portal_poll.json"
        путь.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return путь

    def test_неполный_опрос_это_третий_исход(self):
        итог = pp.свести(
            self._файл(
                {
                    "polled_on": "2026-09-02",
                    "channels_asked": 3,
                    "channels_answered": 2,
                    "partial": True,
                    "new_families": [{"family": "x"}],
                }
            )
        )
        self.assertEqual(итог["outcome"], UNMEASURED_)
        self.assertIn("НЕПОЛНЫЙ", итог["note"])

    def test_полный_опрос_пересчитывается_по_базе(self):
        """Вторая половина (И5): очередь, снятая вчера, называет работой то,
        что сегодня записано, поэтому пересчёт обязателен."""
        with mock.patch.object(pp, "load_facts", lambda: [_факт("x")]):
            итог = pp.свести(
                self._файл(
                    {
                        "polled_on": "2026-09-02",
                        "channels_asked": 3,
                        "channels_answered": 3,
                        "partial": False,
                        "new_families": [{"family": "x"}, {"family": "y"}],
                    }
                )
            )
        self.assertEqual(итог["outcome"], PASS_)
        self.assertEqual([з["family"] for з in итог["still_unknown"]], ["y"])
        self.assertIn("записано с тех пор 1", итог["note"])

    def test_файла_нет_это_не_успех(self):
        итог = pp.свести(Path(tempfile.mkdtemp()) / "нет.json")
        self.assertEqual(итог["outcome"], UNMEASURED_)

    def test_битый_файл_это_нарушение_а_не_пустота(self):
        путь = Path(tempfile.mkdtemp()) / "portal_poll.json"
        путь.write_text("не json", encoding="utf-8")
        self.assertEqual(pp.свести(путь)["outcome"], FAIL_)


class ОтветПортала(unittest.TestCase):
    def _ответ(self, тело: str, исход: str = PASS_) -> dict:
        return {"outcome": исход, "text": тело}

    def test_не_разобралось_отличимо_от_не_ответил(self):
        """Схема портала поменялась и портал лежит — разные события, и лечатся
        они по-разному."""
        with mock.patch.object(pp.fetch, "fetch", lambda url: self._ответ("не json")):
            self.assertEqual(pp.спросить("lipsync", 1)[0], FAIL_)
        with mock.patch.object(pp.fetch, "fetch", lambda url: self._ответ("", UNMEASURED_)):
            self.assertEqual(pp.спросить("lipsync", 1)[0], UNMEASURED_)

    def test_json_без_items_это_смена_схемы(self):
        with mock.patch.object(pp.fetch, "fetch", lambda url: self._ответ('{"данные": []}')):
            self.assertEqual(pp.спросить("lipsync", 1)[0], FAIL_)

    def test_страницы_кончаются_по_слову_портала(self):
        тело = json.dumps({"items": [{"id": "fal-ai/a"}], "pages": 1})
        звонков = []

        def ответ(url: str) -> dict:
            звонков.append(url)
            return self._ответ(тело)

        with mock.patch.object(pp.fetch, "fetch", ответ):
            опрос = pp.опросить(("lipsync",))
        self.assertEqual(len(звонков), 1, "лишняя страница — лишний запрос к чужому хосту")
        self.assertEqual(опрос["answered"], 1)
        self.assertEqual(list(опрос["found"]), ["a"])


def _факт(model: str):
    from studio.selfrag.facts import Fact

    return Fact(model=model, attribute="a", value="v", source_url="u", tier="portal")


if __name__ == "__main__":
    unittest.main()


class ЗнаниеНеЗаменяетсяМеньшимЗнанием(unittest.TestCase):
    """ПОЙМАНО НА СЕБЕ: портал ответил на 1 слово из 3, очередь записалась
    неполной (61 имя стало 21), и сборка покраснела — гейт честно дал третий
    исход. Гейт прав; чинить надо причину."""

    def _файл(self, полная: bool) -> Path:
        путь = Path(tempfile.mkdtemp()) / "portal_poll.json"
        путь.write_text(
            json.dumps({"polled_on": "2026-09-02", "partial": not полная, "new_families": []}),
            encoding="utf-8",
        )
        return путь

    def test_неполный_опрос_не_затирает_полную_очередь(self):
        self.assertTrue(pp.не_записывать(self._файл(True), {"answered": 1, "asked": 3}))

    def test_полный_опрос_записывается_всегда(self):
        """Вторая половина (И5): правило не должно запирать файл навсегда."""
        self.assertFalse(pp.не_записывать(self._файл(True), {"answered": 3, "asked": 3}))

    def test_поверх_неполной_можно_писать_неполную(self):
        """Хуже уже не станет, а свежая дата ближе к правде."""
        self.assertFalse(pp.не_записывать(self._файл(False), {"answered": 1, "asked": 3}))

    def test_битый_файл_не_считается_полной_очередью(self):
        """Иначе очередь чинится только руками: нечитаемый файл запер бы запись
        навсегда, и правило «не заменять знание меньшим» защищало бы то, чего
        в файле уже нет. Мутант «битый файл — полная очередь» промолчал ровно
        здесь."""
        путь = Path(tempfile.mkdtemp()) / "portal_poll.json"
        путь.write_text("не json", encoding="utf-8")
        self.assertFalse(pp.не_записывать(путь, {"answered": 1, "asked": 3}))

    def test_файла_нет_неполная_лучше_чем_ничего(self):
        """Лишь бы она не притворялась полной — за это отвечает пометка
        `partial` и третий исход в `--check`."""
        отсутствует = Path(tempfile.mkdtemp()) / "нет.json"
        self.assertFalse(pp.не_записывать(отсутствует, {"answered": 1, "asked": 3}))


class ЗаголовокНесётСвоёОграничение(unittest.TestCase):
    """Строка «база не знает N» на НЕПОЛНОМ обходе — это «мы не спросили».

    ИЗМЕРЕНО 2026-09-03, пять прогонов подряд: ответило 1, 2, 2, 3, 3 слов из
    трёх, портал показал 22, 58, 58, 66, 66 моделей. Ноль неизвестных
    печатался одинаково во всех пяти.
    """

    @staticmethod
    def _опрос(ответило: int, спрошено: int) -> dict:
        return {
            "found": {"a": {"name": "a", "title": "t"}},
            "answered": ответило,
            "asked": спрошено,
            "unparsed": 0,
            "silent": спрошено - ответило,
        }

    def test_неполный_обход_назван_в_той_же_строке(self) -> None:
        строка = pp.строка_разницы(self._опрос(1, 3), [])
        self.assertIn("ОБХОД НЕПОЛНЫЙ", строка)
        self.assertIn("1 слов из 3", строка)

    def test_полный_обход_оговорки_не_несёт(self) -> None:
        """Оговорка на полном обходе — тот же шум, что её отсутствие на
        неполном: и то и другое учит читателя не смотреть на строку."""
        self.assertNotIn("НЕПОЛНЫЙ", pp.строка_разницы(self._опрос(3, 3), []))

    def test_число_неизвестных_в_строке_есть_всегда(self) -> None:
        строка = pp.строка_разницы(self._опрос(3, 3), [{"name": "x"}, {"name": "y"}])
        self.assertIn("база не знает 2", строка)
