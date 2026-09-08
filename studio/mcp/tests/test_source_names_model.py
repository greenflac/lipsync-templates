"""Утверждение о модели X, снятое со страницы модели Y.

ЗАЧЕМ. Независимая проверка каналов 2026-09-05 нашла в живой базе строки, где
карточка одной модели процитирована как источник утверждения о ДРУГОЙ, и пять
из них стоят на ступени `vendor` — то есть выдаются за слова самого вендора:

    wan2.1-t2v-1.3b  <- карточка Wan2.1-T2V-14B    (другая модель семейства)
    latentsync-1.5   <- карточка LatentSync-1.6    (другая версия)
    gpt-5            <- карточка Kimi-K2-Thinking  (карточка КОНКУРЕНТА)

Ожидаемое — литералы (Т2), сети нет (Т4), входы с обоих краёв (Т3).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

from studio.selfrag.facts import Fact

_SPEC = importlib.util.spec_from_file_location(
    "check_source_names_model",
    Path(__file__).resolve().parents[3] / "scripts" / "check_source_names_model.py",
)
assert _SPEC and _SPEC.loader
проверка = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(проверка)


def факт(model: str, url: str, tier: str = "vendor") -> Fact:
    return Fact(
        model=model,
        attribute="failure_mode",
        value="ломается",
        source_url=url,
        tier=tier,
        stated_on="2026-09-05",
    )


class ЧужаяКарточкаНазываетсяВслух(unittest.TestCase):
    def test_другая_версия_это_чужая_карточка(self):
        живой = факт("latentsync-1.5", "https://huggingface.co/ByteDance/LatentSync-1.6")
        self.assertEqual("LatentSync-1.6", проверка.чужая_карточка(живой))

    def test_карточка_конкурента_это_чужая_карточка(self):
        живой = факт("gpt-5", "https://huggingface.co/moonshotai/Kimi-K2-Thinking", "portal")
        self.assertEqual("Kimi-K2-Thinking", проверка.чужая_карточка(живой))

    def test_своя_карточка_не_нарушение(self):
        """Негативный контроль (И5): проверка, объявляющая чужой каждую строку,
        не отличается от отсутствия проверки."""
        свой = факт("latentsync-1.6", "https://huggingface.co/ByteDance/LatentSync-1.6")
        self.assertEqual("", проверка.чужая_карточка(свой))

    def test_другое_написание_имени_это_та_же_модель(self):
        """`LatentSync-1.6` и `latentsync-1.6` — одна модель; свёртка написаний
        решает это раньше, чем сравнение строк."""
        свой = факт("LatentSync-1.6", "https://huggingface.co/ByteDance/latentsync-1.6")
        self.assertEqual("", проверка.чужая_карточка(свой))

    def test_json_эндпоинт_не_карточка(self):
        """Второй негативный контроль. `huggingface.co/api/models/ВЛАДЕЛЕЦ/МОДЕЛЬ`
        держит имя на два сегмента правее; общий разбор читал его как «модель
        models» и объявил чужими четыре живые строки — поймано чтением выдачи
        глазами (П3), первый замер был 21 вместо 10."""
        живой = факт(
            "mochi-1-preview", "https://huggingface.co/api/models/genmo/mochi-1-preview", "portal"
        )
        self.assertEqual("", проверка.чужая_карточка(живой))

    def test_не_карточка_вообще_не_судится(self):
        for url in (
            "https://arxiv.org/abs/2311.17982",
            "https://fal.ai/models/x",
            "https://huggingface.co/papers/2502.01234",
            "",
        ):
            self.assertEqual("", проверка.чужая_карточка(факт("kling-3.0", url, "paper")), url)

    def test_класс_моделей_под_звёздочкой_не_судится(self):
        """Строка про класс моделей (`*`) не приписана никакой карточке."""
        живой = факт("*", "https://huggingface.co/ByteDance/LatentSync-1.6", "paper")
        self.assertEqual("", проверка.чужая_карточка(живой))

    def test_потолок_ровно_десять(self):
        """Литерал (Т2): ратчет обязан только падать, и его сегодняшнее
        значение — измеренное состояние живой базы."""
        self.assertEqual(10, проверка.ПОТОЛОК)


if __name__ == "__main__":
    unittest.main()
