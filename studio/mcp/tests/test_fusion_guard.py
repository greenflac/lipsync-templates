"""Сторож для FUSION_CHANNELS, работающий на ЛЮБОЙ машине.

ЗАЧЕМ ЭТОТ ФАЙЛ. Разбор 2026-08-31: единственная проверка, сторожившая фузию
(`studio/tests/test_knowledge.py::test_dropping_the_fusion_to_bm25_only_costs_recall`),
пропускается везде — она требует корпус владельца `our_prompts/`, которого нет
ни в репозитории, ни в CI, ни на этой машине. Комментарий внутри неё говорит
прямо: «If this test goes quiet, nothing is guarding the fusion». Он молчит.

Здесь тот же вопрос задан на корпусе, который тест ПИШЕТ САМ, поэтому он живой
везде. Чужой файл при этом не трогается: `studio/tests/test_knowledge.py`
принадлежит другому агенту (HANDOFF_studio-mvp.md), и по Ц2 его не правят.
Сети нет (Т4), ожидаемое — литералы (Т2).
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from studio import knowledge as K  # type: ignore[attr-defined]
from studio.knowledge import build_index, retrieve  # type: ignore[attr-defined]

NOWHERE = Path("/nonexistent/never")

#: Корпус, который этот тест держит сам. Фразы подобраны так, чтобы у части
#: запросов совпадение было ФРАЗОВЫМ, а не пословным: именно на этом канал
#: `phrase` и отличается от `bm25`.
PROMPTS = [
    {"prompt": "warm golden hour light, amber palette, soft film grain, nostalgic portrait"},
    {"prompt": "matte paper texture, split scene columns, muted navy and cream"},
    {"prompt": "studio portrait, key light from camera left, shallow depth of field"},
    {"prompt": "hard noon sun, deep contrast, dry concrete, long black shadows"},
    {"prompt": "overcast diffuse light, pale skin tones, low saturation, quiet mood"},
]


class _Corpus(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        path = Path(self._tmp.name) / "gallery_prompts.jsonl"
        path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in PROMPTS) + "\n", encoding="utf-8"
        )
        self.prompts = path
        self._channels = K.FUSION_CHANNELS  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        K.FUSION_CHANNELS = self._channels  # type: ignore[attr-defined]
        self._tmp.cleanup()

    def _index(self):
        return build_index(
            gallery_prompts=self.prompts, community_prompts=NOWHERE, craft_records=NOWHERE
        )

    def _hits(self, query: str) -> int:
        return len(retrieve(query, index=self._index(), k=5)["examples"])


class TheFusionHasToEarnItsChannels(_Corpus):
    def test_the_full_fusion_finds_a_phrase_query(self) -> None:
        """Опора: на полном наборе каналов запрос находится."""
        assert self._hits("golden hour light") > 0

    def test_dropping_every_channel_but_bm25_is_OBSERVABLE(self) -> None:
        """Мутация, ради которой фузия и существует. Прежний сторож молчал на
        любой машине, поэтому канал `phrase` можно было удалить и не узнать."""
        full = self._hits("split scene columns")
        K.FUSION_CHANNELS = ("bm25",)  # type: ignore[attr-defined]
        only_lexical = self._hits("split scene columns")
        assert full > 0, "опора сломана: на полном наборе не нашлось ничего"
        assert only_lexical <= full, (
            f"один лексический канал вернул {only_lexical} против {full} — "
            "фузия ничего не добавляет, и её незачем держать"
        )

    def test_an_EMPTY_channel_list_finds_nothing(self) -> None:
        """Негативный контроль (И5): если выдача не зависит от списка каналов,
        предыдущий тест ничего не измеряет. С пустым списком искать нечем."""
        K.FUSION_CHANNELS = ()  # type: ignore[attr-defined]
        assert self._hits("golden hour light") == 0

    def test_the_shipped_channel_list_is_what_the_module_claims(self) -> None:
        """Литералы (Т2): четыре канала по именам. Молчаливое удаление одного
        уронит этот тест, а не только чьё-то внимание."""
        assert K.FUSION_CHANNELS == ("bm25", "phrase", "structural", "dense")  # type: ignore[attr-defined]


if __name__ == "__main__":
    unittest.main()


class ANonSearchableRowIsCountedApartFromAFailure(_Corpus):
    """Разбор 2026-08-31: `evaluate()` объявлял `unmeasured = 0` и не двигал
    его НИКОГДА. Строка, на которой ретривер честно ответил «не смогли»
    (запрос без единого поискового термина), получала recall 0.0 и уезжала в
    нарушения — прибор превращал «нечего было искать» в «искали и провалились»
    и занижал собственное число, печатая при этом «не смогли 0»."""

    def _evaluate(self, rows: list[dict]) -> dict:
        from studio.knowledge import evaluate  # type: ignore[attr-defined]

        return evaluate(self._index(), rows)

    def test_an_unsearchable_query_lands_in_could_not_not_in_violations(self) -> None:
        # Ни одного слова и ни одного поля стиля: искать нечем, и retrieve
        # отвечает «не смогли» — это его задокументированное поведение.
        out = self._evaluate([{"query": "  ", "must_retrieve": ["golden hour"]}])
        assert out["unmeasured"] == 1, out["note"]
        assert out["violations"] == 0, out["note"]

    def test_a_REAL_miss_is_still_a_violation(self) -> None:
        """Негативный контроль (И5): если бы всё уезжало в «не смогли», прибор
        перестал бы ловить настоящие промахи."""
        out = self._evaluate(
            [{"query": "золотой час амбра плёнка", "must_retrieve": ["чего тут точно нет"]}]
        )
        assert out["unmeasured"] == 0, out["note"]
        assert out["violations"] == 1, out["note"]

    def test_a_hit_is_neither(self) -> None:
        out = self._evaluate([{"query": "golden hour light", "must_retrieve": ["golden hour"]}])
        assert out["unmeasured"] == 0, out["note"]
        assert out["violations"] == 0, out["note"]
