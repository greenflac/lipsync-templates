"""Канал опыта практиков с Civitai: находит ли он наблюдение и молчит ли там, где надо.

Сети здесь нет и быть не может (Т4): вход — файл
`studio/knowledge/civitai_fixtures.json`, снятый с живого API 2026-09-01.
Тест, которому нужен civitai.com, краснеет от чужой аварии и зеленеет с кэша,
и не измеряет ни того, ни другого.

Ожидаемое — литералы, а не импорт из проверяемого модуля (Т2): число 3 здесь
написано цифрой, и если завтра прибор станет находить два наблюдения там, где
находил три, тест обязан покраснеть, а не поехать вместе с ним.

Фикстуры взяты с обоих краёв и из середины (Т3): описание на 11 086 символов
с разбором настроек, описание на 5 059 символов с одним тестовым прогоном,
описание из ссылок и благодарностей, где нет ничего, — и три версии: с
настройками у всех картинок, у части картинок и без единой.

ПРО ИМЯ ФАЙЛА. Заказан был `test_civitai.py`, но он занят: это 658 строк
чужого теста для `studio/mcp/civitai.py` — сборщика ПРОМПТОВ, у которого свой
писатель. Дописывать в него значит нарушить Ц2, поэтому канал фактов принёс
свой файл. Оба подбираются `unittest discover -s studio/mcp/tests`.
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from studio import civitai

#: CLI грузится по пути, а не импортом: `scripts/` не пакет, а развилка кода
#: возврата обязана быть достижима тестом (Т5).
_КОРЕНЬ = Path(__file__).resolve().parents[3]
_СПЕКА = importlib.util.spec_from_file_location(
    "ingest_civitai", _КОРЕНЬ / "scripts" / "ingest_civitai.py"
)
assert _СПЕКА and _СПЕКА.loader
_cli = importlib.util.module_from_spec(_СПЕКА)
_СПЕКА.loader.exec_module(_cli)

ФИКСТУРЫ = _КОРЕНЬ / "studio" / "knowledge" / "civitai_fixtures.json"

#: Настоящие строки живой выдачи, а не выдуманные. Идентификаторы моделей
#: Civitai: 1651125 Wan2.1_14B_FusionX, 2354193 LTX-2.3 All-In-One workflow,
#: 2129484 MultiTalk Lip-Sync, 2448150 LTX-2.3.
БОГАТАЯ = "1651125"
СРЕДНЯЯ = "2354193"
ПУСТАЯ = "2129484"
БЕЗ_КОММЕРЦИИ = "2448150"


def _данные() -> dict:
    return json.loads(ФИКСТУРЫ.read_text(encoding="utf-8"))


def _описания(ключ: str) -> list[str | None]:
    модель = _данные()["модели"][ключ]
    return [модель.get("description")] + [
        v.get("description") for v in модель.get("modelVersions") or []
    ]


class ПлоскийТекст(unittest.TestCase):
    def test_границы_блоков_становятся_точками(self) -> None:
        # Без разделителя два абзаца слипаются, и условие одного встречается с
        # исходом другого — ложное наблюдение из ничего.
        self.assertEqual(
            civitai.текст("<p>12 GB VRAM</p><p>looks great</p>"), "12 GB VRAM . looks great ."
        )

    def test_пустое_описание_даёт_пустую_строку_а_не_падение(self) -> None:
        self.assertEqual(civitai.текст(None), "")

    def test_предложение_короче_границы_не_рассматривается(self) -> None:
        # 24 символа против 26: граница сторожится с обеих сторон.
        коротко = "I ran it on a 3090 aaa."
        длинно = "I ran it on a 3090 and it was fine."
        self.assertEqual(len(коротко), 23)
        self.assertEqual(civitai.предложения(коротко), [])
        self.assertEqual(civitai.предложения(длинно), [длинно])

    def test_слипшийся_абзац_длиннее_потолка_отбрасывается(self) -> None:
        длинный = "I ran it on a 3090 and steps 8 worked. " * 12
        self.assertGreater(len(длинный), 400)
        self.assertEqual(civitai.предложения(длинный.replace(". ", " ")), [])


class ПочемуНеНаблюдение(unittest.TestCase):
    def test_настоящее_наблюдение_проходит(self) -> None:
        фраза = (
            "Video generation works with as few as 6 steps , but 8-10 steps yield the best quality."
        )
        self.assertEqual(civitai.почему_не_наблюдение(фраза), "")

    def test_отчёт_про_железо_проходит_без_голоса_практика(self) -> None:
        # Условие и исход есть, «я» нет: карта названа, и этого достаточно.
        self.assertEqual(
            civitai.почему_не_наблюдение("12GB VRAM cards run out of memory at 720p here."), ""
        )

    def test_голое_требование_к_железу_наблюдением_не_считается(self) -> None:
        # ИЗМЕРЕННАЯ цена правила «без исхода не наблюдение»: живая фраза
        # «This is a 12gb VRam or more workflow.» (модель 2411105) теряется.
        # Это требование, а не отчёт о прогоне, и пускать его пришлось бы через
        # ту же дверь, в которую влезал заголовок раздела «Workflow for 8GB
        # Card users».
        self.assertEqual(
            civitai.почему_не_наблюдение("This is a 12gb VRam or more workflow."),
            "есть условие, но не сказано, что вышло",
        )

    def test_слово_work_внутри_workflow_исходом_не_считается(self) -> None:
        # ПОЙМАНО на живой записи 2026-09-01: заголовок раздела уехал в базу,
        # потому что `work` сидит внутри `Workflow`.
        self.assertEqual(
            civitai.почему_не_наблюдение("Workflow for 8GB Card users"),
            "есть условие, но не сказано, что вышло",
        )

    def test_реклама_карточки_не_наблюдение(self) -> None:
        реклама = (
            "It is one of the fastest 720P@24fps models available, meeting the needs "
            "of both industrial applications and academic research."
        )
        self.assertEqual(
            civitai.почему_не_наблюдение(реклама),
            "ни голоса практика, ни требования к железу — похоже на рекламу карточки",
        )

    def test_благодарность_названа_промо_а_не_отсутствием_условия(self) -> None:
        self.assertEqual(
            civitai.почему_не_наблюдение("Thanks to everyone who tested it at 8 steps and 12GB!"),
            "промо, благодарность или ссылка на соцсеть",
        )

    def test_проблема_установки_отделена_от_поведения(self) -> None:
        self.assertEqual(
            civitai.почему_не_наблюдение("I could not install the node on 12GB, pip fails here."),
            "про установку и окружение, а не про поведение модели",
        )

    def test_впечатление_без_условий_не_наблюдение(self) -> None:
        self.assertEqual(
            civitai.почему_не_наблюдение("I use this model all the time and it is beautiful."),
            "нет условия прогона: ни числа с единицей, ни ручки, ни карты",
        )

    def test_настройка_без_исхода_не_наблюдение(self) -> None:
        self.assertEqual(
            civitai.почему_не_наблюдение("I set the sampler to UniPC and the seed to 159753456."),
            "есть условие, но не сказано, что вышло",
        )


class НаЖивыхОписаниях(unittest.TestCase):
    def test_богатое_описание_даёт_три_наблюдения_из_девяноста_одной_фразы(self) -> None:
        итог = civitai.наблюдения(_описания(БОГАТАЯ))
        self.assertEqual(итог["предложений"], 91)
        self.assertEqual(len(итог["наблюдения"]), 3)

    def test_значение_это_слова_источника_целиком_а_не_имя_модели(self) -> None:
        итог = civitai.наблюдения(_описания(БОГАТАЯ))
        self.assertIn(
            "⚡ Video generation works with as few as 6 steps , but 8–10 steps yield the best quality.",
            итог["наблюдения"],
        )

    def test_среднее_описание_даёт_отчёт_о_тестовом_прогоне(self) -> None:
        итог = civitai.наблюдения(_описания(СРЕДНЯЯ))
        self.assertEqual(len(итог["наблюдения"]), 1)
        self.assertIn(
            "Testrun: 30 second video (1024 x 704) tooks around 40 minutes without any OOM errors.",
            итог["наблюдения"],
        )

    def test_описание_из_ссылок_и_благодарностей_не_даёт_ничего(self) -> None:
        # Негативный контроль (И5): вход, на котором прибор ОБЯЗАН сказать «нет».
        итог = civitai.наблюдения(_описания(ПУСТАЯ))
        self.assertEqual(len(итог["наблюдения"]), 0)
        self.assertEqual(итог["предложений"], 27)

    def test_у_каждой_отсеянной_фразы_есть_названная_причина(self) -> None:
        итог = civitai.наблюдения(_описания(ПУСТАЯ))
        self.assertEqual(sum(итог["отсев"].values()), 27)


class Права(unittest.TestCase):
    def test_пустой_список_разрешений_помечается_некоммерческой(self) -> None:
        метки = civitai.права(_данные()["модели"][БЕЗ_КОММЕРЦИИ])
        self.assertIn("НЕКОММЕРЧЕСКАЯ: allowCommercialUse пуст", метки)

    def test_полный_набор_прав_некоммерческой_не_помечается(self) -> None:
        # Без этого «все некоммерческие» читалось бы как работа детектора.
        метки = civitai.права(_данные()["модели"][ПУСТАЯ])
        self.assertEqual(метки, [])

    def test_отсутствие_поля_это_третий_исход_а_не_свобода(self) -> None:
        метки = civitai.права({"id": 1})
        self.assertEqual(метки, ["НЕ СМОГЛИ ПРОЧИТАТЬ: поля allowCommercialUse нет в ответе"])

    def test_запрет_производных_считывается_отдельной_меткой(self) -> None:
        метки = civitai.права({"allowCommercialUse": ["Sell"], "allowDerivatives": False})
        self.assertEqual(метки, ["allowDerivatives=false"])


class Прогоны(unittest.TestCase):
    def test_версия_с_настройками_у_всех_картинок(self) -> None:
        итог = civitai.прогонные(_данные()["версии"]["2752735"])
        self.assertEqual(итог["outcome"], "годно")
        self.assertEqual(итог["с настройками"], 10)
        self.assertEqual(итог["картинок"], 10)
        self.assertEqual(итог["сводка"]["sampler"], ["Euler"])

    def test_версия_где_настройки_есть_у_части_картинок(self) -> None:
        итог = civitai.прогонные(_данные()["версии"]["1868891"])
        self.assertEqual(итог["с настройками"], 6)
        self.assertEqual(итог["картинок"], 10)

    def test_картинки_без_настроек_это_не_смогли_а_не_годно(self) -> None:
        итог = civitai.прогонные(_данные()["версии"]["2408802"])
        self.assertEqual(итог["outcome"], "не смогли")
        self.assertEqual(итог["почему"], "ни у одной картинки нет настроек прогона в meta")

    def test_картинок_нет_и_это_другая_причина(self) -> None:
        итог = civitai.прогонные({"images": []})
        self.assertEqual(итог["outcome"], "не смогли")
        self.assertEqual(итог["почему"], "картинок нет")

    def test_промпт_в_настройки_прогона_не_берётся(self) -> None:
        # Промпты собирает другой канал; второе место для одного знания — дефект (Е1).
        итог = civitai.прогонные({"images": [{"meta": {"prompt": "a cat", "steps": 8}}]})
        self.assertEqual(итог["сводка"], {"steps": [8]})


class СколькоВерсийСпрашиваем(unittest.TestCase):
    """Потолок на версии — константа-решение, и её обязан сторожить тест.

    Фейковый ходок считает запросы: сети здесь нет (Т4), а развилка вынесена
    из точки входа именно затем, чтобы её можно было спросить (Т5).
    """

    def test_у_модели_с_пятью_версиями_спрашиваются_три(self) -> None:
        запрошено: list[str] = []

        def ходок(url: str) -> tuple[str, bytes]:
            запрошено.append(url)
            return "ok", json.dumps({"id": 1, "images": []}).encode()

        модель = {
            "id": 777,
            "name": "Fake",
            "description": "<p>nothing here</p>",
            "modelVersions": [{"id": n, "description": None} for n in (1, 2, 3, 4, 5)],
        }
        строка = civitai.разобрать(модель, ходок)
        self.assertEqual(len(запрошено), 3)
        self.assertEqual(len(строка["прогоны"]), 3)

    def test_отказ_сети_на_версии_это_не_смогли_а_не_пустой_прогон(self) -> None:
        def ходок(url: str) -> tuple[str, bytes]:
            return "HTTP 503", b""

        строка = civitai.разобрать({"id": 1, "name": "Fake", "modelVersions": [{"id": 9}]}, ходок)
        self.assertEqual(строка["прогоны"][0]["outcome"], "не смогли")
        self.assertEqual(строка["прогоны"][0]["почему"], "HTTP 503")


class Заявки(unittest.TestCase):
    def _строка(self) -> dict:
        return {
            "model_id": "1651125",
            "outcome": "годно",
            "имя": "Wan2.1_14B_FusionX",
            "тип": "Checkpoint",
            "базовая": "Wan Video 14B t2v",
            "автор": "",
            "скачиваний": 39035,
            "права": ["НЕКОММЕРЧЕСКАЯ: allowCommercialUse пуст — коммерческого права не дано"],
            "наблюдения": ["Video generation works with as few as 6 steps."],
            "свидетельства": [
                {
                    "условия": ["121 frames"],
                    "исходы": ["нехватка памяти"],
                    "значение": "121 frames — нехватка памяти",
                }
            ],
            "предложений": 91,
            "отсев": {},
            "отсев второй ступени": {},
            "прогоны": [
                {
                    "outcome": "годно",
                    "версия": 1868891,
                    "имя версии": "V1",
                    "картинок": 10,
                    "с настройками": 6,
                    "сводка": {"steps": [10], "cfgScale": [1], "sampler": ["UniPC"]},
                }
            ],
            "url": "https://civitai.com/models/1651125",
        }

    def test_значение_свидетельства_это_НАШ_пересказ_а_не_фраза_источника(self) -> None:
        # Перемена 2026-09-02: `civitai.com` числится в studio/verbatim.py
        # хостом, где текст пишут люди, и 74 из 118 живых фраз длиннее предела
        # в 15 слов. У источника берутся ЧИСЛА, исход называется нашим ярлыком.
        наблюдение = [r for r in civitai.заявки(self._строка()) if r[1] == "observed_behaviour"][0]
        self.assertEqual(наблюдение[2], "121 frames — нехватка памяти")
        self.assertNotIn("Video generation works", наблюдение[2])
        self.assertLessEqual(len(наблюдение[2].split()), 15)

    def test_свидетельство_несёт_witnessed_иначе_применимости_не_будет(self) -> None:
        # Ради этого поля вторая ступень и заведена: studio/factaxis.py даёт
        # род `witness` строке из `portal` ТОЛЬКО через заполненный `witnessed`.
        наблюдение = [r for r in civitai.заявки(self._строка()) if r[1] == "observed_behaviour"][0]
        self.assertIn("121 frames", наблюдение[5])
        self.assertIn("нехватка памяти", наблюдение[5])
        self.assertIn("наблюдали не мы", наблюдение[5])

    def test_настройки_прогона_идут_БЕЗ_witnessed(self) -> None:
        # Настройки говорят, ЧТО запускали, и молчат о том, ЧТО вышло.
        прогон = [r for r in civitai.заявки(self._строка()) if "model-versions" in r[3]][0]
        self.assertEqual(прогон[5], "")

    def test_право_идёт_БЕЗ_witnessed(self) -> None:
        право = [r for r in civitai.заявки(self._строка()) if r[1] == "license_restriction"][0]
        self.assertEqual(право[5], "")

    def test_своё_рассуждение_уходит_в_ноту_а_не_в_значение(self) -> None:
        наблюдение = [r for r in civitai.заявки(self._строка()) if r[1] == "observed_behaviour"][0]
        self.assertNotIn("Civitai", наблюдение[2])
        self.assertIn("описания модели на Civitai", наблюдение[4])

    def test_имя_модели_приводится_к_ключу_базы(self) -> None:
        self.assertEqual(civitai.заявки(self._строка())[0][0], "wan2-1-14b-fusionx")

    def test_право_идёт_отдельной_заявкой_со_своим_атрибутом(self) -> None:
        права = [r for r in civitai.заявки(self._строка()) if r[1] == "license_restriction"]
        self.assertEqual(len(права), 1)
        self.assertEqual(
            права[0][2], "НЕКОММЕРЧЕСКАЯ: allowCommercialUse пуст — коммерческого права не дано"
        )

    def test_настройки_прогона_ссылаются_на_версию_а_не_на_карточку(self) -> None:
        прогон = [r for r in civitai.заявки(self._строка()) if "model-versions" in r[3]][0]
        self.assertEqual(прогон[2], "steps 10; cfgScale 1; sampler UniPC")
        self.assertEqual(прогон[3], "https://civitai.com/api/v1/model-versions/1868891")

    def test_два_флага_прав_это_одна_заявка_а_не_две(self) -> None:
        строка = self._строка()
        строка["права"] = ["производные запрещены: allowDerivatives false", "вторая метка"]
        права = [r for r in civitai.заявки(строка) if r[1] == "license_restriction"]
        self.assertEqual(len(права), 1)
        self.assertEqual(права[0][2], "производные запрещены: allowDerivatives false; вторая метка")

    def test_три_версии_с_одинаковыми_настройками_дают_одну_заявку(self) -> None:
        # ИЗМЕРЕНО на живой модели 1651125: три версии, одна и та же строка
        # «steps 10; cfgScale 1; sampler UniPC», и база считала одно наблюдение
        # трижды.
        строка = self._строка()
        прогон = строка["прогоны"][0]
        строка["прогоны"] = [dict(прогон, версия=n) for n in (1868891, 1882322, 1878555)]
        прогоны = [r for r in civitai.заявки(строка) if "model-versions" in r[3]]
        self.assertEqual(len(прогоны), 1)
        self.assertEqual(прогоны[0][2], "steps 10; cfgScale 1; sampler UniPC")
        self.assertIn("18 из 30", прогоны[0][4])

    def test_настройки_разных_версий_сливаются_в_одно_значение(self) -> None:
        строка = self._строка()
        первый = строка["прогоны"][0]
        второй = dict(
            первый, версия=2, сводка={"steps": [8], "cfgScale": [1], "sampler": ["Euler"]}
        )
        строка["прогоны"] = [первый, второй]
        прогон = [r for r in civitai.заявки(строка) if "model-versions" in r[3]][0]
        self.assertEqual(прогон[2], "steps 10, 8; cfgScale 1; sampler UniPC, Euler")

    def test_неудавшийся_прогон_заявкой_не_становится(self) -> None:
        строка = self._строка()
        строка["прогоны"] = [{"outcome": "не смогли", "версия": 1, "почему": "картинок нет"}]
        self.assertEqual([r for r in civitai.заявки(строка) if "model-versions" in r[3]], [])


class Гейт(unittest.TestCase):
    def test_на_настоящих_фикстурах_исход_годно_и_проверок_не_ноль(self) -> None:
        итог = _cli.проверка()
        self.assertEqual(итог["outcome"], "годно")
        self.assertEqual(итог["нарушений"], 0)
        self.assertEqual(итог["проверено"], 28)

    def test_нет_файла_это_не_смогли_а_не_успех(self) -> None:
        # Ноль нарушений при нуле проверок — не успех (Р2).
        итог = _cli.проверка(Path("/nonexistent/civitai_fixtures.json"))
        self.assertEqual(итог["outcome"], "не смогли")
        self.assertEqual(итог["проверено"], 0)

    def test_молчащая_фикстура_заговорила_и_гейт_краснеет(self) -> None:
        данные = _данные()
        данные["модели"][ПУСТАЯ] = данные["модели"][БОГАТАЯ]
        with tempfile.TemporaryDirectory() as каталог:
            путь = Path(каталог) / "f.json"
            путь.write_text(json.dumps(данные, ensure_ascii=False), encoding="utf-8")
            итог = _cli.проверка(путь)
        self.assertEqual(итог["outcome"], "не годно")
        # Две беды, а не одна: молчащая фикстура заговорила И её измеренное
        # число наблюдений (ноль) разошлось с найденным.
        self.assertEqual(итог["нарушений"], 2)

    def test_код_возврата_гейта_годно_это_ноль(self) -> None:
        self.assertEqual(_cli.main(["--check"]), 0)

    def test_без_моделей_код_возврата_два(self) -> None:
        # Третий исход не сворачивается в первый: «нечего разбирать» ≠ «разобрали».
        self.assertEqual(_cli.main([]), 2)


class ВтораяСтупень(unittest.TestCase):
    """Признак разделения: свидетельство применимости против рекомендации ручки.

    Ожидаемое здесь — ЛИТЕРАЛЫ, а не константы модуля (Т2): импортированный
    порог поедет вместе с кодом и промолчит.
    """

    def test_условие_числом_плюс_событие_это_свидетельство(self) -> None:
        одно = civitai.свидетельство(
            "If doing more than 121 frames, and you OOM or if your low on VRAM you will batch."
        )
        assert одно is not None
        self.assertEqual(одно["значение"], "121 frames — нехватка памяти")

    def test_рекомендация_ручки_свидетельством_НЕ_является(self) -> None:
        # Живая фраза с карточки 1662740. Условие есть, голос есть, события нет.
        self.assertEqual(
            civitai.почему_не_свидетельство("Recommend to use with strength 0.85-0.9 for best."),
            "оценка настройки, а не наблюдённый исход",
        )

    def test_событие_без_числа_свидетельством_НЕ_является(self) -> None:
        self.assertEqual(
            civitai.почему_не_свидетельство("I set the sampler to UniPC and it works better."),
            "условие не названо числом или картой",
        )

    def test_отрицание_переворачивает_ярлык(self) -> None:
        # Живая фраза с карточки 2354193. Без этого правила канал записал бы
        # «нехватка памяти» там, где человек сообщил обратное.
        self.assertIn(
            "без: нехватка памяти",
            civitai.исходы(
                "Testrun: 30 second video (1024 x 704) tooks around 40 minutes"
                " without any OOM errors"
            ),
        )

    def test_без_отрицания_ярлык_прямой(self) -> None:
        # Негативный контроль к предыдущему (И5): приставка «без» не должна
        # появляться сама по себе.
        self.assertEqual(civitai.исходы("At 121 frames you OOM here."), ["нехватка памяти"])

    def test_время_прогона_требует_и_числа_и_слова_о_прогоне(self) -> None:
        self.assertIn("время прогона", civitai.исходы("it takes around 40 minutes here"))
        # Длина ролика — не время работы.
        self.assertNotIn("время прогона", civitai.исходы("even 30-50 second videos look fine"))
        # Слово о прогоне без времени — тоже нет.
        self.assertNotIn("время прогона", civitai.исходы("it used to take 10 steps"))

    def test_фраза_про_обучение_отсеивается_с_названной_причиной(self) -> None:
        self.assertEqual(
            civitai.почему_не_свидетельство(
                "finetrainers currently does require 24GB VRAM to train HV and I failed with it."
            ),
            "про обучение модели, а не про её прогон",
        )

    def test_отрицание_из_дальней_части_фразы_знак_НЕ_переворачивает(self) -> None:
        # Окно, а не всё предложение: «no» за сорок символов до события —
        # чужое отрицание. Расширение окна ловится этим тестом.
        self.assertEqual(
            civitai.исходы("There is no reason to worry about this and at 121 frames you OOM."),
            ["нехватка памяти"],
        )

    def test_отрицание_через_два_слова_всё_ещё_читается(self) -> None:
        # Вторая сторона мутации (Т1): правило, сжатое до «отрицание вплотную»,
        # пропустит «without any visible OOM» и запишет отказ там, где его нет.
        self.assertIn(
            "без: нехватка памяти",
            civitai.исходы("40 minutes and it ran without any visible OOM errors"),
        )

    def test_условий_в_значении_ровно_четыре(self) -> None:
        одно = civitai.свидетельство(
            "I run 12GB on a 3090 with 8 steps, cfg 1 and 121 frames and it OOMs every time."
        )
        assert одно is not None
        self.assertEqual(len(одно["условия"]), 4)

    def test_обучение_отсеивается_и_прогон_остаётся(self) -> None:
        # Пара, а не одна проверка (И5): правило, которое ловит ВСЁ, здесь
        # краснеет так же, как правило, которое не ловит ничего.
        self.assertEqual(
            civitai.почему_не_свидетельство("I trained it for 20 epochs and it failed at 24GB."),
            "про обучение модели, а не про её прогон",
        )
        self.assertEqual(
            civitai.почему_не_свидетельство("I run 121 frames on a 3090 and you OOM here."), ""
        )

    def test_декада_не_читается_как_секунды(self) -> None:
        self.assertEqual(civitai.условия_прогона("my 2000s analog core lora"), [])

    def test_потолок_откровенности_ловит_маску_а_не_булево(self) -> None:
        # ИЗМЕРЕНО прошлой сессией: `nsfw` был False у карточки с маской 31.
        self.assertTrue(civitai.выше_потолка({"nsfw": False, "nsfwLevel": 31}))
        self.assertFalse(civitai.выше_потолка({"nsfwLevel": 7}))

    def test_маски_нет_значит_выше_а_не_безопасно(self) -> None:
        self.assertTrue(civitai.выше_потолка({}))


if __name__ == "__main__":
    unittest.main()
