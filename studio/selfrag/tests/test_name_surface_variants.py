"""Одна модель под любым оформлением имени — одна модель (аудит 4-го круга).

ЧТО НАЙДЕНО 2026-10-15. `Hailuo 2.3`, `minimax/hailuo-2.3`, `speech-02-hd` и
`ltx-2` отвечали «не смогли / возможно, опечатка», хотя единственный сосед в
базе — та же модель с вендором впереди; `kling 3 pro` вёл в корень `kling-3.0`,
хотя вариант pro в базе есть.

ЧТО СТОРОЖИТСЯ. (1) Прогон по ВСЕМ именам живой базы: обычные написания
(регистр, пробелы, дефисы, подчёркивания, слэши, площадка впереди, вендор
каталогом пути, точка/дефис в версии, вендор опущен при названной линейке)
сводятся к тому же имени, и тождеством, а не подсказкой. (2) Порог слова
семьи — с обеих сторон (Т1): `ltx` (3 буквы) читается, код `h3` — нет
(голден g15, решение владельца).
"""

from __future__ import annotations

import re
import unittest

from studio.selfrag import modelnames as mn


def _написания(имя: str) -> dict[str, str]:
    """Обычные написания одного имени — так их набирают люди и площадки."""
    out = {
        "регистр": имя.upper(),
        "пробелы": re.sub(r"[-_]", " ", имя),
        "дефисы": re.sub(r"[ _]", "-", имя),
        "подчёркивания": re.sub(r"[- ]", "_", имя),
        "слэши": имя.replace("-", "/"),
        # Только целый номер версии (`2.3` -> `2-3`); `0.5b` — число
        # параметров, а не версия, и дефис в нём неоднозначен.
        "точка_в_дефис": re.sub(r"(?<=\d)\.(?=\d+(?:[-_ ]|$))", "-", имя),
        "заглавные_слова": " ".join(с.capitalize() for с in re.split(r"[-_ ]", имя)),
        "площадка": "fal-ai/" + имя,
    }
    звенья = mn.tokens(имя)
    if len(звенья) > 1 and звенья[0] in mn.ВЕНДОРЫ_В_ИМЕНИ:
        out["вендор_каталогом"] = re.sub(r"^([a-z]+)[-_ ]", r"\1/", имя)
        if mn._линейка_названа(звенья[1:]):
            out["без_вендора"] = re.sub(r"^[a-z]+[-_ ]", "", имя)
    return out


class ВсеИменаБазы(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        from studio.mcp import advice

        cls.known = sorted(advice.store_for(None).models())
        cls.groups = mn.group(cls.known)

    def test_база_не_пуста(self) -> None:
        """Р1: прогон по пустому списку прошёл бы, ничего не проверив."""
        self.assertGreater(len(self.known), 500)

    def test_любое_обычное_написание_сводится_к_тому_же_имени(self) -> None:
        провалы = []
        проверено = 0
        for имя in self.known:
            for вид, написание in _написания(имя).items():
                if написание == имя:
                    continue
                проверено += 1
                r = mn.resolve(написание, self.known, groups=self.groups)
                if имя not in r.names or r.how in mn.HOW_INFERRED:
                    провалы.append((вид, написание, имя, r.names[:2], r.how))
        self.assertGreater(проверено, 4000)
        self.assertEqual([], провалы[:20], f"{len(провалы)} из {проверено}")


class ВендорОпущен(unittest.TestCase):
    """Сосед единственный и отличается только вендором впереди."""

    БАЗА = ("minimax-hailuo-2.3", "lightricks-ltx-2", "minimax-speech-02-hd", "minimax-h3-max")

    def test_названная_линейка_читается_как_имя_базы(self) -> None:
        for спрошено, ждём in (
            ("Hailuo 2.3", "minimax-hailuo-2.3"),
            ("minimax/hailuo-2.3", "minimax-hailuo-2.3"),
            ("speech-02-hd", "minimax-speech-02-hd"),
            ("ltx-2", "lightricks-ltx-2"),
        ):
            r = mn.resolve(спрошено, self.БАЗА)
            self.assertEqual("pass", r.outcome, спрошено)
            self.assertEqual([ждём], list(r.names), спрошено)
            self.assertNotIn(r.how, mn.HOW_INFERRED, спрошено)

    def test_прочтение_названо_в_ноте(self) -> None:
        """Е2: «прочитано как X» — вслух, а не только в поле `how`."""
        r = mn.resolve("ltx-2", self.БАЗА)
        self.assertEqual("vendor_dropped", r.how)
        self.assertIn("'lightricks-ltx-2'", r.note)
        self.assertIn("прочитано как имя базы", r.note)

    def test_код_версии_остаётся_подсказкой(self) -> None:
        """Голден g15: `h3-max` — подсказка, а не факт."""
        r = mn.resolve("h3-max", self.БАЗА)
        self.assertEqual("unique_neighbour", r.how)

    def test_порог_слова_семьи_снизу(self) -> None:
        """Т1: двухбуквенное слово — код, не линейка (мутант «порог 2» краснеет)."""
        r = mn.resolve("ab-22", ("minimax-ab-22",))
        self.assertEqual("unique_neighbour", r.how)

    def test_порог_слова_семьи_сверху(self) -> None:
        """Т1: трёхбуквенное слово — линейка (мутант «порог 4» краснеет)."""
        r = mn.resolve("abc-2", ("minimax-abc-2",))
        self.assertEqual("vendor_dropped", r.how)

    def test_без_версии_не_читается(self) -> None:
        """И5: имя без номера версии линейку не называет — подсказка."""
        r = mn.resolve("hailuo", ("minimax-hailuo",))
        self.assertEqual("unique_neighbour", r.how)

    def test_два_соседа_не_угадываются(self) -> None:
        r = mn.resolve("ltx-2", ("lightricks-ltx-2", "google-ltx-2"))
        self.assertEqual("could not measure", r.outcome)

    def test_вендор_каталогом_пути_это_имя(self) -> None:
        """`minimax/h3` назвал вендора сам: это `minimax-h3`, а не код `h3`."""
        r = mn.resolve("minimax/h3", ("minimax-h3", "kling-3.0"))
        self.assertEqual(["minimax-h3"], list(r.names))
        self.assertEqual("exact", r.how)


class KlingProВариант(unittest.TestCase):
    БАЗА = ("kling-3.0", "kling-3.0-pro-i2v", "kling-3.0-pro-t2v", "kling-3.0-standard-i2v")

    def test_pro_ведёт_в_вариант_pro_а_не_в_корень(self) -> None:
        for спрошено in ("kling 3 pro", "Kling 3.0 Pro", "kling-v3-pro", "kling/3/pro"):
            r = mn.resolve(спрошено, self.БАЗА)
            self.assertEqual(["kling-3.0-pro-i2v"], list(r.names), спрошено)

    def test_свидетельство_названо_и_t2v_упомянут(self) -> None:
        r = mn.resolve("kling 3 pro", self.БАЗА)
        self.assertIn("Kling V3 (pro)", r.evidence)
        self.assertIn("kling-3.0-pro-t2v", r.evidence)

    def test_корень_остаётся_корнем(self) -> None:
        """И5: `kling 3` — сама Kling 3.0, а не её pro."""
        self.assertEqual(["kling-3.0"], list(mn.resolve("kling 3", self.БАЗА).names))


if __name__ == "__main__":
    unittest.main()
