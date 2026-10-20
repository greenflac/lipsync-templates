"""Round 14 (steps & economy): general themes from the hidden set, on the fixer's own EN/RU paraphrases.

Each class guards one category, never a dev or holdout id:

* REAL TIME ONLY WHEN LIVE — a live stream, a video call, an interactive avatar answering
  in session is a recorded gap; low-latency, fast or on-device speech synthesis is an
  ordinary TTS plan;
* SHARED REFERENCES — references are made once per character (r2v too, and a single
  character whose shots come from the duration); a per-shot keyframe edit only when the
  characters share the frame; dialogue in a cutscene gets lip sync, after the video;
* VISUALISER WITHOUT A PERFORMER — abstract / audio-reactive visuals for a track get no
  performer reference and no lip sync; a performer counts only when on screen;
* EDIT AT THE ORDERED FRAME — an edit whose model records a lower limit is followed by an
  upscale priced at the delivery frame (named, or the source frame of YOUR footage);
* NO PREMIUM TIER FOR A CLONED VOICE — the clone's line is read by its cheapest priced tier.

Expected values are literals (T2).
"""

from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from typing import Any

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import planner as pn  # noqa: E402
from studio import realtime  # noqa: E402
from studio.mcp import server  # noqa: E402
from studio.recipes import apply as rc  # noqa: E402

T = {"kind": "text", "owned": True}
ME = {"name": "me", "real": True, "public_figure": False, "consent": "stated", "claim": "none"}


def V(s: float = 10, res: str | None = None) -> dict:
    out: dict[str, Any] = {"kind": "video", "owned": True, "duration_s": s}
    if res:
        out["resolution"] = res
    return out


def A(s: float = 180) -> dict:
    return {"kind": "audio", "owned": True, "duration_s": s}


def _spec(**raw: Any) -> bs.Spec:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    return spec


def _defaults(brief: str, **raw: Any) -> bs.Spec:
    return bs.with_defaults(_spec(**raw), ролик=True, текст=brief)


def _route(brief: str, **raw: Any) -> bs.Маршрут:
    return bs.route(_defaults(brief, **raw))


_PLANS: dict[str, dict] = {}


def _plan(brief: str, **spec: Any) -> dict:
    key = brief + json.dumps(spec, sort_keys=True)
    if key not in _PLANS:
        _PLANS[key] = json.loads(server.plan_pipeline(brief, spec=dict(spec)))
    return _PLANS[key]


def _steps(answer: dict) -> list[str]:
    return [str(s.get("step")) for s in answer.get("steps") or []]


def _models(answer: dict) -> dict[str, str]:
    return {str(s.get("step")): str((s.get("chosen") or {}).get("model") or "") for s in answer.get("steps") or []}


# --- 1. real time only when live --------------------------------------------------------------


class ЖивоеТолькоВЖивом(unittest.TestCase):
    """Speed words alone are a fast TTS; live-system words (or speed + a face answering in session) are a gap."""

    LIVE = (
        ("A video-call avatar that joins our Zoom meetings and answers questions", {"task": "avatar", "outputs": ["video", "speech"]}),
        ("Интерактивный аватар на сайте, который отвечает посетителям голосом прямо в сессии", {"task": "avatar", "outputs": ["video", "speech"]}),
        ("Our avatar should reply with low latency when visitors talk to it on the kiosk", {"task": "avatar", "outputs": ["video", "speech"]}),
        ("Ведущий-аватар для прямого эфира, отвечает на вопросы зрителей", {"task": "avatar", "outputs": ["video", "speech"]}),
        ("A live AI avatar host for our Twitch stream", {"task": "avatar", "outputs": ["video", "speech"]}),
    )
    FAST_TTS = (
        ("Low-latency text-to-speech for our app's navigation prompts", {"task": "generate", "outputs": ["speech"]}),
        ("Синтез речи на устройстве с минимальной задержкой: подсказки для офлайн-приложения", {"task": "generate", "outputs": ["speech"]}),
        ("Fast on-device speech synthesis that runs in real time on a phone", {"task": "generate", "outputs": ["speech"]}),
        ("TTS for our voice bot that answers callers with low latency", {"task": "generate", "outputs": ["speech"]}),
        ("Озвучка аудиогида в реальном времени на устройстве, без сети", {"task": "generate", "outputs": ["speech"]}),
        ("Real-time factor under 0.3 on our laptop for an audiobook narration", {"task": "generate", "outputs": ["speech"]}),
    )

    def test_живое_пробел(self) -> None:
        for brief, spec in self.LIVE:
            with self.subTest(brief=brief):
                self.assertTrue(realtime.applies(brief, spec))

    def test_быстрый_синтез_не_пробел(self) -> None:
        for brief, spec in self.FAST_TTS:
            with self.subTest(brief=brief):
                self.assertFalse(realtime.applies(brief, spec))

    def test_скорость_без_собеседника_не_пробел(self) -> None:
        """A face without an interactive brief: a fast render is not a live system."""
        self.assertFalse(realtime.applies("Render our avatar video with low latency, 60 s", {"task": "avatar", "outputs": ["video"]}))
        self.assertTrue(realtime.asked("visitors talk to it in real time", face=True))
        self.assertTrue(realtime.applies("The avatar answers visitors in real time", {"task": "avatar", "outputs": ["speech"]}))
        self.assertFalse(realtime.asked("visitors talk to it in real time", face=False))

    def test_быстрый_синтез_план_озвучки(self) -> None:
        for brief, lang in (
            ("Low-latency text-to-speech for our app's navigation prompts, 2 minutes of English lines", "en"),
            ("Синтез речи на устройстве с минимальной задержкой: 5 минут подсказок для офлайн-приложения", "ru"),
            ("Fast on-device speech synthesis that runs in real time on a phone, voice our 3-minute audio guide", "en"),
        ):
            with self.subTest(brief=brief):
                answer = _plan(brief, task="generate", inputs=[T], outputs=["speech"], duration_s=120, languages=[lang],
                               people=[])
                self.assertEqual(["озвучка"], _steps(answer))
                self.assertNotEqual("работа_не_поддерживается", answer["reason"])


# --- 2. shared references -----------------------------------------------------------------------


class РеференсыОдинРаз(unittest.TestCase):
    """References are made once per character — r2v and duration-derived shots too."""

    def test_r2v_референс_на_персонажа(self) -> None:
        for brief, chars, shots in (
            ("Kids YouTube series: 5 episodes of 1 minute each with the same two animal characters", 2, 60),
            ("Сериал для TikTok: три одних и тех же героя, 12 серий по 3 шота", 3, 36),
            ("Cutscenes for our RPG: 8 shots with the same hero", 1, 8),
        ):
            with self.subTest(brief=brief):
                м = _route(brief, task="r2v", inputs=[], outputs=["video"], characters=chars, shots=shots, per_shot_s=5)
                self.assertEqual(("генерация_изображения", "видео_по_референсу"), м.шаги)
                self.assertEqual(chars, м.штук["генерация_изображения"])

    def test_один_персонаж_шоты_из_длительности(self) -> None:
        for brief in (
            "A 2-minute episode about our robot mascot",
            "Серия мультфильма про лисёнка на 3 минуты",
            "A 90-second story with the same little girl throughout",
        ):
            with self.subTest(brief=brief):
                м = _route(brief, task="generate", inputs=[], outputs=["video"], characters=1, duration_s=120)
                self.assertEqual(("генерация_изображения", "оживление"), м.шаги)
                self.assertEqual(1, м.штук["генерация_изображения"])

    def test_план_серии_одна_картинка(self) -> None:
        answer = _plan("A 2-minute episode about our robot mascot", task="generate", inputs=[], outputs=["video"],
                       characters=1, duration_s=120, people=[])
        first = answer["steps"][0]
        self.assertEqual(("генерация_изображения", None), (first["step"], first.get("shots")))
        self.assertRegex(first["chosen"]["price"], r"\b1 image\(s\)")


class КлючевойКадрКогдаВместе(unittest.TestCase):
    """A per-shot keyframe edit only when the characters share the frame."""

    TOGETHER = (
        "Game cutscenes: our hero and the villain talk in a throne room",
        "Два кота вместе играют в каждом шоте",
        "A knight and a dragon fight across the series",
        "Бабушка и внук разговаривают на кухне",
    )
    APART = (
        "Анимационный сериал: два персонажа, без диалогов",
        "A series with a fox and an owl, no dialogue",
        "Ad featuring a knight and a dragon",
        "Сериал про двух котов",
    )

    def test_вместе_ключевой_кадр(self) -> None:
        for brief in self.TOGETHER:
            with self.subTest(brief=brief):
                м = _route(brief, task="generate", inputs=[], outputs=["video"], characters=2, shots=6, per_shot_s=5)
                self.assertEqual(("генерация_изображения", "редактирование_изображения", "оживление"), м.шаги)
                self.assertEqual(2, м.штук["генерация_изображения"])

    def test_порознь_прямо_от_референса(self) -> None:
        for brief in self.APART:
            with self.subTest(brief=brief):
                м = _route(brief, task="generate", inputs=[], outputs=["video"], characters=2, shots=6, per_shot_s=5)
                self.assertEqual(("генерация_изображения", "оживление"), м.шаги)
                self.assertEqual(bs.NOTE_CAST_STRAIGHT, м.пометки["оживление"])

    def test_один_персонаж_не_вместе(self) -> None:
        self.assertFalse(bs.персонажи_в_одном_кадре(_spec(characters=1), "the hero and his shadow fight together"))
        self.assertTrue(bs.персонажи_в_одном_кадре(_spec(characters=2), "they fight together"))


class ГубыВКатсцене(unittest.TestCase):
    """Characters' voiced lines in a cutscene move their lips; a narrator does not."""

    def test_реплики_персонажа_липсинк(self) -> None:
        for brief, task, chars, lang in (
            ("Cutscene for our game: the old wizard explains the quest to the player, voiced lines in English", "generate", 1, "en"),
            ("Кат-сцены: принцесса и дракон в пещере, русская озвучка персонажей", "r2v", 2, "ru"),
            ("In-game cinematic: the captain addresses the crew", "generate", 1, "en"),
            ("Катсцена: торговец предлагает герою сделку, реплики на русском", "generate", 2, "ru"),
        ):
            with self.subTest(brief=brief):
                м = _route(brief, task=task, inputs=[], outputs=["video", "speech"], characters=chars, shots=4,
                           per_shot_s=6, languages=[lang])
                self.assertIn("липсинк", м.шаги)
                self.assertEqual(4, м.штук["липсинк"])

    def test_рассказчик_без_губ(self) -> None:
        for brief in (
            "Cutscene with a narrator voice-over over the hero walking through ruins",
            "Кат-сцена: закадровый голос рассказчика, герой идёт по руинам",
        ):
            with self.subTest(brief=brief):
                м = _route(brief, task="generate", inputs=[], outputs=["video", "speech"], characters=1, shots=4,
                           per_shot_s=6, languages=["en"])
                self.assertNotIn("липсинк", м.шаги)

    def test_липсинк_после_видео_по_референсу(self) -> None:
        answer = _plan("Cutscene: our hero says his lines to camera in 4 shots", task="r2v", inputs=[],
                       outputs=["video", "speech"], shots=4, per_shot_s=6, characters=1, languages=["en"], people=[])
        шаги = _steps(answer)
        self.assertLess(шаги.index("видео_по_референсу"), шаги.index("липсинк"))
        self.assertNotEqual("валидатор_отверг", answer["reason"])


# --- 3. visualiser without a performer ----------------------------------------------------------


class ВизуализаторБезИсполнителя(unittest.TestCase):
    """Abstract visuals for a track: looped generation, no reference, no lip sync."""

    NOBODY = (
        ("Abstract audio-reactive visuals for our 3-minute techno track, no performer on screen", "music-visualiser"),
        ("Клип-визуализатор на песню нашей группы: 10 сцен с абстракциями, исполнителей в кадре нет", "music-visualiser"),
        ("Visualizer video for our album track: the artist's logo morphing over liquid gradients", "music-visualiser"),
        ("Audio-reactive visualiser for the band's new song, 6 scenes of cosmic landscapes", "generate"),
        ("Визуализатор для трека нашего рэпера: дым и свет, без людей", "music-visualiser"),
    )

    def test_без_исполнителя_петли(self) -> None:
        for brief, task in self.NOBODY:
            with self.subTest(brief=brief):
                spec = _defaults(brief, task=task, inputs=[A(180)], outputs=["video"], duration_s=180, shots=6)
                self.assertEqual(("music-visualiser", None), (spec.task, spec.characters))
                м = bs.route(spec)
                self.assertEqual(("генерация_видео",), м.шаги)

    def test_исполнитель_в_кадре_референс(self) -> None:
        for brief, steps in (
            ("Music video for our song: the same singer performs in 8 scenes, singing on camera",
             ("генерация_изображения", "оживление", "липсинк")),
            ("Клип на наш трек: певица танцует в 6 сценах", ("генерация_изображения", "оживление")),
            ("A rapper performs our track in 6 locations", ("генерация_изображения", "оживление", "липсинк")),
        ):
            with self.subTest(brief=brief):
                м = _route(brief, task="generate", inputs=[A(120)], outputs=["video"], duration_s=120, shots=6)
                self.assertEqual(steps, м.шаги)

    def test_исполнитель_с_визуальными_словами_не_визуализатор(self) -> None:
        spec = _defaults("Audio-reactive music video: the singer performs in 6 scenes", task="generate", inputs=[A(120)],
                         outputs=["video"], duration_s=120, shots=6)
        self.assertEqual(("generate", 1), (spec.task, spec.characters))

    def test_петли_визуализатора_названного_generate(self) -> None:
        brief = "Audio-reactive visualiser for the band's new song, 6 scenes of cosmic landscapes"
        spec = _spec(task="generate", inputs=[A(180)], outputs=["video"], duration_s=180, shots=6)
        п = rc.rewrite(spec, bs.route(bs.with_defaults(spec, ролик=True, текст=brief)), brief)
        self.assertEqual({"генерация_видео": (32.0, 8.0)}, dict(п.step_seconds))

    def test_слова_без_исполнителя(self) -> None:
        self.assertNotRegex(bs.исполнитель_словами("visuals for the band's track"), bs.PERFORMER)
        self.assertNotRegex(bs.исполнитель_словами("the artist's logo morphing"), bs.PERFORMER)
        self.assertNotRegex(bs.исполнитель_словами("клип на песню нашей группы"), bs.PERFORMER)
        self.assertRegex(bs.исполнитель_словами("the band plays on stage"), bs.PERFORMER)

    def test_план_визуализатора_без_портретов(self) -> None:
        answer = _plan("Abstract audio-reactive visuals for our 3-minute techno track, no performer on screen",
                       task="music-visualiser", inputs=[A(180)], outputs=["video"], duration_s=180, people=[])
        self.assertEqual(["генерация_видео"], _steps(answer))


# --- 4. edit at the ordered frame ---------------------------------------------------------------


class КадрВыдачиПравки(unittest.TestCase):
    """An edit whose model records a lower limit is followed by an upscale priced at the delivery frame."""

    def test_названный_кадр_выше_предела_апскейл(self) -> None:
        for brief, edit in (
            ("Relight our interview clip to evening light, 4K master", "relight"),
            ("Переосвети наш ролик под вечерний свет, сдать в 4K", "relight"),
            ("Replace the red car with a blue one in our clip, deliver 4K", "replace-object"),
        ):
            with self.subTest(brief=brief):
                answer = _plan(brief, task="video-edit", edit=[edit], inputs=[V(10)], outputs=["video"], duration_s=10,
                               resolution="4K", people=[])
                self.assertEqual(["правка_видео", "апскейл"], _steps(answer))
                self.assertRegex(answer["steps"][1]["chosen"]["price"], r"\[2160p\]")

    def test_кадр_исходника_апскейл_по_кадру_выдачи(self) -> None:
        for brief in ("Replace the red car with a blue one in our clip", "Замени машину на нашем ролике на синюю"):
            with self.subTest(brief=brief):
                answer = _plan(brief, task="video-edit", edit=["replace-object"], inputs=[V(8, "3840x2160")],
                               outputs=["video"], duration_s=8, people=[])
                self.assertEqual(["правка_видео", "апскейл"], _steps(answer))
                self.assertRegex(answer["steps"][1]["chosen"]["price"], r"\[2160p\]")

    def test_кадр_не_выше_предела_без_апскейла(self) -> None:
        answer = _plan("Replace the red car with a blue one in our clip, deliver 720p", task="video-edit",
                       edit=["replace-object"], inputs=[V(8)], outputs=["video"], duration_s=8, resolution="720p",
                       people=[])
        self.assertEqual(["правка_видео"], _steps(answer))

    def test_работы_в_кадре_исходника(self) -> None:
        self.assertTrue({"remove-background", "interpolate", "video-edit"} <= pn.SOURCE_FRAME_TASKS)
        self.assertNotIn("lipsync", pn.SOURCE_FRAME_TASKS)


# --- 5. no premium tier for a cloned voice ------------------------------------------------------


def _cand(model: str, usd: float) -> Any:
    вариант = SimpleNamespace(usd=usd, conditional=False, lower_bound="", formula=f"≈1000 chars × {usd} usd")
    return SimpleNamespace(model=model, cost=SimpleNamespace(default=вариант, cheapest=вариант))


class ДешёвыйТарифКлона(unittest.TestCase):
    """The cloned voice is read by the cheapest priced tier of the clone's line."""

    OP = next(оп for оп in pn.OPERATIONS if оп.name == "озвучка")

    def test_премиальный_уступает_место(self) -> None:
        найдены = [_cand("acme-speech-hd", 0.10), _cand("acme-speech-turbo", 0.06), _cand("other-tts", 0.01)]
        pn.дешевле_в_линейке(найдены, "acme", self.OP)
        self.assertEqual(["acme-speech-turbo", "acme-speech-hd", "other-tts"], [c.model for c in найдены])

    def test_не_премиальный_не_трогается(self) -> None:
        найдены = [_cand("acme-speech-v2", 0.10), _cand("acme-speech-turbo", 0.06)]
        pn.дешевле_в_линейке(найдены, "acme", self.OP)
        self.assertEqual(["acme-speech-v2", "acme-speech-turbo"], [c.model for c in найдены])

    def test_чужая_линейка_не_вперёд(self) -> None:
        найдены = [_cand("acme-speech-hd", 0.10), _cand("other-turbo", 0.01)]
        pn.дешевле_в_линейке(найдены, "acme", self.OP)
        self.assertEqual(["acme-speech-hd", "other-turbo"], [c.model for c in найдены])

    def test_рассылка_голосом_клона(self) -> None:
        for brief, seconds, lang in (
            ("Weekly audio newsletter: clone my voice once from a 1-minute sample, then voice 4 issues of 5 minutes each", 1200, "en"),
            ("Озвучь нашу рассылку моим голосом: клон по записи, 8 выпусков по 3 минуты", 1440, "ru"),
            ("Clone my voice and read our 10-minute newsletter", 600, "en"),
        ):
            with self.subTest(brief=brief):
                answer = _plan(brief, task="voice-clone", inputs=[A(60), T], outputs=["speech"], duration_s=seconds,
                               languages=[lang], people=[ME])
                self.assertEqual(["клонирование_голоса", "озвучка"], _steps(answer))
                модели = _models(answer)
                self.assertEqual("minimax-voice-clone", модели["клонирование_голоса"])
                self.assertRegex(модели["озвучка"], r"^minimax-speech-[\d.]+-turbo$")
                self.assertRegex(answer["steps"][0]["chosen"]["price"], r"^1\.50 usd")
                self.assertRegex(answer["steps"][1]["chosen"]["price"], r"0\.06 usd (?:per|за) 1000")


if __name__ == "__main__":
    unittest.main()
