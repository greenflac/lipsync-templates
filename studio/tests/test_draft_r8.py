"""Черновик спецификации, восьмой круг (2026-10-16): любое письмо, входы, владение.

Валидатор v8 на 103 черновиках: пусто у брифов на японском, китайском,
корейском, арабском, хинди, тайском и испанском; `inputs` почти никогда — план
«как есть» строился у 14 из 103. Каждый пункт — литералом (Т2), и «не знаю»
остаётся отсутствием поля, а не уверенной ошибкой.
"""

from __future__ import annotations

import unittest

from studio import brief_spec as bs
from studio import draft_lexicon as lx


def черновик(бриф: str) -> dict:
    return bs.draft(бриф)["spec"]


class ЛюбоеПисьмо(unittest.TestCase):
    def test_японский_удаление_фона_со_своими_фото(self) -> None:
        self.assertEqual(
            {
                "task": "remove-background",
                "outputs": ["image"],
                "inputs": [{"kind": "image", "owned": True, "count": 10}],
                "shots": 10,
                "budget": {"amount": 500.0, "currency": "JPY"},
            },
            черновик("商品写真10枚から背景を白に差し替えた画像を作りたい、予算は500円"),
        )

    def test_китайский_заказ_ролика(self) -> None:
        self.assertEqual(
            {
                "task": "generate",
                "outputs": ["video", "speech"],
                "inputs": [],
                "duration_s": 15.0,
                "aspect": "9:16",
                "budget": {"amount": 100.0, "currency": "CNY"},
                "languages": ["zh"],
            },
            черновик("为我们的茶叶品牌生成一个15秒竖屏视频广告，中文配音，预算100元人民币"),
        )

    def test_китайский_дубляж_язык_исходника_не_цель(self) -> None:
        ч = черновик("把这段30秒的英文产品视频配成中文普通话，口型要对上，主讲人同意")
        self.assertEqual("dub-translate", ч["task"])
        self.assertEqual(["zh"], ч["languages"])
        self.assertIs(True, ч["lipsync"])
        self.assertEqual([{"kind": "video", "owned": True, "duration_s": 30.0}], ч["inputs"])

    def test_японский_расшифровка_совещания(self) -> None:
        ч = черновик("1時間の日本語会議を文字起こしして、話者分離もしてください")
        self.assertEqual(("transcribe", ["ja"]), (ч["task"], ч["languages"]))
        self.assertEqual([{"kind": "audio", "owned": True, "duration_s": 3600.0}], ч["inputs"])

    def test_тайский_видео_для_назначения_не_заказ(self) -> None:
        ч = черновик("เสียงบรรยายภาษาไทย 60 วินาที สำหรับวิดีโอแนะนำโรงแรม")
        self.assertEqual(["speech"], ч["outputs"])
        self.assertEqual(["th"], ч["languages"])

    def test_испанский_своё_аудио_чужое_фото(self) -> None:
        ч = черновик(
            "Mi abuela (está de acuerdo) quiere felicitar a su nieta: haz que su foto hable 20 segundos "
            "en español con su propia voz (tengo un audio de 1 minuto)"
        )
        self.assertEqual("avatar", ч["task"])
        # «su foto» — чья, не сказано: владение не угадывается.
        self.assertEqual([{"kind": "image", "owned": None}, {"kind": "audio", "owned": True}], ч["inputs"])

    def test_письмо_как_язык(self) -> None:
        self.assertEqual("ja", lx.script_language("ラーメン店の宣伝"))
        self.assertEqual("zh", lx.script_language("茶叶品牌"))
        self.assertIsNone(lx.script_language("plain english"))
        self.assertIsNone(lx.script_language("по-русски"))

    def test_цифры_любого_письма(self) -> None:
        self.assertEqual("30 ثانية", lx.normalise("٣٠ ثانية"))


class ВходыИВладение(unittest.TestCase):
    def test_ничего_не_названо_пустые_входы(self) -> None:
        self.assertEqual([], черновик("Generate a 5 second 120fps 4K slow-motion shot of a hummingbird")["inputs"])

    def test_120fps_заказ_не_интерполяция(self) -> None:
        self.assertEqual("generate", черновик("Generate a 5 second 120fps 4K slow-motion shot of a hummingbird")["task"])

    def test_свой_клип_в_60fps_интерполяция(self) -> None:
        ч = черновик("Convert my 10 s 4K 24fps clip to smooth 60fps")
        self.assertEqual(("interpolate", [{"kind": "video", "owned": True}]), (ч["task"], ч["inputs"]))

    def test_материал_работы_свой_по_упоминанию(self) -> None:
        ч = черновик("Real-estate drone footage, 90 seconds, shaky 2.7K — stabilise it and upscale to 4K 60fps")
        self.assertEqual(True, ч["inputs"][0]["owned"])

    def test_чужой_материал_не_угадывается(self) -> None:
        ч = черновик("Restore a scratched clip from a movie I downloaded, 5 minutes")
        self.assertEqual(None, ч["inputs"][0]["owned"])

    def test_портрет_исторического_лица_не_свой(self) -> None:
        ч = черновик(
            "Educational clip: Abraham Lincoln portrait animated reciting the opening of the Gettysburg Address, 30 s"
        )
        self.assertNotIn(True, [в.get("owned") for в in ч.get("inputs", [])])

    def test_ролик_о_наших_кроссовках_не_вход(self) -> None:
        ч = черновик("360° spin video of our sneaker from 4 product photos (front, back, sides), 6 s, white background")
        self.assertEqual(["image"], [в["kind"] for в in ч["inputs"]])

    def test_принесённое_без_моего_не_пустота(self) -> None:
        ч = черновик(
            "My colleague Anna agreed (written) to be an avatar: use her 2-min webcam recording to make a 60 s "
            "onboarding video in German, 1080p"
        )
        self.assertEqual([{"kind": "video", "owned": None}], ч["inputs"])

    def test_моё_в_пяти_словах(self) -> None:
        ч = черновик("Add footsteps, door creak and rain foley to my silent 30 s short film")
        self.assertEqual((["sfx"], [{"kind": "video", "owned": True}]), (ч["outputs"], ч["inputs"]))

    def test_без_упоминания_материала_владение_не_угадывается(self) -> None:
        ч = черновик("Please stabilise and reframe to 9:16, 20 s")
        self.assertEqual([{"kind": "video", "owned": None, "duration_s": 20.0}], ч["inputs"])

    def test_названный_снимок_не_пустые_входы(self) -> None:
        ч = черновик("Talking avatar from a photo of the presenter, 30 s, English")
        self.assertEqual([{"kind": "image", "owned": None}], ч["inputs"])

    def test_картинка_без_хозяина_входы_не_пустые(self) -> None:
        # Снимок назван, чей — нет: «inputs» отсутствует (вопрос), а не [].
        self.assertNotIn("inputs", черновик("Make a 10 s video like this picture"))

    def test_правка_своих_фото(self) -> None:
        ч = черновик("Remove the power lines from 30 real-estate photos")
        self.assertEqual(("edit", ["image"]), (ч["task"], ч["outputs"]))


class Выходы(unittest.TestCase):
    def test_язык_жестов_без_речи(self) -> None:
        ч = черновик("Sign-language avatar that signs our 1-minute announcement in ASL, 16:9 1080p")
        self.assertEqual((["video"], ["ase"]), (ч["outputs"], ч["languages"]))

    def test_инструментал_это_музыка(self) -> None:
        self.assertEqual(["music"], черновик("Generate a 2-minute lo-fi hip hop instrumental for streaming")["outputs"])

    def test_бит_с_картинкой_не_только_музыка(self) -> None:
        self.assertEqual(["video"], черновик("Animated lo-fi beat visual loop, 2 minutes")["outputs"])

    def test_аниме_опенинг_не_только_музыка(self) -> None:
        ч = черновик("30-second anime-style opening (OP) for a web series, 16:9 1080p, 6 cuts, japanese song with vocals")
        self.assertIn("video", ч["outputs"])

    def test_дубляж_без_языка_исходника(self) -> None:
        ч = черновик("Translate our 90s product video from English into Polish and Turkish, lipsync обязательно")
        self.assertEqual(["pl", "tr"], ч["languages"])


class СловарьНапрямую(unittest.TestCase):
    """Константы словаря — литералом, без черновика целиком (`scripts/mutate_round8.py`)."""

    def test_китайское_сгенерируй_это_заказ_генерации(self) -> None:
        # «生成» — единственное слово заказа в этой фразе: без него работа не названа.
        self.assertEqual("generate", lx.task("生成一个广告"))

    def test_китайское_моё_делает_видео_своим(self) -> None:
        # «我的» — притяжательное прямо перед «视频»; «我们» сюда не подходит.
        self.assertEqual({"video": True}, lx.owned_media("请处理我的视频"))


if __name__ == "__main__":
    unittest.main()
