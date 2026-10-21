"""Round 15 (spec-first decisions): every decision that was read from EN/RU brief words reads its SPEC FIELD first.

The product contract: the calling model fills `spec` (it reads any language) and the plan is
built from spec. The round-15 hidden set found the round 13-14 fixes working in EN/RU and
failing on the same intents written in zh, ja, ko, es, pt, de, fr — because the decision read
keyword lists. Each class below guards one decision, three ways:

(a) the spec field ALONE decides, with a brief in a language the keywords do not cover;
(b) the spec field wins over contradicting words, both ways;
(c) with the field absent, the EN/RU keyword fallback still decides.

The briefs are the fixer's own; none is a dev or holdout id. Expected values are literals (T2).
"""

from __future__ import annotations

import json
import os
import unittest
from typing import Any

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import edit_intent as ei  # noqa: E402
from studio import planner as pn  # noqa: E402
from studio import realtime  # noqa: E402
from studio.mcp import server  # noqa: E402
from studio.recipes import apply as rc  # noqa: E402
from studio.recipes import checklist as cl  # noqa: E402

T = {"kind": "text", "owned": True}
A = {"kind": "audio", "owned": True, "duration_s": 180}
V = {"kind": "video", "owned": True, "duration_s": 20}


def _spec(**raw: Any) -> bs.Spec:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    return spec


def _defaults(brief: str, **raw: Any) -> bs.Spec:
    return bs.with_defaults(_spec(**raw), ролик=True, текст=brief)


def _steps(brief: str, **raw: Any) -> tuple[str, ...]:
    return bs.route(_defaults(brief, **raw)).шаги


def _fired(brief: str, steps: list[str], **raw: Any) -> list[str]:
    return [i for i, _ in cl.fire(_spec(**raw), steps, text=brief)]


_PLANS: dict[str, dict] = {}


def _plan(brief: str, **spec: Any) -> dict:
    key = brief + json.dumps(spec, sort_keys=True, ensure_ascii=False)
    if key not in _PLANS:
        _PLANS[key] = json.loads(server.plan_pipeline(brief, spec=dict(spec)))
    return _PLANS[key]


def _note_ids(answer: dict) -> list[str]:
    return [n.get("id") for n in answer.get("production_notes") or []]


# --- 0. the fields themselves -------------------------------------------------------------------


class ПоляРазбираются(unittest.TestCase):
    """The new fields are typed and strict: an unknown value is a spec error naming the allowed list."""

    def test_значения(self) -> None:
        spec = _spec(
            outputs=[{"kind": "video", "loop": True}, {"kind": "image", "tileable": True}, "speech"],
            live=False, edit_target="text", cast_together=True, single_take_s=40, training_use=True,
            consistency=["light", "character"], dataset_count=500,
            people=[{"name": "Mimi", "real": False, "on_screen": True, "speaks": False}],
        )
        self.assertEqual(
            (("video", "image", "speech"), True, True, False, "text", True, 40.0, True, ("light", "character"), 500),
            (spec.outputs, spec.loop, spec.tileable, spec.live, spec.edit_target, spec.cast_together,
             spec.single_take_s, spec.training_use, spec.consistency, spec.dataset_count),
        )
        self.assertEqual((True, False), (spec.people[0]["on_screen"], spec.people[0]["speaks"]))
        self.assertEqual(({"kind": "video", "loop": True}, {"kind": "image", "tileable": True}), spec.output_items)

    def test_строгость(self) -> None:
        _, errors = bs.parse_spec({
            "outputs": [{"kind": "video", "loop": "yes", "fps": 30}], "edit_target": "sign", "consistency": ["mood"],
            "live": "maybe", "single_take_s": -3, "dataset_count": 2.5,
            "people": [{"name": "x", "real": False, "on_screen": 1}],
        })
        self.assertEqual(
            [
                "spec.outputs[0]: unknown field(s) fps (known: kind, loop, tileable, alpha, spatial)",
                "spec.outputs[0].loop='yes': must be true or false",
                "spec.people[0].on_screen=1: must be true or false",
                "spec.live='maybe': must be true or false",
                "spec.single_take_s=-3: must be a finite number above 0",
                "spec.dataset_count=2.5: must be a whole number",
                "spec.edit_target: sign not in text, person, object, background, sky, light, style",
                "spec.consistency: mood not in light, style, character",
            ],
            errors,
        )

    def test_петля_ложна_только_если_так_сказано_у_каждого(self) -> None:
        self.assertEqual((None, None), (_spec(outputs=["video"]).loop, _spec(outputs=["video"]).tileable))
        self.assertEqual(False, _spec(outputs=[{"kind": "video", "loop": False}]).loop)

    def test_эхо_называет_записи_выходов(self) -> None:
        echo = bs.echo(_spec(outputs=[{"kind": "video", "loop": True}], live=False))
        self.assertEqual({"value": ["video"], "from": "spec", "items": [{"kind": "video", "loop": True}]},
                         echo["fields"]["outputs"])
        self.assertEqual({"value": False, "from": "spec"}, echo["fields"]["live"])

    def test_описание_инструмента_называет_поля(self) -> None:
        doc = " ".join((server.plan_pipeline.__doc__ or "").split())
        for name in ("live", "edit_target", "{kind, loop?: bool, tileable?: bool, alpha?: bool}", "people[].on_screen / people[].speaks",
                     "cast_together", "single_take_s", "training_use", "consistency", "dataset_count"):
            self.assertIn(name, doc)
        for name in bs.DECISION_FIELDS:
            self.assertIn(name, bs.OPTIONAL_HELP)


# --- 1. live ----------------------------------------------------------------------------------------


class ЖивоеПоПолю(unittest.TestCase):
    AV = {"task": "avatar", "outputs": ["video", "speech"]}

    def test_поле_решает_на_любом_языке(self) -> None:
        for brief in (
            "访客在展台上和我们的虚拟形象实时对话",  # zh: visitors talk with our avatar in real time at the booth
            "ブースで来場者と会話するAIアバター",  # ja
            "Avatar que conversa con los visitantes de nuestro stand",  # es
        ):
            with self.subTest(brief=brief):
                self.assertEqual(True, realtime.applies(brief, {**self.AV, "live": True}))
                self.assertEqual(False, realtime.applies(brief, {**self.AV, "live": False}))

    def test_поле_старше_слов(self) -> None:
        self.assertEqual(False, realtime.applies("A live AI avatar host for our Twitch stream", {**self.AV, "live": False}))
        self.assertEqual(True, realtime.applies("Pre-rendered 60 s avatar clip of our host", {**self.AV, "live": True}))

    def test_без_речи_живое_не_пробел(self) -> None:
        self.assertEqual(False, realtime.applies("a live stream", {"task": "generate", "outputs": ["video"], "live": True}))

    def test_без_поля_слова(self) -> None:
        self.assertEqual(True, realtime.applies("A live AI avatar host for our Twitch stream", self.AV))
        self.assertEqual(True, realtime.applies("Ведущий-аватар для прямого эфира, отвечает зрителям", self.AV))
        self.assertEqual(False, realtime.applies("Pre-rendered 60 s avatar clip of our host", self.AV))

    def test_план_живое_пробел_по_полю(self) -> None:
        answer = _plan("访客在展台上和我们的虚拟形象实时对话", task="avatar", inputs=[T], outputs=["video", "speech"],
                       duration_s=60, languages=["zh"], people=[], live=True)
        self.assertEqual(("работа_не_поддерживается", "real-time"), (answer["reason"], answer["gap"]["job"]))


# --- 2. edit target -----------------------------------------------------------------------------


class ЦельПравки(unittest.TestCase):
    FR = dict(task="face-replace", inputs=[V], outputs=["video"], duration_s=20)

    def test_поле_решает_на_любом_языке(self) -> None:
        for brief in (
            "把视频里招牌上的字换成我们的新店名",  # zh: change the lettering on the sign to our new shop name
            "動画の看板の文字を新しい店名に変えて",  # ja
            "Cambia el letrero de la tienda en el vídeo por nuestro nuevo nombre",  # es
            "Ändere die Schrift auf dem Ladenschild im Video",  # de
        ):
            with self.subTest(brief=brief):
                spec = _spec(**self.FR, edit_target="text")
                rerouted, note = ei.reroute(spec, brief)
                self.assertEqual(("video-edit", ("replace-text",), ei.NOTE_EN), (rerouted.task, rerouted.edit, note))
                self.assertEqual(("face-replace", ""), (ei.reroute(_spec(**self.FR), brief)[0].task, ei.reroute(_spec(**self.FR), brief)[1]))

    def test_поле_старше_слов(self) -> None:
        brief = "Replace the text on the shop sign in our video"
        self.assertEqual(False, ei.wants_text_edit(_spec(**self.FR, edit_target="person"), brief))
        self.assertEqual(True, ei.wants_text_edit(_spec(**self.FR, edit_target="text"), "Swap the actor's face"))

    def test_без_поля_слова(self) -> None:
        self.assertEqual(True, ei.wants_text_edit(_spec(**self.FR), "Replace the text on the shop sign in our video"))
        self.assertEqual(True, ei.wants_text_edit(_spec(**self.FR), "Замените надпись на вывеске в нашем ролике"))
        self.assertEqual(False, ei.wants_text_edit(_spec(**self.FR), "Swap the actor's face with mine"))

    def test_план_правка_надписи(self) -> None:
        answer = _plan("把视频里招牌上的字换成我们的新店名", **self.FR, people=[], edit_target="text")
        self.assertEqual(["правка_видео"], [s["step"] for s in answer["steps"]])
        self.assertIn("text_edit_in_video", _note_ids(answer))


# --- 3. on-screen speaker, singer, series lip sync, visualiser ----------------------------------


SERIES = dict(task="generate", inputs=[], outputs=["video", "speech"], characters=2, shots=12, per_shot_s=5)
CATS = [{"name": "Mimi", "real": False, "on_screen": True, "speaks": True},
        {"name": "Momo", "real": False, "on_screen": True, "speaks": True}]
WITH_LIPS = ("генерация_изображения", "оживление", "озвучка", "липсинк")
NO_LIPS = ("генерация_изображения", "оживление", "озвучка")


class ГубыПоПолям(unittest.TestCase):
    """people[].on_screen / speaks and spec.lipsync decide the lip-sync step of a generated clip."""

    def test_серия_губы_на_любом_языке(self) -> None:
        for brief, lang in (
            ("アニメシリーズ：2匹の猫のキャラクター、各話1分", "ja"),
            ("두 고양이 캐릭터가 나오는 애니메이션 시리즈, 에피소드당 1분", "ko"),
            ("Série animée : deux chats, épisodes d'une minute", "fr"),
        ):
            with self.subTest(brief=brief):
                self.assertEqual(WITH_LIPS, _steps(brief, **SERIES, languages=[lang], people=CATS))
                self.assertEqual(WITH_LIPS, _steps(brief, **SERIES, languages=[lang], lipsync=True))
                self.assertEqual(NO_LIPS, _steps(brief, **SERIES, languages=[lang]))

    def test_губы_в_каждом_шоте(self) -> None:
        м = bs.route(_defaults("アニメシリーズ", **SERIES, languages=["ja"], people=CATS))
        self.assertEqual(12, м.штук["липсинк"])

    def test_поле_старше_слов(self) -> None:
        brief = "Animated series: two cats talk to each other"
        off = [{**c, "on_screen": False} for c in CATS]
        self.assertEqual(("генерация_изображения", "редактирование_изображения", "оживление", "озвучка"),
                         _steps(brief, **SERIES, languages=["en"], people=off))
        self.assertEqual(("генерация_изображения", "редактирование_изображения", "оживление", "озвучка"),
                         _steps(brief, **SERIES, languages=["en"], lipsync=False))
        self.assertEqual(WITH_LIPS, _steps("Animated series: two cats, no dialogue", **SERIES, languages=["en"], people=CATS))

    def test_без_поля_слова(self) -> None:
        self.assertEqual(("генерация_изображения", "редактирование_изображения", "оживление", "озвучка", "липсинк"),
                         _steps("Animated series: two characters talk to each other", **SERIES, languages=["en"]))
        self.assertEqual(NO_LIPS, _steps("Serie animada: dos personajes", **SERIES, languages=["es"]))

    def test_короткий_клип_голос_модели_по_полю(self) -> None:
        """An 8 s clip: someone speaking on screen -> native audio (the video model makes voice and lips)."""
        clip = dict(task="generate", inputs=[], outputs=["video", "speech"], duration_s=8, languages=["zh"])
        chef = [{"name": "chef", "real": False, "on_screen": True, "speaks": True}]
        self.assertEqual("native", _defaults("厨师对着镜头说欢迎光临", **clip, people=chef).audio)
        self.assertEqual("voiceover", _defaults("厨师对着镜头说欢迎光临", **clip).audio)
        mute = [{**chef[0], "speaks": False}]
        en = {**clip, "languages": ["en"]}
        self.assertEqual("voiceover", _defaults("8 seconds: a chef says 'welcome'", **en, people=mute).audio)
        self.assertEqual("native", _defaults("8 seconds: a chef says 'welcome'", **en).audio)

    def test_молчащий_в_кадре_без_губ(self) -> None:
        mute = [{"name": "host", "real": False, "on_screen": True, "speaks": False}]
        spec = _defaults("A presenter explains our app", task="generate", inputs=[], outputs=["video", "speech"],
                         duration_s=40, languages=["en"], people=mute)
        self.assertEqual((False, "voiceover"), (spec.speaker_on_screen, spec.audio))


VIS = dict(task="music-visualiser", inputs=[A], outputs=["video"], duration_s=180, shots=6)


class ВизуализаторБезГуб(unittest.TestCase):
    def test_липсинк_запрещён_полем_на_любом_языке(self) -> None:
        for brief in (
            "音乐可视化，不要对口型（lip sync），只要抽象图形",  # zh
            "Visualizador para nuestra canción: nada de lip sync, la cantante no aparece",  # es
            "Visualizador para a nossa música, a cantora canta sem aparecer",  # pt
        ):
            with self.subTest(brief=brief):
                self.assertEqual(("генерация_видео",), _steps(brief, **VIS, people=[], lipsync=False))

    def test_исполнитель_не_в_кадре_полем(self) -> None:
        singer = [{"name": "our singer", "real": True, "public_figure": False, "consent": "stated", "claim": "none",
                   "on_screen": False, "speaks": True}]
        self.assertEqual(("генерация_видео",), _steps("Visualiseur pour la chanson de notre chanteuse", **VIS, people=singer))
        spec = _defaults("Visualizer für den Song unserer Sängerin", task="generate", inputs=[A], outputs=["video"],
                         duration_s=180, shots=6, people=singer)
        self.assertEqual(("music-visualiser", None, False), (spec.task, spec.characters, spec.speaker_on_screen))

    def test_исполнитель_в_кадре_полем(self) -> None:
        """people[].on_screen decides the performer reference: zh words alone name nobody; EN words lose to the field."""
        clip = dict(task="generate", inputs=[A], outputs=["video"], duration_s=120, shots=6)
        dancer = {"name": "our singer", "real": True, "public_figure": False, "consent": "stated", "claim": "none",
                  "speaks": False}
        self.assertEqual(STRAIGHT, _steps("我们歌曲的MV，六个场景", **clip, people=[{**dancer, "on_screen": True}]))
        self.assertEqual(("генерация_видео",), _steps("我们歌曲的MV，六个场景", **clip, people=[dancer]))
        self.assertEqual(("генерация_видео",), _steps("Music video: the singer performs our song in 6 scenes", **clip,
                                                      people=[{**dancer, "on_screen": False}]))
        self.assertEqual(STRAIGHT, _steps("Music video: the singer performs our song in 6 scenes", **clip,
                                          people=[dancer]))

    def test_поле_старше_слов(self) -> None:
        # lipsync=false: the singer named in words stays a performer on screen, but nobody's lips move.
        self.assertEqual(("генерация_изображения", "оживление"),
                         _steps("Music video: the singer sings on camera in 6 scenes", **VIS, lipsync=False))
        self.assertEqual(("генерация_изображения", "оживление", "липсинк"),
                         _steps("Abstract visuals for our track", task="generate", inputs=[A], outputs=["video"],
                                duration_s=180, shots=6, lipsync=True))

    def test_без_поля_слова(self) -> None:
        self.assertEqual(("генерация_видео",), _steps("Visualizer for our song, no lip sync, just shapes", **VIS, people=[]))
        self.assertEqual(("генерация_видео",), _steps("Визуализатор для трека, без липсинка, только формы", **VIS, people=[]))
        self.assertEqual(("генерация_изображения", "оживление", "липсинк"),
                         _steps("Music video for our song: the singer sings on camera in 6 scenes", task="generate",
                                inputs=[A], outputs=["video"], duration_s=120, shots=6))


# --- 4. cast together ---------------------------------------------------------------------------


KEYFRAMES = ("генерация_изображения", "редактирование_изображения", "оживление")
STRAIGHT = ("генерация_изображения", "оживление")
CAST = dict(task="generate", inputs=[], outputs=["video"], characters=2, shots=6, per_shot_s=5)


class КадрНаДвоих(unittest.TestCase):
    def test_поле_решает_на_любом_языке(self) -> None:
        for brief in ("骑士和龙在每个镜头里", "기사와 용이 매 장면에", "Ein Ritter und ein Drache in jeder Szene"):
            with self.subTest(brief=brief):
                self.assertEqual(KEYFRAMES, _steps(brief, **CAST, cast_together=True))
                self.assertEqual(STRAIGHT, _steps(brief, **CAST))

    def test_поле_старше_слов(self) -> None:
        self.assertEqual(STRAIGHT, _steps("A knight and a dragon fight across the series", **CAST, cast_together=False))
        self.assertEqual(KEYFRAMES, _steps("A series with a fox and an owl, no dialogue", **CAST, cast_together=True))

    def test_без_поля_слова(self) -> None:
        self.assertEqual(KEYFRAMES, _steps("A knight and a dragon fight across the series", **CAST))
        self.assertEqual(KEYFRAMES, _steps("Бабушка и внук разговаривают на кухне", **CAST))
        self.assertEqual(STRAIGHT, _steps("Сериал про двух котов", **CAST))


# --- 5. single take ------------------------------------------------------------------------------


GEN = dict(task="generate", inputs=[], outputs=["video"], people=[])


class ДлинаДубля(unittest.TestCase):
    def test_поле_решает_на_любом_языке(self) -> None:
        for brief in ("一个40秒的一镜到底长镜头", "40초짜리 원테이크 장면이 들어간 2분 광고", "Plano secuencia de 40 segundos"):
            with self.subTest(brief=brief):
                spec = _spec(**GEN, duration_s=120, shots=8, single_take_s=40)
                self.assertEqual([("single_take_limit", {"seconds": "40"})],
                                 [(i, f) for i, f in cl.fire(spec, ["генерация_видео"], text=brief) if i == "single_take_limit"])
                self.assertNotIn("single_take_limit", _fired(brief, ["генерация_видео"], **GEN, duration_s=120, shots=8))

    def test_поле_старше_длины_шота(self) -> None:
        self.assertNotIn("single_take_limit", _fired("one 40 s shot", ["генерация_видео"], **GEN, duration_s=40, shots=1,
                                                       single_take_s=8))
        self.assertIn("single_take_limit", _fired("x", ["генерация_видео"], **GEN, duration_s=40, shots=8, single_take_s=20))

    def test_без_поля_длина_шота(self) -> None:
        self.assertIn("single_take_limit", _fired("one 40 s shot", ["генерация_видео"], **GEN, duration_s=40, shots=1))
        self.assertNotIn("single_take_limit", _fired("eight shots", ["генерация_видео"], **GEN, duration_s=40, shots=8))


# --- 6. training use, face-swap data set ---------------------------------------------------------


IMG = dict(task="generate", inputs=[], outputs=["image"], shots=40, people=[])
FS = dict(task="face-replace", inputs=[{"kind": "image", "owned": True, "count": 3}], outputs=["image"], people=[])


class Обучение(unittest.TestCase):
    def test_поле_решает_на_любом_языке(self) -> None:
        for brief in ("生成40张货架图片，用来训练我们的检测模型", "棚の画像を40枚、検出モデルの学習用に",
                      "40 imagens de prateleiras para treinar o nosso detector"):
            with self.subTest(brief=brief):
                self.assertIn("outputs_as_training_data", _fired(brief, ["генерация_изображения"], **IMG, training_use=True))
                self.assertNotIn("outputs_as_training_data", _fired(brief, ["генерация_изображения"], **IMG))

    def test_поле_старше_слов(self) -> None:
        self.assertNotIn("outputs_as_training_data", _fired("40 shelf images to train our detector model",
                                                              ["генерация_изображения"], **IMG, training_use=False))
        self.assertIn("outputs_as_training_data", _fired("40 shelf images for our catalogue", ["генерация_изображения"],
                                                          **IMG, training_use=True))

    def test_без_поля_слова(self) -> None:
        self.assertIn("outputs_as_training_data", _fired("40 shelf images to train our detector model",
                                                          ["генерация_изображения"], **IMG))
        self.assertIn("outputs_as_training_data", _fired("40 картинок полок для обучения нейросети",
                                                          ["генерация_изображения"], **IMG))
        self.assertNotIn("outputs_as_training_data", _fired("40 shelf images for our catalogue", ["генерация_изображения"], **IMG))


class ДатасетЗаменыЛиц(unittest.TestCase):
    def test_поле_решает_на_любом_языке(self) -> None:
        for brief in ("换脸数据集：三位志愿者的脸", "Datensatz mit Gesichtstausch aus drei Freiwilligen"):
            with self.subTest(brief=brief):
                spec = _spec(**FS, dataset_count=500)
                self.assertEqual(500, bs.face_swap_items(spec))
                self.assertEqual([("face_swap_dataset_consent", {"n": "500"})],
                                 [(i, f) for i, f in cl.fire(spec, ["замена_лица_изображения"], text=brief)
                                  if i == "face_swap_dataset_consent"])
                self.assertIn("face_swap_dataset_consent",
                              _fired(brief, ["замена_лица_изображения"], **FS, training_use=True))
                self.assertNotIn("face_swap_dataset_consent", _fired(brief, ["замена_лица_изображения"], **FS))

    def test_малый_датасет_полем(self) -> None:
        spec = _spec(**FS, dataset_count=12)
        self.assertEqual([("face_swap_dataset_consent", {"n": "12"})],
                         [(i, f) for i, f in cl.fire(spec, ["замена_лица_изображения"], text="换脸数据集")
                          if i == "face_swap_dataset_consent"])

    def test_поле_старше_слов(self) -> None:
        self.assertNotIn("face_swap_dataset_consent", _fired("face swap for our detector's training data",
                                                               ["замена_лица_изображения"], **FS, training_use=False))

    def test_без_поля_слова_и_счёт(self) -> None:
        self.assertIn("face_swap_dataset_consent", _fired("face swap for our detector's training data",
                                                           ["замена_лица_изображения"], **FS))
        self.assertIn("face_swap_dataset_consent", _fired("x", ["замена_лица_изображения"], **{**FS, "shots": 40}))
        self.assertEqual(0, bs.face_swap_items(_spec(**FS)))

    def test_план_датасета_с_ценой(self) -> None:
        answer = _plan("换脸数据集：三位志愿者的脸换到图片上", **FS, dataset_count=500)
        step = answer["steps"][0]
        self.assertEqual("замена_лица_изображения", step["step"])
        self.assertRegex(step["chosen"]["price"], r"\b500 image\(s\)")


# --- 7. consistency -------------------------------------------------------------------------------


class Постоянство(unittest.TestCase):
    SHOTS = dict(task="generate", inputs=[], outputs=["video"], duration_s=40, shots=8, people=[])

    def test_свет_полем_на_любом_языке(self) -> None:
        for brief in ("8个镜头的广告", "8カットの広告", "Anuncio de 8 planos"):
            with self.subTest(brief=brief):
                self.assertIn("relight_limits", _fired(brief, ["генерация_видео"], **self.SHOTS, consistency=["light"]))
                self.assertNotIn("relight_limits", _fired(brief, ["генерация_видео"], **self.SHOTS))

    def test_поле_старше_слов(self) -> None:
        brief = "8 shots, keep the lighting consistent across all shots"
        self.assertNotIn("relight_limits", _fired(brief, ["генерация_видео"], **self.SHOTS, consistency=["character"]))
        self.assertIn("relight_limits", _fired("8 shots of a beach", ["генерация_видео"], **self.SHOTS, consistency=["light"]))

    def test_без_поля_слова(self) -> None:
        self.assertIn("relight_limits", _fired("8 shots, keep the lighting consistent across all shots",
                                                ["генерация_видео"], **self.SHOTS))
        self.assertIn("relight_limits", _fired("8 шотов, свет везде одинаковый", ["генерация_видео"], **self.SHOTS))
        self.assertNotIn("relight_limits", _fired("8 shots of a beach", ["генерация_видео"], **self.SHOTS))

    def test_персонаж_полем(self) -> None:
        images = dict(task="generate", inputs=[], outputs=["image"], shots=20, people=[])
        self.assertEqual(1, _defaults("我们吉祥物猫的20张图片", **images, consistency=["character"]).characters)
        self.assertEqual(None, _defaults("我们吉祥物猫的20张图片", **images).characters)
        self.assertEqual(None, _defaults("20 pictures of our cat mascot, the same cat everywhere", **images,
                                         consistency=["light"]).characters)
        self.assertEqual(1, _defaults("20 pictures of our cat mascot, the same cat everywhere", **images).characters)


# --- 8. loop -------------------------------------------------------------------------------------


class Петля(unittest.TestCase):
    LOOP = dict(task="generate", inputs=[], outputs=[{"kind": "video", "loop": True}], duration_s=60, people=[])
    PLAIN = dict(task="generate", inputs=[], outputs=["video"], duration_s=60, people=[])

    def test_поле_решает_на_любом_языке(self) -> None:
        for brief in ("大堂屏幕用的海浪视频，60秒", "ロビー画面用の波の映像、60秒", "Vídeo de olas para la pantalla del vestíbulo"):
            with self.subTest(brief=brief):
                self.assertIn("seamless_loop", _fired(brief, ["генерация_видео"], **self.LOOP))
                self.assertEqual(float(rc.LOOP_CLIP_S), rc.loop_seconds(_spec(**self.LOOP), brief))
                self.assertNotIn("seamless_loop", _fired(brief, ["генерация_видео"], **self.PLAIN))
                self.assertEqual(None, rc.loop_seconds(_spec(**self.PLAIN), brief))

    def test_поле_старше_слов(self) -> None:
        off = {**self.PLAIN, "outputs": [{"kind": "video", "loop": False}]}
        self.assertNotIn("seamless_loop", _fired("a seamless loop of waves", ["генерация_видео"], **off))
        self.assertEqual(None, rc.loop_seconds(_spec(**off), "a seamless loop of waves"))

    def test_без_поля_слова(self) -> None:
        self.assertIn("seamless_loop", _fired("a seamless loop of waves", ["генерация_видео"], **self.PLAIN))
        self.assertEqual(6.0, rc.loop_seconds(_spec(**self.PLAIN), "a 6-second loop of waves"))
        self.assertIn("seamless_loop", _fired("зацикленное видео волн", ["генерация_видео"], **self.PLAIN))


class Прозрачность(unittest.TestCase):
    """outputs[].alpha decides a transparent background (the alpha-upscaler choice, the delivery format)."""

    def test_поле_решает_на_любом_языке(self) -> None:
        for brief in ("透明背景的产品图", "透過背景の商品画像", "Produktbild mit durchsichtigem Hintergrund"):
            with self.subTest(brief=brief):
                self.assertEqual(True, rc.wants_alpha(_spec(outputs=[{"kind": "image", "alpha": True}]), brief))
                self.assertEqual(False, rc.wants_alpha(_spec(outputs=["image"]), brief))

    def test_поле_старше_слов(self) -> None:
        self.assertEqual(False, rc.wants_alpha(_spec(outputs=[{"kind": "image", "alpha": False}]),
                                               "product shot on a transparent background, PNG"))
        self.assertEqual(True, rc.wants_alpha(_spec(outputs=[{"kind": "video", "alpha": True}]),
                                              "our singer for a Pepper's ghost hologram stage"))

    def test_без_поля_слова(self) -> None:
        self.assertEqual(True, rc.wants_alpha(_spec(outputs=["image"]), "product shot on a transparent background, PNG"))
        self.assertEqual(True, rc.wants_alpha(_spec(outputs=["image"]), "товар на прозрачном фоне"))
        self.assertEqual(False, rc.wants_alpha(_spec(outputs=["image"]), "a perfume bottle made of transparent glass"))


class ЧислоКартинок(unittest.TestCase):
    """spec.shots decides how many pictures are priced; "6 images" in the words only when it is absent."""

    IMG = dict(task="generate", inputs=[], outputs=["image"], people=[])

    @staticmethod
    def _price(answer: dict) -> str:
        return str(answer["steps"][0]["chosen"]["price"])

    def test_поле_решает_на_любом_языке(self) -> None:
        self.assertRegex(self._price(_plan("我们咖啡杯的产品图", **self.IMG, shots=6)), r"\b6 image\(s\)")

    def test_поле_старше_слов(self) -> None:
        answer = _plan("6 images of our coffee mug on a table", **self.IMG, shots=2)
        self.assertRegex(self._price(answer), r"\b2 image\(s\)")
        self.assertEqual(2, answer["steps"][0]["shots"])
        self.assertEqual(None, pn.кадров_словами(_spec(**self.IMG, shots=2), "6 images of our coffee mug"))

    def test_без_поля_слова(self) -> None:
        answer = json.loads(server.план_по_тексту("6 images of our coffee mug on a table", spec=dict(self.IMG)))
        self.assertRegex(self._price(answer), r"\b6 image\(s\)")
        self.assertEqual(6, pn.кадров_словами(_spec(**self.IMG), "6 images of our coffee mug"))
        self.assertEqual(4, pn.кадров_словами(_spec(**self.IMG), "4 картинки кружки"))


# --- 9. audience (existing field) -----------------------------------------------------------------


class Зритель(unittest.TestCase):
    GEN = dict(task="generate", inputs=[], outputs=["video"], duration_s=60, people=[])

    def test_поле_решает_на_любом_языке(self) -> None:
        for brief in ("幼儿园的儿歌动画", "Animación de canciones infantiles para preescolar"):
            with self.subTest(brief=brief):
                self.assertIn("made_for_kids", _fired(brief, ["генерация_видео"], **self.GEN, audience="children"))

    def test_поле_старше_слов(self) -> None:
        self.assertNotIn("made_for_kids", _fired("a video about how kids learn, for parents", ["генерация_видео"],
                                                 **self.GEN, audience="adults"))
        self.assertIn("made_for_kids", _fired("a cartoon about planets", ["генерация_видео"], **self.GEN,
                                              audience="children"))

    def test_без_поля_слова(self) -> None:
        self.assertIn("made_for_kids", _fired("a cartoon for kids about planets", ["генерация_видео"], **self.GEN))
        self.assertIn("made_for_kids", _fired("мультфильм для детей про планеты", ["генерация_видео"], **self.GEN))


# --- 10. the station's own presenter: decided by spec in any language ----------------------------


AV = {"task": "avatar", "inputs": [T], "outputs": ["video"], "duration_s": 45, "jurisdiction": ["US"]}
SYN = {"name": "Skye", "real": False}
OWN_REAL = {"type": "news", "fabricated": False, "real_brand": True, "own_brand": True, "brand": "KXTV 5"}


class СвойВедущийНаЛюбомЯзыке(unittest.TestCase):
    def test_синтетический_ведущий_план(self) -> None:
        for brief, lang in (
            ("KXTV 5新闻希望由完全AI生成的天气主持人（不是真人）播报我们气象学家撰写的预报", "zh"),
            ("KXTV 5 뉴스는 AI로 만든 가상 날씨 진행자가 우리 기상팀의 예보를 읽기를 원합니다", "ko"),
            ("KXTV 5 Noticias quiere una presentadora del tiempo generada por IA que lea nuestro pronóstico", "es"),
        ):
            with self.subTest(brief=brief):
                answer = _plan(brief, **AV, languages=[lang], people=[SYN], claims=[OWN_REAL])
                self.assertEqual("allow", answer["synthetic_presenter"]["decision"])
                self.assertIn("synthetic_presenter_disclosure", _note_ids(answer))

    def test_чужой_канал_отказ_на_любом_языке(self) -> None:
        answer = _plan("KXTV 5新闻希望由完全AI生成的天气主持人播报预报", **AV, languages=["zh"], people=[SYN],
                       claims=[{**OWN_REAL, "own_brand": False}])
        self.assertEqual(("fail", []), (answer["outcome"], answer["steps"]))


# --- 11. the spec question proposes the decision fields ------------------------------------------


class ЧерновикПредлагаетПоля(unittest.TestCase):
    def test_вопрос_называет_поля_решений(self) -> None:
        answer = json.loads(server.plan_pipeline("两只猫在30秒的循环视频里互相说话"))
        self.assertEqual("нужна_спецификация", answer["reason"])
        fields = answer["spec_needed"]["draft"]["decision_fields"]
        self.assertEqual(list(bs.DECISION_FIELDS), [f["field"] for f in fields])
        self.assertEqual([None] * len(bs.DECISION_FIELDS), [f["read_from_text"] for f in fields])
        for name in bs.DECISION_FIELDS:
            self.assertIn(name, answer["spec_needed"]["allowed"])
        self.assertIn("draft.decision_fields", answer["spec_needed"]["instruction"])

    def test_слова_подсказывают(self) -> None:
        # Round 16 fields are cased in `test_round16_spec` / `test_round16_integration`.
        got = {f["field"]: f["read_from_text"] for f in bs.decision_fields(
            "A live avatar; replace the text on the sign; a seamless loop; training data; no lip sync; "
            "keep the lighting consistent")
            if f["field"] not in (*bs.DECISION_FIELDS_R16, *bs.DECISION_FIELDS_R16_OUTPUTS, *bs.DECISION_FIELDS_R17,
                              *bs.DECISION_FIELDS_R18)}
        self.assertEqual(
            {"live": True, "edit_target": "text", "outputs[].loop": True, "outputs[].tileable": None, "outputs[].alpha": None,
             "people[].on_screen": None, "people[].speaks": None, "lipsync": False, "cast_together": None,
             "single_take_s": None, "training_use": True, "consistency": ["light"], "dataset_count": None},
            got,
        )

    def test_названные_поля_не_предлагаются(self) -> None:
        names = [f["field"] for f in bs.decision_fields("x", {"live": False, "lipsync": True, "outputs": ["video"]})]
        self.assertNotIn("live", names)
        self.assertNotIn("lipsync", names)
        self.assertIn("outputs[].loop", names)


if __name__ == "__main__":
    unittest.main()
