"""Английский бриф спрашивается ТАК ЖЕ, как его русский близнец.

ЗАЧЕМ. ИЗМЕРЕНО 2026-09-07 на восьми парах близнецов (один и тот же бриф
по-английски и по-русски, поданный в `plan_pipeline`): три пары кончались
РАЗНЫМИ осями, и во всех трёх молчала английская сторона. Заказчик, писавший
«we need an online course where the teacher speaks english», получал план без
единственного вопроса, стоящего в продукте дороже всех прочих, тогда как
«нужен онлайн-курс, преподаватель говорит по-английски» этот вопрос получал.

Т2: ожидаемое здесь ЛИТЕРАЛЫ. Имя оси написано руками, а не импортировано из
`studio.clarify`: импортированное ожидание поедет вместе с кодом и промолчит.

Р1/Р2: набор печатает три числа — пар всего, сошлось, разошлось, — а не один
булев вердикт: «расхождений нет» при нуле сравненных пар не успех.
"""

from __future__ import annotations

import unittest

from studio import planner

#: Пары близнецов. Левое — английский бриф, правое — его русский перевод.
#: КОНСТАНТА-РЕШЕНИЕ набора: пары взяты и там, где обе стороны СПРАШИВАЮТ, и
#: там, где обе МОЛЧАТ (`talking head`, `ad`, `promo`, `movie scene`) — второе
#: и есть негативный контроль (И5): без таких пар «починка» вида «спрашивать
#: на всяком английском слове» прошла бы набор целиком.
БЛИЗНЕЦЫ: tuple[tuple[str, str], ...] = (
    (
        "we need an online course where the teacher speaks english",
        "нужен онлайн-курс, преподаватель говорит по-английски",
    ),
    (
        "we need a lesson where the teacher greets the student by name",
        "нужен урок, преподаватель здоровается со студентом по имени",
    ),
    (
        "we need an explainer where the host talks to camera",
        "нужен разъясняющий ролик, ведущий говорит в камеру",
    ),
    (
        "we need a business card video for the founder",
        "нужна видео-визитка для основателя",
    ),
    (
        "make me a talking head that greets the client by name",
        "сделайте говорящую голову, здоровается с клиентом по имени",
    ),
    ("we need an ad where the presenter speaks", "нужна реклама, ведущий говорит"),
    (
        "we need a promo where the avatar speaks our script",
        "нужен промо-ролик, аватар говорит наш сценарий",
    ),
    (
        "we need a movie scene where the actor speaks russian",
        "нужна сцена из фильма, актёр говорит по-русски",
    ),
)

#: Брифы НЕ ПРО НАШУ РАБОТУ, названные теми же словами (И5). На них вопрос
#: обязан не задаваться вовсе.
ЧУЖИЕ: tuple[str, ...] = (
    "write an explainer article about the generative video market",
    "Write a blog post about the generative video market",
    "of course we need a voiceover",
    "of course, we need a voiceover for the podcast",
)


def ось(бриф: str) -> str | None:
    """Ось вопроса так, как её получает заказчик: после замыкания плана."""
    есть = planner.inputs_of(бриф)
    операции, дописаны = planner.замкнуть(planner.derive(бриф), есть)
    вопрос = planner.вопрос_по_плану(бриф, операции, есть, дописаны)
    return вопрос.ось if вопрос else None


class ЯзыкБрифаНеМеняетОси(unittest.TestCase):
    def test_все_пары_близнецов_сходятся(self):
        разошлись = [(en, ось(en), ось(ru)) for en, ru in БЛИЗНЕЦЫ if ось(en) != ось(ru)]
        self.assertEqual(
            [],
            разошлись,
            f"пар {len(БЛИЗНЕЦЫ)}, сошлось {len(БЛИЗНЕЦЫ) - len(разошлись)}, "
            f"разошлось {len(разошлись)}",
        )

    def test_английский_курс_спрашивает_про_исходник(self):
        self.assertEqual(
            "есть_ли_исходное_видео",
            ось("we need an online course where the teacher speaks english"),
        )

    def test_английский_урок_спрашивает_про_исходник(self):
        self.assertEqual(
            "есть_ли_исходное_видео",
            ось("we need a lesson where the teacher greets the student by name"),
        )

    def test_английский_explainer_спрашивает_про_исходник(self):
        self.assertEqual(
            "есть_ли_исходное_видео",
            ось("we need an explainer where the host talks to camera"),
        )


class ГдеМолчимПоАнглийски(unittest.TestCase):
    def test_негативный_контроль_чужое_ремесло(self):
        """И5. `explainer` в списке слов результата — и заказчик ТЕКСТА про
        него получал бы вопрос «есть ли у вас отснятое видео?»."""
        задано = [б for б in ЧУЖИЕ if ось(б) is not None]
        self.assertEqual([], задано, f"чужих брифов {len(ЧУЖИЕ)}, спрошено {len(задано)}")

    def test_голое_course_не_заведено(self):
        """И6, отрицательный результат: подстрока «course» живёт внутри «of
        course», и потому в список взяты только `online course`/`video course`."""
        self.assertIsNone(ось("of course we need a voiceover"))

    def test_английский_ответ_заказчика_закрывает_ось(self):
        """Круг вопроса: заказчик отвечает предложенным вариантом и обязан
        получить НЕ тот же экран."""
        self.assertIsNone(ось("Lip sync our footage. I have the video"))
        self.assertIsNone(ось("Lip sync our footage. Nothing is shot, make it from scratch"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
