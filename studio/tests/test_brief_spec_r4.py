"""Структурное понимание брифа, четвёртый круг (2026-10-15): `studio/brief_spec.py`.

Валидатор третьего круга показал, что понимание брифа держалось на списках
подстрок, подогнанных под его же фразы. Здесь — НАШИ перефразировки (не его
текст), по три английских и три русских на сценарий, и `spec` от вызывающего.

Т2: ожидания — литералы. Т4: сети нет, база — синтетические факты (состав шагов
и разбор от живой базы не зависят). Т1: константы-решения модуля мутируются в
`scripts/mutate_brief_spec.py`; каждая сторожится здесь тестом с обеих сторон.
"""

from __future__ import annotations

import unittest
from datetime import date

import studio.planner as pn
from studio import brief_spec as bs
from studio import clarify, pricing
from studio.selfrag.facts import Fact

СЕГОДНЯ = date(2026, 10, 15)


def факт(model: str, attribute: str, value: str) -> Fact:
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url=f"https://example.invalid/{model}",
        tier="vendor",
        stated_on="2026-10-01",
    )


#: Картинка за $0.05 и оживление за $0.5 прогон до 10 с.
БАЗА: tuple[Fact, ...] = (
    факт("x-t2i", "architecture", "text-to-image model"),
    факт("x-t2i", "price_per_image_usd", "$0.05 per image"),
    факт("x-i2v", "architecture", "image-to-video model"),
    факт("x-i2v", "max_seconds", "10"),
    факт("x-i2v", "price_per_run_usd", "$0.5 per run"),
)


def план(бриф: str, **kw) -> dict:
    kw.setdefault("facts", list(БАЗА))
    kw.setdefault("today", СЕГОДНЯ)
    kw.setdefault("full", True)
    return pn.plan(бриф, **kw)


def шаги(итог: dict) -> list[tuple[str, int | None]]:
    return [(ш["step"], ш.get("shots")) for ш in итог["steps"]]


def поля(итог: dict) -> dict:
    return {к: в["value"] for к, в in итог["understood_as"]["fields"].items()}


def источники(итог: dict) -> dict:
    return {к: в["from"] for к, в in итог["understood_as"]["fields"].items()}


class ОживитьКаждый(unittest.TestCase):
    """Сценарий «N кадров, оживить каждый по X с»: шоты, длина шота, цена за шот."""

    СЛУЧАИ = {
        "Four packshots of our sneakers, bring each one to life for 6 seconds": (4, 6.0, 24.0),
        "make 2 stills move, 4 sec apiece, square format": (2, 4.0, 8.0),
        "animate every one of the five banner images, 3s per clip": (5, 3.0, 15.0),
        "пять кадров упаковки — каждый анимировать на 6 сек": (5, 6.0, 30.0),
        "две картинки, оживи каждую на 5 с, вертикально": (2, 5.0, 10.0),
        "три фото товара, оживить каждое по 4 секунды": (3, 4.0, 12.0),
    }

    def test_шоты_и_длина_шота_из_структуры(self) -> None:
        got = {}
        for б in self.СЛУЧАИ:
            с = bs.from_text(б)
            got[б] = (с.shots, с.per_shot_s, с.duration_s)
        self.assertEqual(self.СЛУЧАИ, got)

    def test_каждый_шаг_умножен_на_шоты(self) -> None:
        ждём = {
            "Four packshots of our sneakers, bring each one to life for 6 seconds": [
                ("генерация_изображения", 4),
                ("оживление", 4),
            ],
            "make 2 stills move, 4 sec apiece, square format": [
                ("генерация_изображения", 2),
                ("оживление", 2),
            ],
            "animate every one of the five banner images, 3s per clip": [
                ("генерация_изображения", 5),
                ("оживление", 5),
            ],
            "пять кадров упаковки — каждый анимировать на 6 сек": [
                ("генерация_изображения", 5),
                ("оживление", 5),
            ],
            "две картинки, оживи каждую на 5 с, вертикально": [
                ("генерация_изображения", 2),
                ("оживление", 2),
            ],
            # Фото принесено: кадров не генерируем, оживляем три своих.
            "три фото товара, оживить каждое по 4 секунды": [("оживление", 3)],
        }
        self.assertEqual(ждём, {б: шаги(план(б)) for б in ждём})

    def test_цена_за_шот_а_не_за_один_клип(self) -> None:
        """«animate each 5s» над 3 кадрами — 3 прогона, а не ceil(15/10) = 2."""
        итог = план("3 product stills, animate each for 5 s, budget $4")
        смета = {с["step"]: (с["usd"], с.get("shots"), с.get("usd_per_shot")) for с in итог["pipeline_price"]["смета"]["steps"]}
        self.assertEqual(
            {"генерация_изображения": (0.15, 3, 0.05), "оживление": (1.5, 3, 0.5)},
            смета,
        )

    def test_прогоны_по_шотам_в_ценах(self) -> None:
        ставки = pricing.rates("$0.5 per run", "price_per_run_usd")
        нужда = pricing.Need(seconds=15.0, max_run_seconds=10.0, shots=3, mode="i2v")
        self.assertEqual([1.5], [o.usd for o in pricing.estimate(ставки, нужда)])
        # Негативный контроль: без шотов — одним куском, ceil(15/10) = 2.
        нужда = pricing.Need(seconds=15.0, max_run_seconds=10.0, mode="i2v")
        self.assertEqual([1.0], [o.usd for o in pricing.estimate(ставки, нужда)])


class СтильИГолос(unittest.TestCase):
    """Сценарий «стиль + длительность + голос на языке»: видео И речь, язык речи."""

    СЛУЧАИ = {
        "a 12-second watercolor cartoon narrated in German": ("german", 12.0),
        "8s claymation clip, voice in French": ("french", 8.0),
        "15 sec photoreal scene with a Korean voice": ("korean", 15.0),
        "мультик 10 секунд с голосом на японском": ("japanese", 10.0),
        "аниме-ролик на 8 сек, озвучка на испанском": ("spanish", 8.0),
        "пластилиновый мультфильм на 15 секунд, диктор на немецком": ("german", 15.0),
    }

    def test_видео_с_речью_на_языке(self) -> None:
        got = {}
        for б in self.СЛУЧАИ:
            итог = план(б)
            got[б] = (
                [ш for ш, _ in шаги(итог)],
                итог["languages"],
                поля(итог)["duration_s"],
                итог["question"],
            )
        ждём = {
            б: (["озвучка", "генерация_видео"], [язык], сек, None)
            for б, (язык, сек) in self.СЛУЧАИ.items()
        }
        self.assertEqual(ждём, got)

    def test_голос_поверх_картинки_назван_допущением(self) -> None:
        итог = план("8s claymation clip, voice in French")
        self.assertEqual(("voiceover", "default"), (поля(итог)["audio"], источники(итог)["audio"]))
        self.assertIn(
            "the voice plays over the picture, nobody on screen moves their lips",
            итог["understood_as"]["assumptions"][1],
        )


class ТехническийЗаказ(unittest.TestCase):
    """Сценарий «разрешение + fps + секунды + без звука»: генерация видео без звука."""

    СЛУЧАИ = {
        "1440p 30fps, 5 seconds, silent": ("1440p", 30, 5.0),
        "8k at 60 fps, 4s long, without sound": ("8k", 60, 4.0),
        "2160p 25 fps 7 second shot, mute": ("2160p", 25, 7.0),
        "4к 25 кадров в секунду, 6 секунд, без звука": ("4k", 25, 6.0),
        "720p, 24 fps, 3 секунды, звук не нужен": ("720p", 24, 3.0),
        "8к, 50 fps, 4 секунды, беззвучно": ("8k", 50, 4.0),
    }

    def test_план_и_понятое(self) -> None:
        got = {}
        for б in self.СЛУЧАИ:
            итог = план(б)
            п = поля(итог)
            got[б] = ([ш for ш, _ in шаги(итог)], п["resolution"], п["fps"], п["duration_s"], п["audio"])
        ждём = {б: (["генерация_видео"], р, f, с, "none") for б, (р, f, с) in self.СЛУЧАИ.items()}
        self.assertEqual(ждём, got)

    def test_ролик_без_слова_о_съёмке_спрашивает(self) -> None:
        """«ролик» без способа — прежний вопрос «видео уже снято?» (решение владельца)."""
        итог = план("1080p 30fps ролик на 5 с, беззвучный")
        self.assertEqual(([], "есть_ли_исходное_видео"), (итог["steps"], итог["question"]["axis"]))


class ЗаменаЛица(unittest.TestCase):
    """Сценарий «заменить лицо/персонажа в СВОЁМ видео»: шаг замены, без генерации видео."""

    БРИФЫ = (
        "swap the presenter's face in our 30s clip",
        "put a different actor into my existing footage, replacing the lead's face",
        "replace the character in the video I uploaded",
        "замени лицо актёра в моём ролике на 15 секунд",
        "подменить персонажа в нашем готовом видео",
        "заменить героя на нашем видео длиной 20 с",
    )

    def test_замена_персонажа_на_своём_видео(self) -> None:
        got = {}
        for б in self.БРИФЫ:
            итог = план(б)
            got[б] = ([ш for ш, _ in шаги(итог)], поля(итог)["task"], поля(итог)["inputs"], итог["question"])
        ждём = {б: (["замена_персонажа"], "face-replace", ["video"], None) for б in self.БРИФЫ}
        self.assertEqual(ждём, got)

    def test_референс_лица_назван_допущением(self) -> None:
        итог = план("x", spec={"task": "face-replace", "inputs": ["video"]})
        self.assertEqual(
            [
                "the new face/character comes from YOUR reference image — none is named in the brief; "
                "attach it, or pass spec.inputs=['video', 'photo']"
            ],
            итог["understood_as"]["assumptions"],
        )
        итог = план("x", spec={"task": "face-replace", "inputs": ["video", "photo"]})
        self.assertEqual(([("замена_персонажа", None)], []), (шаги(итог), итог["understood_as"]["assumptions"]))

    def test_без_своего_видео_вопрос(self) -> None:
        итог = план("x", spec={"task": "face-replace", "inputs": []})
        self.assertEqual(([], "вход_задачи", "нужен_ответ_заказчика"), (итог["steps"], итог["question"]["axis"], итог["reason"]))


class ПереводСвоегоВидео(unittest.TestCase):
    """Сценарий «перевести своё видео»: дубляж + липсинк, без генерации и без «уже снято?»."""

    СЛУЧАИ = {
        "dub our 2-minute product demo into Portuguese": "portuguese",
        "my 30 sec reel needs to be in French - translate it": "french",
        "localize the explainer video we shot into German, keep the lips matching": "german",
        "переведи наше видео на 40 секунд на немецкий": "german",
        "дубляж моего ролика на французский": "french",
        "локализовать готовый ролик на португальский": "portuguese",
    }

    def test_дубляж_и_губы_на_целевом_языке(self) -> None:
        got = {}
        for б in self.СЛУЧАИ:
            итог = план(б)
            got[б] = ([ш for ш, _ in шаги(итог)], итог["languages"], итог["question"])
        ждём = {б: (["дубляж", "липсинк"], [язык], None) for б, язык in self.СЛУЧАИ.items()}
        self.assertEqual(ждём, got)

    def test_притяжательное_в_окне_слов(self) -> None:
        """«my 45s English video»: между `my` и `video` два слова — видео принесено."""
        self.assertEqual(("video",), bs.from_text("please dub my 45s English video").inputs)


class АватарБезСнимка(unittest.TestCase):
    """Сценарий «говорящий аватар, снимка нет»: кадр -> озвучка -> аватар, 1080p названо."""

    БРИФЫ = (
        "an AI avatar presenting our app for 25 seconds",
        "talking-head spokesperson video, 15s, Spanish, no footage",
        "need a virtual avatar to read our 20 sec script",
        "аватар рассказывает о продукте 30 секунд",
        "говорящая голова на 20 секунд для рекламы, фото нет",
        "нужен ИИ-аватар, который зачитает наш текст, 15 с",
    )

    def test_кадр_озвучка_аватар(self) -> None:
        got = {б: [ш for ш, _ in шаги(план(б))] for б in self.БРИФЫ}
        ждём = {б: ["генерация_изображения", "озвучка", "говорящий_аватар"] for б in self.БРИФЫ}
        self.assertEqual(ждём, got)

    def test_разрешение_по_умолчанию_названо(self) -> None:
        итог = план("an AI avatar presenting our app for 25 seconds")
        self.assertEqual(("1080p", "default"), (поля(итог)["resolution"], источники(итог)["resolution"]))
        self.assertEqual(
            ["resolution not named — 1080p assumed (delivery standard); pass spec.resolution to change"],
            итог["understood_as"]["assumptions"],
        )
        итог = план("vertical 9:16 avatar ad, 20 s")
        self.assertEqual(
            ["resolution not named — 1080p assumed (9:16 ad standard); pass spec.resolution to change"],
            итог["understood_as"]["assumptions"],
        )

    def test_снимок_принесён_кадр_не_генерируется(self) -> None:
        итог = план("x", spec={"task": "avatar", "inputs": ["photo"]})
        self.assertEqual(["озвучка", "говорящий_аватар"], [ш for ш, _ in шаги(итог)])


class Многоперсонажный(unittest.TestCase):
    """Ключевых кадров не меньше шотов; шоты — ceil(длительность / предел модели)."""

    def test_шоты_из_предела_выбранной_модели(self) -> None:
        итог = план("x", spec={"outputs": ["video"], "characters": 2, "duration_s": 40, "inputs": []})
        self.assertEqual([("генерация_изображения", 4), ("оживление", 4)], шаги(итог))
        self.assertEqual("ceil(40 s / 10 s max run of the chosen model)", итог["understood_as"]["shots_basis"])
        self.assertEqual("derived", источники(итог)["shots"])

    def test_предел_не_записан_допущение_названо(self) -> None:
        база = [f for f in БАЗА if f.attribute != "max_seconds"]
        итог = план("x", facts=база, spec={"outputs": ["video"], "characters": 2, "duration_s": 40, "inputs": []})
        self.assertEqual([("генерация_изображения", 5), ("оживление", 5)], шаги(итог))
        self.assertEqual(
            "ceil(40 s / 8 s assumed shot — the model records no max run)", итог["understood_as"]["shots_basis"]
        )

    def test_один_персонаж_без_ключевых_кадров(self) -> None:
        """MULTI_CHARACTER_MIN с другой стороны: один персонаж — видео с нуля."""
        итог = план("x", spec={"outputs": ["video"], "characters": 1, "duration_s": 40, "inputs": []})
        self.assertEqual(["генерация_видео"], [ш for ш, _ in шаги(итог)])

    def test_персонажи_из_текста(self) -> None:
        self.assertEqual(
            {"three heroes duel, 30s": 3, "бой двух боксёров, 20 секунд": 2, "fighters face off, 10 s": 2, "a woman walks, 5 s": None},
            {б: bs.from_text(б).characters for б in ("three heroes duel, 30s", "бой двух боксёров, 20 секунд", "fighters face off, 10 s", "a woman walks, 5 s")},
        )


class СпецификацияСтаршеТекста(unittest.TestCase):
    """`spec` вызывающего: поле spec старше разбора текста; плохой spec — отказ с перечнем."""

    def test_spec_задаёт_работу_которой_в_тексте_нет(self) -> None:
        итог = план("сделайте как обсуждали", spec={"task": "dub-translate", "inputs": ["video"], "languages": ["spanish"]})
        self.assertEqual(["дубляж", "липсинк"], [ш for ш, _ in шаги(итог)])
        self.assertEqual(["spanish"], итог["languages"])
        self.assertEqual({"task": "spec", "inputs": "spec", "languages": "spec"}, {
            к: в for к, в in источники(итог).items() if к in ("task", "inputs", "languages")
        })

    def test_spec_перекрывает_прочитанное(self) -> None:
        итог = план("4K 24fps cinematic 6s, no audio", spec={"resolution": "720p", "duration_s": 3})
        п, и = поля(итог), источники(итог)
        self.assertEqual(
            (("720p", "spec"), (3.0, "spec"), (24, "text")),
            ((п["resolution"], и["resolution"]), (п["duration_s"], и["duration_s"]), (п["fps"], и["fps"])),
        )

    def test_пустые_входы_снимают_вопрос_о_съёмке(self) -> None:
        бриф = "We want a short clip for instagram"
        self.assertEqual("есть_ли_исходное_видео", план(бриф)["question"]["axis"])
        итог = план(бриф, spec={"outputs": ["video"], "inputs": []})
        self.assertEqual((["генерация_видео"], None), ([ш for ш, _ in шаги(итог)], итог["question"]))

    def test_шоты_и_длина_шота_из_spec(self) -> None:
        итог = план("x", spec={"task": "animate", "shots": 3, "per_shot_s": 5, "inputs": ["photo"]})
        self.assertEqual(([("оживление", 3)], 15.0), (шаги(итог), поля(итог)["duration_s"]))

    def test_бюджет_из_spec(self) -> None:
        итог = план("x", spec={"task": "animate", "inputs": ["photo"], "budget_usd": 2})
        self.assertEqual(2.0, итог["budget"]["amount"])

    def test_плохой_spec_отказ_с_перечнем(self) -> None:
        итог = план("x", spec={"task": "dance", "duration_s": -1, "colour": "red", "resolution": "big"})
        self.assertEqual(("fail", "spec_не_разобран", []), (итог["outcome"], итог["reason"], итог["steps"]))
        self.assertEqual(
            [
                "spec.colour: unknown field (known: task, outputs, duration_s, shots, per_shot_s, characters, "
                "resolution, aspect, fps, audio, languages, inputs, objective, budget_usd, self_host, jurisdiction, "
                "budget, people, conditions, open_weights)",
                "spec.task: dance not in generate, animate, lipsync, dub-translate, face-replace, avatar, upscale, edit, "
                "restore, remove-background, interpolate, transcribe, voice-clone, turntable, captions, "
                "video-edit, r2v, music-visualiser, sing-photo, cut-to-shorts",
                "spec.duration_s=-1: must be a finite number above 0",
                "spec.resolution='big': not a resolution (use one of 8k, 4k, 2160p, 2.7k, 1440p, 2k, 1080p, full hd, "
                "fullhd, fhd, 720p, hd, 540p, 480p or WIDTHxHEIGHT)",
            ],
            итог["spec_errors"],
        )

    def test_spec_доходит_через_сервер(self) -> None:
        import json

        from studio.mcp import server

        def _план(бриф, creative="", budget_usd=None, spec=None):
            return {"brief": бриф, "spec": spec}

        out, ignored = server.plan_call("b", spec={"task": "avatar"}, plan_fn=_план)
        self.assertEqual(({"brief": "b", "spec": {"task": "avatar"}}, []), (out, ignored))

        def _старый(бриф, creative="", budget_usd=None):
            return {}

        self.assertEqual(["spec"], server.plan_call("b", spec={"task": "avatar"}, plan_fn=_старый)[1])
        # И сам инструмент принимает spec, а плохой spec возвращает отказом.
        итог = json.loads(server.plan_pipeline("make a clip", spec={"task": "dance"}))
        self.assertEqual("spec_не_разобран", итог["reason"])


class ВопросВместоПустоты(unittest.TestCase):
    """Р1: шагов нет, а бриф о медиа — вопрос, называющий, чего не хватает."""

    def test_вопрос_называет_недостающее(self) -> None:
        в = pn.вопрос_чего_нет(bs.Spec(duration_s=30.0, aspect="9:16", source={"duration_s": "text", "aspect": "text"}))
        self.assertEqual(
            (
                "что_заказано",
                "not everything is understood — name what should come out (video / image / speech / music / sound "
                "effects); what you already have (photo, video, audio, script — or nothing)",
            ),
            (в.ось, в.english[0]),
        )

    def test_пустой_план_о_медиа_спрашивает(self) -> None:
        for б in ("1080p, 9:16, budget $10", "вертикально 1080p, бюджет 10 долларов"):
            итог = план(б)
            self.assertEqual(
                ([], "нужен_ответ_заказчика", "что_заказано"), (итог["steps"], итог["reason"], итог["question"]["axis"]), б
            )

    def test_без_признаков_медиа_вопроса_нет(self) -> None:
        self.assertIsNone(pn.вопрос_чего_нет(bs.Spec()))
        # «видеопоток» — не заказ видео: слово медиа считается целым словом.
        self.assertEqual((), bs.from_text("пайплайн управляет манипулятором по видеопотоку").outputs)
        итог = план("Посчитайте юнит-экономику подписки на год")
        self.assertEqual(("шаги_не_выведены", None), (итог["reason"], итог["question"]))

    def test_эхо_на_любом_ответе(self) -> None:
        итог = план("Посчитайте юнит-экономику подписки на год")
        self.assertIn("understood_as", итог)
        сжатый = pn.plan("make 2 stills move, 4 sec apiece", facts=list(БАЗА), today=СЕГОДНЯ)
        self.assertEqual(2, сжатый["understood_as"]["fields"]["shots"]["value"])
        self.assertEqual([2, 2], [ш["shots"] for ш in сжатый["steps"]])


class ГраницыКонстант(unittest.TestCase):
    """Т1: каждая константа-решение — тест с обеих сторон границы."""

    def test_окно_притяжательного(self) -> None:
        # Три слова между `our` и `video` — принесено; четыре — нет. Без глагола
        # работы: он сам делает объект входом и заслонил бы окно.
        self.assertEqual(("video",), bs.from_text("here is our new 30s product video").inputs)
        self.assertEqual((), bs.from_text("here is our new 30s shiny product video").inputs)

    def test_окно_объекта(self) -> None:
        # Четыре слова между глаголом работы и объектом — вход; пять — нет.
        self.assertEqual(("photo",), bs.from_text("animate the large glossy product photo").inputs)
        self.assertEqual((), bs.from_text("animate the five large glossy product photo").inputs)

    def test_работа_называет_выход(self) -> None:
        """«фото нет» в брифе о говорящей голове — не заказ картинки (`TASK_OUTPUTS`)."""
        self.assertEqual(
            ("video", "speech"), bs.from_text("говорящая голова на 20 секунд для рекламы, фото нет").outputs
        )

    def test_своё_видео_без_работы_не_генерируется_заново(self) -> None:
        итог = план("x", spec={"outputs": ["video"], "inputs": ["video"]})
        self.assertEqual(([], "шаги_не_выведены"), (итог["steps"], итог["reason"]))

    def test_окно_по(self) -> None:
        # Одно слово между «по» и числом — шот; два — уже не про шот.
        self.assertEqual(5.0, bs.from_text("три сцены по целых 5 секунд").per_shot_s)
        self.assertIsNone(bs.from_text("по брифу ролик 30 секунд").per_shot_s)

    def test_разрешение_по_умолчанию(self) -> None:
        self.assertEqual("1080p", bs.DEFAULT_VIDEO_RESOLUTION)
        с = bs.with_defaults(bs.Spec(outputs=("video",)), ролик=True)
        self.assertEqual(((1920, 1080), "default"), (bs.frame(с), с.source["resolution"]))
        # Видео принесено — допущения нет: кадр его собственный.
        с = bs.with_defaults(bs.Spec(outputs=("video",), inputs=("video",)), ролик=True)
        self.assertIsNone(с.resolution)

    def test_маршрут_старше_на_задачах(self) -> None:
        self.assertEqual(
            (True, False, True, False, False),
            (
                bs.route_first(bs.Spec(task="dub-translate", inputs=("video",))),
                bs.route_first(bs.Spec(task="dub-translate")),
                bs.route_first(bs.Spec(task="avatar")),
                bs.route_first(bs.Spec(task="avatar", inputs=("photo",))),
                bs.route_first(bs.Spec(task="generate")),
            ),
        )

    def test_чужое_ремесло_не_понимается_маршрутом(self) -> None:
        for б in ("Please cut the footage we already shot into a 2 minute montage", "смонтировать отснятое в ролик на минуту"):
            итог = план(б)
            self.assertEqual(([], None), (итог["steps"], итог["question"]), б)

    def test_вопрос_о_съёмке_остаётся_для_результата_без_способа(self) -> None:
        """И5: маршрут не глушит вопрос «видео уже снято?» там, где его задавали."""
        self.assertEqual(clarify.ОСЬ_ИСХОДНИК, план("I need a 30 second promo for my bakery")["question"]["axis"])


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
