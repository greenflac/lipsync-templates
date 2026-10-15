"""Цены, круг 4: квалификатор не теряется, вердикт бюджета честен (2026-10-15).

Находки независимого валидатора, каждая — литералом (Т2), и одно СВОЙСТВО на
живой базе вместо выборки процитированных строк:

1. «$0.49 per video generation» без записанной длины прогона — нижняя граница,
   а не цена 120- и 300-секундного ролика.
2. «$0.05 480p, $0.10 720p, or $0.20 1080p» — разрешение вплотную после суммы;
   непривязанные равные ставки — неоднозначность, берётся наибольшая.
3. «$0.10 per 10 seconds of output at 720p, $0.20 at 1080p» — «за что» общее у
   сумм куска; блок в 10 секунд считается целиком.
4. wan-3.0-i2v 1080p — 0.20 usd/с, а не 0.05 (п. 2 на живой базе).
5. Видео «за мегапиксель» — мегапиксели × кадров (fps × секунды); без fps шаг
   без цены, а не «укладывается».
6. Шаг без цены или с нижней границей — «не подтвердить», с именем шага;
   «превышен» — только по наименьшей известной стоимости.
7. План без шага-видео (одна музыка) — цена плана и вердикт бюджета есть.
8. Противоречия брифа печатаются и становятся вопросом.
9. Расхождения источников — флагом цены шага на всех путях выдачи.

Т4: сети нет — свойство читает базу из репозитория.
Т1: 13 мутаций, `python -B`, кэши очищены, все красные (2026-10-15): min
вместо max среди равных; нижняя граница не ставится; «за что» не наследуется;
блок линейно; разрешение «вплотную после» отключено; мегапиксель без fps;
нижние не делают смету неполной; превышение по «дёшево», а не по минимуму;
план без видео — ранний возврат; противоречие тишины выключено; повтор
сводки не привязывается; ставка за 60 fps без штрафа; поштучная цена снова
«укладывается». Две из них — и в `scripts/mutate_planner.py`.
"""

from __future__ import annotations

import re
import unittest

from studio import planner as pn
from studio import pricing
from studio.selfrag.facts import load_facts

WAN_30 = (
    "For every second of video you generate, you will be charged $0.05 480p, $0.10 720p, or "
    "$0.20 1080p. For example, a 5s video at 720p will cost $0.50. Pricing is subjected to change."
)
TOPAZ = (
    "Your request will cost $0.10 per 10 seconds of output at 720p, $0.20 at 1080p, and $0.60 "
    "at 4K with the precision models"
)
VEO_T2V = (
    "For every second of video you generate you will be charged $0.20 without audio or $0.40 "
    "with audio for 720p or 1080p. At 4k, you will be charged $0.40 per second without audio, "
    "or $0.60 with."
)
SEEDANCE = (
    "For every second of 720p video you generated, you will be charged $0.3034/second and for "
    "1080p you will be charged $0.682/second."
)
LTX_MP = "$0.001205 per megapixel"
HAILUO = "Your request will cost $0.49 per video generation."


def _ставки(текст: str, имя: str) -> list[tuple]:
    return [(r.amount, r.per, r.resolutions, r.audio) for r in pricing.rates(текст, имя)]


class ПривязкаРазрешения(unittest.TestCase):
    def test_разрешение_вплотную_после_суммы(self) -> None:
        self.assertEqual(
            [(0.05, "second", (480,), None), (0.1, "second", (720,), None), (0.2, "second", (1080,), None)],
            _ставки(WAN_30, "price_per_second_usd"),
        )

    def test_wan_1080p_десять_секунд(self) -> None:
        варианты = pricing.estimate(
            pricing.rates(WAN_30, "price_per_second_usd"), pricing.Need(seconds=10, resolution=1080)
        )
        self.assertEqual([(2.0, 1080, "")], [(o.usd, o.resolution, o.ambiguous) for o in варианты])

    def test_пара_с_общим_разрешением_и_голое_with(self) -> None:
        self.assertEqual(
            [
                (0.2, "second", (720, 1080), False),
                (0.4, "second", (720, 1080), True),
                (0.4, "second", (2160,), False),
                (0.6, "second", (2160,), True),
            ],
            _ставки(VEO_T2V, "price_per_second_usd"),
        )

    def test_and_for_не_отдаёт_разрешение_соседу(self) -> None:
        self.assertEqual(
            [(0.3034, "second", (720,), None), (0.682, "second", (1080,), None)],
            _ставки(SEEDANCE, "price_per_second_usd"),
        )

    def test_подпись_размера_не_сумма(self) -> None:
        self.assertEqual(
            [(0.211, "image", (1024,), None)],
            _ставки("high 1024x1024 $0.211", "price_per_image_usd"),
        )

    def test_1k_символов_не_разрешение(self) -> None:
        self.assertEqual(
            [(0.08, "1000_chars", (), None)],
            _ставки("$0.08 per 1K characters (API)", "price_per_1000_chars"),
        )

    def test_повтор_сводки_получает_разрешение_двойника(self) -> None:
        self.assertEqual(
            [(0.3034, "second", (720,), None), (0.682, "second", (1080,), None), (0.3034, "second", (720,), None)],
            _ставки("$0.3034; 1080p $0.682; 720p $0.3034", "price_per_second_usd_via_fal_ai"),
        )


class Неоднозначность(unittest.TestCase):
    """Непривязанные ставки одной привязки: наибольшая — в цену, наименьшая — рядом."""

    ТРИ = "$0.05, $0.10, or $0.20"

    def test_берётся_наибольшая_и_это_сказано(self) -> None:
        (o,) = pricing.estimate(
            pricing.rates(self.ТРИ, "price_per_second_usd"), pricing.Need(seconds=10, resolution=1080)
        )
        self.assertEqual((2.0, 0.5), (o.usd, o.usd_min))
        self.assertIn("НЕОДНОЗНАЧНО", o.formula)

    def test_разрешение_не_названо_берётся_наименьшее_без_неоднозначности(self) -> None:
        (o,) = pricing.estimate(
            pricing.rates(WAN_30, "price_per_second_usd"), pricing.Need(seconds=10)
        )
        self.assertEqual((0.5, 480, ""), (o.usd, o.resolution, o.ambiguous))


class ЗаNСекунд(unittest.TestCase):
    def test_за_что_общее_у_сумм_куска(self) -> None:
        self.assertEqual(
            [(0.01, 10.0, (720,)), (0.02, 10.0, (1080,)), (0.06, 10.0, (2160,))],
            [(round(r.amount, 6), r.block, r.resolutions) for r in pricing.rates(TOPAZ, "price")],
        )

    def test_начатый_блок_считается_целиком(self) -> None:
        (o,) = pricing.estimate(pricing.rates(TOPAZ, "price"), pricing.Need(seconds=15, resolution=1080))
        self.assertEqual(0.4, o.usd)

    def test_n_seconds_costs_перед_суммой(self) -> None:
        (r,) = pricing.rates("At 30 fps, 10 seconds costs $1.20 up to 1080p", "price")
        self.assertEqual(("second", 10.0, (1080,), 30.0), (r.per, r.block, r.resolutions, r.fps))


class ПрогонБезДлины(unittest.TestCase):
    def test_нижняя_граница(self) -> None:
        for секунд in (120, 300):
            (o,) = pricing.estimate(pricing.rates(HAILUO, "price"), pricing.Need(seconds=секунд))
            self.assertEqual((0.49, pricing.LOWER_BOUND_RUN), (o.usd, o.lower_bound))

    def test_с_пределом_прогона_прогоны_считаются(self) -> None:
        (o,) = pricing.estimate(
            pricing.rates(HAILUO, "price"), pricing.Need(seconds=120, max_run_seconds=10)
        )
        self.assertEqual((5.88, ""), (o.usd, o.lower_bound))


class МегапиксельВидео(unittest.TestCase):
    НУЖДА = dict(seconds=8, resolution=2160, megapixels=3840 * 2160 / 1e6, images=0.0)

    def test_мегапиксели_на_кадры(self) -> None:
        (o,) = pricing.estimate(
            pricing.rates(LTX_MP, "price_unit_megapixel_usd"), pricing.Need(**self.НУЖДА, fps=60)
        )
        # ⌈8.2944 Мп × 480 кадров⌉ = 3982 Мп × 0.001205
        self.assertEqual(4.7983, o.usd)

    def test_без_fps_цены_нет(self) -> None:
        self.assertEqual(
            [], pricing.estimate(pricing.rates(LTX_MP, "price_unit_megapixel_usd"), pricing.Need(**self.НУЖДА))
        )

    def test_мегапиксель_в_секунду_не_читается_за_секунду(self) -> None:
        self.assertEqual([], pricing.rates("Pricing is $0.10 per megapixel per second.", "price_per_second_usd"))

    def test_ставка_за_60_fps_только_когда_заказано(self) -> None:
        ставки = pricing.rates("$0.12/s at 1080p; at 60 fps $0.24/s at 1080p", "price_per_second_usd")
        self.assertEqual(
            [1.2, 2.4, 1.2],
            [
                pricing.estimate(ставки, pricing.Need(seconds=10, resolution=1080, fps=fps))[0].usd
                for fps in (None, 60.0, 24.0)
            ],
        )

    def test_fps_из_брифа(self) -> None:
        self.assertEqual(
            [60.0, 24.0, None],
            [pn.fps_из_брифа(б) for б in ("8s 4K 60fps", "ролик 24 fps", "8s 4K")],
        )


def оп(имя: str) -> pn.Operation:
    return next(о for о in pn.OPERATIONS if о.name == имя)


def стоимость(o: pricing.Option) -> pn.Стоимость:
    return pn.Стоимость((o,), o, o, "")


def кандидат(o: pricing.Option, модель: str = "м") -> pn.Candidate:
    return pn.Candidate(модель, (), 0, 1, 0, "", cost=стоимость(o))


class ВердиктБюджета(unittest.TestCase):
    ВИДЕО_НИЖНЯЯ = pricing.Option(0.49, "", None, "0.49", lower_bound=pricing.LOWER_BOUND_RUN)
    ЗВУК = pricing.Option(0.05, "", None, "0.05")

    def _смета(self, видео: pricing.Option, потолок: float) -> dict:
        return pn.смета_ролика(
            {"note": "n"},
            [(оп("генерация_видео"), кандидат(видео)), (оп("озвучка"), кандидат(self.ЗВУК))],
            120.0,
            потолок,
        )

    def test_нижняя_граница_не_подтверждает(self) -> None:
        итог = self._смета(self.ВИДЕО_НИЖНЯЯ, 15.0)
        self.assertEqual(("не смогли", ["генерация_видео"]), (итог["outcome"], итог["budget_unconfirmed_steps"]))

    def test_превышение_по_наименьшей_известной(self) -> None:
        итог = self._смета(self.ВИДЕО_НИЖНЯЯ, 0.3)
        self.assertEqual("не годно", итог["outcome"])
        self.assertIn("наименьшая известная стоимость 0.54", итог["note"])

    def test_неоднозначность_решает_не_подтвердить(self) -> None:
        видео = pricing.Option(2.0, "", 1080, "2", ambiguous="x", usd_min=0.5)
        self.assertEqual("не смогли", self._смета(видео, 1.0)["outcome"])
        self.assertEqual("не годно", self._смета(видео, 0.5)["outcome"])
        self.assertEqual("годно", self._смета(видео, 3.0)["outcome"])

    def test_план_без_видео_получает_вердикт(self) -> None:
        музыка = pricing.Option(0.3, "", None, "0.3")
        итог = pn.смета_ролика({"note": "n"}, [(оп("музыка"), кандидат(музыка))], 30.0, 1.0, (), True)
        self.assertNotIn("за_ролик", итог)
        self.assertEqual(("годно", True), (итог["outcome"], итог["no_clip_price"]))
        self.assertIn("ЦЕНА ПЛАНА: 30 с × ставки шагов = 0.30 usd", итог["note"])


class Противоречия(unittest.TestCase):
    def test_пары_брифа(self) -> None:
        self.assertEqual(
            [["цена_и_качество"], ["тишина_и_звук"], []],
            [
                [п["kind"] for п in pn.противоречия(б, [])]
                for б in (
                    "cheapest possible but best quality, 8s 4K",
                    "silent 10s clip with native audio dialogue in French",
                    "cheap 8s clip, good lighting",
                )
            ],
        )

    def test_апскейл_дописанный_планом_противоречие(self) -> None:
        шаги = [{"step": "апскейл", "inferred": "заказан 2160p, модель даёт 1080p"}]
        self.assertEqual(["кадр_выше_модели"], [п["kind"] for п in pn.противоречия("8s 4K", шаги)])


class ФлагиЦены(unittest.TestCase):
    def test_расхождение_и_нижняя_граница_флагами(self) -> None:
        o = pricing.Option(0.49, "", None, "f", lower_bound=pricing.LOWER_BOUND_RUN)
        к = pn.Candidate(
            "м", (), 0, 1, 0, "", cost=pn.Стоимость((o,), o, o, "", contradictions=("fal: 1 против 2",))
        )
        self.assertEqual(
            ["ИСТОЧНИКИ РАСХОДЯТСЯ: fal: 1 против 2", f"НИЖНЯЯ ГРАНИЦА: {pricing.LOWER_BOUND_RUN}"],
            pn.флаги_цены(к),
        )


# --------------------------------------------------------------------------
# СВОЙСТВО НА ЖИВОЙ БАЗЕ: ни одна ставка не теряет молча квалификатор текста.
#
# Для каждой ценовой строки `model_facts.jsonl` (уникальной по атрибуту и
# тексту) разбор `pricing.rates` проверяется на пять потерь:
#   сумма      — «сумма» ≥ 100 usd: подпись размера или множитель прочитаны суммой;
#   разрешение — в тексте ≥ 2 разрешений, а в группе (тариф, режим, звук, «за
#                что») с разными суммами есть ставка без разрешения;
#   за_N_секунд — кусок говорит «per N seconds», а ставка — «за прогон» без длины;
#   мегапиксель — кусок говорит «megapixel», а ставка — «за секунду»;
#   звук       — кусок называет и «с звуком», и «без», а ставка с другой суммой
#                осталась без звука.
# Исключения — СПИСКОМ, с причиной; исправленная строка обязана из него уйти
# (множество нарушителей сверяется целиком, в обе стороны).
# --------------------------------------------------------------------------

#: (модель, атрибут) -> почему потеря допустима. Пусто здесь быть не может:
#: строка либо разобрана, либо названа.
ИСКЛЮЧЕНИЯ: dict[tuple[str, str], str] = {
    # Сводка LiteLLM: ведущая сумма — цена по умолчанию, разрешение источник
    # не называет и с привязанными она не совпадает. В смету она идёт только
    # там, где точной ступени нет (штраф «не названо»), — и печатается.
    ("seedance-2.0", "price_per_second_usd_via_runwayml"): "ведущая сумма сводки LiteLLM без разрешения",
    ("seedance-2.5", "price_per_second_usd_via_runwayml"): "ведущая сумма сводки LiteLLM без разрешения",
    ("veo-3.1-fast", "price_per_second_usd_via_gemini"): "ведущая сумма сводки LiteLLM без разрешения",
    ("nano-banana-pro", "price_per_image_usd"): "«Batch/Flex $0.067 / $0.12» повторяет пару Standard 1K-2K / 4K по ПОЗИЦИИ — по тексту не привязать",
    ("seedream-5-pro", "price"): "пороги ПЛОЩАДИ (≤1536², 1536²–2048²), а не ступени разрешения",
}

ЗА_N_СЕКУНД = re.compile(r"(?:per|/)\s*(\d+)\s*(?:seconds?|secs?|s)\b", re.I)
С_ЗВУКОМ = re.compile(r"with audio|audio on", re.I)
БЕЗ_ЗВУКА = re.compile(r"without audio|no audio|audio off", re.I)


def потери(value: str, attribute: str) -> list[str]:
    """Какие квалификаторы текста разбор потерял. Пусто — ни одного."""
    ставки = pricing.rates(value, attribute)
    usd = [r for r in ставки if r.unit == "usd"]
    итог: list[str] = []
    if any(r.amount >= 100 for r in usd):
        итог.append("сумма")
    if len(set(pricing._разрешения(value))) >= 2:
        группы: dict[tuple, list[pricing.Rate]] = {}
        for r in usd:
            if r.per in ("second", "run", "generation", "image") and not r.conditional:
                группы.setdefault((r.tier, r.mode, r.audio, r.per), []).append(r)
        for своя in группы.values():
            if len({r.amount for r in своя}) >= 2 and any(not r.resolutions for r in своя):
                итог.append("разрешение")
                break
    for r in ставки:
        м = ЗА_N_СЕКУНД.search(r.source)
        if м and int(м.group(1)) > 1 and r.per in ("run", "generation", "") and not r.run_seconds and not r.upfront:
            итог.append("за_N_секунд")
        if re.search(r"megapixel", r.source, re.I) and r.per == "second":
            итог.append("мегапиксель")
    for r in usd:
        if (
            С_ЗВУКОМ.search(r.source)
            and БЕЗ_ЗВУКА.search(r.source)
            and r.audio is None
            and not r.conditional
            and len({x.amount for x in usd if x.source == r.source}) > 1
        ):
            итог.append("звук")
    return sorted(set(итог))


class СвойствоЖивойБазы(unittest.TestCase):
    def test_ни_один_квалификатор_не_теряется_молча(self) -> None:
        строки = {(f.model, f.attribute, f.value) for f in pn.price_facts(load_facts())}
        проверено = 0
        нарушители: dict[tuple[str, str], list[str]] = {}
        for модель, атрибут, текст in sorted(строки):
            проверено += 1
            потеряно = потери(текст, атрибут)
            if потеряно:
                нарушители[(модель, атрибут)] = потеряно
        # П1: ноль проверок — не «годно». На 2026-10-15 ценовых строк 761.
        self.assertGreater(проверено, 300)
        self.assertEqual(sorted(ИСКЛЮЧЕНИЯ), sorted(нарушители), нарушители)

    def test_прибор_ловит_потерю(self) -> None:
        """Негативный контроль: на заведомо плохом разборе свойство краснеет."""
        self.assertEqual(["разрешение"], потери("$0.05 at 480p, $0.10, $0.20 at 1080p", "price_per_second_usd"))
        self.assertEqual(["сумма"], потери("1024 $", "price_per_image_usd"))


if __name__ == "__main__":
    unittest.main()
