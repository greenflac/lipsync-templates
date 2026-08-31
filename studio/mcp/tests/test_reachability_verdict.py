"""Карта достижимости: «никто не ответил» обязано отличаться от «всё разрешено».

Сети здесь нет (Т4): модульный `fetch` подменяется, и проверяется именно тот
вердикт, по которому ветвится агент.

ЗАЧЕМ ЭТОТ ФАЙЛ. Разбор 2026-08-31 нашёл, что `reachability()` возвращала
`pass` с пустым списком открытых хостов, когда egress или DNS лежали: «проверено
12, нарушений 0» — ровно та форма, против которой в репозитории стоит отдельный
тест `test_zero_checks_floor.py`. Ни один тест на её `outcome` не смотрел.
"""

from __future__ import annotations

import unittest

from lipsync.fork_identity import FAIL, PASS, UNMEASURED
from studio.mcp import fetch

HOSTS = ("example.invalid", "second.invalid", "third.invalid")


class _World:
    """Один и тот же ответ на любой запрос — три мира, три исхода.

    ВАЖНО, и на этом первая редакция теста ошиблась: `fail` от `fetch()`
    означает, что хост ОТВЕТИЛ — 404 на голом корне это доказательство
    достижимости. Мёртвая сеть даёт `не смогли` (URLError → UNMEASURED в
    самом fetch), и именно так её надо изображать здесь.
    """

    def __init__(
        self, outcome: object, note: str, status: int | None = None, denied: bool = False
    ) -> None:
        self.outcome, self.note, self.status, self.denied = outcome, note, status, denied

    def __call__(self, url: str, **_: object) -> dict:
        return {
            "outcome": self.outcome,
            "note": self.note,
            "status": self.status,
            "denied": self.denied,
        }


class _Stubbed:
    def setUp(self) -> None:
        self._real = fetch.fetch

    def tearDown(self) -> None:
        fetch.fetch = self._real  # type: ignore[assignment]


class NobodyAnsweredIsNotACleanBill(_Stubbed, unittest.TestCase):
    def test_every_host_unreachable_is_COULD_NOT_MEASURE(self) -> None:
        """Настоящий сценарий: DNS умер. Раньше здесь печаталось pass."""
        fetch.fetch = _World(UNMEASURED, "DNS lookup failed")  # type: ignore[assignment]
        out = fetch.reachability(HOSTS)
        assert out["outcome"] == UNMEASURED, out["note"]
        assert out["open"] == []
        assert out["unmeasured"] == 3
        assert "NOBODY answered" in out["note"]

    def test_at_least_one_open_host_is_a_pass(self) -> None:
        """Негативный контроль (И5): прибор, который никогда не говорит «годно»,
        так же бесполезен, как тот, что говорит его всегда."""
        fetch.fetch = _World(PASS, "answered", status=200)  # type: ignore[assignment]
        out = fetch.reachability(HOSTS)
        assert out["outcome"] == PASS, out["note"]
        assert out["open"] == sorted(HOSTS)
        assert "NOBODY answered" not in out["note"]

    def test_a_host_refused_by_policy_is_a_violation_not_a_silence(self) -> None:
        """Третий мир: политика отказала. Это «не годно», и оно обязано
        отличаться от «не дозвонились» — иначе оба снимут одним способом."""
        fetch.fetch = _World(FAIL, "CONNECT refused by policy: 403", denied=True)  # type: ignore[assignment]
        out = fetch.reachability(HOSTS)
        assert out["outcome"] == FAIL, out["note"]
        assert out["closed"] == sorted(HOSTS)
        assert out["violations"] == 3

    def test_one_open_among_unreachable_still_passes(self) -> None:
        """Граница: одного ответившего хватает, чтобы карта что-то значила."""
        answered = {"example.invalid"}

        def mixed(url: str, **_: object) -> dict:
            host = url.split("//")[-1].split("/")[0]
            if host in answered:
                return {"outcome": PASS, "note": "answered", "status": 200, "denied": False}
            return {"outcome": UNMEASURED, "note": "timed out", "denied": False}

        fetch.fetch = mixed  # type: ignore[assignment]
        out = fetch.reachability(HOSTS)
        assert out["outcome"] == PASS, out["note"]
        assert out["open"] == ["example.invalid"]
        assert out["unmeasured"] == 2


class TheDefaultListIsWhyTheOldBranchWasDead(_Stubbed, unittest.TestCase):
    def test_an_empty_argument_falls_back_to_the_default_hosts(self) -> None:
        """Ветка `if not targets` была единственным путём к UNMEASURED и не
        бралась никогда: пустой вход подменяется списком по умолчанию."""
        fetch.fetch = _World(PASS, "answered", status=200)  # type: ignore[assignment]
        empties: list[object] = [None, (), []]
        for empty in empties:
            out = fetch.reachability(empty)  # type: ignore[arg-type]
            assert out["checked"] == len(fetch._DEFAULT_HOSTS), empty
            assert out["checked"] > 0


if __name__ == "__main__":
    unittest.main()
