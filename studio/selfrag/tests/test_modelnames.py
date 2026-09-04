"""Разрешение имени модели: склеивает написания, различает модели, умеет молчать.

Ожидаемые значения — литералы (правило Т2): ни одно из них не импортируется из
проверяемого модуля, иначе тест поедет вместе с кодом и промолчит. Сети здесь
нет (правило Т4): хранилище собирается из фактов, переданных в конструктор.

НЕГАТИВНЫЙ КОНТРОЛЬ (правило И5) — половина этого файла. Прибор, который
склеивает всё, отвечает «одна модель» на любой вход и потому не измеряет
ничего: пары РАЗНЫХ моделей обязаны остаться разными, а выдуманное имя —
остаться выдуманным.
"""

from __future__ import annotations

import unittest

from studio.selfrag.facts import Fact, FactStore
from studio.selfrag.modelnames import fold, resolve, similar


def факт(model: str, attribute: str = "max_seconds", value: str = "15") -> Fact:
    return Fact(
        model=model,
        attribute=attribute,
        value=value,
        source_url="https://example.test/x",
        tier="vendor",
        stated_on="2026-09-02",
    )


class Свёртка(unittest.TestCase):
    def test_разделители_и_регистр_не_меняют_имени(self) -> None:
        self.assertEqual(fold("FLUX.2-Klein-9B"), "flux2klein9b")
        self.assertEqual(fold("flux-2-klein-9b"), "flux2klein9b")
        self.assertEqual(fold("  flux 2  klein 9b "), "flux2klein9b")

    def test_область_остаётся_областью(self) -> None:
        """`*` не оформление: свёрнутая до пустоты область — это находка о
        классе, потерявшая имя."""
        self.assertEqual(fold("*"), "*")
        self.assertEqual(fold("eleven-*"), "eleven*")

    def test_разные_модели_остаются_разными(self) -> None:
        """Негативный контроль. Все три пары взяты из живой базы."""
        self.assertNotEqual(fold("flux-2-pro"), fold("flux-2-pro-edit"))
        self.assertNotEqual(fold("kling-3.0"), fold("kling-3.0-pro-i2v"))
        self.assertNotEqual(fold("eleven_v3"), fold("eleven_v3_conversational"))


class Разрешение(unittest.TestCase):
    база = ("flux.2-klein-9b", "flux-2-klein-9b", "kling-3.0", "ltx-2.3")

    def test_оба_написания_ведут_на_одну_модель(self) -> None:
        got = resolve("flux-2-klein-9b", self.база)
        self.assertEqual(got.outcome, "pass")
        self.assertEqual(got.reason, "resolved")
        self.assertEqual(list(got.names), ["flux-2-klein-9b", "flux.2-klein-9b"])
        self.assertEqual(got.canonical, "flux-2-klein-9b")

    def test_написание_которым_спросили_становится_каноническим(self) -> None:
        self.assertEqual(resolve("flux.2-klein-9b", self.база).canonical, "flux.2-klein-9b")

    def test_чужого_написания_хватает_чтобы_попасть_в_базу(self) -> None:
        got = resolve("FLUX 2 Klein 9B", self.база)
        self.assertEqual(got.outcome, "pass")
        self.assertEqual(got.canonical, "flux-2-klein-9b")

    def test_неизвестное_имя_это_третий_исход_с_подсказкой(self) -> None:
        """Р1: «не знаем такой модели» — не пустой ответ и не «не годно»."""
        got = resolve("kling-3.0-turbo", self.база)
        self.assertEqual(got.outcome, "could not measure")
        self.assertEqual(got.reason, "not_in_base")
        self.assertEqual(list(got.suggestions), ["kling-3.0"])
        self.assertEqual(got.names, ())
        self.assertEqual(got.unmeasured, 1)

    def test_чужак_получает_молчание_а_не_плохую_подсказку(self) -> None:
        """Негативный контроль: подсказка обязана уметь не подсказывать."""
        got = resolve("зззывыдумка", self.база)
        self.assertEqual(got.outcome, "could not measure")
        self.assertEqual(got.reason, "not_in_base")
        self.assertEqual(got.suggestions, ())

    def test_не_названное_имя_отличается_от_неизвестного(self) -> None:
        """Третий исход не сворачивается во второй: лечатся они по-разному."""
        got = resolve("   ", self.база)
        self.assertEqual(got.outcome, "could not measure")
        self.assertEqual(got.reason, "no_name_asked")

    def test_числа_печатаются_рядом_с_исходом(self) -> None:
        """Р2: сколько написаний нашлось и сколько имён просмотрено."""
        got = resolve("ltx-2.3", self.база)
        self.assertEqual(got.checked, 1)
        self.assertEqual(got.spellings_seen, 4)


class Подсказка(unittest.TestCase):
    def test_короткое_имя_это_шум_а_не_подсказка(self) -> None:
        self.assertEqual(similar("ltx", ("ltx-2.3", "ltx-2-3")), [])

    def test_разделители_не_идут_в_зачёт_общего_начала(self) -> None:
        """`flux-2` против `flux.2-dev`: общих знаков четыре, из них один —
        разделитель. Считаются только четыре БУКВЕННЫХ, и порог берётся."""
        self.assertEqual(similar("flux-2", ("flux.2-dev",)), ["flux.2-dev"])


class СклейкаНаЧтении(unittest.TestCase):
    """Оба кармана отвечают одним набором утверждений — без правки журнала."""

    def склад(self) -> FactStore:
        return FactStore(
            [
                факт("flux.2-klein-9b", "max_seconds", "5"),
                факт("flux.2-klein-9b", "failure_mode", "текст плывёт"),
                факт("flux-2-klein-9b", "resolution", "1024x1024"),
                факт("kling-3.0", "max_seconds", "10"),
            ]
        )

    def test_атрибуты_собираются_из_обоих_карманов(self) -> None:
        склад = self.склад()
        self.assertEqual(
            склад.attributes("flux-2-klein-9b"),
            ["failure_mode", "max_seconds", "resolution"],
        )
        self.assertEqual(
            склад.attributes("flux.2-klein-9b"),
            ["failure_mode", "max_seconds", "resolution"],
        )

    def test_утверждение_находится_по_любому_написанию(self) -> None:
        склад = self.склад()
        self.assertEqual(склад.claims("flux-2-klein-9b", "max_seconds")["values"], ["5"])
        self.assertEqual(склад.claims("flux.2-klein-9b", "resolution")["values"], ["1024x1024"])

    def test_провалы_видны_обоим_написаниям(self) -> None:
        склад = self.склад()
        self.assertEqual(len(склад.failure_modes("flux-2-klein-9b")), 1)
        self.assertEqual(len(склад.failure_modes("flux.2-klein-9b")), 1)

    def test_соседняя_модель_не_втягивается(self) -> None:
        """Негативный контроль склейки: у `kling-3.0` свой один атрибут."""
        self.assertEqual(self.склад().attributes("kling-3.0"), ["max_seconds"])

    def test_спорное_место_считается_один_раз_а_не_по_написанию(self) -> None:
        склад = FactStore(
            [
                факт("ltx-2.3", "max_seconds", "10"),
                факт("ltx-2-3", "max_seconds", "20"),
            ]
        )
        self.assertEqual(len(склад.contested()), 1)
        self.assertEqual(склад.claims("ltx-2-3", "max_seconds")["outcome"], "fail")

    def test_журнал_не_переписан(self) -> None:
        """Склейка живёт на чтении: строки остаются как записаны."""
        self.assertEqual(
            sorted(self.склад().models()),
            ["flux-2-klein-9b", "flux.2-klein-9b", "kling-3.0"],
        )


if __name__ == "__main__":
    unittest.main()


class ПриставкаВерсии(unittest.TestCase):
    """`sync-lipsync-v2` и `sync-lipsync-2` — одна модель.

    Т2: пары написаны литералами. Найдено 2026-09-03 при заходе за целью
    голден-сета: цена одной и той же модели с одного и того же адреса лежала
    под двумя именами, и вопрос об одном из них не видел строк другого.
    """

    #: Одна модель под двумя написаниями. Все семь пар взяты из живой базы.
    ОДНА_И_ТА_ЖЕ = (
        ("sync-lipsync-2", "sync-lipsync-v2"),
        ("sync-lipsync-3-image-to-video", "sync-lipsync-v3-image-to-video"),
        ("ideogram-3", "ideogram-v3"),
        ("wan-2.7-edit-video", "wan-v2.7-edit-video"),
        ("flux-pro-1.1-ultra", "flux-pro-v1.1-ultra"),
        ("bytedance-omnihuman-1.5", "bytedance-omnihuman-v1.5"),
        ("wan-2.2-14b-animate-replace", "wan-v2.2-14b-animate-replace"),
    )

    #: `v` ВНУТРИ СЛОВА, а не в начале звена: это часть имени, а не версия.
    #: Правило, ловящее `v` перед цифрой где угодно, превратило бы `wav2lip` —
    #: самую известную липсинк-модель базы — в `wa2lip` (И5). Найдено мутацией:
    #: первая редакция этого контроля сторожила `s2v`/`t2v`/`i2v`, где `v` стоит
    #: ПОСЛЕ цифры, слабое правило их не трогает, и мутант молчал.
    ВНУТРИ_СЛОВА = ("wav2lip", "proteusv0.3")

    def test_приставка_версии_склеивает(self) -> None:
        for а, б in self.ОДНА_И_ТА_ЖЕ:
            self.assertEqual(fold(а), fold(б), f"{а} и {б} остались разными")

    def test_буква_внутри_слова_не_срезается(self) -> None:
        self.assertEqual("wav2lip", fold("wav2lip"))
        self.assertEqual("proteusv03", fold("proteusv0.3"))

    def test_разные_модели_остались_разными(self) -> None:
        self.assertNotEqual(fold("eleven_v3"), fold("eleven_v3_conversational"))
        self.assertNotEqual(fold("flux-2-klein-4b"), fold("flux-2-klein-9b"))

    def test_таблица_имён_склеивает_площадку_с_репозиторием(self) -> None:
        """Т1: строка таблицы — решение об идентичности, и она под тестом.

        Разбор 2026-09-04: `infinitalk` (площадка fal, 7 строк, есть схема, нет
        применимости) и `infinitetalk` (репозиторий MeiGen-AI, 12 строк, есть
        применимость, нет схемы) — одна модель. Из-за разъезда написаний
        планировщик выбирал её вслепую: наблюдения лежали под именем, которого
        он не видел.
        """
        self.assertEqual(fold("infinitalk"), fold("infinitetalk"))
        self.assertEqual(fold("InfiniTalk"), fold("infinitetalk"))
        # Площадка ставит впереди имя лаборатории, статья — нет, и версия
        # совпадает: `fal-ai/bytedance/omnihuman/v1.5` против `omnihuman-1.5`.
        self.assertEqual(fold("bytedance-omnihuman"), fold("omnihuman-1"))
        self.assertEqual(fold("bytedance-omnihuman-v1.5"), fold("omnihuman-1.5"))

    def test_версии_одной_модели_остались_разными(self) -> None:
        """Склейка по лаборатории не смеет склеить ВЕРСИИ (И5).

        `omnihuman-1` и `omnihuman-1.5` — разные модели с разными наблюдениями,
        и таблица обязана довести до разных ключей обе стороны.
        """
        self.assertNotEqual(fold("omnihuman-1"), fold("omnihuman-1.5"))
        self.assertNotEqual(fold("bytedance-omnihuman"), fold("bytedance-omnihuman-v1.5"))

    def test_таблица_не_склеила_соседнюю_модель(self) -> None:
        """Негативный контроль к таблице (И5), и он не формальный.

        Поле `about` в схеме fal называет эндпоинт словом «MultiTalk» — имя
        СОСЕДНЕЙ модели той же лаборатории, у которой свой репозиторий и свои
        наблюдения. Склеить её сюда значило бы приписать модели чужое, а это
        худшее, что умеет этот продукт.
        """
        self.assertNotEqual(fold("multitalk"), fold("infinitetalk"))
