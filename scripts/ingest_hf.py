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

from studio.selfrag.facts import FactStore  # noqa: E402

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


#: Доля не-ASCII символов, выше которой текст считается написанным не на том
#: языке, который умеет читать `license_flags`. ВЫБРАНО 0.2: английская
#: лицензия с парой символов «—» и «’» остаётся ниже, а китайская —
#: заведомо выше. Сторожится мутацией в обе стороны (правило Т1).
FOREIGN_TEXT_SHARE = 0.2

#: Правило Р1 в этом приборе: «оговорок не нашли» и «прочитать не смогли» —
#: РАЗНЫЕ исходы. Пока они печатались одинаково, китайская версия лицензии
#: IndexTTS-2 читалась как «чистая», а английская рядом несла некоммерческую
#: оговорку — и прибор объявлял это РАСХОЖДЕНИЕМ между весами, хотя это одна
#: лицензия на двух языках. Отсутствие свидетельства выдавалось за
#: свидетельство отсутствия, а сверху ещё и за ложную находку.
CANNOT_READ = "НЕ СМОГЛИ ПРОЧИТАТЬ"


#: Так выглядит НЕ файл, а указатель на него: HuggingFace хранит большие файлы
#: в git-lfs, и `raw/` отдаёт вместо содержимого три строки метаданных.
#: ПОЙМАНО на Comfy-Org/Krea-2 2026-08-31: `LICENSE.pdf` пришёл в 131 символ,
#: детектор не нашёл в них оговорок и объявил лицензию чистой — при том что за
#: указателем лежит PDF на 137 711 байт, которого мы не видели.
LFS_POINTER = "git-lfs.github.com/spec"

#: Короче этого текст лицензией не бывает — это обрывок, шапка или указатель.
#: ВЫБРАНО 400 символов: самая короткая настоящая лицензия из прочитанных
#: (MIT, ~1000 символов) вдвое длиннее, а LFS-указатель втрое короче.
LICENCE_MIN_CHARS = 400


def unreadable(text: str) -> str:
    """ПОЧЕМУ по этому тексту нельзя судить об оговорках. Пусто — можно.

    Три причины, и они разные: пусто/обрывок, указатель git-lfs вместо файла,
    чужой язык. Все три обязаны печататься как «не смогли», а не как «оговорок
    не нашли» (правило Р1) — и называть себя, а не прикрываться одной общей
    фразой: первая редакция говорила «язык не тот» про LFS-указатель, то есть
    третий исход отдавала с неверной причиной.
    """
    if LFS_POINTER in text[:200]:
        return "это указатель git-lfs, а не сам файл"
    if not text or len(text) < LICENCE_MIN_CHARS:
        return f"текст короче {LICENCE_MIN_CHARS} символов — обрывок, не лицензия"
    чужих = sum(1 for ch in text if ord(ch) > 127)
    if чужих / len(text) > FOREIGN_TEXT_SHARE:
        return "язык не тот, оговорки не проверены"
    return ""


def license_flags(text: str) -> list[str]:
    """Что в тексте лицензии меняет применимость. Пусто — ничего не нашли.

    Ищутся ровно те формы, которые уже кусали: территориальное исключение,
    порог выручки, запрет учить на выходах, некоммерческая оговорка. Правило
    Ц5 требует прочитать лицензию ДО встраивания, а не после.

    Текст не на английском возвращает НЕ пустой список, а `CANNOT_READ`:
    молчащий детектор и чистая лицензия обязаны выглядеть по-разному.
    """
    почему = unreadable(text)
    if почему:
        return [f"{CANNOT_READ}: {почему}"]
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


#: Признаки того, что тред про УСТАНОВКУ и окружение, а не про поведение
#: модели. ИЗМЕРЕНО 2026-08-31 на 49 тредах восьми моделей: 24 из них (49%) —
#: «не ставится», «не грузится», «нет CUDA», «404». Это настоящие проблемы
#: людей, но они не говорят НИЧЕГО о том, как модель себя ведёт, а именно за
#: применимостью канал и заведён. Оценка выхода поправлена с 4.0 до 3.1
#: полезной записи на модель.
#:
#: Граница правила закреплена настоящими заголовками в тесте: слово `loads` в
#: «LoRA loads without error but has zero conditioning effect» едва не увело
#: настоящий отчёт о поведении в установку.
SETUP_TROUBLE = re.compile(
    r"(install|pip\b|colab|import|module|cuda|oom|vram|memory|download|404"
    r"|not found|config\.json|failed to fetch|环境|安装"
    r"|loading|pretrained|stall|state dict|dependency|version conflict)",
    re.I,
)


def troubles(payload: dict[str, Any], *, setup: bool = False) -> list[dict[str, Any]]:
    """Треды, похожие на отчёт о дефекте.

    :param setup: вернуть вместо этого треды про установку и окружение.

    Просьбы и вакансии не идут сюда вовсе. Установка отделена от поведения:
    «не ставится на Colab» — проблема человека, «персонажи не моргают» —
    свойство модели, и ради второго канал заведён. Обе группы считаются и
    печатаются: молча выбросить половину значит соврать о выходе канала.
    """
    rows = []
    for item in (payload.get("discussions") or [])[:DISCUSSIONS_SCANNED]:
        title = str(item.get("title") or "")
        if not TROUBLE.search(title):
            continue
        if bool(SETUP_TROUBLE.search(title)) == setup:
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

    разобрано = json.loads(talk) if talk_state == "ok" else {}
    found = troubles(разобрано) if talk_state == "ok" else []
    установочные = troubles(разобрано, setup=True) if talk_state == "ok" else []
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
        # Отдельным полем, потому что «обсуждений ноль» и «обсуждения нам не
        # отдали» — разные исходы (Р1), а вместе они читаются как «модель без
        # опыта практиков». ИЗМЕРЕНО 2026-08-31: из 12 моделей 11 отдали
        # обсуждения, одна (hexgrad/Kokoro-82M) ответила 403 — обсуждения на
        # ней просто выключены, и это не отсутствие опыта.
        "discussions_state": talk_state,
        "troubles": found,
        "setup_troubles": установочные,
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
    # Файл, который мы не смогли прочитать, в сравнении НЕ участвует: иначе
    # непрочитанная китайская версия «расходится» с прочитанной английской, и
    # прибор поднимает тревогу там, где просто не хватило языка.
    наборы = {
        frozenset(lic["flags"])
        for lic in licences
        if not any(str(f).startswith(CANNOT_READ) for f in lic["flags"])
    }
    return len(наборы) > 1


def already_known(model_id: str, store: FactStore | None = None) -> dict[str, Any]:
    """Что база УЖЕ знает про эту модель. Спрашивается ДО записи «нового».

    ЗАЧЕМ ЭТО ЗДЕСЬ. 2026-08-31 я объявил семейство `latentsync`, написав в
    комментарии к исходнику, что выделенных липсинк-моделей в базе нет. Их было
    двадцать фактов, с 27 августа, включая вендорские режимы отказа. Повтор
    ключа поймал ЛИНТЕР, а не я, и записанный «новый» факт оказался СЛАБЕЕ
    стоявшего из того же источника. Инструмент спросить базу был под рукой.
    Намерение «сначала спрашивать» — это строка правил, которая забывается;
    поэтому оно здесь, в выдаче, рядом с находками.
    """
    склад = store or FactStore()
    короткое = model_id.rsplit("/", 1)[-1].lower()
    свои = [m for m in склад.models() if m == короткое]
    соседи = склад.near(короткое)
    return {
        "exact": свои,
        "neighbours": соседи,
        "attributes": sorted({a for m in свои for a in склад.attributes(m)}),
    }


def report(rows: list[dict[str, Any]], store: FactStore | None = None) -> int:
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
        знание = already_known(row["model_id"], store)
        if знание["exact"]:
            print(f"    В БАЗЕ УЖЕ ЭТА: {', '.join(знание['exact'])}")
            print(
                f"       атрибутов записано {len(знание['attributes'])}: "
                f"{', '.join(знание['attributes'][:8])}"
            )
            print("       новым записывать только то, чего здесь НЕТ")
        else:
            print("    в базе этой модели нет")
        if знание["neighbours"]:
            # ПОХОЖИЕ, а не «уже есть». `omnigen2` и `omnihuman-1` делят четыре
            # первые буквы и не имеют друг к другу отношения — разные вендоры,
            # разные задачи. Печатать их как «уже в базе» значит подсказывать
            # неверно (поймано на живой выдаче 2026-08-31).
            print(f"    похожие имена (могут быть ЧУЖИЕ): {', '.join(знание['neighbours'][:5])}")
        всего = row["discussions_total"]
        сказано = (
            f"{всего}"
            if row.get("discussions_state") == "ok"
            else f"НЕ СМОГЛИ прочесть ({row.get('discussions_state')})"
        )
        print(
            f"    обсуждений: {сказано},"
            f" про поведение модели {len(row['troubles'])},"
            f" про установку {len(row.get('setup_troubles', []))}"
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
