"""Round 14: caveats on natural phrasings, the broadcaster's synthetic presenter, edit targets, upscalers, face-swap data sets.

Every case here is a paraphrase written for this file (EN and RU), never a dev
or holdout brief. Decision constants are tested at their edges so that
`scripts/mutate_round14_models.py` turns each mutant red. No network (T4).

1. CAVEATS — `checklist.RULES_R14` (hologram black, synthetic presenter,
   face-swap data set) and wider triggers of round-13 rules: relighting across
   shots, outputs as training data, the single take against the CHOSEN model's
   recorded run.
2. POLICY — a fully synthetic presenter reading true content for the
   broadcaster's own programme is planned with disclosure
   (`studio/synthetic_presenter.py`); every refusal around it still holds.
3. EDIT TARGET — lettering in the shot is a video edit even with people in the
   shot (`studio/edit_intent.py`).
4. UPSCALERS — 8K prefers an upscaler that reaches the frame by record over
   one whose quality is tested below it or that works per frame; an alpha
   upscaler only when transparency is ordered (`studio/upscale_reach.py`).
5. FACE-SWAP DATA SETS — image data sets route to the priced image face swap,
   counted per item, with the consent / licence caveat.
"""

from __future__ import annotations

import json
import os
import unittest

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import edit_intent as ei  # noqa: E402
from studio import planner  # noqa: E402
from studio import synthetic_presenter as sp  # noqa: E402
from studio import upscale_reach as ur  # noqa: E402
from studio.factindex import FactIndex  # noqa: E402
from studio.mcp import server  # noqa: E402
from studio.recipes import apply as ra  # noqa: E402
from studio.recipes import checklist as cl  # noqa: E402
from studio.selfrag.facts import Fact  # noqa: E402

_PLANS: dict[str, dict] = {}


def plan(brief: str, spec: dict) -> dict:
    ключ = brief + json.dumps(spec, sort_keys=True, ensure_ascii=False)
    if ключ not in _PLANS:
        _PLANS[ключ] = json.loads(server.plan_pipeline(brief, spec=spec))
    return _PLANS[ключ]


def steps_of(d: dict) -> list[str]:
    return [ш.get("step") for ш in d.get("steps") or []]


def step(d: dict, name: str) -> dict:
    for ш in d.get("steps") or []:
        if ш.get("step") == name:
            return ш
    raise AssertionError(f"no step {name}: {steps_of(d)}")


def note_ids(d: dict) -> list[str]:
    return [n.get("id") for n in d.get("production_notes") or []]


def _spec(raw: dict) -> bs.Spec:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    return spec


def fired(raw: dict, steps: list[str], brief: str = "", priors: tuple[str, ...] = ()) -> list[str]:
    return [i for i, _ in cl.fire(_spec(raw), steps, text=brief, priors=priors)]


def F(model: str, attribute: str, value: str, url: str = "https://example.org/x", tier: str = "portal") -> Fact:
    return Fact(model, attribute, value, url, tier)


VID = [{"kind": "video", "owned": True}]
GEN = {"task": "generate", "inputs": [], "outputs": ["video"], "duration_s": 10, "shots": 1, "people": []}
ANI = {"task": "animate", "inputs": [{"kind": "image", "owned": True}], "outputs": ["video"], "duration_s": 10, "people": []}
IMG = {"task": "generate", "inputs": [], "outputs": ["image"], "shots": 40, "people": []}
EDV = {"task": "video-edit", "inputs": VID, "outputs": ["video"], "duration_s": 20, "people": []}
AV = {"task": "avatar", "inputs": [{"kind": "text", "owned": True}], "outputs": ["video"], "duration_s": 45, "languages": ["en"]}
FS = {"task": "face-replace", "inputs": [{"kind": "image", "owned": True, "count": 3}], "outputs": ["image"], "people": []}


def w(base: dict, **more: object) -> dict:
    return {**base, **more}


SYN = {"name": "Skye", "real": False}
OWN_REAL = {"type": "news", "fabricated": False, "real_brand": True, "own_brand": True, "brand": "KXTV 5"}
OWN = {"type": "news", "fabricated": False, "real_brand": False, "own_brand": True}

# --- 1. caveats ------------------------------------------------------------------------------

#: rule -> (firing cases [(spec, steps, brief)], silent cases).
CAVEATS: dict[str, tuple[list[tuple[dict, list[str], str]], list[tuple[dict, list[str], str]]]] = {
    "hologram_black_background": (
        [(ANI, ["оживление"], "our singer for a Pepper's ghost hologram stage"),
         (GEN, ["генерация_видео"], "a product loop for the transparent LED screen in our shop window"),
         (ANI, ["оживление"], "ведущий для голографического вентилятора на выставке"),
         (GEN, ["генерация_видео"], "ролик для прозрачного экрана в витрине, всё вокруг чёрное")],
        [(GEN, ["генерация_видео"], "a perfume bottle on a black background for our website"),
         (GEN, ["генерация_видео"], "флакон на чёрном фоне для сайта"),
         (w(GEN, outputs=["speech"]), [], "a hologram stage announcement read aloud")],
    ),
    "synthetic_presenter_disclosure": (
        [(w(AV, people=[SYN], claims=[OWN_REAL]), ["говорящий_аватар"], "weather presenter for our station"),
         (w(AV, people=[SYN], claims=[OWN]), ["говорящий_аватар"], "виртуальная ведущая нашего канала"),
         (w(AV, people=[SYN, {"name": "Max", "real": False}], claims=[{**OWN, "type": "real_event"}]), ["говорящий_аватар"], "")],
        [(w(AV, people=[{"name": "Lena", "real": True, "consent": "stated", "claim": "news", "role": "employee"}], claims=[OWN]),
          ["говорящий_аватар"], "our own anchor"),
         (w(AV, people=[SYN], claims=[{**OWN, "own_brand": False}]), ["говорящий_аватар"], "a virtual presenter"),
         (w(AV, people=[SYN], claims=[{**OWN, "type": "product"}]), ["говорящий_аватар"], "ведущая рекламы"),
         (w(AV, people=[], claims=[OWN]), ["говорящий_аватар"], "")],
    ),
    "face_swap_dataset_consent": (
        [(w(FS, shots=500), ["замена_лица_изображения"], "a face-swap data set"),
         (FS, ["замена_лица_изображения"], "swapped faces to train our detector"),
         (w(FS, shots=300), ["замена_лица_изображения"], "датасет из 300 картинок с заменой лица"),
         (FS, ["замена_лица_изображения"], "на них будем учить нейросеть")],
        [(FS, ["замена_лица_изображения"], "put my face on these three posters"),
         (w(FS, shots=cl.FACE_SWAP_DATASET_MIN - 1), ["замена_лица_изображения"], "поставьте моё лицо на открытки"),
         (w(IMG, shots=500), ["генерация_изображения"], "500 images for a data set")],
    ),
    # Round-13 rules on the natural phrasings the round-14 hidden set used.
    "relight_limits": (
        [(w(GEN, shots=3, duration_s=24), ["генерация_видео"], "keep the lighting consistent across all three shots"),
         (EDV, ["правка_видео"], "the interview was shot in two sessions and the light is different — match it"),
         (EDV, ["правка_видео"], "сделайте одинаковый свет во всех сценах"),
         (w(GEN, shots=4, duration_s=20), ["генерация_видео"], "свет в шотах должен совпадать")],
        [(GEN, ["генерация_видео"], "consistent lighting in this one shot"),
         (EDV, ["правка_видео"], "stabilise the shaky shot"),
         (EDV, ["правка_видео"], "уберите дрожание")],
    ),
    "outputs_as_training_data": (
        [(IMG, ["генерация_изображения"], "we will train our own classifier on them"),
         (IMG, ["генерация_изображения"], "images for ML training"),
         (IMG, ["генерация_изображения"], "на них будем учить свою нейросеть"),
         (IMG, ["генерация_изображения"], "натренировать детектор брака")],
        [(IMG, ["генерация_изображения"], "40 images for our catalogue"),
         (IMG, ["генерация_изображения"], "a training video for our new staff"),
         (IMG, ["генерация_изображения"], "картинки для каталога интернет-магазина")],
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

    def test_round14_rules_are_cased_bilingual_and_sourced(self) -> None:
        self.assertEqual({р.id for р in cl.RULES_R14} | {"relight_limits", "outputs_as_training_data"}, set(CAVEATS))
        for р in cl.RULES_R14:
            self.assertTrue(р.en and р.ru, р.id)
            if р.tag == cl.R:
                self.assertTrue(р.sources, р.id)

    def test_constants_at_their_edges(self) -> None:
        self.assertEqual(cl.FACE_SWAP_DATASET_MIN, 20)
        self.assertIn("face_swap_dataset_consent", fired(w(FS, shots=20), ["замена_лица_изображения"], ""))
        self.assertNotIn("face_swap_dataset_consent", fired(w(FS, shots=19), ["замена_лица_изображения"], ""))
        self.assertEqual(cl.RELIGHT_SERIES_MIN_SHOTS, 2)
        self.assertIn("relight_limits", fired(w(GEN, shots=2), ["генерация_видео"], "match the lighting"))
        self.assertNotIn("relight_limits", fired(w(GEN, shots=1), ["генерация_видео"], "match the lighting"))
        self.assertEqual(cl.PRESENTER_NEWS_TYPES, frozenset({"news", "real_event"}))
        self.assertEqual(cl.FACE_SWAP_JOBS, frozenset({"char_replace", "face_swap"}))
        self.assertEqual(cl.JOBS_OF_STEP["замена_лица_изображения"], "face_swap")
        # Работа «замена лица на снимке» — по шагу, даже когда задача названа иначе.
        правка = {"task": "edit", "inputs": [{"kind": "image", "owned": True, "count": 3}], "outputs": ["image"], "shots": 500,
                  "people": []}
        self.assertIn("face_swap_dataset_consent", fired(правка, ["замена_лица_изображения"], ""))


class SingleTakeFollowsTheChosenModel(unittest.TestCase):
    def test_run_over_prior_is_read_from_the_step_lines(self) -> None:
        en = "one run of veo-3.1 is at most 8 s by record (x); the 12 s take is 2 runs joined by extend"
        ru = "один прогон veo-3.1 — не больше 8 с по записи (x); дубль 12 с — это 2 прогона"
        self.assertEqual(cl.run_over_priors([None, en]), (f"{cl.RUN_OVER_PRIOR}:8",))
        self.assertEqual(cl.run_over_priors([ru, "один прогон m — не больше 10 с по записи"]), (f"{cl.RUN_OVER_PRIOR}:8",))
        self.assertEqual(cl.run_over_priors([None, ""]), ())
        self.assertEqual(cl.chosen_run_s((f"{cl.RUN_OVER_PRIOR}:8",)), 8.0)
        self.assertIsNone(cl.chosen_run_s(("lyrics_alignment",)))

    def test_notes_take_the_plan_priors(self) -> None:
        take = _spec(w(GEN, duration_s=12))
        ids = [р["id"] for р in ra.notes(take, ["генерация_видео"], True, extra_priors=(f"{cl.RUN_OVER_PRIOR}:8",))]
        self.assertIn("single_take_limit", ids)
        self.assertNotIn("single_take_limit", [р["id"] for р in ra.notes(take, ["генерация_видео"], True)])

    def test_take_under_15_s_but_over_the_chosen_run(self) -> None:
        take = w(GEN, duration_s=12)
        self.assertNotIn("single_take_limit", fired(take, ["генерация_видео"], "one unbroken take"))
        self.assertIn("single_take_limit", fired(take, ["генерация_видео"], "", (f"{cl.RUN_OVER_PRIOR}:8",)))
        self.assertIn("single_take_limit", fired(take, ["генерация_видео"], "один дубль", (f"{cl.RUN_OVER_PRIOR}:11.5",)))
        # Дубль не длиннее прогона — заметки нет; шоты считаются по отдельности.
        self.assertNotIn("single_take_limit", fired(take, ["генерация_видео"], "", (f"{cl.RUN_OVER_PRIOR}:12",)))
        self.assertNotIn("single_take_limit", fired(w(GEN, duration_s=24, shots=3), ["генерация_видео"], "",
                                                    (f"{cl.RUN_OVER_PRIOR}:10",)))
        self.assertIn("single_take_limit", fired(w(GEN, duration_s=24, shots=2), ["генерация_видео"], "",
                                                 (f"{cl.RUN_OVER_PRIOR}:10",)))

    def test_a_multi_shot_plan_does_not_get_the_note_from_the_whole_length(self) -> None:
        d = plan("Three-shot ad for our coffee brand, 8 seconds each", w(GEN, duration_s=24, shots=3, jurisdiction=["US"]))
        self.assertNotIn("single_take_limit", note_ids(d))


class HologramWantsBlackNotAlpha(unittest.TestCase):
    def test_wants_alpha(self) -> None:
        for text, want in (
            ("a loop for the transparent LED screen in our window", False),
            ("для прозрачного экрана в витрине", False),
            ("Pepper's ghost hologram, transparent background", False),
            ("hologram fan, deliver with alpha channel", True),
            ("our transparent glass bottle on a table", False),
            ("прозрачный флакон крупным планом", False),
            ("logo on a transparent background", True),
            ("на прозрачном фоне", True),
            ("export as webm", True),
        ):
            with self.subTest(text=text):
                self.assertEqual(ra.wants_alpha(_spec(GEN), text), want)

    def test_plan_for_a_transparent_led_has_no_background_removal(self) -> None:
        for brief in ("Product loop for a transparent LED screen in our shop window, everything around the bottle black",
                      "Ролик для голографического вентилятора: наш логотип вращается на чёрном"):
            with self.subTest(brief=brief):
                d = plan(brief, w(GEN, jurisdiction=["US"]))
                self.assertNotIn("удаление_фона_видео", steps_of(d))
                self.assertNotIn("alpha_delivery", note_ids(d))
                self.assertIn("hologram_black_background", note_ids(d))


# --- 2. synthetic presenter for the broadcaster's own programme ---------------------------------

SYNTHETIC = (
    ("KXTV 5 News wants a fully AI-generated weather presenter — not a real person — to read the forecast our "
     "meteorologists write", "en", [OWN_REAL]),
    ("Телеканал «Город-ТВ»: ИИ-ведущая прогноза погоды, вымышленная, читает прогноз нашей редакции", "ru",
     [{**OWN_REAL, "brand": "Город-ТВ"}]),
    ("Our regional radio's website wants a virtual newsreader (synthetic, no real likeness) for our verified headlines",
     "en", [OWN]),
    ("Синтетический диктор для утренних новостей нашего городского канала, текст пишет наша редакция", "ru",
     [{**OWN_REAL, "brand": "Утро-24"}]),
)


class SyntheticPresenter(unittest.TestCase):
    def test_planned_with_disclosure(self) -> None:
        for brief, lang, claims in SYNTHETIC:
            with self.subTest(brief=brief):
                d = plan(brief, w(AV, languages=[lang], people=[SYN], claims=claims, jurisdiction=["US"]))
                self.assertNotEqual(d.get("outcome"), "fail", d.get("reason"))
                self.assertTrue(d.get("steps"))
                self.assertIn("synthetic_presenter_disclosure", note_ids(d))
                if any(з.get("real_brand") for з in claims):
                    self.assertEqual(d["synthetic_presenter"]["decision"], sp.DECISION_ALLOW)

    def test_every_refusal_still_holds(self) -> None:
        brief = SYNTHETIC[0][0]
        for why, people, claims, text in (
            ("another broadcaster", [SYN], [{**OWN_REAL, "own_brand": False, "brand": "BBC"}], brief),
            ("own_brand claimed for a known broadcaster", [SYN], [{**OWN_REAL, "brand": "CNN"}], brief),
            ("a known broadcaster in the brief", [SYN], [OWN_REAL], brief + " in the style of CNN"),
            ("fabricated", [SYN], [{**OWN_REAL, "fabricated": True}], brief),
            ("parody", [SYN], [{**OWN_REAL, "parody": True}], brief),
            ("real person without consent", [{"name": "Dana Lee", "real": True, "public_figure": True, "consent": "unknown",
                                              "claim": "news"}], [OWN_REAL], brief),
            ("one real person among synthetic", [SYN, {"name": "Dana Lee", "real": True, "public_figure": True,
                                                      "consent": "none", "claim": "news"}], [OWN_REAL], brief),
            ("fake news words", [SYN], [OWN_REAL], "A fake breaking news bulletin about a flood that never happened, "
                                                   "read by an AI presenter for KXTV 5"),
        ):
            with self.subTest(why=why):
                d = plan(text, w(AV, languages=["en"], people=people, claims=claims, jurisdiction=["US"]))
                self.assertIn(d.get("outcome"), ("fail", "could not measure"))
                self.assertNotIn("synthetic_presenter", d)
                self.assertFalse(d.get("steps"), why)

    def test_decide_is_narrow(self) -> None:
        spec = {"people": [SYN], "claims": [OWN_REAL]}
        policy = {"decision": "refuse", "people": [{"name": "Skye", "verdict": "proceed", "rule": "fictional"}],
                  "claims": [{"name": "KXTV 5", "verdict": "refuse", "rule": "news_brand"}], "banned": ["x"]}
        screened = {"banned": ["x"]}
        self.assertEqual(sp.decide(spec, policy, screened, {})["decision"], sp.DECISION_ALLOW)
        self.assertEqual(sp.decide(spec, policy, screened, {"banned": ["t"]})["decision"], sp.DECISION_NONE)
        self.assertEqual(sp.decide(spec, policy, screened, {}, "like Fox News")["decision"], sp.DECISION_NONE)
        for слова in ("a fake bulletin", "a flood that never happened", "выдуманные новости", "пародия на выпуск"):
            self.assertEqual(sp.decide(spec, policy, screened, {}, слова)["decision"], sp.DECISION_NONE, слова)
        for слова in ("a fictional weather presenter", "вымышленная ведущая погоды"):
            self.assertEqual(sp.decide(spec, policy, screened, {}, слова)["decision"], sp.DECISION_ALLOW, слова)
        other = {**policy, "claims": [{"name": "KXTV 5", "verdict": "refuse", "rule": "event_fabricated"}]}
        self.assertEqual(sp.decide(spec, other, screened, {})["decision"], sp.DECISION_NONE)
        self.assertEqual(sp.decide(spec, policy, {"banned": ["x", "y"]}, {})["decision"], sp.DECISION_NONE)
        refused_person = {**policy, "people": [{"name": "Skye", "verdict": "refuse"}]}
        self.assertEqual(sp.decide(spec, refused_person, screened, {})["decision"], sp.DECISION_NONE)
        self.assertEqual(sp.decide({**spec, "people": [{**SYN, "real": None}]}, policy, screened, {})["decision"],
                         sp.DECISION_NONE)
        self.assertEqual(sp.decide({**spec, "people": []}, policy, screened, {})["decision"], sp.DECISION_NONE)
        смешанные = {**spec, "people": [SYN, {"name": "Ann", "real": None}]}
        self.assertEqual(sp.decide(смешанные, policy, screened, {})["decision"], sp.DECISION_NONE)
        for claims in ([{**OWN_REAL, "own_brand": False}], [{k: v for k, v in OWN_REAL.items() if k != "fabricated"}],
                       [{**OWN_REAL, "type": "product"}], [{**OWN_REAL, "brand": "Sky News"}],
                       [OWN_REAL, {"type": "news", "fabricated": False, "real_brand": True, "own_brand": False,
                                   "brand": "Metro Daily"}]):
            with self.subTest(claims=claims):
                self.assertEqual(sp.decide({**spec, "claims": claims}, policy, screened, {})["decision"], sp.DECISION_NONE)

    def test_apply_lifts_only_the_named_claims(self) -> None:
        policy = {"decision": "refuse", "claims": [{"name": "KXTV 5", "verdict": "refuse", "rule": "news_brand", "label": "l"}],
                  "banned": ["l"]}
        новый_просев, новая = sp.apply({"decision": sp.DECISION_ALLOW, "claims": ["KXTV 5"]}, {"outcome": "fail", "banned": ["l"]},
                                       policy)
        self.assertEqual(новая["decision"], "proceed")
        self.assertEqual(новая["claims"][0]["rule"], sp.RULE_ID)
        self.assertEqual(новый_просев["banned"], [])
        self.assertEqual(sp.apply({"decision": sp.DECISION_NONE}, {"outcome": "fail"}, policy)[1], policy)
        self.assertEqual(sp.note({"decision": sp.DECISION_NONE}), "")
        self.assertIn("синтетический", sp.note({"decision": sp.DECISION_ALLOW, "claims": ["X"]}, en=False))


# --- 3. the edit target decides ---------------------------------------------------------------

STAFF = {"name": "staff", "real": True, "public_figure": False, "consent": "stated", "claim": "none", "role": "employee"}

LETTERING_WITH_PEOPLE = (
    ("In our shop video two people walk past the sign — replace the sign text with 'OPEN 24/7'", "face-replace", "en"),
    ("The presenter stands in front of a screen; replace the text on the screen with our new slogan", "edit", "en"),
    ("Замените надпись на футболке актёра на наш слоган", "face-replace", "ru"),
    ("Ведущая стоит у вывески — поменяйте текст на вывеске на «Открыто»", "video-edit", "ru"),
)


class TextTargetDecides(unittest.TestCase):
    def test_lettering_is_a_priced_video_edit_with_people_in_the_shot(self) -> None:
        for brief, task, lang in LETTERING_WITH_PEOPLE:
            with self.subTest(brief=brief):
                d = plan(brief, {"task": task, "inputs": [{"kind": "video", "owned": True, "duration_s": 10}],
                                 "outputs": ["video"], "languages": [lang], "people": [STAFF], "jurisdiction": ["US"]})
                self.assertIn("правка_видео", steps_of(d))
                self.assertNotIn("замена_персонажа", steps_of(d))
                ш = step(d, "правка_видео")
                self.assertTrue((ш.get("chosen") or {}).get("model"), ш)
                self.assertIn("usd", str((ш.get("chosen") or {}).get("price")))
                self.assertIn("text_edit_in_video", note_ids(d))

    def test_a_face_as_the_target_keeps_the_task(self) -> None:
        spec = _spec({"task": "face-replace", "inputs": VID, "outputs": ["video"], "people": [STAFF]})
        for brief in ("Swap the actor's face and keep the sign as it is, the sign text is fine",
                      "Put my face on the presenter; also change the text on the banner",
                      "Замените лицо ведущего, надпись на вывеске оставьте",
                      "Поставьте моё лицо вместо актёра и исправьте надпись на табличке"):
            with self.subTest(brief=brief):
                self.assertEqual(ei.reroute(spec, brief)[0].task, "face-replace")

    def test_people_words_in_the_shot_are_not_a_target(self) -> None:
        for brief in ("two people walk past the shop sign — change the sign text",
                      "the presenter holds a box: replace the label text on the box",
                      "актёр стоит у двери — замените надпись на табличке",
                      "fix the typo on the whiteboard behind the speaker"):
            with self.subTest(brief=brief):
                self.assertTrue(ei.TEXT_EDIT_WORDS.search(brief))
                self.assertIsNone(ei.PERSON_EDIT.search(brief), brief)


# --- 4. upscalers -----------------------------------------------------------------------------


def _upscaler(model: str, endpoint: str, *rows: tuple[str, str], tier: str = "portal") -> list[Fact]:
    u = f"https://fal.ai/api/openapi/queue/openapi.json?endpoint_id={endpoint}"
    return [
        F(model, "availability", f"on fal.ai as {endpoint} (video-to-video)", u),
        F(model, "accepts_inputs", "видео", u),
        F(model, "requires_inputs", "видео", u),
        F(model, "produces_outputs", "видео", u),
        F(model, "price_unit_second_usd", "$0.05 per second", u),
        *[F(model, a, v, u, tier) for a, v in rows],
    ]


class UpscaleReachTested(unittest.TestCase):
    def test_tested_ceiling_below_target_is_schema_only(self) -> None:
        rows = [F("m", "upscale_factor_max", "4 (schema 1-4)"), F("m", "tested_output_ceiling", "1440p in the paper", tier="paper")]
        self.assertEqual(ur.reach_state(rows, 4320, 1080)[0], ur.REACH_UNTESTED)
        self.assertEqual(ur.reach_state(rows, 1440, 1080)[0], ur.REACH_YES)
        self.assertEqual(ur.reach_state(rows[:1], 4320, 1080)[0], ur.REACH_YES)
        # Без кадра исходника множитель ничего не решает: проверенный предел не повышает «не записано».
        self.assertEqual(ur.reach_state(rows, 4320, None)[0], ur.REACH_UNKNOWN)

    def test_per_frame_image_upscaler_on_video(self) -> None:
        rows = [F("m", "upscale_factor_max", "8 (schema 1-8)"), F("m", "architecture", "RealESRGAN on each frame")]
        self.assertEqual(ur.reach_state(rows, 4320, 1080, video=True)[0], ur.REACH_UNTESTED)
        self.assertEqual(ur.reach_state(rows, 4320, 1080)[0], ur.REACH_YES)
        self.assertEqual(ur.per_frame([F("m", "positioning", "покадровый апскейл")]), "https://example.org/x")
        self.assertEqual(ur.per_frame([F("m", "architecture", "temporal transformer")]), "")

    def test_order(self) -> None:
        self.assertEqual(
            sorted([ur.REACH_BELOW, ur.REACH_UNKNOWN, ur.REACH_UNTESTED, ur.REACH_YES], key=ur.REACH_ORDER.__getitem__),
            [ur.REACH_YES, ur.REACH_UNTESTED, ur.REACH_UNKNOWN, ur.REACH_BELOW],
        )

    def test_reaching_by_record_ranks_before_schema_only(self) -> None:
        op = next(o for o in planner.OPERATIONS if o.name == "апскейл")
        cheap = _upscaler("fast-upscale-video", "fal-ai/fast/upscale/video", ("upscale_factor_max", "4 (schema 1-4)"))
        cheap += [F("fast-upscale-video", "tested_output_ceiling", "1440p in the paper", tier="paper")]
        dear = _upscaler("solid-upscale-video", "fal-ai/solid/upscale/video", ("upscale_factor_max", "10 (schema 1-10)"))
        dear = [F(f.model, f.attribute, "$0.09 per second", f.source_url) if f.attribute.startswith("price") else f for f in dear]
        k = planner.candidates_for(op, FactIndex(facts=cheap + dear), upscale_target=(7680, 4320), source_frame=(1920, 1080))
        self.assertEqual(k[0].model, "solid-upscale-video")
        self.assertTrue(k[1].reach_note.startswith(ur.REACH_UNTESTED))


EIGHT_K_LED = (
    ("Upscale our 4K concert footage to 8K for the LED wall at the arena, one minute", "3840x2160", 60),
    ("Апскейл ролика 1080p до 8K для светодиодного экрана на стадионе, 30 секунд", "1920x1080", 30),
    ("Our 1080p brand film must play at 7680x4320 on a museum LED wall, 15 s", "1920x1080", 15),
    ("Поднимите наше 4K-видео до 8K для LED-стены в лобби, 20 секунд", "3840x2160", 20),
)


class EightKLedWall(unittest.TestCase):
    def test_reaches_8k_by_record(self) -> None:
        idx = FactIndex()
        for brief, src, s in EIGHT_K_LED:
            with self.subTest(brief=brief):
                d = plan(brief, {"task": "upscale", "inputs": [{"kind": "video", "owned": True, "resolution": src, "duration_s": s}],
                                 "outputs": ["video"], "resolution": "8k", "people": [], "jurisdiction": ["US"]})
                модель = (step(d, "апскейл").get("chosen") or {}).get("model")
                self.assertTrue(модель)
                строки = [f for f in idx.facts if f.model == модель]
                короткая = min(int(x) for x in src.split("x"))
                self.assertEqual(ur.reach_state(строки, 4320, короткая, video=True)[0], ur.REACH_YES, модель)


class AlphaOnlyWhenOrdered(unittest.TestCase):
    def test_alpha_specialised(self) -> None:
        self.assertTrue(ur.alpha_specialised("topaz-upscale-image-transparent", []))
        self.assertTrue(ur.alpha_specialised("x", [F("x", "best_for", "assets with transparency, alpha channel kept")]))
        self.assertFalse(ur.alpha_specialised("x", [F("x", "price", "preserves the alpha channel")]))
        self.assertFalse(ur.alpha_specialised("seedvr2-upscale-image", [F("x", "best_for", "photos")]))

    def test_opaque_frames_get_an_ordinary_upscaler(self) -> None:
        idx = FactIndex()
        for brief, lang in (("Product zoom: enlarge the packshot so we can crop into the label", "en"),
                            ("Upscale our hero shot of a glass perfume bottle 4x for the homepage", "en"),
                            ("Увеличьте фото товара для зума на карточке маркетплейса", "ru"),
                            ("Апскейл кадра с прозрачным флаконом для баннера", "ru")):
            with self.subTest(brief=brief):
                d = plan(brief, {"task": "upscale", "inputs": [{"kind": "image", "owned": True}], "outputs": ["image"],
                                 "shots": 1, "languages": [lang], "people": [], "jurisdiction": ["US"]})
                модель = (step(d, "апскейл_изображения").get("chosen") or {}).get("model")
                self.assertTrue(модель)
                self.assertFalse(ur.alpha_specialised(модель, [f for f in idx.facts if f.model == модель]), модель)

    def test_alpha_ordered_keeps_the_alpha_upscaler(self) -> None:
        d = plan("Upscale our logo PNG 4x on a transparent background, keep the alpha",
                 {"task": "upscale", "inputs": [{"kind": "image", "owned": True}], "outputs": ["image"], "shots": 1,
                  "people": [], "jurisdiction": ["US"], "conditions": ["transparent background"]})
        отсеяны = {х["model"] for х in step(d, "апскейл_изображения").get("hard_excluded") or []}
        self.assertNotIn("topaz-upscale-image-transparent", отсеяны)


# --- 5. face-swap data sets -------------------------------------------------------------------

ACTORS = {"name": "actors", "real": True, "public_figure": False, "consent": "stated", "claim": "none"}


class FaceSwapDataSets(unittest.TestCase):
    def test_route(self) -> None:
        кадры = _spec({"task": "face-replace", "inputs": [{"kind": "video", "owned": True}, {"kind": "image", "owned": True}],
                       "outputs": ["image"], "shots": 400, "people": []})
        м = bs.route(кадры)
        self.assertEqual(м.шаги, ("замена_лица_изображения",))
        self.assertEqual(м.штук, {"замена_лица_изображения": 400})
        self.assertIn(bs.NOTE_FRAMES_FROM_VIDEO, м.сборка)
        видео = _spec({"task": "face-replace", "inputs": [{"kind": "video", "owned": True}, {"kind": "image", "owned": True}],
                       "outputs": ["video"], "duration_s": 10, "people": []})
        self.assertEqual(bs.route(видео).шаги, ("замена_персонажа",))
        оба = _spec({"task": "face-replace", "inputs": [{"kind": "video", "owned": True}, {"kind": "image", "owned": True}],
                     "outputs": ["video", "image"], "duration_s": 10, "people": []})
        self.assertIn("замена_персонажа", bs.route(оба).шаги)
        снимок = _spec({"task": "face-replace", "inputs": [{"kind": "image", "owned": True, "count": 2}], "outputs": ["image"],
                        "people": []})
        self.assertEqual(bs.route(снимок).сборка, ())

    def test_items_counted(self) -> None:
        self.assertEqual(bs.FACE_SWAP_BATCH_MIN, 10)
        def n(**raw: object) -> int:
            return bs.face_swap_items(_spec({"task": "face-replace", "outputs": ["image"], "people": [], **raw}))
        self.assertEqual(n(inputs=[{"kind": "image", "owned": True, "count": 300}, {"kind": "image", "owned": True, "count": 5}]), 300)
        self.assertEqual(n(inputs=[{"kind": "image", "owned": True, "count": 10}]), 10)
        self.assertEqual(n(inputs=[{"kind": "image", "owned": True, "count": 9}]), 0)
        self.assertEqual(n(inputs=[{"kind": "image", "owned": True, "count": 300}], shots=50), 50)

    def test_data_set_is_priced_per_item(self) -> None:
        for brief, lang, inputs, count in (
            ("Build a face-swap training set: 1000 swapped frames from our stock videos with faces of our consenting actors",
             "en", [{"kind": "video", "owned": True, "count": 10}, {"kind": "image", "owned": True, "count": 5}], 1000),
            ("Датасет: 300 фото с заменой лиц наших сотрудников (согласие есть) для обучения модели", "ru",
             [{"kind": "image", "owned": True, "count": 300}, {"kind": "image", "owned": True, "count": 5}], 300),
        ):
            with self.subTest(brief=brief):
                d = plan(brief, {"task": "face-replace", "inputs": inputs, "outputs": ["image"], "languages": [lang],
                                 "people": [ACTORS], "jurisdiction": ["US"]}
                         if lang == "ru" else
                         {"task": "face-replace", "inputs": inputs, "outputs": ["image"], "shots": count,
                          "languages": [lang], "people": [ACTORS], "jurisdiction": ["US"]})
                self.assertEqual(steps_of(d), ["замена_лица_изображения"])
                ш = step(d, "замена_лица_изображения")
                self.assertEqual(ш.get("shots"), count)
                self.assertRegex(str((ш.get("chosen") or {}).get("price")), rf"{count} (?:image|кадр)")
                self.assertIn("face_swap_dataset_consent", note_ids(d))
                self.assertIn("outputs_as_training_data", note_ids(d))

    def test_refused_without_consent(self) -> None:
        for brief, consent in (("Swap faces in 300 photos of people from the street for our data set", "none"),
                               ("Замените лица на 300 фото прохожих для нашего датасета", "none")):
            with self.subTest(brief=brief):
                d = plan(brief, {"task": "face-replace", "inputs": [{"kind": "image", "owned": True, "count": 300}],
                                 "outputs": ["image"], "shots": 300, "jurisdiction": ["US"],
                                 "people": [{"name": "passers-by", "real": True, "public_figure": False, "consent": consent,
                                             "claim": "none"}]})
                self.assertEqual(d.get("outcome"), "fail")
                self.assertFalse(d.get("steps"))


if __name__ == "__main__":
    unittest.main()
