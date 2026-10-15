"""Чужой образ или голос: вопрос о согласии в исходе, знаменитость в рекламе — отказ.

НАЙДЕНО валидатором 5-го круга (2026-10-15):
  * «Make Taylor Swift sing…» читалось как человек «Make Taylor»;
  * «голосом Путина» (голос, русский падеж, одна фамилия) не ловилось вовсе;
  * реклама от имени знаменитости получала полный план, предупреждение — в ноте.

Правило: реальный человек без названного согласия -> исход — ВОПРОС о
согласии/правах (Р1), он же первой строкой сводки; реклама от имени реальной
знаменитости -> отказ с причиной. Много негативных контролей (И5): обычные
слова с заглавной, бренды, выдуманные персонажи, «Иван» как родовое имя.
"""

from __future__ import annotations

import json
import os
import unittest

from studio.mcp import screen, server

ЛЮДИ = {
    "Make Taylor Swift sing a lullaby for my daughter": ["Taylor Swift"],
    "озвучь текст голосом Путина": ["Путина"],
    "ролик, где Путин поздравляет мою маму": ["Путин"],
    "voice of Obama reading a poem": ["Obama"],
    "sounds like Morgan Freeman narrating": ["Morgan Freeman"],
    "интервью, в кадре рассказывает Иван Петров": ["Иван Петров"],
    "озвучь голосом Ивановой": ["Ивановой"],
    "Elon Musk talks about Mars, a parody for my friends": ["Elon Musk"],
}

НИКОГО = (
    "Make it look good",
    "Generate Video Of A Cat",
    "Create A Beautiful Sunset Timelapse",
    "озвучь голосом Ивана",
    "озвучь голосом Алексеем",
    "наш ведущий Иван рассказывает о скидках",
    "Ivan from accounting reads the safety notice",
    "голосом Алисы прочитай сказку",
    "Mickey Mouse dances in our promo",
    "Harry Potter reads a spell, animated short",
    "Чебурашка поёт песенку",
    "Coca Cola ad, presenter speaks to camera",
    "Apple Watch promo, narrator speaks",
    "Suzuki Swift promo, narrator speaks",
    "a talking head ad for New York Pizza",
    "already shot in New York, need lipsync",
    "Our Product Launch Video, narrator speaks",
)

РЕКЛАМА_ЗНАМЕНИТОСТИ = {
    "Make Taylor Swift sing our jingle": ["celebrity endorsement: Taylor Swift"],
    "озвучь рекламу нашего банка голосом Путина": ["celebrity endorsement: Путина"],
    "Obama's voice reading our ad": ["celebrity endorsement: Obama"],
    "Make a video of Elon Musk endorsing my crypto token": ["celebrity endorsement: Elon Musk"],
}


class Имена(unittest.TestCase):
    def test_люди_найдены_целиком(self) -> None:
        for текст, ждём in ЛЮДИ.items():
            with self.subTest(текст=текст):
                self.assertEqual(ждём, screen.просеять(текст)["likeness"]["people"])

    def test_никого_не_назвали(self) -> None:
        for текст in НИКОГО:
            with self.subTest(текст=текст):
                self.assertEqual([], screen.просеять(текст)["likeness"]["people"])

    def test_хвост_имени_с_обеих_сторон(self) -> None:
        """Т1: «Иваном» (хвост 2) — имя; «Иванова» (хвост 3) — фамилия."""
        self.assertEqual(2, screen.ХВОСТ_ИМЕНИ)
        self.assertEqual([], screen.просеять("озвучь голосом Иваном")["likeness"]["people"])
        self.assertEqual(["Иванова"], screen.просеять("озвучь голосом Иванова")["likeness"]["people"])


class Согласие(unittest.TestCase):
    def test_названное_согласие_видно(self) -> None:
        for текст in (
            "our CEO John Smith speaks about the quarter, he agreed and signed a release",
            "Мой друг Сергей Иванов говорит тост, у нас есть согласие",
        ):
            with self.subTest(текст=текст):
                self.assertTrue(screen.просеять(текст)["likeness"]["consent_stated"])

    def test_без_согласия_не_согласие(self) -> None:
        лик = screen.просеять("Иван Петров рассказывает о банке без его согласия")["likeness"]
        self.assertFalse(лик["consent_stated"])


class РекламаЗнаменитости(unittest.TestCase):
    def test_отказ_с_причиной(self) -> None:
        for текст, ждём in РЕКЛАМА_ЗНАМЕНИТОСТИ.items():
            with self.subTest(текст=текст):
                итог = screen.просеять(текст)
                self.assertEqual("fail", итог["outcome"])
                self.assertEqual(ждём, итог["banned"])

    def test_знаменитость_не_в_рекламе_не_отказ(self) -> None:
        """И5: колыбельная для дочери — не реклама; это вопрос о согласии."""
        итог = screen.просеять("Make Taylor Swift sing a lullaby for my daughter")
        self.assertEqual("pass", итог["outcome"])

    def test_частный_человек_в_рекламе_не_отказ(self) -> None:
        итог = screen.просеять("наш сотрудник Иван Петров рассказывает про наш банк")
        self.assertEqual(("pass", []), (итог["outcome"], итог["banned"]))


class ПланСпрашивает(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["STUDIO_NO_JOURNAL"] = "1"

    def test_голос_знаменитости_вопрос_в_исходе_и_сводке(self) -> None:
        итог = json.loads(server.план_по_тексту("Make Taylor Swift sing a lullaby for my daughter, 15 seconds"))
        self.assertEqual(("could not measure", "нужен_ответ_заказчика"), (итог["outcome"], итог["reason"]))
        # С 6-ГО КРУГА без `spec.people` вопрос — КТО это (запасной путь), а
        # не угаданный «реальный человек»; подсказка вызывающему — в «что дальше».
        self.assertEqual("люди_в_заказе", итог["question"]["axis"])
        self.assertTrue(итог["summary"].startswith("QUESTION: the order names a person (Taylor Swift)"))
        self.assertIn("fill spec.people", итог["что_дальше"])
        self.assertTrue(итог["steps"], "план-черновик остаётся")

    def test_русский_голос_вопрос(self) -> None:
        итог = json.loads(server.план_по_тексту("озвучь текст голосом Путина, 20 секунд"))
        self.assertEqual("люди_в_заказе", итог["question"]["axis"])
        self.assertTrue(итог["summary"].startswith("ВОПРОС: в заказе назван человек (Путина)"))

    def test_согласие_названо_вопроса_нет(self) -> None:
        итог = json.loads(
            server.план_по_тексту(
                "our CEO John Smith speaks about the quarter, he agreed and signed a release, 20 seconds talking head"
            )
        )
        # С 6-ГО КРУГА вопрос о людях — две оси; ни одной быть не должно.
        self.assertNotIn((итог.get("question") or {}).get("axis"), ("согласие_на_образ", "люди_в_заказе"))
        self.assertEqual(["John Smith"], итог["people_policy"]["consent_recorded"])

    def test_реклама_знаменитости_отказ_плана(self) -> None:
        итог = json.loads(server.план_по_тексту("Make Taylor Swift sing our jingle, 15 seconds ad"))
        self.assertEqual(("fail", "запрещённая_тема", []), (итог["outcome"], итог["reason"], итог["steps"]))
        self.assertIn("an advert put in the mouth of a real celebrity", итог["note"])


if __name__ == "__main__":
    unittest.main()
