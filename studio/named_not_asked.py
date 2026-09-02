"""Названо, но не спрошено: имена моделей в ответе против вызовов `model_advice`.

Инструкция MCP-сервера (`studio/mcp/server.py`, поле `instructions`) требует
звать `model_advice` на КАЖДОГО кандидата, которого сравниваешь, а не только на
того, который нравится. Правило жило словами и не исполнялось ничем. Ц7: то,
что обязано выполняться всегда, — это хук, а не строка правил.

ЧТО ЭТОТ МОДУЛЬ ДЕЛАЕТ. Берёт завершаемый ответ и след сессии, находит в ответе
имена моделей ИЗ БАЗЫ (Е1: список имён не копируется, он приходит из
`studio/knowledge/model_facts.jsonl` через `FactStore.models()`), оставляет из
них только те, что названы в РЕКОМЕНДАТЕЛЬНОЙ фразе, и сверяет с именами, по
которым в этой сессии был вызов `model_advice`.

ГЛАВНЫЙ РИСК — ЛОЖНОЕ СРАБАТЫВАНИЕ, и он измерен, а не оценён на глаз.
ИЗМЕРЕНО 2026-09-02 прибором `scripts/stop_named_not_asked.py --measure` на
живом следе `/root/.claude/projects/-home-user-lipsync-templates/` (618 файлов
транскриптов, 2560 текстовых блоков ассистента, 395 вызовов `model_advice`;
след ПИШЕТСЯ ВО ВРЕМЯ ЗАМЕРА, поэтому число блоков растёт от прогона к прогону
на единицы):

* голое совпадение по имени — 177 блоков называют хоть одну модель из базы, из
  них 157 называют имя, по которому `model_advice` в этом файле не звался.
  Выборка 14 таких блоков просмотрена глазами (П3): рекомендаций среди них
  НОЛЬ — это инженерные отчёты, где имя модели предмет разбора
  (`kling-3.0.failure_mode`), а не совет. Голое имя даёт ~90% ложных;
* с фильтром рекомендательной фразы (`CUES`) — 1 блок на весь след, и он
  настоящий: таблица лицензий, где `chatterbox` назван «прямой кандидат» без
  единого вызова `model_advice`. Ложных 0 из 2560.

Порог фильтра стоит на измеренном. Широкая форма ловила три ложных, и все три
одного рода — разговор О рекомендации вместо рекомендации: «помечено до
попадания в рекомендации», «читалось бы как уверенная рекомендация», «turns a
"works best" recommendation into a hard maximum». Поэтому в `CUES` стоят
глагольные формы и слово «кандидат», а существительные «рекомендация» и
`recommendation` — нет. Все три текста сохранены фикстурами в
`studio/fixtures/named_not_asked_controls.json` и обязаны молчать (И5), рядом
с входом, на котором прибор обязан шевельнуться.

ТРИ ИСХОДА (Р1). `годно` / `не годно` (названо без запроса) / `не смогли`
(следа нет, не читается, ни одного ответа ассистента в нём). Третий не
сворачивается ни в первый, ни во второй: молчание из-за нечитаемого следа
выглядит как чистый ответ, и это ровно та подмена, которая стоила проектов.
Рядом всегда печатается `проверено N`, `нарушений M`, `не смогли K` (Р2).

ИЗВЕСТНЫЙ ПРЕДЕЛ. Хук видит только имена, КОТОРЫЕ БАЗА ЗНАЕТ: рекомендация
модели, которой в базе нет, здесь не ловится ничем — её и `model_advice` не
опишет. Сравнение имён точное (без склейки `kling 3.0` -> `kling-3.0`):
свободная нормализация возвращает ложные, ради которых всё и сужалось.
Сети здесь нет (Т4).

# DEBT(2026-09-02): хэндоф ветки этой работой НЕ дописан. `HANDOFF_*.md` в этой
# сессии — чужой файл под параллельными писателями (Ц2), и правило Ц6 уступило
# правилу Ц2 осознанно. Что сюда должно попасть, названо в отчёте сессии:
# числа замера, три отсечённых ложных и место хука в `.claude/settings.json`.
# DEBT(2026-09-02): рекомендация модели, КОТОРОЙ НЕТ В БАЗЕ, не ловится ничем —
# ни этим хуком, ни `model_advice`. Это и есть самый дорогой случай (советуем
# то, о чём не знаем), и он остаётся открытым.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio.selfrag.facts import DEFAULT_FACTS_PATH, FactStore, load_facts

#: Имя-джокер базы: `*` — это ОБЛАСТЬ (всё поле), а не модель, и рекомендовать
#: его нельзя. Приходит из facts.py, где он и определён.
SCOPE_NAME = "*"

#: Признак рекомендательной фразы. ВЫБРАНО из форм, встреченных на живом следе,
#: и СУЖЕНО по измерению: см. модульный докстринг. Существительных
#: «рекомендация/recommendation» здесь нет намеренно — они чаще всего
#: встречаются в разговоре О рекомендациях. Это константа-решение: расширение
#: списка обязано покраснить негативный контроль, сужение — позитивный.
CUES = re.compile(
    r"рекоменду[юем]"
    r"|советую"
    r"|посоветую"
    r"|берит[ей]"
    r"|возьмит[ей]"
    r"|стоит взять"
    r"|лучше подойд"
    r"|подойдёт лучше"
    r"|кандидат"
    r"|\brecommend(?:s|ed|ing)?\b"
    r"|would use"
    r"|go with"
    r"|best choice"
    r"|better suited"
    r"|candidate",
    re.IGNORECASE,
)

#: Блок кода: имя внутри — это вызов, лог или конфиг, а не совет.
FENCE = re.compile(r"```.*?(?:```|\Z)", re.DOTALL)

#: Цитата пользователя. Имя, названное ИМ, — не наша рекомендация.
QUOTE_MARK = ">"

#: Граница предложения: знак конца ПЛЮС пробел, либо перевод строки. Точка без
#: пробела границей не считается, и это не косметика — на ней прибор врал:
#: `veo-3.1` разрезалось на `veo-3` и `1`, и хук требовал спросить о `veo-3`,
#: которого никто не называл. Нашёл это контрольный набор (И5), а не чтение.
#: По ячейке markdown-таблицы (`|`) не режется тоже: единственная настоящая
#: находка на живом следе — строка таблицы, где имя стоит в одной ячейке, а
#: «прямой кандидат» в соседней.
SENTENCE = re.compile(r"(?<=[.!?…])\s+|\n+")

#: Имя инструмента в следе. Сервер регистрирует его как `model_advice`, клиент
#: пишет с префиксом `mcp__<сервер>__`; сверка идёт по хвосту.
ADVICE_TOOL_SUFFIX = "model_advice"


def model_names(path: Path | None = None) -> list[str]:
    """Имена моделей из базы. Е1: список не копируется, а импортируется."""
    facts = load_facts(path or DEFAULT_FACTS_PATH)
    return [name for name in FactStore(facts).models() if name != SCOPE_NAME]


def name_pattern(names: list[str]) -> re.Pattern[str] | None:
    """Одна альтернатива на весь список — дешевле 465 отдельных прогонов (П2)."""
    usable = sorted({n.strip() for n in names if n.strip()}, key=len, reverse=True)
    if not usable:
        return None
    body = "|".join(re.escape(n) for n in usable)
    return re.compile(rf"(?<![0-9a-z])({body})(?![0-9a-z\-])", re.IGNORECASE)


def countable_text(text: str) -> str:
    """Что вообще считается сказанным НАМИ: без блоков кода и без цитат."""
    without_code = FENCE.sub(" ", text)
    lines = [line for line in without_code.split("\n") if not line.lstrip().startswith(QUOTE_MARK)]
    return "\n".join(lines)


def recommended_names(text: str, names: list[str]) -> list[str]:
    """Имена, названные в рекомендательной фразе. Развилка вынесена сюда (Т5)."""
    pattern = name_pattern(names)
    if pattern is None:
        return []
    found: set[str] = set()
    for sentence in SENTENCE.split(countable_text(text)):
        if CUES.search(sentence):
            found.update(m.group(1).lower() for m in pattern.finditer(sentence))
    return sorted(found)


def read_trace(path: Path) -> dict[str, Any]:
    """След сессии: по каким именам звали `model_advice` и чем ответ кончился.

    Возвращает `outcome`: `pass` — прочитан, `could not measure` — файла нет,
    он не читается или ни одного ответа ассистента в нём не нашлось.
    """
    asked: set[str] = set()
    answer = ""
    try:
        handle = path.open(encoding="utf-8", errors="replace")
    except OSError as exc:
        return {
            "outcome": UNMEASURED,
            "asked": [],
            "answer": "",
            "note": f"след не читается: {type(exc).__name__}: {exc}",
        }
    with handle:
        for line in handle:
            if not line.strip():
                continue
            if ADVICE_TOOL_SUFFIX not in line and '"text"' not in line:
                continue
            try:
                record = json.loads(line)
            except ValueError:
                continue
            if not isinstance(record, dict) or record.get("type") != "assistant":
                continue
            blocks = (record.get("message") or {}).get("content") or []
            texts = []
            for block in blocks:
                if not isinstance(block, dict):
                    continue
                kind = block.get("type")
                if kind == "tool_use" and str(block.get("name", "")).endswith(ADVICE_TOOL_SUFFIX):
                    asked.add(str((block.get("input") or {}).get("model", "")).strip().lower())
                elif kind == "text" and (block.get("text") or "").strip():
                    texts.append(str(block.get("text")))
            if texts:
                answer = "\n".join(texts)
    if not answer:
        return {
            "outcome": UNMEASURED,
            "asked": sorted(asked),
            "answer": "",
            "note": f"в следе {path} нет ни одного ответа ассистента",
        }
    return {"outcome": PASS, "asked": sorted(asked), "answer": answer, "note": "след прочитан"}


def judge(answer: str, asked: list[str], names: list[str]) -> dict[str, Any]:
    """Вердикт по уже прочитанному следу. Отдельная функция ради Т5 и И1."""
    named = recommended_names(answer, names)
    asked_low = {a.strip().lower() for a in asked}
    unasked = [n for n in named if n not in asked_low]
    return {
        "outcome": FAIL if unasked else PASS,
        "checked": len(named),
        "violations": len(unasked),
        "unmeasured": 0,
        "named": named,
        "unasked": unasked,
        "note": (
            f"названо без запроса: {', '.join(unasked)}"
            if unasked
            else f"рекомендательно названо {len(named)} имён, все спрошены"
        ),
    }


def verdict(transcript: Path | None, *, facts_path: Path | None = None) -> dict[str, Any]:
    """Полный вердикт по следу. Три исхода, третий не сворачивается (Р1)."""
    if transcript is None:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "named": [],
            "unasked": [],
            "note": "хук не получил пути к следу",
        }
    trace = read_trace(Path(transcript))
    if trace["outcome"] == UNMEASURED:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "named": [],
            "unasked": [],
            "note": trace["note"],
        }
    return judge(trace["answer"], trace["asked"], model_names(facts_path))


def render(result: dict[str, Any]) -> str:
    """Строка отчёта. Р2: числа рядом с исходом, а не вместо него."""
    return (
        f"[названо-но-не-спрошено] исход: {result['outcome']}; "
        f"проверено {result['checked']}, нарушений {result['violations']}, "
        f"не смогли {result['unmeasured']}. {result['note']}"
    )
