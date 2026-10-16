"""Round 10: general rules found by the hidden holdout, tested on the fixer's own paraphrases.

Each class guards one category, never a dev or holdout id: delivery notes (print,
interlaced tape, 8K, extreme fps), the advertising claims policy, whole-character
replacement, virtual try-on, self-host fit (VRAM, CPU-only) and the cheapest
objective leaving its evidence band. Expected values are literals (T2).
"""

from __future__ import annotations

import json
import os
import unittest

os.environ.setdefault("STUDIO_NO_JOURNAL", "1")

from studio import brief_spec as bs  # noqa: E402
from studio import claims_policy as cp  # noqa: E402
from studio import hardneed as hn  # noqa: E402
from studio import planner  # noqa: E402
from studio.recipes import apply as ra  # noqa: E402
from studio.recipes import delivery as dl  # noqa: E402
from studio.selfrag.facts import Fact  # noqa: E402


def _spec(**raw: object) -> bs.Spec:
    spec, errors, _ = bs.gaps(raw)
    assert not errors, errors
    return spec


def _fact(attribute: str, value: str) -> Fact:
    return Fact(model="m", attribute=attribute, value=value, source_url="https://example.org/x", tier="vendor", stated_on="2026-10-16")


class Печать(unittest.TestCase):
    def test_a2_при_300_dpi(self) -> None:
        spec = _spec(task="generate", inputs=[], outputs=["image"], shots=1, aspect="1:1.414", conditions=["печать A2"])
        self.assertEqual(((4961, 7016), "A2", 300), dl.print_frame(spec))

    def test_дюймы_и_альбомная_ориентация(self) -> None:
        spec = _spec(task="generate", inputs=[], outputs=["image"], shots=1, aspect="5:4", conditions=["printed at 8x10 in"])
        self.assertEqual(((3000, 2400), "8x10 in", 300), dl.print_frame(spec))

    def test_большой_формат_150_dpi(self) -> None:
        spec = _spec(task="generate", inputs=[], outputs=["image"], shots=1, conditions=["billboard 300x100 cm"])
        self.assertEqual(150, dl.print_frame(spec)[2])

    def test_принт_на_футболке_не_печать(self) -> None:
        spec = _spec(task="edit", inputs=[{"kind": "image", "owned": True}], outputs=["image"], shots=1)
        self.assertFalse(dl.is_print(spec, "put our printed t-shirt on a model"))
        self.assertTrue(dl.is_print(spec, "a poster for our shop"))

    def test_видео_не_печать(self) -> None:
        spec = _spec(task="generate", inputs=[], outputs=["video"], duration_s=5)
        self.assertFalse(dl.is_print(spec, "a poster-style video for print"))

    def test_нота_печати_с_пикселями(self) -> None:
        spec = _spec(task="generate", inputs=[], outputs=["image"], shots=1, conditions=["печать A2"])
        rows = ra.notes(spec, ["генерация_изображения"], english=True, text="")
        says = next(r["says"] for r in rows if r["id"] == "print_resolution")
        self.assertIn("4961x7016 px", says)
        self.assertIn("300 DPI", says)

    def test_апскейл_печати_на_молчании(self) -> None:
        spec = _spec(task="generate", inputs=[], outputs=["image"], shots=1)
        found = ra.frame_prior("генерация_изображения", (2400, 3000), spec, printed=True)
        self.assertEqual("print_upscale", found[0].id)
        self.assertIsNone(ra.frame_prior("генерация_изображения", (2000, 2000), spec, printed=True))
        self.assertIsNone(ra.frame_prior("генерация_изображения", (2400, 3000), spec, printed=False))

    def test_нота_печати_без_формата_просит_формат(self) -> None:
        spec = _spec(task="generate", inputs=[], outputs=["image"], shots=1)
        rows = ra.notes(spec, ["генерация_изображения"], english=False, text="постер для печати")
        says = next(r["says"] for r in rows if r["id"] == "print_resolution")
        self.assertIn("назовите формат", says)


class ДоставкаВидео(unittest.TestCase):
    def test_vhs_и_576i_чересстрочные(self) -> None:
        spec = _spec(task="restore", inputs=[{"kind": "video", "owned": True, "duration_s": 60}], outputs=["video"], duration_s=60)
        self.assertTrue(dl.interlaced_source(spec, "a VHS tape transfer"))
        self.assertTrue(dl.interlaced_source(spec, "оцифровка с кассеты"))
        self.assertTrue(dl.interlaced_source(spec, "digitised as 576i"))
        self.assertFalse(dl.interlaced_source(spec, "a phone video from 2019"))

    def test_8k_по_короткой_стороне(self) -> None:
        self.assertTrue(dl.eight_k(_spec(task="upscale", inputs=[{"kind": "video", "owned": True, "duration_s": 5}], outputs=["video"], resolution="8k")))
        self.assertFalse(dl.eight_k(_spec(task="upscale", inputs=[{"kind": "video", "owned": True, "duration_s": 5}], outputs=["video"], resolution="4k")))

    def test_экстремальная_частота_с_120(self) -> None:
        base = dict(task="interpolate", inputs=[{"kind": "video", "owned": True, "duration_s": 5}], outputs=["video"])
        self.assertTrue(dl.extreme_fps(_spec(**base, fps=120)))
        self.assertFalse(dl.extreme_fps(_spec(**base, fps=60)))

    def test_ноты_восьми_k_и_интерполяции(self) -> None:
        spec = _spec(task="interpolate", inputs=[{"kind": "video", "owned": True, "duration_s": 3}], outputs=["video"], fps=240)
        ids = [n for n, _ in ra.note_ids(spec, ["интерполяция_кадров"], text="")]
        self.assertEqual(["interp_artifacts"], ids)


class ЗаявленияВРекламе(unittest.TestCase):
    def test_текст_здоровье_en_ru(self) -> None:
        self.assertEqual(["health_claim"], cp.text_claims("our tea cures anxiety and lowers blood pressure"))
        self.assertEqual(["health_claim"], cp.text_claims("наша добавка излечивает диабет за месяц"))

    def test_текст_деньги_en_ru(self) -> None:
        self.assertEqual(["financial_claim"], cp.text_claims("guaranteed 30% monthly returns"))
        self.assertEqual(["financial_claim"], cp.text_claims("гарантированная доходность 40% годовых"))

    def test_окно_между_глаголом_и_болезнью(self) -> None:
        self.assertEqual(["health_claim"], cp.text_claims("it cures your chronic insomnia"))
        self.assertEqual(
            [], cp.text_claims("our bakery treats guests to fresh warm bread and coffee in the cold season")
        )

    def test_худшее_решение_побеждает(self) -> None:
        both = [{"type": "health_claim", "substantiated": False}, {"type": "financial_claim"}]
        self.assertEqual("refuse", cp.decide(both, "")["decision"])
        self.assertEqual([0, 1, 2], [cp.DECISION_RANK[d] for d in ("plan", "question", "refuse")])

    def test_негативный_контроль(self) -> None:
        for text in (
            "a 30 s ad for sparkling water",
            "guaranteed fun at our gym",
            "история открытия инсулина",
            "a rocket launch over the sea",
        ):
            self.assertEqual([], cp.text_claims(text), text)

    def test_политика_по_spec(self) -> None:
        self.assertEqual("refuse", cp.decide([{"type": "health_claim", "substantiated": False}], "")["decision"])
        self.assertEqual("question", cp.decide([{"type": "financial_claim"}], "")["decision"])
        self.assertEqual("plan", cp.decide([{"type": "financial_claim", "substantiated": True}], "")["decision"])
        self.assertEqual("question", cp.decide([], "it cures insomnia")["decision"])

    def test_разделение_spec(self) -> None:
        spec = {"claims": [{"type": "news", "fabricated": False}, {"type": "health_claim"}]}
        rest, own = cp.split(spec)
        self.assertEqual([{"type": "news", "fabricated": False}], rest["claims"])
        self.assertEqual([{"type": "health_claim"}], own)


class ЗаменаПерсонажаИПримерка(unittest.TestCase):
    def test_маскот_по_people(self) -> None:
        spec = _spec(
            task="face-replace",
            inputs=[{"kind": "video", "owned": True, "duration_s": 10}, {"kind": "image", "owned": True}],
            outputs=["video"],
            duration_s=10,
            people=[{"name": "orange fox mascot", "real": False, "public_figure": False, "consent": "unknown", "claim": "none"}],
        )
        self.assertTrue(ra.whole_character(spec))
        одно_слово = _spec(
            task="face-replace",
            inputs=[{"kind": "video", "owned": True, "duration_s": 10}],
            outputs=["video"],
            duration_s=10,
            people=[{"name": "the company mascot", "real": False, "public_figure": False, "consent": "unknown", "claim": "none"}],
        )
        self.assertTrue(ra.whole_character(одно_слово))

    def test_лицо_остаётся_лицом(self) -> None:
        spec = _spec(task="face-replace", inputs=[{"kind": "video", "owned": True, "duration_s": 10}], outputs=["video"], duration_s=10)
        self.assertFalse(ra.whole_character(spec, "put my face on the groom in our wedding clip"))
        self.assertFalse(ra.whole_character(spec, "put my face on the mascot costume"))
        self.assertTrue(ra.whole_character(spec, "swap the guy in the bunny suit for our cartoon mascot"))

    def test_примерка(self) -> None:
        spec = _spec(task="edit", inputs=[{"kind": "image", "owned": True}], outputs=["image"], shots=2)
        self.assertTrue(ra.wants_try_on(spec, "our dress worn by a generated model"))
        self.assertTrue(ra.wants_try_on(spec, "наденьте куртку на модель"))
        self.assertTrue(ra.wants_try_on(spec, "virtual try-on of our shirt"))
        self.assertFalse(ra.wants_try_on(spec, "remove the power lines from the photo"))
        self.assertFalse(ra.wants_try_on(spec, "a woman wearing sunglasses on the beach, change the sky"))


class РаботыРеестра(unittest.TestCase):
    def test_примерка_и_замена_персонажа_по_имени(self) -> None:
        from studio import endpoints as ep

        def работы(model: str) -> tuple[str, ...]:
            return tuple(sorted(ep.classify(model, [_fact("summary_line", "x")])[0]))

        self.assertEqual(("image-edit", "virtual-try-on"), работы("kolors-virtual-try-on"))
        self.assertEqual(("image-edit", "virtual-try-on"), работы("flux-pro-v1-vto"))
        self.assertEqual(("character-replace", "v2v-edit"), работы("wan-2.2-animate-mix"))


class СвояМашина(unittest.TestCase):
    def test_без_gpu_по_имени(self) -> None:
        for name in ("Raspberry Pi 5", "Raspberry Pi Zero 2 W", "none (CPU only)", "Intel NUC mini PC", "без видеокарты"):
            self.assertTrue(hn.CPU_ONLY.search(name), name)
        for name in ("RTX 3060", "Jetson Orin", "Apple M2 Pro"):
            self.assertFalse(hn.CPU_ONLY.search(name), name)

    def test_лестница_запуска_без_gpu(self) -> None:
        self.assertEqual(hn.CPU_ARM, hn.cpu_state([_fact("arm_inference", "yes — Raspberry Pi 4")])[0])
        self.assertEqual(hn.CPU_YES, hn.cpu_state([_fact("cpu_inference", "yes — onnxruntime")])[0])
        self.assertEqual(hn.CPU_NO, hn.cpu_state([_fact("cpu_inference", "not the 0.5B models")])[0])
        self.assertEqual(hn.CPU_UNKNOWN, hn.cpu_state([_fact("license", "mit")])[0])
        self.assertEqual([0, 1, 2, 3], [hn.CPU_ORDER[s] for s in (hn.CPU_ARM, hn.CPU_YES, hn.CPU_UNKNOWN, hn.CPU_NO)])

    def test_spec_платформа_cpu(self) -> None:
        spec = _spec(task="generate", inputs=[{"kind": "text", "owned": True}], outputs=["speech"], duration_s=5, languages=["en"], self_host={"gpu": "Raspberry Pi 4"})
        self.assertEqual("cpu", spec.self_host["platform"])

    def test_допуск_кадра(self) -> None:
        self.assertEqual(0.05, planner.FRAME_REACH_TOLERANCE)
        self.assertEqual(5.0, planner.CHEAP_OFFER_RATIO)


def _plan(brief: str, spec: dict) -> dict:
    from studio.mcp import server

    return json.loads(server.plan_pipeline(brief, spec=spec))


def _steps(d: dict) -> list[tuple[str, str]]:
    return [(s["step"], (s.get("chosen") or {}).get("model") or "") for s in d.get("steps") or []]


class ПланыПересказов(unittest.TestCase):
    """Integration on the fixer's paraphrases (studio/eval/paraphrase_r10*.jsonl), one per category."""

    def test_маскот_целиком(self) -> None:
        d = _plan(
            "Swap the guy in the bunny suit for our cartoon mascot Captain Crunchy in this 10 s clip",
            {"task": "face-replace", "inputs": [{"kind": "video", "owned": True, "duration_s": 10}, {"kind": "image", "owned": True}], "outputs": ["video"], "duration_s": 10, "people": []},
        )
        self.assertEqual(["замена_фигуры"], [s for s, _ in _steps(d)])
        self.assertIn("animate-replace", _steps(d)[0][1])

    def test_примерка_на_сгенерированной_модели(self) -> None:
        d = _plan(
            "Lookbook photos: our hoodie (product photo attached) on an AI model, 2 images",
            {"task": "edit", "inputs": [{"kind": "image", "owned": True}], "outputs": ["image"], "shots": 2, "people": []},
        )
        self.assertEqual(["генерация_изображения", "примерка"], [s for s, _ in _steps(d)])

    def test_raspberry_pi_не_chatterbox(self) -> None:
        d = _plan(
            "Синтез русской речи на Raspberry Pi 4 без интернета",
            {"task": "generate", "inputs": [{"kind": "text", "owned": True}], "outputs": ["speech"], "duration_s": 10, "languages": ["ru"], "self_host": {"gpu": "Raspberry Pi 4"}, "open_weights": True, "people": []},
        )
        self.assertEqual([("озвучка", "piper-tts")], _steps(d))

    def test_12_гб_не_14b(self) -> None:
        d = _plan(
            "Animate a photo locally on my RTX 3060 12GB, 5 s at 720p, open weights",
            {"task": "animate", "inputs": [{"kind": "image", "owned": True}], "outputs": ["video"], "duration_s": 5, "resolution": "720p", "self_host": {"gpu": "RTX 3060", "vram_gb": 12}, "open_weights": True, "people": []},
        )
        steps = _steps(d)
        self.assertEqual(["оживление"], [s for s, _ in steps])
        self.assertNotIn("14b", steps[0][1])

    def test_заявление_о_здоровье_вопрос(self) -> None:
        d = _plan(
            "Рекламный ролик 20 секунд: наша биодобавка избавляет от диабета за месяц",
            {"task": "generate", "inputs": [], "outputs": ["video", "speech"], "duration_s": 20, "languages": ["ru"], "people": []},
        )
        self.assertEqual("нужен_ответ_заказчика", d["reason"])
        self.assertEqual("question", d["claims_policy"]["decision"])

    def test_неподтверждённое_заявление_отказ(self) -> None:
        d = _plan(
            "30 s ad for our herbal tea, warm kitchen scene",
            {"task": "generate", "inputs": [], "outputs": ["video", "speech"], "duration_s": 30, "languages": ["en"], "people": [], "claims": [{"type": "health_claim", "substantiated": False}]},
        )
        self.assertEqual("запрещённая_тема", d["reason"])
        self.assertEqual([], d["steps"])

    def test_дешёвый_ugc_с_пометкой(self) -> None:
        d = _plan(
            "Cheapest lip sync of a 45 s UGC selfie video to a new voiceover; the creator consents",
            {"task": "lipsync", "inputs": [{"kind": "video", "owned": True, "duration_s": 45}, {"kind": "audio", "owned": True, "duration_s": 45}], "outputs": ["video"], "duration_s": 45, "languages": ["en"], "objective": "cheapest", "people": [{"name": "creator", "real": True, "public_figure": False, "consent": "stated", "claim": "none"}]},
        )
        swap = d["steps"][0]["budget_swap"]
        self.assertTrue(swap["label"].startswith(("unmeasured", "less evidence")))
        self.assertLess(d["pipeline_price"]["смета"]["usd"], 5.0)


if __name__ == "__main__":
    unittest.main()
