#!/usr/bin/env python3
"""Цены медиамоделей и даты снятия из таблицы LiteLLM.

    python scripts/import_litellm_prices.py            # dry-run
    python scripts/import_litellm_prices.py --apply    # записать через advice.record
    python scripts/import_litellm_prices.py --check    # офлайн: связность записанного

ЧТО ЭТО ЗА ИСТОЧНИК. `model_prices_and_context_window.json` в репозитории
BerriAI/litellm — сводная таблица цен, которую прокси LiteLLM использует для
подсчёта расходов. Ключ — модель У КОНКРЕТНОГО ПРОВАЙДЕРА (`gemini/veo-3.1-…`,
`fal_ai/…`, `azure/…`), то есть цена — это цена ПЕРЕПРОДАЖИ у этого
провайдера, а не вендорский прайс. Поэтому:

  * атрибут несёт провайдера в имени: `price_per_second_usd_via_gemini`.
    Цена Azure и цена OpenAI за одну модель — разные утверждения о разных
    местах, и под одним именем `FactStore` читал бы их как спор источников;
  * условия (разрешение, качество, размер) сводятся в ОДНО значение на
    (модель, провайдер, единица): строки одного адреса с разными значениями
    тоже читались бы как спор;
  * тир решает адрес (`source_hosts.classify`). На 2026-10-14
    `raw.githubusercontent.com/BerriAI/` в таблице хостов не числился, и
    строки ложились ступенью `blog`. С 2026-10-15 организация BerriAI
    объявлена ПОРТАЛОМ (прокси, который запускает чужие модели по их API и
    публикует, что за запуск берут) — таблицей хостов, а не этим скриптом;
    уже записанные строки переведены `scripts/retier_facts.py` дописыванием.
    Портал ниже вендора: прайс LiteLLM — пересказ чужого прайса.

`deprecation_date` пишется как `deprecation_date_via_<провайдер>`: дата, когда
провайдер снимает модель, — это жизненный цикл ТАМ, а не у модели вообще.

ДАТА ИСТОЧНИКА — дата последнего коммита файла (GitHub API), а не сегодняшняя:
сегодняшняя дата у старой цены выдавала бы её за свежую.

ОХВАТ. Только режимы `image_generation`, `image_edit`, `video_generation`,
`audio_speech` и только модели семейств, о которых студию спрашивают (те же,
что у `sync_fal_catalog.py`), плюс модели, уже известные базе.

ТРИ ИСХОДА (Р1): 0 годно / 1 не годно / 2 не смогли.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from lipsync.fork_identity import FAIL, PASS, UNMEASURED  # noqa: E402
from scripts import sync_fal_catalog as fal  # noqa: E402
from studio.selfrag import modelnames, source_hosts  # noqa: E402

ИСТОЧНИК = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/model_prices_and_context_window.json"
)
КОММИТЫ = (
    "https://api.github.com/repos/BerriAI/litellm/commits"
    "?path=model_prices_and_context_window.json&per_page=1"
)
РЕЖИМЫ: frozenset[str] = frozenset(
    {"image_generation", "image_edit", "video_generation", "audio_speech"}
)

#: Метка ноты строк этого канала: по ней `--check` и отзыв узнают свои строки.
МЕТКА = "LiteLLM model_prices_and_context_window.json"

#: Поле стоимости -> «за что» в имени атрибута (его читает `studio/pricing.py`).
#: Токенные поля не берутся: у медиамоделей это цена промпта, а не результата,
#: и рядом с ценой за картинку она читалась бы как цена картинки.
ПОЛЯ: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"^output_cost_per_image$"), "image"),
    (re.compile(r"^input_cost_per_image$"), "input_image"),
    (re.compile(r"^output_cost_per_video_per_second$"), "second"),
    (re.compile(r"^output_cost_per_second(?:_(\w+))?$"), "second"),
    (re.compile(r"^input_cost_per_character$"), "character"),
)

КАЧЕСТВО: frozenset[str] = frozenset({"low", "medium", "high", "xhigh", "max", "standard", "hd"})
РАЗМЕР = re.compile(r"^\d+-x-\d+$")
ХВОСТЫ = re.compile(
    r"(?:-generate)?(?:-preview|-001|-002|-latest)$|-\d{4}-\d{2}-\d{2}$|-\d{8}$", re.I
)
#: Вендорские приставки пути, которые провайдеры ставят перед именем модели.
ВЕНДОРЫ: frozenset[str] = frozenset(
    {"openai", "google", "bytedance", "minimax", "xai", "alibaba", "black-forest-labs"}
)

#: Корни семейств охвата. Пересекается с таблицей `sync_fal_catalog.СЕМЕЙСТВА`
#: по смыслу, но здесь имена провайдеров (`veo-3.1-fast-generate-preview`), а не
#: пути портала, поэтому сверяется свёрнутое имя.
КОРНИ: tuple[str, ...] = (
    "veo-3.1",
    "kling",
    "seedance",
    "minimax-h3",
    "hailuo",
    "wan2.6",
    "wan2.7",
    "wan3",
    "wan-2.6",
    "wan-2.7",
    "wan-3",
    "ltx",
    "gpt-image",
    "nano-banana",
    "gemini-3-pro-image",
    "gemini-3.1-flash-image",
    "gemini-2.5-flash-image",
    "flux-2",
    "flux-3",
    "seedream",
    "happyhorse",
    "happy-horse",
    "grok-imagine",
    "omnihuman",
    "eleven",
    "speech-2.6",
    "speech-2.8",
    "sora",
    "imagen-4",
)


@dataclass(frozen=True)
class Строка:
    ключ: str
    провайдер: str
    модель_пути: str
    условие: str
    поля: dict[str, Any]


def разобрать_ключ(ключ: str, провайдер: str) -> tuple[str, str]:
    """(путь модели, условие). Условие — качество и размер из ключа."""
    куски = [к for к in ключ.split("/") if к]
    if куски and куски[0] in (провайдер, провайдер.replace("_", "-")):
        куски = куски[1:]
    условие: list[str] = []
    остаток: list[str] = []
    for к in куски:
        if к in КАЧЕСТВО and not остаток:
            условие.append(к)
        elif РАЗМЕР.match(к) and not остаток:
            условие.append(к.replace("-x-", "x"))
        else:
            остаток.append(к)
    return "/".join(остаток), " ".join(условие)


def имя_модели(путь: str, провайдер: str) -> tuple[str, str]:
    """(имя-кандидат, нота) для пути модели у провайдера."""
    if провайдер == "fal_ai":
        # Путь у fal_ai — это id эндпоинта портала: имя строится тем же
        # правилом, что у `sync_fal_catalog` (Е1: одно имя на эндпоинт).
        эндпоинт = путь if "/" in путь else f"fal-ai/{путь}"
        return fal.имя_по_таблице(эндпоинт)
    куски = [к for к in путь.split("/") if к]
    while len(куски) > 1 and куски[0].lower() in ВЕНДОРЫ:
        куски = куски[1:]
    # Регистр не различает модели (`FLUX.1-Kontext-pro` = `flux.1-kontext-pro`),
    # а слой имён при совпадении без учёта регистра оставляет спрошенное
    # написание — и `merge_model_ids --check` видит второе написание.
    имя = "-".join(куски).lower()
    было = имя
    for _ in range(3):
        имя = ХВОСТЫ.sub("", имя)
    return имя, ("" if имя == было else f"имя у провайдера {было!r}, снят хвост выпуска")


def в_охвате(имя: str, известные: set[str]) -> bool:
    свёрнуто = modelnames.fold(имя)
    if свёрнуто in известные:
        return True
    return any(свёрнуто.startswith(modelnames.fold(к)) for к in КОРНИ)


def строки(таблица: dict[str, Any]) -> list[Строка]:
    out: list[Строка] = []
    for ключ, поля in таблица.items():
        if not isinstance(поля, dict) or поля.get("mode") not in РЕЖИМЫ:
            continue
        провайдер = str(поля.get("litellm_provider") or "").strip()
        if not провайдер:
            continue
        путь, условие = разобрать_ключ(ключ, провайдер)
        out.append(Строка(ключ, провайдер, путь, условие, поля))
    return out


def _сумма(число: float) -> str:
    return f"${число:.6f}".rstrip("0").rstrip(".")


Разрешитель = Callable[[str], tuple[str, str]]


@dataclass
class Находка:
    модель: str
    атрибут: str
    значение: str
    нота: str


def находки(
    таблица: dict[str, Any], известные: set[str], разрешитель: Разрешитель
) -> tuple[list[Находка], dict[str, int]]:
    """Сводит строки таблицы в находки: одна на (модель, провайдер, единица)."""
    счёт = {"строк_медиа": 0, "в_охвате": 0, "вне_охвата": 0}
    цены: dict[tuple[str, str], dict[str, str]] = {}
    ноты: dict[tuple[str, str], set[str]] = {}
    даты: dict[tuple[str, str], set[str]] = {}
    for с in строки(таблица):
        счёт["строк_медиа"] += 1
        кандидат, нота_имени = имя_модели(с.модель_пути, с.провайдер)
        if not кандидат or not в_охвате(кандидат, известные):
            счёт["вне_охвата"] += 1
            continue
        модель, отказ = разрешитель(кандидат)
        if отказ:
            модель = кандидат
        счёт["в_охвате"] += 1
        провайдер = re.sub(r"[^a-z0-9]+", "_", с.провайдер.lower()).strip("_")
        for поле, значение in sorted(с.поля.items()):
            if not isinstance(значение, (int, float)) or isinstance(значение, bool):
                continue
            for образец, за in ПОЛЯ:
                м = образец.match(поле)
                if not м:
                    continue
                атрибут = f"price_per_{за}_usd_via_{провайдер}"
                уточнение = " ".join(
                    ч for ч in (с.условие, (м.group(1) if м.groups() else "") or "") if ч
                )
                ключ = (модель, атрибут)
                цены.setdefault(ключ, {})[уточнение] = _сумма(float(значение))
                ноты.setdefault(ключ, set()).add(f"{с.ключ} [{поле}]")
                if нота_имени:
                    ноты[ключ].add(нота_имени)
                break
        снятие = str(с.поля.get("deprecation_date") or "").strip()
        if снятие:
            ключ = (модель, f"deprecation_date_via_{провайдер}")
            даты.setdefault(ключ, set()).add(снятие)
            ноты.setdefault(ключ, set()).add(с.ключ)
    out: list[Находка] = []
    for (модель, атрибут), по_условию in sorted(цены.items()):
        части = [
            f"{условие} {сумма}" if условие else сумма
            for условие, сумма in sorted(по_условию.items(), key=lambda п: (п[0] != "", п[0]))
        ]
        значение = "; ".join(части)
        if len(значение) > 900:
            значение = значение[:880].rsplit(";", 1)[0] + "; …"
        out.append(Находка(модель, атрибут, значение, _нота(ноты[(модель, атрибут)])))
    for (модель, атрибут), набор in sorted(даты.items()):
        out.append(
            Находка(модель, атрибут, ", ".join(sorted(набор)), _нота(ноты[(модель, атрибут)]))
        )
    return out, счёт


def _нота(ключи: set[str]) -> str:
    показ = sorted(ключи)
    return (
        f"{МЕТКА}: ключи "
        + ", ".join(показ[:6])
        + (f" и ещё {len(показ) - 6}" if len(показ) > 6 else "")
        + ". Цена перепродажи у провайдера из ключа, не вендорский прайс"
    )


# --- сеть --------------------------------------------------------------------


def прочитать(url: str, max_bytes: int) -> dict[str, Any]:
    from studio.mcp import fetch

    return fetch.fetch(url, why_wanted="цены медиамоделей из таблицы LiteLLM", max_bytes=max_bytes)


def дата_источника(получатель: Callable[[str, int], dict[str, Any]]) -> str:
    """Дата последнего коммита файла. Пусто — GitHub API не ответил."""
    ответ = получатель(КОММИТЫ, 200_000)
    if ответ.get("outcome") != PASS:
        return ""
    try:
        тело = json.loads(str(ответ.get("text") or ""))
        return str(тело[0]["commit"]["committer"]["date"])[:10]
    except (ValueError, KeyError, IndexError, TypeError):
        return ""


# --- запись ------------------------------------------------------------------


def записать(находки_: list[Находка], stated_on: str, путь: Path | None = None) -> dict[str, Any]:
    from studio.mcp import advice
    from studio.selfrag.facts import load_facts

    итог: dict[str, Any] = {"записано": 0, "не_изменилось": 0, "отозвано": 0, "отказано": 0}
    по_атрибутам: dict[str, int] = {}
    причины: dict[str, int] = {}
    тиры: dict[str, int] = {}
    новые: set[str] = set()
    факты = load_facts(путь) if путь else load_facts()
    до = {ф.model for ф in факты}
    for н in находки_:
        тир = source_hosts.classify(
            н.модель, ИСТОЧНИК, vendor_tier="vendor", portal_tier="portal", blog_tier="blog"
        )
        имя, _ = advice.каноническое_имя(н.модель, путь, new_model=True)
        for ф in факты:
            if (
                ф.model == имя
                and ф.attribute == н.атрибут
                and ф.source_url == ИСТОЧНИК
                and ф.value != н.значение
                and str(ф.note or "").startswith(МЕТКА)
            ):
                ответ = advice.withdraw(
                    ф.model,
                    ф.attribute,
                    ф.value,
                    ф.source_url,
                    f"таблица LiteLLM на {stated_on} говорит {н.значение[:120]!r}",
                    path=путь,
                )
                if ответ.get("outcome") == PASS:
                    итог["отозвано"] += 1
        ответ = advice.record(
            н.модель,
            н.атрибут,
            н.значение,
            ИСТОЧНИК,
            тир,
            stated_on,
            note=н.нота,
            read_directly=True,
            new_model=True,
            path=путь,
        )
        if ответ.get("outcome") != PASS:
            итог["отказано"] += 1
            причина = str(ответ.get("note") or "")[:100]
            причины[причина] = причины.get(причина, 0) + 1
            continue
        if ответ.get("written") is None:
            итог["не_изменилось"] += 1
            continue
        итог["записано"] += 1
        факты = load_facts(путь) if путь else load_facts()
        тиры[тир] = тиры.get(тир, 0) + 1
        по_атрибутам[н.атрибут] = по_атрибутам.get(н.атрибут, 0) + 1
        записанная = str((ответ.get("written") or {}).get("model") or "")
        if записанная and записанная not in до:
            новые.add(записанная)
    итог.update(по_атрибутам=по_атрибутам, причины=причины, тиры=тиры, новые_модели=sorted(новые))
    return итог


# --- офлайн-проверка ------------------------------------------------------------


def проверить_собранное(факты: Any = None) -> dict[str, Any]:
    """Офлайн: строки канала связны. Сети здесь нет.

    Нарушения: тир не тот, что даёт адрес; дата не ISO или в будущем; атрибут
    без провайдера в имени; один (модель, атрибут) с двумя значениями разом.
    """
    from studio.selfrag.facts import load_facts

    свои = [
        ф
        for ф in (load_facts() if факты is None else факты)
        if ф.source_url == ИСТОЧНИК and str(ф.note or "").startswith(МЕТКА)
    ]
    if not свои:
        return {
            "outcome": UNMEASURED,
            "checked": 0,
            "violations": 0,
            "unmeasured": 1,
            "note": "в базе нет ни одной строки этого канала — проверять нечего",
        }
    нарушения: list[str] = []
    значения: dict[tuple[str, str], set[str]] = {}
    for ф in свои:
        тир = source_hosts.classify(
            ф.model, ф.source_url, vendor_tier="vendor", portal_tier="portal", blog_tier="blog"
        )
        if ф.tier != тир:
            нарушения.append(f"{ф.model}.{ф.attribute}: тир {ф.tier!r}, адрес даёт {тир!r}")
        try:
            if date.fromisoformat(str(ф.stated_on)) > date.today():
                нарушения.append(f"{ф.model}.{ф.attribute}: дата {ф.stated_on} в будущем")
        except ValueError:
            нарушения.append(f"{ф.model}.{ф.attribute}: дата {ф.stated_on!r} не ISO")
        if "_via_" not in ф.attribute:
            нарушения.append(f"{ф.model}.{ф.attribute}: в имени атрибута нет провайдера")
        значения.setdefault((ф.model, ф.attribute), set()).add(ф.value)
    for (модель, атрибут), набор in sorted(значения.items()):
        if len(набор) > 1:
            нарушения.append(f"{модель}.{атрибут}: {len(набор)} значения разом")
    return {
        "outcome": FAIL if нарушения else PASS,
        "checked": len(свои),
        "violations": len(нарушения),
        "unmeasured": 0,
        "note": f"строк канала {len(свои)}, моделей {len({ф.model for ф in свои})}"
        + ("\n  " + "\n  ".join(нарушения[:10]) if нарушения else ""),
    }


def _разрешитель_базы(кандидат: str) -> tuple[str, str]:
    return fal.имя_как_в_базе(кандидат)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--apply", action="store_true", help="записать находки через advice.record")
    parser.add_argument("--check", action="store_true", help="без сети: связность записанного")
    parser.add_argument(
        "--from", dest="source", type=Path, help="локальная копия таблицы (без сети)"
    )
    parser.add_argument("--stated-on", default="", help="дата источника, если GitHub API молчит")
    args = parser.parse_args(argv)

    if args.check:
        итог = проверить_собранное()
        print(итог["note"])
        print(
            f"\nпроверено {итог['checked']}\nнарушений {итог['violations']}\n"
            f"не смогли {итог['unmeasured']}"
        )
        return 0 if итог["outcome"] == PASS else (1 if итог["outcome"] == FAIL else 2)

    if args.source:
        текст = args.source.read_text(encoding="utf-8")
    else:
        ответ = прочитать(ИСТОЧНИК, 8_000_000)
        if ответ.get("outcome") != PASS:
            print(f"не смогли: {ответ.get('note')}")
            return 2
        текст = str(ответ.get("text") or "")
    try:
        таблица = json.loads(текст)
    except ValueError as ошибка:
        print(f"не годно: таблица не JSON ({ошибка})")
        return 1
    stated_on = args.stated_on or дата_источника(прочитать) or date.today().isoformat()

    from studio.selfrag.facts import load_facts

    известные = {modelnames.fold(ф.model) for ф in load_facts()}
    найдено, счёт = находки(таблица, известные, _разрешитель_базы)
    print(
        f"медийных строк {счёт['строк_медиа']}, в охвате {счёт['в_охвате']}, "
        f"вне охвата {счёт['вне_охвата']}; находок {len(найдено)}; дата источника {stated_on}"
    )
    if args.apply:
        итог = записать(найдено, stated_on)
        print(
            f"записано {итог['записано']}, не изменилось {итог['не_изменилось']}, "
            f"отозвано прежних {итог['отозвано']}, отказано {итог['отказано']}; тиры {итог['тиры']}"
        )
        for а, ч in sorted(итог["по_атрибутам"].items()):
            print(f"  {а}: {ч}")
        print(f"новых моделей: {len(итог['новые_модели'])}")
        for причина, ч in sorted(итог["причины"].items(), key=lambda п: -п[1]):
            print(f"  отказ x{ч}: {причина}")
    else:
        for н in найдено[:80]:
            print(f"  {н.модель[:30]:32} {н.атрибут:38} {н.значение[:60]}")
        print("(dry-run: ничего не записано; --apply пишет)")
    print(f"\nпроверено {счёт['строк_медиа']}\nнарушений 0\nне смогли 0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
