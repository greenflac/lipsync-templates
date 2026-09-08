"""Поиск фактов о моделях СЛОВАМИ ЗАДАЧИ, а не именем модели.

ЗАЧЕМ ЭТОТ МОДУЛЬ СУЩЕСТВУЕТ

ИЗМЕРЕНО 2026-08-31: `grep -c model_facts studio/knowledge.py` даёт ноль. В
индексе извлечения 13 438 записей шести полок, и фактов о моделях среди них
нет. Значит факт достаётся ИМЕНЕМ МОДЕЛИ, а задача приходит СЛОВАМИ оператора.
Это разные ключи, и моста между ними не было.

Цена измерима на живом вопросе владельца — «заменить персонажа, сохранив
цветокор и освещение». В базе лежит `wan-animate-replace`: «replacing the
original character while preserving the scene's lighting and color tone».
Дословный ответ. Достать его можно было, только угадав имя модели заранее, то
есть уже имея ответ.

ПОЧЕМУ ОТДЕЛЬНЫЙ МОДУЛЬ, А НЕ СЕДЬМАЯ ПОЛКА В knowledge.py

Решение владельца 2026-08-31 по правилу Ц2: у `studio/knowledge.py` другой
писатель, и его не трогают. Цена названа вслух: в репозитории появляется
второй индексатор, и это риск против Е1 — два способа искать по тексту. Он
принимается сознательно, потому что подмести чужую незаконченную работу уже
однажды стоило дороже.

ЧТО ЗДЕСЬ НЕ ДЕЛАЕТСЯ НАРОЧНО

Не ранжируется «лучшая модель». Возвращаются ФАКТЫ, каждый со своим тиром,
датой и источником, и решение остаётся за тем, кто читает. Индекс, который
сам выбирает победителя, прячет от читателя, на чём основан выбор.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence

from studio.selfrag.facts import Fact, load_facts

#: Слова, которые есть в любом тексте и потому ничего не различают. Список
#: короткий нарочно: настоящую фильтрацию делает IDF, а это только страховка
#: от самых частых служебных слов двух языков, на которых пишут в этой базе.
STOP = frozenset(
    """а и в во не что он на я с со как а то все она так его но да ты к у же вы за бы
    по её мне было вот от меня еще нет о из ему теперь когда даже ну вдруг ли если уже
    или ни быть был него до вас нибудь опять уж вам ведь там потом себя ничего ей может
    они тут где есть надо ней для мы тебя их чем была сам чтоб без будто чего раз тоже
    себе под будет ж тогда кто этот того потому этого какой совсем ним здесь этом один
    почти мой тем чтобы нее сейчас были куда зачем всех никогда можно при наконец два об
    другой хоть после над больше тот через эти нас про всего них какая много разве три
    эту моя впрочем хорошо свою этой перед иногда лучше чуть том нельзя такой им более
    всегда конечно всю между
    the a an and or of to in on for with is are was were be been it its this that these
    those as at by from not no but if then than so such can may will would should
    """.split()
)

#: Ниже этого веса совпадение не считается попаданием. ВЫБРАНО: порог отсекает
#: документы, совпавшие ровно одним частым словом, и оставляет совпавшие редким.
#: Сторожится мутацией в обе стороны (правило Т1).
SCORE_FLOOR = 0.12

#: Сколько фактов возвращать по умолчанию. ВЫБРАНО 8: ответ на требование
#: читается человеком, и список длиннее экрана перестаёт быть ответом.
DEFAULT_K = 8

_WORD = re.compile(r"[a-zа-яё0-9][a-zа-яё0-9._-]*", re.I)


def tokens(text: str) -> list[str]:
    """Слова текста в нижнем регистре, без служебных.

    Точки и дефисы внутри слова СОХРАНЯЮТСЯ: `wan-2.2` и `max_seconds` —
    это термины, и разбивать их значит терять именно то, по чему ищут.
    """
    return [w for w in (m.group(0).lower() for m in _WORD.finditer(text or "")) if w not in STOP]


def haystack(fact: Fact) -> str:
    """Текст, по которому факт находится.

    Имя модели ВХОДИТ в стог: спрашивают и словами, и именем, и второе не
    должно перестать работать оттого, что заработало первое.
    """
    куски = [fact.model, fact.attribute.replace("_", " "), fact.value, fact.note, fact.fix]
    return " ".join(str(x) for x in куски if x)


@dataclass(frozen=True)
class Hit:
    """Один найденный факт и то, чем он найден."""

    fact: Fact
    score: float
    matched: tuple[str, ...]


class FactIndex:
    """Обратный индекс по фактам. Строится в памяти, сети не требует."""

    def __init__(self, facts: Sequence[Fact] | None = None, path: Path | None = None) -> None:
        self.facts: list[Fact] = list(
            facts if facts is not None else (load_facts(path) if path else load_facts())
        )
        self._postings: dict[str, list[int]] = defaultdict(list)
        self._lengths: list[int] = []
        for i, fact in enumerate(self.facts):
            слова = tokens(haystack(fact))
            self._lengths.append(len(слова) or 1)
            for слово in set(слова):
                self._postings[слово].append(i)

    def _idf(self, слово: str) -> float:
        """Редкое слово весит больше частого. Отсутствующее — ноль, не ошибка."""
        n = len(self.facts) or 1
        df = len(self._postings.get(слово, ()))
        if not df:
            return 0.0
        return math.log(1 + n / df)

    def search(self, text: str, *, k: int = DEFAULT_K, floor: float = SCORE_FLOOR) -> list[Hit]:
        """Факты, относящиеся к этому тексту. Пусто — честный ответ."""
        спрошено = tokens(text)
        if not спрошено:
            return []
        частоты = Counter(спрошено)
        очки: dict[int, float] = defaultdict(float)
        попало: dict[int, set[str]] = defaultdict(set)
        for слово, сколько in частоты.items():
            вес = self._idf(слово)
            if not вес:
                continue
            for i in self._postings[слово]:
                очки[i] += вес * сколько / math.sqrt(self._lengths[i])
                попало[i].add(слово)
        найдено = [
            Hit(self.facts[i], score, tuple(sorted(попало[i])))
            for i, score in очки.items()
            if score >= floor
        ]
        найдено.sort(key=lambda h: (-h.score, h.fact.model, h.fact.attribute))
        return найдено[:k]


def verdict(hits: Iterable[Hit], asked: str) -> dict[str, Any]:
    """Три исхода вместо двух (правило Р1).

    Пустая выдача — это `не смогли`, а НЕ `годно с нулём находок`. Прецедент в
    этом же репозитории: `retrieve()` на настоящем брифе владельца вернул
    `outcome: pass` при `examples: 0`, а честная нота о том, что не совпало
    ничего, лежала строкой ниже. Поле вердикта читают, ноту — нет.
    """
    строки = list(hits)
    if not str(asked or "").strip():
        return {
            "outcome": "could not measure",
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "спросили пустым текстом — искать нечего",
            "hits": [],
        }
    if not строки:
        return {
            "outcome": "could not measure",
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "ни один факт не превысил порог; база об этом молчит",
            "hits": [],
        }
    return {
        "outcome": "pass",
        "checked": len(строки),
        "violations": 0,
        "unmeasured": 0,
        "note": f"{len(строки)} факт(ов) выше порога, сильнейший — {строки[0].fact.model}",
        "hits": [
            {
                "model": h.fact.model,
                "attribute": h.fact.attribute,
                "value": h.fact.value,
                "tier": h.fact.tier,
                "stated_on": h.fact.stated_on,
                "source_url": h.fact.source_url,
                "score": round(h.score, 4),
                "matched": list(h.matched),
            }
            for h in строки
        ],
    }
