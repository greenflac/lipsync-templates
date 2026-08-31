"""Одна модель на HuggingFace: спека, лицензия, принятость, опыт практиков.

ЗАЧЕМ СКРИПТ, А НЕ РУКИ

Первую модель (MiniMax H3) я разобрал вручную и потратил на это десяток
запросов. Вторая обошлась бы так же, тридцатая не случилась бы никогда. Канал,
который работает только пока им занимается человек, — это не канал.

ЧТО БЕРЁТСЯ И ПОЧЕМУ ИМЕННО ЭТО

  * `api/models/{id}` — лицензия, скачивания, лайки, теги, дата. Принятость
    здесь ЧИСЛО, а не впечатление: 5 362 365 скачиваний у MiniMax-H3 говорят
    о промышленном стандарте больше, чем любой обзор.
  * `raw/main/README.md` — карточка. У вендорских аккаунтов это спека: длина
    ролика, fps, разрешение, архитектура.
  * `raw/main/LICENSE` — читается ДО встраивания (правило Ц5) и отдельно от
    поля `license`, потому что `license: other` не говорит ничего, а внутри
    может стоять территориальное исключение, как у MiniMax H3.
  * `api/models/{id}/discussions` — опыт практиков. Здесь лежит то, чего нет
    ни в одной спеке: «персонажи почти не моргают», «мелкое лицо разваливается
    и 2K это не лечит». Это APPLICABILITY, и она приходит только отсюда.

ТИРЫ РЕШАЕТ URL, А НЕ ЭТОТ СКРИПТ

Карточка вендорского аккаунта — `vendor`, обсуждение — `blog`, и решает это
`source_hosts.classify`, а не аргумент. Скрипт лишь предъявляет ссылку.
Поэтому же он НЕ пишет факты сам: он готовит находки, а запись идёт через
`advice.record`, который сверяет тир с URL и умеет отказать.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

API = "https://huggingface.co/api/models/"
WEB = "https://huggingface.co/"

#: ВЫБРАНО: столько обсуждений просматривается на модель. Больше — и разбор
#: одной модели уезжает в минуты; меньше — и тонут редкие, но ценные отчёты,
#: которые лежат не на первой странице.
DISCUSSIONS_SCANNED = 100

#: Сколько файлов лицензий читать на модель. У LTX-Video их четыре: один на
#: репозиторий и по одному на версию веса, и условия у них могут не совпадать.
LICENCES_READ = 6

#: Имя файла лицензии НАХОДИТСЯ по дереву репозитория, а не угадывается.
#: Список имён был первой редакцией и провалился на первой же живой модели:
#: у MiniMax файл зовётся `LICENSE`, а у Lightricks —
#: `LTX-Video-Open-Weights-License-0.X.txt`, и никакой список этого не покроет.
#: При `license: other` непрочитанный файл означает, что условий мы НЕ ЗНАЕМ, —
#: а правило Ц5 требует прочитать их ДО встраивания, и поле в карточке
#: лицензией не является.
LICENSE_IN_NAME = re.compile(r"licen[cs]e", re.I)

#: Куда не заглядывать в поисках лицензии: лицензия ЗАВИСИМОСТИ — не лицензия
#: модели, и спутать их значит принять чужие условия за свои.
LICENSE_SKIP = re.compile(r"(^|/)(node_modules|vendor|third[_-]?party|examples?)/", re.I)

#: Слова, по которым тред похож на ОТЧЁТ О ДЕФЕКТЕ, а не на просьбу, вакансию
#: или вопрос о лицензии. Список смешанный нарочно: половина полезных тредов у
#: китайских моделей написана по-китайски, и англоязычный фильтр их теряет.
#: ИЗМЕРЕНО на MiniMax-H3: из 98 тредов фильтр оставил 4, и все четыре были по
#: делу — моргание, разваливающееся лицо, VRAM, искажения.
TROUBLE = re.compile(
    r"(problem|issue|bug|fail|error|slow|vram|oom|artifact|flicker|blink|distort"
    r"|quality|crash|不|无法|问题|瑕疵|眨眼)",
    re.I,
)


def _get(url: str, cap: int = 400_000) -> tuple[str, bytes]:
    """Один запрос. Отказ — это состояние, а не исключение."""
    request = urllib.request.Request(url, headers={"User-Agent": "lipsync-studio/ingest"})
    try:
        with urllib.request.urlopen(request, timeout=25) as response:
            return "ok", response.read(cap)
    except urllib.error.HTTPError as error:
        return f"HTTP {error.code}", b""
    except Exception as error:  # noqa: BLE001 — состояние канала, не наша ошибка
        return type(error).__name__, b""


def license_flags(text: str) -> list[str]:
    """Что в тексте лицензии меняет применимость. Пусто — ничего не нашли.

    Ищутся ровно те формы, которые уже кусали: территориальное исключение,
    порог выручки, запрет учить на выходах, некоммерческая оговорка. Правило
    Ц5 требует прочитать лицензию ДО встраивания, а не после.
    """
    found: list[str] = []
    low = text.lower()
    if "excluded territor" in low or "applicable territory" in low:
        found.append("территориальное ограничение: права даны не везде")
    if "non-commercial" in low or "noncommercial" in low:
        found.append("некоммерческая оговорка")
    if "research only" in low or "research purposes only" in low:
        found.append("только для исследований")
    if re.search(r"improve any other artificial intelligence model", low):
        found.append("запрет учить другие модели на выходах")
    money = re.search(r"(\d[\d,\. ]{5,})\s*(?:us )?dollars", low)
    if money:
        found.append(f"порог выручки: {money.group(1).strip()} USD")
    return found


def troubles(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Треды, похожие на отчёт о дефекте. Просьбы и вакансии сюда не идут."""
    rows = []
    for item in (payload.get("discussions") or [])[:DISCUSSIONS_SCANNED]:
        title = str(item.get("title") or "")
        if TROUBLE.search(title):
            rows.append({"num": item.get("num"), "title": title, "status": item.get("status")})
    return rows


def license_paths(model_id: str, get: Callable[[str], tuple[str, bytes]] = _get) -> list[str]:
    """Файлы репозитория, похожие на лицензию, короткое имя первым.

    Короткое первым потому, что `LICENSE` — это лицензия модели, а
    `ltx-video-2b-v0.9.1.license.txt` — лицензия одного веса из многих.
    """
    state, body = get(f"{API}{model_id}/tree/main")
    if state != "ok":
        return []
    try:
        rows = json.loads(body)
    except json.JSONDecodeError:
        return []
    paths = [
        str(row.get("path") or "")
        for row in rows
        if isinstance(row, dict)
        and LICENSE_IN_NAME.search(str(row.get("path") or ""))
        and not LICENSE_SKIP.search(str(row.get("path") or ""))
    ]
    return sorted(set(paths), key=lambda p: (len(p), p))


def survey(model_id: str, get: Callable[[str], tuple[str, bytes]] = _get) -> dict[str, Any]:
    """Всё, что HuggingFace знает об одной модели. Три исхода, как везде."""
    state, body = get(API + model_id)
    if state != "ok":
        return {"model_id": model_id, "outcome": "не смогли", "note": f"карточка: {state}"}
    meta = json.loads(body)
    card_data = meta.get("cardData") or {}

    readme_state, readme = get(f"{WEB}{model_id}/raw/main/README.md")
    licences: list[dict[str, Any]] = []
    for name in license_paths(model_id, get)[:LICENCES_READ]:
        state_here, body_here = get(f"{WEB}{model_id}/raw/main/{name}")
        if state_here == "ok" and body_here.strip():
            licences.append(
                {
                    "file": name,
                    "flags": license_flags(body_here.decode("utf-8", "replace")),
                    "chars": len(body_here),
                }
            )
    talk_state, talk = get(f"{API}{model_id}/discussions")

    found = troubles(json.loads(talk)) if talk_state == "ok" else []
    return {
        "model_id": model_id,
        "outcome": "годно",
        "author": meta.get("author", ""),
        "created": str(meta.get("createdAt", ""))[:10],
        "downloads": meta.get("downloads"),
        "likes": meta.get("likes"),
        "gated": meta.get("gated"),
        "pipeline": meta.get("pipeline_tag", ""),
        "license": card_data.get("license", ""),
        "license_name": card_data.get("license_name", ""),
        "licences": licences,
        "license_read": bool(licences),
        "card_read": readme_state == "ok",
        "card_chars": len(readme),
        "discussions_total": (json.loads(talk).get("count") if talk_state == "ok" else None),
        "troubles": found,
        "card_url": f"{WEB}{model_id}",
        "license_url": f"{WEB}{model_id}/tree/main",
    }


def licences_disagree(licences: list[dict[str, Any]]) -> bool:
    """Разные файлы лицензий дают разные оговорки — значит, права зависят от веса.

    ИЗМЕРЕНО на Lightricks/LTX-Video 2026-08-31: четыре файла, и два из них
    («2b-v0.9», «2b-v0.9.1») содержат оговорку «только для исследований», а
    два других — нет. Прочитавший ОДИН файл получит неверный ответ в любую из
    двух сторон, и это ровно тот случай, ради которого правило Ц5 требует
    читать лицензию, а не поле карточки.
    """
    наборы = {frozenset(lic["flags"]) for lic in licences}
    return len(наборы) > 1


def report(rows: list[dict[str, Any]]) -> int:
    """Печать числами и три исхода (правила Р1, Р2, Е3)."""
    done = [r for r in rows if r.get("outcome") == "годно"]
    for row in rows:
        if row.get("outcome") != "годно":
            print(f"  НЕ СМОГЛИ  {row['model_id']}: {row.get('note', '')}")
            continue
        print(f"\n=== {row['model_id']}  ({row['author']}, с {row['created']})")
        print(f"    принятость: скачиваний {row['downloads']}, лайков {row['likes']}")
        лиц = row["license_name"] or row["license"] or "не указана"
        print(f"    лицензия:   {лиц}  (файлов прочитано {len(row['licences'])})")
        if not row["license_read"] and str(row["license"]).lower() in ("other", "", "unknown"):
            print(
                "       ВНИМАНИЕ: поле говорит 'other', а текста нет —"
                " до встраивания читать нельзя (Ц5)"
            )
        for lic in row["licences"]:
            метки = "; ".join(lic["flags"]) or "особых оговорок не нашли"
            print(f"       {lic['file']} ({lic['chars']} симв.): {метки}")
        if licences_disagree(row["licences"]):
            print(
                "       ВНИМАНИЕ: файлы лицензий РАСХОДЯТСЯ — права зависят от того,"
                " какой вес вы грузите, и один файл ответа не даёт (Ц5)"
            )
        print(f"    карточка:   {row['card_chars']} символов, задача {row['pipeline'] or '—'}")
        print(
            f"    обсуждений: {row['discussions_total']}, похожих на отчёт о дефекте {len(row['troubles'])}"
        )
        for t in row["troubles"][:6]:
            print(f"       #{t['num']} [{t['status']}] {t['title'][:80]}")
    print(f"\nпроверено {len(rows)}, разобрано {len(done)}, не смогли {len(rows) - len(done)}")
    if not rows:
        print("исход: не смогли — не назвали ни одной модели")
        return 2
    if not done:
        print("исход: не смогли — ни одна карточка не открылась")
        return 2
    if len(done) < len(rows):
        print(f"исход: не смогли полностью — {len(done)} из {len(rows)}")
        return 2
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("models", nargs="+", help="id вида MiniMaxAI/MiniMax-H3")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    rows = [survey(m) for m in args.models]
    if args.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0 if all(r.get("outcome") == "годно" for r in rows) else 2
    return report(rows)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
