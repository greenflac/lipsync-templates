#!/usr/bin/env python3
"""One model, one id. Merge the spellings that split a model's claims in two.

    python scripts/merge_model_ids.py             # план, НИЧЕГО не пишет (по умолчанию)
    python scripts/merge_model_ids.py --apply     # применить план к базе
    python scripts/merge_model_ids.py --check     # red if a merged spelling returns

ДОПОЛНЕНО 2026-10-14 (аудит ae94057). Кроме таблицы `MERGES` ниже, план
теперь берёт ВСЕ группы, которые сводит свёртка имени
(`studio/selfrag/modelnames.py`): после её усиления (`X.0` = `X`,
`i2v` = `image-to-video`, вендор/площадка впереди, курируемые переписи) на
живой базе таких групп 44, из них 21 новая — `seedance-2.0`/`seedance2`,
`imagen-4`/`imagen-4.0`, `minimax-h3-i2v`/`minimax-h3-image-to-video`,
`veo-3.1-i2v`/`veo3.1-image-to-video`, `eleven_v3`/`elevenlabs-tts-eleven-v3`,
`wan-2.2-a14b-i2v`/`wan-v2.2-a14b-image-to-video` и т.д.; каждая проверена
чтением строк как одна модель. Каноническое написание группы —
`modelnames.canonical_spelling`: вендорское, если известно, иначе то, под
которым строк больше.

ПО УМОЛЧАНИЮ — СУХОЙ ПРОГОН. Раньше запуск без флагов писал в базу, а сухой
прогон надо было просить; теперь наоборот, потому что запись в append-only
журнал не откатывается.

КАК ПЕРЕНОСИТСЯ СТРОКА ГРУППЫ. Не через `record`, а КОПИЕЙ стоящей строки
(все поля — тир, даты, ноты, флаг чтения, `witnessed`, `contra`) с заменой
одного `model` и полем `asked_as` = прежнее написание; затем `withdraw`
прежней. `record` перепроверяет строку ПО НЫНЕШНИМ правилам и дописывает ноты
(«зонда в журнале нет», «хост закрыт политикой»), то есть переписал бы
происхождение — а переименование модели происхождения не меняет.

THE DEFECT, MEASURED 2026-08-27

The base held 211 model ids and five of them were really one model twice or
three times:

    eleven-v3(6), eleven_v3(1), elevenlabs-eleven-v3(4)
    eleven-flash-v2-5(4), eleven-flash-v2.5(1)
    eleven-multilingual-v2(3), elevenlabs-multilingual-v2(2)
    eleven-turbo-v2-5(1), elevenlabs-turbo-v2.5(1)
    gpt-image-2(13), gpt_image_2(1)

Nobody notices, because nothing goes red. What happens instead is that a
caller asking `model_advice("eleven-v3")` is answered from 6 facts while the
base holds 11, and `model_advice("eleven-turbo-v2.5")` is answered from ZERO
while the base holds two. MEASURED: 23 of 37 facts visible, 14 lost.

An honest negative result belongs here too (rule I6): merging the five groups
revealed NO hidden contradiction — contested pairs stayed at 14 before and
after. The cost of the split is invisibility, not a wrong answer, and saying
so is the difference between a measurement and a scare.

WHICH SPELLING WINS, AND WHY IT IS NOT A MATTER OF TASTE

The vendor's. Rule E2: at a disagreement between a label and the evidence,
believe the evidence. These ids appear inside the quotations already recorded
from elevenlabs.io — `eleven_v3`, `eleven_flash_v2_5`,
`eleven_multilingual_v2`, `eleven_turbo_v2_5`, underscores and all. That is
what their API accepts, so that is the id a claim about it is filed under.

`gpt-image-2` goes the other way for the same reason: OpenAI's own pages
write it with hyphens, and the single `gpt_image_2` row came from Runway's
OpenAPI document, where a reseller spells a key in its own house style.

HOW THE MERGE IS DONE

Through `record` and `withdraw`, never by editing the file. The log then
carries the correction with its reason, which is what makes it reviewable —
and re-running is a no-op, because `record` supersedes an identical row and
`withdraw` refuses what is already withdrawn.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import PASS  # noqa: E402

from studio.mcp import advice  # noqa: E402
from studio.selfrag import modelnames  # noqa: E402
from studio.selfrag.facts import DEFAULT_FACTS_PATH, claim_key, load_facts  # noqa: E402

#: spelling seen in the base -> the id its vendor uses. Every entry is a claim
#: about what a vendor calls its own model, and every one of them was read out
#: of a quotation already in the base rather than guessed (rule C10).
MERGES: dict[str, str] = {
    # ElevenLabs' API ids, quoted from elevenlabs.io/docs in the notes of the
    # rows already recorded. Underscores are theirs, not a typo.
    "eleven-v3": "eleven_v3",
    "elevenlabs-eleven-v3": "eleven_v3",
    "eleven-flash-v2.5": "eleven_flash_v2_5",
    "eleven-flash-v2-5": "eleven_flash_v2_5",
    "eleven-flash-v2": "eleven_flash_v2",
    "eleven-multilingual-v2": "eleven_multilingual_v2",
    "elevenlabs-multilingual-v2": "eleven_multilingual_v2",
    "eleven-multilingual-sts-v2": "eleven_multilingual_sts_v2",
    "eleven-turbo-v2-5": "eleven_turbo_v2_5",
    "elevenlabs-turbo-v2.5": "eleven_turbo_v2_5",
    "eleven-turbo-v2": "eleven_turbo_v2",
    "eleven-v3-conversational": "eleven_v3_conversational",
    # OpenAI writes this one with hyphens on its own pages; the underscore
    # spelling arrived from a reseller's OpenAPI document.
    "gpt_image_2": "gpt-image-2",
    # A SCOPE, not a model — `<family>-*` means "true of this vendor's line".
    # It has to carry the family the vendor's own ids use, or `class_claims`
    # can never match it: `elevenlabs-*` reaches nothing, because every id it
    # is about is spelled `eleven_...`.
    "elevenlabs-*": "eleven-*",
}

#: То же правило, но про ИМЯ АТРИБУТА, а не модели. Обнаружено 2026-08-31,
#: когда `ingest_hf.py` показал у Hunyuan атрибут `licence`, а записывали мы
#: везде `license`. ИЗМЕРЕНО по всей базе: 267 имён атрибутов, столкновение
#: ровно одно — `licence` (10 фактов) против `license` (9). Спросивший одно
#: написание не видит 9 фактов из 19.
#:
#: Побеждает `license` не по вкусу, а по свидетельству (правило Е2): именно так
#: поле называется в машиночитаемой карточке HuggingFace (`cardData.license`),
#: откуда теперь и приходит большинство этих фактов.
#:
#: Цена ошибки здесь выше средней: пропущенный факт о лицензии — это
#: research-only модель, уехавшая в продакшен.
ATTRIBUTE_MERGES: dict[str, str] = {
    "licence": "license",
}

WHY = (
    "merged into the id the vendor's own documentation uses; the same claim "
    "stands under that id. Two spellings of one model answer a caller from "
    "half its facts each."
)


def _plan(path: Path | None = None) -> list:
    """Every standing fact filed under a spelling that is not the canonical one."""
    rows = load_facts(path or DEFAULT_FACTS_PATH)
    группы = canonical_by_fold(rows)
    return [
        f for f in rows if f.model in MERGES or f.attribute in ATTRIBUTE_MERGES or f.model in группы
    ]


def canonical_by_fold(rows) -> dict[str, str]:
    """Написание -> каноническое, для каждой группы, которую сводит свёртка.

    Только написания, отличные от канонического; таблица `MERGES` главнее
    (вендорское свидетельство), поэтому её левые части здесь не повторяются.
    """
    счёт: dict[str, int] = {}
    for f in rows:
        счёт[f.model] = счёт.get(f.model, 0) + 1
    out: dict[str, str] = {}
    for names in modelnames.group(счёт).values():
        канон = modelnames.canonical_spelling(names, счёт)
        # Одиночка сводится, только если вендор назвал своё написание
        # (`ПРЕДПОЧТЕНИЕ`): `gemini_image3.1_flash` -> `nano-banana-2`.
        if len(names) < 2 and канон in names:
            continue
        for name in names:
            if name != канон and name not in MERGES:
                out[name] = канон
    return out


def canonical_of(fact, группы: dict[str, str] | None = None) -> tuple[str, str]:
    """Под какими именем модели и именем атрибута факт должен стоять."""
    model = MERGES.get(fact.model) or (группы or {}).get(fact.model, fact.model)
    return model, ATTRIBUTE_MERGES.get(fact.attribute, fact.attribute)


def _check(path: Path | None = None) -> int:
    stale = _plan(path)
    for fact in stale[:10]:
        print(f"  всё ещё под чужим написанием: {fact.model}.{fact.attribute}")
    группы = canonical_by_fold(load_facts(path or DEFAULT_FACTS_PATH))
    print(f"\nпроверено {len(MERGES)} написаний имени модели по таблице")
    print(f"проверено {len(группы)} написаний, сводимых свёрткой, ещё не слитых")
    print(f"проверено {len(ATTRIBUTE_MERGES)} написаний имени атрибута")
    print(f"не слито {len(stale)}")
    return 1 if stale else 0


def стоящие_строки(path: Path) -> dict[tuple[str, str, str, str], dict]:
    """Ключ утверждения -> СЫРАЯ последняя строка о нём, как она записана.

    Тем же правилом, что `facts.load_facts` (последняя строка о ключе
    побеждает, отзыв убирает), но со всеми полями строки — переносится
    происхождение целиком, а не то, что знает датакласс `Fact`.
    """
    стоит: dict[tuple[str, str, str, str], dict | None] = {}
    if not path.is_file():
        return {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("//"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict) or not row.get("model") or not row.get("attribute"):
            continue
        key = claim_key(
            str(row["model"]),
            str(row["attribute"]),
            str(row.get("value", "")),
            str(row.get("source_url", "")),
        )
        стоит[key] = None if row.get("withdrawn") else row
    return {k: v for k, v in стоит.items() if v is not None}


def перенести(fact, canonical: str, attribute: str, path: Path) -> tuple[str, dict | None]:
    """Дописать копию стоящей строки под каноническими именами. (исход, строка).

    Исход: `written` — дописана; `already` — такое утверждение под каноническим
    именем уже стоит (переносить нечего, остаётся снять дубль); `missing` —
    строки нет (кто-то снял её между планом и переносом).
    """
    стоит = стоящие_строки(path)
    сырая = стоит.get(claim_key(fact.model, fact.attribute, fact.value, fact.source_url))
    if сырая is None:
        return "missing", None
    if claim_key(canonical, attribute, fact.value, fact.source_url) in стоит:
        return "already", None
    копия = dict(сырая)
    копия["model"] = canonical
    копия["attribute"] = attribute
    if canonical != fact.model and not копия.get("asked_as"):
        копия["asked_as"] = fact.model
    if attribute != fact.attribute and not копия.get("asked_as_attribute"):
        копия["asked_as_attribute"] = fact.attribute
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(копия, ensure_ascii=False) + "\n")
    return "written", копия


def счёт_базы(path: Path) -> dict[str, int]:
    """Числа до и после (Р2): строк в файле, стоящих утверждений, имён, групп."""
    строк = (
        sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
        if path.is_file()
        else 0
    )
    rows = load_facts(path)
    имена = {f.model for f in rows}
    return {
        "строк в файле": строк,
        "стоящих утверждений": len(rows),
        "имён моделей": len(имена),
        "групп из >1 написания": sum(1 for v in modelnames.group(имена).values() if len(v) > 1),
    }


ПОЧЕМУ_НЕ_ПЕРЕНОС = (
    "строка не проходит НЫНЕШНЮЮ проверку записи и под своим прежним именем тоже: "
    "перенос тут ни при чём, чинить надо саму строку"
)


def отказ_из_за_самой_строки(fact, пробник: Path | None = None) -> bool:
    """Отказ пришёл от переноса — или строка сама не проходит проверку записи?

    ЗАЧЕМ (найдено независимой проверкой 2026-09-06). Правила записи строже
    правил, действовавших когда строка легла в базу: с `7900a37` ступень `paper`
    требует адреса, по которому статью перепроверить. Такая старая строка не
    переносится НИКОГДА — и без этой развилки давала жёсткое «НЕ ПЕРЕНЕСЕНО» и
    код 1, то есть сведение имён навсегда красное по причине, к сведению имён
    отношения не имеющей. Это Р1: третий исход не сворачивается в «не годно».

    Проверяется наблюдением, а не догадкой (Е2): тот же факт записывается под
    ПРЕЖНИМ именем в ОТДЕЛЬНЫЙ файл. Отказали оба — дело в строке.
    """
    with tempfile.TemporaryDirectory() as каталог:
        итог = advice.record(
            fact.model,
            fact.attribute,
            fact.value,
            fact.source_url,
            fact.tier,
            fact.stated_on,
            note=fact.note,
            fix=fact.fix,
            read_directly=fact.read_directly,
            path=пробник or Path(каталог) / "probe.jsonl",
        )
    return итог["outcome"] != PASS


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="сухой прогон (и так по умолчанию)")
    parser.add_argument("--apply", action="store_true", help="применить план к базе")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--path", type=Path, default=None, help="другая база (для проверки)")
    args = parser.parse_args(argv)
    target = Path(args.path or DEFAULT_FACTS_PATH)

    if args.check:
        return _check(target)

    сухой = not args.apply or args.dry_run
    план = _plan(target)
    группы = canonical_by_fold(load_facts(target))
    до = счёт_базы(target)
    print("ПЛАН" + (" (сухой прогон: ничего не записано; --apply применит)" if сухой else ""))
    по_парам: dict[tuple[str, str], int] = {}
    for fact in план:
        canonical, attribute = canonical_of(fact, группы)
        по_парам[(fact.model, canonical)] = по_парам.get((fact.model, canonical), 0) + 1
    for (было, стало), n in sorted(по_парам.items()):
        print(f"  {было} -> {стало}  ({n} утв.)")
    атрибуты = sum(1 for f in план if f.attribute in ATTRIBUTE_MERGES)
    if атрибуты:
        print(f"  + имён атрибутов к сведению: {атрибуты}")

    moved = kept = failed = не_смогли = 0
    if not сухой:
        for fact in план:
            canonical, attribute = canonical_of(fact, группы)
            исход, _row = перенести(fact, canonical, attribute, target)
            if исход == "missing":
                не_смогли += 1
                print(f"  НЕ СМОГЛИ {fact.model}.{fact.attribute}: строки уже нет в базе")
                continue
            removed = advice.withdraw(
                fact.model, fact.attribute, fact.value, fact.source_url, WHY, path=target
            )
            if removed["outcome"] != PASS:
                failed += 1
                print(f"  НЕ СНЯТО {fact.model}.{fact.attribute}: {removed['note'][:120]}")
                continue
            if исход == "already":
                kept += 1
            moved += 1
    после = счёт_базы(target) if not сухой else до

    print(f"\nнаписаний в таблице {len(MERGES) + len(ATTRIBUTE_MERGES)}")
    print(f"написаний, сводимых свёрткой {len(группы)}")
    print(f"утверждений в плане {len(план)}")
    print(f"перенесено {moved}")
    print(f"из них уже стояло под каноническим id {kept}")
    print(f"не смогли {не_смогли}")
    print(f"не перенесено {failed}")
    for ключ in до:
        print(f"{ключ}: до {до[ключ]}, после {после[ключ]}")
    return 1 if failed else (2 if не_смогли else 0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
