"""Девятый круг: пробелы знания и выбор модели (агент B).

Ожидания — литералы (Т2). Брифы здесь — ПЕРЕСКАЗ задач, а не строки набора
оценки: проверяется общая причина (факт, ярлык реестра, порядок), а не ответ
на конкретный бриф.

* свой Mac: запуск на MPS/MLX/Core ML по записи старше записанного CPU, тот
  старше молчания; единая память отсеивает веса больше машины;
* правка видео: продление — правка, выводится из длины; названная правка
  старше родного кадра; замена неба называет инпейнт; у локальной правки
  есть метод «маска + композит»;
* при названном бюджете кандидат, которого валидатор отвергнет, ниже
  неотвергнутого.
"""

from __future__ import annotations

import unittest

from studio import brief_spec as bs
from studio import endpoints as ep
from studio import hardneed as hn
from studio import planner as pn
from studio.selfrag.facts import Fact


def _факт(model: str, attribute: str, value: str) -> Fact:
    return Fact(model, attribute, value, f"https://{model}.test/{attribute}", "vendor", "2026-10-01")


class ЗапускНаMac(unittest.TestCase):
    def test_mps_записан(self) -> None:
        строки = [_факт("m", "apple_silicon", "runs via the PyTorch mps device")]
        self.assertEqual("запуск на GPU Mac (MPS / MLX / Metal / Core ML) записан", hn.apple_state(строки)[0])

    def test_core_ml_записан(self) -> None:
        строки = [_факт("m", "apple_silicon", "Apple publishes a Core ML conversion")]
        self.assertEqual(hn.APPLE_GPU, hn.apple_state(строки)[0])

    def test_только_cpu(self) -> None:
        строки = [_факт("m", "apple_silicon", "no MPS path: cuda if available, else the CPU")]
        self.assertEqual("на Mac записан только запуск на CPU", hn.apple_state(строки)[0])

    def test_cpu_вне_строки_о_mac_не_считается(self) -> None:
        строки = [_факт("m", "positioning", "int8 on CPU and GPU")]
        self.assertEqual("запуск на Mac не записан", hn.apple_state(строки)[0])

    def test_порядок_ступеней(self) -> None:
        self.assertEqual(
            {hn.APPLE_GPU: 0, hn.APPLE_CPU: 1, hn.APPLE_UNKNOWN: 2},
            hn.APPLE_ORDER,
        )

    def test_единая_память_отсеивает_веса_больше_машины(self) -> None:
        оп = next(o for o in pn.OPERATIONS if o.name == "генерация_изображения")
        строки = [
            Fact("big", "license", "apache-2.0", "https://huggingface.co/acme/big", "portal", "2026-10-01"),
            _факт("big", "parameter_count", "20B parameters"),
        ]
        mac = hn.Hard(self_host=True, gpu="applem1", apple_silicon=True, unified_memory_gb=8.0)
        итог = pn.требования_заказчика(оп, "big", строки, None, mac, {}, [], None, None)
        self.assertIn("единой памяти 8 ГБ, а нужно 20 ГБ", итог.исключить)
        большой = hn.Hard(self_host=True, gpu="applem1", apple_silicon=True, unified_memory_gb=64.0)
        self.assertEqual("", pn.требования_заказчика(оп, "big", строки, None, большой, {}, [], None, None).исключить)

    def test_spec_mac_доходит_до_жёстких_требований(self) -> None:
        итог = pn.plan(
            "Generate images locally on an Apple laptop with 8 GB",
            spec={
                "task": "generate",
                "inputs": [],
                "outputs": ["image"],
                "shots": 1,
                "self_host": {"gpu": "Apple M1", "unified_memory_gb": 8},
                "open_weights": True,
                "people": [],
            },
            spec_only=True,
        )
        self.assertTrue(итог["hard"]["apple_silicon"])
        self.assertEqual(8.0, итог["hard"]["unified_memory_gb"])
        # 20B весов (оценка снизу 20 ГБ) в 8 ГБ единой памяти не помещаются.
        self.assertNotEqual("qwen-image", итог["steps"][0]["chosen"]["model"])


class ПравкаВидео(unittest.TestCase):
    def test_продление_названо_эндпоинтом(self) -> None:
        self.assertIn("extend", ep.edit_intents("fal-ai/ltx-2.3/extend"))
        self.assertIn("extend", ep.edit_named("fal-ai/ltx-2.3/extend"))

    def test_продление_годится_только_когда_заказано(self) -> None:
        self.assertTrue(pn.продление_годится("fal-ai/ltx-2.3/extend", ("extend",)))
        self.assertFalse(pn.продление_годится("fal-ai/ltx-2.3/extend", ("replace-sky",)))
        self.assertFalse(pn.продление_годится("fal-ai/wan/v2.7/edit-video", ("extend",)))

    def test_замена_неба_называет_инпейнт(self) -> None:
        self.assertIn("replace-sky", ep.edit_named("fal-ai/ltx-2.3-quality/inpaint"))
        self.assertNotIn("replace-sky", ep.edit_named("fal-ai/wan/v2.7/edit-video"))

    def test_правка_старше_кадра_в_ключе(self) -> None:
        # (кадр, частота, язык, правка) -> (правка, кадр, частота, язык)
        self.assertEqual((1, 0, 0, 0), pn.порядок_требований((0, 0, 0, 1)))
        self.assertEqual((0, 1, 0, 0), pn.порядок_требований((1, 0, 0, 0)))
        self.assertEqual((), pn.порядок_требований(()))

    def test_продление_по_длине(self) -> None:
        def spec(выход: float, вход: float) -> bs.Spec:
            s, _ = bs.parse_spec(
                {
                    "task": "video-edit",
                    "inputs": [{"kind": "video", "owned": True, "duration_s": вход}],
                    "outputs": ["video"],
                    "duration_s": выход,
                }
            )
            return s

        self.assertTrue(bs.продление_по_длине(spec(10, 5)))
        self.assertFalse(bs.продление_по_длине(spec(5.4, 5)))
        self.assertFalse(bs.продление_по_длине(spec(5, 5)))
        self.assertEqual(1.2, bs.EXTEND_RATIO)

    def test_метод_локальной_правки(self) -> None:
        self.assertIn("mask", pn.EDIT_METHOD_NOTES["remove-object"])
        self.assertIn("composite", pn.EDIT_METHOD_NOTES["replace-sky"])
        self.assertNotIn("extend", pn.EDIT_METHOD_NOTES)


def _кандидат(имя: str, *, отвергнет: bool, против: int) -> pn.Candidate:
    return pn.Candidate(
        model=имя,
        evidence=(),
        applicability=2,
        capability=0,
        unresolved=0,
        price="цена не записана",
        anchored=2,
        against=против,
        refused=отвергнет,
    )


class ОтвергнутыйПриБюджете(unittest.TestCase):
    def test_отвергнутый_ниже(self) -> None:
        отвергнутый = _кандидат("а-отвергнутый", отвергнет=True, против=1)
        чистый = _кандидат("я-не-отвергнутый", отвергнет=False, против=1)
        порядок = sorted([отвергнутый, чистый], key=pn.by_evidence)
        self.assertEqual(["я-не-отвергнутый", "а-отвергнутый"], [c.model for c in порядок])

    def test_поле_в_ключе_и_в_списке(self) -> None:
        self.assertEqual(
            pn.KEY_FIELDS.index(pn.REFUSED_KEY_FIELD) + 1, pn.KEY_FIELDS.index(pn.CONDITION_KEY_FIELD)
        )
        self.assertEqual(len(pn.by_evidence(_кандидат("x", отвергнет=False, против=0))), len(pn.KEY_FIELDS))
        c = _кандидат("x", отвергнет=True, против=1)
        self.assertEqual("валидатор отвергнет", pn._поле(c, pn.KEY_FIELDS.index(pn.REFUSED_KEY_FIELD)))


class ЗапрещённыйВход(unittest.TestCase):
    def test_нечем_запустить(self) -> None:
        строки = [_факт("swap", "requires_inputs", "видео, изображение")]
        self.assertTrue(pn.нечем_запустить("swap", {"видео"}, строки))
        self.assertFalse(pn.нечем_запустить("swap", {"видео", "изображение"}, строки))

    def test_звук_принесённого_видео_доступен(self) -> None:
        строки = [_факт("clone", "requires_inputs", "аудио")]
        self.assertFalse(pn.нечем_запустить("clone", {"видео"}, строки))
        self.assertTrue(pn.нечем_запустить("clone", set(), строки))

    def test_без_строк_судить_не_по_чему(self) -> None:
        self.assertFalse(pn.нечем_запустить("x", set(), []))


class ЖивыеЗадачиДевятогоКруга(unittest.TestCase):
    """Пересказ задач, по живой базе: что выбрано и чем это доказано."""

    def _шаги(self, бриф: str, spec: dict) -> list:
        итог = pn.plan(бриф, spec=spec, spec_only=True)
        return [(ш["step"], (ш.get("chosen") or {}).get("model", "")) for ш in итог["steps"]]

    def test_замена_лица_на_видео_через_api(self) -> None:
        шаги = self._шаги(
            "Put my face onto the person in a short clip of my own",
            {
                "task": "face-replace",
                "inputs": [{"kind": "video", "owned": True, "duration_s": 12}, {"kind": "image", "owned": True}],
                "outputs": ["video"],
                "duration_s": 12,
                "people": [{"name": "me", "real": True, "public_figure": False, "consent": "stated", "claim": "none"}],
            },
        )
        self.assertEqual([("замена_персонажа", "wavespeed-video-face-swap")], шаги)

    def test_расшифровка_на_ноутбуке_не_диаризация(self) -> None:
        шаги = self._шаги(
            "Transcribe interviews offline on a laptop GPU with 8 GB",
            {
                "task": "transcribe",
                "inputs": [{"kind": "audio", "owned": True, "duration_s": 3600}],
                "outputs": ["text"],
                "duration_s": 3600,
                "languages": ["en"],
                "self_host": {"gpu": "RTX 4060 Laptop", "vram_gb": 8},
                "open_weights": True,
                "people": [],
            },
        )
        self.assertEqual(1, len(шаги))
        self.assertNotEqual("pyannote-speaker-diarization-3.1", шаги[0][1])
        self.assertIn("whisper", шаги[0][1])

    def test_музыка_на_своём_gpu(self) -> None:
        шаги = self._шаги(
            "Generate a track on my own 24 GB card, open weights",
            {
                "task": "generate",
                "inputs": [],
                "outputs": ["music"],
                "duration_s": 90,
                "self_host": {"gpu": "RTX 3090", "vram_gb": 24},
                "open_weights": True,
                "people": [],
            },
        )
        self.assertEqual([("музыка", "ace-step")], шаги)

    def test_липсинк_на_mac(self) -> None:
        шаги = self._шаги(
            "Lipsync my own clip to new audio locally on an Apple laptop",
            {
                "task": "lipsync",
                "inputs": [
                    {"kind": "video", "owned": True, "duration_s": 20},
                    {"kind": "audio", "owned": True, "duration_s": 20},
                ],
                "outputs": ["video"],
                "duration_s": 20,
                "languages": ["en"],
                "self_host": {"gpu": "Apple M2 Pro", "unified_memory_gb": 32},
                "open_weights": True,
                "people": [{"name": "me", "real": True, "public_figure": False, "consent": "stated", "claim": "none"}],
            },
        )
        self.assertIn(шаги[0][1], ("musetalk", "wav2lip"))

    def test_продление_ролика(self) -> None:
        шаги = self._шаги(
            "Make our 4 s clip run 8 s",
            {
                "task": "video-edit",
                "inputs": [{"kind": "video", "owned": True, "duration_s": 4}],
                "outputs": ["video"],
                "duration_s": 8,
                "people": [],
            },
        )
        self.assertEqual("правка_видео", шаги[0][0])
        self.assertIn("extend", шаги[0][1])


if __name__ == "__main__":
    unittest.main()
