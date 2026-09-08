"""Схема эндпоинта: какой вход модель принимает.

Сети нет (Т4), ожидаемое — литералы (Т2). Все имена полей ниже — ИЗ ЖИВЫХ СХЕМ
портала: правило выведено из 102 имён, встреченных на 37 эндпоинтах, а не
придумано. Половина тестов — негативный контроль (И5): ложное отрицание,
записанное как факт, хуже отсутствия строки.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "ingest_schema", Path(__file__).resolve().parents[3] / "scripts" / "ingest_schema.py"
)
assert SPEC and SPEC.loader
sc = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sc)


class ВидВхода(unittest.TestCase):
    def test_приставка_перед_видом_не_мешает(self):
        """ПОЙМАНО НА ЖИВОМ ЗАХОДЕ: закрытый список имён промахнулся, и в базу
        ушло `kling-video-o1-image-to-video / accepts_inputs = «текст»` — у
        эндпоинта с `start_image_url` и `end_image_url`."""
        for поле in ("start_image_url", "end_image_url", "source_image_url"):
            with self.subTest(поле=поле):
                self.assertEqual(sc.вид_входа(поле), "изображение")

    def test_вид_ловится_в_середине_имени(self):
        self.assertEqual(sc.вид_входа("driven_audio_url"), "аудио")
        self.assertEqual(sc.вид_входа("reference_pose_video_url"), "видео")

    def test_текст_под_разными_именами(self):
        for поле in ("prompt", "text", "text_input", "multi_prompt", "first_text_input"):
            with self.subTest(поле=поле):
                self.assertEqual(sc.вид_входа(поле), "текст")


class ЭтоНеВход(unittest.TestCase):
    """Все восемь имён — из живых схем; в каждом есть слово, входа нет."""

    def test_переключатель_вывода_входом_не_является(self):
        """`generate_audio` — булев флаг «добавить звук на выходе». Суффикс
        `_url` и есть разделитель, отличающий вход от флага."""
        self.assertEqual(sc.вид_входа("generate_audio"), "")
        self.assertEqual(sc.вид_входа("preserve_audio"), "")
        self.assertEqual(sc.вид_входа("use_only_first_audio"), "")

    def test_настройки_входом_не_являются(self):
        for поле in ("image_size", "num_images", "video_quality", "video_write_mode"):
            with self.subTest(поле=поле):
                self.assertEqual(sc.вид_входа(поле), "")

    def test_уточнение_промпта_отдельным_входом_не_считается(self):
        self.assertEqual(sc.вид_входа("negative_prompt"), "")


class ЗаявкиИзСхемы(unittest.TestCase):
    def _вход(self, props: dict) -> dict:
        return {"properties": props}

    def test_входы_собираются_без_повторов_и_по_алфавиту(self):
        з = sc.заявки(
            "fal-ai/x",
            self._вход({"image_url": {}, "start_image_url": {}, "audio_url": {}, "seed": {}}),
        )
        self.assertEqual([(с[1], с[2]) for с in з], [("accepts_inputs", "аудио, изображение")])

    def test_перечисление_берётся_под_именем_из_базы(self):
        """Иначе семья атрибутов получит шестое написание одного и того же."""
        з = sc.заявки(
            "fal-ai/x",
            self._вход({"resolution": {"enum": ["480p", "720p"]}, "duration": {"enum": [5, 10]}}),
        )
        имена = {с[1] for с in з}
        self.assertIn("resolution_enum", имена)
        self.assertIn("duration_enum_seconds", имена)

    def test_поле_без_перечисления_строки_не_даёт(self):
        з = sc.заявки("fal-ai/x", self._вход({"resolution": {"type": "string"}}))
        self.assertEqual([с[1] for с in з], [])

    def test_имя_текста_из_живой_схемы(self):
        """`mirage-api/avatar-x/text-to-video` называет текст полем `script`;
        без него у эндпоинта «text-to-video» в базу ушло «принимает: аудио,
        видео» — ложное отрицание третьим заходом подряд."""
        self.assertEqual(sc.вид_входа("script"), "текст")

    def test_неопознанное_поле_ссылка_называется_в_ноте(self):
        """`file_urls` у `heygen/v3/video-agent` — «URLs of files to include as
        assets (images, ...)»: вход есть, вид из имени не следует. Строка
        «принимает: текст» была бы ВЕРНА и НЕПОЛНА, а читается как полный
        список."""
        нота = sc.заявки("fal-ai/x", self._вход({"prompt": {}, "file_urls": {}}))[0][4]
        self.assertIn("НЕПОЛОН", нота)
        self.assertIn("1", нота)

    def test_когда_всё_опознано_ноты_о_неполноте_нет(self):
        """Вторая половина (И5): пометка, стоящая всегда, перестаёт читаться."""
        нота = sc.заявки("fal-ai/x", self._вход({"prompt": {}, "image_url": {}}))[0][4]
        self.assertNotIn("НЕПОЛОН", нота)

    def test_схема_без_входов_молчит(self):
        self.assertEqual(sc.заявки("fal-ai/x", self._вход({"seed": {}})), [])


class ЧтоМодельВЫДАЁТ(unittest.TestCase):
    """ПОЙМАНО НА ЖИВОМ ПРОГОНЕ ЧЕРЕЗ MCP: шагу «озвучка» (produces: аудио)
    планировщик выбрал `pixverse-lipsync` — липсинк-модель с перечнем голосов в
    схеме, — а выдаёт она `video`. Шаг, которому нужен звук, получил модель,
    которая звука не отдаёт: вход проверялся, выход — нет.
    """

    def test_артефакт_выхода_опознаётся(self):
        self.assertEqual(sc.вид_выхода("video", {"$ref": "#/components/schemas/File"}), "видео")
        self.assertEqual(sc.вид_выхода("audio", {"$ref": "#/components/schemas/File"}), "аудио")

    def test_скалярное_поле_артефактом_не_является(self):
        """`seed` (integer) и `timestamps` — сопровождающие числа, а не то, что
        модель отдаёт. Отсекаются по ТИПУ, а не по имени."""
        self.assertEqual(sc.вид_выхода("seed", {"type": "integer"}), "")
        self.assertEqual(sc.вид_выхода("timestamps", {}), "")

    def test_строка_артефактом_не_считается(self):
        """ИЗМЕРЕНО на 20 схемах выхода: ни одно поле с видом в имени не имеет
        типа `string` — артефакты приходят как `$ref` на File (13 полей) или
        массивом (2). Строками типизированы `request_id` и `prompt`, то есть не
        артефакты.

        ГРАНИЦА, НАЗВАННАЯ ВСЛУХ: правило верно ДЛЯ ЭТОГО портала. Площадка,
        отдающая ссылку строкой (`video: {type: string}`), потеряется — и это
        придётся заметить на её первых же строках, а не выводить из общих
        соображений сейчас."""
        self.assertEqual(sc.вид_выхода("video", {"type": "string"}), "")

    def test_массив_артефактов_это_артефакт(self):
        """`portrait-enhance.images` — массив: `images: {type: array}` отдаёт
        картинки, и выбросить его значило бы не заметить выход целиком."""
        self.assertEqual(sc.вид_выхода("images", {"type": "array"}), "изображение")

    def test_поле_с_видом_но_скалярное_тоже_не_артефакт(self):
        """Вторая половина (И5): имя не решает. `video_quality: integer` —
        настройка, а не выход."""
        self.assertEqual(sc.вид_выхода("video_quality", {"type": "integer"}), "")

    def test_выход_едет_строкой_в_заявках(self):
        вход = {"properties": {"audio_url": {}}, "_выход": {"properties": {"video": {}}}}
        з = {с[1]: с[2] for с in sc.заявки("fal-ai/x", вход)}
        self.assertEqual(з.get("produces_outputs"), "видео")
        self.assertEqual(з.get("accepts_inputs"), "аудио")

    def test_схема_без_выхода_строки_не_даёт(self):
        з = [с[1] for с in sc.заявки("fal-ai/x", {"properties": {"audio_url": {}}})]
        self.assertNotIn("produces_outputs", з)


class ТриИсхода(unittest.TestCase):
    def test_молчание_переспрашивается_один_раз(self):
        """ИЗМЕРЕНО: из пяти эндпоинтов два не ответили, а на повторе ответили
        ОБА. Записать икоту третьим исходом значило бы занизить покрытие."""
        звонки = []

        def ответ(url: str) -> dict:
            звонки.append(url)
            if len(звонки) == 1:
                return {"outcome": "could not measure", "text": ""}
            return {
                "outcome": "pass",
                "text": json.dumps({"components": {"schemas": {"XInput": {"properties": {}}}}}),
            }

        with (
            mock.patch.object(sc.fetch, "fetch", ответ),
            mock.patch.object(sc.time, "sleep", lambda _: None),
        ):
            исход, _ = sc.спросить("fal-ai/x")
        self.assertEqual(исход, "pass")
        self.assertEqual(len(звонки), 2, "переспрашиваем ровно один раз")

    def test_второе_молчание_это_третий_исход(self):
        """И ЧУЖОЙ ХОСТ НЕ ДОЛБИТСЯ. Мутант «переспрашиваем пять раз» промолчал:
        тест на успешный повтор считает звонки, а на молчащем хосте их никто не
        считал — верхняя граница вежливости не сторожилась ничем."""
        звонки = []

        def ответ(url: str) -> dict:
            звонки.append(url)
            return {"outcome": "could not measure", "text": ""}

        with (
            mock.patch.object(sc.fetch, "fetch", ответ),
            mock.patch.object(sc.time, "sleep", lambda _: None),
        ):
            self.assertEqual(sc.спросить("fal-ai/x")[0], "could not measure")
        self.assertEqual(len(звонки), 2, "первый запрос и ровно один повтор")

    def test_ответ_без_схемы_входа_это_смена_формата(self):
        with mock.patch.object(
            sc.fetch, "fetch", lambda url: {"outcome": "pass", "text": json.dumps({"openapi": "3"})}
        ):
            self.assertEqual(sc.спросить("fal-ai/x")[0], "fail")


if __name__ == "__main__":
    unittest.main()
