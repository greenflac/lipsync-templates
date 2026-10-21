"""Round 17 integration: the missing routes (`routes_r17`) × the specialist knowledge (`expert_r17`).

Each case is an order where a route of one branch meets a decision of the other on the same footage;
literal steps, notes and price lines; negatives keep each side's own plan. Every brief is a paraphrase
written for this file, never a dev or holdout brief. No network (T4).

(a) a recap (cut-to-shorts / video-edit) of footage with burned-in subtitles to translate: the removal
    of the old band stays beside the recap, priced on the RECAP's seconds, the transcript once;
(b) code-switching speech + burned-in subtitles to translate: the `mul` tag is the source's mixed
    speech, never a translation target (the translation is priced for the real targets only);
(c) blur-background + replace-person on the same footage: both edits stay (the matte over the
    replaced footage, the blur at assembly);
(d) a UGC product batch made from a client's product photos: the shared stills and the
    provider-data caveat together;
(e) a singer's music video + stem separation (`delivery.stems`): the performer route keeps its lip
    sync seconds and the stem caveats fire.

SAFETY REVIEW of `studio/consented_simulation.py` (the consented internal drill door): it never opens
for a public figure who is not the customer's own staff, a minor (field or words), unknown / none
consent, a non-employee, an external or mixed platform, a political or endorsement claim, a
fabricated claim, a real brand, or an audience other than the customer's adult staff; and every
other screen's refusal still holds (the door only lifts the public-statement rule). The screens
themselves are called, never read here.
"""

from __future__ import annotations

import json
import os
import re
import unittest
from typing import Any

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from lipsync.fork_identity import PASS  # noqa: E402
from studio import brief_spec as bs  # noqa: E402
from studio import consented_simulation as cs  # noqa: E402
from studio import routes_r17 as r17  # noqa: E402
from studio.mcp import server  # noqa: E402
from studio.recipes import apply as ra  # noqa: E402

_PLANS: dict[str, dict] = {}


def plan(brief: str, spec: dict) -> dict:
    ключ = brief + json.dumps(spec, sort_keys=True, ensure_ascii=False)
    if ключ not in _PLANS:
        _PLANS[ключ] = json.loads(server.plan_pipeline(brief, spec=spec))
    return _PLANS[ключ]


def steps_of(d: dict) -> list[str]:
    return [str(ш.get("step")) for ш in d.get("steps") or []]


def price_of(d: dict, name: str) -> str:
    for ш in d.get("steps") or []:
        if ш.get("step") == name:
            return str((ш.get("chosen") or {}).get("price") or "")
    raise AssertionError(f"no step {name}: {steps_of(d)}")


def notes(d: dict) -> list[str]:
    return [str(н.get("id")) for н in d.get("production_notes") or []]


def assembly(d: dict) -> str:
    return " | ".join(str(с) for с in (d.get("assembly") or {}).get("why") or [])


def applied(brief: str, raw: dict) -> ra.Applied:
    spec, errors = bs.parse_spec(raw)
    assert not errors, errors
    spec = bs.with_defaults(spec, ролик=True, текст=brief)
    return ra.rewrite(spec, bs.route(spec), brief)


def w(base: dict, **more: Any) -> dict:
    return {**base, **more}


def V(**more: Any) -> dict:
    return {"kind": "video", "owned": True, "duration_s": 60, **more}


def refused(d: dict) -> bool:
    return d.get("outcome") == "fail" and not d.get("steps")


# --- (a) recap + burned-in subtitles ------------------------------------------------------------------

SHORTS = {"task": "cut-to-shorts", "inputs": [V(subtitles="burned", duration_s=7200)], "outputs": ["video"],
          "duration_s": 90, "languages": ["en"], "people": []}
RECAP_EDIT = w(SHORTS, task="video-edit")


class ПересказИВшитыеСубтитры(unittest.TestCase):
    def test_нарезка_снимает_старую_полосу(self) -> None:
        for brief in ("Cut a 90-second recap of our series; the subtitles are burned in, translate them to English",
                      "Нарезка на 90 секунд из нашего сериала, вшитые субтитры перевести на английский",
                      "Un resumen de 90 segundos de nuestra serie, con los subtítulos traducidos al inglés"):
            d = plan(brief, SHORTS)
            self.assertEqual(["правка_видео", "расшифровка"], sorted(steps_of(d)), brief)
            self.assertRegex(price_of(d, "правка_видео"), r"\b90 [sс] ×", brief)
            self.assertRegex(price_of(d, "расшифровка"), r"\b7200 [sс] ×", brief)
            self.assertIn("burned_subtitles_translation", notes(d))
            self.assertIn("highlight_selection", notes(d))
            self.assertIn("Google Cloud Translation", assembly(d))

    def test_нарезка_без_вшитых_без_правки(self) -> None:
        d = plan("Cut a 90-second recap of our series", w(SHORTS, inputs=[V(subtitles="none", duration_s=7200)]))
        self.assertEqual(["расшифровка"], steps_of(d))
        self.assertNotIn("burned_subtitles_translation", notes(d))

    def test_секунды_правки_по_нарезке(self) -> None:
        а = applied("x", w(SHORTS, shots=3))
        self.assertEqual((90.0, 30.0), а.step_seconds["правка_видео"])
        self.assertIn("правка_видео", а.route.шаги)

    def test_пересказ_правкой_держит_снятие(self) -> None:
        brief = "Recap of our series; translate the burned-in subtitles to English"
        d = plan(brief, RECAP_EDIT)
        self.assertEqual(["правка_видео", "расшифровка"], sorted(steps_of(d)))
        self.assertIn("highlight_selection", notes(d))
        self.assertRegex(assembly(d), "picked from shot changes")
        # without burned subtitles the recap edit is still the cut (knowledge branch, unchanged)
        d = plan("Recap of our series", w(RECAP_EDIT, inputs=[V(subtitles="none", duration_s=7200)]))
        self.assertEqual(["расшифровка"], steps_of(d))

    def test_строка_своих_субтитров_уходит(self) -> None:
        d = plan("Translate the burned-in subtitles of our promo into English",
                 {"task": "video-edit", "inputs": [V(subtitles="burned")], "outputs": ["video"], "duration_s": 60,
                  "languages": ["en"], "people": []})
        self.assertNotIn("no transcription needed", assembly(d))
        self.assertIn("burned in at assembly (ffmpeg subtitles / libass", assembly(d))
        # the line stays where it is true: the customer's own subtitle file burned in
        а = applied("Burn our SRT subtitles into the video",
                    {"task": "video-edit", "inputs": [V(), {"kind": "text", "owned": True}], "outputs": ["video"],
                     "duration_s": 60, "edit": ["burn-captions"], "languages": ["en"], "people": []})
        self.assertIn(bs.NOTE_BURN_CAPTIONS, а.route.сборка)


# --- (b) code-switching + burned-in subtitles ------------------------------------------------------------

MIXED = {"task": "video-edit", "inputs": [V(subtitles="burned", duration_s=60)], "outputs": ["video"],
         "duration_s": 60, "languages": ["mul", "en"], "people": []}


class СмешениеЯзыковИСубтитры(unittest.TestCase):
    def test_mul_не_цель_перевода(self) -> None:
        for brief in ("Translate the burned-in subtitles of our Spanglish promo into English",
                      "Переведите вшитые субтитры нашего ролика на английский, речь вперемешку",
                      "Traduisez les sous-titres incrustés de notre pub en anglais"):
            d = plan(brief, MIXED)
            self.assertEqual(["правка_видео", "расшифровка"], sorted(steps_of(d)), brief)
            self.assertIn("code_switching_speech", notes(d), brief)
            self.assertIn("burned_subtitles_translation", notes(d), brief)
            self.assertIn("≈900 chars × 20 usd per 1M = 0.02 usd", assembly(d), brief)
            self.assertRegex(price_of(d, "расшифровка"), r"\b60 [sс] × 0\.008 usd/(min|мин)", brief)

    def test_две_цели_считаются_дважды(self) -> None:
        d = plan("Translate the burned-in subtitles into English and German", w(MIXED, languages=["mul", "en", "de"]))
        self.assertIn("≈1800 chars × 20 usd per 1M = 0.04 usd", assembly(d))


# --- (c) blur-background + replace-person ------------------------------------------------------------

BOTH = {"task": "video-edit", "inputs": [V(duration_s=20), {"kind": "image", "owned": True}], "outputs": ["video"],
        "duration_s": 20, "edit": ["blur-background", "replace-person"], "languages": [], "people": []}


class РазмытиеИЗаменаЧеловека(unittest.TestCase):
    def test_обе_правки_остаются(self) -> None:
        for brief in ("Replace the presenter with our character and blur the background",
                      "Замените ведущего нашим персонажем и размойте фон",
                      "Ersetzen Sie den Moderator durch unsere Figur und machen Sie den Hintergrund unscharf"):
            d = plan(brief, BOTH)
            self.assertEqual(["замена_фигуры", "удаление_фона_видео"], steps_of(d), brief)
            self.assertRegex(price_of(d, "замена_фигуры"), r"\b20 [sс] × 0\.08 usd/[sс] = 1\.60 usd")
            self.assertRegex(price_of(d, "удаление_фона_видео"), r"\b20 [sс] × 0\.05 usd/[sс] = 1\.00 usd")
            self.assertIn("background_blur", notes(d))
            self.assertRegex(assembly(d), "blurred under the matte|размытие фона по маске")

    def test_каждая_отдельно_как_прежде(self) -> None:
        d = plan("Replace the presenter with our character", w(BOTH, edit=["replace-person"]))
        self.assertEqual(["замена_фигуры"], steps_of(d))
        d = plan("Blur the background", w(BOTH, edit=["blur-background"], inputs=[V(duration_s=20)]))
        self.assertEqual(["удаление_фона_видео"], steps_of(d))

    def test_без_референса_референс_первым(self) -> None:
        а = applied("x", w(BOTH, inputs=[V(duration_s=20)]))
        self.assertEqual(("генерация_изображения", "замена_фигуры", "удаление_фона_видео"), а.route.шаги)


# --- (d) UGC batch + provider data terms ----------------------------------------------------------------

UGC = {"task": "generate", "inputs": [{"kind": "photo", "owned": True, "count": 4}], "outputs": ["video", "speech"],
       "shots": 12, "per_shot_s": 15, "products": 4, "languages": ["en"], "aspect": "9:16",
       "delivery": {"platform": ["tiktok"]}, "subject": ["product"], "training_use": True,
       "people": [{"name": "creator", "real": False, "on_screen": True, "speaks": True}]}


class ПачкаUGCИУсловияПровайдера(unittest.TestCase):
    def test_общие_кадры_и_условия(self) -> None:
        for brief in ("12 UGC clips for TikTok Shop from our client's product photos",
                      "12 UGC-роликов для тикток-шопа по фото товаров клиента",
                      "12 vídeos UGC para TikTok Shop con las fotos de producto de nuestro cliente"):
            d = plan(brief, UGC)
            self.assertRegex(price_of(d, "генерация_изображения"), r"\] 1 (image\(s\)|кадр\(ов\)) ×", brief)
            self.assertIn("provider_data_terms", notes(d), brief)
            self.assertIn("outputs_as_training_data", notes(d), brief)

    def test_свой_сервер_молчит(self) -> None:
        d = plan("12 UGC clips for TikTok Shop from our client's product photos", w(UGC, self_host=True))
        self.assertNotIn("provider_data_terms", notes(d))


# --- (e) singer music video + stem separation --------------------------------------------------------

SINGER = {"name": "Mara", "real": True, "public_figure": False, "consent": "stated", "role": "talent",
          "on_screen": True, "speaks": True}
MV = {"task": "r2v", "inputs": [{"kind": "image", "owned": True, "count": 3}, {"kind": "audio", "owned": True, "duration_s": 180}],
      "outputs": ["video"], "duration_s": 180, "shots": 12, "languages": ["en"], "audio_content": ["song"],
      "performer_shots": 6, "delivery": {"stems": True}, "people": [SINGER]}


class КлипИСтемы(unittest.TestCase):
    def test_клип_держит_липсинк_и_стемы(self) -> None:
        for brief in ("Music video for our singer, and deliver the stems of the track",
                      "Клип для нашей певицы, плюс стемы трека",
                      "Videoclip para nuestra cantante, entregar también los stems"):
            d = plan(brief, MV)
            self.assertEqual(["генерация_изображения", "липсинк", "видео_по_референсу", "оживление"],
                             sorted(steps_of(d), key=["генерация_изображения", "липсинк", "видео_по_референсу",
                                                       "оживление"].index), brief)
            self.assertRegex(price_of(d, "липсинк"), r"\b90 [sс] ×", brief)
            self.assertIn("stem_separation", notes(d), brief)
            self.assertIn("singing_vocal_stem", notes(d), brief)

    def test_без_стемов_молчит(self) -> None:
        d = plan("Music video for our singer", w(MV, delivery={}))
        self.assertNotIn("stem_separation", notes(d))
        self.assertRegex(price_of(d, "липсинк"), r"\b90 [sс] ×")


# --- SAFETY REVIEW: the consented internal drill door --------------------------------------------------

CEO = {"name": "Anna Berg", "real": True, "public_figure": True, "role": "employee", "consent": "stated",
       "claim": "news", "on_screen": True, "speaks": True}
DRILL = {"task": "avatar", "inputs": [{"kind": "video", "owned": True, "duration_s": 120}, {"kind": "text", "owned": True}],
         "outputs": ["video", "speech"], "duration_s": 60, "languages": ["en"], "people": [CEO],
         "domain": ["security-awareness"], "delivery": {"platform": ["internal"]}, "live": False}
B = "Security awareness drill: a deepfake of our CEO Anna Berg announcing an urgent acquisition, internal only"


class ДверьУчений(unittest.TestCase):
    def test_открыта_только_в_узком_случае(self) -> None:
        d = plan(B, DRILL)
        self.assertFalse(refused(d))
        self.assertEqual("consented_simulation", d["consented_simulation"]["rule"])

    def test_никогда_не_открывается(self) -> None:
        закрыто = {
            "public figure not staff": w(DRILL, people=[{**CEO, "role": "other"}]),
            "public figure, no role": w(DRILL, people=[{k: v for k, v in CEO.items() if k != "role"}]),
            "hired actor": w(DRILL, people=[{**CEO, "role": "talent"}]),
            "minor (field)": w(DRILL, people=[{**CEO, "minor": True}]),
            "consent unknown": w(DRILL, people=[{**CEO, "consent": "unknown"}]),
            "consent none": w(DRILL, people=[{**CEO, "consent": "none"}]),
            "consent absent": w(DRILL, people=[{k: v for k, v in CEO.items() if k != "consent"}]),
            "external platform": w(DRILL, delivery={"platform": ["youtube"]}),
            "mixed platform": w(DRILL, delivery={"platform": ["internal", "linkedin"]}),
            "no platform": w(DRILL, delivery={}),
            "another domain": w(DRILL, domain=["corporate"]),
            "political person claim": w(DRILL, people=[{**CEO, "claim": "political"}]),
            "endorsement person claim": w(DRILL, people=[{**CEO, "claim": "endorsement"}]),
            "political claim": w(DRILL, claims=[{"type": "political"}]),
            "election claim": w(DRILL, claims=[{"type": "election"}]),
            "endorsement claim": w(DRILL, claims=[{"type": "endorsement"}]),
            "fabricated news claim": w(DRILL, claims=[{"type": "news", "fabricated": True}]),
            "fabricated other claim": w(DRILL, claims=[{"type": "other", "fabricated": True}]),
            "real brand": w(DRILL, claims=[{"type": "other", "real_brand": True}]),
            "audience children": w(DRILL, audience="children"),
            "audience teens": w(DRILL, audience="teens"),
            "audience general public": w(DRILL, audience="general"),
            "a second unconsented public figure": w(DRILL, people=[CEO, {
                "name": "Someone Famous", "real": True, "public_figure": True, "role": "other", "consent": "none",
                "claim": "news"}]),
        }
        for что, raw in закрыто.items():
            d = plan(B, raw)
            self.assertTrue(refused(d), что)
            self.assertNotIn("consented_simulation", d, что)

    def test_слова_только_закрывают(self) -> None:
        for brief in (
            "Security drill: a deepfake of our CEO Anna Berg urging staff to vote for a candidate, internal only",
            "Учения: дипфейк гендиректора Анны Берг агитирует за кандидата на выборах, только внутри",
            "Security drill: a deepfake of our CEO Anna Berg with her 12-year-old daughter, internal only",
            "Учения: дипфейк гендиректора Анны Берг вместе с её дочерью, только внутри",
        ):
            d = plan(brief, DRILL)
            self.assertTrue(refused(d), brief)
            self.assertNotIn("consented_simulation", d, brief)
        # and no word opens it: the same words with an external platform stay refused
        d = plan("Internal security-awareness drill, consented, staff only", w(DRILL, delivery={"platform": ["tiktok"]}))
        self.assertTrue(refused(d))

    def test_взрослые_сотрудники_проходят(self) -> None:
        d = plan(B, w(DRILL, audience="adults"))
        self.assertFalse(refused(d))
        self.assertIn("consented_simulation", d)
        d = plan(B, w(DRILL, people=[{**CEO, "role": "self", "minor": False}]))
        self.assertIn("consented_simulation", d)

    def test_прочие_отказы_держатся(self) -> None:
        # A refusal some OTHER screen makes for a consented private employee stays a refusal with the
        # drill fields on (the door lifts only the public-statement rule).
        частный = {**CEO, "public_figure": False, "claim": "other"}
        for brief in ("Security drill: a nude deepfake of our CEO Anna Berg, internal only",):
            без_двери = plan(brief, w(DRILL, people=[частный]))
            self.assertTrue(refused(без_двери), brief)
            d = plan(brief, DRILL)
            self.assertTrue(refused(d), brief)
            self.assertNotIn("consented_simulation", d, brief)
        # an unsubstantiated regulated claim (claims_policy) is still refused behind the open door
        d = plan(B, w(DRILL, claims=[{"type": "health_claim", "substantiated": False}]))
        self.assertTrue(refused(d))

    def test_повторный_просев_решает(self) -> None:
        # decide() never lifts a refusal the re-screen keeps (topic screen or people policy).
        политика = {"decision": "refuse", "people": [{"name": "Anna Berg", "verdict": "refuse", "rule": cs.LIFTED_RULE}]}
        просев = {"outcome": "fail", "banned": ["public_statement"]}
        for повтор in (
            ({"outcome": "fail"}, {"decision": "proceed"}),
            ({"outcome": PASS}, {"decision": "refuse"}),
        ):
            self.assertEqual(cs.DECISION_NONE, cs.decide(DRILL, политика, просев, lambda _s, п=повтор: п, B)["decision"])
        ok = cs.decide(DRILL, политика, просев, lambda _s: ({"outcome": PASS}, {"decision": "proceed"}), B)
        self.assertEqual(cs.DECISION_ALLOW, ok["decision"])
        # another rule's refusal of the same person is never lifted
        другое = {"decision": "refuse", "people": [{"name": "Anna Berg", "verdict": "refuse", "rule": "minor"}]}
        self.assertEqual(cs.DECISION_NONE, cs.decide(DRILL, другое, просев,
                                                     lambda _s: ({"outcome": PASS}, {"decision": "proceed"}), B)["decision"])
        # the re-screen reads the people's claim as "other" and nothing else changes
        повторный = cs.as_drill(DRILL, ["Anna Berg"])
        self.assertEqual("other", повторный["people"][0]["claim"])
        self.assertEqual({k: v for k, v in DRILL.items() if k != "people"},
                         {k: v for k, v in повторный.items() if k != "people"})

    def test_поля_двери(self) -> None:
        self.assertFalse(cs.in_house({**CEO, "minor": True}))
        self.assertTrue(cs.in_house({**CEO, "minor": False}))
        self.assertTrue(cs.W_MINOR.search("a 12-year-old"))
        self.assertFalse(cs.W_MINOR.search("a 35-year-old CFO, sonic branding, season finale"))
        self.assertEqual(frozenset({"adults"}), cs.INTERNAL_AUDIENCES)
        self.assertTrue(re.search(r"\bfabricated\b", cs.__doc__ or ""))


# --- guard: the round-17 modules stay light (lazy server imports) ------------------------------------

class ЛёгкиеМодули(unittest.TestCase):
    def test_импорты(self) -> None:
        import ast
        from pathlib import Path

        корень = Path(__file__).resolve().parents[2]
        тяжёлые = {"studio.planner", "studio.mcp.server", "studio.recipes.apply", "studio.recipes.checklist",
                   "studio.endpoints", "studio.selfrag"}
        for файл in ("studio/routes_r17.py", "studio/consented_simulation.py", "studio/expert_r17.py"):
            дерево = ast.parse((корень / файл).read_text())
            for узел in дерево.body:
                if isinstance(узел, ast.ImportFrom) and узел.module:
                    имена = {узел.module, *(f"{узел.module}.{а.name}" for а in узел.names)}
                    self.assertFalse(имена & тяжёлые, (файл, узел.module))
                elif isinstance(узел, ast.Import):
                    self.assertFalse({а.name for а in узел.names} & тяжёлые, файл)
        self.assertTrue(r17.SUBTITLE_ADD_REMOVAL_TASKS >= {"dub-translate", "cut-to-shorts"})


if __name__ == "__main__":
    unittest.main()
