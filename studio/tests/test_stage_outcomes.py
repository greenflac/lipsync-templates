"""Стадии сессии: каждая названа исходом ПОИМЁННО, а не «одной из группы».

ЗАЧЕМ ОТДЕЛЬНЫЙ ФАЙЛ (Ц2): `test_app.py` писал другой автор.

ЧТО ЭТО ЗАКРЫВАЕТ. Мутация «убрать `STAGE_DONE` из разрешённых стадий»
2026-09-04 промолчала: в наборе не было случая с завершённой сессией. Цена —
заказчик, у которого работа ДОДЕЛАНА, получил бы «кадр не показан» и пошёл бы
генерировать его заново.

Проверяется КАЖДАЯ стадия по отдельности, а не «хотя бы одна из списка»: за
день это была самая частая форма слабого теста в репозитории (список,
сторожимый одним своим членом).
"""

from __future__ import annotations

import unittest

from studio.app import (
    STAGE_CONSENTED,
    STAGE_DONE,
    STAGE_FRAME_RUNNING,
    STAGE_FRAME_SHOWN,
    STAGE_REVIEW,
    STAGE_VIDEO_RUNNING,
    frame_state,
)

#: Стадии, на которых первый кадр УЖЕ показан. Литералами (Т2): имена стадий —
#: это протокол между сервером и страницей, и молчаливое переименование одной
#: из них ломает поток у заказчика, а не в тесте.
КАДР_ПОКАЗАН = ("frame_shown", "consented", "video_running", "done")


class КаждаяСтадияСудитсяОтдельно(unittest.TestCase):
    def test_имена_стадий_не_переименованы(self) -> None:
        self.assertEqual("frame_shown", STAGE_FRAME_SHOWN)
        self.assertEqual("consented", STAGE_CONSENTED)
        self.assertEqual("video_running", STAGE_VIDEO_RUNNING)
        self.assertEqual("done", STAGE_DONE)
        self.assertEqual("needs_review", STAGE_REVIEW)
        self.assertEqual("frame_running", STAGE_FRAME_RUNNING)

    def test_на_каждой_из_четырёх_стадий_кадр_считается_показанным(self) -> None:
        for стадия in КАДР_ПОКАЗАН:
            with self.subTest(стадия):
                итог = frame_state({"stage": стадия, "last_job_id": "j1"})
                self.assertEqual("pass", итог["outcome"], итог)

    def test_завершённая_сессия_не_просит_генерировать_кадр_заново(self) -> None:
        """Тот самый случай, которого не было: работа доделана — кадр показан."""
        итог = frame_state({"stage": STAGE_DONE, "last_job_id": "j1"})
        self.assertEqual("pass", итог["outcome"], итог)
        self.assertIn("shown", итог["note"])

    def test_ожидание_человека_это_третий_исход(self) -> None:
        итог = frame_state({"stage": STAGE_REVIEW, "last_job_id": "j1"})
        self.assertEqual("could not measure", итог["outcome"], итог)
        self.assertEqual(1, итог["unmeasured"])

    def test_чужая_стадия_это_не_годно_а_не_молчание(self) -> None:
        """И5: прибор обязан УМЕТЬ сказать «нет» на стадии, которой не знает."""
        итог = frame_state({"stage": "styled", "last_job_id": None})
        self.assertEqual("fail", итог["outcome"], итог)


if __name__ == "__main__":
    unittest.main()
