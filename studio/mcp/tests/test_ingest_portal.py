"""Канал портала: цена словами, снятие с обслуживания и то, чего он не пишет.

Сети здесь нет (Т4), ожидаемое — литералы (Т2). Проверяется то, ради чего
канал заведён, и — важнее — то, что он обязан НЕ записать: поле с нулевым
разбросом и цена, которой портал не показал.
"""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path
from unittest import mock

SPEC = importlib.util.spec_from_file_location(
    "ingest_portal", Path(__file__).resolve().parents[3] / "scripts" / "ingest_portal.py"
)
assert SPEC and SPEC.loader
ip = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ip)


def карточка(**поля):
    основа = {
        "id": "veed/lipsync/v2",
        "title": "VEED Lipsync",
        # Портал отдаёт ОБА адреса, и они ведут в разные места: `modelUrl` —
        # это runtime, по которому человек не прочтёт ничего. Фикстура без
        # этого поля дала бы тесту пройти на запасной ветке и не сторожила бы
        # правило (мутант «источник — runtime-адрес» промолчал ровно так).
        "modelUrl": "https://fal.run/veed/lipsync/v2",
        "licenseType": "commercial",
        "status": "public",
        "deprecated": False,
        "removed": False,
        "hidePricing": False,
        "pricingInfoOverride": "Your request will cost **$0.07** for every second of output video.",
    }
    основа.update(поля)
    return основа


class ЦенаСловамиИсточника(unittest.TestCase):
    def test_разметка_снята_слова_целы(self):
        """`**` — оформление чужой страницы. Всё остальное трогать нельзя: «per
        second of OUTPUT video» — часть цены, а не украшение."""
        self.assertEqual(
            ip.цена(карточка()),
            "Your request will cost $0.07 for every second of output video.",
        )

    def test_число_не_вынимается(self):
        """Разбор в число живёт в `studio/pricing.py` и читает эту же строку.
        Вынуть `0.07` здесь значит потерять, за что берут, — и это уже стоило
        сравнения минуты с секундой."""
        значение = ip.заявки(карточка())[0][2]
        self.assertIn("every second of output video", значение)

    def test_цена_скрыта_это_не_ноль(self):
        self.assertEqual(ip.цена(карточка(hidePricing=True)), "")
        self.assertEqual(ip.цена(карточка(pricingInfoOverride="")), "")

    def test_скрытая_цена_не_пишется_вовсе(self):
        """Строка `price = ""` читалась бы как «бесплатно»."""
        атрибуты = [з[1] for з in ip.заявки(карточка(hidePricing=True))]
        self.assertNotIn("price", атрибуты)


class ЧемМодельЗанята(unittest.TestCase):
    """ИЗМЕРЕНО 2026-09-02: свежие имена с портала не доезжают до кандидатов
    планировщика — из 15 показанных на трёх брифах записанный вход был у
    ОДНОГО. У новых моделей в базе лежат цена и схема входа, и ни одного слова
    о том, ЧТО они делают, а якорный отбор ищет именно слова задачи.
    """

    def test_описание_записывается_словами_вендора(self):
        з = [
            с
            for с in ip.заявки(карточка(shortDescription="Generate lipsync from any audio"))
            if с[1] == "positioning"
        ]
        self.assertEqual(len(з), 1, з)
        self.assertEqual(з[0][2], "Generate lipsync from any audio")

    def test_имя_атрибута_уже_есть_в_базе(self):
        """Шестого написания одного и того же не заводим: `positioning` в базе
        уже стоит."""
        з = ip.заявки(карточка(shortDescription="x"))
        self.assertIn("positioning", [с[1] for с in з])

    def test_пустое_описание_строки_не_даёт(self):
        self.assertNotIn("positioning", [с[1] for с in ip.заявки(карточка(shortDescription=""))])
        self.assertNotIn("positioning", [с[1] for с in ip.заявки(карточка())])


class СнятаСОбслуживания(unittest.TestCase):
    """Рекомендовать снятую модель значит послать человека платить за 404."""

    def test_живая_модель_строки_не_даёт(self):
        self.assertEqual(ip.снята(карточка()), "")

    def test_три_поля_означают_разное_и_не_сливаются(self):
        значение = ip.снята(карточка(deprecated=True, removed=True, status="private"))
        self.assertIn("deprecated", значение)
        self.assertIn("removed", значение)
        self.assertIn("private", значение)

    def test_непубличный_статус_это_тоже_снятие(self):
        self.assertIn("private", ip.снята(карточка(status="private")))


class ЛицензияПорталаНеЛицензияМодели(unittest.TestCase):
    """ИЗМЕРЕНО: `licenseType` = `commercial` у 66 карточек из 66.

    Поле с нулевым разбросом не говорит о модели ничего, а прочитанное как
    свойство модели врёт в опасную сторону: условия ПЕРЕПРОДАЖИ площадкой — не
    лицензия весов, и `license = commercial` у модели, чьи веса лежат под
    «research only», дало бы ложный зелёный на правиле Ц5.
    """

    def test_у_модели_лицензии_с_портала_нет(self):
        атрибуты = [з[1] for з in ip.заявки(карточка())]
        self.assertNotIn("license", атрибуты)

    def test_одна_строка_об_области_а_не_о_модели(self):
        тело = json.dumps({"items": [карточка(), карточка(id="sync/lipsync/v2")], "pages": 1})
        with mock.patch.object(ip.fetch, "fetch", lambda url: {"outcome": "pass", "text": тело}):
            итог = ip.собрать(("lipsync",))
        лицензии = [з for з in итог["находки"] if з[1] == "portal_license"]
        self.assertEqual(len(лицензии), 1, лицензии)
        self.assertEqual(лицензии[0][0], "fal.ai-*", "область, а не модель")
        self.assertIn("commercial: 2", лицензии[0][2], "число карточек едет вместе со значением")

    def test_разброс_если_он_появится_будет_виден(self):
        """Вторая половина (И5): сводка обязана шевелиться. Если завтра портал
        начнёт продавать что-то на других условиях, строка это покажет, а не
        сплющит в одно слово."""
        тело = json.dumps(
            {
                "items": [карточка(), карточка(id="a/b", licenseType="research")],
                "pages": 1,
            }
        )
        with mock.patch.object(ip.fetch, "fetch", lambda url: {"outcome": "pass", "text": тело}):
            итог = ip.собрать(("lipsync",))
        значение = [з for з in итог["находки"] if з[1] == "portal_license"][0][2]
        self.assertIn("commercial: 1", значение)
        self.assertIn("research: 1", значение)


class ТриИсхода(unittest.TestCase):
    def test_смена_схемы_отличима_от_молчания(self):
        with mock.patch.object(
            ip.fetch, "fetch", lambda url: {"outcome": "pass", "text": "не json"}
        ):
            self.assertEqual(ip.спросить("lipsync", 1)[0], "fail")
        with mock.patch.object(
            ip.fetch, "fetch", lambda url: {"outcome": "could not measure", "text": ""}
        ):
            self.assertEqual(ip.спросить("lipsync", 1)[0], "could not measure")

    def test_имя_приводится_к_форме_базы(self):
        """Через `modelnames.from_portal_id` (Е1): опрос каталога и запись цен
        читают один портал и обязаны получать из одного `id` одно имя."""
        self.assertEqual(ip.заявки(карточка())[0][0], "veed-lipsync-v2")

    def test_источник_ведёт_на_читаемую_страницу(self):
        """`modelUrl` портала указывает на runtime `fal.run/...`, по которому
        человек ничего не прочтёт; проверяющий строку обязан получить страницу,
        которую можно открыть."""
        url = ip.заявки(карточка())[0][3]
        self.assertEqual(url, "https://fal.ai/models/veed/lipsync/v2")


if __name__ == "__main__":
    unittest.main()


class ЕдиницаЦеныИзСловЦены(unittest.TestCase):
    """Имя атрибута решает, как цену прочтёт разборщик бюджета.

    `studio/pricing.py` берёт единицу из ИМЕНИ атрибута и число — ПЕРВОЕ из
    текста. Поэтому единица, взятая от другого тарифа той же строки, делает из
    честной цены неверную, и проверка бюджета пропускает ошибку как обычное
    число.
    """

    def test_за_секунду_опознаётся(self):
        self.assertEqual(
            ip.атрибут_цены("Your request will cost $0.07 for every second of output video."),
            "price_per_second_usd",
        )

    def test_за_минуту_опознаётся(self):
        self.assertEqual(
            ip.атрибут_цены("Your request will cost $3 per minute of video."), "price_per_minute"
        )

    def test_два_тарифа_остаются_просто_ценой(self):
        """ПОЙМАНО чтением своей же выдачи: у latentsync «per second» относится
        ко ВТОРОМУ тарифу, а разборщик берёт первое число — выходило «$0.2 за
        секунду» вместо «$0.2 за ролик до 40 секунд», ошибка в сорок раз."""
        self.assertEqual(
            ip.атрибут_цены(
                "Your request will cost $0.2 for videos up to 40 seconds. For longer "
                "videos, you will be charged $0.005 per second of output video."
            ),
            "price",
        )

    def test_за_знаки_это_не_за_секунду(self):
        self.assertEqual(ip.атрибут_цены("$0.025 per 1000 characters"), "price")

    def test_за_генерацию_остаётся_просто_ценой(self):
        """Ideogram берёт за генерацию и называет цену по режимам качества.
        Подставить «за секунду» по умолчанию значит выдумать единицу."""
        self.assertEqual(
            ip.атрибут_цены("Your request will cost $0.1 with TURBO, $0.15 with BALANCED."),
            "price",
        )

    def test_единица_перед_суммой_тоже_считается(self):
        """Вторая половина (И5): близость двусторонняя. Портал пишет и
        «Priced per second ... 480p at $0.08/sec»."""
        self.assertEqual(
            ip.атрибут_цены("Priced per second of output video, by resolution: 480p at $0.08/sec"),
            "price_per_second_usd",
        )

    def test_доллар_после_числа_тоже_сумма(self):
        """Портал пишет и «0.06 $ per second» — не найдя суммы, правило
        осталось бы слепым на этой строке."""
        self.assertEqual(
            ip.атрибут_цены("Your request will be charged at 0.06 $ per second of generated video"),
            "price_per_second_usd",
        )
