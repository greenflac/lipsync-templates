"""Round 11: false refusals and needless questions found by the hidden holdout, on the fixer's own paraphrases.

Each class guards one category, never a dev or holdout id:

* word-level screen hits decided by a filled `spec.people` (an audience of
  children, a fictional character, a contracted actor with consent, a deceased
  relative) — and the negative controls that must still refuse;
* speech read from the customer's script without a named length;
* restoration and colourisation of brought photos;
* a face swap on a still image;
* a recurring character without `spec.characters` (series of pictures, a
  cartoon series);
* a short generated clip where someone speaks (native audio) against a
  voice-over ad;
* a voice sample + a text in a speech order (voice clone);
* a photo + a driving video (motion transfer).

Expected values are literals (T2).
"""

from __future__ import annotations

import json
import os
import unittest

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import endpoints as ep  # noqa: E402
from studio.mcp import server  # noqa: E402
from studio.mcp import spec_screen  # noqa: E402
from studio.selfrag.facts import Fact  # noqa: E402


def _plan(brief: str, **spec: object) -> dict:
    return json.loads(server.plan_pipeline(brief, spec=dict(spec)))


def _steps(answer: dict) -> list[str]:
    return [str(s.get("step")) for s in answer.get("steps") or []]


def _models(answer: dict) -> dict[str, str]:
    return {str(s.get("step")): str((s.get("chosen") or {}).get("model") or "") for s in answer.get("steps") or []}


def _refused(answer: dict) -> bool:
    return answer.get("reason") == "запрещённая_тема" or (answer.get("people_policy") or {}).get("decision") == "refuse"


ME = {"name": "me", "real": True, "public_figure": False, "consent": "stated", "claim": "none"}


class СловоРешаетSpec(unittest.TestCase):
    """A child word or a likeness word is decided by `spec.people` when it is filled."""

    def test_дети_зрители_не_отказ(self) -> None:
        answer = _plan(
            "Read a bedtime story for my kids in my late mother's voice, family only, everyone agrees.",
            task="voice-clone",
            inputs=[{"kind": "audio", "owned": True, "duration_s": 60}, {"kind": "text", "owned": True}],
            outputs=["speech"],
            duration_s=120,
            languages=["en"],
            audience="children",
            people=[{"name": "my mother", "real": True, "public_figure": False, "deceased": True, "consent": "stated", "claim": "none"}],
        )
        self.assertFalse(_refused(answer))
        self.assertEqual(["клонирование_голоса"], _steps(answer))
        self.assertEqual(1, answer.get("decided_by_spec"))

    def test_без_spec_people_слово_решает_как_прежде(self) -> None:
        answer = _plan(
            "Read a bedtime story for my kids in a warm voice, 2 minutes.",
            task="generate",
            inputs=[{"kind": "text", "owned": True}],
            outputs=["speech"],
            duration_s=120,
            languages=["en"],
        )
        self.assertTrue(_refused(answer))

    def test_мультсериал_с_вымышленной_школьницей(self) -> None:
        answer = _plan(
            "Анимационный сериал для детей: школьница Катя и её робот решают задачки, серия минута.",
            task="generate",
            inputs=[],
            outputs=["video", "speech"],
            duration_s=60,
            languages=["ru"],
            audience="children",
            people=[{"name": "Катя", "real": False}],
        )
        self.assertFalse(_refused(answer))
        self.assertEqual("генерация_изображения", _steps(answer)[0])

    def test_реальный_ребёнок_по_имени_отказ_остаётся(self) -> None:
        answer = _plan(
            "Animate this photo of my kids at the beach.",
            task="animate",
            inputs=[{"kind": "image", "owned": True}],
            outputs=["video"],
            duration_s=5,
            people=[{"name": "my kids", "real": True, "public_figure": False, "consent": "stated", "claim": "none"}],
        )
        self.assertTrue(_refused(answer))

    def test_minor_true_держит_отказ(self) -> None:
        answer = _plan(
            "Animate this photo of my kids at the beach.",
            task="animate",
            inputs=[{"kind": "image", "owned": True}],
            outputs=["video"],
            duration_s=5,
            people=[{"name": "Anna", "real": True, "public_figure": False, "consent": "stated", "claim": "none", "minor": True}],
        )
        self.assertTrue(_refused(answer))

    def test_актёр_по_контракту_с_согласием(self) -> None:
        answer = _plan(
            "TV ad starring an actor we hired; contract and consent signed; animate his photo drinking our lemonade, 10 s.",
            task="animate",
            inputs=[{"kind": "image", "owned": True}],
            outputs=["video"],
            duration_s=10,
            people=[{"name": "hired actor", "real": True, "public_figure": False, "consent": "stated", "claim": "endorsement"}],
        )
        self.assertFalse(_refused(answer))
        self.assertEqual(["оживление"], _steps(answer))

    def test_тот_же_бриф_без_согласия_отказ(self) -> None:
        answer = _plan(
            "TV ad starring an actor we hired; animate his photo drinking our lemonade, 10 s.",
            task="animate",
            inputs=[{"kind": "image", "owned": True}],
            outputs=["video"],
            duration_s=10,
            people=[{"name": "hired actor", "real": True, "public_figure": False, "consent": "unknown", "claim": "endorsement"}],
        )
        # Согласие не названо: слово о подмене образа не снимается — отказ просева, а не вопрос.
        self.assertEqual("запрещённая_тема", answer.get("reason"))

    def test_знаменитость_при_слове_подмены_отказ(self) -> None:
        answer = _plan(
            "A face-swapped clip of Taylor Swift in my video, she agreed.",
            task="face-replace",
            inputs=[{"kind": "video", "owned": True, "duration_s": 10}],
            outputs=["video"],
            duration_s=10,
            people=[{"name": "Taylor Swift", "real": True, "public_figure": True, "consent": "stated", "claim": "other"}],
        )
        self.assertTrue(_refused(answer))

    def test_вымышленный_герой_рекламы(self) -> None:
        answer = _plan(
            "A TV ad starring a cartoon fox who loves our cereal, 10 seconds.",
            task="generate",
            inputs=[],
            outputs=["video"],
            duration_s=10,
            people=[],
        )
        self.assertFalse(_refused(answer))

    def test_real_minor_по_полю_и_по_имени(self) -> None:
        self.assertTrue(spec_screen.real_minor({"name": "Anna", "real": True, "minor": True}))
        self.assertFalse(spec_screen.real_minor({"name": "my kids", "real": True, "minor": False}))
        self.assertFalse(spec_screen.real_minor({"name": "my kids", "real": False}))
        self.assertTrue(spec_screen.real_minor({"name": "my kids", "real": True}))
        self.assertFalse(spec_screen.real_minor({"name": "my mother", "real": True}))

    def test_поля_spec(self) -> None:
        spec, errors, _ = bs.gaps(
            {"task": "generate", "inputs": [], "outputs": ["image"], "shots": 1, "audience": "children",
             "people": [{"name": "x", "real": True, "minor": False, "consent": "stated"}]}
        )
        self.assertEqual(([], "children"), (errors, spec.audience))
        _, errors, _ = bs.gaps({"task": "generate", "inputs": [], "outputs": ["image"], "shots": 1, "audience": "kids"})
        self.assertEqual(["spec.audience: kids not in children, teens, general, adults"], errors)


class ОзвучкаСценария(unittest.TestCase):
    def test_текст_без_длины_план(self) -> None:
        answer = _plan(
            "Turn my script into a voice-over, warm female voice.",
            task="generate", inputs=[{"kind": "text", "owned": True}], outputs=["speech"], languages=["en"], people=[],
        )
        self.assertEqual(["озвучка"], _steps(answer))
        поле = answer["understood_as"]["fields"]["duration_s"]
        self.assertEqual((60.0, "default"), (поле["value"], поле["from"]))

    def test_без_текста_длина_нужна(self) -> None:
        answer = _plan(
            "A voice-over, warm female voice.",
            task="generate", inputs=[], outputs=["speech"], languages=["en"], people=[],
        )
        self.assertEqual("нужна_спецификация", answer["reason"])

    def test_видео_по_тексту_длина_нужна(self) -> None:
        answer = _plan(
            "A video with a voice-over from my script.",
            task="generate", inputs=[{"kind": "text", "owned": True}], outputs=["video", "speech"], languages=["en"], people=[],
        )
        self.assertEqual("нужна_спецификация", answer["reason"])


class АрхивСнимков(unittest.TestCase):
    def test_реставрация_и_раскраска_фото(self) -> None:
        answer = _plan(
            "Restore and colorize 12 old black-and-white family photos.",
            task=["restore", "colorize"], inputs=[{"kind": "image", "owned": True, "count": 12}], outputs=["image"], people=[],
        )
        self.assertEqual(["реставрация_изображения", "раскраска_изображения"], _steps(answer))

    def test_одно_фото_без_count(self) -> None:
        answer = _plan(
            "Restore my great-grandfather's old photo.",
            task="restore", inputs=[{"kind": "image", "owned": True}], outputs=["image"], people=[],
        )
        self.assertEqual(["реставрация_изображения"], _steps(answer))

    def test_плёнка_остаётся_видео(self) -> None:
        answer = _plan(
            "Restore and colorize our 3-minute home movie.",
            task=["restore", "colorize"], inputs=[{"kind": "video", "owned": True, "duration_s": 180}], outputs=["video"], people=[],
        )
        self.assertEqual(["реставрация", "раскраска"], _steps(answer))


class ЛицоНаСнимке(unittest.TestCase):
    def test_картиночный_face_swap(self) -> None:
        answer = _plan(
            "Swap my face onto the knight in this poster image.",
            task="face-replace", inputs=[{"kind": "image", "owned": True, "count": 2}], outputs=["image"], people=[ME],
        )
        self.assertEqual(["замена_лица_изображения"], _steps(answer))
        # Тринадцатый круг: картиночный face swap WaveSpeed с записанной ценой.
        self.assertIn(
            _models(answer)["замена_лица_изображения"],
            {"easel-advanced-face-swap", "face-swap-fal", "wavespeed-image-face-swap"},
        )

    def test_видео_по_прежнему_замена_персонажа(self) -> None:
        answer = _plan(
            "Swap my face into my wedding clip.",
            task="face-replace", inputs=[{"kind": "video", "owned": True, "duration_s": 10}, {"kind": "image", "owned": True}],
            outputs=["video"], duration_s=10, people=[ME],
        )
        self.assertEqual(["замена_персонажа"], _steps(answer))


class ПовторяющийсяПерсонаж(unittest.TestCase):
    def test_серия_картинок_без_characters(self) -> None:
        answer = _plan(
            "20 posts with our mascot, a blue owl, the same owl in every picture.",
            task="generate", inputs=[], outputs=["image"], shots=20, people=[],
        )
        self.assertEqual(["генерация_изображения", "редактирование_изображения"], _steps(answer))
        self.assertEqual(1, answer["understood_as"]["fields"]["characters"]["value"])

    def test_разные_картинки_без_героя(self) -> None:
        answer = _plan(
            "20 different cosy interiors for our blog.",
            task="generate", inputs=[], outputs=["image"], shots=20, people=[],
        )
        self.assertEqual(["генерация_изображения"], _steps(answer))

    def test_мультсериал_с_героем_от_референса(self) -> None:
        answer = _plan(
            "Pilot episode of a children's animated series about a curious little robot, 2 minutes, narrated.",
            task="generate", inputs=[], outputs=["video", "speech"], duration_s=120, languages=["en"], people=[],
        )
        self.assertEqual(["генерация_изображения", "озвучка", "оживление"], _steps(answer))

    def test_заставка_сериала_без_героя(self) -> None:
        answer = _plan(
            "30-second opening for a web series, 6 cuts, with a song.",
            task="generate", inputs=[], outputs=["video", "music"], shots=6, per_shot_s=5, people=[],
        )
        self.assertEqual(["генерация_видео", "музыка"], _steps(answer))

    def test_один_персонаж_длинный_ролик(self) -> None:
        answer = _plan(
            "Our fox character walks through the forest.",
            task="generate", inputs=[], outputs=["video"], duration_s=40, characters=1, people=[],
        )
        self.assertEqual(["генерация_изображения", "оживление"], _steps(answer))

    def test_один_персонаж_один_прогон(self) -> None:
        answer = _plan(
            "Our fox character walks through the forest.",
            task="generate", inputs=[], outputs=["video"], duration_s=10, characters=1, people=[],
        )
        self.assertEqual(["генерация_видео"], _steps(answer))


class ГоворятВКадре(unittest.TestCase):
    def test_повар_говорит_нативный_звук(self) -> None:
        answer = _plan(
            "Generate an 8-second video of a chef in a kitchen saying 'Welcome to our restaurant'.",
            task="generate", inputs=[], outputs=["video", "speech"], duration_s=8, languages=["en"], people=[],
        )
        self.assertEqual(["видео_со_звуком"], _steps(answer))

    def test_язык_без_речи_в_выходе(self) -> None:
        answer = _plan(
            "Сгенерируй 10 секунд: бариста говорит в камеру «попробуйте наш латте».",
            task="generate", inputs=[], outputs=["video"], duration_s=10, languages=["ru"], people=[],
        )
        self.assertEqual(["видео_со_звуком"], _steps(answer))

    def test_реклама_с_озвучкой_не_нативная(self) -> None:
        answer = _plan(
            "A 15-second vertical ad for our tea with a voice-over that says our slogan.",
            task="generate", inputs=[], outputs=["video", "speech"], duration_s=15, languages=["en"], people=[],
        )
        self.assertEqual(["озвучка", "генерация_видео"], _steps(answer))

    def test_длинный_ролик_не_нативный(self) -> None:
        answer = _plan(
            "A 60-second clip where a guide talks about our city.",
            task="generate", inputs=[], outputs=["video", "speech"], duration_s=60, languages=["en"], people=[],
        )
        self.assertNotIn("видео_со_звуком", _steps(answer))

    def test_граница_длины(self) -> None:
        def spec(s: float) -> bs.Spec:
            return bs.gaps({"task": "generate", "inputs": [], "outputs": ["video", "speech"], "duration_s": s, "languages": ["en"]})[0]

        self.assertEqual(
            (True, False), (bs.говорящий_ролик(spec(15), "he says hi"), bs.говорящий_ролик(spec(16), "he says hi"))
        )


class ОбразецГолоса(unittest.TestCase):
    def test_образец_и_текст_в_заказе_речи(self) -> None:
        answer = _plan(
            "Here is 30 seconds of my voice; clone it and read my script with it.",
            task="generate",
            inputs=[{"kind": "audio", "owned": True, "duration_s": 30}, {"kind": "text", "owned": True}],
            outputs=["speech"], duration_s=120, languages=["en"], people=[ME],
        )
        self.assertEqual(["клонирование_голоса"], _steps(answer))


class ПереносДвижения(unittest.TestCase):
    def test_фото_и_ведущее_видео(self) -> None:
        answer = _plan(
            "Animate my photo so I copy the dance from this driving video, 8 seconds.",
            task="animate",
            inputs=[{"kind": "image", "owned": True}, {"kind": "video", "owned": True, "duration_s": 8}],
            outputs=["video"], duration_s=8, people=[ME],
        )
        self.assertEqual(["перенос_движения"], _steps(answer))
        self.assertIn("motion-control", _models(answer)["перенос_движения"])

    def test_только_фото_оживление(self) -> None:
        answer = _plan(
            "Animate my photo, 5 seconds.",
            task="animate", inputs=[{"kind": "image", "owned": True}], outputs=["video"], duration_s=5, people=[ME],
        )
        self.assertEqual(["оживление"], _steps(answer))

    def test_работа_только_по_своему_имени(self) -> None:
        """Схема соседа под семьёй не делает семью переносом движения (dev-набор падал на 6 брифов)."""
        сосед = Fact(
            model="acme-3.0",
            attribute="max_seconds",
            value="10",
            source_url="https://fal.ai/api/openapi/queue/openapi.json?endpoint_id=fal-ai/acme/v3/standard/motion-control",
            tier="vendor",
            stated_on="2026-10-19",
        )
        работы, _, _ = ep.classify("acme-3.0", [сосед])
        self.assertNotIn(ep.MOTION_TRANSFER, работы)
        работы, _, _ = ep.classify("acme-v3-standard-motion-control", [])
        self.assertEqual((ep.V2V_EDIT, ep.MOTION_TRANSFER), работы)


if __name__ == "__main__":
    unittest.main()
