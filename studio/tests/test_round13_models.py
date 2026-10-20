"""Round 13: the right model for the step, expert caveats, and the in-house news presenter.

Every case here is a paraphrase written for this file (EN and RU), never a dev
or holdout brief. Decision constants are tested at their edges so that
`scripts/mutate_round13_models.py` turns each mutant red. No network (T4).

1. WRONG / MISSING MODEL — an upscaler whose recorded output ceiling is below
   the ordered frame is not a candidate (`studio/upscale_reach.py`); lettering
   in a video is a text edit, not a character swap (`studio/edit_intent.py`);
   an image face swap and an upscale on the customer's Mac get a model and a
   price from sourced rows.
2. EXPERT CAVEATS — `checklist.RULES_R13`, structured triggers first.
3. POLICY — a consented in-house presenter reading the customer's own true
   news is planned with disclosure (`studio/inhouse_news.py`); fabricated news
   and another broadcaster stay refused.
"""

from __future__ import annotations

import json
import math
import os
import unittest

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import edit_intent as ei  # noqa: E402
from studio import endpoints as ep  # noqa: E402
from studio import inhouse_news as ihn  # noqa: E402
from studio import planner  # noqa: E402
from studio import upscale_reach as ur  # noqa: E402
from studio.factindex import FactIndex  # noqa: E402
from studio.mcp import server  # noqa: E402
from studio.recipes import checklist as cl  # noqa: E402
from studio.selfrag.facts import Fact  # noqa: E402

_PLANS: dict[str, dict] = {}


def plan(brief: str, spec: dict) -> dict:
    """plan_pipeline answer, cached per (brief, spec) — the same brief is read by several tests."""
    ключ = brief + json.dumps(spec, sort_keys=True, ensure_ascii=False)
    if ключ not in _PLANS:
        _PLANS[ключ] = json.loads(server.plan_pipeline(brief, spec=spec))
    return _PLANS[ключ]


def step(d: dict, name: str) -> dict:
    for ш in d.get("steps") or []:
        if ш.get("step") == name:
            return ш
    raise AssertionError(f"no step {name}: {[ш.get('step') for ш in d.get('steps') or []]}")


def note_ids(d: dict) -> list[str]:
    return [n.get("id") for n in d.get("production_notes") or []]


def _spec(raw: dict) -> bs.Spec:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    return spec


def fired(raw: dict, steps: list[str], brief: str = "") -> list[str]:
    return [i for i, _ in cl.fire(_spec(raw), steps, text=brief)]


def F(model: str, attribute: str, value: str, url: str = "https://example.org/x", tier: str = "portal") -> Fact:
    return Fact(model, attribute, value, url, tier)


# --- 1a. upscale output ceiling --------------------------------------------------------------


class UpscaleReachRows(unittest.TestCase):
    def test_cap_rows_read_as_short_side(self) -> None:
        self.assertEqual(ur.row_reach("max_resolution", "2160p target (enum 720p, 1080p, 1440p, 2160p)", None)[0], 2160)
        self.assertEqual(ur.row_reach("max_resolution", "4K (2160p): the top output tier", None)[0], 2160)
        self.assertEqual(ur.row_reach("max_output_resolution", "up to 8K (7680x4320)", None)[0], 4320)
        mp = ur.row_reach("max_resolution", "input up to 2560x1440 (3.7 MP/frame); output capped at 13.75 MP/frame", None)[0]
        self.assertTrue(2700 < mp < 2800, mp)
        self.assertEqual(ur.row_reach("max_resolution", "any output resolution divisible by 2", None)[0], math.inf)

    def test_factor_needs_the_source_frame(self) -> None:
        self.assertEqual(ur.row_reach("upscale_factor_max", "10 in factor mode (upscale_factor 1-10)", 720)[0], 7200)
        self.assertEqual(ur.row_reach("upscale_factor_max", "4 (schema upscale_factor 1-4, default 2)", 1080)[0], 4320)
        self.assertIsNone(ur.row_reach("upscale_factor_max", "4 (schema upscale_factor 1-4)", None)[0])
        self.assertIsNone(ur.row_reach("positioning", "8K upscaler", 1080)[0])

    def test_one_mode_that_reaches_is_enough(self) -> None:
        rows = [F("m", "max_resolution", "2160p target"), F("m", "upscale_factor_max", "10 in factor mode")]
        self.assertEqual(ur.reach_state(rows, 4320, 720)[0], ur.REACH_YES)
        # Без кадра исходника режим множителя ничего не решает: «не записано», а не «ниже».
        self.assertEqual(ur.reach_state(rows, 4320, None)[0], ur.REACH_UNKNOWN)
        self.assertEqual(ur.reach_state(rows[:1], 4320, None)[0], ur.REACH_BELOW)
        self.assertEqual(ur.reach_state(rows[:1], 2160, None)[0], ur.REACH_YES)
        self.assertEqual(ur.reach_state([], 4320, 1080)[0], ur.REACH_UNKNOWN)

    def test_order_reaching_before_silence_before_below(self) -> None:
        self.assertEqual(
            sorted([ur.REACH_BELOW, ur.REACH_YES, ur.REACH_UNKNOWN], key=ur.REACH_ORDER.__getitem__),
            [ur.REACH_YES, ur.REACH_UNKNOWN, ur.REACH_BELOW],
        )


def _upscaler(model: str, endpoint: str, cap: str) -> list[Fact]:
    u = f"https://fal.ai/api/openapi/queue/openapi.json?endpoint_id={endpoint}"
    return [
        F(model, "availability", f"on fal.ai as {endpoint} (video-to-video)", u),
        F(model, "accepts_inputs", "видео", u),
        F(model, "requires_inputs", "видео", u),
        F(model, "produces_outputs", "видео", u),
        F(model, "price_unit_second_usd", "$0.05 per second", u),
        F(model, "max_resolution", cap, u),
    ]


class UpscaleReachCandidates(unittest.TestCase):
    OP = next(o for o in planner.OPERATIONS if o.name == "апскейл")

    def _cands(self, *caps: str, target=(7680, 4320)):
        facts = []
        for i, cap in enumerate(caps):
            facts += _upscaler(f"up{i}-upscale-video", f"fal-ai/up{i}/upscale/video", cap)
        return planner.candidates_for(self.OP, FactIndex(facts=facts), upscale_target=target)

    def test_below_is_excluded_when_someone_reaches(self) -> None:
        k = self._cands("2160p target", "8K (7680x4320)")
        self.assertEqual([c.model for c in k], ["up1-upscale-video"])
        self.assertIn("output ceiling", k.исключены["up0-upscale-video"])
        self.assertTrue(k[0].reach_note.startswith(ur.REACH_YES))

    def test_all_below_keeps_them_and_says_two_passes(self) -> None:
        k = self._cands("2160p target", "4K (2160p) top tier")
        self.assertEqual(len(k), 2)
        self.assertEqual(k.исключены, {})
        self.assertIn("two passes", k[0].reach_note)

    def test_no_target_no_filter(self) -> None:
        k = self._cands("2160p target", "8K (7680x4320)", target=None)
        self.assertEqual(len(k), 2)
        self.assertEqual(k[0].reach_note, "")

    def test_reaching_ranks_before_silence(self) -> None:
        facts = _upscaler("up0-upscale-video", "fal-ai/up0/upscale/video", "8K (7680x4320)")
        silent = [f for f in _upscaler("up1-upscale-video", "fal-ai/up1/upscale/video", "x") if f.attribute != "max_resolution"]
        # Тише и дешевле — но предел не записан: записанный дотяг стоит выше.
        silent = [F(f.model, f.attribute, "$0.01 per second", f.source_url) if f.attribute.startswith("price") else f for f in silent]
        k = planner.candidates_for(self.OP, FactIndex(facts=facts + silent), upscale_target=(7680, 4320))
        self.assertEqual(k[0].model, "up0-upscale-video")


EIGHT_K = (
    ("Blow our 720p archive reel up to 8K for an LED wall, 20 s", "1280x720", 20),
    ("Апскейл нашего ролика 1080p до 8K для огромного экрана, 30 секунд", "1920x1080", 30),
    ("We need an 8K master of this 4K short for a festival projector, one minute", "3840x2160", 60),
    ("Поднимите видео 1440p до 8K для выставочного стенда, 15 секунд", "2560x1440", 15),
)


class EightKPlans(unittest.TestCase):
    def test_only_upscale_steps_are_judged_by_output_ceiling(self) -> None:
        d = plan("A 10-second 4K clip of waves at dawn", {"task": "generate", "inputs": [], "outputs": ["video"],
                                                         "duration_s": 10, "resolution": "4k", "people": []})
        self.assertNotIn("upscale_reach", step(d, "генерация_видео"))
        self.assertEqual(ur.UPSCALE_OPS, frozenset({"апскейл", "апскейл_изображения"}))

    def test_no_upscaler_below_8k_by_record(self) -> None:
        idx = FactIndex()
        for brief, src, s in EIGHT_K:
            with self.subTest(brief=brief):
                d = plan(brief, {"task": "upscale", "inputs": [{"kind": "video", "owned": True, "resolution": src, "duration_s": s}],
                                 "outputs": ["video"], "resolution": "8k", "people": []})
                ш = step(d, "апскейл")
                модель = (ш.get("chosen") or {}).get("model")
                self.assertTrue(модель, ш)
                строки = [f for f in idx.facts if f.model == модель]
                короткая = min(int(x) for x in src.split("x"))
                self.assertNotEqual(ur.reach_state(строки, 4320, короткая)[0], ur.REACH_BELOW, модель)
                self.assertIn("upscale_reach", ш)
                отсеяны = {х["model"]: х["why"] for х in ш.get("hard_excluded") or []}
                self.assertIn("bytedance-upscaler-upscale-video", отсеяны)
                self.assertRegex(отсеяны["bytedance-upscaler-upscale-video"], r"output ceiling|предел выхода")


# --- 1b. lettering in a video is a text edit -------------------------------------------------

SIGNS = (
    ("Swap the words on the shop sign in my clip for 'OPEN LATE'", "face-replace", "en"),
    ("Change the text on the billboard in this drone shot to our new slogan", "video-edit", "en"),
    ("Замените надпись на вывеске в моём ролике на «Кофе с собой»", "face-replace", "ru"),
    ("Поменяйте текст на табличке у двери в видео на «Закрыто»", "edit", "ru"),
)


class TextEditRouting(unittest.TestCase):
    def test_sign_text_is_a_video_edit_with_text(self) -> None:
        for brief, task, lang in SIGNS:
            with self.subTest(brief=brief):
                d = plan(brief, {"task": task, "inputs": [{"kind": "video", "owned": True, "duration_s": 8}],
                                 "outputs": ["video"], "languages": [lang], "people": []})
                имена = [ш.get("step") for ш in d.get("steps") or []]
                self.assertIn("правка_видео", имена)
                self.assertNotIn("замена_персонажа", имена)
                self.assertEqual(step(d, "правка_видео")["edit"]["asked"], ["replace-text"])
                self.assertIn("text_edit_in_video", note_ids(d))

    def test_structured_edit_decides_without_words(self) -> None:
        spec = _spec({"task": "face-replace", "edit": ["replace-text"], "inputs": [{"kind": "video", "owned": True}],
                      "outputs": ["video"], "people": []})
        новый, нота = ei.reroute(spec, "")
        self.assertEqual((новый.task, новый.edit), ("video-edit", ("replace-text",)))
        self.assertTrue(нота)

    def test_a_face_keeps_its_task(self) -> None:
        for brief in ("Change the sign text and put my face on the presenter", "Замените надпись на вывеске и лицо ведущего"):
            self.assertTrue(ei.TEXT_EDIT_WORDS.search(brief), brief)
            spec = _spec({"task": "face-replace", "inputs": [{"kind": "video", "owned": True}], "outputs": ["video"], "people": []})
            self.assertEqual(ei.reroute(spec, brief)[0].task, "face-replace")

    def test_a_person_in_spec_does_not_decide_the_target(self) -> None:
        # Round 14 (owner policy): the edit TARGET decides — a person in the shot does not turn a sign
        # edit into a character swap (`test_round14_models.TextTargetDecides`); a face named as the
        # object of the edit still keeps the task.
        spec = _spec({"task": "face-replace", "inputs": [{"kind": "video", "owned": True}], "outputs": ["video"],
                      "people": [{"name": "me", "real": True, "public_figure": False, "consent": "stated", "claim": "none"}]})
        self.assertEqual(ei.reroute(spec, "change the text on the sign")[0].task, "video-edit")
        self.assertEqual(ei.reroute(spec, "change the text on the sign and swap my face onto the host")[0].task, "face-replace")

    def test_only_on_video_and_only_listed_tasks(self) -> None:
        фото = _spec({"task": "face-replace", "inputs": [{"kind": "image", "owned": True}], "outputs": ["image"], "people": []})
        self.assertFalse(ei.wants_text_edit(фото, "change the text on the sign"))
        липы = _spec({"task": "lipsync", "inputs": [{"kind": "video", "owned": True}, {"kind": "audio", "owned": True}],
                      "outputs": ["video"], "languages": ["en"], "people": []})
        self.assertFalse(ei.wants_text_edit(липы, "change the text on the sign"))
        for task in sorted(ei.TEXT_EDIT_TASKS):
            s = _spec({"task": task, "inputs": [{"kind": "video", "owned": True}], "outputs": ["video"], "people": []})
            self.assertTrue(ei.wants_text_edit(s, "change the text on the sign"), task)

    def test_replace_text_is_an_edit_intent_and_ranks_legibility(self) -> None:
        self.assertIn(ep.EDIT_REPLACE_TEXT, ep.EDIT_INTENTS)
        self.assertIn(ep.EDIT_REPLACE_TEXT, ep.edit_intents("fal-ai/some/edit-video"))
        spec = _spec({"task": "video-edit", "edit": ["replace-text"], "inputs": [{"kind": "video", "owned": True}],
                      "outputs": ["video"], "people": []})
        понятые, _ = planner.заявленные(spec, {}, "")
        self.assertIn("text_legibility", понятые)


# --- 1c. image face swap and the customer's Mac get a model and a price ------------------------

MACS = (
    ("Upscale 40 product photos to 4K on my MacBook Pro M3 Max", "M3 Max", 64),
    ("Апскейл 25 фотографий до 4K на моём MacBook Air M2", "M2", 16),
    ("Upscale my illustrations x4 locally on a Mac mini M4", "M4", 24),
    ("Увеличьте 10 снимков до 4K на iMac M1, без облака", "M1", 16),
)


class FaceSwapAndMacUpscale(unittest.TestCase):
    def test_image_face_swap_is_priced(self) -> None:
        for brief in ("Put my face on this knight painting", "Поставьте моё лицо на это свадебное фото"):
            with self.subTest(brief=brief):
                d = plan(brief, {"task": "face-replace", "inputs": [{"kind": "image", "owned": True, "count": 2}],
                                 "outputs": ["image"], "shots": 1,
                                 "people": [{"name": "me", "real": True, "public_figure": False, "consent": "stated", "claim": "none"}]})
                ch = step(d, "замена_лица_изображения").get("chosen") or {}
                self.assertTrue(ch.get("model"))
                self.assertRegex(ch.get("price") or "", r"\d+\.\d+ usd")

    def test_mac_image_upscale_has_a_model(self) -> None:
        for brief, chip, mem in MACS:
            with self.subTest(brief=brief):
                d = plan(brief, {"task": "upscale", "inputs": [{"kind": "image", "owned": True, "count": 10}], "outputs": ["image"],
                                 "shots": 10, "resolution": "4k", "self_host": {"gpu": f"Apple {chip}", "unified_memory_gb": mem},
                                 "people": []})
                ш = step(d, "апскейл_изображения")
                ch = ш.get("chosen") or {}
                self.assertTrue(ch.get("model"), ш.get("hard_excluded"))
                self.assertTrue(ch.get("price"))
                self.assertIn("recorded", str(ш.get("apple_silicon")))

    def test_new_rows_are_sourced(self) -> None:
        idx = FactIndex()
        for model, attribute in (
            ("wavespeed-image-face-swap", "price"),
            ("real-esrgan", "apple_silicon"),
            ("upscayl", "apple_silicon"),
            ("flux-2-pro", "output_training_use"),
            ("flux.1-dev", "output_training_use"),
        ):
            строки = [f for f in idx.facts if f.model == model and f.attribute == attribute]
            self.assertTrue(строки, (model, attribute))
            self.assertTrue(all(f.source_url.startswith("https://") for f in строки))


# --- 2. expert caveats -------------------------------------------------------------------------

VID = [{"kind": "video", "owned": True, "duration_s": 20}]
BG = {"task": "remove-background", "inputs": VID, "outputs": ["video"], "people": []}
LIPS = {"task": "lipsync", "inputs": VID + [{"kind": "audio", "owned": True}], "outputs": ["video"], "languages": ["en"], "people": []}
IMG = {"task": "generate", "inputs": [], "outputs": ["image"], "shots": 50, "people": []}
COL = {"task": "colorize", "inputs": [{"kind": "image", "owned": True}], "outputs": ["image"], "shots": 1, "people": []}
EDV = {"task": "video-edit", "inputs": VID, "outputs": ["video"], "people": []}
UPV = {"task": "upscale", "inputs": VID, "outputs": ["video"], "resolution": "4k", "people": []}
CAP = {"task": "captions", "inputs": VID, "outputs": ["video"], "languages": ["en"], "people": []}
GEN = {"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 10, "shots": 1, "people": []}


def w(base: dict, **more: object) -> dict:
    return {**base, **more}


AV0 = {"task": "avatar", "inputs": [{"kind": "image", "owned": True}, {"kind": "audio", "owned": True}],
       "outputs": ["video"], "duration_s": 30, "languages": ["en"]}
ANCHOR = {"name": "A", "real": True, "public_figure": True, "consent": "stated", "claim": "news", "role": "employee"}


#: rule -> (firing cases [(spec, steps, brief)], silent cases).
CAVEATS: dict[str, tuple[list[tuple[dict, list[str], str]], list[tuple[dict, list[str], str]]]] = {
    "green_screen_keying": (
        [(BG, ["удаление_фона_видео"], "the presenter was shot on a green screen"),
         (BG, ["удаление_фона_видео"], "key out the blue screen behind the dancer"),
         (BG, ["удаление_фона_видео"], "снимали на хромакее, нужен чистый кеинг"),
         (BG, ["удаление_фона_видео"], "за спикером зелёный фон — замените на офис")],
        [(BG, ["удаление_фона_видео"], "remove the busy street behind the presenter")],
    ),
    "stylised_face_photoreal_model": (
        [(LIPS, ["липсинк"], "lip-sync our cartoon mascot"),
         (LIPS, ["липсинк"], "make the 3D character's mouth follow the voice"),
         (LIPS, ["липсинк"], "синхронизируйте губы аниме-героини"),
         (LIPS, ["липсинк"], "пусть наша собака-талисман говорит этот текст")],
        [(LIPS, ["липсинк"], "lip-sync the CEO's interview"), (IMG, ["генерация_изображения"], "a cartoon poster")],
    ),
    "outputs_as_training_data": (
        [(IMG, ["генерация_изображения"], "images to use as training data for our detector"),
         (IMG, ["генерация_изображения"], "a synthetic dataset of shoes"),
         (IMG, ["генерация_изображения"], "картинки для датасета, на котором дообучим модель"),
         (IMG, ["генерация_изображения"], "кадры для обучения нейросети распознавать брак")],
        [(IMG, ["генерация_изображения"], "50 images for our catalogue")],
    ),
    "colorize_plausible_not_true": (
        [(COL, ["раскраска_изображения"], "colorize grandma's photo"),
         (w(COL, inputs=VID, outputs=["video"]), ["раскраска"], "раскрасьте хронику"),
         (COL, ["раскраска_изображения"], "make this b&w street photo colour"),
         (COL, ["раскраска_изображения"], "сделайте цветным старый снимок")],
        [(w(COL, task="restore"), ["реставрация_изображения"], "remove scratches only")],
    ),
    "relight_limits": (
        [(w(EDV, edit=["relight"]), ["правка_видео"], "key light from the left"),
         (w(EDV, edit=["relight"]), ["правка_видео"], "свет слева, как в студии"),
         (EDV, ["правка_видео"], "relight the face, it is too dark"),
         (EDV, ["правка_видео"], "переосветите сцену тёплым светом")],
        [(EDV, ["правка_видео"], "stabilise the shot")],
    ),
    "multicam_sync": (
        [(w(UPV, inputs=[{"kind": "video", "owned": True, "count": 2}]), ["апскейл"], "upscale both angles"),
         (w(UPV, inputs=VID + VID), ["апскейл"], "апскейл двух видео"),
         (UPV, ["апскейл"], "we filmed it with three cameras"),
         (UPV, ["апскейл"], "интервью снято на две камеры")],
        [(UPV, ["апскейл"], "upscale the drone shot"), (w(UPV, inputs=[{"kind": "image", "owned": True, "count": 3}]), ["апскейл_изображения"], "")],
    ),
    "rtl_burn_in": (
        [(w(CAP, languages=["ar"]), [], "burn in the subtitles"),
         (w(CAP, languages=["he"]), [], "вшитые субтитры"),
         (w(CAP, languages=["fa"]), [], "Persian captions on the video"),
         (w(CAP, languages=["ur"]), [], "субтитры на урду")],
        [(CAP, [], "burn in English subtitles")],
    ),
    "single_take_limit": (
        [(w(GEN, duration_s=30), ["генерация_видео"], "one continuous take"),
         (w(GEN, duration_s=16), ["генерация_видео"], "single shot, no cuts"),
         (w(GEN, duration_s=40), ["генерация_видео"], "один непрерывный дубль"),
         (w(GEN, shots=2, per_shot_s=20, duration_s=40), ["генерация_видео"], "два шота по 20 секунд")],
        [(w(GEN, duration_s=15), ["генерация_видео"], "one take"), (w(GEN, duration_s=30, shots=3), ["генерация_видео"], "three shots")],
    ),
    "text_edit_in_video": (
        [(w(EDV, edit=["replace-text"]), ["правка_видео"], ""),
         (w(EDV, edit=["replace-text", "stabilise"]), ["правка_видео"], "новая надпись на вывеске")],
        [(w(EDV, edit=["replace-object"]), ["правка_видео"], "replace the car with a bus")],
    ),
    "in_house_anchor_disclosure": (
        [({**AV0, "people": [ANCHOR]}, ["говорящий_аватар"], "our anchor reads our news"),
         ({**AV0, "people": [{**ANCHOR, "role": "self"}]}, ["говорящий_аватар"], "я сам читаю новости своего канала")],
        [({**AV0, "people": [{**ANCHOR, "role": "talent"}]}, ["говорящий_аватар"], "a hired presenter"),
         ({**AV0, "people": [{**ANCHOR, "consent": "unknown"}]}, ["говорящий_аватар"], "our anchor")],
    ),
}


class Caveats(unittest.TestCase):
    def test_each_rule_fires_and_stays_silent(self) -> None:
        for rule, (pos, neg) in CAVEATS.items():
            for raw, steps, brief in pos:
                with self.subTest(rule=rule, brief=brief):
                    self.assertIn(rule, fired(raw, steps, brief))
            for raw, steps, brief in neg:
                with self.subTest(rule=rule, silent=brief):
                    self.assertNotIn(rule, fired(raw, steps, brief))

    def test_constants_at_their_edges(self) -> None:
        self.assertEqual(cl.MULTICAM_MIN_INPUTS, 2)
        self.assertEqual(cl.SINGLE_TAKE_TYPICAL_MAX_S, 15.0)
        self.assertNotIn("avatar", cl.GENERATED_TAKE_JOBS)
        self.assertNotIn("single_take_limit", fired(
            {"task": "avatar", "inputs": [{"kind": "image", "owned": True}, {"kind": "audio", "owned": True}],
             "outputs": ["video"], "duration_s": 60, "languages": ["en"], "people": []}, ["говорящий_аватар"], ""))

    def test_rules_are_bilingual_and_sourced_where_regulatory(self) -> None:
        self.assertEqual({р.id for р in cl.RULES_R13}, set(CAVEATS))
        for р in cl.RULES_R13:
            self.assertTrue(р.en and р.ru, р.id)
            if р.tag == cl.R:
                self.assertTrue(р.sources, р.id)

    def test_long_take_prints_the_models_recorded_run(self) -> None:
        d = plan("A single unbroken 45-second aerial take over a glacier", {
            "task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 45, "shots": 1, "people": []})
        ш = step(d, "генерация_видео")
        self.assertIn("single_take_limit", note_ids(d))
        self.assertRegex(str(ш.get("run_limit")), r"at most \d+ s by record")


# --- 3. the in-house news presenter --------------------------------------------------------------


def anchor(name: str, **more: object) -> dict:
    return {"name": name, "real": True, "public_figure": True, "consent": "stated", "claim": "news", "role": "employee", **more}


OWN = {"type": "news", "real_brand": False, "own_brand": True, "fabricated": False}
AV = {"task": "avatar", "inputs": [{"kind": "image", "owned": True}, {"kind": "text", "owned": True}], "outputs": ["video"],
      "duration_s": 45, "aspect": "16:9"}

IN_HOUSE = (
    ("Our city channel wants an AI version of our anchor Lena Ford, a staff member who signed consent, to read the "
     "evening bulletin our newsroom wrote", "Lena Ford", "en"),
    ("Наш канал просит ИИ-аватар нашей ведущей Ольги Луниной — она в штате, согласие подписано — для утреннего выпуска "
     "нашей редакции", "Ольга Лунина", "ru"),
    ("We are a local news website: our presenter Sam Ortiz (employee, consent on file) should read today's verified "
     "headlines from our desk", "Sam Ortiz", "en"),
    ("Мы региональное радио; наш штатный диктор Павел Седов дал согласие — пусть он в видео читает проверенные новости "
     "нашей редакции", "Павел Седов", "ru"),
)


class InHousePresenter(unittest.TestCase):
    def test_planned_with_disclosure(self) -> None:
        for brief, name, lang in IN_HOUSE:
            with self.subTest(brief=brief):
                d = plan(brief, {**AV, "languages": [lang], "people": [anchor(name)], "claims": [OWN]})
                self.assertNotEqual(d.get("outcome"), "fail", d.get("reason"))
                self.assertNotEqual(d.get("reason"), "запрещённая_тема")
                self.assertTrue(d.get("steps"))
                self.assertEqual(d["in_house_news"]["decision"], ihn.DECISION_ALLOW)
                self.assertIn("in_house_anchor_disclosure", note_ids(d))

    def test_still_refused(self) -> None:
        brief, name, lang = IN_HOUSE[0]
        for why, people, claims in (
            ("fabricated", [anchor(name)], [{**OWN, "fabricated": True}]),
            ("fabricated unknown", [anchor(name)], [{k: v for k, v in OWN.items() if k != "fabricated"}]),
            ("another broadcaster", [anchor(name)], [{**OWN, "real_brand": True, "own_brand": False, "brand": "CNN"}]),
            ("not own outlet", [anchor(name)], [{**OWN, "own_brand": False}]),
            ("hired talent", [anchor(name, role="talent")], [OWN]),
            ("no role", [{k: v for k, v in anchor(name).items() if k != "role"}], [OWN]),
            ("consent unknown", [anchor(name, consent="unknown")], [OWN]),
        ):
            with self.subTest(why=why):
                d = plan(brief, {**AV, "languages": [lang], "people": people, "claims": claims})
                self.assertIn(d.get("outcome"), ("fail", "could not measure"))
                self.assertNotIn("in_house_news", d)
                self.assertFalse(d.get("steps"), why)

    def test_decide_is_narrow(self) -> None:
        spec = {"people": [anchor("A")], "claims": [OWN]}
        policy = {"decision": "refuse", "people": [{"name": "A", "verdict": "refuse", "rule": "public_statement"}],
                  "claims": [{"verdict": "proceed"}], "banned": ["x"]}
        screened = {"banned": ["x"]}
        self.assertEqual(ihn.decide(spec, policy, screened, {"banned": []})["decision"], ihn.DECISION_ALLOW)
        # Запрет самого текста (бренд новостей + «fake») — дверь закрыта.
        self.assertEqual(ihn.decide(spec, policy, screened, {"banned": ["t"]})["decision"], ihn.DECISION_NONE)
        # Другое правило отказа — дверь закрыта.
        other = {**policy, "people": [{"name": "A", "verdict": "refuse", "rule": "consent_none"}]}
        self.assertEqual(ihn.decide(spec, other, screened, {"banned": []})["decision"], ihn.DECISION_NONE)
        # Лишний запрет сверх людей — закрыта.
        self.assertEqual(ihn.decide(spec, policy, {"banned": ["x", "y"]}, {"banned": []})["decision"], ihn.DECISION_NONE)
        self.assertEqual(ihn.decide({**spec, "people": [anchor("A", role="self")]}, policy, screened, {})["decision"], ihn.DECISION_ALLOW)
        # Сами поля заявлений решают, даже если политика их пропустила.
        for claims in ([{**OWN, "real_brand": True}], [{k: v for k, v in OWN.items() if k != "fabricated"}],
                       [{**OWN, "own_brand": False}], [{**OWN, "type": "none"}]):
            with self.subTest(claims=claims):
                self.assertEqual(ihn.decide({**spec, "claims": claims}, policy, screened, {})["decision"], ihn.DECISION_NONE)

    def test_role_is_a_validated_spec_field(self) -> None:
        _, errors = bs.parse_spec({"task": "avatar", "people": [anchor("A", role="boss")]})
        self.assertTrue(any("role" in e for e in errors))
        spec, errors = bs.parse_spec({"task": "avatar", "people": [anchor("A")]})
        self.assertEqual(spec.people[0]["role"], "employee")

    def test_documented_in_the_tool_description(self) -> None:
        doc = server.plan_pipeline.__doc__ or ""
        self.assertIn("own_brand", doc)
        self.assertIn("role: employee", doc)


if __name__ == "__main__":
    unittest.main()
