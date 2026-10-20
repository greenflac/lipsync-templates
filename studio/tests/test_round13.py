"""Round 13: general themes from the hidden set, on the fixer's own EN/RU paraphrases.

Each class guards one category, never a dev or holdout id:

* GENERATION ECONOMY — shared assets (character references, one loop for every
  version, a voice clone) are made once, priced once, and the plan says so;
* REQUIRED STEPS — a clone that only creates the voice is followed by speech in
  that voice; an edit of the customer's footage is delivered at the source frame
  (an upscale when the model's recorded limit is lower); lip sync in every
  speaking shot of a dialogue series; a music video with a recurring performer is a
  reference, per-scene animation and lip sync to the track;
* EDIT BEFORE GENERATE — assembly-only edits (trim, join, speed, LUT, watermark,
  logo, burn-in of supplied subtitles, crop) plan at 0 usd without a question; a
  reframe is a tracked crop unless the subject would be cut;
* SCOPE — real-time / live work is a recorded gap with the base's realtime options;
  sound for the customer's own video is a video-to-audio step.

Expected values are literals (T2).
"""

from __future__ import annotations

import json
import os
import unittest
from typing import Any

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import endpoints as ep  # noqa: E402
from studio import planner as pn  # noqa: E402
from studio import realtime  # noqa: E402
from studio.mcp import server  # noqa: E402
from studio.recipes import apply as rc  # noqa: E402
from studio.selfrag.facts import Fact, load_facts  # noqa: E402

T = {"kind": "text", "owned": True}
ME = {"name": "me", "real": True, "public_figure": False, "consent": "stated", "claim": "none"}


def V(s: float = 30, res: str | None = None) -> dict:
    out: dict[str, Any] = {"kind": "video", "owned": True, "duration_s": s}
    if res:
        out["resolution"] = res
    return out


def A(s: float = 120) -> dict:
    return {"kind": "audio", "owned": True, "duration_s": s}


def _spec(**raw: Any) -> bs.Spec:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    return spec


def _route(brief: str, **raw: Any) -> bs.Маршрут:
    return bs.route(bs.with_defaults(_spec(**raw), ролик=True, текст=brief))


def _rewrite(brief: str, **raw: Any) -> rc.Applied:
    spec = bs.with_defaults(_spec(**raw), ролик=True, текст=brief)
    return rc.rewrite(spec, bs.route(spec), brief)


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


# --- 1. generation economy ---------------------------------------------------------------


class ОбщиеРеференсы(unittest.TestCase):
    """Two or more recurring characters: one reference per character for the whole series."""

    # Round 14: the per-shot keyframe edit is made only when the characters SHARE the
    # frame (argue, "in every shot"); otherwise each shot starts from its reference.
    CASES = (
        ("A web series where two robots argue, 4 episodes of 3 shots", 2, 12,
         ("генерация_изображения", "редактирование_изображения", "оживление")),
        ("Три подруги в каждом из 6 шотов рекламы", 3, 6,
         ("генерация_изображения", "редактирование_изображения", "оживление")),
        ("Сериал про двух котов: 10 серий по 3 шота", 2, 30, ("генерация_изображения", "оживление")),
        ("Ad with a knight and a dragon in 5 shots", 2, 5, ("генерация_изображения", "оживление")),
    )

    def test_референс_на_персонажа_один_раз(self) -> None:
        for brief, chars, shots, steps in self.CASES:
            with self.subTest(brief=brief):
                м = _route(brief, task="generate", inputs=[], outputs=["video"], characters=chars, shots=shots, per_shot_s=5)
                self.assertEqual(steps, м.шаги)
                self.assertEqual(chars, м.штук["генерация_изображения"])

    def test_длинный_ролик_без_шотов_тоже_серия(self) -> None:
        м = _route("A 40-second clip with a knight and a dragon", task="generate", inputs=[], outputs=["video"],
                   characters=2, duration_s=40)
        self.assertEqual(("генерация_изображения", "оживление"), м.шаги)
        м = _route("A 40-second clip: a knight and a dragon fight", task="generate", inputs=[], outputs=["video"],
                   characters=2, duration_s=40)
        self.assertEqual(("генерация_изображения", "редактирование_изображения", "оживление"), м.шаги)

    def test_один_шот_двух_персонажей_ключевой_кадр(self) -> None:
        м = _route("One 8 s shot: a knight and a dragon", task="generate", inputs=[], outputs=["video"],
                   characters=2, duration_s=8)
        self.assertEqual(("генерация_изображения", "оживление"), м.шаги)
        # Round 14: a single shot is not a series — no shared references (the keyframe count is the shot's).
        self.assertNotIn("генерация_изображения", м.штук)


class ОднаПетля(unittest.TestCase):
    """A loop is generated once at its own length; every version is assembly."""

    CASES = (
        ("Make one seamless 6-second gradient loop and deliver 15 s, 30 s and 60 s versions", 6.0, 60),
        ("Сделай зацикленный фон из частиц на 5 секунд и выдай версии на 10, 20 и 30 секунд", 5.0, 30),
        ("Looping smoke background for our three lobby screens, 20 s each", 8.0, 60),
        ("Бесшовная петля длиной 4 секунды для сайта, нужны три длины: 10, 20, 40 секунд", 4.0, 40),
    )

    def test_петля_один_прогон(self) -> None:
        for brief, loop_s, total in self.CASES:
            with self.subTest(brief=brief):
                п = _rewrite(brief, task="generate", inputs=[], outputs=["video"], shots=3, duration_s=total)
                self.assertEqual({"генерация_видео": (loop_s, loop_s)}, dict(п.step_seconds))
                self.assertEqual(1, п.route.штук["генерация_видео"])
                self.assertIn("loop_reuse", п.priors)
                self.assertIn(rc.ASSEMBLY_LOOP_VERSIONS, п.assembly)
                self.assertEqual(("генерация_видео",), п.shared)

    def test_без_петли_версии_генерируются(self) -> None:
        п = _rewrite("Three different 10 s product clips", task="generate", inputs=[], outputs=["video"], shots=3,
                     per_shot_s=10)
        self.assertEqual({}, dict(п.step_seconds))
        self.assertNotIn("loop_reuse", п.priors)

    def test_петля_в_плане_один_прогон_и_повтор_назван(self) -> None:
        answer = _plan(
            "Make one seamless 6-second gradient loop and deliver 15 s, 30 s and 60 s versions",
            task="generate", inputs=[], outputs=["video"], shots=3, duration_s=60, resolution="1080p", people=[],
        )
        шаг = answer["steps"][0]
        self.assertEqual(("генерация_видео", None), (шаг["step"], шаг.get("shots")))
        self.assertEqual(["генерация_видео"], [a["step"] for a in answer["shared_assets"]])


class ОбщиеАктивыВПлане(unittest.TestCase):
    def test_референсы_сериала_названы_общими(self) -> None:
        answer = _plan(
            "A 3-episode web series: a cat and a dog talk to each other, 6 shots an episode, English dialogue",
            task="generate", inputs=[], outputs=["video", "speech"], shots=18, per_shot_s=10, characters=2,
            languages=["en"], people=[],
        )
        общие = answer["shared_assets"]
        self.assertEqual(["генерация_изображения"], [a["step"] for a in общие])
        self.assertEqual((2, 18), (общие[0]["made"], общие[0]["reused_by"]))


# --- 2. required steps ----------------------------------------------------------------------


class КлонИНачитка(unittest.TestCase):
    """A clone endpoint that only creates the voice is followed by speech in that voice."""

    CASES = (
        ("Clone the voice from this 2-minute interview (speaker consents) and voice our 90-second explainer", "en", 90),
        ("Склонируй мой голос по 40-секундной записи и озвучь им 3 минуты текста", "ru", 180),
        ("Use my recorded sample to clone my voice, then read five 60-second product scripts with it", "en", 300),
        ("Сделай клон голоса диктора (он согласен) и начитай им лекцию на 4 минуты", "ru", 240),
    )

    def test_клон_затем_озвучка_его_линейки(self) -> None:
        for brief, lang, seconds in self.CASES:
            with self.subTest(brief=brief):
                answer = _plan(
                    brief, task="voice-clone", inputs=[A(60), T], outputs=["speech"], duration_s=seconds,
                    languages=[lang], people=[ME],
                )
                self.assertEqual(["клонирование_голоса", "озвучка"], _steps(answer))
                модели = _models(answer)
                self.assertEqual("minimax-voice-clone", модели["клонирование_голоса"])
                self.assertTrue(модели["озвучка"].startswith("minimax-"), модели["озвучка"])
                клон = answer["steps"][0]["chosen"]
                self.assertRegex(клон["price"], r"^1\.50 usd")
                self.assertNotRegex(клон["price"], r"chars|знак")
                self.assertEqual([], [ф for ф in клон.get("price_flags") or [] if "НИЖНЯЯ" in ф or "LOWER" in ф])

    def test_по_записи_реестра(self) -> None:
        реестр = ep.build(load_facts())
        self.assertFalse(pn.клон_читает_текст("minimax-voice-clone", реестр))
        self.assertTrue(pn.клон_читает_текст("xtts-v2", реестр))
        self.assertTrue(pn.клон_читает_текст("no-such-model-recorded", реестр))


class КадрИсходника(unittest.TestCase):
    """An edit of the customer's footage is delivered at the source frame."""

    CASES = (
        "Replace the red car with a blue one in our clip",
        "Замени машину на нашем ролике на синюю",
        "Swap the bottle in the shot for our new can",
        "Поменяй вывеску на здании в нашем ролике",
    )

    def test_4k_исходник_модель_720p_апскейл(self) -> None:
        for brief in self.CASES:
            with self.subTest(brief=brief):
                answer = _plan(
                    brief, task="video-edit", edit=["replace-object"], inputs=[V(8, "3840x2160")], outputs=["video"],
                    duration_s=8, people=[],
                )
                self.assertEqual(["правка_видео", "апскейл"], _steps(answer))

    def test_исходник_720p_апскейла_нет(self) -> None:
        answer = _plan(
            "Replace the red car with a blue one in our clip", task="video-edit", edit=["replace-object"],
            inputs=[V(8, "1280x720")], outputs=["video"], duration_s=8, people=[],
        )
        self.assertEqual(["правка_видео"], _steps(answer))


class ДиалогСериала(unittest.TestCase):
    """Characters talking on screen across episodes: lip sync in every speaking shot."""

    CASES = (
        ("A 3-episode web series: a cat and a dog talk to each other, English dialogue", 18, "en"),
        ("Мини-сериал: бабушка и внук разговаривают на кухне, 4 серии по 4 шота", 16, "ru"),
        ("Two hosts banter about tech news in a weekly animated show, 5 shots an episode", 10, "en"),
        ("Диалог двух роботов в каждой серии мультсериала, 3 серии по 3 шота", 9, "ru"),
    )

    def test_липсинк_в_каждом_шоте(self) -> None:
        for brief, shots, lang in self.CASES:
            with self.subTest(brief=brief):
                м = _route(brief, task="generate", inputs=[], outputs=["video", "speech"], shots=shots, per_shot_s=8,
                           characters=2, languages=[lang])
                self.assertIn("липсинк", м.шаги)
                self.assertEqual(shots, м.штук["липсинк"])

    def test_закадровый_рассказчик_без_губ(self) -> None:
        м = _route("A narrator voice-over tells the story of two foxes over 6 shots", task="generate", inputs=[],
                   outputs=["video", "speech"], shots=6, per_shot_s=8, characters=2, languages=["en"])
        self.assertNotIn("липсинк", м.шаги)


class КлипСИсполнителем(unittest.TestCase):
    """A music video with scenes and a recurring performer: reference, scenes, lip sync to the track."""

    CASES = (
        ("Music video for our song: the same singer performs in 8 scenes, singing on camera", "generate", 8),
        ("Клип на нашу песню: одна и та же певица в 10 сценах, поёт в кадр", "generate", 10),
        ("A rapper performs our track in 6 different locations, music video", "generate", 6),
        ("Клип: исполнитель поёт в кадр в 8 сценах", "music-visualiser", 8),
    )

    def test_референс_сцены_и_губы(self) -> None:
        for brief, task, shots in self.CASES:
            with self.subTest(brief=brief):
                м = _route(brief, task=task, inputs=[A(120)], outputs=["video"], shots=shots, duration_s=120)
                self.assertEqual(("генерация_изображения", "оживление", "липсинк"), м.шаги)
                self.assertEqual(shots, м.штук["липсинк"])

    def test_сцены_без_исполнителя_без_губ(self) -> None:
        м = _route("Music video of 6 landscape scenes, no people", task="generate", inputs=[A(90)], outputs=["video"],
                   shots=6, duration_s=90)
        self.assertNotIn("липсинк", м.шаги)
        self.assertNotIn("генерация_изображения", м.шаги)


# --- 3. edit before generate --------------------------------------------------------------------


class ТолькоМонтаж(unittest.TestCase):
    """Assembly-only edits: no model step, 0 usd, and no question when the input is there."""

    CASES = (
        ("Trim the first 10 seconds off my clip and speed it up 2x", {"task": "video-edit"}, ("trim", "speed")),
        ("Join these three clips into one and add our logo in the corner", {"task": "video-edit"}, ("concat", "logo-overlay")),
        ("Наложи водяной знак и LUT на наше 30-секундное видео", {"task": "video-edit"}, ("lut", "watermark")),
        ("Make it faster", {"task": "video-edit", "edit": ["speed-up", "cut"]}, ("speed", "trim")),
        ("Склей три наших ролика в один", {}, ("concat",)),
    )

    def test_монтаж_без_шагов(self) -> None:
        for brief, extra, edits in self.CASES:
            with self.subTest(brief=brief):
                spec = bs.with_defaults(_spec(inputs=[V(60)], outputs=["video"], **extra), ролик=True, текст=brief)
                self.assertEqual(set(edits), set(spec.edit))
                self.assertTrue(bs.монтаж_целиком(spec, brief))
                м = bs.route(spec)
                self.assertEqual((), м.шаги)
                self.assertEqual({bs.ASSEMBLY_ONLY_EDITS[e] for e in edits}, set(м.сборка))

    def test_приложенные_субтитры_без_расшифровки(self) -> None:
        м = _route("Burn the attached SRT subtitles into my 2-minute video", task="captions", inputs=[V(120), T],
                   outputs=["video"])
        self.assertEqual(((), (bs.NOTE_BURN_CAPTIONS,)), (м.шаги, м.сборка))

    def test_план_сразу_без_вопроса(self) -> None:
        for brief, spec in (
            ("Burn the attached SRT subtitles into my 2-minute video",
             {"task": "captions", "inputs": [V(120), T], "outputs": ["video"]}),
            ("Наложи водяной знак на наше видео", {"task": "video-edit", "inputs": [{"kind": "video", "owned": True}],
                                                "outputs": ["video"]}),
        ):
            with self.subTest(brief=brief):
                answer = _plan(brief, people=[], **spec)
                self.assertEqual(("только_монтаж", []), (answer["reason"], answer["steps"]))

    def test_удалить_водяной_знак_работа_модели(self) -> None:
        spec = bs.with_defaults(_spec(task="video-edit", edit=["remove-object"], inputs=[V(30)], outputs=["video"]),
                                ролик=True, текст="Remove the watermark from our clip")
        self.assertNotIn("watermark", spec.edit)
        self.assertIn("правка_видео", bs.route(spec).шаги)

    def test_чужая_правка_ошибка(self) -> None:
        _, errors = bs.parse_spec({"task": "video-edit", "edit": ["warp-drive"]})
        self.assertEqual(1, len(errors))


class Рефрейм(unittest.TestCase):
    """Reframe: a tracked crop when the target is not wider than the source; else outpaint."""

    def _crop(self, brief: str, aspect: str, res: str | None = None, **extra: Any) -> bool:
        spec = _spec(task="video-edit", edit=["reframe"], inputs=[V(30, res)], outputs=["video"], aspect=aspect, **extra)
        return bs.рефрейм_кадрированием(spec, brief)

    def test_кадрирование_и_дорисовка(self) -> None:
        cases = (
            ("Reframe our 45 s interview to 9:16 for TikTok", "9:16", "1920x1080", True),
            ("Сделай из нашего горизонтального ролика 16:9 вертикальную версию 9:16", "9:16", None, True),
            ("Turn our vertical phone clip into 16:9 widescreen", "16:9", "1080x1920", False),
            ("Crop our 16:9 webinar to a square, keep everyone in frame", "1:1", "1920x1080", False),
            ("Make a 4:5 version for Instagram", "4:5", None, True),
            ("Make a widescreen version of our clip", "16:9", None, False),
            ("Slightly wider cut", "1.8:1", "1920x1080", True),
            ("Make it 3:2", "3:2", "1080x1080", False),
        )
        for brief, aspect, res, crop in cases:
            with self.subTest(brief=brief):
                self.assertEqual(crop, self._crop(brief, aspect, res))

    def test_кадрирование_это_монтаж(self) -> None:
        м = _route("Reframe our interview to 9:16 for Reels", task="video-edit", edit=["reframe"],
                   inputs=[V(60, "1920x1080")], outputs=["video"], aspect="9:16")
        self.assertEqual(((), (bs.NOTE_CROP,)), (м.шаги, м.сборка))


# --- 4. scope -------------------------------------------------------------------------------------


class РеальноеВремя(unittest.TestCase):
    """Live work is a different product class: a recorded gap, never a batch plan."""

    LIVE = (
        ("A live AI avatar that talks with visitors on our kiosk in real time", {"task": "avatar", "outputs": ["video", "speech"]}),
        ("Аватар для стрима в реальном времени, отвечает зрителям голосом", {"task": "avatar", "outputs": ["video", "speech"]}),
        ("Live dubbing of our Zoom webinar into Spanish", {"task": "dub-translate", "outputs": ["video", "speech"]}),
        ("An avatar on our site that answers customers live", {"task": "avatar", "outputs": ["video", "speech"]}),
        ("No budget limits, the avatar must answer visitors in real time", {"task": "avatar", "outputs": ["video"]}),
    )
    RECORDED = (
        ("Live-action product ad with a presenter talking to camera", {"task": "avatar", "outputs": ["video", "speech"]}),
        ("It does not need to be real time: a recorded 60 s avatar video", {"task": "avatar", "outputs": ["video", "speech"]}),
        # Round 14: a speed word counts only with someone answered in session — the negation is judged there.
        ("It does not need to be real time: the avatar answers visitors in a recorded 60 s video",
         {"task": "avatar", "outputs": ["video", "speech"]}),
        ("Real-time strategy game trailer, 30 s", {"task": "generate", "outputs": ["video"]}),
        ("Dub our real-time strategy game trailer into German", {"task": "dub-translate", "outputs": ["video", "speech"]}),
        ("Translate the live recording of our concert into Spanish subtitles", {"task": "captions", "outputs": ["video"]}),
        ("Live dubbing of our webinar", {"task": "generate", "outputs": ["video"]}),
    )

    def test_живое_это_пробел(self) -> None:
        for brief, spec in self.LIVE:
            with self.subTest(brief=brief):
                self.assertTrue(realtime.applies(brief, spec))

    def test_записанное_не_пробел(self) -> None:
        for brief, spec in self.RECORDED:
            with self.subTest(brief=brief):
                self.assertFalse(realtime.applies(brief, spec))

    def test_варианты_из_базы(self) -> None:
        facts = [Fact(f"rt-model-{i}", "latency", f"~{i * 10}ms", "https://example.org", "vendor") for i in range(10)]
        self.assertEqual(8, len(realtime.options(facts)))
        пусто = realtime.gap("Live avatar", english=True, facts=[])
        self.assertEqual([], пусто["gap"]["realtime_options"])
        self.assertEqual(realtime.NONE_RECORDED[1], пусто["gap"]["realtime_options_note"])

    def test_план_пробел_с_вариантами(self) -> None:
        answer = _plan("A live AI avatar that talks with visitors on our kiosk in real time", task="avatar", inputs=[],
                       outputs=["video", "speech"], languages=["en"], people=[])
        self.assertEqual(("работа_не_поддерживается", [], "real-time"),
                         (answer["reason"], answer["steps"], answer["gap"]["job"]))
        self.assertIn("eleven_flash_v2_5", [r["model"] for r in answer["gap"]["realtime_options"]])


class ВидеоВЗвук(unittest.TestCase):
    """Sound for the customer's own video is a video-to-audio step."""

    CASES = (
        ("Generate a soundtrack that follows the action of my 20 s skateboard clip", {"task": "generate", "outputs": ["music"]}),
        ("Озвучь шумами наш немой 15-секундный ролик: шаги, ветер", {"task": "generate", "outputs": ["sfx"]}),
        ("Add foley to our 10 s clip", {"task": "video-edit", "outputs": ["video", "sfx"]}),
        ("Make sound effects for this silent video", {"outputs": ["sfx"]}),
    )

    def test_шаг_видео_в_звук(self) -> None:
        for brief, spec in self.CASES:
            with self.subTest(brief=brief):
                answer = _plan(brief, inputs=[V(15)], duration_s=15, people=[], **spec)
                self.assertEqual(["звук_по_видео"], _steps(answer))

    def test_фоновая_музыка_без_синхрона_это_музыка(self) -> None:
        п = _rewrite("Add calm background music to our wedding video", task="video-edit", inputs=[V(120)],
                     outputs=["video", "music"])
        self.assertEqual(("музыка",), п.route.шаги)

    def test_без_работы_звук_не_вопрос_а_речь_вопрос(self) -> None:
        for выход in ("sfx", "music"):
            поля = [н["field"] for н in bs.gaps({"inputs": [V(15)], "outputs": [выход], "duration_s": 15})[2]]
            self.assertNotIn("task", поля)
        поля = [н["field"] for н in bs.gaps({"inputs": [V(15)], "outputs": ["speech"], "duration_s": 15,
                                              "languages": ["en"]})[2]]
        self.assertIn("task", поля)


if __name__ == "__main__":
    unittest.main()
