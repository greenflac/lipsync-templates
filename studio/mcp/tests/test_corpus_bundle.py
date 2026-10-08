"""Связка корпуса: что едет, что не едет никогда, и виден ли разъезд.

Фикстуры — литералы (Т2). На диск ходит только tmp-каталог теста, в сеть —
никогда (Т4).
"""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

_SPEC = importlib.util.spec_from_file_location(
    "corpus_bundle", Path(__file__).resolve().parents[3] / "scripts" / "corpus_bundle.py"
)
assert _SPEC and _SPEC.loader
bundle = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(bundle)


class MediaNeverTravels(unittest.TestCase):
    """Собрать чужие ролики для замера и раздать их — разные вещи. Список
    CARRIED — намерение; предохранитель NEVER существует на случай, когда
    намерение однажды разойдётся с тем, что дописали."""

    def test_a_video_named_in_the_list_is_still_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "clip.mp4").write_bytes(b"not-a-real-clip")
            carried, missing, refused = bundle.plan(("clip.mp4",), root)
            assert refused == ["clip.mp4"]
            assert carried == []

    def test_every_forbidden_extension_is_refused(self) -> None:
        names = tuple(f"x{ext}" for ext in (".mp4", ".jpg", ".png", ".parquet"))
        with tempfile.TemporaryDirectory() as tmp:
            _, _, refused = bundle.plan(names, Path(tmp))
            assert sorted(refused) == sorted(names)

    def test_a_TEXT_file_is_NOT_refused(self) -> None:
        """Негативный контроль (И5). Предохранитель, отвергающий всё, — это не
        предохранитель, а закрытая дверь."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "corpus.jsonl").write_text('{"a":1}\n', encoding="utf-8")
            carried, missing, refused = bundle.plan(("corpus.jsonl",), root)
            assert carried == ["corpus.jsonl"]
            assert refused == []


class AMissingFileIsNotAViolation(unittest.TestCase):
    def test_a_file_absent_from_disk_lands_in_could_not(self) -> None:
        """Р1: «его нет» и «он запрещён» — разные исходы. Свернуть их значило бы
        поднять тревогу там, где корпус просто ещё не собран."""
        with tempfile.TemporaryDirectory() as tmp:
            carried, missing, refused = bundle.plan(("нет-такого.jsonl",), Path(tmp))
            assert missing == ["нет-такого.jsonl"]
            assert refused == []
            assert carried == []


class DriftHasToBeVisible(unittest.TestCase):
    def _bundle(self, tmp: str, text: str) -> Path:
        out = Path(tmp) / "bundle"
        out.mkdir()
        (out / "corpus.jsonl").write_text(text, encoding="utf-8")
        manifest = {"corpus.jsonl": dict(bundle.digest(out / "corpus.jsonl"), source="x")}
        (out / bundle.MANIFEST).write_text(json.dumps(manifest), encoding="utf-8")
        return out

    def test_a_changed_file_is_reported_with_both_line_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = self._bundle(tmp, '{"a":1}\n')
            (out / "corpus.jsonl").write_text('{"a":1}\n{"b":2}\n', encoding="utf-8")
            got = bundle.verify(out)
            assert got["outcome"] == FAIL, got["note"]
            assert got["differ"] == ["corpus.jsonl: 1 строк → 2"]

    def test_an_unchanged_file_is_NOT_reported(self) -> None:
        """Негативный контроль: сверка, которая всегда краснеет, бесполезна."""
        with tempfile.TemporaryDirectory() as tmp:
            got = bundle.verify(self._bundle(tmp, '{"a":1}\n'))
            assert got["outcome"] == PASS, got["note"]
            assert got["differ"] == []
            assert got["checked"] == 1

    def test_a_file_in_the_manifest_but_not_on_disk_is_COULD_NOT_not_drift(self) -> None:
        """Отсутствующий файл не «разъехался» — его не с чем сравнивать."""
        with tempfile.TemporaryDirectory() as tmp:
            out = self._bundle(tmp, '{"a":1}\n')
            (out / "corpus.jsonl").unlink()
            got = bundle.verify(out)
            assert got["absent"] == ["corpus.jsonl"]
            assert got["differ"] == []
            assert got["outcome"] == UNMEASURED

    def test_no_manifest_at_all_is_could_not_measure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            assert bundle.verify(Path(tmp))["outcome"] == UNMEASURED


class CompareIsWhereTheDecisionLives(unittest.TestCase):
    """Т5: развилка вынесена из точки входа, поэтому её видно отсюда."""

    def test_same_hash_different_line_count_is_impossible_and_not_reported(self) -> None:
        manifest = {"a": {"sha256": "abc", "lines": 1}}
        assert bundle.compare(manifest, {"a": {"sha256": "abc", "lines": 1}}) == ([], [])

    def test_different_hash_is_reported(self) -> None:
        manifest = {"a": {"sha256": "abc", "lines": 1}}
        differ, absent = bundle.compare(manifest, {"a": {"sha256": "zzz", "lines": 9}})
        assert differ == ["a: 1 строк → 9"]
        assert absent == []


if __name__ == "__main__":
    unittest.main()
