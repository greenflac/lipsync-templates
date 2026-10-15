"""Понимание брифа, аудит третьего круга 2026-10-15 (находки 5, 6, 7, 8, 14).

Каждая находка — литералом (Т2), на английском И русском брифе. Сеть не нужна
(Т4): база — синтетические факты либо её нет вовсе (разбор брифа и состав
шагов от базы не зависят).
"""

from __future__ import annotations

import unittest
from datetime import date

import studio.planner as pn
from studio import clarify, pricing
from studio.selfrag.facts import Fact

СЕГОДНЯ = date(2026, 10, 15)


def факт(model: str, attribute: str, value: str, tier: str = "vendor") -> Fact:
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url=f"https://example.invalid/{model}",
        tier=tier,
        stated_on="2026-10-01",
    )


def оп(имя: str) -> pn.Operation:
    return next(о for о in pn.OPERATIONS if о.name == имя)


def замкнуто(бриф: str) -> list[str]:
    операции, _ = pn.замкнуть(pn.derive(бриф), pn.inputs_of(бриф), бриф)
    return [о.name for о in операции]


def вопрос(бриф: str) -> str | None:
    есть = pn.inputs_of(бриф)
    операции, дописаны = pn.замкнуть(pn.derive(бриф), есть, бриф)
    в = pn.вопрос_по_плану(бриф, операции, есть, дописаны)
    return в.ось if в else None


#: Две картиночные модели: одна берёт за ЗАПРОС, другая — за картинку.
КАРТИНКИ: tuple[Fact, ...] = (
    факт("а-text-to-image", "architecture", "text-to-image model"),
    факт("а-text-to-image", "price_per_run_usd", "$1 per run"),
    факт("а-text-to-image", "license", "commercial use allowed"),
    факт("б-text-to-image", "architecture", "text-to-image model"),
    факт("б-text-to-image", "price_per_image_usd", "$0.1 per image"),
    факт("б-text-to-image", "license", "commercial use allowed"),
)


class Находка5СколькоКадров(unittest.TestCase):
    def test_число_кадров_из_брифа(self) -> None:
        случаи = {
            "photoreal keyframe images for a storyboard, 6 images, budget $1": 6,
            "6 ключевых кадров для MMA ролика": 6,
            "six keyframes for an MMA ad": 6,
            "шесть кадров для раскадровки": 6,
            "12 photoreal stills": 12,
            "4 картинки в одном стиле": 4,
            # Частота кадров — не заказ кадров.
            "30 кадров в секунду, ролик 10 секунд": None,
            "shoot at 30 frames per second": None,
            "24 fps, 10 second video": None,
            "10 second video, 1080x1920": None,
        }
        self.assertEqual(случаи, {б: pn.кадров_заказано(б) for б in случаи})

    def test_нужда_картиночного_шага_это_n_кадров_без_секунд(self) -> None:
        длительность = pn.dur.просят("ролик 40 секунд")
        нужда = pn.нужда_шага(оп("генерация_изображения"), длительность, None, 6)
        self.assertEqual((6.0, None), (нужда.images, нужда.seconds))
        # Не названо — одна картинка, как было.
        нужда = pn.нужда_шага(оп("генерация_изображения"), длительность, None)
        self.assertEqual(1.0, нужда.images)
        # Видео и речь числа кадров не берут.
        self.assertEqual(0.0, pn.нужда_шага(оп("генерация_видео"), длительность, None, 6).images)
        речь = pn.нужда_шага(оп("озвучка"), длительность, None, 6)
        self.assertEqual((1.0, 40.0, 600.0), (речь.images, речь.seconds, речь.chars))

    def test_цена_за_запрос_умножается_на_кадры(self) -> None:
        ставка = pricing.Rate(amount=1.0, unit="usd", per="run")
        варианты = pricing.estimate([ставка], pricing.Need(images=6.0))
        self.assertEqual(
            [(6.0, "6 прогон(ов) × 1 usd (прогон = 1 кадр) = 6.00 usd")],
            [(o.usd, o.formula) for o in варианты],
        )
        # Негативный контроль: один кадр — один прогон, формула прежняя.
        варианты = pricing.estimate([ставка], pricing.Need(images=1.0))
        self.assertEqual(
            [(1.0, "1 прогон(ов) × 1 usd = 1.00 usd")], [(o.usd, o.formula) for o in варианты]
        )

    def test_план_шести_кадров_английский(self) -> None:
        итог = pn.plan(
            "photoreal keyframe images for a storyboard, 6 images, budget $1",
            КАРТИНКИ,
            today=СЕГОДНЯ,
        )
        шаг = итог["steps"][0]
        self.assertEqual("б-text-to-image", шаг["chosen"]["model"])
        # Английский бриф — английские формы во всём ответе (4-й круг, `l10n`).
        self.assertEqual("0.60 usd per step: via example — 6 image(s) × 0.1 usd = 0.60 usd", шаг["chosen"]["price"])
        self.assertEqual(
            ["а-text-to-image:6.00 usd per step: via example — 6 run(s) × 1 usd (run = 1 image) = 6.00 usd"],
            [f"{а['model']}:{а['price']}" for а in шаг["alternatives"]],
        )
        self.assertIn("price: 0.60 usd per step: via example — 6 image(s) × 0.1 usd = 0.60 usd", итог["summary"])

    def test_план_шести_кадров_русский(self) -> None:
        итог = pn.plan(
            "6 ключевых кадров для раскадровки, бюджет 1 доллар", КАРТИНКИ, today=СЕГОДНЯ
        )
        self.assertEqual(
            "0.60 usd за шаг: через example — 6 кадр(ов) × 0.1 usd = 0.60 usd", итог["steps"][0]["chosen"]["price"]
        )
        self.assertIn("цена: 0.60 usd за шаг: через example — 6 кадр(ов) × 0.1 usd = 0.60 usd", итог["summary"])


class Находка6МузыкаДляРолика(unittest.TestCase):
    def test_музыка_для_рекламы_без_генерации_видео(self) -> None:
        self.assertEqual(
            ["музыка"], замкнуто("30 second instrumental background music for an ad, budget $1")
        )
        self.assertEqual(
            ["музыка"], замкнуто("музыка для рекламы 30 секунд, без слов, бюджет 1 доллар")
        )
        self.assertEqual(
            ["озвучка"], замкнуто("voiceover for an ad, 30 seconds English, budget $1")
        )

    def test_и_вопроса_о_снятом_видео_нет(self) -> None:
        self.assertIsNone(вопрос("30 second instrumental background music for an ad, budget $1"))
        self.assertIsNone(вопрос("музыка для рекламы 30 секунд, без слов, бюджет 1 доллар"))

    def test_негативный_контроль_липсинк_для_рекламы_видео_требует(self) -> None:
        # Липсинку нужно видео: исключение для дорожки его не снимает.
        бриф = "English VO for an ad with lipsync, 20 seconds, budget $5"
        self.assertEqual(["озвучка", "генерация_видео", "липсинк"], замкнуто(бриф))
        self.assertEqual(clarify.ОСЬ_ИСХОДНИК, вопрос(бриф))
        # Ролик заказан сам по себе — видео к музыке дописывается, как раньше.
        self.assertEqual(
            ["генерация_видео", "музыка"], замкнуто("30 second promo video with background music")
        )


class Находка7ВопросУжеОтвечен(unittest.TestCase):
    def test_способ_с_нуля_назван_вопроса_нет(self) -> None:
        брифы = (
            "cheapest native 1080p image-to-video with audio, 8 seconds, budget $2",
            "I have a still image. Animate it into an 8 second 1080p clip with native audio",
            "open-weights video model to self-host on RunPod RTX 4090, 5 second clips",
            "8 second 1080p text-to-video with native audio, budget $1 per generation",
            "generate a 10 second ad from scratch",
            "ролик 10 секунд с нуля, бюджет 2 доллара",
            "сгенерировать рекламный ролик 10 секунд",
            "видеомодель с открытыми весами, ролик 5 секунд",
        )
        self.assertEqual({б: None for б in брифы}, {б: вопрос(б) for б in брифы})

    def test_видео_только_догадкой_вопрос_снят_словами_брифа(self) -> None:
        # Видео в плане только из нашей догадки (дописано) — решают слова брифа.
        def спросить(бриф: str) -> str | None:
            в = clarify.спросить(
                бриф,
                ["видео", "видео_с_липсинком", "аудио"],
                [],
                артефакт_видео="видео",
                артефакт_аудио="аудио",
                дописано=["видео"],
            )
            return в.ось if в else None

        self.assertEqual(
            {
                "talking avatar ad from scratch, 20 seconds": None,
                "generated presenter ad, 20 seconds, lipsync": None,
                "рекламный ролик с нуля, 20 секунд, липсинк": None,
                "talking avatar ad, 20 seconds, lipsync": clarify.ОСЬ_ИСХОДНИК,
                "рекламный ролик, не генерируйте видео, липсинк": clarify.ОСЬ_ИСХОДНИК,
            },
            {
                б: спросить(б)
                for б in (
                    "talking avatar ad from scratch, 20 seconds",
                    "generated presenter ad, 20 seconds, lipsync",
                    "рекламный ролик с нуля, 20 секунд, липсинк",
                    "talking avatar ad, 20 seconds, lipsync",
                    "рекламный ролик, не генерируйте видео, липсинк",
                )
            },
        )

    def test_и_операции_выводятся(self) -> None:
        self.assertEqual(
            {
                "cheapest native 1080p image-to-video with audio, 8 seconds": [
                    "генерация_изображения",
                    "оживление",
                ],
                "I have a still image. Animate it into an 8 second clip": ["оживление"],
                "8 second 1080p text-to-video": ["генерация_видео"],
                "open-weights video model to self-host, 5 second clips": ["генерация_видео"],
                "видеомодель с открытыми весами, ролик 5 секунд": ["генерация_видео"],
                "оживи мою картинку, 5 секунд": ["оживление"],
            },
            {
                б: замкнуто(б)
                for б in (
                    "cheapest native 1080p image-to-video with audio, 8 seconds",
                    "I have a still image. Animate it into an 8 second clip",
                    "8 second 1080p text-to-video",
                    "open-weights video model to self-host, 5 second clips",
                    "видеомодель с открытыми весами, ролик 5 секунд",
                    "оживи мою картинку, 5 секунд",
                )
            },
        )

    def test_негативный_контроль_отрицание_и_молчание(self) -> None:
        # Генерацию запретили — это не ответ «снятого нет».
        self.assertTrue(clarify._с_нуля_названо("ролик с нуля"))
        self.assertFalse(clarify._с_нуля_названо("ролик, не генерируйте видео"))
        self.assertFalse(clarify._с_нуля_названо("ad, don't generate anything"))
        # Способ не назван — вопрос задаётся, как раньше.
        self.assertEqual(
            clarify.ОСЬ_ИСХОДНИК, вопрос("lipsync to 30s English voiceover, budget $3")
        )


class Находка8ОдинИТотЖеПерсонаж(unittest.TestCase):
    #: Кадр, правка по референсу, оживление из кадра — маршрут консистентности.
    МАРШРУТ = ["генерация_изображения", "редактирование_изображения", "оживление"]

    def test_консистентность_названа_своими_словами(self) -> None:
        брифы = (
            "40s 9:16 1080x1920 ad with two consistent realistic fighters, budget $15",
            "Рекламный ролик 40 секунд, два одинаковых реалистичных бойца на протяжении всего ролика",
            "same character across shots, 20 second ad",
            "keep the faces consistent across scenes, 20 second ad",
            "один и тот же боец во всех сценах, ролик 20 секунд",
            "ролик 20 секунд с тем же лицом в каждом кадре",
        )
        self.assertEqual({б: self.МАРШРУТ for б in брифы}, {б: замкнуто(б) for б in брифы})

    def test_с_озвучкой_и_липсинком(self) -> None:
        self.assertEqual(
            self.МАРШРУТ[:2] + ["озвучка", "оживление", "липсинк"],
            замкнуто(
                "40s 9:16 1080x1920 ad with two consistent realistic fighters, "
                "English VO with lipsync, budget $15"
            ),
        )
        self.assertEqual(
            self.МАРШРУТ[:2] + ["озвучка", "оживление", "липсинк"],
            замкнуто(
                "Рекламный ролик 40 секунд, 9:16, 1080x1920, два одинаковых реалистичных бойца "
                "на протяжении всего ролика, английская озвучка с липсинком, бюджет 15 долларов"
            ),
        )

    def test_негативный_контроль_не_люди(self) -> None:
        брифы = (
            "consistent lighting across shots, 10 second video",
            "the same model for all clips, 10 second video",
            "одинаковый свет во всех сценах, ролик 10 секунд",
            "лицензия на тот же ролик",
        )
        self.assertEqual(
            {б: False for б in брифы},
            {б: "редактирование_изображения" in [о.name for о in pn.derive(б)] for б in брифы},
        )


#: Речь и музыка под одной операцией озвучки: вид выхода у обеих «аудио».
ЗВУК: tuple[Fact, ...] = (
    факт("к-tts", "architecture", "text-to-speech voice model"),
    факт("к-tts", "price_per_1000_chars_usd", "$0.1 per 1000 characters"),
    факт("л-tts", "architecture", "text-to-speech voice model"),
    факт("л-tts", "price_per_1000_chars_usd", "$0.2 per 1000 characters"),
    факт("м-music-tts", "architecture", "text-to-speech and music generation"),
    факт("м-music-tts", "price_per_1000_chars_usd", "$0.01 per 1000 characters"),
    факт("н-text-to-audio", "architecture", "text-to-speech style text-to-audio"),
)


class Находка14СоседиИЯзык(unittest.TestCase):
    def test_музыка_не_сосед_синтеза_речи(self) -> None:
        for бриф in (
            "TTS voiceover, 30 seconds English, budget $1",
            "озвучка диктором 30 секунд, бюджет 1 доллар",
        ):
            шаг = pn.plan(бриф, ЗВУК, today=СЕГОДНЯ, full=True)["steps"][0]
            self.assertEqual("озвучка", шаг["step"])
            self.assertEqual(
                ["к-tts", "л-tts"],
                [шаг["chosen"]["model"]] + [а["model"] for а in шаг["alternatives"]],
            )
            # Пятый круг: `н-text-to-audio` — работа не установлена реестром, а
            # эндпоинты TTS в базе известны: не кандидат вовсе, а не «чужой».
            self.assertEqual(1, шаг["foreign_count"])
            self.assertEqual(["н-text-to-audio"], шаг["registry"]["unclassified_dropped"])

    def test_чужой_не_занимает_место_соседа(self) -> None:
        # Один свой и один чужой: без отбора чужой встал бы единственным соседом.
        факты = [ф for ф in ЗВУК if ф.model in ("к-tts", "м-music-tts")]
        шаг = pn.plan("TTS voiceover, 30 seconds English", факты, today=СЕГОДНЯ)["steps"][0]
        self.assertEqual(("к-tts", []), (шаг["chosen"]["model"], шаг["alternatives"]))

    def test_чужая_работа_озвучки_по_имени(self) -> None:
        self.assertEqual(
            {"elevenlabs-music-v2.5": True, "ltx-2.3-quality-t2a": True, "eleven_v3": False},
            {
                и: pn.чужая_работа(оп("озвучка"), и, ())
                for и in ("elevenlabs-music-v2.5", "ltx-2.3-quality-t2a", "eleven_v3")
            },
        )

    def test_формы_по_английски(self) -> None:
        случаи = {
            "0.08 usd за шаг: ≈450 знаков × 0.18 usd за 1000_chars": (
                "0.08 usd per step: ≈450 chars × 0.18 usd per 1000 chars"
            ),
            "0.30 usd за шаг: 30 с × 0.6 usd/мин ÷ 60 = 0.30 usd": (
                "0.30 usd per step: 30 s × 0.6 usd/min ÷ 60 = 0.30 usd"
            ),
            "0.06 usd за шаг: 1 кадр(ов) × 3 Мп × 0.02 usd": (
                "0.06 usd per step: 1 image(s) × 3 MP × 0.02 usd"
            ),
            "ffmpeg или монтажная программа (не модель)": "ffmpeg or an editing app (not a model)",
            # С 4-го круга (`studio/l10n.py`) имена шагов переводятся и внутри
            # строки: одна функция языка на весь ответ.
            "видео сводится с отдельными дорожками: музыка": (
                "the video is mixed with separate tracks: music"
            ),
            "о речи на языке брифа (english) у minimax-h3 ничего не записано — проверить "
            "пробным прогоном до заказа": (
                "nothing is recorded about minimax-h3 speaking the brief's language (english) — "
                "test it with a trial run before ordering"
            ),
            "лицензия исключает территории EU, UK — где работает заказчик?": (
                "the licence excludes territories EU, UK — where will you use it?"
            ),
            # Цитата из базы остаётся на языке источника; к русской — глосс.
            "«рот плывёт за 10 с» — при условии: текст в кадре": (
                "«рот плывёт за 10 с» [ru: operator's note in Russian, kept as recorded] "
                "— when: text in frame"
            ),
            "по пути clip.mp4 файла нет": "nothing at clip.mp4",
        }
        self.assertEqual(случаи, {р: pn._форма_по_английски(р) for р in случаи})
        self.assertEqual(
            "the video is mixed with separate tracks: music",
            pn._шаги_по_английски("the video is mixed with separate tracks: музыка"),
        )

    def test_английский_план_без_русских_форм(self) -> None:
        итог = pn.plan("TTS voiceover, 30 seconds English, budget $1", ЗВУК, today=СЕГОДНЯ)
        self.assertIn(
            "price: 0.04 usd per step: via example — ≈450 chars × 0.1 usd per 1000 chars", итог["summary"]
        )
        for русское in ("за шаг", "знаков", "за 1000_chars", "через "):
            self.assertNotIn(русское, итог["summary"])
        # Русский бриф — русские формы, без перевода.
        итог = pn.plan("озвучка диктором 30 секунд, бюджет 1 доллар", ЗВУК, today=СЕГОДНЯ)
        self.assertIn("цена: 0.04 usd за шаг: через example — ≈450 знаков × 0.1 usd за 1000_chars", итог["summary"])


if __name__ == "__main__":
    unittest.main()
