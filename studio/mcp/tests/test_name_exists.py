"""Просьба к владельцу окружения не содержит доменов, которых не существует.

ВОСПРОИЗВЕДЕНО 2026-09-07 (И2), живым прогоном через прокси:

    docs-nesuschestvuet-2026.example-nope-xyz.com  denied=True
        «refused by this organisation's egress policy (Tunnel connection
         failed: 403 Forbidden)»
    example.com                                   denied=True
        ровно та же строка

То есть отказ прокси НЕ ОТЛИЧАЕТ «закрыт политикой» от «не существует», а
журнал отказов — это и есть документ, по которому человек идёт открывать
доступ. Просить открыть несуществующий домен значит тратить чужое время и
обесценивать остальную просьбу.

Различает DNS: ИЗМЕРЕНО 2026-09-07, 0.01–0.03 с на имя, обе стороны сходятся.
Это НЕ обход Ц3: с закрытого хоста ничего не скачивается, спрашивается только
существование имени.

Т4: getaddrinfo здесь подменён — сеть в тестах не открывается.
"""

from __future__ import annotations

import socket
import unittest
from unittest import mock

from studio.mcp import fetch


def _временный():
    import tempfile
    from pathlib import Path

    return Path(tempfile.mkdtemp()) / "WHITELIST_REQUEST.txt"


#: Литералы (Т2). Слева — что подсунут резолверу, справа — чем он ответит.
ЕСТЬ = "docs.bfl.ai"
НЕТ = "docs-nesuschestvuet-2026.example-nope-xyz.com"


class ТриИсходаРезолвера(unittest.TestCase):
    def test_имя_есть(self) -> None:
        with mock.patch("socket.getaddrinfo", return_value=[("x",)]):
            self.assertIs(True, fetch.имя_существует(ЕСТЬ))

    def test_имени_нет(self) -> None:
        ошибка = socket.gaierror(socket.EAI_NONAME, "Name or service not known")
        with mock.patch("socket.getaddrinfo", side_effect=ошибка):
            self.assertIs(False, fetch.имя_существует(НЕТ))

    def test_резолвер_не_ответил_это_третий_исход(self) -> None:
        """Р1: своя авария не превращается в «хоста нет».

        ФИКСТУРА ВЗЯТА С НАСТОЯЩЕГО КРАЯ (Т3), И ПЕРВАЯ БЫЛА НЕ ОТТУДА.
        Приёмка 2026-09-07: тест проверял третий исход через `TimeoutError`,
        которого `getaddrinfo` при отказе резолвера НЕ БРОСАЕТ — он бросает
        тот же `gaierror`, но с кодом `EAI_AGAIN`. Из-за этого сторож молчал,
        пока прибор объявлял «имени нет» на любой аварии DNS, и просьба к
        владельцу вычёркивала все 49 хостов, печатая «нечего просить».
        """
        занят = socket.gaierror(socket.EAI_AGAIN, "Temporary failure in name resolution")
        with mock.patch("socket.getaddrinfo", side_effect=занят):
            self.assertIsNone(fetch.имя_существует(ЕСТЬ), "EAI_AGAIN — это не «имени нет»")
        with mock.patch("socket.getaddrinfo", side_effect=OSError("network unreachable")):
            self.assertIsNone(fetch.имя_существует(ЕСТЬ))
        with mock.patch("socket.getaddrinfo", side_effect=TimeoutError("resolver")):
            self.assertIsNone(fetch.имя_существует(ЕСТЬ))

    def test_пустое_имя_не_вопрос_к_dns(self) -> None:
        self.assertIsNone(fetch.имя_существует(""))


class ПросьбаОтделяетНесуществующее(unittest.TestCase):
    """Решение принимается в `scripts/allowlist_request.py` — единственном
    месте, которое и так ходит в сеть (Е1, Т4)."""

    def _просьба(self, resolves: object) -> tuple[list[str], str]:
        from scripts import allowlist_request

        заявка = {
            "hosts": [
                {"host": НЕТ, "why_wanted": "нужен предел модели"},
                {"host": ЕСТЬ, "why_wanted": "нужен предел модели"},
            ],
            "also_refused": [],
            "granted": [],
            "withdrawn": [],
        }
        карта = {НЕТ: resolves, ЕСТЬ: True}
        with (
            mock.patch.object(allowlist_request.fetch, "wanted", return_value=заявка),
            mock.patch.object(
                allowlist_request.fetch,
                "имя_существует",
                side_effect=lambda h: карта.get(h),
            ),
            mock.patch.object(
                allowlist_request.fetch,
                "reachability",
                return_value={"open": [], "closed": []},
            ),
            mock.patch.object(allowlist_request, "OUT_PATH", _временный()),
            mock.patch.object(allowlist_request.sys, "argv", ["x", "--render"]),
        ):
            allowlist_request.main()
            документ = allowlist_request.OUT_PATH.read_text(encoding="utf-8")
        просят = [и for и in (ЕСТЬ, НЕТ) if f"`{и}`" in документ or f"\n{и}\n" in документ]
        return просят, документ

    def test_несуществующее_имя_в_документ_не_попадает(self) -> None:
        просят, документ = self._просьба(False)
        self.assertNotIn(НЕТ, документ.split("## The list, to paste")[1][:400])
        self.assertIn(ЕСТЬ, документ)
        self.assertIn("do not resolve in DNS", документ)

    def test_неизвестность_остаётся_в_просьбе(self) -> None:
        """Вторая сторона (И5): вынимается только явное «имени нет».

        Резолвер, не ответивший из-за нашей аварии, не должен вынимать из
        просьбы доступ, который вправду нужен.
        """
        _, документ = self._просьба(None)
        блок = документ.split("## The list, to paste")[1][:400]
        self.assertIn(НЕТ.split(".", 1)[1], блок)
        self.assertNotIn("do not resolve in DNS", документ)
