"""Перепрощупать хосты, чей отказ протух. Отказ — не свойство, а измерение.

ЗАЧЕМ ЭТОТ СКРИПТ

`denied_hosts.jsonl` — журнал состояний, и он умеет записать, что хост
открылся: `fetch.note_open` пишет такую строку при первом же удачном запросе.
Но удачного запроса не случается никогда: код, увидев в карте `refused`,
обходит хост стороной и больше его не спрашивает. Отказ, записанный один раз,
живёт вечно, а политика доступа тем временем меняется без нашего ведома.

ИЗМЕРЕНО 2026-09-02, прощупаны ВСЕ 214 хостов с последним статусом `refused`:

    открылись        18   (8.4%)
    закрыты          195
    не смогли         1   (docs.hedra.com: tunnel 502, это не отказ политики)

Среди открывшихся — `docs.mistral.ai`, `docs.cohere.com`,
`api-docs.deepseek.com`, `docs.bfl.ml`, `docs.anthropic.com`,
`tongyi.aliyun.com`, `developer.ideogram.ai`, `platform.kimi.ai`. Первые три
названы в шапке `routes.py` как закрытые, и ради них там написан обход через
HuggingFace. Обход работал по карте, устаревшей на шесть дней, и стоил нам
перворучных вендорских источников — тира `vendor` вместо `portal`.

ЧТО ЭТОТ СКРИПТ НЕ ДЕЛАЕТ

Он не обходит политику (правило Ц3): он спрашивает те же хосты тем же путём и
записывает ответ. Отказ остаётся отказом; меняется только его ДАТА, а
`routes.ГОРИЗОНТ_ДНЕЙ` решает, когда дата перестаёт что-либо значить.

ТРИ ИСХОДА (Р1)

    годно        прощупали хотя бы один хост, все ответы записаны
    не годно     нечитаемые строки в журнале
    не смогли    прощупать не удалось ни одного (сеть или прокси лежат)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.mcp import routes  # noqa: E402
from studio.mcp.fetch import DENIED_PATH, STATE_REFUSED, note_open  # noqa: E402

#: Подпись прокси под отказом ПОЛИТИКИ. Всё остальное — не отказ: 502 от
#: туннеля значит «шлюз лёг», и записать его отказом значит закрыть себе хост
#: чужой аварией.
ОТКАЗ_ПОЛИТИКИ = re.compile(r"tunnel connection failed:\s*(403|407)", re.I)

#: Пауза между запросами: тот же довод, что в канале HuggingFace — залп с
#: одного адреса есть форма, по которой банят.
ПАУЗА = 0.2

#: Сколько ждать ответа. ВЫБРАНО 15 с: медленная документация успевает, а
#: заход по двум сотням хостов не превращается в час.
ЖДАТЬ = 15

АГЕНТ = "lipsync-studio-knowledge/1.0 (+https://github.com/greenflac/lipsync-templates)"


def строки(path: Path) -> tuple[list[dict], int]:
    """Строки журнала и число НЕЧИТАЕМЫХ. Второе — не ноль по умолчанию (Р2)."""
    прочитано: list[dict] = []
    битых = 0
    if not path.is_file():
        return прочитано, битых
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            прочитано.append(json.loads(line))
        except ValueError:
            битых += 1
    return прочитано, битых


def протухшие(path: Path, *, today: str = "") -> list[tuple[str, str]]:
    """(хост, url) для тех, чей ПОСЛЕДНИЙ статус — отказ старше горизонта."""
    прочитано, _ = строки(path)
    последнее: dict[str, dict] = {}
    for row in прочитано:
        host = str(row.get("host") or "")
        if host:
            последнее[host] = row
    итог = []
    for host, row in последнее.items():
        if str(row.get("state", STATE_REFUSED)) != STATE_REFUSED:
            continue
        когда = str(row.get("first_seen") or row.get("date") or "")
        if routes.просрочен(когда, today=today):
            итог.append((host, str(row.get("url") or f"https://{host}/")))
    return sorted(итог)


def прощупать(url: str) -> tuple[str, str]:
    """`open` / `refused` / `не смогли` — и третье не сворачивается в второе."""
    request = urllib.request.Request(url, headers={"User-Agent": АГЕНТ})
    try:
        with urllib.request.urlopen(request, timeout=ЖДАТЬ) as response:
            return "open", f"HTTP {response.status}"
    except urllib.error.HTTPError as error:
        # Ответил 404 или 401 — значит хост ДОСТУПЕН, а путь другой. Это
        # ровно то, что здесь измеряется.
        return "open", f"HTTP {error.code}"
    except Exception as error:  # noqa: BLE001 — состояние сети, не наша ошибка
        текст = str(error)
        if ОТКАЗ_ПОЛИТИКИ.search(текст):
            return "refused", текст[:120]
        return "не смогли", f"{type(error).__name__}: {текст[:100]}"


def подтвердить_отказ(host: str, url: str, причина: str, today: str) -> None:
    """Записать «проверено сегодня, по-прежнему закрыт».

    `note_denial` такую строку не пишет намеренно: для него повтор той же
    жалобы — шум в заявке владельцу. Но без даты подтверждения отказ вечно
    остаётся протухшим и перепрощупывается каждый заход. Поэтому строка
    пишется здесь и помечена `incidental`, чтобы не раздувать заявку.
    """
    with DENIED_PATH.open("a", encoding="utf-8") as handle:
        handle.write(
            json.dumps(
                {
                    "host": host,
                    "url": url,
                    "reason": причина,
                    "why_wanted": "",
                    "incidental": True,
                    "state": STATE_REFUSED,
                    "first_seen": today,
                    "reprobed": True,
                },
                ensure_ascii=False,
            )
            + "\n"
        )


def свести(*, today: str = "", path: Path | None = None) -> dict:
    """Сколько строк журнала протухло. Без сети — это и есть режим `--check`.

    :param path: журнал, отличный от репозиторного. Нужен НЕ для удобства:
        без него у гейта нет отрицательного контроля — на живом журнале
        сегодня закрытых протухшим отказом семей нет, и проверка, которая
        никогда не краснела, неотличима от проверки, которая не умеет.
    """
    журнал = path or DENIED_PATH
    прочитано, битых = строки(журнал)
    последнее: dict[str, dict] = {}
    for row in прочитано:
        host = str(row.get("host") or "")
        if host:
            последнее[host] = row
    отказов = sum(
        1 for r in последнее.values() if str(r.get("state", STATE_REFUSED)) == STATE_REFUSED
    )
    протухло = len(протухшие(журнал, today=today))
    # Настоящая проверка: НИ ОДНО решение о маршруте не должно опираться на
    # отказ старше горизонта. Это ловит не саму формулу, а её обход в любом
    # месте цепочки — если горизонт из `reachability` уберут, здесь появятся
    # семьи, закрытые протухшей записью.
    закрытые = routes.blocked_families(path=журнал)
    на_протухшем = []
    просроченные = {h for h, _ in протухшие(журнал, today=today)}
    for семья in закрытые.get("blocked", []):
        if any(host in просроченные for host in семья["hosts"]):
            на_протухшем.append(семья["family"])
    return {
        "хостов": len(последнее),
        "отказов": отказов,
        "протухло": протухло,
        "битых строк": битых,
        "семей на протухшем отказе": на_протухшем,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="без сети: считает протухшее")
    parser.add_argument("--limit", type=int, default=0, help="сколько хостов прощупать")
    parser.add_argument("--today", default="", help="дата для проверки (тесты)")
    args = parser.parse_args()

    if args.check:
        итог = свести(today=args.today)
        print(
            f"хостов {итог['хостов']}, отказов {итог['отказов']}, "
            f"протухло {итог['протухло']}, битых строк {итог['битых строк']}"
        )
        if итог["битых строк"]:
            print(f"не годно: {итог['битых строк']} нечитаемых строк в журнале")
            return 1
        if итог["семей на протухшем отказе"]:
            print(
                "не годно: маршрут закрыт протухшим отказом — "
                + ", ".join(итог["семей на протухшем отказе"])
            )
            return 1
        print("годно: ни одна семья не закрыта отказом старше горизонта")
        return 0

    today = args.today or date.today().isoformat()
    цели = протухшие(DENIED_PATH, today=today)
    if args.limit:
        цели = цели[: args.limit]
    if not цели:
        print(f"не смогли: протухших отказов нет (горизонт {routes.ГОРИЗОНТ_ДНЕЙ} дн.)")
        return 2

    счёт = {"open": 0, "refused": 0, "не смогли": 0}
    открылись: list[str] = []
    for host, url in цели:
        состояние, почему = прощупать(url)
        счёт[состояние] += 1
        if состояние == "open":
            note_open(url)
            открылись.append(host)
        elif состояние == "refused":
            подтвердить_отказ(host, url, почему, today)
        time.sleep(ПАУЗА)

    print(
        f"прощупано {len(цели)}: открылись {счёт['open']}, "
        f"закрыты {счёт['refused']}, не смогли {счёт['не смогли']}"
    )
    if открылись:
        print("открылись: " + ", ".join(sorted(открылись)))
    if счёт["open"] + счёт["refused"] == 0:
        print("не смогли: ни один хост не ответил — это авария сети, а не карта")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
