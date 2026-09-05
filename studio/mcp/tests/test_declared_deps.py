"""Необъявленная зависимость: ловится ли, и не ловится ли лишнего.

ЗАЧЕМ. `imageio-ffmpeg` использовался четырьмя модулями и не был объявлен
нигде. Локально пакет стоял, поэтому и гейт, и зеркало CI были зелёными, а
настоящий CI упал на первом же тесте, которому пакет понадобился.

Фикстуры — исходники строками (Т2), диск и сеть не трогаются (Т4).
"""

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

_SPEC = importlib.util.spec_from_file_location(
    "check_declared_deps",
    Path(__file__).resolve().parents[3] / "scripts" / "check_declared_deps.py",
)
assert _SPEC and _SPEC.loader
deps = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(deps)

REQS = "numpy==2.4.6\npillow==12.3.0\n# комментарий\nimageio-ffmpeg==0.6.0\n"


class AnUnguardedImportMustBeDeclared(unittest.TestCase):
    def test_a_top_level_import_of_an_undeclared_package_is_caught(self) -> None:
        got = deps.undeclared({"m.py": "import nowhere_declared\n"}, REQS)
        assert got == {"nowhere-declared": ["m.py"]}, got

    def test_THE_REAL_MISTAKE_would_have_been_caught(self) -> None:
        """Ровно то, что я написал 2026-08-31: импорт внутри функции, без
        `try`. Локально прошло, CI упал."""
        source = "def make():\n    import imageio_ffmpeg\n    return imageio_ffmpeg\n"
        assert deps.undeclared({"t.py": source}, "numpy==2.4.6\n") == {"imageio-ffmpeg": ["t.py"]}

    def test_a_declared_package_is_NOT_caught(self) -> None:
        """Негативный контроль (И5): проверка, которая ругается на всё, будет
        отключена в первый же день."""
        assert deps.undeclared({"m.py": "import numpy\n"}, REQS) == {}

    def test_the_import_name_is_mapped_to_the_package_name(self) -> None:
        """`PIL` ставится как `pillow`. Угадывать по подчёркиваниям значит
        однажды угадать неверно и промолчать."""
        assert deps.undeclared({"m.py": "from PIL import Image\n"}, REQS) == {}


class AGuardedImportIsOptionalByDesign(unittest.TestCase):
    def test_an_import_inside_try_except_is_NOT_required(self) -> None:
        """Так устроены torch, sentence-transformers и pyarrow: отсутствие
        пакета превращается в честное «не смогли», и объявлять его не нужно."""
        source = "def probe():\n    try:\n        import torch\n    except Exception:\n        return None\n"
        assert deps.undeclared({"m.py": source}, REQS) == {}

    def test_the_SAME_package_unguarded_elsewhere_is_still_caught(self) -> None:
        """Граница проходит по защите, а не по имени пакета: один защищённый
        импорт не выдаёт индульгенцию всем остальным."""
        guarded = "def probe():\n    try:\n        import torch\n    except Exception:\n        return None\n"
        naked = "import torch\n"
        got = deps.undeclared({"safe.py": guarded, "risky.py": naked}, REQS)
        assert got == {"torch": ["risky.py"]}, got


class OurOwnModulesAreNotPackages(unittest.TestCase):
    def test_a_sibling_script_is_not_reported_as_a_dependency(self) -> None:
        """`read_sources` из scripts/ читался как пакет с PyPI — правдоподобно
        и неверно. Своё определяется по файлам, а не по догадке."""
        assert "read-sources" not in deps.undeclared({"m.py": "import read_sources\n"}, REQS)

    def test_the_standard_library_is_not_reported(self) -> None:
        assert deps.undeclared({"m.py": "import json\nimport pathlib\n"}, REQS) == {}


class TheRequirementsParserReadsWhatIsThere(unittest.TestCase):
    def test_versions_and_comments_are_stripped(self) -> None:
        assert deps.declared("numpy==2.4.6  # пин\n\nruff>=0.1\n") == {"numpy", "ruff"}

    def test_underscores_and_case_do_not_matter(self) -> None:
        """`imageio_ffmpeg` в импорте и `imageio-ffmpeg` в requirements — один
        пакет. Без этого проверка ругалась бы на объявленное."""
        assert "imageio-ffmpeg" in deps.declared("Imageio_FFmpeg==0.6.0\n")


if __name__ == "__main__":
    unittest.main()
