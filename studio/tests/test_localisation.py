"""Ответ говорит на языке вопроса — весь, а не только вопрос и совет.

НАЙДЕНО аудитом 4-го круга 2026-10-15: английский план нёс «цена не
записана», «в брифе заказан…», «usd за megapixel», строку RESOLUTION
по-русски и русские цитаты рисков без пояснения; справка о модели на
английский вопрос — русские ноты. Прежний тест
(`test_answer_in_the_customers_language.py`) сторожил только вопрос и
«что дальше», и всё прочее заговаривало по-русски незаметно.

ЧТО СТОРОЖИТСЯ. Набор `l10n_battery` (≥25 английских брифов и вопросов: все
виды операций, вопрос заказчику, отказы просева, пустой бриф, полный и
краткий план, полная и краткая справка) проходит через инструменты сервера,
и `l10n.leaks` обязан вернуть пусто:
  * по-английски — ни одной кириллической буквы вне цитат «…» из базы (коды
    `CODE_KEYS` — ключи для программ — не в счёт), и у каждой русской цитаты
    английский глосс `[ru: …]`;
  * по-русски — ни одного английского шаблонного оборота вне цитат.
"""

from __future__ import annotations

import json
import os
import re
import unittest

from studio import l10n, planner
from studio.mcp import server
from studio.tests import l10n_battery as набор

_ВЫКЛ = {"STUDIO_NO_JOURNAL": "1"}


def _без_журнала():
    """Журнал вопросов справки не пишется из теста (он — живые данные)."""
    прежнее = {k: os.environ.get(k) for k in _ВЫКЛ}
    os.environ.update(_ВЫКЛ)
    return прежнее


def _вернуть(прежнее: dict) -> None:
    for k, v in прежнее.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


_ПРОГОН: dict = {}


def _прогон() -> dict:
    """Один прогон набора на модуль: план — секунды, весь набор — около двух минут."""
    if not _ПРОГОН:
        прежнее = _без_журнала()
        try:
            _ПРОГОН["планы_en"] = {
                (б, json.dumps(п)): json.loads(server.план_по_тексту(б, **п))
                for б, п in набор.EN_PLANS
            }
            _ПРОГОН["планы_ru"] = {
                (б, json.dumps(п)): json.loads(server.план_по_тексту(б, **п))
                for б, п in набор.RU_PLANS
            }
            _ПРОГОН["справки_en"] = {
                (м, а, ф): json.loads(server.model_advice(м, а, ф)) for м, а, ф in набор.EN_ADVICE
            }
            _ПРОГОН["справки_ru"] = {
                (м, а, ф): json.loads(server.model_advice(м, а, ф, lang="ru"))
                for м, а, ф in набор.RU_ADVICE
            }
            _ПРОГОН["отказы_en"] = {у: json.loads(server.fetch_url(у)) for у in набор.EN_FETCH}
            _ПРОГОН["отказы_ru"] = {
                у: json.loads(server.fetch_url(у, lang="ru")) for у in набор.RU_FETCH
            }
        finally:
            _вернуть(прежнее)
    return _ПРОГОН


class Набор(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        for ключ, значение in _прогон().items():
            setattr(cls, ключ, значение)


class АнглийскийОтвет(Набор):
    def test_набор_не_меньше_25(self) -> None:
        """Р1: пустой набор прошёл бы, ничего не проверив."""
        self.assertGreaterEqual(len(self.планы_en) + len(self.справки_en), 25)

    def test_набор_покрывает_все_виды_операций(self) -> None:
        виды = {оп.name for оп in planner.OPERATIONS}
        встречено = set()
        for ответ in self.планы_en.values():
            встречено |= {ш.get("step") for ш in ответ.get("steps") or []}
            встречено.add((ответ.get("native_audio_variant") or {}).get("step"))
        self.assertEqual(set(), виды - встречено)
        self.assertIn(planner.NATIVE_AUDIO_STEP, встречено)

    def test_набор_покрывает_вопрос_отказ_и_пустой_бриф(self) -> None:
        причины = {о.get("reason") for о in self.планы_en.values()}
        for нужна in ("нужен_ответ_заказчика", "запрещённая_тема", "обращение_к_читателю",
                      "шаги_не_выведены", "валидатор_отверг"):
            self.assertIn(нужна, причины)
        self.assertTrue(any(о.get("full") for о in self.планы_en.values()), "нет полного плана")

    def test_план_без_кириллицы_вне_цитат(self) -> None:
        провалы = {
            б[:50]: l10n.leaks(о, "en")[:3] for (б, _), о in self.планы_en.items() if l10n.leaks(о, "en")
        }
        self.assertEqual({}, провалы)

    def test_справка_без_кириллицы_вне_цитат(self) -> None:
        провалы = {к: l10n.leaks(о, "en")[:3] for к, о in self.справки_en.items() if l10n.leaks(о, "en")}
        self.assertEqual({}, провалы)

    def test_отказы_fetch_url_без_кириллицы(self) -> None:
        """Пятый круг: причина SSRF («лежит во внутренней сети») шла по-русски."""
        self.assertTrue(all(о["outcome"] == "fail" for о in self.отказы_en.values()))
        провалы = {у: l10n.leaks(о, "en")[:3] for у, о in self.отказы_en.items() if l10n.leaks(о, "en")}
        self.assertEqual({}, провалы)
        self.assertIn(
            "127.0.0.1 lies in the internal network 127.0.0.0/8", self.отказы_en["http://127.1/"]["note"]
        )

    def test_пятый_круг_формы_справки_и_плана(self) -> None:
        """Т2: литералы форм, найденных валидатором 5-го круга."""
        текст = "\n".join(
            s for о in [*self.справки_en.values(), *self.планы_en.values()] for _, _, s, _ in l10n._walk(о)
        )
        for было in ("ВНИМАНИЕ", "Единицы у них РАЗНЫЕ", "ПОТОЛОК", "mostly Russian", "о самой"):
            self.assertNotIn(было, текст)
        план = self.планы_en[("make it look good", "{}")]
        self.assertEqual("нужен_ответ_заказчика", план["reason"])
        self.assertIsNotNone(план["question"])

    def test_названные_аудитом_формы_переведены(self) -> None:
        """Т2: ожидаемое — литералы, по одному на каждую форму из отчёта аудита."""
        # Только ЗНАЧЕНИЯ: ключи словаря (`"usd за megapixel"` в `lower_bound`)
        # — имена полей, как `что_дальше`, и не переводятся.
        текст = "\n".join(s for о in self.планы_en.values() for _, _, s, _ in l10n._walk(о))
        for было in ("цена не записана", "в брифе заказан", "за megapixel", "RESOLUTION: кадр"):
            self.assertNotIn(было, текст)
        self.assertIn("no price recorded", текст)
        self.assertIn("usd per megapixel", текст)
        self.assertRegex(текст, r"RESOLUTION: frame \d+x\d+ carried from step")

    def test_русская_цитата_риска_с_глоссом_и_источником(self) -> None:
        сводки = [о.get("summary") or "" for о in self.планы_en.values()]
        риски = [с for с in сводки if "measured failure: «" in с]
        self.assertTrue(риски)
        for с in риски:
            self.assertRegex(с, r"measured failure: «[^»]+» \[ru: [^\]]+\] \(\w+, \d{4}-\d\d-\d\d\)")

    def test_имя_читается_как_имя_базы_и_это_сказано(self) -> None:
        """Пункт 2 аудита глазами справки: прочтение названо по-английски."""
        ответ = self.справки_en[("Hailuo 2.3", "", False)]
        self.assertEqual("pass", ответ["outcome"])
        self.assertIn("'Hailuo 2.3' read as 'minimax-hailuo-2.3'", ответ["resolved_as"]["note"])


class РусскийОтвет(Набор):
    def test_план_без_английских_шаблонов(self) -> None:
        провалы = {
            б[:50]: l10n.leaks(о, "ru")[:3] for (б, _), о in self.планы_ru.items() if l10n.leaks(о, "ru")
        }
        self.assertEqual({}, провалы)

    def test_справка_без_английских_шаблонов(self) -> None:
        провалы = {к: l10n.leaks(о, "ru")[:3] for к, о in self.справки_ru.items() if l10n.leaks(о, "ru")}
        self.assertEqual({}, провалы)

    def test_отказы_fetch_url_по_русски(self) -> None:
        провалы = {у: l10n.leaks(о, "ru")[:3] for у, о in self.отказы_ru.items() if l10n.leaks(о, "ru")}
        self.assertEqual({}, провалы)

    def test_русский_план_остаётся_русским(self) -> None:
        """И5: «починка», переведшая на английский всех, — не починка."""
        for (б, _), о in self.планы_ru.items():
            if о.get("summary"):
                self.assertTrue(l10n.CYR.search(о["summary"]), б)


class Прибор(unittest.TestCase):
    """Негативный контроль самого прибора (И5): он видит то, что должен."""

    def test_кириллица_вне_цитаты_ловится(self) -> None:
        self.assertEqual([(".note", "цена не записана")], l10n.leaks({"note": "цена не записана"}, "en"))

    def test_цитата_без_глосса_ловится_а_с_глоссом_нет(self) -> None:
        self.assertTrue(l10n.leaks({"note": "risk: «рот плывёт»"}, "en"))
        self.assertEqual([], l10n.leaks({"note": "risk: «рот плывёт» [ru: mouth drifts]"}, "en"))

    def test_код_не_в_счёт(self) -> None:
        self.assertEqual([], l10n.leaks({"step": "липсинк", "reason": "бриф_пуст"}, "en"))

    def test_английский_оборот_в_русском_ловится(self) -> None:
        self.assertTrue(l10n.leaks({"note": "3 attribute(s) answered from 3 statements"}, "ru"))
        self.assertEqual([], l10n.leaks({"note": "модель kling-3.0 через fal"}, "ru"))
        # Т1, порог «три слова» с обеих сторон: два слова подряд — ещё термин.
        self.assertEqual([], l10n.leaks({"note": "лучшая ступень vendor portal"}, "ru"))

    def test_перевод_идемпотентен(self) -> None:
        один = l10n.localise_payload({"note": "цена не записана", "value": "Рот плывёт"}, "en")
        self.assertEqual(один, l10n.localise_payload(один, "en"))
        self.assertEqual({"note": "no price recorded", "value": "«Рот плывёт» [ru: operator's note in Russian, kept as recorded]"}, один)


class ТаблицаПолна(unittest.TestCase):
    """Каждое имя, которое планировщик печатает человеку, есть в таблице."""

    def test_поля_ключа_отбора_имеют_ярлык(self) -> None:
        self.assertEqual([], [п for п in planner.KEY_FIELDS if п not in l10n.LABELS_EN])

    def test_имена_шагов_и_артефактов_переводятся(self) -> None:
        имена = set(planner.ШАГ_ПО_АНГЛИЙСКИ) | {
            v for k, v in vars(planner).items() if k.startswith("ARTEFACT_") and isinstance(v, str)
        }
        self.assertEqual([], sorted(и for и in имена if l10n.CYR.search(str(l10n.localise(и, "en")))))

    def test_положения_кандидата_переводятся(self) -> None:
        положения = [
            v
            for k, v in vars(planner).items()
            if re.match(r"(PRICE|FIT|BAN|LIFE|OUT|REACH)_[A-Z]+$", k) and isinstance(v, str)
        ] + [planner.NO_PRICE, planner.NOT_MEASURED_MARK, *planner.SIGN_WORDS.values()]
        self.assertGreater(len(положения), 15)
        self.assertEqual([], [п for п in положения if l10n.CYR.search(str(l10n.localise(п, "en")))])

    def test_формы_аудита_литералами(self) -> None:
        """Т2: литералы на входе и выходе."""
        self.assertEqual("no price recorded", l10n.localise("цена не записана", "en"))
        self.assertEqual("0.02 usd per megapixel", l10n.localise("0.02 usd за megapixel", "en"))
        self.assertEqual(
            "the brief asks for native audio: one video model makes the picture, the speech and "
            "the lips (instead of: video from scratch)",
            l10n.localise(
                "в брифе заказан нативный звук: картинку, речь и губы делает одна видеомодель "
                "(вместо: генерация_видео)",
                "en",
            ),
        )


class ВосьмойКруг(unittest.TestCase):
    """Утечки, найденные валидатором v8: код шага без ярлыка, «годно», «брифа нет»."""

    @classmethod
    def setUpClass(cls) -> None:
        прежнее = _без_журнала()
        try:
            cls.по_spec = json.loads(
                server.plan_pipeline(
                    "15-second 1080p product teaser for a coffee machine, 9:16",
                    spec={
                        "task": "generate",
                        "inputs": [],
                        "outputs": ["video"],
                        "duration_s": 15,
                        "aspect": "9:16",
                        "people": [],
                    },
                )
            )
        finally:
            _вернуть(прежнее)

    def _коды_без_ярлыка(self, obj, путь="") -> list[str]:
        найдено: list[str] = []
        if isinstance(obj, dict):
            шаг = obj.get("step")
            if isinstance(шаг, str) and l10n.CYR.search(шаг) and "step_label" not in obj:
                найдено.append(путь)
            for k, v in obj.items():
                найдено += self._коды_без_ярлыка(v, f"{путь}.{k}")
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                найдено += self._коды_без_ярлыка(v, f"{путь}[{i}]")
        return найдено

    def test_у_кода_шага_есть_ярлык(self) -> None:
        self.assertEqual([], self._коды_без_ярлыка(self.по_spec))

    def test_исход_сметы_по_английски(self) -> None:
        self.assertIn(self.по_spec["pipeline_price"].get("outcome"), ("pass", "fail", "could not measure"))

    def test_бриф_есть_и_нота_бюджета_это_знает(self) -> None:
        нота = self.по_spec["budget"]["note"]
        self.assertEqual(
            "no budget in the spec — with a spec, the brief text is only echoed and sets the language", нота
        )

    def test_литералы(self) -> None:
        """Т2: литералы на входе и выходе."""
        self.assertEqual("pass", l10n.localise_payload({"outcome": "годно"}, "en")["outcome"])
        self.assertEqual("годно", l10n.localise_payload({"outcome": "годно"}, "ru")["outcome"])
        self.assertEqual(
            {"step": "генерация_видео", "step_label": "video from scratch"},
            l10n.localise_payload({"step": "генерация_видео"}, "en"),
        )
        self.assertEqual(
            {"steps_without_price": ["озвучка"], "steps_without_price_labels": ["voiceover"]},
            l10n.localise_payload({"steps_without_price": ["озвучка"]}, "en"),
        )
        self.assertEqual({"step": "генерация_видео"}, l10n.localise_payload({"step": "генерация_видео"}, "ru"))
        self.assertEqual(
            "weights licence openrail++ — declared in the card on the weights page",
            l10n.localise("лицензия весов openrail++ — declared in the card на странице весов", "en"),
        )
        self.assertEqual(
            "own GPU: price = GPU time × rental rate; rental rate not recorded; …",
            l10n.localise("свой GPU: цена — время GPU × ставка аренды; ставка не записана; время…", "en"),
        )
        self.assertEqual("own GPU: …", l10n.localise("свой GPU: цена — время GPU × ставка аренды…", "en"))


if __name__ == "__main__":
    unittest.main()
