"""Интеграция четвёртого круга: ОДНА спецификация заказа на отбор и цену.

`brief_spec` (поля от вызывающего поверх разбора текста) — публичная схема;
`hardneed.Hard` (свой GPU, цель, юрисдикция, кадр) строится из неё же
(`brief_spec.hard`). Тесты гоняют живую базу: бриф -> план -> выбранная модель.
"""

from __future__ import annotations

import unittest

import studio.planner as pn
from studio import brief_spec as bs


def _модели(итог: dict) -> dict[str, str | None]:
    return {ш["step"]: (ш.get("chosen") or {}).get("model") for ш in итог["steps"]}


class ОднаСпецификация(unittest.TestCase):
    def test_текст_и_spec_дают_одно_требование(self) -> None:
        бриф = "self-host on one RTX 4090, 1080p 5s"
        из_текста, _ = bs.resolve(бриф)
        из_spec, ошибки = bs.resolve(
            "a 5s clip", {"self_host": {"gpu": "RTX 4090"}, "resolution": "1080p", "duration_s": 5}
        )
        self.assertEqual([], ошибки)
        т = bs.hard(из_текста, бриф, None, bs.frame(из_текста))
        с = bs.hard(из_spec, "a 5s clip", None, bs.frame(из_spec))
        for т_или_с in (т, с):
            self.assertEqual(
                (True, "rtx-4090", 24.0, 1080),
                (т_или_с.self_host, т_или_с.gpu, т_или_с.vram_gb, т_или_с.resolution),
            )
        self.assertEqual("бриф", dict(т.sources)["self_host"])
        self.assertEqual("spec", dict(с.sources)["self_host"])

    def test_spec_self_host_false_перекрывает_текст(self) -> None:
        понято, _ = bs.resolve("self-host it", {"self_host": False})
        self.assertFalse(bs.hard(понято, "self-host it").self_host)
        # Негативный контроль: без spec текст делает запуск своим.
        понято, _ = bs.resolve("self-host it")
        self.assertTrue(bs.hard(понято, "self-host it").self_host)

    def test_цель_из_текста_и_из_spec(self) -> None:
        бриф = "4K 24fps cinematic 6s, no audio, quality over price"
        понято, _ = bs.resolve(бриф)
        self.assertEqual("quality", bs.hard(понято, бриф).objective)
        понято, _ = bs.resolve("6s clip", {"objective": "balanced"})
        self.assertEqual("balanced", bs.hard(понято, "6s clip").objective)
        # «premium» — описание кадра, не цель отбора.
        понято, _ = bs.resolve("premium product shot video 6s")
        self.assertEqual("", bs.hard(понято, "premium product shot video 6s").objective)

    def test_юрисдикция_страной_в_spec(self) -> None:
        понято, ошибки = bs.resolve("a clip", {"jurisdiction": "DE"})
        self.assertEqual([], ошибки)
        т = bs.hard(понято, "a clip", {"jurisdiction": "DE"})
        self.assertEqual((("EU",), ("DE",)), (т.jurisdiction, т.countries))


class СквозныеБрифы(unittest.TestCase):
    """Бриф -> план на живой базе: требования доходят до выбора модели.

    Ответ на английский бриф — по-английски (`studio/l10n.py`): ноты сверяются
    английскими формами.
    """

    def test_4k_качество_родная_4k_модель(self) -> None:
        итог = pn.plan("4K 24fps cinematic 6s, no audio, quality over price", full=True)
        self.assertEqual(("quality", 2160), (итог["hard"]["objective"], итог["hard"]["resolution"]))
        модель = _модели(итог)["генерация_видео"]
        self.assertIn("4k", модель or "")
        self.assertIn("the frame asked is native", итог["steps"][0]["hard_note"])
        # Апскейл не дописан: кадр родной.
        self.assertNotIn("апскейл", _модели(итог))

    def _свой_gpu(self, итог: dict, источник: str) -> None:
        self.assertEqual(
            (True, "rtx-4090", 24.0, источник),
            (
                итог["hard"]["self_host"],
                итог["hard"]["gpu"],
                итог["hard"]["vram_gb"],
                итог["hard"]["sources"]["self_host"],
            ),
        )
        шаг = итог["steps"][0]
        self.assertEqual("генерация_видео", шаг["step"])
        # Пятый круг: реестр добавил эндпоинт работы t2v, которого слова не
        # находили, — те же веса Wan2.2-TI2V-5B в формате diffusers. Узел
        # `wan-2.2-ti2v-5b` записан с родным кадром НИЖЕ 1080p и стоит соседом.
        self.assertEqual("wan2.2-ti2v-5b-diffusers", шаг["chosen"]["model"])
        self.assertIn("wan-2.2-ti2v-5b", [а["model"] for а in шаг["alternatives"]])
        self.assertIn("weights open", шаг["hard_note"])
        self.assertIn("fits the GPU memory", шаг["hard_note"])
        self.assertGreater(шаг["hard_excluded_count"], 0)

    def test_свой_gpu_текстом(self) -> None:
        self._свой_gpu(pn.plan("self-host on one RTX 4090, 1080p 5s", full=True), "brief")

    def test_свой_gpu_через_spec(self) -> None:
        итог = pn.plan(
            "a 5s clip",
            spec={
                "task": "generate",
                "outputs": ["video"],
                "self_host": {"gpu": "RTX 4090"},
                "resolution": "1080p",
                "duration_s": 5,
            },
            full=True,
        )
        self._свой_gpu(итог, "spec")

    def test_своё_видео_без_кадра_цена_по_стандарту(self) -> None:
        # Пятый круг: кандидаты замены — только эндпоинты работы face-swap
        # (прежде выбиралась r2v-генерация `seedance-2.5-r2v`). На живой базе
        # первым встаёт `bfs-best-face-swap` БЕЗ цены, и допущения кадра для
        # цены тогда нет; оно проверяется на базе, где из эндпоинтов face-swap
        # остался продаваемый с тарифом по кадру, а снимок для лица принесён.
        без = {"bfs-best-face-swap", "inswapper_128", "wan-animate-replace"}
        факты = [f for f in pn.FactIndex().facts if f.model not in без]
        spec = {"task": "face-replace", "inputs": ["video", "photo"], "duration_s": 20}
        итог = pn.plan(
            "replace the face in my 20s video with my character", facts=факты, spec=spec, full=True
        )
        выбран = итог["steps"][0]["chosen"]
        self.assertEqual("wan-2.2-14b-animate-replace", выбран["model"])
        self.assertIn("[720p below the ordered 1080p", выбран["price"])
        self.assertTrue(
            any("1080p assumed for pricing" in д for д in итог["understood_as"]["assumptions"])
        )
        # Негативный контроль: названный кадр — без допущения.
        итог = pn.plan(
            "replace the face in my 20s 720p video with my character",
            facts=факты,
            spec=spec,
            full=True,
        )
        self.assertFalse(
            any("assumed for pricing" in д for д in итог["understood_as"]["assumptions"])
        )


if __name__ == "__main__":
    unittest.main()
