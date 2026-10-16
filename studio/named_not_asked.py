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

ВТОРОЙ ПРИБОР: ИМЯ, КОТОРОГО БАЗА НЕ ЗНАЕТ. Первая редакция видела только
имена ИЗ базы, и это был её самый дорогой предел: у моделей около пятой части
предлагаемых имён не существует (Ц10), а выдуманное звучит ровно так же
уверенно, как настоящее. Теперь токен в рекомендательной фразе, похожий на имя
модели (известное базе СЕМЕЙСТВО, но незнакомое имя), тоже останавливает ход.

ИЗМЕРЕНО 2026-09-02 тем же прибором `--measure` на том же следе (2577 блоков):

* в рекомендательной фразе имя вне базы названо ОДИН раз, и оно НЕ выдумано:
  `Flux.1` — настоящая модель, лежащая в базе как `flux-1-dev` / `flux.1-dev`.
  Выдуманных имён в рекомендательных фразах на этом следе НОЛЬ, и это
  записанный отрицательный результат (И6), а не повод подкрутить прибор;
* широкая сеть (тот же разбор без фильтра рекомендательной фразы) — 68 имён
  вне базы. Выборка 14 просмотрена глазами (П3): ложных 0, все четырнадцать —
  настоящие имена (`gen4.5`, `kling-2.5`, `Wan2.6-T2V`, `sora-2-2025-10-06`,
  `sync-lipsync`, `Gen-4.5`). До отсевов та же сеть давала 198 токенов, и
  ложные шли тремя классами, каждый из которых теперь отсеивается по имени:
  файл документации (`sora-2.md`), ссылка на строку базы
  (`kling-3.0.failure_mode`), два имени, склеенные слэшем (`flux-3/wav2lip`),
  и слитное техническое слово с цифрами (`float16` — у базы есть модель
  `float`);
* «разобрать не смогли» в рекомендательной фразе — 3 токена
  (`apache-2.0` и два имени длиннее семейства). Третий исход по тексту ответа
  существует и наблюдаем.

«НЕТ В БАЗЕ» НЕ ЕСТЬ «НЕ СУЩЕСТВУЕТ», и хук говорит именно первое. База
собрана нами и заведомо неполна; единственное утверждение, на которое у нас
есть право, — «мы не смотрели». Поэтому у имени три исхода, а не два: база
знает / база не знает, но имя похоже на настоящее / разобрать не смогли.
Близкие имена для подсказки берутся у `studio/selfrag/modelnames.resolve`,
второго такого разрешения здесь не заводится (Е1).

ИЗВЕСТНЫЙ ПРЕДЕЛ. Сравнение имён точное (без склейки `kling 3.0` ->
`kling-3.0`): свободная нормализация возвращает ложные, ради которых всё и
сужалось. Сети здесь нет (Т4).

# DEBT(2026-09-02): хэндоф ветки этой работой НЕ дописан. `HANDOFF_*.md` в этой
# сессии — чужой файл под параллельными писателями (Ц2), и правило Ц6 уступило
# правилу Ц2 осознанно. Что сюда должно попасть, названо в отчёте сессии:
# числа замера, три отсечённых ложных и место хука в `.claude/settings.json`.
# DEBT(2026-09-02): выдуманное имя БЕЗ РАЗДЕЛИТЕЛЯ (`kling4`, `veo5`) проходит
# мимо: отсев слитных слов с цифрами поставлен ради `float16`, и цена названа
# числом в шапке. Осталось от прежнего долга «имя вне базы не ловится ничем»,
# закрытого вторым прибором; закрывать этот остаток есть чем только на новом
# измерении — на этом следе ни одного такого имени не встретилось.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from lipsync.fork_identity import FAIL, PASS, UNMEASURED

from studio.selfrag.facts import DEFAULT_FACTS_PATH, FactStore, load_facts
from studio.selfrag.modelnames import NOT_IN_BASE, RESOLVED, fold, resolve

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

#: Что вообще может оказаться именем модели: слово из букв и цифр, возможно
#: собранное через `-`, `_` или `.`. Косая черта в разделители НЕ входит, и
#: это измерено: `sora-2/elevenlabs-pvc` и `flux-3/wav2lip` — ДВА имени через
#: слэш, а склеенные они не разрешаются ни во что и дают ложное. Разрез по
#: слэшу заодно делит и путь, и запись `вендор/модель` с Hugging Face.
TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[-._][A-Za-z0-9]+)*")

#: Сколько букв в начале имени считаются СЕМЕЙСТВОМ (`veo-3.1` -> `veo`).
#: ВЫБРАНО 3: две буквы (`f5`, `ai`) цепляют слишком многое, четыре теряют
#: `ltx`, `veo`, `wan`, `gpt` — семейства, которые в базе как раз и есть.
FAMILY_MIN = 3

#: Расширения файлов. ИЗМЕРЕНО на живом следе: `sora-2.md`, `gpt-image-2.md`,
#: `gpt-5.6-sol.md` — самый частый класс ложных у широкой сети, это ссылки на
#: страницы документации, а не имена моделей.
FILE_SUFFIXES = (
    ".md",
    ".json",
    ".jsonl",
    ".py",
    ".txt",
    ".html",
    ".yaml",
    ".yml",
    ".csv",
    ".png",
    ".mp4",
)

#: Исходы для ОДНОГО имени, поверх исходов проверки. `не в базе` — это НЕ
#: «такой модели нет»: база собрана нами и заведомо неполна. Разница
#: наблюдаемая: первое лечится поиском источника, второе — несуществующим
#: действием, потому что второго мы не знаем.
NAME_IN_BASE = "in_base"
NAME_OUTSIDE_BASE = "outside_base"


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
        if not CUES.search(sentence):
            continue
        for match in pattern.finditer(sentence):
            # `sora-2.md` — страница документации, а не совет взять модель.
            # Имя базы стоит внутри имени файла, и без этого отсева совет
            # «прочти sora-2.md» читался бы как рекомендация модели.
            if sentence[match.end() :].lower().startswith(FILE_SUFFIXES):
                continue
            found.add(match.group(1).lower())
    return sorted(found)


def families(names: list[str]) -> set[str]:
    """Семейства базы: ведущие буквы свёрнутого имени. Список НЕ копируется."""
    out: set[str] = set()
    for name in names:
        head = re.match(r"[a-z]+", fold(name))
        if head and len(head.group(0)) >= FAMILY_MIN:
            out.add(head.group(0))
    return out


def looks_like_a_model_name(token: str, known_folds: set[str], known_families: set[str]) -> bool:
    """Токен похож на имя модели, но базы под ним нет. Развилка целиком здесь.

    Три отсева, и каждый стоит на классе ложных, ВИДЕННОМ на живом следе:

    * файл (`sora-2.md`) — это страница документации, а не модель;
    * `имя.атрибут` (`kling-3.0.failure_mode`, `flux-2-pro.max_resolution`) —
      ссылка на строку базы, самый частый класс у широкой сети;
    * незнакомое семейство (`torch-2.4`, `python-3.11`) — библиотека, а не
      модель. Семейство берётся из базы, а не из списка руками;
    * имя без единого разделителя (`float16`, `int8`) — техническое слово,
      прилипшее к цифрам. ИЗМЕРЕНО: `float16` было единственным ложным в
      выборке 14 из широкой сети, и оно ложное ровно потому, что в базе есть
      модель `float`. ЦЕНА ЭТОГО ОТСЕВА НАЗВАНА: слитное выдуманное имя вида
      `kling4` тоже пройдёт мимо — см. долг в шапке модуля.
    """
    low = token.lower()
    if low.endswith(FILE_SUFFIXES):
        return False
    folded = fold(token)
    if not folded or folded in known_folds:
        return False
    if "." in token:
        stem = token.rsplit(".", 1)[0]
        if fold(stem) in known_folds:
            return False
    if not any(ch in "-._" for ch in token):
        return False
    head = re.match(r"[a-z]+", folded)
    if not head or len(head.group(0)) < FAMILY_MIN:
        return False
    return head.group(0) in known_families


def version_shaped(token: str, known_folds: set[str]) -> bool:
    """Токен формы «слово-цифры»: может быть моделью, а может быть библиотекой.

    Это третий исход для ОДНОГО имени (Р1): не «имя базы» и не «похоже на
    модель, но базы нет», а «разобрать не смогли». Он не сворачивается ни в
    один из первых: `torch-2.4` молча посчитанный чистым и молча посчитанный
    нарушением — две разные неправды.
    """
    low = token.lower()
    if low.endswith(FILE_SUFFIXES):
        return False
    folded = fold(token)
    if not folded or folded in known_folds:
        return False
    if "." in token and fold(token.rsplit(".", 1)[0]) in known_folds:
        return False
    if not any(ch in "-._" for ch in token):
        return False
    return any(ch.isdigit() for ch in token)


def classify(text: str, names: list[str], *, cued_only: bool = True) -> dict[str, list[str]]:
    """Разбор названных токенов на три кучи. Развилка вынесена сюда (Т5).

    `cued_only=False` снимает фильтр рекомендательной фразы — это широкая
    сеть, которой мерится риск ложных, а не то, чем судит хук.
    """
    known_folds = {fold(n) for n in names}
    known_families = families(names)
    outside: dict[str, None] = {}
    unsure: dict[str, None] = {}
    for sentence in SENTENCE.split(countable_text(text)):
        if cued_only and not CUES.search(sentence):
            continue
        for match in TOKEN.finditer(sentence):
            token = match.group(0)
            if looks_like_a_model_name(token, known_folds, known_families):
                outside.setdefault(token, None)
            elif version_shaped(token, known_folds):
                unsure.setdefault(token, None)
    return {"outside": sorted(outside), "unsure": sorted(unsure)}


def outside_base(text: str, names: list[str], *, cued_only: bool = True) -> list[str]:
    """Имена, названные в рекомендательной фразе, которых база не знает."""
    return classify(text, names, cued_only=cued_only)["outside"]


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


def unknown_name_note(token: str, names: list[str]) -> str:
    """Что сказать про имя, которого база не знает. Е1: разрешение имени берётся
    у `studio/selfrag/modelnames.resolve`, второго такого здесь не заводится.

    Формулировка — не косметика. «Такой модели нет» — утверждение о МИРЕ, на
    которое у нас нет права: база собрана нами и заведомо неполна. Право у нас
    есть ровно на одно утверждение — «мы не смотрели».
    """
    got = resolve(token, names)
    if got.reason == RESOLVED:
        return f"{token}: база знает это имя как {got.canonical}"
    if got.reason != NOT_IN_BASE:
        return f"{token}: {got.note}"
    close = f"; близкие имена базы: {', '.join(got.suggestions)}" if got.suggestions else ""
    return f"{token}: в базе не искали — сюда нечего было спросить{close}"


def judge(answer: str, asked: list[str], names: list[str]) -> dict[str, Any]:
    """Вердикт по уже прочитанному следу. Отдельная функция ради Т5 и И1.

    Имя из ответа попадает в одну из ТРЁХ куч, и они не сливаются (Р1):

    * база это имя знает — тогда спрашивали о нём или нет (старая проверка);
    * база не знает, но имя похоже на настоящее — «не в базе» НЕ ЕСТЬ «не
      существует», и лечится это поиском, а не отказом;
    * разобрать не смогли — форма `слово-цифры` без известного семейства
      (`torch-2.4`, `apache-2.0`). Тихо посчитать такое чистым нельзя.

    Второй род опаснее первого: у моделей около пятой части предлагаемых имён
    не существует (Ц10), и выдуманное звучит ровно так же уверенно.
    """
    named = recommended_names(answer, names)
    asked_low = {a.strip().lower() for a in asked}
    unasked = [n for n in named if n not in asked_low]
    split = classify(answer, names)
    unknown, unsure = split["outside"], split["unsure"]
    notes = []
    if unasked:
        notes.append(f"названо без запроса: {', '.join(unasked)}")
    if unknown:
        notes.append(
            "названо имя вне базы: " + "; ".join(unknown_name_note(t, names) for t in unknown)
        )
    if unsure:
        notes.append(f"разобрать не смогли: {', '.join(unsure)}")
    if unasked or unknown:
        outcome = FAIL
    elif unsure:
        outcome = UNMEASURED
    else:
        outcome = PASS
    return {
        "outcome": outcome,
        "checked": len(named) + len(unknown),
        "violations": len(unasked) + len(unknown),
        "unmeasured": len(unsure),
        "named": named,
        "unasked": unasked,
        "outside_base": unknown,
        "unsure": unsure,
        "note": (
            ". ".join(notes)
            if notes
            else f"рекомендательно названо {len(named)} имён, все спрошены и все из базы"
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
            "outside_base": [],
            "unsure": [],
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
            "outside_base": [],
            "unsure": [],
            "note": trace["note"],
        }
    return judge(trace["answer"], trace["asked"], model_names(facts_path))


def render(result: dict[str, Any]) -> str:
    """Строка отчёта. Р2: числа рядом с исходом, а не вместо него."""
    return (
        f"[названо-но-не-спрошено] исход: {result['outcome']}; "
        f"проверено {result['checked']}, нарушений {result['violations']} "
        f"(не спрошено {len(result.get('unasked') or [])}, "
        f"вне базы {len(result.get('outside_base') or [])}), "
        f"не смогли {result['unmeasured']}. {result['note']}"
    )
