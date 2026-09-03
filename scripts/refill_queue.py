"""Одна очередь дочитывания: что именно сейчас стоит идти читать.

ЗАЧЕМ ОДНА, А НЕ ТРИ

Работа, которая делает базу полнее, приходит из трёх мест, и до сих пор ни
одно не порождало работу — каждое только отвечало на вопрос:

  * `misses.jsonl` — о модели СПРОСИЛИ, а база промолчала. Спрос доказан.
  * `stale_model_facts` — факт старше 90 дней. Мы прямо сейчас отвечаем им.
  * `discover_models.py` — в индексе появилось то, чего у нас нет.

Три списка в трёх местах читаются как три необязательных отчёта. Один
упорядоченный список читается как очередь, и это разница между «знаем о
пробеле» и «пробел закрывается».

ПОЧЕМУ ПОРЯДОК ИМЕННО ТАКОЙ

Протухший ВЕНДОРСКИЙ факт стоит выше промаха нарочно: промах — это честное
«не знаем», а протухший факт — это ответ, который мы продолжаем выдавать за
верный. Неверный ответ дороже отсутствующего. Всё остальное — будущий спрос,
и оно ниже доказанного.

Порядок — константа-решение, и он сторожится тестом (правило Т1): если его
переставить, тест обязан покраснеть, иначе очередь не очередь, а список.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio.mcp import misses  # noqa: E402
from studio.selfrag import facts as facts_mod
from studio.selfrag import modelnames  # noqa: E402

import importlib.util as _iu  # noqa: E402

_спец = _iu.spec_from_file_location(
    "mark_reread", Path(__file__).resolve().parent / "mark_reread.py"
)
assert _спец and _спец.loader
reread = _iu.module_from_spec(_спец)
_спец.loader.exec_module(reread)
from studio.mcp import advice  # noqa: E402
from studio.selfrag.facts import STALE_AFTER_DAYS, TIER_VENDOR  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
FACTS = ROOT / "studio" / "knowledge" / "model_facts.jsonl"

#: Причина — ОДНА строка в одном месте, и производители берут её отсюда же.
#: Пока производители печатали свои литералы, а `PRIORITY` держал их копии,
#: опечатка на стороне производителя уводила все протухшие вендорские факты в
#: хвост очереди, и ни один тест этого не видел: тесты порядка подавали в
#: `order()` литералы, набранные в самом тесте, то есть проверяли копию
#: (найдено независимой проверкой 2026-08-31, правило Е1).
#: Страница ИЗМЕНИЛАСЬ — не «постарела», а именно изменилась, и это видел
#: прибор (`scripts/recheck_vendor.py`). Отдельная причина, а не разновидность
#: протухшего: у протухшего есть только возраст, то есть догадка, что источник
#: мог поменяться; здесь есть свидетельство, что он поменялся.
CHANGED_SOURCE = "источник изменился"
STALE_VENDOR = "протухший вендорский факт"
ASKED_UNKNOWN = "спросили — не знаем"
NEW_FAMILY = "новое семейство"
NEW_VERSION = "новая версия известного семейства"
STALE_OTHER = "протухший факт прочих тиров"

#: Промах, у которого база держит ПОХОЖЕЕ имя. Это другая работа: не «идти
#: читать источники», а «спросивший написал имя иначе», и путать их значит
#: посылать человека искать то, что лежит под соседним написанием.
ASKED_OTHER_SPELLING = "спросили другим написанием"

#: ВЫБРАНО 2026-08-31, дополнено 2026-09-02. Меньшее число — раньше в очереди.
#: Обоснование каждой ступени — в докстроке модуля; переставить их молча
#: нельзя, тест держит.
#:
#: `CHANGED_SOURCE` встал ВЫШЕ протухшего вендорского нарочно, и это не вкус:
#: возраст факта — догадка о том, что источник мог поменяться, а изменившийся
#: отпечаток — наблюдение, что он поменялся. Наблюдение раньше догадки.
PRIORITY: dict[str, int] = {
    CHANGED_SOURCE: 0,
    STALE_VENDOR: 1,
    ASKED_UNKNOWN: 2,
    # Рядом со спросом, но НИЖЕ него: работа тут дешевле — не читать источники,
    # а переспросить под тем именем, которое база знает.
    ASKED_OTHER_SPELLING: 2,
    NEW_FAMILY: 3,
    NEW_VERSION: 4,
    STALE_OTHER: 5,
}


def stale_work(today: date | None = None, path: Path | None = None) -> list[dict[str, Any]]:
    """Факты старше порога — тем, чем мы отвечаем, и что пора перечитать."""
    rows = facts_mod.load_facts(FACTS if path is None else path)
    when = today or date.today()
    found: list[dict[str, Any]] = []
    # Список из одного числа, а не просто число: счётчик обязан пережить
    # замыкание и напечататься рядом с очередью (Р2 — «сколько не взяли»
    # печатается, а не подразумевается).
    опубликованных = [0]
    for fact in rows:
        if not fact.stated_on:
            continue
        try:
            age = (when - date.fromisoformat(fact.stated_on)).days
        except ValueError:
            continue
        if age <= STALE_AFTER_DAYS:
            continue
        # ОПУБЛИКОВАННЫЙ ИСТОЧНИК В ОЧЕРЕДЬ ЧТЕНИЯ НЕ ИДЁТ. Правило одно на
        # проект и живёт в `advice.PUBLISHED_TIERS` (Е1): здесь оно было
        # переписано заново и поэтому не поехало вместе с починкой —
        # ИЗМЕРЕНО 2026-09-02, в очереди из 51 строки лежало 10 arXiv-ссылок,
        # старейшей 1352 дня. Статья говорит сегодня то же, что и в день
        # публикации; «перечитай её» — работа, которую нельзя выполнить, а
        # очередь, где такой работы пятая часть, читают по диагонали.
        #
        # Если модель с тех пор изменилась, ответ — измерить МОДЕЛЬ
        # (`propose_measurement`), а не перечитать статью.
        if fact.tier in advice.PUBLISHED_TIERS:
            опубликованных[0] += 1
            continue
        vendor = fact.tier == TIER_VENDOR
        found.append(
            {
                "reason": STALE_VENDOR if vendor else STALE_OTHER,
                "model": fact.model,
                "detail": f"{fact.attribute}, источнику {age} дней",
                "where": fact.source_url,
            }
        )
    if опубликованных[0]:
        print(
            f"  опубликованных источников старше {STALE_AFTER_DAYS} дней: "
            f"{опубликованных[0]} — в очередь НЕ взяты: статья не протухает"
        )
    return found


def missed_work(path: Path | None = None) -> list[dict[str, Any]]:
    """Модели, о которых спрашивали не раз и база молчала — ПО НЫНЕШНЕЙ базе.

    ПЕРЕСЧЁТ ОБЯЗАТЕЛЕН. ИЗМЕРЕНО 2026-09-02: журнал держал `minimax-h3` с
    двумя промахами по `max_seconds`, а база отвечает на этот вопрос `15` —
    ответ появился в тот же день, когда семья атрибутов научилась разворачивать
    `max_seconds` в `duration_enum` и соседей. Очередь, которая просит
    сделанного, читается по диагонали; на другом канале (`poll_portal`) это уже
    разбиралось.

    Три исхода промаха, а не один:

      * база отвечает -> строки нет вовсе, работа сделана;
      * база молчит, но держит ПОХОЖЕЕ имя -> `спросили другим написанием`;
      * база молчит совсем -> `спросили — не знаем`, работа читать источники.
    """
    готово: list[dict[str, Any]] = []
    for row in misses.queue(misses.load(path)):
        атрибуты = [а for а in (row.get("attributes") or []) if а] or [""]
        ответы = [advice.advise(row["model"], attribute=а) for а in атрибуты]
        # Отвечает хотя бы на один спрошенный атрибут — промах закрыт: очередь
        # про остальные атрибуты той же модели заведётся из журнала сама.
        if any(о.get("reason") == "answered" for о in ответы):
            continue
        соседи = sorted({и for о in ответы for и in (о.get("near") or [])})
        готово.append(
            {
                "reason": ASKED_OTHER_SPELLING if соседи else ASKED_UNKNOWN,
                "model": row["model"],
                "detail": f"спрашивали {row['misses']} раз(а), последний {row['last_asked']}"
                + (f"; база держит {', '.join(соседи[:3])}" if соседи else ""),
                "where": ", ".join(row["attributes"]) or "всё",
            }
        )
    return готово


#: Прогон опроса индексов, который лежит в знании. ЗАЧЕМ УМОЛЧАНИЕ: без него
#: очередь при каждом обычном запуске печатала «молчат: опрос индексов», хотя
#: файл лежал рядом и был свежим (снят 2026-08-31, 763 записи, оба канала
#: ответили). Третий исход, который выдаётся ВСЕГДА, перестаёт быть сигналом:
#: читатель привыкает и не замечает дня, когда канал замолчит по-настоящему.
#: Молчание осталось молчанием — но теперь оно означает «файла нет», а не
#: «флаг не передали».
ОПРОС_ПО_УМОЛЧАНИЮ = (
    Path(__file__).resolve().parents[1] / "studio" / "knowledge" / "catalog_poll.json"
)


def _дней_назад(когда: str) -> int | None:
    """Возраст прогона в днях. Нечитаемая дата — None, а не ноль.

    Печатается рядом с очередью: свежесть опроса и его наличие — разные вещи,
    и «канал ответил» месячной давности читается как сегодняшний, если возраст
    не назвать.
    """
    try:
        return (date.today() - date.fromisoformat(когда)).days
    except ValueError:
        return None


def discovered_work(payload: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Находки опроса индексов, если прогон сохранён. Нет прогона — нет строк."""
    if not payload:
        return []
    found: list[dict[str, Any]] = []
    for row in payload.get("new_families", []):
        found.append(
            {
                "reason": NEW_FAMILY,
                "model": row.get("family", ""),
                "detail": f"загрузчиков {len(row.get('uploaders', []))}, задача {row.get('task', '')}",
                "where": ", ".join(row.get("examples", [])[:2]),
            }
        )
    for row in payload.get("new_versions", []):
        found.append(
            {
                "reason": NEW_VERSION,
                "model": row.get("stem", ""),
                "detail": f"семейство {row.get('family', '')}, перезаливок {row.get('count', 0)}",
                "where": ", ".join(row.get("examples", [])[:2]),
            }
        )
    return found


#: Журнал отпечатков вендорских страниц и очередь портала — то, что производят
#: каналы, заведённые 2026-09-02. Читаются отсюда, а не пересчитываются: сходить
#: в сеть за очередью значило бы сделать очередь недоступной без сети.
СТРАНИЦЫ = ROOT / "studio" / "knowledge" / "vendor_pages.jsonl"
ПОРТАЛ = ROOT / "studio" / "knowledge" / "portal_poll.json"


def changed_work(
    path: Path | None = None, перечитаны: dict[str, str] | None = None
) -> tuple[list[dict[str, Any]], int]:
    """Страницы, чей отпечаток разошёлся с предыдущим. Журнал: сравниваются
    ДВЕ последние записи одного адреса одного и того же способа.

    Одна запись — сравнивать не с чем (основание только заведено), и это НЕ
    строка работы: иначе первый же прогон канала завалил бы очередь семьюдесятью
    «изменилось», ни одно из которых не наблюдалось.
    """
    журнал = path or СТРАНИЦЫ
    if not журнал.is_file():
        return [], 0
    # ПЕРЕЧИТАННОЕ ИЗ ОЧЕРЕДИ УХОДИТ. Канал говорит «страница изменилась»,
    # человек сверяет утверждения за ней — и очередь предлагает ту же страницу
    # завтра, потому что о перечитывании не знает ничего. ИЗМЕРЕНО 2026-09-03:
    # 11 страниц перечитаны, 56 утверждений сверены, очередь показывала те же
    # 11. Дата факта при этом НЕ двигается: перечитывание — наше действие, а
    # `stated_on` принадлежит источнику (`scripts/mark_reread.py`).
    прочитано = перечитаны if перечитаны is not None else reread.последнее()
    по_адресу: dict[str, list[dict[str, Any]]] = {}
    for строка in журнал.read_text(encoding="utf-8").splitlines():
        строка = строка.strip()
        if not строка or строка.startswith("//"):
            continue
        try:
            запись = json.loads(строка)
        except ValueError:
            continue
        url = str(запись.get("url") or "")
        if url:
            по_адресу.setdefault(url, []).append(запись)
    работа: list[dict[str, Any]] = []
    сделано = 0
    for url, записи in по_адресу.items():
        свои = [з for з in записи if з.get("method") == записи[-1].get("method")]
        if len(свои) < 2 or свои[-1].get("fingerprint") == свои[-2].get("fingerprint"):
            continue
        # Перечитано ПОСЛЕ того, как изменение увидели, — работа сделана.
        # Раньше — не считается: читали прежнюю страницу.
        if прочитано.get(url, "") >= str(свои[-1].get("seen_on") or ""):
            сделано += 1
            continue
        работа.append(
            {
                "reason": CHANGED_SOURCE,
                "model": url.split("/")[2] if "//" in url else url,
                "detail": (
                    f"утверждений на странице {свои[-1].get('claims', '?')}, "
                    f"прежде виделась {свои[-2].get('seen_on', 'без даты')}"
                ),
                "where": url,
            }
        )
    return работа, сделано


def уже_знаем(строка: dict[str, Any], известные: set[str]) -> bool:
    """Знает ли база это семейство — по имени модели, а не по имени семейства.

    Имя в базе выводится из адреса эндпоинта тем же разборщиком, что и при
    записи (`modelnames.from_portal_id`, Е1): семейство `ai-avatar` попадает
    в базу как `ai-avatar-multi`, и сравнение по имени семейства не нашло бы
    ничего.
    """
    for адрес in строка.get("examples") or []:
        эндпоинт = str(адрес).split("/models/")[-1]
        if modelnames.from_portal_id(эндпоинт) in известные:
            return True
    return str(строка.get("family", "")) in известные


def portal_work(
    path: Path | None = None, известные: set[str] | None = None
) -> tuple[list[dict[str, Any]], int]:
    """Имена с портала, которых база НЕ ЗНАЕТ, и сколько отсеяно как известные.

    Неполный опрос строк не даёт: неполная очередь — третий исход у самого
    канала (`poll_portal.py`), и подмешивать её сюда значило бы выдать пробел
    опроса за отсутствие работы.

    СНИМОК ОПРОСА — НЕ СОСТОЯНИЕ БАЗЫ, И ЭТО ИЗМЕРЕНО. Файл опроса пишется
    один раз и не меняется, когда семейство собрано; очередь читала его
    дословно и 2026-09-03 предлагала 37 строк работы, из которых сделаны были
    ВСЕ 37. Очередь, где каждая строка сделана, учит себя не открывать —
    ровно как канал, который кричит двести раз (см. `recheck_vendor`).
    Отсеянное печатается числом (Р2), а не пропадает молча.
    """
    файл = path or ПОРТАЛ
    if not файл.is_file():
        return [], 0
    try:
        снято = json.loads(файл.read_text(encoding="utf-8"))
    except ValueError:
        return [], 0
    if снято.get("partial"):
        return [], 0
    имена = известные if известные is not None else {ф.model for ф in facts_mod.load_facts(FACTS)}
    все = снято.get("new_families") or []
    новые = [с for с in все if not уже_знаем(с, имена)]
    return (
        [
            {
                "reason": NEW_FAMILY,
                "model": str(строка.get("family", "")),
                "detail": f"продаётся на {снято.get('portal', 'портале')}, "
                f"{строка.get('task', '')}"[:90],
                "where": ", ".join((строка.get("examples") or [])[:2]),
            }
            for строка in новые
        ],
        len(все) - len(новые),
    )


#: Что журнал отпечатков знает о странице. Три состояния, и третье — самое
#: частое: наблюдать начали сегодня, у большинства страниц по одной записи.
ИСТОЧНИК_ПРЕЖНИЙ = "источник не менялся"
ИСТОЧНИК_ИЗМЕНИЛСЯ = "источник изменился"
ИСТОЧНИК_НЕ_НАБЛЮДАЛИ = "источник не наблюдали"


def состояние_источников(path: Path | None = None) -> dict[str, tuple[str, str]]:
    """URL -> (что известно об источнике, дата последнего наблюдения).

    ЗАЧЕМ. Возраст факта — ДОГАДКА о том, что источник мог поменяться. Очередь
    ставит по нему шесть вендорских строк, и человек идёт перечитывать
    страницы, которые, возможно, не менялись ни на знак.

    ПРОВЕРЕНО РУКАМИ 2026-09-02 на `kling-3.0.max_seconds = 15`, источнику 209
    дней: страница жива и говорит дословно «extended video duration of up to
    15 seconds». Факт верен; протухла только его дата.

    Отпечаток не отменяет возраст и не делает факт свежим: вендор мог выпустить
    новую модель, ничего не поменяв на СТАРОЙ странице. Поэтому строка остаётся
    в очереди, но рядом с ней стоит, что известно об источнике, — и читающий
    сам решает, с чего начать.
    """
    журнал = path or СТРАНИЦЫ
    if not журнал.is_file():
        return {}
    по_адресу: dict[str, list[dict[str, Any]]] = {}
    for строка in журнал.read_text(encoding="utf-8").splitlines():
        строка = строка.strip()
        if not строка or строка.startswith("//"):
            continue
        try:
            запись = json.loads(строка)
        except ValueError:
            continue
        if запись.get("url"):
            по_адресу.setdefault(str(запись["url"]), []).append(запись)
    итог: dict[str, tuple[str, str]] = {}
    for url, записи in по_адресу.items():
        свои = [з for з in записи if з.get("method") == записи[-1].get("method")]
        когда = str(записи[-1].get("seen_on") or "без даты")
        if len(свои) < 2:
            итог[url] = (ИСТОЧНИК_НЕ_НАБЛЮДАЛИ, когда)
        elif свои[-1].get("fingerprint") == свои[-2].get("fingerprint"):
            итог[url] = (ИСТОЧНИК_ПРЕЖНИЙ, когда)
        else:
            итог[url] = (ИСТОЧНИК_ИЗМЕНИЛСЯ, когда)
    return итог


def с_состоянием_источника(
    rows: list[dict[str, Any]],
    состояния: dict[str, tuple[str, str]],
    перечитаны: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Дописать к строкам очереди, что известно об их источнике.

    ПЕРЕЧИТЫВАНИЕ ПОКАЗЫВАЕТСЯ, НО НЕ ДВИГАЕТ ПОРЯДОК, и это НЕ забывчивость.
    Возраст факта считается от даты ИСТОЧНИКА; засчитать перечитывание за
    свежесть значило бы решить продуктовый вопрос молча — а он задан владельцу
    и ответа на него нет. Поэтому строка несёт оба свидетельства рядом:
    сколько факту лет и когда мы последний раз сверяли его с источником.
    """
    прочитано = перечитаны if перечитаны is not None else reread.последнее()
    готово: list[dict[str, Any]] = []
    for строка in rows:
        адрес = str(строка.get("where") or "")
        что, когда = состояния.get(адрес, (ИСТОЧНИК_НЕ_НАБЛЮДАЛИ, ""))
        сверено = прочитано.get(адрес, "")
        готово.append(
            {
                **строка,
                "detail": f"{строка.get('detail', '')} [{что}"
                + (f" {когда}]" if когда else "]")
                + (f" [сверено с источником {сверено}]" if сверено else ""),
            }
        )
    return готово


def order(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Очередь: по приоритету причины, внутри причины — по имени модели.

    Неизвестная причина уезжает в конец, а не роняет прогон: очередь, которая
    падает от новой строки, перестаёт быть очередью ровно тогда, когда её
    расширяют.
    """
    ranked = sorted(rows, key=lambda r: (PRIORITY.get(str(r["reason"]), 99), str(r["model"])))
    return ranked


def report(rows: list[dict[str, Any]], sources: dict[str, bool], limit: int) -> int:
    """Напечатать очередь числами и вернуть исход из трёх."""
    silent = [name for name, answered in sources.items() if not answered]
    counts: dict[str, int] = {}
    for row in rows:
        counts[str(row["reason"])] = counts.get(str(row["reason"]), 0) + 1

    print("ОЧЕРЕДЬ ДОЧИТЫВАНИЯ")
    print(
        f"источников работы {len(sources)}, ответили {len(sources) - len(silent)}, "
        f"не смогли {len(silent)}"
    )
    if silent:
        print("  молчат: " + ", ".join(silent))
    print(f"строк в очереди {len(rows)}")
    for reason in sorted(counts, key=lambda r: PRIORITY.get(r, 99)):
        print(f"  {reason}: {counts[reason]}")

    print(f"\n--- ПЕРВЫЕ {min(limit, len(rows))}")
    for row in order(rows)[:limit]:
        print(f"  [{row['reason']}] {row['model']}")
        print(f"       {row['detail']}  |  {row['where']}")

    if len(silent) == len(sources):
        print("\nисход: не смогли — ни один источник работы не ответил")
        return 2
    if silent:
        print(f"\nисход: не смогли полностью — молчат {len(silent)} из {len(sources)}")
        return 2
    print(f"\nисход: годно — работы на {len(rows)} строк")
    return 0


def check_journal(path: Path | None = None) -> int:
    """Гейт: журнал читается, строки целы, знаменатель покрытия существует.

    Сети здесь нет нарочно — гейт обязан быть честным в CI (правило Т4). Три
    исхода: битая строка красит сборку, пустой журнал красит её отдельным
    сообщением (файл лежит в репозитории заполненным, и пустым он может стать
    только если строки вычистили), целый журнал печатает числа и молчит.
    """
    rows, torn = misses.read(path)
    broken = [(i, misses.problems(row)) for i, row in enumerate(rows, 1) if misses.problems(row)]
    cover = misses.coverage(rows)
    print(
        f"журнал вопросов: разобрано {len(rows)}, не разобралось {len(torn)}, "
        f"битых по схеме {len(broken)}"
    )
    if torn:
        print("  строки, не разобравшиеся как JSON: " + ", ".join(str(n) for n in torn[:10]))
    print(f"покрытие: {cover.note}, исход {cover.outcome}")
    # «запись», а не «строка»: здесь порядковый номер среди РАЗОБРАВШИХСЯ, и
    # он не совпадает с номером строки в файле, если выше был обрыв. Две разные
    # нумерации под одним словом — способ отправить читателя не туда.
    for number, found in broken[:10]:
        print(f"  запись {number}: " + "; ".join(found))
    if broken or torn:
        print("ПРОВАЛ: битые строки в журнале — знаменатель покрытия им врёт")
        return 1
    if not rows:
        print("НЕ СМОГЛИ: журнал пуст, мерить покрытие нечем")
        return 2
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--discovered",
        type=Path,
        default=ОПРОС_ПО_УМОЛЧАНИЮ,
        help=(
            "сохранённый прогон discover_models.py --json; по умолчанию берётся "
            f"{ОПРОС_ПО_УМОЛЧАНИЮ.name} из знания, если он там есть"
        ),
    )
    parser.add_argument("--limit", type=int, default=20, help="сколько строк печатать")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--check",
        action="store_true",
        help="гейт: схема журнала вопросов и знаменатель покрытия, без сети",
    )
    args = parser.parse_args(argv)

    if args.check:
        return check_journal()

    payload: dict[str, Any] | None = None
    if args.discovered and args.discovered.exists():
        payload = json.loads(args.discovered.read_text(encoding="utf-8"))
        снято = str(payload.get("polled_on") or "")
        возраст = _дней_назад(снято)
        print(
            f"  опрос индексов: снят {снято or 'без даты'}"
            + (f", {возраст} дн. назад" if возраст is not None else "")
            + f", каналов ответило {payload.get('channels_answered', '?')}"
            f" из {payload.get('channels_asked', '?')}"
        )

    asked = missed_work()
    stale = stale_work()
    fresh = discovered_work(payload)
    changed, перечитанных = changed_work()
    portal, портальных_уже_знаем = portal_work()
    # Возрастные строки несут рядом наблюдение об источнике: возраст —
    # догадка, отпечаток — свидетельство, и читающему видно оба.
    состояния = состояние_источников()
    if перечитанных:
        print(
            f"  изменившихся страниц уже перечитано: {перечитанных} — "
            "в очередь НЕ взяты: утверждения за ними сверены"
        )
    if портальных_уже_знаем:
        print(
            f"  семейств с портала уже в базе: {портальных_уже_знаем} — "
            "в очередь НЕ взяты: работа сделана"
        )
    rows = order(с_состоянием_источника(stale, состояния) + asked + fresh + changed + portal)
    # ИСТОЧНИК, КОТОРЫЙ МОЛЧИТ, НАЗЫВАЕТСЯ ПОИМЁННО. Пустая очередь по вине
    # ненайденного файла и пустая очередь по отсутствию работы — разные вещи,
    # и до 2026-09-02 два новых канала не значились здесь вовсе: их молчание
    # было бы неотличимо от их отсутствия.
    sources = {
        "журнал вопросов": bool(misses.load()),
        "факты с датами": bool(stale) or bool(facts_mod.load_facts(FACTS)),
        "опрос индексов": payload is not None,
        "отпечатки вендорских страниц": СТРАНИЦЫ.is_file(),
        "опрос портала": ПОРТАЛ.is_file(),
    }
    if args.json:
        print(json.dumps({"queue": rows, "sources": sources}, ensure_ascii=False, indent=2))
        return 0 if any(sources.values()) else 2
    return report(rows, sources, args.limit)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
