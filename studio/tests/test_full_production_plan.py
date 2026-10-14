"""Планировщик как инженер полного производства ролика (2026-10-14).

Живой прогон пяти брифов показал, что планировщик знал семь операций — все из
мира липсинка — и:

    (1) «рекламный ролик ..., консистентные персонажи, музыка»  -> ни музыки,
        ни консистентности; отказ по строкам о хинди и телугу;
    (2) «ключевые кадры фотореалистичные для MMA ролика»       -> оживление
        несуществующего селфи, ни одной картинки;
    (3) «оживить фото и озвучить по-английски»                  -> голос и
        оживление без липсинка между ними;
    (4) «30s vertical ad ... budget 20»                          -> «ЦЕНА РОЛИКА
        0.67 usd» при двух шагах из трёх без цены;
    (5) «сгенерировать фотореалистичный ключевой кадр, без людей» -> оживление
        и генерация видео.

Здесь сторожится каждая починка. Т2: ожидаемое — литералы. Т4: сети и живой
базы нет — факты собраны здесь. Т1: у каждой новой константы-решения есть
случай, который краснеет при её подмене в обе стороны (см. `scripts/
mutate_planner.py`, раздел 2026-10-14).
"""

from __future__ import annotations

import unittest
from datetime import date

from studio import duration as dur
from studio import planner as pn
from studio.factindex import FactIndex
from studio.selfrag.facts import Fact

СЕГОДНЯ = date(2026, 10, 14)


def факт(model: str, attribute: str, value: str, tier: str = "vendor") -> Fact:
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url=f"https://example.invalid/{model}",
        tier=tier,
        stated_on="2026-10-01",
    )


def имена(операции) -> list[str]:
    return [оп.name for оп in операции]


def замкнуто(бриф: str) -> tuple[list[str], dict[str, str]]:
    операции, дописаны = pn.замкнуть(pn.derive(бриф), pn.inputs_of(бриф), бриф)
    return имена(операции), дописаны


def оп(имя: str) -> pn.Operation:
    return next(о for о in pn.OPERATIONS if о.name == имя)


class ОперацииПолногоПроизводства(unittest.TestCase):
    """(a) и (b): новые операции и подсказки по объекту, а не по подстроке."""

    def test_ключевой_кадр_без_людей_это_только_картинка(self) -> None:
        self.assertEqual(
            ["генерация_изображения"],
            имена(pn.derive("сгенерировать фотореалистичный ключевой кадр, без людей")),
        )

    def test_ключевые_кадры_для_ролика_не_оживляют_селфи(self) -> None:
        self.assertEqual(
            (["генерация_изображения"], {}),
            замкнуто("ключевые кадры фотореалистичные для MMA ролика"),
        )

    def test_объект_генерации_решает_картинка_или_видео(self) -> None:
        self.assertEqual(["генерация_изображения"], имена(pn.derive("сгенерировать картинку кота")))
        self.assertEqual(["генерация_видео"], имена(pn.derive("сгенерируй видео с котом")))
        self.assertEqual(
            ["генерация_изображения"], имена(pn.derive("create an image of a fighter"))
        )
        # Прежнее поведение «сгенерировать с нуля» сохранено.
        self.assertEqual(["генерация_видео"], имена(pn.derive("нужен ролик с нуля, сгенерировать")))

    def test_голый_глагол_генерации_значит_видео(self) -> None:
        self.assertEqual(["генерация_видео"], имена(pn.derive("сгенерировать рекламу кофейни")))

    def test_сгенерировать_фото_не_оживление(self) -> None:
        self.assertEqual(["генерация_изображения"], имена(pn.derive("сгенерировать фото кота")))

    def test_отменённый_глагол_ничего_не_выводит(self) -> None:
        self.assertEqual([], имена(pn.derive("картинку не генерировать")))

    def test_фото_целым_словом_а_не_подстрокой(self) -> None:
        self.assertEqual([], имена(pn.derive("фотореалистичный стиль")))
        self.assertEqual(["оживление"], имена(pn.derive("оживить фотографию бабушки")))
        self.assertEqual([], имена(pn.derive("фотосессия продукта с живым фотографом")))

    def test_портретный_формат_не_снимок(self) -> None:
        self.assertNotIn("оживление", имена(pn.derive("вертикальный портретный ролик, говорящая голова")))

    def test_оживить_и_озвучить_соединяет_липсинк(self) -> None:
        self.assertEqual(
            (
                ["озвучка", "оживление", "липсинк"],
                {"липсинк": "голос и оживлённое лицо в брифе не соединены — губы двигает липсинк"},
            ),
            замкнуто("оживить фото и озвучить по-английски"),
        )

    def test_голос_за_кадром_липсинка_не_требует(self) -> None:
        self.assertEqual(
            (["озвучка", "оживление"], {}),
            замкнуто("оживить фото и озвучить закадровым голосом"),
        )

    def test_консистентные_персонажи_и_музыка_собирают_цепочку(self) -> None:
        self.assertEqual(
            (
                [
                    "генерация_изображения",
                    "редактирование_изображения",
                    "озвучка",
                    "оживление",
                    "музыка",
                    "липсинк",
                ],
                {"генерация_изображения": "изображение", "озвучка": "аудио", "оживление": "видео"},
            ),
            замкнуто(
                "рекламный ролик 9:16 1080p, говорящие персонажи с липсинком, "
                "консистентные персонажи, музыка"
            ),
        )

    def test_оживление_без_снимка_получает_кадр_от_генерации(self) -> None:
        self.assertEqual(
            (["генерация_изображения", "оживление"], {"генерация_изображения": "изображение"}),
            замкнуто("оживить персонажа"),
        )

    def test_аватар_выводит_липсинк_но_не_генерацию(self) -> None:
        self.assertEqual(["липсинк"], имена(pn.derive("нужен аватар")))

    def test_подсказка_говорит_одна(self) -> None:
        self.assertEqual(1, оп("липсинк").cues.count("говорит"))

    def test_апскейл_без_видео_это_апскейл_кадра(self) -> None:
        self.assertEqual(["апскейл_изображения"], имена(pn.derive("апскейл фото до 4k")))
        self.assertIn("апскейл", имена(pn.derive("сделай липсинк и апскейл")))

    def test_подобрать_музыку_не_генерация(self) -> None:
        self.assertEqual([], имена(pn.derive("Подобрать музыку без слов под готовое видео")))
        self.assertEqual(["музыка"], имена(pn.derive("нужна музыка для рекламы")))

    def test_раскадровка_текстом_не_картинка(self) -> None:
        self.assertEqual([], имена(pn.derive("Написать сценарий и раскадровку, снимать будем сами")))


class КадрПринесён(unittest.TestCase):
    """(c): селфи больше не существует «всегда» — его приносят."""

    def test_принесённое_фото_вход_плана(self) -> None:
        self.assertIn("изображение", pn.inputs_of("оживить фото клиента"))
        self.assertIn("изображение", pn.inputs_of("animate this photo of my dad"))

    def test_отсутствие_и_генерация_не_приносят(self) -> None:
        self.assertNotIn("изображение", pn.inputs_of("у меня нет ни видео ни фото, всё с нуля"))
        self.assertNotIn("изображение", pn.inputs_of("сгенерировать фото кота"))
        self.assertNotIn("изображение", pn.inputs_of("фотореалистичный ключевой кадр"))

    def test_селфи_ушло_из_всегда_доступного(self) -> None:
        from studio import pipeline as pl

        self.assertEqual(frozenset({"бриф", "референс"}), pl.AMBIENT_ARTEFACTS)
        self.assertEqual(("изображение",), оп("оживление").requires)


# --------------------------------------------------------------------------
# (d) ПРОФИЛЬ, (e) ПОРЯДОК, (f) ОДНА МОДЕЛЬ — ОДИН КАНДИДАТ
# --------------------------------------------------------------------------

#: Генератор видео, у которого НЕТ слова text-to-video: только пределы.
ПРОФИЛЬНЫЙ = (
    факт("acme-video-9", "max_seconds", "8"),
    факт("acme-video-9", "prompt_skeleton", "subject, action, scene"),
    факт("acme-video-9", "summary_line", "8-second videos at 1080p with native audio"),
)

#: Липсинк с пределом длительности, но без промпта: генератором не числится.
НЕ_ГЕНЕРАТОР = (факт("acme-mouth", "max_seconds", "60"),)


class ПрофильМодели(unittest.TestCase):
    def test_генератор_находится_без_якорного_слова(self) -> None:
        найдено = pn.profile_hits(оп("генерация_видео"), {"acmevideo9": list(ПРОФИЛЬНЫЙ)})
        self.assertEqual(["acmevideo9"], list(найдено))
        self.assertEqual("acme-video-9", найдено["acmevideo9"][0])

    def test_одной_длительности_мало(self) -> None:
        self.assertEqual({}, pn.profile_hits(оп("генерация_видео"), {"acmemouth": list(НЕ_ГЕНЕРАТОР)}))

    def test_имя_эндпоинта_называет_работу(self) -> None:
        свои = [факт("acme-image-to-video-pro", "license", "apache-2.0")]
        найдено = pn.profile_hits(оп("оживление"), {"x": свои})
        self.assertEqual("имя эндпоинта (image-to-video)", найдено["x"][2])

    def test_кандидат_по_профилю_доходит_до_плана(self) -> None:
        кандидаты = pn.candidates_for(оп("генерация_видео"), FactIndex(facts=list(ПРОФИЛЬНЫЙ)))
        self.assertEqual(["acme-video-9"], [c.model for c in кандидаты])


def кандидат(**поля) -> pn.Candidate:
    база = dict(model="м", evidence=(), applicability=0, capability=0, unresolved=0, price="")
    база.update(поля)
    return pn.Candidate(**база)


class ПорядокПоДоказательству(unittest.TestCase):
    """(e): подтверждённая схемой ось — довод ПОСЛЕ применимости, а не приговор."""

    def test_измеренный_обгоняет_схемный(self) -> None:
        схемный = кандидат(
            model="схемный",
            ban_state=pn.BAN_ALLOWED,
            out_state=pn.OUT_YES,
            capability=4,
        )
        измеренный = кандидат(model="измеренный", applicability=4, capability=1)
        self.assertEqual(
            ["измеренный", "схемный"],
            [c.model for c in sorted([схемный, измеренный], key=pn.by_evidence)],
        )

    def test_стена_по_прежнему_старше_всего(self) -> None:
        запрещён = кандидат(model="запрещён", applicability=9, ban_state=pn.BAN_FORBIDS)
        молчит = кандидат(model="молчит")
        self.assertEqual(
            ["молчит", "запрещён"],
            [c.model for c in sorted([запрещён, молчит], key=pn.by_evidence)],
        )

    def test_лицензия_запрещает_значит_стена(self) -> None:
        некоммерческая = кандидат(model="nc", applicability=9, licence_blocked=True)
        молчит = кандидат(model="молчит")
        self.assertEqual("молчит", sorted([некоммерческая, молчит], key=pn.by_evidence)[0].model)

    def test_чужая_работа_уходит_вниз_даже_измеренной(self) -> None:
        аватар = кандидат(model="аватар", applicability=5, foreign=True)
        генератор = кандидат(model="генератор")
        self.assertEqual("генератор", sorted([аватар, генератор], key=pn.by_evidence)[0].model)

    def test_незаписанная_длительность_не_стена(self) -> None:
        влезает = кандидат(model="влезает", dur_state=dur.DUR_IN)
        измерен = кандидат(model="измерен", applicability=3, dur_state=dur.DUR_ABSENT)
        self.assertEqual("измерен", sorted([влезает, измерен], key=pn.by_evidence)[0].model)

    def test_незаписанный_предел_кадра_не_старше_применимости(self) -> None:
        принимает = кандидат(model="принимает", fit_state=pn.FIT_IN)
        измерен = кандидат(model="измерен", applicability=3, fit_state=pn.FIT_ABSENT)
        self.assertEqual("измерен", sorted([принимает, измерен], key=pn.by_evidence)[0].model)
        отвергнут = кандидат(model="отвергнут", applicability=3, fit_state=pn.FIT_OVER)
        self.assertEqual("принимает", sorted([принимает, отвергнут], key=pn.by_evidence)[0].model)

    def test_длиннее_предела_стена_только_вне_клипов(self) -> None:
        over_wall = кандидат(model="стена", applicability=3, dur_state=dur.DUR_OVER)
        over_clip = кандидат(model="клипы", applicability=3, dur_state=dur.DUR_OVER, dur_wall=False)
        молчит = кандидат(model="молчит")
        self.assertEqual("молчит", sorted([over_wall, молчит], key=pn.by_evidence)[0].model)
        self.assertEqual("клипы", sorted([over_clip, молчит], key=pn.by_evidence)[0].model)

    def test_генерация_клипами_не_упирается_в_предел(self) -> None:
        ролик = dur.Запрос(600.0, "10 минут")
        индекс = FactIndex(facts=list(ПРОФИЛЬНЫЙ))
        генератор = pn.candidates_for(оп("генерация_видео"), индекс, wanted=ролик)[0]
        self.assertEqual((dur.DUR_OVER, False), (генератор.dur_state, генератор.dur_wall))
        липсинк = pn.candidates_for(
            оп("липсинк"),
            FactIndex(facts=[факт("acme-lipsync", "max_seconds", "60"), факт("acme-lipsync", "architecture", "lipsync")]),
            wanted=ролик,
        )[0]
        self.assertEqual((dur.DUR_OVER, True), (липсинк.dur_state, липсинк.dur_wall))

    def test_константы_ключа(self) -> None:
        self.assertEqual(2, pn.STRICT_BLOCK)
        self.assertEqual(5, pn.CONSTRAINT_KEYS)
        self.assertEqual("делает ли модель эту работу, а не соседнюю", pn.KEY_FIELDS[1])

    def test_аватар_на_генерации_видео_чужой(self) -> None:
        свои = [факт("acme-avatars-text-to-video", "requires_inputs", "текст", "portal")]
        self.assertTrue(pn.чужая_работа(оп("генерация_видео"), "acme-avatars-text-to-video", свои))
        self.assertFalse(pn.чужая_работа(оп("генерация_видео"), "acme-text-to-video", []))

    def test_ведомая_звуком_модель_на_оживлении_чужая(self) -> None:
        свои = [факт("acme-human", "requires_inputs", "аудио, изображение", "portal")]
        self.assertTrue(pn.чужая_работа(оп("оживление"), "acme-human", свои))


class ОднаМодельОдинКандидат(unittest.TestCase):
    """(f): ключ кандидата — свёрнутое имя; применимость не считается дважды."""

    def test_два_написания_одна_модель(self) -> None:
        факты = [
            факт("sync-lipsync-2", "observed_behaviour", "lipsync: губы держат синхрон", "operator"),
            факт("sync-lipsync-v2", "observed_behaviour", "lipsync: зубы не плывут", "operator"),
        ]
        кандидаты = pn.candidates_for(оп("липсинк"), FactIndex(facts=факты))
        self.assertEqual(1, len(кандидаты))
        self.assertEqual(2, кандидаты[0].applicability)


class СчётчикЦены(unittest.TestCase):
    """(g): «вытеснен ценой» — только когда потолок назван и разошлись по цене."""

    def _пара(self):
        дешёвый = кандидат(model="дешёвый", price_state=pn.PRICE_IN)
        проверенный = кандидат(model="проверенный", applicability=3, price_state=pn.PRICE_ABSENT)
        return дешёвый, проверенный

    def test_без_потолка_не_ценой(self) -> None:
        дешёвый, проверенный = self._пара()
        нет = pn.Budget(None, "", (), "could not measure", "не назван")
        self.assertFalse(pn.вытеснен_ценой(дешёвый, [дешёвый, проверенный], нет))

    def test_с_потолком_ценой(self) -> None:
        дешёвый, проверенный = self._пара()
        есть = pn.Budget(1.0, "usd", ("run",), "pass", "потолок 1")
        self.assertTrue(pn.вытеснен_ценой(дешёвый, [дешёвый, проверенный], есть))

    def test_в_ноте_оба_счётчика(self) -> None:
        итог = pn.plan("сделай липсинк", facts=[факт("x-lipsync", "license", "apache-2.0")], today=СЕГОДНЯ)
        self.assertIn("проверенный не выбран 0", итог["note"])
        self.assertIn("проверенный вытеснен ценой 0", итог["note"])


class ЦенаРолика(unittest.TestCase):
    """(h): «ЦЕНА РОЛИКА» — только когда у каждого шага есть цена."""

    def test_неполная_цена_это_нижняя_граница(self) -> None:
        цена = {
            "outcome": "не смогли",
            "lower_bound": {"usd за second": 0.1},
            "note": "не менее 0.1 usd за second",
            "steps_without_price": ["липсинк"],
        }
        итог = pn.в_ролик(цена, 30.0, 20.0)
        self.assertIn("НИЖНЯЯ ГРАНИЦА РОЛИКА: 30 с × 0.1 usd за second = 3.00 usd", итог["note"])
        self.assertNotIn("ЦЕНА РОЛИКА:", итог["note"])
        self.assertIn("без цены шаги липсинк", итог["note"])
        self.assertEqual("не смогли", итог["outcome"])

    def test_нижняя_граница_выше_потолка_это_не_годно(self) -> None:
        цена = {
            "outcome": "не смогли",
            "lower_bound": {"usd за second": 1.0},
            "note": "",
            "steps_without_price": ["липсинк"],
        }
        self.assertEqual("не годно", pn.в_ролик(цена, 30.0, 20.0)["outcome"])

    def test_полная_цена_называется_ценой(self) -> None:
        цена = {"outcome": "годно", "lower_bound": {"usd за second": 0.1}, "note": ""}
        итог = pn.в_ролик(цена, 30.0, 20.0)
        self.assertIn("ЦЕНА РОЛИКА: 30 с × 0.1 usd за second = 3.00 usd", итог["note"])
        self.assertEqual("годно", итог["outcome"])

    def test_минута_переводится_в_секунды(self) -> None:
        цена = {"outcome": "годно", "lower_bound": {"usd за minute": 0.6}, "note": ""}
        self.assertEqual({"usd": 0.3}, pn.в_ролик(цена, 30.0, None)["за_ролик"])

    def test_нулевой_потолок_превышен_любой_ценой(self) -> None:
        цена = {"outcome": "годно", "lower_bound": {"usd за 1000_chars": 0.025}, "note": ""}
        итог = pn.в_ролик(цена, None, 0.0)
        self.assertEqual("не годно", итог["outcome"])
        self.assertIn("ПОТОЛОК 0: работа столько не стоит", итог["note"])

    def test_длительность_из_брифа(self) -> None:
        self.assertEqual(30.0, dur.просят("30s vertical ad").секунды)
        self.assertEqual(40.0, dur.просят("ролик 40 секунд").секунды)


class ЯзыкБрифа(unittest.TestCase):
    """(i): строка о хинди не судит английскую озвучку."""

    ФАКТЫ = (
        факт("acme-tts", "accepts_inputs", "текст", "portal"),
        факт("acme-tts", "architecture", "text-to-speech, tts", "vendor"),
        факт("acme-tts", "degrades_when", "на хинди и телугу срыв ретрофлексов 40%", "paper"),
    )

    def test_языки_брифа(self) -> None:
        self.assertEqual(("english",), pn.языки_брифа("оживить фото и озвучить по-английски"))
        self.assertEqual(("russian",), pn.языки_брифа("сделай озвучку"))
        self.assertEqual(("english",), pn.языки_брифа("make a voiceover"))

    def test_чужой_язык_не_считается_доводом(self) -> None:
        индекс = FactIndex(facts=list(self.ФАКТЫ))
        без_языка = pn.candidates_for(оп("озвучка"), индекс)[0]
        английский = pn.candidates_for(оп("озвучка"), индекс, languages=("english",))[0]
        хинди = pn.candidates_for(оп("озвучка"), индекс, languages=("hindi",))[0]
        self.assertEqual((1, 1), (без_языка.applicability, без_языка.against))
        self.assertEqual((0, 0), (английский.applicability, английский.against))
        self.assertEqual((1, 1), (хинди.applicability, хинди.against))


class АпскейлСборкаВариант(unittest.TestCase):
    """Шаги, которые инженер добавляет к плану сам."""

    def test_кадр_из_брифа(self) -> None:
        self.assertEqual((1080, 1920), pn.кадр_из_брифа("рекламный ролик 9:16 1080p"))
        self.assertEqual((1920, 1080), pn.кадр_из_брифа("ролик 1080p"))
        self.assertEqual((3840, 2160), pn.кадр_из_брифа("ролик 4к"))
        self.assertIsNone(pn.кадр_из_брифа("ролик без разрешения"))

    def test_апскейл_когда_предел_не_подтверждён(self) -> None:
        выбор = [(оп("липсинк"), кандидат(model="acme-lip"))]
        факты = [факт("acme-lip", "max_resolution", "720p")]
        self.assertIn("acme-lip", pn.нужен_апскейл(выбор, (1080, 1920), факты))
        большой = [факт("acme-lip", "max_resolution", "4K")]
        self.assertEqual("", pn.нужен_апскейл(выбор, (1080, 1920), большой))
        self.assertEqual("", pn.нужен_апскейл(выбор, None, факты))

    def test_сборка_когда_есть_дорожки_или_клипы(self) -> None:
        нет = dur.Запрос(None, "не спрашивали")
        видео_и_музыка = [(оп("генерация_видео"), кандидат()), (оп("музыка"), кандидат())]
        self.assertEqual(
            ["видео сводится с отдельными дорожками: музыка"],
            pn.нужна_сборка(видео_и_музыка, нет)["why"],
        )
        self.assertIsNone(pn.нужна_сборка([(оп("генерация_изображения"), кандидат())], нет))
        self.assertIsNone(pn.нужна_сборка([(оп("генерация_видео"), кандидат())], нет))

    def test_вариант_с_нативным_звуком_строится_из_фактов(self) -> None:
        факты = list(ПРОФИЛЬНЫЙ) + [
            факт("acme-lipsync", "observed_behaviour", "lipsync держит губы", "operator"),
            факт("acme-tts", "architecture", "text-to-speech, tts", "vendor"),
        ]
        итог = pn.plan("нужен говорящий персонаж", facts=факты, today=СЕГОДНЯ)
        вариант = итог["native_audio_variant"]
        self.assertEqual("acme-video-9", вариант["chosen"]["model"])
        self.assertEqual(["озвучка", "генерация_видео", "липсинк"], вариант["replaces"])

    def test_видеомодель_со_звуком_раньше_аватара(self) -> None:
        факты = list(ПРОФИЛЬНЫЙ) + [
            факт("acme-lipsync", "observed_behaviour", "lipsync держит губы", "operator"),
            факт("acme-avatar-studio", "requires_inputs", "текст", "portal"),
            факт("acme-avatar-studio", "produces_outputs", "видео", "portal"),
            факт("acme-avatar-studio", "positioning", "talking avatar video from a script"),
            факт("acme-avatar-studio", "observed_behaviour", "аватар держит лицо весь ролик", "operator"),
        ]
        вариант = pn.plan("нужен говорящий персонаж", facts=факты, today=СЕГОДНЯ)["native_audio_variant"]
        self.assertEqual("acme-video-9", вариант["chosen"]["model"])
        self.assertEqual(["acme-avatar-studio"], [a["model"] for a in вариант["alternatives"]])

    def test_нет_фактов_о_звуке_нет_кандидата(self) -> None:
        факты = [
            факт("acme-lipsync", "observed_behaviour", "lipsync держит губы", "operator"),
            факт("acme-t2v", "observed_behaviour", "text-to-video: кадр держится", "operator"),
        ]
        вариант = pn.plan("нужен говорящий персонаж", facts=факты, today=СЕГОДНЯ)["native_audio_variant"]
        self.assertIsNone(вариант["chosen"])
        self.assertIn("нет ни одной видеомодели с записью о нативном звуке", вариант["note"])


class КраткийПлан(unittest.TestCase):
    """(j): сверху ответа — план словами человека, подробности ниже."""

    def test_сводка_первая_и_по_делу(self) -> None:
        факты = list(ПРОФИЛЬНЫЙ) + [
            факт("acme-lipsync", "observed_behaviour", "lipsync держит губы", "operator"),
        ]
        итог = pn.plan("нужен говорящий персонаж, музыка", facts=факты, today=СЕГОДНЯ)
        self.assertEqual("summary", next(iter(итог)))
        сводка = итог["summary"]
        self.assertTrue(сводка.startswith("КРАТКО: шагов "))
        self.assertIn("липсинк -> acme-lipsync", сводка)
        self.assertIn("ЦЕНА: ", сводка)
        self.assertIn("ВАРИАНТ Б", сводка)
        self.assertNotIn("валидатор-2", сводка)
        self.assertTrue(pn.render(итог).startswith("КРАТКО: шагов "))

    def test_английский_бриф_английская_сводка(self) -> None:
        итог = pn.plan("make a talking head video", facts=list(ПРОФИЛЬНЫЙ), today=СЕГОДНЯ)
        self.assertTrue(итог["summary"].startswith("PLAN IN SHORT: "))
        self.assertIn("PRICE: ", итог["summary"])
        self.assertIn("added by plan: no step makes audio and you did not bring it", итог["summary"])
        self.assertNotIn("применимость", итог["summary"])

    def test_кадры_для_ролика_не_спрашивают_про_видео(self) -> None:
        self.assertIsNone(pn.plan("ключевые кадры фотореалистичные для MMA ролика", facts=[], today=СЕГОДНЯ)["question"])
        вопрос = pn.plan("рекламный ролик с ключевыми кадрами", facts=[], today=СЕГОДНЯ)["question"]
        self.assertEqual("есть_ли_исходное_видео", вопрос["axis"])


if __name__ == "__main__":
    unittest.main()
