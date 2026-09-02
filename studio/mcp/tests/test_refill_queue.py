"""Очередь дочитывания: порядок, знаменатели и третий исход.

Сеть и диск сюда не заходят — все три источника подаются данными (Т4).
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from unittest import mock
from datetime import date
from pathlib import Path

from studio.mcp import advice

SPEC = importlib.util.spec_from_file_location(
    "refill_queue",
    Path(__file__).resolve().parents[3] / "scripts" / "refill_queue.py",
)
assert SPEC and SPEC.loader
refill = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refill)


def work(reason: str, model: str) -> dict:
    return {"reason": reason, "model": model, "detail": "", "where": ""}


class Order(unittest.TestCase):
    def test_a_stale_vendor_claim_outranks_a_question_we_could_not_answer(self):
        """Неверный ответ дороже отсутствующего: им мы отвечаем прямо сейчас."""
        rows = refill.order(
            [work("спросили — не знаем", "a"), work("протухший вендорский факт", "b")]
        )
        self.assertEqual([r["model"] for r in rows], ["b", "a"])

    def test_proven_demand_outranks_future_demand(self):
        rows = refill.order([work("новое семейство", "a"), work("спросили — не знаем", "b")])
        self.assertEqual([r["model"] for r in rows], ["b", "a"])

    def test_a_new_family_outranks_a_new_version(self):
        rows = refill.order(
            [work("новая версия известного семейства", "a"), work("новое семейство", "b")]
        )
        self.assertEqual([r["model"] for r in rows], ["b", "a"])

    def test_an_unknown_reason_goes_last_and_does_not_crash(self):
        """Очередь, падающая от новой строки, перестаёт быть очередью."""
        rows = refill.order([work("причина, которой ещё нет", "a"), work("новое семейство", "b")])
        self.assertEqual([r["model"] for r in rows], ["b", "a"])

    def test_inside_one_reason_the_order_is_stable_by_name(self):
        rows = refill.order([work("новое семейство", "z"), work("новое семейство", "a")])
        self.assertEqual([r["model"] for r in rows], ["a", "z"])


class ReasonsAreOneString(unittest.TestCase):
    """Е1: причина живёт в одном месте, и производители берут её оттуда.

    Тесты порядка подают в `order()` литералы, набранные в тесте, — то есть
    проверяют копию. Эти проверяют СВЯЗЬ: что реально порождают производители
    и знает ли об этом таблица приоритетов.
    """

    def test_every_reason_a_producer_emits_has_a_priority(self):
        """Все ТРИ производителя вызываются по-настоящему.

        Первая редакция этого теста подставляла константы руками для двух из
        трёх — то есть сравнивала `PRIORITY` сам с собой, и опечатка на стороне
        `stale_work`/`missed_work` оставляла её зелёной (найдено независимой
        проверкой 2026-08-31). Это ровно тот дефект, который тест закрывает.
        """
        payload = {
            "new_families": [{"family": "x", "uploaders": ["a", "b"], "examples": []}],
            "new_versions": [{"stem": "y", "family": "x", "count": 2, "examples": []}],
        }
        produced = {r["reason"] for r in refill.discovered_work(payload)}

        with tempfile.TemporaryDirectory() as tmp:
            journal = Path(tmp) / "misses.jsonl"
            row = '{"model":"h3-max","attribute":"","outcome":"could not measure",'
            row += '"known":0,"asked_on":"2026-08-31"}\n'
            journal.write_text(row * 2, encoding="utf-8")
            produced |= {r["reason"] for r in refill.missed_work(journal)}

            facts = Path(tmp) / "facts.jsonl"
            facts.write_text(
                "\n".join(
                    [
                        '{"model":"m","attribute":"a","value":"v","source_url":'
                        '"https://example.test/x","tier":"vendor","stated_on":"2020-01-01"}',
                        '{"model":"m","attribute":"b","value":"v","source_url":'
                        '"https://example.test/y","tier":"blog","stated_on":"2020-01-01"}',
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            produced |= {r["reason"] for r in refill.stale_work(path=facts)}

        self.assertEqual(len(produced), 5)  # все пять ступеней действительно порождаются
        self.assertEqual(produced - set(refill.PRIORITY), set())

    def test_the_lowest_rung_is_ranked_below_the_others(self):
        """Пятая ступень тоже константа-решение: в живой очереди это 26 строк
        из 34, и без сторожа её можно было поставить впереди вендорской."""
        rows = refill.order([work(refill.STALE_OTHER, "a"), work(refill.STALE_VENDOR, "b")])
        self.assertEqual([r["model"] for r in rows], ["b", "a"])

    def test_the_lowest_rung_still_outranks_a_reason_nobody_ranked(self):
        """Нижняя ступень — не то же самое, что «причина, которой нет в таблице».

        Абсолютное значение ступени ничего не решает, решает порядок, поэтому
        подмена 5 на 6 или 7 не может ничего покрасить и теста на неё не будет.
        А вот 99 — может: там сидит корзина неизвестных причин, и совпасть с
        ней значит потерять различие между «низкий приоритет» и «не разобрано».
        """
        rows = refill.order([work("причина, которой ещё нет", "a"), work(refill.STALE_OTHER, "b")])
        self.assertEqual([r["model"] for r in rows], ["b", "a"])

    def test_the_lowest_rung_is_below_future_demand_too(self):
        rows = refill.order([work(refill.STALE_OTHER, "a"), work(refill.NEW_VERSION, "b")])
        self.assertEqual([r["model"] for r in rows], ["b", "a"])


class Verdict(unittest.TestCase):
    def test_all_sources_silent_is_the_third_outcome(self):
        """Р1: нечего читать и нечем мерить — разные вещи."""
        code = refill.report([], {"a": False, "b": False}, 5)
        self.assertEqual(code, 2)

    def test_one_silent_source_is_still_could_not_measure(self):
        code = refill.report([work("новое семейство", "a")], {"a": True, "b": False}, 5)
        self.assertEqual(code, 2)

    def test_all_sources_answered_with_an_empty_queue_is_a_pass(self):
        """Пустая очередь при трёх живых источниках — это хорошая новость."""
        code = refill.report([], {"a": True, "b": True}, 5)
        self.assertEqual(code, 0)


class Gate(unittest.TestCase):
    """`check_journal` — функция, производящая коды возврата для scripts/check.

    Сторож стоял на её помощнике, а не на ней: подмена `if broken or torn` на
    `if broken` оставляла все тесты зелёными и возвращала исходный дефект
    целиком (найдено независимой проверкой 2026-08-31). Тот же класс, который
    этими же тестами и чинили.
    """

    def journal(self, body: str) -> int:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "misses.jsonl"
            path.write_text(body, encoding="utf-8")
            return refill.check_journal(path)

    GOOD = '{"model":"a","outcome":"pass","known":1,"asked_on":"2026-08-31"}\n'

    def test_a_whole_journal_passes(self):
        self.assertEqual(self.journal(self.GOOD), 0)

    def test_a_torn_line_fails_the_build(self):
        self.assertEqual(self.journal(self.GOOD + "обрыв{"), 1)

    def test_a_line_broken_by_schema_fails_the_build(self):
        bad = '{"model":"a","outcome":"годно","known":1,"asked_on":"2026-08-31"}\n'
        self.assertEqual(self.journal(self.GOOD + bad), 1)

    def test_a_non_numeric_known_fails_instead_of_crashing(self):
        bad = '{"model":"a","outcome":"pass","known":"много","asked_on":"2026-08-31"}\n'
        self.assertEqual(self.journal(bad), 1)

    def test_an_empty_journal_is_the_third_outcome_not_a_pass(self):
        self.assertEqual(self.journal("// только шапка\n"), 2)

    def test_a_journal_of_pure_junk_is_broken_not_empty(self):
        """Второй исход не подменяется третьим: строки БЫЛИ, они испорчены."""
        self.assertEqual(self.journal("это не json\nи это тоже\n"), 1)


class Sources(unittest.TestCase):
    def test_a_fact_younger_than_the_threshold_is_not_work(self):
        rows = refill.stale_work(today=date(2026, 1, 1), path=Path("нет такого файла"))
        self.assertEqual(rows, [])

    def test_a_discovery_run_that_never_happened_yields_no_rows(self):
        self.assertEqual(refill.discovered_work(None), [])

    def test_a_discovered_family_and_version_land_with_their_own_reasons(self):
        payload = {
            "new_families": [
                {"family": "sensenova", "uploaders": ["a", "b"], "task": "any", "examples": ["a/x"]}
            ],
            "new_versions": [
                {"stem": "minimax h3", "family": "minimax", "count": 42, "examples": ["b/y"]}
            ],
        }
        rows = refill.discovered_work(payload)
        self.assertEqual(
            [r["reason"] for r in rows],
            ["новое семейство", "новая версия известного семейства"],
        )


if __name__ == "__main__":
    unittest.main()


class ОпубликованноеВОчередьНеИдёт(unittest.TestCase):
    """Правило одно на проект, и жило оно в двух местах (Е1).

    `advice.stale` научили отличать дату публикации от износа 2026-09-02, а
    здесь тот же расчёт был переписан заново — и починка сюда не доехала.
    ИЗМЕРЕНО в тот же день: в очереди из 51 строки лежало 10 ссылок на arXiv,
    старейшей 1352 дня.
    """

    def _база(self, rows: list[dict]) -> Path:
        файл = Path(tempfile.mkdtemp()) / "facts.jsonl"
        файл.write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
        )
        return файл

    СТАРАЯ_СТАТЬЯ = {
        "model": "м",
        "attribute": "failure_mode",
        "value": "статья",
        "source_url": "https://arxiv.org/abs/2212.10562",
        "tier": "paper",
        "stated_on": "2022-12-20",
    }
    СТАРАЯ_ЦЕНА = {
        "model": "м",
        "attribute": "price_per_second_usd",
        "value": "0.06",
        "source_url": "https://fal.ai/models/x",
        "tier": "portal",
        "stated_on": "2024-01-01",
    }

    def test_статья_в_очередь_не_попадает(self):
        очередь = refill.stale_work(path=self._база([self.СТАРАЯ_СТАТЬЯ]))
        self.assertEqual(очередь, [])

    def test_цена_площадки_в_очередь_попадает(self):
        """Вторая половина (И5): иначе правило просто выключает очередь."""
        очередь = refill.stale_work(path=self._база([self.СТАРАЯ_ЦЕНА]))
        self.assertEqual([r["model"] for r in очередь], ["м"])

    def test_правило_берётся_из_одного_места(self):
        """Т2 наоборот, и нарочно: здесь ожидаемое — ИМЕННО импорт, потому что
        проверяется, что второго списка тиров не завели."""
        self.assertIs(refill.advice.PUBLISHED_TIERS, advice.PUBLISHED_TIERS)


class ОпросИндексовПоУмолчанию(unittest.TestCase):
    """Третий исход, выдаваемый ВСЕГДА, перестаёт быть сигналом.

    Очередь при каждом обычном запуске печатала «молчат: опрос индексов», хотя
    прогон лежал рядом и был свежим (снят 2026-08-31, 763 записи, оба канала
    ответили) — просто флаг `--discovered` никто не передавал. Читатель
    привыкает к такому молчанию и не заметит дня, когда канал замолчит
    по-настоящему.
    """

    def test_умолчание_указывает_на_прогон_в_знании(self):
        self.assertEqual(refill.ОПРОС_ПО_УМОЛЧАНИЮ.name, "catalog_poll.json")
        self.assertTrue(
            refill.ОПРОС_ПО_УМОЛЧАНИЮ.parent.name == "knowledge",
            refill.ОПРОС_ПО_УМОЛЧАНИЮ,
        )

    def test_очередь_не_молчит_без_флага(self):
        """Дыра, найденная мутацией: тест проверял КОНСТАНТУ, а разбор
        аргументов мог её не использовать. Проверяется НАПЕЧАТАННОЕ (Т5): зовут
        точку входа без единого флага, как её зовёт человек."""
        import contextlib
        import io

        буфер = io.StringIO()
        with contextlib.redirect_stdout(буфер):
            refill.main([])
        напечатано = буфер.getvalue()
        self.assertIn("опрос индексов: снят", напечатано)
        self.assertNotIn("молчат: опрос индексов", напечатано)

    def test_возраст_считается_днями(self):
        сегодня = date.today().isoformat()
        self.assertEqual(refill._дней_назад(сегодня), 0)

    def test_нечитаемая_дата_это_не_ноль(self):
        """Р1 у мелочи: «даты нет» и «снято сегодня» — разные вещи, и вторая
        читается как свежесть, которой нет."""
        self.assertIsNone(refill._дней_назад("позавчера"))
        self.assertIsNone(refill._дней_назад(""))


class ИсточникИзменился(unittest.TestCase):
    """Наблюдение раньше догадки.

    Возраст факта — догадка о том, что источник мог поменяться; разошедшийся
    отпечаток — наблюдение, что он поменялся. Поэтому `источник изменился`
    стоит в очереди ВЫШЕ протухшего вендорского.
    """

    def _журнал(self, записи: list[dict]) -> Path:
        путь = Path(tempfile.mkdtemp()) / "vendor_pages.jsonl"
        путь.write_text(
            "// шапка\n" + "".join(json.dumps(з, ensure_ascii=False) + "\n" for з in записи),
            encoding="utf-8",
        )
        return путь

    def _запись(self, отпечаток: str, способ: str = "сп-1", дата: str = "2026-09-01") -> dict:
        return {
            "url": "https://vendor.test/pricing",
            "fingerprint": отпечаток,
            "method": способ,
            "claims": 8,
            "seen_on": дата,
        }

    def test_отпечаток_разошёлся_это_работа(self):
        строки = refill.changed_work(self._журнал([self._запись("aaa"), self._запись("bbb")]))
        self.assertEqual(len(строки), 1, строки)
        self.assertEqual(строки[0]["reason"], refill.CHANGED_SOURCE)
        self.assertIn("8", строки[0]["detail"], "число утверждений на странице — в строке")

    def test_отпечаток_прежний_работы_нет(self):
        self.assertEqual(
            refill.changed_work(self._журнал([self._запись("aaa"), self._запись("aaa")])), []
        )

    def test_одна_запись_это_не_изменение(self):
        """Иначе первый же прогон канала завалил бы очередь семьюдесятью
        «изменилось», ни одно из которых не наблюдалось."""
        self.assertEqual(refill.changed_work(self._журнал([self._запись("aaa")])), [])

    def test_разные_способы_не_сравниваются(self):
        """Отпечатки, снятые разными правилами, не «отличаются» — они посчитаны
        иначе. Сравнив их, очередь получила бы смену правила как смену всех
        страниц разом."""
        строки = refill.changed_work(
            self._журнал([self._запись("aaa", "сп-старый"), self._запись("bbb", "сп-новый")])
        )
        self.assertEqual(строки, [])

    def test_изменение_идёт_раньше_протухшего(self):
        порядок = refill.order(
            [
                {"reason": refill.STALE_VENDOR, "model": "a"},
                {"reason": refill.CHANGED_SOURCE, "model": "z"},
            ]
        )
        self.assertEqual(порядок[0]["reason"], refill.CHANGED_SOURCE)


class ОчередьПортала(unittest.TestCase):
    def _файл(self, payload: dict) -> Path:
        путь = Path(tempfile.mkdtemp()) / "portal_poll.json"
        путь.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        return путь

    def test_имена_портала_попадают_в_очередь(self):
        строки = refill.portal_work(
            self._файл(
                {
                    "portal": "fal.ai",
                    "partial": False,
                    "new_families": [{"family": "veed-lipsync-v2", "task": "Lipsync"}],
                }
            )
        )
        self.assertEqual([с["model"] for с in строки], ["veed-lipsync-v2"])
        self.assertEqual(строки[0]["reason"], refill.NEW_FAMILY)

    def test_неполный_опрос_строк_не_даёт(self):
        """Подмешать неполную очередь значит выдать пробел опроса за отсутствие
        работы — третий исход, свёрнутый в первый."""
        строки = refill.portal_work(
            self._файл({"partial": True, "new_families": [{"family": "x", "task": "y"}]})
        )
        self.assertEqual(строки, [])

    def test_файла_нет_строк_нет_и_прогон_цел(self):
        self.assertEqual(refill.portal_work(Path(tempfile.mkdtemp()) / "нет.json"), [])


class СостояниеИсточникаРядомСВозрастом(unittest.TestCase):
    """Возраст факта — ДОГАДКА о том, что источник мог поменяться; отпечаток —
    наблюдение, менялся ли он.

    ПРОВЕРЕНО РУКАМИ 2026-09-02 на `kling-3.0.max_seconds = 15`, источнику 209
    дней: страница жива и говорит дословно «extended video duration of up to 15
    seconds». Факт верен; протухла только его дата. Строка из очереди при этом
    не убирается — вендор мог выпустить новую модель, ничего не поменяв на
    старой странице, — но рядом с ней теперь стоит, что известно об источнике.
    """

    def _журнал(self, записи: list[dict]) -> Path:
        путь = Path(tempfile.mkdtemp()) / "vendor_pages.jsonl"
        путь.write_text(
            "// шапка\n" + "".join(json.dumps(з, ensure_ascii=False) + "\n" for з in записи),
            encoding="utf-8",
        )
        return путь

    def _з(self, отпечаток: str, способ: str = "сп-1", дата: str = "2026-09-01") -> dict:
        return {
            "url": "https://vendor.test/a",
            "fingerprint": отпечаток,
            "method": способ,
            "seen_on": дата,
        }

    def test_источник_не_менялся(self):
        сост = refill.состояние_источников(self._журнал([self._з("aaa"), self._з("aaa")]))
        self.assertEqual(сост["https://vendor.test/a"][0], refill.ИСТОЧНИК_ПРЕЖНИЙ)

    def test_источник_изменился(self):
        сост = refill.состояние_источников(self._журнал([self._з("aaa"), self._з("bbb")]))
        self.assertEqual(сост["https://vendor.test/a"][0], refill.ИСТОЧНИК_ИЗМЕНИЛСЯ)

    def test_одно_наблюдение_это_не_наблюдение(self):
        """Сравнивать не с чем: одна запись — основание, а не история."""
        сост = refill.состояние_источников(self._журнал([self._з("aaa")]))
        self.assertEqual(сост["https://vendor.test/a"][0], refill.ИСТОЧНИК_НЕ_НАБЛЮДАЛИ)

    def test_разные_способы_не_сравниваются(self):
        сост = refill.состояние_источников(
            self._журнал([self._з("aaa", "сп-старый"), self._з("bbb", "сп-новый")])
        )
        self.assertEqual(сост["https://vendor.test/a"][0], refill.ИСТОЧНИК_НЕ_НАБЛЮДАЛИ)

    def test_строка_очереди_несёт_состояние(self):
        строки = refill.с_состоянием_источника(
            [
                {
                    "reason": refill.STALE_VENDOR,
                    "model": "m",
                    "detail": "x",
                    "where": "https://vendor.test/a",
                }
            ],
            {"https://vendor.test/a": (refill.ИСТОЧНИК_ПРЕЖНИЙ, "2026-09-02")},
        )
        self.assertIn(refill.ИСТОЧНИК_ПРЕЖНИЙ, строки[0]["detail"])
        self.assertIn("2026-09-02", строки[0]["detail"])

    def test_строка_из_очереди_не_исчезает(self):
        """И5: наблюдение НЕ отменяет возраст. Вендор мог выпустить новую
        модель, ничего не поменяв на старой странице."""
        строки = refill.с_состоянием_источника(
            [
                {
                    "reason": refill.STALE_VENDOR,
                    "model": "m",
                    "detail": "x",
                    "where": "https://vendor.test/a",
                }
            ],
            {"https://vendor.test/a": (refill.ИСТОЧНИК_ПРЕЖНИЙ, "2026-09-02")},
        )
        self.assertEqual(len(строки), 1)
        self.assertEqual(строки[0]["reason"], refill.STALE_VENDOR)


class ПромахПересчитываетсяПоНынешнейБазе(unittest.TestCase):
    """ИЗМЕРЕНО 2026-09-02: журнал держал `minimax-h3` с двумя промахами по
    `max_seconds`, а база отвечает на этот вопрос `15` — ответ появился в тот
    же день, когда семья атрибутов научилась разворачивать `max_seconds` в
    `duration_enum` и соседей.

    Очередь, которая просит сделанного, читается по диагонали. На канале опроса
    портала это уже разбиралось; здесь тот же пересчёт.
    """

    def _журнал(self, строки: list[dict]) -> Path:
        путь = Path(tempfile.mkdtemp()) / "misses.jsonl"
        путь.write_text(
            "".join(json.dumps(с, ensure_ascii=False) + "\n" for с in строки), encoding="utf-8"
        )
        return путь

    def _промах(self, model: str, attribute: str = "max_seconds") -> dict:
        return {
            "model": model,
            "attribute": attribute,
            "outcome": "could not measure",
            "known": 0,
            "asked_on": "2026-08-31",
            "note": "",
        }

    def _ответ(self, reason: str, near: list[str] | None = None):
        return lambda model, attribute="", **kw: {"reason": reason, "near": near or []}

    def test_отвеченный_промах_из_очереди_уходит(self):
        путь = self._журнал([self._промах("m"), self._промах("m")])
        with mock.patch.object(refill.advice, "advise", self._ответ("answered")):
            self.assertEqual(refill.missed_work(путь), [])

    def test_молчание_с_похожим_именем_это_другая_работа(self):
        """Не «идти читать источники», а «спросивший написал имя иначе»."""
        путь = self._журнал([self._промах("h3-max"), self._промах("h3-max")])
        with mock.patch.object(
            refill.advice, "advise", self._ответ("name_maybe_mistyped", ["minimax-h3-max"])
        ):
            строки = refill.missed_work(путь)
        self.assertEqual(строки[0]["reason"], refill.ASKED_OTHER_SPELLING)
        self.assertIn("minimax-h3-max", строки[0]["detail"])

    def test_полное_молчание_остаётся_спросом(self):
        """Вторая половина (И5): пересчёт не должен опустошать очередь. Модель,
        которой база не знает вовсе, — по-прежнему работа читать источники."""
        путь = self._журнал([self._промах("нет-такой"), self._промах("нет-такой")])
        with mock.patch.object(refill.advice, "advise", self._ответ("model_unknown")):
            строки = refill.missed_work(путь)
        self.assertEqual(строки[0]["reason"], refill.ASKED_UNKNOWN)
        self.assertNotIn("база держит", строки[0]["detail"])
