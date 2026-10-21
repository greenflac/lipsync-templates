"""Девятый круг: заметки производства и маршруты, которых не хватало экспертному набору.

Экспертный набор (`scripts/eval_plans.py`) измерил: заметки — самое слабое
измерение (22 из 44 не сказаны), и семь маршрутов разложены не так, как их
раскладывает инженер (альфа-канал, клип со словами, аудиограмма, серия с одним
персонажем, раскраска снимков, 3D-модель, бюджет 0). Здесь — по правилу на
класс работы или условие; брифы ПЕРЕФРАЗИРОВАНЫ, а не взяты из набора.

Т2: ожидания — литералы. Т4: сети нет; синтетическая база, кроме двух
проверок хостинга, которые читают живую базу с диска. Т1: константы-решения
мутируются в `scripts/mutate_recipes.py`.
"""

from __future__ import annotations

import unittest
from datetime import date

import studio.planner as pn
from studio import brief_spec as bs
from studio import endpoints as ep
from studio import l10n
from studio import recipes as rc
from studio.recipes import table as rt
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


БАЗА: tuple[Fact, ...] = (
    факт("x-t2i", "architecture", "text-to-image model"),
    факт("x-t2i", "price_per_image_usd", "$0.05 per image"),
    факт("x-t2v", "architecture", "text-to-video model"),
    факт("x-t2v", "price_per_second_usd", "$0.10 per second"),
    факт("x-i2v", "architecture", "image-to-video model"),
    факт("x-i2v", "price_per_second_usd", "$0.10 per second"),
    факт("x-asr", "architecture", "speech-to-text transcription model with timestamps"),
    факт("x-asr", "price_per_minute_usd", "$0.01 per minute"),
    факт("x-music", "architecture", "text-to-music model"),
    факт("x-music", "price_per_second_usd", "$0.01 per second"),
)


def план(spec: dict, бриф: str = "spec-only call") -> dict:
    return pn.plan(бриф, facts=list(БАЗА), today=СЕГОДНЯ, full=True, spec=spec, spec_only=True)


def spec_(raw: dict) -> bs.Spec:
    spec, ошибки = bs.parse_spec(raw)
    assert not ошибки, ошибки
    return spec


def маршрут(raw: dict, бриф: str = "") -> rc.Applied:
    spec = spec_(raw)
    return rc.rewrite(spec, bs.route(spec), бриф)


def заметки(raw: dict, шаги: tuple[str, ...], бриф: str = "") -> list[str]:
    """Заметки ДЕВЯТОГО И ДЕСЯТОГО кругов (`table.NOTES`).

    Одиннадцатый круг добавил отдельный слой — чек-лист инженера
    (`recipes/checklist.py`, свои тесты в `test_checklist_r11.py`); здесь
    сторожатся правила своего круга, и строки чек-листа в сравнение не идут.
    """
    return [и for и, _ in rc.note_ids(spec_(raw), шаги, text=бриф) if и in rt.NOTES]


def notes_r9(*args: object, **kwargs: object) -> list[dict]:
    """`rc.notes` без строк чек-листа одиннадцатого круга (см. `заметки`)."""
    return [з for з in rc.notes(*args, **kwargs) if з["id"] in rt.NOTES]  # type: ignore[arg-type]


def свои_заметки(итог: dict) -> list[str]:
    return [з["id"] for з in итог["production_notes"] if з["id"] in rt.NOTES]


def свой(kind: str, сек: float | None = None, **ещё: object) -> dict:
    return {"kind": kind, "owned": True, **({"duration_s": сек} if сек else {}), **ещё}


# --- таблица -----------------------------------------------------------------------


class Таблица(unittest.TestCase):
    def test_заметки_на_двух_языках_с_тегом(self) -> None:
        for н in rt.NOTES_LIST:
            self.assertTrue(н.en and н.ru, н.id)
            self.assertIn(н.tag, (rt.TAG_ENGINEERING, rt.TAG_REGULATION), н.id)
            self.assertEqual(н.tag == rt.TAG_REGULATION, bool(н.sources), н.id)

    def test_русская_заметка_без_английских_оборотов(self) -> None:
        поля = {
            "seconds": "600", "aspect": "2.39:1", "native": "16:9", "speakers": "2", "tags": "ar-EG",
            # Десятый круг: поля нот печати и частоты кадров.
            "dpi": "300", "size": " (A2)", "frame": "4961x7016 px", "fps": "240",
        }
        for н in rt.NOTES_LIST:
            строка = {"says": н.ru.format(**поля)}
            self.assertEqual([], l10n.leaks(строка, "ru"), н.id)
            self.assertEqual([], l10n.leaks({"says": н.en.format(**поля)}, "en"), н.id)

    def test_акт_ес_ссылается_на_регламент(self) -> None:
        self.assertEqual(
            "https://eur-lex.europa.eu/eli/reg/2024/1689/oj", rt.NOTES["ai_act_label"].sources[0].url
        )


# --- заметки: по правилу на класс работы или условие --------------------------------


class Заметки(unittest.TestCase):
    def test_музыка_лицензия(self) -> None:
        raw = {"task": "generate", "inputs": [], "outputs": ["music"], "duration_s": 90}
        self.assertEqual(["music_licence"], заметки(raw, ("музыка",)))
        (строка,) = notes_r9(spec_(raw), ("музыка",), True)
        self.assertIn("licence terms of the chosen service decide commercial use", строка["says"])
        self.assertIn("royalty-free", строка["says"])

    def test_открытые_веса_лицензия(self) -> None:
        raw = {"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 5, "open_weights": True}
        self.assertEqual(["weights_licence"], заметки(raw, ("генерация_видео",)))
        raw = {"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 5}
        self.assertEqual([], заметки(raw, ("генерация_видео",)))

    def test_чужая_песня_права(self) -> None:
        чужая = {"kind": "audio", "owned": False, "duration_s": 12}
        raw = {"task": "sing-photo", "inputs": [свой("image"), чужая], "outputs": ["video"], "duration_s": 12}
        self.assertEqual(["song_rights"], заметки(raw, ("говорящий_аватар",)))
        raw["inputs"] = [свой("image"), свой("audio", 12)]
        self.assertEqual([], заметки(raw, ("говорящий_аватар",)))

    def test_длинный_аватар_отрезками(self) -> None:
        raw = {"task": "avatar", "inputs": [свой("text")], "outputs": ["video", "speech"], "languages": ["de"]}
        self.assertEqual(
            ["long_form_segmented"], заметки({**raw, "duration_s": 300}, ("озвучка", "говорящий_аватар"))
        )
        self.assertEqual([], заметки({**raw, "duration_s": 120}, ("озвучка", "говорящий_аватар")))
        (строка,) = notes_r9(spec_({**raw, "duration_s": 900}), ("говорящий_аватар",), True)
        self.assertTrue(строка["says"].startswith("long form (900 s): a talking-avatar or lip-sync run"))

    def test_длинный_ролик_без_речи_не_отрезками(self) -> None:
        raw = {"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 600}
        self.assertEqual([], заметки(raw, ("генерация_видео",)))

    def test_удаление_объекта_маска(self) -> None:
        raw = {"task": "video-edit", "edit": ["remove-object"], "inputs": [свой("video", 8)], "outputs": ["video"]}
        self.assertEqual(["mask_composite"], заметки(raw, ("правка_видео",)))
        raw["edit"] = ["replace-sky"]
        self.assertEqual(["mask_composite"], заметки(raw, ("правка_видео",)))
        raw["edit"] = ["restyle"]
        self.assertEqual([], заметки(raw, ("правка_видео",)))

    def test_рефрейм_кадрирование(self) -> None:
        raw = {"task": "video-edit", "edit": ["reframe"], "inputs": [свой("video", 30)], "outputs": ["video"], "aspect": "4:5"}
        self.assertEqual(["crop_track"], заметки(raw, ("правка_видео",)))
        (строка,) = notes_r9(spec_(raw), ("правка_видео",), True)
        self.assertTrue(строка["says"].startswith("reframing to 4:5 is a crop that follows the subject"))

    def test_нестандартный_кадр_кадрируется(self) -> None:
        raw = {"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 8, "aspect": "2.39:1"}
        self.assertEqual(["aspect_crop"], заметки(raw, ("генерация_видео",)))
        (строка,) = notes_r9(spec_(raw), ("генерация_видео",), True)
        self.assertTrue(строка["says"].startswith("2.39:1 is not an aspect generators render natively: it is generated at 16:9"))
        self.assertEqual(["aspect_crop"], заметки({**raw, "aspect": "1.85:1"}, ("генерация_видео",)))
        for родной in ("16:9", "1.78:1", "21:9", "9:16", "4:5"):
            self.assertEqual([], заметки({**raw, "aspect": родной}, ("генерация_видео",)), родной)

    def test_узкий_кадр_от_вертикали(self) -> None:
        raw = {"task": "generate", "inputs": [], "outputs": ["image"], "shots": 1, "aspect": "1:3"}
        (строка,) = notes_r9(spec_(raw), ("генерация_изображения",), True)
        self.assertIn("generated at 9:16", строка["says"])

    def test_ес_маркировка(self) -> None:
        raw = {"task": "generate", "inputs": [], "outputs": ["image"], "shots": 1, "jurisdiction": "Germany"}
        self.assertEqual(["ai_act_label"], заметки(raw, ("генерация_изображения",)))
        raw["jurisdiction"] = "US"
        self.assertEqual([], заметки(raw, ("генерация_изображения",)))

    def test_два_говорящих_по_очереди(self) -> None:
        люди = [
            {"name": "host", "real": True, "public_figure": False, "consent": "stated", "claim": "none"},
            {"name": "guest", "real": True, "public_figure": False, "consent": "stated", "claim": "none"},
        ]
        raw = {"task": "lipsync", "inputs": [свой("video", 30), свой("audio", 30)], "outputs": ["video"], "people": люди}
        self.assertEqual(["multi_speaker"], заметки(raw, ("липсинк",)))
        (строка,) = notes_r9(spec_(raw), ("липсинк",), True)
        self.assertTrue(строка["says"].startswith("2 speakers in the shot: the audio is diarized"))
        self.assertIn("each speaker's face", строка["says"])
        raw["people"] = люди[:1]
        self.assertEqual([], заметки(raw, ("липсинк",)))

    def test_точный_текст_накладывается(self) -> None:
        raw = {"task": "edit", "inputs": [свой("image")], "outputs": ["image"], "shots": 1, "conditions": ["headline readable"]}
        self.assertEqual(["logo_text_composited"], заметки(raw, ("редактирование_изображения",)))
        raw["conditions"] = ["hands"]
        self.assertEqual([], заметки(raw, ("редактирование_изображения",)))

    def test_логотип_уже_в_рецепте_не_повторяется(self) -> None:
        raw = {"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 6, "conditions": ["logo legible"]}
        применено = маршрут(raw)
        self.assertIn("logo_overlay", применено.priors)
        self.assertEqual([], [и for и, _ in rc.note_ids(spec_(raw), ("генерация_видео",), applied=применено) if и in rt.NOTES])

    def test_один_снимок_обратная_сторона(self) -> None:
        raw = {"task": "turntable", "inputs": [свой("image")], "outputs": ["video"], "duration_s": 4}
        self.assertEqual(["unseen_side"], заметки(raw, ("оборот_360",)))
        raw["inputs"] = [свой("image", count=4)]
        self.assertEqual([], заметки(raw, ("оборот_360",)))

    def test_нарезка_субтитры_вжигаются(self) -> None:
        raw = {"task": "cut-to-shorts", "inputs": [свой("video", 1800)], "outputs": ["video", "text"], "shots": 3, "per_shot_s": 30, "languages": ["fr"]}
        self.assertEqual(["captions_burned"], заметки(raw, ("расшифровка",)))
        raw["outputs"] = ["video"]
        self.assertEqual([], заметки(raw, ("расшифровка",)))

    def test_региональный_вариант_языка(self) -> None:
        raw = {"task": "generate", "inputs": [свой("text")], "outputs": ["speech"], "duration_s": 60, "languages": ["pt-BR", "de"]}
        self.assertEqual(["regional_variety"], заметки(raw, ("озвучка",)))
        (строка,) = notes_r9(spec_(raw), ("озвучка",), True)
        self.assertTrue(строка["says"].startswith("pt-BR: a regional variety (dialect, accent) is not the language itself"))
        raw["languages"] = ["pt", "de"]
        self.assertEqual([], заметки(raw, ("озвучка",)))

    def test_по_русски(self) -> None:
        raw = {"task": "generate", "inputs": [], "outputs": ["music"], "duration_s": 60}
        (строка,) = [з for з in notes_r9(spec_(raw), ("музыка",), False) if з["id"] in rt.NOTES]
        self.assertEqual("инженерное допущение", строка["tag"])
        self.assertIn("условия лицензии", строка["says"])


# --- маршруты ----------------------------------------------------------------------


class Маршруты(unittest.TestCase):
    def test_прозрачный_фон_снимается_после_генерации(self) -> None:
        raw = {"task": "animate", "inputs": [свой("image")], "outputs": ["video"], "duration_s": 3, "conditions": ["transparent background"]}
        применено = маршрут(raw)
        self.assertEqual(("оживление", "удаление_фона_видео"), применено.route.шаги)
        self.assertEqual(("alpha_matte",), применено.priors)
        self.assertEqual(
            ["alpha_delivery"],
            [и for и, _ in rc.note_ids(spec_(raw), применено.route.шаги, applied=применено) if и in rt.NOTES],
        )

    def test_прозрачный_фон_словами_брифа(self) -> None:
        raw = {"task": "animate", "inputs": [свой("image")], "outputs": ["video"], "duration_s": 3}
        self.assertEqual(("оживление",), маршрут(raw).route.шаги)
        self.assertEqual(
            ("оживление", "удаление_фона_видео"),
            маршрут(raw, "our logo bouncing, delivered as a WebM file for the site").route.шаги,
        )

    def test_прозрачный_фон_выключается(self) -> None:
        raw = {"task": "animate", "inputs": [свой("image")], "outputs": ["video"], "duration_s": 3,
               "conditions": ["transparent"], "priors": {"alpha_matte": False}}
        self.assertEqual(("оживление",), маршрут(raw).route.шаги)

    def test_аудиограмма_без_оживления(self) -> None:
        raw = {"task": "music-visualiser", "inputs": [свой("audio", 30), свой("image")], "outputs": ["video"], "languages": ["en"]}
        применено = маршрут(raw)
        self.assertEqual(("расшифровка",), применено.route.шаги)
        self.assertIn("audiogram_static_art", применено.priors)
        без_языка = маршрут({**raw, "languages": []})
        self.assertEqual((), без_языка.route.шаги)
        оживить = маршрут({**raw, "conditions": ["animate the cover art"]})
        self.assertEqual(("оживление",), оживить.route.шаги)

    def test_аудиограмма_план_монтажом(self) -> None:
        итог = план({"task": "music-visualiser", "inputs": [свой("audio", 30), свой("image")], "outputs": ["video"]})
        self.assertEqual(("только_монтаж", []), (итог["reason"], итог["steps"]))
        self.assertEqual(["waveform_layer"], свои_заметки(итог))

    def test_клип_со_словами_расшифровка_для_выравнивания(self) -> None:
        raw = {"task": "music-visualiser", "inputs": [свой("audio", 200), свой("text")], "outputs": ["video"], "languages": ["es"]}
        применено = маршрут(raw)
        self.assertEqual("расшифровка", применено.route.шаги[0])
        self.assertIn("генерация_видео", применено.route.шаги)
        self.assertIn("lyrics_alignment", применено.priors)

    def test_один_персонаж_в_двух_шотах(self) -> None:
        итог = план({"task": "generate", "inputs": [], "outputs": ["video"], "shots": 3, "per_shot_s": 5, "characters": 1})
        # Один референс (shots не печатается — один), оживлений три.
        self.assertEqual(
            [("генерация_изображения", None), ("оживление", 3)], [(ш["step"], ш["shots"]) for ш in итог["steps"]]
        )

    def test_один_шот_без_референса(self) -> None:
        итог = план({"task": "generate", "inputs": [], "outputs": ["video"], "shots": 1, "per_shot_s": 5, "characters": 1})
        self.assertEqual(["генерация_видео"], [ш["step"] for ш in итог["steps"]])

    def test_раскраска_снимков(self) -> None:
        м = bs.route(spec_({"task": "colorize", "inputs": [свой("image", count=30)], "outputs": ["image"], "shots": 30}))
        self.assertEqual((("раскраска_изображения",), None), (м.шаги, м.нехватка))
        м = bs.route(spec_({"task": "colorize", "inputs": [свой("video", 60)], "outputs": ["video"]}))
        self.assertEqual(("раскраска",), м.шаги)

    def test_3d_модель_вместо_оборота(self) -> None:
        raw = {"task": "turntable", "inputs": [свой("image", count=8)], "outputs": ["image"], "conditions": ["USDZ for AR"]}
        self.assertEqual(("модель_3d",), маршрут(raw).route.шаги)
        self.assertEqual(("модель_3d",), маршрут({**raw, "conditions": []}, "a 3D model of our vase").route.шаги)
        self.assertEqual(("оборот_360",), маршрут({**raw, "conditions": []}).route.шаги)

    def test_3d_модель_без_кандидата_честно(self) -> None:
        итог = план({"task": "turntable", "inputs": [свой("image", count=3)], "outputs": ["image"], "conditions": ["glb"]})
        self.assertEqual(
            (["модель_3d"], None, "шаг_без_кандидатов"),
            ([ш["step"] for ш in итог["steps"]], итог["steps"][0]["chosen"], итог["reason"]),
        )
        self.assertEqual(["mesh_route"], свои_заметки(итог))

    def test_бюджет_ноль_свой_gpu_при_открытых_весах(self) -> None:
        база = (*БАЗА, факт("x-open-t2i", "architecture", "text-to-image model"),
                факт("x-open-t2i", "license", "apache-2.0"),
                Fact(model="x-open-t2i", attribute="license", value="apache-2.0",
                     source_url="https://huggingface.co/x/x-open-t2i", tier="vendor", stated_on="2026-10-01"))
        spec = {"task": "generate", "inputs": [], "outputs": ["image"], "shots": 2, "budget": {"amount": 0, "currency": "USD"}}
        итог = pn.plan("spec-only call", facts=list(база), today=СЕГОДНЯ, full=True, spec=spec, spec_only=True)
        if not ep.build(list(база)).get("x-open-t2i").self_hostable:
            self.skipTest("synthetic weights page not read as open weights")
        self.assertEqual(
            (True, "x-open-t2i"),
            (итог["hard"]["self_host"], итог["steps"][0]["chosen"]["model"]),
        )
        self.assertNotEqual("fail", итог["budget"]["outcome"])
        self.assertIn("self_host_route", [з["id"] for з in итог["production_notes"]])


# --- хостинг ---------------------------------------------------------------------


class Хостинг(unittest.TestCase):
    def test_места_облака_это_юрисдикции(self) -> None:
        self.assertEqual(
            ("CN", "EU", "JP", "SG", "US"),
            ep.hosting_of("International (Singapore) and Global (Beijing, Tokyo, Frankfurt, Virginia, Hong Kong)"),
        )
        self.assertEqual((), ep.hosting_of("served from our own data centres"))

    def test_закрепление_региона(self) -> None:
        self.assertEqual(("US",), ep.hosting_pinned_of("USA, Netherlands, Singapore; api.us.vendor.io pins USA"))
        self.assertEqual(("EU",), ep.hosting_pinned_of("data residency in the EU on the enterprise plan"))
        self.assertEqual((), ep.hosting_pinned_of("USA, Netherlands"))

    def test_чужой_регион_без_закрепления_отсеивает(self) -> None:
        узел = ep.Endpoint(model="m", key="m", hosting=("CN", "US"), hosting_note="note")
        self.assertTrue(pn.хостинг_вне(узел, ("US",)).startswith("хостинг вендора по записи: CN, US — запрос может уйти в CN"))
        закреплён = ep.Endpoint(model="m", key="m", hosting=("CN", "US"), hosting_pinned=("US",))
        self.assertEqual("", pn.хостинг_вне(закреплён, ("US",)))
        свой = ep.Endpoint(model="m", key="m", hosting=("US",))
        self.assertEqual("", pn.хостинг_вне(свой, ("US",)))
        self.assertEqual("", pn.хостинг_вне(узел, None))

    def test_вариант_закрытой_семьи_наследует_хостинг(self) -> None:
        from studio.selfrag import facts as F

        реестр = ep.build(F.load_facts())
        семья, вариант = реестр.get("wan-3.0"), реестр.get("wan-3.0-t2v")
        if семья is None or вариант is None or not семья.hosting:
            self.skipTest("live base without the wan-3.0 serving-regions row")
        self.assertEqual(семья.hosting, вариант.hosting)
        self.assertIn("CN", вариант.hosting)


if __name__ == "__main__":
    unittest.main()
