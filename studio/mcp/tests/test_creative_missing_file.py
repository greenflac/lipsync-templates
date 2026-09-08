"""«Файла нет» и «нечем измерить» — РАЗНЫЕ новости, и это проверяется здесь.

НАЙДЕНО 2026-09-07 на живом прогоне продукта. Вход:

    plan_pipeline(brief="у меня есть своё видео, надо просто переозвучить...",
                  creative=".../assets/x.mp4")   # файла не существует

Выдача была:

    "creative": {"path": ".../x.mp4", "width": null, "height": null,
      "outcome": "could not measure",
      "note": "креатив не измерен: 0 thing(s) measured, 0 against the engine's
               bars, 5 not measurable; NOT RUN: look, intake, video_decode"}

Верхний исход у НЕСУЩЕСТВУЮЩЕГО файла был ровно тот же, что у настоящего файла,
которому не хватило пакета: `could not measure`. «Файла нет» лежало на два
уровня ниже, в `could_not_run[0].why`, вперемешку с тремя строками про
отсутствующий `insightface`, к пути не относящимися вовсе. Заказчик, принёсший
своё видео, получал план и не узнавал, что его видео никто не открывал.

Цена у этих двух новостей разная: путь заказчик поправит за пять секунд,
отсутствующий пакет он не поправит никогда. Свёрнутые в один исход, они
нарушали Р1.

ЧТО ЗДЕСЬ ПРОВЕРЯЕТСЯ. Три состояния входа, каждое своим тестом, и оба конца
диапазона (И5): вход, на котором прибор ОБЯЗАН сказать «нет» (пути нет), и
вход, на котором он обязан шевельнуться (настоящий файл, с которого сняты
числа). Середина — файл на диске, а открыть его нечем — получается ПОДМЕНОЙ
пакета (`numpy` вынут из `sys.modules`), а не рассказом о ней.

Ожидаемые строки — ЛИТЕРАЛЫ (Т2): импортируй их из `creative`, и переименование
состояния уедет вместе с тестом и промолчит. Фикстуры рисуются Pillow здесь же,
сети нет ни в одном тесте (Т4 держит раннер `scripts/run_tests.py`).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from studio.mcp import creative

#: Те же три строки, что печатает продукт, набранные ЗДЕСЬ РУКАМИ (Т2).
MISSING = "no file at that path"
UNOPENED = "the file is there, but nothing could open it"
MEASURED = "the file was opened and measured"

#: И то же самое про каталог кадров — второе место той же формы (И7).
FRAMES_NONE = "no frames were handed in"
FRAMES_MISSING = "no frames at that directory"
FRAMES_GIVEN = "frames were handed in"

#: Верхний исход дома, тоже литералом.
COULD_NOT_MEASURE = "could not measure"


def _real_png(path: Path) -> str:
    Image.new("RGB", (64, 64), (10, 10, 10)).save(path)
    return str(path)


class ТриСостоянияВхода(unittest.TestCase):
    """Ни одно из трёх не сворачивается в другое (Р1)."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def test_ФАЙЛА_НЕТ_названо_в_верхней_строке_ответа(self) -> None:
        """Сам дефект. Раньше это было `could not measure` без единого слова
        о пути, и причину приходилось выкапывать из `could_not_run[0].why`."""
        итог = creative.analyse(self.tmp / "x.mp4")
        assert итог["input"]["state"] == MISSING, итог["input"]
        assert итог["outcome"] == COULD_NOT_MEASURE
        assert итог["note"].startswith(MISSING), итог["note"]
        assert "x.mp4" in итог["input"]["why"]

    def test_НАСТОЯЩИЙ_ФАЙЛ_даёт_состояние_измерено(self) -> None:
        """Негативный контроль (И5): вход, на котором прибор обязан
        шевельнуться. Без него починкой сошло бы «всегда говорить: файла нет»,
        и все остальные проверки остались бы зелёными."""
        итог = creative.analyse(_real_png(self.tmp / "real.png"))
        assert итог["input"]["state"] == MEASURED, итог["input"]
        assert итог["checked"] > 0, итог["note"]
        # Состояние стоит в НАЧАЛЕ верхней строки во всех трёх случаях, а не
        # только у отсутствующего файла: читают первую строку.
        assert итог["note"].startswith(MEASURED), итог["note"]

    def test_ФАЙЛ_ЕСТЬ_А_ПАКЕТА_НЕТ_это_третье_состояние_а_не_первое(self) -> None:
        """Середина диапазона, полученная ПОДМЕНОЙ: `numpy` вынут из
        `sys.modules`, и `look` получает ImportError на настоящем файле;
        замер лица подменён строкой ровно того вида, какой отдаёт живая
        среда без `insightface`. Файл при этом лежит на диске — и ответ
        обязан сказать «открыть нечем», а не «файла нет»."""
        настоящий = _real_png(self.tmp / "real.png")
        нет_лица = {
            "outcome": COULD_NOT_MEASURE,
            "checked": 0,
            "violations": 0,
            "unmeasured": 3,
            "note": "nothing to ask with: ModuleNotFoundError: No module named 'insightface'",
            "axes": {},
        }
        with (
            mock.patch.dict(sys.modules, {"numpy": None}),
            mock.patch.object(creative, "intake_of", return_value=нет_лица),
        ):
            итог = creative.analyse(настоящий)
        assert итог["input"]["state"] == UNOPENED, итог["input"]
        assert итог["outcome"] == COULD_NOT_MEASURE
        assert итог["checked"] == 0
        assert итог["note"].startswith(UNOPENED), итог["note"]
        # Причина названа, и она НЕ про путь.
        assert "insightface" in итог["could_not_run"][1]["why"]

    def test_три_состояния_это_три_РАЗНЫЕ_строки(self) -> None:
        """Если однажды два из них сольются в одну строку, весь этот файл
        станет проверять одно состояние вместо трёх и не покраснеет."""
        assert len({MISSING, UNOPENED, MEASURED}) == 3


class ЧтоИменноНеТакСПутём(unittest.TestCase):
    """«Файла нет» бывает четырёх видов, и заказчик чинит их по-разному."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def test_пустой_путь(self) -> None:
        итог = creative.analyse("")
        assert итог["input"]["state"] == MISSING
        assert итог["input"]["why"] == "путь к креативу не назван"

    def test_каталог_вместо_файла_назван_каталогом(self) -> None:
        итог = creative.analyse(self.tmp)
        assert итог["input"]["state"] == MISSING
        assert "каталог" in итог["input"]["why"], итог["input"]["why"]

    def test_битый_файл_это_НЕ_отсутствующий_файл(self) -> None:
        """Другой конец диапазона (Т3): байты на диске есть, читать их
        нечем. Свернуть это в «файла нет» значило бы послать заказчика
        чинить путь, который в порядке."""
        битый = self.tmp / "broken.png"
        битый.write_text("это не PNG", encoding="utf-8")
        итог = creative.analyse(битый)
        assert итог["input"]["state"] == UNOPENED, итог["input"]
        assert "could not be decoded" in итог["parts"]["look"]["note"]

    def test_у_несуществующего_файла_приборы_НЕ_запускаются(self) -> None:
        """До заплаты по несуществующему пути запускались все три прибора, и
        два из них жаловались на отсутствующий пакет — к пути не относящийся.
        Дешёвое раньше дорогого (П2): ffmpeg по пустому пути не зовётся."""
        итог = creative.analyse(self.tmp / "нет.mp4")
        assert итог["parts"] == {}
        assert итог["could_not_run"] == [
            {"instrument": "input", "why": f"по пути {self.tmp / 'нет.mp4'} файла нет"}
        ]


class ВТОРОЕ_МЕСТО_ТОЙ_ЖЕ_ФОРМЫ(unittest.TestCase):
    """`frames_dir` у `analyse_creative` сворачивал ровно те же две новости.

    ВОСПРОИЗВЕДЕНО 2026-09-07: инструмент читал каталог как
    `sorted(directory.glob("*"))`, несуществующий каталог давал пустой список,
    список доезжал до приборов движения и возвращался как

        "0 frame(s): the engine needs at least 3 to judge a loop"

    — теми же словами, какими отвечает НАСТОЯЩИЙ двухкадровый клип. «Каталога
    нет» и «в клипе мало кадров» — снова один исход на две новости.
    """

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def test_несуществующий_каталог_кадров_назван_а_не_превращён_в_ноль_кадров(self) -> None:
        итог = creative.frames_in(self.tmp / "нет-такого")
        assert итог["state"] == FRAMES_MISSING, итог
        assert итог["frames"] == []
        assert "нет" in итог["why"]

    def test_пустой_каталог_это_тоже_НЕТ_КАДРОВ_а_не_короткий_клип(self) -> None:
        пустой = self.tmp / "пусто"
        пустой.mkdir()
        итог = creative.frames_in(пустой)
        assert итог["state"] == FRAMES_MISSING, итог

    def test_каталог_не_назван_это_ТРЕТИЙ_исход_а_не_ошибка(self) -> None:
        """Обычный случай: кадров не подавали, и разбор вынет их сам. Свернуть
        его в «каталога нет» значило бы ругаться на правильный вызов."""
        assert creative.frames_in("")["state"] == FRAMES_NONE

    def test_НЕГАТИВНЫЙ_КОНТРОЛЬ_каталог_с_кадрами_отдаёт_кадры(self) -> None:
        for i in range(3):
            _real_png(self.tmp / f"f{i}.png")
        итог = creative.frames_in(self.tmp)
        assert итог["state"] == FRAMES_GIVEN, итог
        assert len(итог["frames"]) == 3

    def test_пустой_список_кадров_НЕ_отменяет_раскадровку_и_не_зовёт_движение(self) -> None:
        """Ловушка внутри самого разбора: `frames=[]` считался «кадры поданы».
        Прибор движения на пустом списке отвечал про короткий клип."""
        итог = creative.analyse(_real_png(self.tmp / "real.png"), frames=[])
        assert "motion" not in итог["parts"], итог["parts"].keys()


class ЭтоЖеВидноИЗПЛАНА(unittest.TestCase):
    """Планировщик берёт замер отсюда, и новость обязана доезжать до него."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.addCleanup(self._dir.cleanup)
        self.tmp = Path(self._dir.name)

    def test_строка_креатива_в_плане_называет_отсутствие_файла(self) -> None:
        from studio.planner import frame_of

        кадр, про_кадр = frame_of(str(self.tmp / "x.mp4"))
        assert кадр is None
        assert MISSING in про_кадр, про_кадр

    def test_НЕГАТИВНЫЙ_КОНТРОЛЬ_настоящий_файл_меряется_как_и_мерился(self) -> None:
        from studio.planner import frame_of

        кадр, про_кадр = frame_of(_real_png(self.tmp / "real.png"))
        assert кадр == (64, 64), про_кадр
        assert про_кадр == "64x64"


if __name__ == "__main__":
    unittest.main()
