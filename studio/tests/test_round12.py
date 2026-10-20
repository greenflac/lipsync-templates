"""Round 12: general themes from the hidden holdout, on the fixer's own EN/RU paraphrases.

Each class guards one category, never a dev or holdout id:

* COMPOSITION — every ordered output is made by some step: narration over
  restored / colourised / upscaled footage, lip sync for an on-screen speaker,
  and an output no step makes is a question, never a silent drop;
* UNPRICED STEPS — a compute-second rate without a recorded ratio and a rate for
  a lower frame rate give a LOWER BOUND, and the plan still shows a clip price;
* NICHE ROUTES — a property walkthrough from photos (camera path, not motion
  transfer), a drawn-footage dub (lip sync on a stylised-face model, round 15), a local dub chain;
* DECISIVE OUTCOMES — a real broadcaster's marks on fabricated or parody news
  are refused; a visualiser without its track and a lip-sync order without
  footage plan instead of asking.

Expected values are literals (T2).
"""

from __future__ import annotations

import json
import os
import unittest
from typing import Any

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import broadcast_marks as bm  # noqa: E402
from studio import pricing  # noqa: E402
from studio.mcp import server  # noqa: E402
from studio.recipes import apply as rc  # noqa: E402

V = {"kind": "video", "owned": True, "duration_s": 60}
T = {"kind": "text", "owned": True}


def _spec(**raw: Any) -> bs.Spec:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    return spec


def _route(brief: str, **raw: Any) -> bs.Маршрут:
    return bs.route(bs.with_defaults(_spec(**raw), ролик=True, текст=brief))


def _rewrite(brief: str, **raw: Any) -> rc.Applied:
    spec = bs.with_defaults(_spec(**raw), ролик=True, текст=brief)
    return rc.rewrite(spec, bs.route(spec), brief)


def _plan(brief: str, **spec: Any) -> dict:
    return json.loads(server.plan_pipeline(brief, spec=dict(spec)))


def _steps(answer: dict) -> list[str]:
    return [str(s.get("step")) for s in answer.get("steps") or []]


def _models(answer: dict) -> dict[str, str]:
    return {str(s.get("step")): str((s.get("chosen") or {}).get("model") or "") for s in answer.get("steps") or []}


class СоставВыходов(unittest.TestCase):
    """Two jobs in one order: the second job's output is not dropped."""

    def test_реставрация_и_диктор(self) -> None:
        м = _route(
            "Restore my grandfather's 1950s reel and add a warm English narration",
            task="restore", inputs=[V, T], outputs=["video", "speech"], duration_s=60, audio="voiceover", languages=["en"],
        )
        self.assertEqual(("реставрация", "озвучка"), м.шаги)
        self.assertIn(bs.NOTE_NARRATION_MIX, м.сборка)

    def test_раскраска_и_закадровый_голос_ru(self) -> None:
        м = _route(
            "Раскрась чёрно-белую хронику и наложи голос диктора",
            task="colorize", inputs=[V], outputs=["video", "speech"], duration_s=45, audio="voiceover", languages=["ru"],
        )
        self.assertEqual(("раскраска", "озвучка"), м.шаги)

    def test_апскейл_музыка_и_голос(self) -> None:
        м = _route(
            "Апскейл старого видео до 4K, добавь музыку и закадровый текст",
            task="upscale", inputs=[V], outputs=["video", "speech", "music"], duration_s=30, audio="voiceover", languages=["ru"],
        )
        self.assertEqual(("апскейл", "озвучка", "музыка"), м.шаги)

    def test_нарезка_оставляет_свою_речь(self) -> None:
        м = _route(
            "Cut my podcast video into a 3-minute highlight with music",
            task="cut-to-shorts", inputs=[{"kind": "video", "owned": True, "duration_s": 3600}],
            outputs=["video", "music", "speech"], shots=1, per_shot_s=180, languages=["en"],
        )
        self.assertEqual(("расшифровка", "музыка"), м.шаги)

    def test_своя_запись_голоса_не_синтезируется(self) -> None:
        м = _route(
            "Restore the film and lay my recorded narration over it",
            task="restore", inputs=[V, {"kind": "audio", "owned": True, "duration_s": 60}], outputs=["video", "speech"],
            duration_s=60, languages=["en"],
        )
        self.assertEqual(("реставрация",), м.шаги)

    def test_свой_трек_не_генерируется(self) -> None:
        м = _route(
            "Restore my old film and put my own music track under it",
            task="restore", inputs=[V, {"kind": "audio", "owned": True, "duration_s": 60}], outputs=["video", "music"],
            duration_s=60,
        )
        self.assertEqual(("реставрация",), м.шаги)

    def test_выход_без_шага_вопрос(self) -> None:
        м = _route(
            "Transcribe my podcast recording and give me a video of it",
            task="transcribe", inputs=[{"kind": "audio", "owned": True, "duration_s": 600}], outputs=["text", "video"],
            languages=["en"],
        )
        self.assertIsNotNone(м.нехватка)
        assert м.нехватка is not None
        self.assertEqual("выход_без_шага", м.нехватка[0])

    def test_снимок_оживляется_когда_заказано_видео(self) -> None:
        м = _route(
            "Restore my grandmother's photo and make it move",
            task="restore", inputs=[{"kind": "image", "owned": True}], outputs=["video"], duration_s=5,
        )
        self.assertEqual(("реставрация_изображения", "оживление"), м.шаги)


class ГоворящийВКадре(unittest.TestCase):
    """A seen speaker gets lip sync; an off-screen narrator does not."""

    def _генерация(self, brief: str, **extra: Any) -> bs.Маршрут:
        raw: dict[str, Any] = {
            "task": "generate", "inputs": [], "outputs": ["video", "speech"], "duration_s": 40, "languages": ["en"],
        }
        raw.update(extra)
        return _route(brief, **raw)

    def test_сатира_с_ведущим(self) -> None:
        м = self._генерация("30-second satirical explainer where a cartoon fox presenter talks to camera about inflation",
                            characters=1, audio="voiceover")
        self.assertIn("липсинк", м.шаги)

    def test_объяснялка_профессор_в_кадре_ru(self) -> None:
        м = self._генерация("Объясняющий ролик: выдуманный профессор в кадре рассказывает про фотосинтез",
                            languages=["ru"], people=[{"name": "профессор", "real": False}])
        self.assertIn("липсинк", м.шаги)

    def test_персонаж_говорит(self) -> None:
        м = self._генерация("A grumpy robot character says why Mondays are bad", characters=1)
        self.assertIn("липсинк", м.шаги)

    def test_ведущий_в_камеру_без_персонажа(self) -> None:
        м = self._генерация("An on-camera host walks through our app features")
        self.assertIn("липсинк", м.шаги)

    def test_закадровый_диктор_без_губ(self) -> None:
        м = self._генерация("Explainer about our app with a calm narrator voice-over over product shots")
        self.assertNotIn("липсинк", м.шаги)

    def test_глагол_без_персонажа_без_губ(self) -> None:
        м = self._генерация("A video that tells customers about our new app features")
        self.assertNotIn("липсинк", м.шаги)


class НижняяГраница(unittest.TestCase):
    """An unpriced step gets a lower bound, labelled as such."""

    def test_секунда_вычисления_по_оценке(self) -> None:
        ставки = pricing.rates("$0.0013 per compute second", "price_unit_second_usd")
        (о,) = pricing.estimate(ставки, pricing.Need(seconds=20.0))
        self.assertEqual(0.026, о.usd)
        self.assertEqual(pricing.LOWER_BOUND_COMPUTE, о.lower_bound)

    def test_записанное_отношение_не_граница(self) -> None:
        ставки = pricing.rates("$0.0013 per compute second", "price_unit_second_usd")
        (о,) = pricing.estimate(ставки, pricing.Need(seconds=20.0, compute_ratio=2.0))
        self.assertEqual(0.052, о.usd)
        self.assertFalse(о.lower_bound)

    def test_ставка_за_меньшую_частоту(self) -> None:
        ставки = pricing.rates("60fps: $0.05 per second", "price")
        (о,) = pricing.estimate(ставки, pricing.Need(seconds=10.0, fps=120.0))
        self.assertEqual(0.5, о.usd)
        self.assertEqual(pricing.LOWER_BOUND_FPS, о.lower_bound)

    def test_годная_частота_не_граница(self) -> None:
        ставки = pricing.rates("60fps: $0.05 per second", "price")
        (о,) = pricing.estimate(ставки, pricing.Need(seconds=10.0, fps=60.0))
        self.assertFalse(о.lower_bound)

    def test_интерполяция_120_fps_с_ценой_ролика_ru(self) -> None:
        ответ = _plan(
            "Плавное слоумо: интерполяция кадров моего ролика с 30 до 120 к/с, 10 секунд",
            task="interpolate", inputs=[{"kind": "video", "owned": True, "duration_s": 10}], outputs=["video"],
            duration_s=10, fps=120, people=[],
        )
        цена = ответ["pipeline_price"]
        self.assertIsNotNone(цена.get("за_ролик"))
        self.assertTrue(цена["смета"].get("steps_lower_bound"))

    def test_дубляж_своего_видео_имеет_цену_ролика(self) -> None:
        ответ = _plan(
            "Dub my 2-minute anime episode into Egyptian Arabic",
            task="dub-translate", inputs=[{"kind": "video", "owned": True, "duration_s": 120}], outputs=["video"],
            duration_s=120, languages=["ar-EG"], people=[],
        )
        self.assertFalse(ответ["pipeline_price"].get("no_clip_price"))
        self.assertIsNotNone(ответ["pipeline_price"].get("за_ролик"))


class ПроходПоСнимкам(unittest.TestCase):
    """A tour of a place from photos is a camera path, not motion transfer."""

    def test_тур_по_квартире_en(self) -> None:
        а = _rewrite("Turn my 25 listing photos of the apartment into a walkthrough video",
                     task="animate", inputs=[{"kind": "image", "owned": True, "count": 25}], outputs=["video"], duration_s=40)
        self.assertEqual(("оживление",), а.route.шаги)
        self.assertEqual(rc.MOTION_CONTROL_MODELS, а.avoid["оживление"])
        self.assertIn(rc.ASSEMBLY_SPLAT, а.assembly)

    def test_видео_рядом_не_делает_перенос_движения(self) -> None:
        а = _rewrite("Property walkthrough from 6 photos of the house for a listing",
                     task="animate", inputs=[{"kind": "image", "owned": True, "count": 6}, {"kind": "video", "owned": False}],
                     outputs=["video"], duration_s=20)
        self.assertEqual(("оживление",), а.route.шаги)
        self.assertNotIn(rc.ASSEMBLY_SPLAT, а.assembly)

    def test_видеотур_ru(self) -> None:
        а = _rewrite("Сделай видеотур по дому из 12 фотографий объявления",
                     task="generate", inputs=[{"kind": "image", "owned": True, "count": 12}], outputs=["video"], duration_s=60)
        self.assertEqual(("оживление",), а.route.шаги)
        self.assertNotIn(rc.ASSEMBLY_SPLAT, а.assembly)

    def test_танец_по_ведущему_видео_остаётся_переносом(self) -> None:
        а = _rewrite("Make my photo dance like in this video",
                     task="animate", inputs=[{"kind": "image", "owned": True}, {"kind": "video", "owned": True}],
                     outputs=["video"], duration_s=10)
        self.assertEqual(("перенос_движения",), а.route.шаги)


    def test_несколько_снимков_и_ведущее_видео_без_тура(self) -> None:
        а = _rewrite("Make these three photos of me dance like in the clip",
                     task="animate", inputs=[{"kind": "image", "owned": True, "count": 3}, {"kind": "video", "owned": True}],
                     outputs=["video"], duration_s=10)
        self.assertEqual(("перенос_движения",), а.route.шаги)


class ДубляжРисованного(unittest.TestCase):
    """Drawn footage: lip sync on a model recorded for drawn / stylised faces (round 15) is an OPTIONAL
    upgrade priced apart; the base dub adapts the script to the mouth flaps (round 16)."""

    def _дубляж(self, brief: str, **extra: Any) -> rc.Applied:
        raw: dict[str, Any] = {"task": "dub-translate", "inputs": [V], "outputs": ["video"], "duration_s": 300, "languages": ["en"]}
        raw.update(extra)
        return _rewrite(brief, **raw)

    def test_аниме(self) -> None:
        а = self._дубляж("Dub my 5-minute anime episode from Japanese into English")
        self.assertEqual(("дубляж", "липсинк"), а.route.шаги)
        self.assertEqual(("липсинк",), а.prefer_stylised)
        self.assertEqual(("липсинк",), а.optional)
        self.assertIn(rc.ASSEMBLY_DRAWN_ADAPT, а.assembly)
        self.assertNotIn(rc.ASSEMBLY_DRAWN_DUB, а.assembly)

    def test_аниме_липсинк_заказан(self) -> None:
        а = self._дубляж("Dub my 5-minute anime episode from Japanese into English", lipsync=True)
        self.assertEqual((), а.optional)
        self.assertIn(rc.ASSEMBLY_DRAWN_DUB, а.assembly)

    def test_мультфильм_ru(self) -> None:
        а = self._дубляж("Переведи и озвучь наш мультфильм на английский")
        self.assertEqual(("дубляж", "липсинк"), а.route.шаги)
        self.assertEqual(("липсинк",), а.prefer_stylised)

    def test_снятое_видео_с_губами(self) -> None:
        а = self._дубляж("Dub my interview video into English with lip sync")
        self.assertEqual(("дубляж", "липсинк"), а.route.шаги)
        self.assertEqual((), а.prefer_stylised)


class ЛокальныйДубляж(unittest.TestCase):
    """A dub on the customer's own machine is a chain of open-weights steps."""

    def test_свой_gpu(self) -> None:
        а = _rewrite("Dub my lecture into Spanish", task="dub-translate", inputs=[V], outputs=["video"], duration_s=600,
                     languages=["es"], self_host={"gpu": "RTX 4090", "vram_gb": 24}, lipsync=False)
        self.assertEqual(("расшифровка", "клонирование_голоса"), а.route.шаги)
        self.assertTrue(а.local_only)
        self.assertEqual(rc.NO_CLONE_MODELS, а.avoid["клонирование_голоса"])

    def test_только_локально_словами_ru(self) -> None:
        а = _rewrite("Дубляж моего видео на немецкий, только локально, без облака", task="dub-translate", inputs=[V],
                     outputs=["video"], duration_s=300, languages=["de"], lipsync=False)
        self.assertEqual(("расшифровка", "клонирование_голоса"), а.route.шаги)

    def test_облачный_дубляж_один_шаг(self) -> None:
        а = _rewrite("Dub my video into German", task="dub-translate", inputs=[V], outputs=["video"], duration_s=300,
                     languages=["de"], lipsync=False)
        self.assertEqual(("дубляж",), а.route.шаги)
        self.assertFalse(а.local_only)

    def test_план_цепочки_с_моделями(self) -> None:
        ответ = _plan(
            "Dub my 10-minute lecture into Spanish, local-only — everything offline on my own GPU",
            task="dub-translate", inputs=[{"kind": "video", "owned": True, "duration_s": 600}], outputs=["video"],
            duration_s=600, languages=["es"], self_host={"gpu": "RTX 4090", "vram_gb": 24}, lipsync=False, people=[],
        )
        модели = _models(ответ)
        self.assertEqual(["расшифровка", "клонирование_голоса"], _steps(ответ))
        self.assertTrue(all(модели.values()), модели)
        self.assertNotIn("without-voice-clon", модели["клонирование_голоса"])


    def test_цепочка_с_губами_по_порядку(self) -> None:
        ответ = _plan(
            "Дубляж моего видео на немецкий, только локально, с движением губ",
            task="dub-translate", inputs=[{"kind": "video", "owned": True, "duration_s": 300}], outputs=["video"],
            duration_s=300, languages=["de"], self_host={"gpu": "RTX 3090", "vram_gb": 24}, lipsync=True, people=[],
        )
        self.assertEqual(["расшифровка", "клонирование_голоса", "липсинк"], _steps(ответ))


class ЗнакиКанала(unittest.TestCase):
    """A real broadcaster's marks on fabricated or parody news: refused, decisively."""

    def test_пародия_с_логотипом(self) -> None:
        self.assertEqual("refuse", bm.decide("Parody news segment with the CNN logo and lower-thirds", None)["decision"])

    def test_шуточный_выпуск_ru(self) -> None:
        self.assertEqual("refuse", bm.decide("Шуточный выпуск новостей в оформлении Первого канала", None)["decision"])

    def test_spec_claims(self) -> None:
        claims = {"claims": [{"type": "other", "real_brand": True, "brand": "BBC", "fabricated": True}]}
        self.assertEqual("refuse", bm.decide("Satirical sketch", claims)["decision"])

    def test_выдуманный_канал_план(self) -> None:
        self.assertEqual("plan", bm.decide("Satire sketch on a fictional channel, nothing like Fox News branding", None)["decision"])

    def test_отрицание_рядом(self) -> None:
        self.assertEqual("plan", bm.decide("Fake news clip, without the BBC logo, fictional channel", None)["decision"])

    def test_далёкое_отрицание_не_считается(self) -> None:
        self.assertEqual("refuse", bm.decide("No budget limit here, parody news with the CNN logo", None)["decision"])

    def test_стиль_без_выдумки_план(self) -> None:
        self.assertEqual("plan", bm.decide("Nature film in BBC documentary style", None)["decision"])

    def test_отказ_через_инструмент(self) -> None:
        ответ = _plan(
            "Satirical news sketch using the BBC News logo and studio look, 25 s",
            task="generate", inputs=[], outputs=["video", "speech"], duration_s=25, languages=["en"],
            claims=[{"type": "other", "real_brand": True, "brand": "BBC", "fabricated": True}], people=[],
        )
        self.assertEqual("запрещённая_тема", ответ["reason"])
        self.assertEqual([], ответ["steps"])


class БезЛишнегоВопроса(unittest.TestCase):
    """A complete spec plans with stated assumptions."""

    def test_визуализатор_без_трека(self) -> None:
        м = _route("Seamless 10-second loop visual for my techno track, abstract neon tunnel",
                   task="music-visualiser", inputs=[], outputs=["video"], duration_s=10)
        self.assertIsNone(м.нехватка)
        self.assertEqual(("генерация_видео",), м.шаги)
        self.assertIn(bs.NOTE_VISUALISER_NO_TRACK, м.сборка)

    def test_визуализатор_с_треком_прежний(self) -> None:
        м = _route("Visualiser for my song", task="music-visualiser",
                   inputs=[{"kind": "audio", "owned": True, "duration_s": 180}], outputs=["video"], duration_s=180)
        self.assertEqual(("генерация_видео",), м.шаги)
        self.assertIn(bs.NOTE_VISUALISER, м.сборка)

    def test_липсинк_без_материала_аватар(self) -> None:
        м = _route("Lip-sync a talking character saying hello", task="lipsync", inputs=[], outputs=["video", "speech"],
                   duration_s=8, languages=["en"])
        self.assertEqual(("говорящий_аватар",), м.шаги)

    def test_петля_ru_план(self) -> None:
        ответ = _plan("Зацикленная фоновая анимация 8 секунд, 16:9, абстрактные волны", task="generate", inputs=[],
                      outputs=["video"], duration_s=8, aspect="16:9", languages=[], people=[])
        self.assertEqual(["генерация_видео"], _steps(ответ))


if __name__ == "__main__":
    unittest.main()
