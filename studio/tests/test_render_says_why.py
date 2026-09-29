"""Причина отказа обязана стоять В БЛОКЕ ШАГА, а не одним словом в шапке.

ВОСПРОИЗВЕДЕНО 2026-09-05 независимым аудитом и прогоном. Модель с лицензией
`CC BY-NC 4.0: non-commercial research only`, бриф «есть готовое видео и своя
дорожка — сделай липсинк». Валидатор отверг план, и вот что читал заказчик:

    исход: не годно [валидатор_отверг] — … слабейшее звено: липсинк — лицензия
    классы валидатора: лицензия
      шаг липсинк: acme-lipsync — применимость измерена: 1 строк(и)
          вход шага: вход разрешён явно …
          выход шага: отдаёт нужный вид …
          цена: 1.0 usd за minute
          чем выбран: observed_behaviour=губы держат синхрон …

Нота пробы — «лицензия acme-lipsync содержит «non-commercial», а применение
заявлено как коммерческое» — лежала в JSON и НЕ ПЕЧАТАЛАСЬ НИГДЕ. Блок шага
читается как полностью здоровый: вход разрешён, выход тот, цена есть, довод
за модель приведён.

ЧЕМ ЭТО ОПАСНО. Слово «лицензия» в перечне классов не говорит НИ ЧТО не так,
НИ у какой модели. Человек, читающий блок шага, видит одни зелёные строки и
уходит в коммерческую работу с моделью, которую лицензия запрещает. Это худший
вид уверенного ответа: отказ формально прозвучал, а содержания у него нет.
"""

from __future__ import annotations

import unittest
from datetime import date

import studio.planner as pn
from studio.selfrag.facts import Fact

СЕГОДНЯ = date(2026, 9, 5)


def _факт(attribute: str, value: str, tier: str = "vendor", **прочее) -> Fact:
    return Fact(
        model="acme-lipsync",
        attribute=attribute,
        value=value,
        source_url="https://vendor.test/p",
        tier=tier,
        stated_on="2026-09-01",
        **прочее,
    )


ЗДОРОВЫЕ = [
    _факт("positioning", "lipsync model for talking-head video"),
    _факт("accepts_inputs", "аудио, видео"),
    _факт("produces_outputs", "видео"),
    _факт(
        "observed_behaviour",
        "lipsync: губы держат синхрон, лицо не плывёт",
        tier="operator",
        witnessed="прогнали 10 с",
    ),
    _факт("price_per_minute", "$1 per minute of video"),
]
БРИФ = "есть готовое видео и своя дорожка — сделай липсинк"


def _текст(факты) -> str:
    return pn.render(pn.plan(БРИФ, facts=факты, today=СЕГОДНЯ))


class ОтказНазываетПричину(unittest.TestCase):
    def test_некоммерческая_лицензия_названа_в_тексте(self) -> None:
        текст = _текст(ЗДОРОВЫЕ + [_факт("license", "CC BY-NC 4.0: non-commercial research only")])
        self.assertIn("non-commercial", текст)
        self.assertIn("acme-lipsync", текст)

    def test_названа_ИМЕННО_у_шага_а_не_только_в_шапке(self) -> None:
        """Шапка перечисляет классы; человек читает блок шага и решает по нему."""
        текст = _текст(ЗДОРОВЫЕ + [_факт("license", "CC BY-NC 4.0: non-commercial research only")])
        блок = текст.split("шаг липсинк")[-1]
        self.assertIn("non-commercial", блок)

    def test_здоровый_план_не_обрастает_страшилками(self) -> None:
        """Негативный контроль (И5): без нарушения новых строк не появляется.

        Прибор, который печатает предупреждение всегда, ничем не лучше прибора,
        который молчит всегда: читатель перестаёт их различать.
        """
        текст = _текст(ЗДОРОВЫЕ + [_факт("license", "Apache-2.0, commercial use permitted")])
        self.assertNotIn("non-commercial", текст)
        self.assertNotIn("ПОЧЕМУ ОТВЕРГНУТ", текст)


if __name__ == "__main__":
    unittest.main()
