"""Прибор «находка или предмет письма» и его гейт.

Ожидаемое здесь — ЛИТЕРАЛЫ (правило Т2): ни один порог не импортируется из
проверяемого модуля, иначе тест поедет вместе с константой и промолчит. Числа
дублируются сознательно и именно поэтому краснеют, когда кто-то двигает порог.

Сети здесь нет (Т4): прибор её не касается, гейт читает файл базы. Тест гейта
работает на СВОЕЙ временной базе, кроме одного случая, который меряет живую —
он и есть негативный контроль из трёх половин (И5).

Гита здесь нет: CI клонирует с `fetch-depth: 1`, и тест, заглянувший в историю,
покраснел бы там при зелени локально. Проверено мелким клоном.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from studio import harvest_quality as hq
from studio.selfrag.facts import Fact, load_facts

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts"))

import check_harvest_quality as гейт  # noqa: E402

# Исходы прибора, литералами. Совпадают с `lipsync.fork_identity`, и если там
# их переименуют, этот тест обязан покраснеть, а не подстроиться.
ГОДНО = "pass"
НЕ_ГОДНО = "fail"
НЕ_СМОГЛИ = "could not measure"

# Пороги гейта литералами (Т2).
ПОЛ_ОСУЖДЕНИЯ = 0.80
ЛОЖНЫХ_РУЧНЫХ_ПОЗВОЛЕНО = 0

# Живые числа на 2026-09-01, ИЗМЕРЕНО этим же прибором. Стоят как ориентир, а
# не как требование: требование — доля выше пола и ноль ложных на ручных.
ЖИВЫХ_МАССОВЫХ = 181
ЖИВЫХ_РУЧНЫХ = 20


def факт(
    значение: str,
    атрибут: str = "failure_mode",
    tier: str = "blog",
    note: str = "",
    source_url: str = "https://huggingface.co/какая-то-модель/discussions/1",
) -> Fact:
    """Строка базы для теста. Тир `blog` — тот же, что у массового захода."""
    return Fact(
        model="какая-то-модель",
        attribute=атрибут,
        value=значение,
        source_url=source_url,
        tier=tier,
        stated_on="2026-09-01",
        note=note,
    )


class ТриИсхода(unittest.TestCase):
    """Р1: годно, не годно, не смогли — и третий не сворачивается в два первых."""

    def test_находка_годна(self) -> None:
        в = hq.судить(
            "In V2V lipsync the sampler rebuilds the entire frame every step, so people "
            "who are NOT the audio target visibly drift",
            "failure_mode",
        )
        self.assertEqual(в.исход, ГОДНО)
        self.assertEqual(в.признак, "")

    def test_заголовок_не_годен(self) -> None:
        в = hq.судить("Gemma API call issues", "failure_mode")
        self.assertEqual(в.исход, НЕ_ГОДНО)
        self.assertEqual(в.признак, "ярлык-жалоба")

    def test_чужой_язык_это_не_смогли_а_не_не_годно(self) -> None:
        """Осмысленное короткое утверждение по-японски: прибор ОБЯЗАН отказаться.

        «Липсинк ломается, когда говорящих становится двое» — настоящая находка.
        Осудить её значит забраковать чужой язык, пропустить — выдать незнание
        за вердикт.
        """
        в = hq.судить("話者が二人になるとリップシンクが崩れる", "failure_mode")
        self.assertEqual(в.исход, НЕ_СМОГЛИ)
        self.assertEqual(в.признак, "язык не разбирается")

    def test_слово_исхода_по_русски(self) -> None:
        self.assertEqual(hq.судить("Gemma API call issues", "failure_mode").слово, "не годно")


class КаждыйПризнак(unittest.TestCase):
    """У каждого правила свой вход. Правило без входа снимается молча."""

    def test_трассировка(self) -> None:
        for значение in (
            "AssertionError: Input and weight inner dimensions must match",
            "NotImplementedError: Cannot copy out of meta tensor; no data!",
            "Couldn't connect to the Hub: 401 Client Error",
        ):
            with self.subTest(значение=значение):
                self.assertEqual(hq.судить(значение, "failure_mode").признак, "трассировка")

    def test_вопрос(self) -> None:
        for значение in (
            "Artifacts in 8-step model with LoRA?",
            "What sampler and scheduler should I use for best quality in Flux Schnell",
            "老大krea不更了吗",
        ):
            with self.subTest(значение=значение):
                self.assertEqual(hq.судить(значение, "failure_mode").признак, "вопрос")

    def test_просьба(self) -> None:
        for значение in ("Please post issues on GitHub", "🚩 Report: Ethical issue(s)"):
            with self.subTest(значение=значение):
                self.assertEqual(hq.судить(значение, "failure_mode").признак, "просьба")

    def test_лицензионный_спор(self) -> None:
        в = hq.судить("Counterfeit-V2.5商用利用禁止 著作権侵害の疑い", "failure_mode")
        self.assertEqual(в.признак, "лицензионный спор")

    def test_тема_письма(self) -> None:
        self.assertEqual(
            hq.судить("Regarding Turkish Speech Quality", "failure_mode").признак, "тема письма"
        )

    def test_ярлык_жалоба(self) -> None:
        self.assertEqual(
            hq.судить("The issue with the Vietnamese accent", "failure_mode").признак,
            "ярлык-жалоба",
        )

    def test_титульный_регистр(self) -> None:
        в = hq.судить(
            "Speed and Quality Combined: Working with SDXL-Lightning Model", "failure_mode"
        )
        self.assertEqual(в.признак, "титульный регистр")

    def test_отчёт_об_установке(self) -> None:
        в = hq.судить(
            "TX-2.3 model fails to load with Diffusers - Missing model_index.json", "failure_mode"
        )
        self.assertEqual(в.признак, "отчёт об установке")

    def test_расхождение_знака(self) -> None:
        """Похвала под отрицательным атрибутом — это перепутанный знак."""
        в = hq.судить("the model works great on every clip we threw at it", "limitation")
        self.assertEqual(в.исход, НЕ_ГОДНО)
        self.assertEqual(в.признак, "расхождение знака")

    def test_похвала_с_оговоркой_не_расхождение(self) -> None:
        """«excellent ... but very blurry» — настоящая находка, не перепутанный знак."""
        в = hq.судить(
            "Independently evaluated by the LatentSync authors: excellent lip-sync "
            "accuracy but very blurry output",
            "failure_mode",
        )
        self.assertEqual(в.исход, ГОДНО)

    def test_пусто(self) -> None:
        self.assertEqual(hq.судить("   ", "failure_mode").признак, "пусто")


class ГраницыПорогов(unittest.TestCase):
    """Т3: с обоих краёв диапазона и из середины, а не из одной точки."""

    def test_длина_по_обе_стороны_порога(self) -> None:
        # Порог 24 знака: на 23 прибор обязан осудить, на 24 — пропустить.
        под_порогом = "губы плывут на 23 знак"
        self.assertEqual(len(под_порогом), 22)
        self.assertEqual(hq.судить(под_порогом, "failure_mode").признак, "слишком коротко")

        ровно_под = "губы плывут на 23 знака"
        self.assertEqual(len(ровно_под), 23)
        self.assertEqual(hq.судить(ровно_под, "failure_mode").исход, НЕ_ГОДНО)

        ровно_на_пороге = "губы плывут на 24 знака."
        self.assertEqual(len(ровно_на_пороге), 24)
        self.assertEqual(hq.судить(ровно_на_пороге, "failure_mode").исход, ГОДНО)

        длинное = "губы плывут на длинной реплике, к концу клипа расходятся с речью"
        self.assertEqual(hq.судить(длинное, "failure_mode").исход, ГОДНО)

    def test_длина_не_применяется_к_нестрогому_атрибуту(self) -> None:
        """Короткое значение под атрибутом не о поломке — законно."""
        self.assertEqual(hq.судить("English", "prompt_language").исход, ГОДНО)

    def test_перечисление_и_связная_фраза(self) -> None:
        салат = "Linear, dynamic, high resolution, detailed, 3D rendering, high quality"
        self.assertEqual(hq.судить(салат, "failure_mode").признак, "перечисление")
        связное = (
            "In start-frame/end-frame workflows colour drifts progressively across the "
            "clip, so the final frames no longer match the supplied end frame"
        )
        self.assertEqual(hq.судить(связное, "failure_mode").исход, ГОДНО)

    def test_таксономии_список_разрешён(self) -> None:
        в = hq.судить(
            "flicker, jitter, warp, texture crawl, boundary defects, object mismatches",
            "artifact_taxonomy",
        )
        self.assertEqual(в.исход, ГОДНО)

    def test_доля_чужих_букв_края_и_середина(self) -> None:
        self.assertEqual(hq.доля_чужих_букв("полностью кириллица"), 0.0)
        self.assertEqual(hq.доля_чужих_букв("話者が二人"), 1.0)
        смешанное = hq.доля_чужих_букв("abcd話者")
        self.assertGreater(смешанное, 0.0)
        self.assertLess(смешанное, 1.0)

    def test_смешанный_текст_судится_а_не_отклоняется(self) -> None:
        """Между краями: латиница с вкраплением иероглифов ещё читается.

        Порог отказа — половина букв. Строка, где чужих букв меньше, ОБЯЗАНА
        получить вердикт: отказ на первом же иероглифе превратил бы «не смогли»
        в отговорку.
        """
        смешанное = (
            "lipsync 話者 breaks down as soon as a second speaker starts talking in the same clip"
        )
        доля = hq.доля_чужих_букв(смешанное)
        self.assertGreater(доля, 0.01)
        self.assertLess(доля, 0.5)
        self.assertEqual(hq.судить(смешанное, "failure_mode").исход, ГОДНО)

    def test_титульный_регистр_края(self) -> None:
        self.assertFalse(hq.титульный_регистр("Wan Animate drifts"))
        self.assertTrue(hq.титульный_регистр("Speed And Quality Combined Here"))
        self.assertFalse(hq.титульный_регистр("the sampler rebuilds the entire frame"))


class ОбластьПрибора(unittest.TestCase):
    """Форма входа судится не этим прибором, и это печатается, а не молчится."""

    def test_схема_вне_области(self) -> None:
        схема = факт("15", "max_seconds", tier="vendor")
        self.assertFalse(hq.в_области(схема))
        self.assertEqual(hq.судить_факт(схема).исход, НЕ_СМОГЛИ)
        self.assertEqual(hq.судить_факт(схема).признак, "вне области")

    def test_поломка_в_области(self) -> None:
        self.assertTrue(hq.в_области(факт("Gemma API call issues")))

    def test_учесть_печатает_числа_а_не_флаг(self) -> None:
        итог = hq.учесть(
            [
                факт("Gemma API call issues"),
                факт("話者が二人になるとリップシンクが崩れる"),
                факт(
                    "Skin tone is not preserved under the flowmatch_distill scheduler - "
                    "dark skin is rendered markedly redder than the reference"
                ),
                факт("15", "max_seconds", tier="vendor"),
            ]
        )
        self.assertEqual(итог["checked"], 3)
        self.assertEqual(итог["осуждено"], 1)
        self.assertEqual(итог["годно"], 1)
        self.assertEqual(итог["не смогли"], 1)
        self.assertEqual(итог["вне области"], 1)


def _написать_базу(каталог: Path, строки: list[dict]) -> Path:
    путь = каталог / "model_facts.jsonl"
    путь.write_text(
        "// тестовая база\n" + "\n".join(json.dumps(с, ensure_ascii=False) for с in строки) + "\n",
        encoding="utf-8",
    )
    return путь


def _строка(значение: str, note: str, url: str, атрибут: str = "failure_mode") -> dict:
    return {
        "model": "модель",
        "attribute": атрибут,
        "value": значение,
        "source_url": url,
        "tier": "blog",
        "stated_on": "2026-09-01",
        "note": note,
    }


ЗАГОЛОВКИ = [
    "Gemma API call issues",
    "AssertionError: Input and weight inner dimensions must match",
    "Artifacts in 8-step model with LoRA?",
    "Please post issues on GitHub",
    "Regarding Turkish Speech Quality",
]
РАЗБОРЫ = [
    "In V2V lipsync the sampler rebuilds the entire frame every step, so people who "
    "are NOT the audio target visibly drift",
    "Speaker count is a hard applicability ceiling, not a smooth degradation: two "
    "simultaneous speakers break it, one does not",
    "Output diverges in exposure from the conditioning image starting immediately "
    "after frame 1, going grey or darker",
]


class ГейтНаСвоейБазе(unittest.TestCase):
    """Развилка гейта проверяема, потому что живёт не в main() (Т5)."""

    def test_здоровая_база_годна(self) -> None:
        строки = [
            _строка(з, f"тред #{i}, состояние open", f"https://huggingface.co/м/discussions/{i}")
            for i, з in enumerate(ЗАГОЛОВКИ * 3)
        ]
        строки += [
            _строка(
                р,
                "HARVESTED 2026-08-27 из тела треда",
                f"https://huggingface.co/м/discussions/9{i}",
            )
            for i, р in enumerate(РАЗБОРЫ)
        ]
        строки += [
            _строка(
                "話者が二人になるとリップシンクが崩れる",
                "чужой язык",
                "https://example.com/страница",
            )
        ]
        строки += [
            _строка(
                "Skin tone is not preserved under the flowmatch_distill scheduler - dark "
                "skin is rendered markedly redder than the reference",
                "разбор прочего канала",
                "https://example.com/другая",
            )
        ]
        with TemporaryDirectory() as каталог:
            путь = _написать_базу(Path(каталог), строки)
            вердикт = гейт.проверить(путь)
        self.assertEqual(вердикт["outcome"], ГОДНО, вердикт.get("беды"))
        self.assertEqual(вердикт["группы"][гейт.ЗАГОЛОВОЧНЫЙ]["осуждено"], 15)
        self.assertEqual(вердикт["группы"][гейт.РУЧНОЙ]["осуждено"], 0)

    def test_прибор_молчащий_на_массовом_заходе_красит_гейт(self) -> None:
        """Негативный контроль гейта: заголовки заменены настоящими разборами."""
        строки = [
            _строка(р, f"тред #{i}, состояние open", f"https://huggingface.co/м/discussions/{i}")
            for i, р in enumerate(РАЗБОРЫ * 4)
        ]
        строки += [
            _строка(
                р,
                "HARVESTED 2026-08-27 из тела треда",
                f"https://huggingface.co/м/discussions/9{i}",
            )
            for i, р in enumerate(РАЗБОРЫ)
        ]
        строки += [_строка("話者が二人になる", "чужой", "https://example.com/страница")]
        with TemporaryDirectory() as каталог:
            путь = _написать_базу(Path(каталог), строки)
            вердикт = гейт.проверить(путь)
        self.assertEqual(вердикт["outcome"], НЕ_ГОДНО)
        self.assertTrue(any("заголовочный заход" in б for б in вердикт["беды"]))

    def test_прибор_бракующий_ручные_красит_гейт(self) -> None:
        строки = [
            _строка(з, f"тред #{i}, состояние open", f"https://huggingface.co/м/discussions/{i}")
            for i, з in enumerate(ЗАГОЛОВКИ * 3)
        ]
        строки += [
            _строка(
                з,
                "HARVESTED 2026-08-27 из тела треда",
                f"https://huggingface.co/м/discussions/9{i}",
            )
            for i, з in enumerate(ЗАГОЛОВКИ)
        ]
        строки += [_строка("話者が二人になる", "чужой", "https://example.com/страница")]
        with TemporaryDirectory() as каталог:
            путь = _написать_базу(Path(каталог), строки)
            вердикт = гейт.проверить(путь)
        self.assertEqual(вердикт["outcome"], НЕ_ГОДНО)
        self.assertTrue(any("ручной разбор" in б for б in вердикт["беды"]))

    def test_прибор_бракующий_прочие_каналы_красит_гейт(self) -> None:
        """Третья половина контроля: осуждение здоровых записей прочих каналов."""
        строки = [
            _строка(з, f"тред #{i}, состояние open", f"https://huggingface.co/м/discussions/{i}")
            for i, з in enumerate(ЗАГОЛОВКИ * 3)
        ]
        строки += [
            _строка(
                р,
                "HARVESTED 2026-08-27 из тела треда",
                f"https://huggingface.co/м/discussions/9{i}",
            )
            for i, р in enumerate(РАЗБОРЫ)
        ]
        # Прочий канал, набитый заголовками: прибор обязан их осудить, а гейт —
        # покраснеть, потому что доля осуждённых выше потолка 0.01.
        строки += [
            _строка(з, "вендорская страница", f"https://example.com/страница/{i}")
            for i, з in enumerate(ЗАГОЛОВКИ * 4)
        ]
        with TemporaryDirectory() as каталог:
            путь = _написать_базу(Path(каталог), строки)
            вердикт = гейт.проверить(путь)
        self.assertEqual(вердикт["outcome"], НЕ_ГОДНО)
        self.assertTrue(any("прочие каналы" in б for б in вердикт["беды"]), вердикт["беды"])

    def test_неопознанная_метка_канала_идёт_в_не_смогли(self) -> None:
        """Чужой заход не приписывается к ручному разбору: там его осудили бы."""
        строки = [
            _строка(з, f"тред #{i}, состояние open", f"https://huggingface.co/м/discussions/{i}")
            for i, з in enumerate(ЗАГОЛОВКИ * 3)
        ]
        строки += [
            _строка(
                р,
                "HARVESTED 2026-08-27 из тела треда",
                f"https://huggingface.co/м/discussions/9{i}",
            )
            for i, р in enumerate(РАЗБОРЫ)
        ]
        строки += [
            _строка(
                "Gemma API call issues",
                "метка нового захода",
                "https://huggingface.co/м/discussions/77",
            )
        ]
        строки += [_строка("話者が二人になる", "чужой", "https://example.com/страница")]
        with TemporaryDirectory() as каталог:
            путь = _написать_базу(Path(каталог), строки)
            вердикт = гейт.проверить(путь)
        self.assertEqual(вердикт["outcome"], ГОДНО, вердикт.get("беды"))
        self.assertEqual(вердикт["неопознанных"], 1)

    def test_пустая_база_это_не_смогли(self) -> None:
        with TemporaryDirectory() as каталог:
            путь = Path(каталог) / "нет.jsonl"
            вердикт = гейт.проверить(путь)
        self.assertEqual(вердикт["outcome"], НЕ_СМОГЛИ)
        self.assertEqual(вердикт["unmeasured"], 1)

    def test_группа_без_строк_это_не_смогли_а_не_годно(self) -> None:
        строки = [
            _строка(з, f"тред #{i}, состояние open", f"https://huggingface.co/м/discussions/{i}")
            for i, з in enumerate(ЗАГОЛОВКИ)
        ]
        with TemporaryDirectory() as каталог:
            путь = _написать_базу(Path(каталог), строки)
            вердикт = гейт.проверить(путь)
        self.assertEqual(вердикт["outcome"], НЕ_СМОГЛИ)

    def test_код_возврата_только_под_флагом(self) -> None:
        """Без `--check` скрипт возвращает 0 при любом исходе — это уже стоило прогона."""
        with TemporaryDirectory() as каталог:
            путь = Path(каталог) / "нет.jsonl"
            self.assertEqual(гейт.main([f"--path={путь}"]), 0)
            self.assertEqual(гейт.main(["--check", f"--path={путь}"]), 2)


class КонтрольныйНаборГейта(unittest.TestCase):
    """И5: у каждого правила есть вход, где оно обязано сработать."""

    def test_контроль_сходится_целиком(self) -> None:
        сошлось, беды = гейт.проверить_контроль()
        self.assertEqual(беды, [])
        self.assertEqual(сошлось, len(гейт.КОНТРОЛЬНЫЙ_НАБОР))

    def test_в_наборе_есть_здоровые_чужаки(self) -> None:
        """Прибор, отвергающий всё, обязан упасть на этой половине набора."""
        чужаки = [с for с in гейт.КОНТРОЛЬНЫЙ_НАБОР if с[2] == ГОДНО]
        self.assertGreaterEqual(len(чужаки), 5)

    def test_в_наборе_есть_третий_исход(self) -> None:
        отказы = [с for с in гейт.КОНТРОЛЬНЫЙ_НАБОР if с[2] == НЕ_СМОГЛИ]
        self.assertGreaterEqual(len(отказы), 1)


class ЖиваяБаза(unittest.TestCase):
    """Негативный контроль из трёх половин — на настоящей базе (И5)."""

    def setUp(self) -> None:
        self.факты = load_facts()
        if not self.факты:
            self.fail("базы фактов нет: измерить нечем")
        self.группы = гейт.разложить(self.факты)

    def test_группы_нашлись(self) -> None:
        self.assertEqual(len(self.группы[гейт.ЗАГОЛОВОЧНЫЙ]), ЖИВЫХ_МАССОВЫХ)
        self.assertEqual(len(self.группы[гейт.РУЧНОЙ]), ЖИВЫХ_РУЧНЫХ)
        self.assertGreater(len(self.группы[гейт.ПРОЧИЕ]), 100)

    def test_массовый_заход_осуждён(self) -> None:
        итог = hq.учесть(self.группы[гейт.ЗАГОЛОВОЧНЫЙ])
        доля = итог["осуждено"] / итог["checked"]
        self.assertGreaterEqual(
            доля, ПОЛ_ОСУЖДЕНИЯ, f"осуждено {итог['осуждено']} из {итог['checked']}"
        )

    def test_ручной_разбор_пропущен_целиком(self) -> None:
        итог = hq.учесть(self.группы[гейт.РУЧНОЙ])
        осуждённые = [f.value for f, в in итог["строки"] if в.исход == НЕ_ГОДНО]
        self.assertEqual(len(осуждённые), ЛОЖНЫХ_РУЧНЫХ_ПОЗВОЛЕНО, осуждённые)

    def test_прочие_каналы_не_забракованы(self) -> None:
        итог = hq.учесть(self.группы[гейт.ПРОЧИЕ])
        доля = итог["осуждено"] / итог["checked"]
        self.assertLessEqual(доля, 0.01, f"осуждено {итог['осуждено']} из {итог['checked']}")

    def test_гейт_на_живой_базе_годен(self) -> None:
        вердикт = гейт.проверить()
        self.assertEqual(вердикт["outcome"], ГОДНО, вердикт.get("беды"))


if __name__ == "__main__":
    unittest.main()
