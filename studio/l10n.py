"""Язык ответа: ОДНА функция и ОДНА таблица на весь продукт.

ЗАЧЕМ (аудит 4-го круга, 2026-10-15). Английский бриф получал план, где
половина строк была по-русски: «цена не записана», «в брифе заказан…»,
«usd за megapixel», строка RESOLUTION, цитаты рисков; справка о модели на
английский вопрос несла русские ноты. Переводы жили россыпью: `x if англ
else y` в сотне мест планировщика, отдельная таблица форм, а у справки —
ничего. Каждая новая строка заговаривала по-русски, и заметить это было
нечем.

КАК ТЕПЕРЬ. Шаблоны строятся там, где строились (планировщик, смета,
валидатор, справка), а на ГРАНИЦЕ ответа весь словарь проходит через
`localise_payload(ответ, lang)`: по-английски — таблица `EN` (русская форма
шаблона -> английская), по-русски — таблица `RU` (английские шаблоны справки
-> русские). Проверяет это тест `studio/tests/test_localisation.py` на наборе
из ≥25 брифов и вопросов: в английском ответе нет кириллицы вне цитат, в
русском — английских шаблонных оборотов.

ЧТО НЕ ПЕРЕВОДИТСЯ, названо вслух:
  * КОДЫ (`CODE_KEYS`): имя шага, класс валидатора, причина, исход, ось
    вопроса. Это ключи для машин, такие же, как имена полей; человеческая
    форма тех же вещей — в `summary`, нотах и `что_дальше`.
  * ЦИТАТЫ из базы фактов — текст того, кто его записал. Цитата помечается
    «ёлочками» и не переписывается; к русской цитате в английском ответе
    добавляется короткий английский глосс `[ru: …]` (`gloss`). Источник
    цитаты стоит рядом: в поле (`source_url`, `tier`) или в скобках.
  * Слова, которые привёл сам заказчик (`brief`).
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from typing import Any

__all__ = [
    "CODE_KEYS",
    "EN",
    "EN_FRAGMENTS",
    "FACT_KEYS",
    "OUTCOME_EN",
    "RU",
    "TERMS_EN",
    "clip",
    "gloss",
    "lang_of",
    "leaks",
    "localise",
    "localise_payload",
    "quote_fact",
    "step_label_en",
]

CYR = re.compile(r"[А-Яа-яЁё]")
QUOTE = re.compile(r"«[^«»]*»")
GLOSS_MARK = "[ru:"


def lang_of(*texts: object) -> str:
    """`ru`, если в тексте есть хоть одна кириллическая буква, иначе `en`.

    Признак несимметричный нарочно (как `planner._есть_кириллица`): русский
    текст свободно несёт латиницу, английский кириллицы не несёт.
    """
    return "ru" if any(CYR.search(str(t or "")) for t in texts) else "en"


#: КОНСТАНТЫ-РЕШЕНИЯ ОБРЕЗКИ (`clip`). Конец предложения ищется в последних
#: 40 % отрезка, граница слова — в последней половине: дальше назад — и
#: обрезка съедает больше смысла, чем спасает.
CLIP_SENTENCE_SHARE = 0.6
CLIP_WORD_SHARE = 0.5
_КОНЕЦ_ФРАЗЫ = re.compile(r"[.;!?](?=\s)")


def clip(текст: object, n: int) -> str:
    """Текст не длиннее `n` знаков, обрезанный по фразе или слову, с «…».

    НАЙДЕНО валидатором 7-го круга: «(no faces on scre…» — обрезка посреди
    слова. Правило: конец фразы в последних 40 % — режем там; иначе последний
    пробел в последней половине; слово длиннее половины (URL) — режем как есть.
    Хвостовая пунктуация снимается; открытая «цитата» закрывается «…»».
    """
    t = " ".join(str(текст or "").split())
    if len(t) <= n:
        return t
    кусок = t[: max(n - 1, 1)]
    if not t[len(кусок)].isspace():
        фразы = [м.end() for м in _КОНЕЦ_ФРАЗЫ.finditer(кусок)]
        пробел = кусок.rfind(" ")
        if фразы and фразы[-1] >= len(кусок) * CLIP_SENTENCE_SHARE:
            кусок = кусок[: фразы[-1]]
        elif пробел >= len(кусок) * CLIP_WORD_SHARE:
            кусок = кусок[:пробел]
    кусок = кусок.rstrip(" ,;:—–-(«\"'")
    if кусок.count("«") > кусок.count("»"):
        return кусок[: n - 2].rstrip(" ,;:—–-(«\"'") + "…»"
    return кусок + "…"


#: КОДЫ: значения этих полей сравнивают программы, а не читают люди. Их
#: перевод сломал бы каждого потребителя, сравнивающего `step == "липсинк"`.
CODE_KEYS: frozenset[str] = frozenset(
    {
        "step",
        "requires",
        "produces",
        "replaces",
        "input_of_plan",
        "classes",
        "class",
        "reason",
        "axis",
        "outcome",
        "steps_without_price",
        "steps_without_cost",
        "source_url",
        "url",
        "model",
        "models",
        "from",
        "to",
        "tier",
        "best_tier",
        "kind",
        "attribute",
        "about",
        "scope",
        "role",
        "name",
        "how",
        "asked",
        "looked_up_as",
        "spellings",
        "variants",
        "community",
        "addons",
        "variant_roles",
        "contested",
        "possibly_stale",
        "languages",
        "near",
        "other_versions",
        "stated_on",
        "date",
        "id",
        "tied_with",
        "brief",
        "banned",
        "injection",
        "matched_words",
        "fired",
        "ignored_params",
        "paged",
    }
)

#: ЦИТАТЫ ИЗ БАЗЫ: значение факта, способ починки, свидетель. Источник —
#: соседнее поле того же словаря. `note` внутри `sources` — тоже цитата
#: (нота оператора к источнику), см. `localise_payload`.
FACT_KEYS: frozenset[str] = frozenset(
    {"value", "values", "fix", "witnessed", "forbids", "evidence_value", "failure_modes"}
)

#: Поля с английским близнецом (`note`/`note_en`): по-английски берётся близнец.
EN_SUFFIX = "_en"

#: ПОДДЕРЕВЬЯ-ДАННЫЕ: карточка реестра (`card`, её `quirks`, `parameters` —
#: запись того, кто её составил) и значения базы в сверке с ней (`base`).
#: Внутри всё — цитата: как `FACT_KEYS`.
FACT_SUBTREES: frozenset[str] = frozenset({"card", "base"})

#: ПОДДЕРЕВЬЯ ТРАНСПОРТА: `response_cap` — записка сервера ВЫЗЫВАЮЩЕЙ
#: ПРОГРАММЕ о том, как листать обрезанный ответ (как заголовок ответа), а не
#: часть ответа заказчику. Не переводится и не проверяется.
TRANSPORT_SUBTREES: frozenset[str] = frozenset({"response_cap"})


# ---------------------------------------------------------------------------
# Термины: имена шагов, артефактов, классов. Планировщик дописывает сюда свои
# имена шагов при импорте (`planner.ШАГ_ПО_АНГЛИЙСКИ`) — один словарь (Е1).
# ---------------------------------------------------------------------------

TERMS_EN: dict[str, str] = {
    # артефакты (`planner.ARTEFACT_*`)
    "видео_с_липсинком": "lip-synced video",
    "фоновый_звук": "background sound",
    "видео_апскейл": "upscaled video",
    "изображение_апскейл": "upscaled image",
    "видео_реставрация": "restored video",
    "видео_раскраска": "colorized video",
    "видео_интерполяция": "frame-interpolated video",
    "изображение_без_фона": "image with background removed",
    "видео_без_фона": "video with background removed",
    "расшифровка_текст": "transcript",
    "видео_правка": "edited video",
    "готовый_ролик": "finished clip",
    "бриф": "brief",
    "селфи": "selfie",
    "референс": "reference",
    "аудио": "audio",
    "видео": "video",
    "изображение": "image",
    "изображения": "images",
    "текст": "text",
    "музыка": "music",
    # классы валидатора (`pipeline.CLASS_*`)
    "нет_модели": "no model",
    "разрыв": "gap",
    "применимость": "applicability",
    "лицензия": "licence",
    "устарел": "stale",
    "противоречие": "contradiction",
    "способность": "capability",
    "юрисдикция": "jurisdiction",
    "креатив": "creative",
    # условия брифа (`pipeline.CONDITION_THEMES`)
    "текст в кадре": "text in frame",
    "руки": "hands",
    "несколько людей": "several people",
    "длинный ролик": "long clip",
    "быстрое движение": "fast motion",
    "стилизация": "stylisation",
    "поворот головы": "head turn",
    "темнота": "darkness",
    "пение": "singing",
    "сверхвысокое разрешение": "ultra-high resolution",
    # оси вопроса (`clarify`)
    "есть_ли_исходное_видео": "is there source footage",
}


# ---------------------------------------------------------------------------
# EN: русская форма шаблона -> английская. Порядок важен: длинные обороты
# раньше коротких. Цитаты «…» таблица не трогает (см. `localise`).
# ---------------------------------------------------------------------------

_N = r"(\d[\d .,]*)"
_W = r"([\w.\-/]+)"

EN: tuple[tuple[str, str], ...] = (
    # --- просев брифа и пустой бриф (studio/mcp/screen.py, server.py)
    (r"в тексте нет ни одного слова — просеивать нечего\. Непроверенный текст не является чистым\.",
     "the text has no words at all — nothing to screen. Unscreened text is not clean text."),
    (r"опишите работу словами — что нужно сделать и с чем; по пустому брифу план не собирается",
     "describe the job in words — what needs doing and with what; an empty brief builds no plan"),
    (r"поправьте путь к видео — по названному файла нет",
     "fix the path to the video — there is no file at the path given"),
    (r"креатив не подан", "no creative was given"),
    # --- вопрос/совет (planner.что_дальше)
    (r"ни одна из операций студии не выводится из этого брифа: словарь знает (\d+) операций, совпало (\d+)\. План не собирается",
     r"none of the studio's operations can be derived from this brief: the vocabulary knows \1 operations, \2 matched. No plan is built"),
    # --- нота плана (planner: валидатор-2 …)
    (r"валидатор-2 отверг план: ", "validator-2 refuted the plan: "),
    (r"валидатор-2 не смог подтвердить план: ", "validator-2 could not confirm the plan: "),
    (r"валидатор-2 подтвердил план: ", "validator-2 confirmed the plan: "),
    (r"валидатор-2 не опроверг план: ", "validator-2 did not refute the plan: "),
    (r"слабейшее звено: ", "weakest link: "),
    (r"главное не решено: ", "the main question is open: "),
    (r"Видео уже снято — или ролик нужно сделать с нуля\?", "Is the video already shot — or must the clip be made from scratch?"),
    (r"шагов (\d+), без кандидата (\d+), кандидат без применимости (\d+)",
     r"steps \1, without a candidate \2, candidate without applicability \3"),
    (r", дороже потолка (\d+)", r", over the ceiling \1"),
    (r", проверенный не выбран (\d+)", r", proven one not chosen \1"),
    (r", проверенный вытеснен ценой (\d+)", r", proven one pushed out by price \1"),
    (r", проверенных нет вовсе (\d+)", r", no proven candidate at all \1"),
    (r", кадр не принимают (\d+)", r", frame refused \1"),
    (r", вход запрещён (\d+)", r", input forbidden \1"),
    (r", уже снятых выбрано (\d+)", r", retired models chosen \1"),
    (r", выход не тот (\d+)", r", wrong output \1"),
    (r", дорожками: ", ", tracks: "),
    (r"; ВНИМАНИЕ: ", "; WARNING: "),
    (r"класс не назван", "class not named"),
    # --- проба валидатора (studio/pipeline.py)
    (r"способность закрыта (\d+) относящимися строк\(ами\), применимость: нет свидетельства",
     r"capability covered by \1 relevant row(s), applicability: no evidence"),
    (r"применимость наблюдалась ПО ЭТОМУ требованию и она отрицательная: (\d+) строк\(и\) о том, где это ломается",
     r"applicability was observed FOR THIS requirement and it is negative: \1 row(s) about where it breaks"),
    (r"применимость наблюдалась ПО ЭТОМУ требованию и она положительная: (\d+) строк\(и\)",
     r"applicability was observed FOR THIS requirement and it is positive: \1 row(s)"),
    (r"вне языка шага отброшено: (\d+) строк\(и\) о языке ([\w?]+(?:, [\w?]+)*), а шаг — о ([\w?]+(?:, [\w?]+)*)",
     r"dropped as outside the step's language: \1 row(s) about \2, while the step is about \3"),
    (r"вне языка шага отброшено: (\d+) строк\(и\) о языке (\w+)", r"dropped as outside the step's language: \1 row(s) about \2"),
    (r"вне языка шага отброшено", "dropped as outside the step's language"),
    (r"вне условий брифа отброшено: (\d+) строк\(и\)", r"dropped as outside the brief's conditions: \1 row(s)"),
    (r"вне условий брифа отброшено", "dropped as outside the brief's conditions"),
    (r"ни одна строка не относится к требованию: (\d+) строк\(и\) про другое",
     r"no row is about the requirement: \1 row(s) about something else"),
    (r"относящихся строк (\d+), но род не выведен ни у одной", r"relevant rows \1, but the kind of none is derived"),
    (r"утверждений о модели: (\d+)", r"statements about the model: \1"),
    (r"вход шага закрыт: требуется (\d+)", r"the step's input is covered: \1 required"),
    (r"лицензий прочитано: (\d+), запрета нет", r"licences read: \1, no prohibition"),
    (r"о лицензии модели в базе нет ни строки: разрешено ли применение — не смогли",
     "the base has no line about the model's licence: whether the use is allowed — could not tell"),
    (r"бюджет шага не заявлен — сравнивать не с чем", "no step budget stated — nothing to compare with"),
    (r"свежайшему утверждению (\d+) дн\. из (\d+)", r"the newest statement is \1 day(s) old of \2"),
    (r"решающих атрибутов сверено: (\d+), расхождений нет", r"deciding attributes cross-checked: \1, no disagreement"),
    (r"решающих атрибутов сверено: (\d+), расхождений (\d+)", r"deciding attributes cross-checked: \1, disagreements \2"),
    # --- требования шага (pipeline: человеческая половина; якоря поиска английские)
    (r"кадр по описанию: композиция, свет и персонажи как в брифе", "an image from a description: composition, light and characters as in the brief"),
    (r"персонаж держится от кадра к кадру по референсу, правка не ломает лицо", "the character holds from image to image by the reference; the edit does not break the face"),
    (r"речь по тексту заказчика, голос держится всю реплику", "speech from the customer's text, the voice holds for the whole line"),
    (r"речь того же ролика на другом языке, смысл и тайминг держатся", "the same clip's speech in another language; meaning and timing hold"),
    (r"лицо клиента не подменяется, движение не разваливает кадр", "the client's face is not swapped, motion does not break the frame"),
    (r"лицо со снимка говорит голосом заказчика: губы в синхроне, лицо не плывёт", "the face from the photo speaks in the customer's voice: lips in sync, the face does not drift"),
    (r"видео по описанию, длительность и план держатся", "video from a description, duration and shot hold"),
    (r"персонаж заменён, цветокор и освещение сцены сохранены", "the character is replaced; grading and scene lighting are kept"),
    (r"фоновые звуки сцены", "the scene's background sounds"),
    (r"музыка под настроение и длину ролика", "music matching the mood and length of the clip"),
    (r"губы держат синхрон всю реплику, лицо не плывёт", "lips stay in sync for the whole line, the face does not drift"),
    (r"разрешение поднято без восковой кожи и мерцания", "resolution raised without waxy skin or flicker"),
    (r"разрешение кадра поднято без артефактов", "image resolution raised without artefacts"),
    (r"картинка, речь и губы одной моделью: голос держится, губы в синхроне", "picture, speech and lips by one model: the voice holds, lips in sync"),
    (r"снимок оживает, лицо и черты держатся", "the photo comes alive, the face and features hold"),
    (r"старое видео восстановлено \(шум, царапины, мерцание\) без смены цвета",
     "old footage restored (noise, scratches, flicker) without changing its colour"),
    (r"чёрно-белое видео раскрашено без мерцания цвета между кадрами",
     "black-and-white footage colourised without colour flicker between frames"),
    (r"промежуточные кадры без двоения и дрожи на быстром движении",
     "in-between frames without ghosting or judder on fast motion"),
    (r"фон снят чисто по контуру \(волосы, стекло\), на выходе прозрачность",
     "the background is cut cleanly along the edge (hair, glass), transparency on output"),
    (r"фон снят по контуру в каждом кадре, без мерцания края",
     "the background is cut along the edge in every frame, without edge flicker"),
    (r"текст со словами и метками говорящих, тайминги для субтитров",
     "a transcript with speaker labels and timings for captions"),
    (r"текст прочитан голосом образца: тембр, акцент и темп как в образце",
     "the script read in the sample's voice: timbre, accent and pace as in the sample"),
    (r"предмет поворачивается на 360° без искажения формы, петля без шва",
     "the object turns 360° without warping, a seamless loop"),
    (r"режимы вариантов: ", "modes of the variants: "),
    (r"атрибуты: ", "attributes: "),
    # --- положения кандидата (planner: PRICE_*, FIT_*, BAN_*, LIFE_*, OUT_*, duration.DUR_*)
    (r"измеренный провал: ", "measured failure: "),
    (r"применимость не измерена — только схема и заявления вендора", "applicability not measured — vendor schema and claims only"),
    (r"применимость измерена: (\d+) строк\(и\), из них (\d+) о том, где ломается",
     r"applicability measured: \1 row(s), \2 of them about where it breaks"),
    (r"применимость измерена: (\d+) строк\(и\), плохих новостей нет", r"applicability measured: \1 row(s), no bad news"),
    (r"применимость не измерена", "applicability not measured"),
    (r"цена записана, но с бюджетом несравнима", "price recorded but not comparable with the budget"),
    (r"цена не записана", "no price recorded"),
    (r"дороже бюджета", "over budget"),
    (r"в бюджете", "within budget"),
    (r"кадр НЕ принимается", "frame NOT accepted"),
    (r"кадр принимается", "frame accepted"),
    (r"предел записан, но не разобран", "limit recorded but not parsed"),
    (r"предел кадра не записан", "frame limit not recorded"),
    (r"кадр не подан — сравнивать не с чем", "no frame given — nothing to compare with"),
    (r"вход разрешён явно", "input explicitly allowed"),
    (r"о запрете на вход \(([^)]*)\) в базе не сказано ни строки из (\d+): это НЕ разрешение",
     r"nothing about a ban on the input (\1) in \2 row(s) of the base: this is NOT permission"),
    (r"о запрете на вход не сказано", "no ban on the input stated"),
    (r"ВОСПОЛЬЗОВАТЬСЯ НЕЛЬЗЯ \(вход ЗАПРЕЩЁН\): ", "CANNOT BE USED (input FORBIDDEN): "),
    (r"вход ЗАПРЕЩЁН", "input FORBIDDEN"),
    (r"ЗАПРЕТ НА ВХОД, а не довод", "INPUT BAN, not a reason"),
    (r" и ещё (\d+) — модель без («Q») не запускается, а на этом шаге его взять неоткуда: ",
     r" and \1 more — the model does not run without \2, and this step has nowhere to take it from: "),
    (r" — модель без («Q») не запускается, а на этом шаге его взять неоткуда: ",
     r" — the model does not run without \1, and this step has nowhere to take it from: "),
    # Та же нота, когда она стоит одна (поле `ban_note` альтернативы), без тире перед ней.
    (r"^модель без («Q») не запускается, а на этом шаге его взять неоткуда: ",
     r"the model does not run without \1, and this step has nowhere to take it from: "),
    (r"цена ЗАПИСАНА, но с потолком несравнима: (.+?) — единица не та, что у бюджета шага, и подставлять одно в"
     r" другое значило бы сравнить разное",
     r"price RECORDED but not comparable with the ceiling: \1 — not the unit of the step budget, and putting one"
     r" for the other would compare different things"),
    (r"цена ЗАПИСАНА, но с потолком несравнима: ", "price RECORDED but not comparable with the ceiling: "),
    (r" и ещё (\d+) — шагу нужен вход («Q»), а схема эндпоинта такого поля не имеет: ",
     r" and \1 more — the step needs the input \2, and the endpoint schema has no such field: "),
    # Интеграция пятого круга: общие формы `blocked_line` (снята, выход не тот).
    (r"ВОСПОЛЬЗОВАТЬСЯ НЕЛЬЗЯ \(", "CANNOT BE USED ("),
    (r" и ещё (\d+) — ", r" and \1 more — "),
    # Условный запрет лицензии (`pipeline`, проба лицензии): тариф заказчика неизвестен.
    (r"лицензия (\S+) содержит («Q»), но запрет условный: он снимается («Q»)\. "
     r"Тариф заказчика неизвестен — проверить не смогли",
     r"licence \1 contains \2, but the ban is conditional: it is lifted by \3. "
     r"The customer's plan is unknown — could not check"),
    (r"о снятии не сказано", "no retirement stated"),
    (r"снятие объявлено, срок впереди", "retirement announced, date ahead"),
    (r"снята: срок прошёл", "retired: the date has passed"),
    (r"признаков снятия нет ни в одной из (\d+) строк", r"no sign of retirement in any of \1 row(s)"),
    (r"снятие на маршруте (\w+) назначено на ([\d-]+) — впереди", r"retirement on route \1 is set for \2 — ahead"),
    (r"сроки снятия по маршрутам — ", "retirement dates by route — "),
    (r"(\w+): закрывается ([\d-]+) \(сегодня открыты все записанные маршруты\)",
     r"\1: closes \2 (all recorded routes are open today)"),
    (r"отдаёт нужный вид", "produces the needed kind"),
    (r"нужного вида НЕ отдаёт", "does NOT produce the needed kind"),
    (r"выход не записан", "output not recorded"),
    (r"шагу нужен (\S+), модель отдаёт (\S+) ", r"the step needs \1, the model produces \2 "),
    (r"шагу нужен ([\w]+(?:, [\w]+)*), а модель отдаёт ([\w]+(?:, [\w]+)*)",
     r"the step needs \1, and the model produces \2"),
    (r"ролик ДЛИННЕЕ предела", "clip LONGER than the limit"),
    (r"длительность принимает", "duration accepted"),
    (r"предел длительности не записан", "duration limit not recorded"),
    (r"предел длительности не разобран", "duration limit not parsed"),
    (r"длительность не спрашивали", "duration not asked"),
    (r"длительность в брифе не разобрана", "duration in the brief not parsed"),
    (r"о длительности этой модели база молчит", "the base is silent on this model's duration"),
    (r"([\d.]+) с ролика при пределе ([\d.]+) с \(предел ([\d.]+) с: ", r"\1 s of clip against a limit of \2 s (limit \3 s: "),
    (r"в брифе названо '([^']*)' — это ([\d.]+) с \(секунд\)", r"the brief says '\1' — that is \2 s (seconds)"),
    # --- положения кандидата, полный ответ (planner)
    (r"длительность в брифе не названа — сравнивать не с чем", "the brief names no duration — nothing to compare with"),
    (r"вход принимается по схеме: ", "the input is accepted by the schema: "),
    (r"\(шагу нужны: ([^)]*)\)", r"(the step needs: \1)"),
    (r"строк о длительности (\d+), числа из них не вышло: ", r"duration rows \1, no number came out of them: "),
    (r"шаг производит (.+?), а выход модели не записан ни одной строкой из (\d+): это НЕ («Q»)",
     r"the step produces \1, and the model's output is not recorded in any of \2 rows: this is NOT \3"),
    (r"в той же семье есть новее: ", "there is a newer one in the same family: "),
    (r"модель ещё отвечает — это предупреждение, а не отказ", "the model still answers — this is a warning, not a refusal"),
    (r"(\w+): закрывается ([\d-]+)", r"\1: closes \2"),
    (r"применимость закрыта (\d+) относящимися строк\(ами\), не опровергнута", r"applicability covered by \1 relevant row(s), not refuted"),
    (r"способность закрыта (\d+) относящимися строк\(ами\)", r"capability covered by \1 relevant row(s)"),
    (r", не опровергнута", ", not refuted"),
    (r"применимость: нет свидетельства", "applicability: no evidence"),
    (r"нечем закрывать требование: ни одной размеченной строки", "nothing to cover the requirement: not one labelled row"),
    (r"\[со звуком\]", "[with audio]"),
    # --- справка: площадки и срок жизни
    (r"по записи базы (\S+) = ", r"per the base's record \1 = "),
    (r"(\S+): вендорского значения в базе нет; ПО ПЛОЩАДКАМ: ", r"\1: no vendor value in the base; BY PLATFORM: "),
    (r"\. ОБЛАСТЬ, НЕ СПОР: каждая площадка сообщает предел своего эндпоинта", ". SCOPE, NOT A DISPUTE: each platform reports the limit of its own endpoint"),
    # --- выбор и соперники (planner)
    (r"ПРОВЕРЕННЫЙ ЕСТЬ, НО ВЫБРАН НЕ ОН: ", "A PROVEN ONE EXISTS, BUT IT WAS NOT CHOSEN: "),
    (r"ПРОВЕРЕННЫХ НЕТ ВОВСЕ: ни у одного из (\d+) найденных кандидатов применимость не измерена — выбирать пришлось между непроверенными",
     r"NO PROVEN CANDIDATE AT ALL: none of the \1 candidates found has measured applicability — the choice was between unproven ones"),
    (r"ПРОВЕРЕННЫХ НЕТ ВОВСЕ", "NO PROVEN CANDIDATE AT ALL"),
    (r"НИЧЬЯ: (\S+) и (\S+) равны по всем полям отбора — данные между ними не выбирают; первым стоит дешевле \(при равной цене — по имени\), а не лучше\. Смотрите обоих",
     r"TIE: \1 and \2 are equal on every selection field — the data does not choose between them; the first is first because it is cheaper (by name at equal price), not better. Look at both"),
    (r"выбран (\S+), а не (\S+): разошлись по ", r"chose \1 over \2: they differed on "),
    (r"подтверждено осей (\d+) из (\d+)", r"axes confirmed \1 of \2"),
    (r"кадр: не считалось", "frame: not counted"),
    (r"измерено, но есть плохая новость", "measured, but there is bad news"),
    (r"измерено одной строкой — чисто по бедности, а не по проверке", "measured by one row — clean for lack of data, not by checking"),
    (r"измерено чисто", "measured clean"),
    (r"не ниже по записи", "not lower on record"),
    (r"строк применимости (\d+) \(за (\d+), против (\d+)\)", r"applicability rows \1 (for \2, against \3)"),
    (r"; полоса та же \(", "; same band ("),
    (r"\), внутри неё порядок решали поля младше знака \(счёт строк, якоря, имя\), а не род доказательства",
     "): inside it the order was decided by the fields below the sign (row count, anchors, name), not by the kind of evidence"),
    (r"; кадр/длительность: ", "; frame/duration: "),
    (r"; лицензия: ", "; licence: "),
    (r"перевыбрано внутри полосы доводов \(всё старше счёта строк — то же, кроме цены\): ",
     "re-selected within the same evidence band (every key above the row count equal, price aside): "),
    (r"сумма ([\d.]+) usd выше потолка ролика ([\d.]+) usd", r"total \1 usd is over the clip ceiling \2 usd"),
    # --- дописанные шаги (planner)
    (r"(\S+) никем не производится и на входе его нет", r"no step makes \1 and you did not bring it"),
    (r"голос и оживлённое лицо в брифе не соединены — губы двигает липсинк",
     "voice and the animated face are not joined in the brief — lip sync joins them"),
    (r"в брифе заказан нативный звук: картинку, речь и губы делает одна видеомодель \(вместо: ([^)]*)\)",
     r"the brief asks for native audio: one video model makes the picture, the speech and the lips (instead of: \1)"),
    (r"в брифе заказан нативный звук: картинку, речь и губы делает одна видеомодель",
     "the brief asks for native audio: one video model makes the picture, the speech and the lips"),
    (r"снимок принесён, и он должен заговорить: одна модель («Q») вместо оживления и липсинка",
     r"a photo was brought and it must speak: one model \1 instead of animation and lip sync"),
    (r"УСЛОВНО: в брифе заказан кадр (\S+), а модель шага (\S+) \((\S+)\) его не подтверждает и не опровергает — ",
     r"CONDITIONAL: the brief asks for a \1 frame, and the model of step \2 (\3) neither confirms nor refutes it — "),
    (r"предел кадра не записан: строк о разрешении (\d+): предел модели не записан",
     r"frame limit not recorded: rows about resolution \1: the model's limit is not recorded"),
    (r"; апскейл нужен, только если выход окажется меньше заказа", "; upscaling is needed only if the output turns out smaller than ordered"),
    (r"в брифе заказан кадр (\S+), а у модели последнего шага",
     r"the brief asks for \1, and the last image/video model"),
    (r"не входит в цену ролика и в вердикт бюджета: нужен, только если выход предыдущего шага окажется меньше заказанного кадра",
     "not in the clip price nor in the budget verdict: needed only if the previous step's output turns out smaller than the ordered frame"),
    (r"одна модель вместо (\d+) шагов \(([^)]*)\); валидатор: ", r"one model instead of \1 steps (\2); validator: "),
    # --- кадр (planner.resolution_carry)
    (r"кадр (\S+) не подтверждён: модель шага (\S+) \((\S+)\) его не подтверждает и не опровергает — ",
     r"frame \1 not confirmed: the model of step \2 (\3) neither confirms nor refutes it — "),
    (r"; апскейл не дописан — молчание базы не повод платить",
     "; no upscale step added — the base's silence is no reason to pay"),
    (r"кадр (\S+) пронесён от шага (\S+) \(", r"frame \1 carried from step \2 ("),
    (r"тариф шага посчитан в (\d+p) — ниже (\d+p)", r"the step's rate is priced at \1 — below \2"),
    (r"тариф шага посчитан в (\d+p)", r"the step's rate is priced at \1"),
    (r"по записи семьи (\S+): ", r"on the family's record \1: "),
    (r"в брифе заказан кадр (\S+), а у модели шага (\S+) \((\S+)\) он ниже по записи — ",
     r"the brief asks for a \1 frame, and the model of step \2 (\3) is below it on record — "),
    # --- кадр против предела (planner.fit, studio/resolution.py)
    (r"строк о разрешении (\d+): принимают (\d+), отвергают (\d+), не разобрано (\d+)",
     r"resolution rows \1: accept \2, refuse \3, not parsed \4"),
    (r"строк о разрешении 0: предел модели не записан", "resolution rows 0: the model's limit is not recorded"),
    (r"креатив (\d+x\d+); ", r"creative \1; "),
    (r"вторая сторона не названа: ступень задаёт только одну", "the other side is not named: a tier sets only one"),
    (r"ступень (\w+) неизвестна", r"tier \1 unknown"),
    (r"\(ступень (\w+): ", r"(tier \1: "),
    (r"ступень (\w+): ", r"tier \1: "),
    (r"длинная сторона (\d+) больше предела (\d+)", r"long side \1 above the limit \2"),
    (r"короткая сторона (\d+) больше предела (\d+)", r"short side \1 above the limit \2"),
    (r"длинная (\d+) <= (\d+)", r"long \1 <= \2"),
    (r"короткая (\d+) <= (\d+)", r"short \1 <= \2"),
    (r"предел не разобран: ", "limit not parsed: "),
    (r"предел не назвал ни одной стороны", "the limit names neither side"),
    (r"пар чисел в строке (\d+), взята крупнейшая", r"number pairs in the row \1, the largest taken"),
    (r"верхняя граница диапазона сторон", "upper bound of the side range"),
    (r"ни пары чисел, ни известной ступени", "neither a number pair nor a known tier"),
    (r"значение пустое", "the value is empty"),
    (r"\) через (.+?): о разрешении их выхода база молчит, и принято, что проход кадр сохраняет — допущение, не замер",
     r") through \1: the base is silent on their output resolution, and the pass is assumed to keep the frame — an assumption, not a measurement"),
    (r": о разрешении их выхода база молчит, и принято, что проход кадр сохраняет — допущение, не замер",
     ": the base is silent on their output resolution, and the pass is assumed to keep the frame — an assumption, not a measurement"),
    # --- бюджет (planner.budget)
    (r"бюджет в брифе не назван — сравнивать не с чем", "no budget named in the brief — nothing to compare with"),
    (r"потолок ([\d.]+) usd; («Q») заказчик НЕ назвал; принято — на ВЕСЬ РОЛИК: с потолком сравнивается сумма всех шагов\. Потолок на шаг — только если так и сказано(\.?)",
     r"ceiling \1 usd; the customer did NOT say \2; taken as for the WHOLE CLIP: the sum of all steps is compared with the ceiling. A per-step ceiling only if said so\3"),
    (r"потолок ([\d.]+) usd; («Q») названо: ([^.]*?)\.", r"ceiling \1 usd; \2 named: \3."),
    (r" Валидатору потолок НЕ передан: его поле — бюджет ШАГА \(run, generation\), а этот назван за (\w+); подставить одно в другое значило бы сравнить разное\.",
     r" The ceiling is NOT passed to the validator: its field is the STEP budget (run, generation), and this one is named per \1; substituting one for the other would compare different things."),
    (r" Валидатору потолок НЕ передан: его поле — бюджет ШАГА \(run, generation\), а этот назван за (\w+); подставить одно в другое значило бы сравнить",
     r" The ceiling is NOT passed to the validator: its field is the STEP budget (run, generation), and this one is named per \1; substituting one for the other would compare"),
    (r" В отборе кандидатов потолок при этом участвует полностью", " In candidate selection the ceiling still counts in full"),
    (r"шаг ([\d.]+) usd \((.*)\) при потолке ([\d.]+) usd на весь ролик", r"step \1 usd (\2) against a ceiling of \3 usd for the whole clip"),
    (r"нижняя цена ([\d.]+) usd за (\w+) \(([^)]*)\) укладывается в потолок ([\d.]+)", r"the lowest price \1 usd per \2 (\3) fits the ceiling \4"),
    (r"нижняя цена ([\d.]+) usd (?:за|per) (\w+)( \[[^\]]*\])? \(([^)]*)\); потолка заказчик не назвал — сравнивать не с чем",
     r"the lowest price \1 usd per \2\3 (\4); the customer named no ceiling — nothing to compare with"),
    (r"ценовых строк (\d+), сравнимых с потолком (\d+) \(", r"price rows \1, comparable with the ceiling \2 ("),
    (r"ценовых строк (\d+): посмотреть нечего", r"price rows \1: nothing to look at"),
    # --- смета (planner/pricing): цены и формулы
    (r"; неизвестных слагаемых (\d+), из них с условиями (\d+)", r"; unknown terms \1, of them conditional \2"),
    (r"; неизвестных слагаемых (\d+)", r"; unknown terms \1"),
    (r"шагов с ценой (\d+) из (\d+), без цены: ", r"steps with a price \1 of \2, without a price: "),
    (r"шагов с ценой (\d+) из (\d+)", r"steps with a price \1 of \2"),
    (r"НИЖНЯЯ ГРАНИЦА РОЛИКА: ", "CLIP LOWER BOUND: "),
    (r"НИЖНЯЯ ГРАНИЦА ПЛАНА: ", "PLAN LOWER BOUND: "),
    (r"ЦЕНА РОЛИКА: ", "CLIP PRICE: "),
    (r"ЦЕНА ПЛАНА: ", "PLAN PRICE: "),
    (r"ЦЕНЫ РОЛИКА НЕТ: ни один шаг плана не делает сам ролик \(видео\) — посчитаны только шаги ",
     "NO CLIP PRICE: no step of the plan makes the clip itself (video) — only these steps are priced: "),
    (r"ЦЕНЫ РОЛИКА НЕТ: ни один шаг плана не делает сам ролик — посчитаны только ",
     "NO CLIP PRICE: no step of the plan makes the clip itself — only these are priced: "),
    (r"ЦЕНЫ РОЛИКА НЕТ", "NO CLIP PRICE"),
    (r" — это не полная цена, без цены шаги ", " — this is not the full price; steps without a price: "),
    (r" — в потолок ([\d.]+) укладывается только ИЗВЕСТНАЯ часть; шаги без цены \(([^)]*)\) могут его превысить, и это не проверено",
     r" — only the KNOWN part fits the ceiling \1; the steps without a price (\2) may exceed it, and that is not checked"),
    (r" — в потолок ([\d.]+) влезает только на дешёвых тарифах: ", r" — the ceiling \1 fits only on the cheaper tiers: "),
    (r"по умолчанию ([\d.]+) usd — ПРЕВЫШЕН", r"by default \1 usd — EXCEEDED"),
    (r"все шаги на самых дешёвых, ", "all steps on the cheapest, "),
    (r"; на самых дешёвых тарифах \(([^)]*)\) ", r"; on the cheapest tiers (\1) "),
    (r" — ПОТОЛОК ([\d.]+): работа столько не стоит, дешевле всего выходит ", r" — CEILING \1: the work does not cost that little, the cheapest comes to "),
    (r" — ПОТОЛОК ([\d.]+): работа столько не стоит, любая записанная цена больше нуля \(наименьшая ",
     r" — CEILING \1: the work does not cost that little, every recorded price is above zero (the lowest "),
    (r"\. ВНИМАНИЕ: это СТАВКА ЗА СЕКУНДУ, а не цена ролика \(", ". WARNING: this is a RATE PER SECOND, not the clip price ("),
    (r"; прочие единицы — поштучные и сюда не входят\): длительность в брифе не разобрана, умножать не на что",
     "; other units are per item and not included): the brief's duration was not parsed, nothing to multiply by"),
    # --- краткий ответ плана (planner.сжать)
    (r"строки доказательства сверх одной на шаг, ноты положений \(цена, длительность\), положения соседей \(кадр, вход, служба, выход\), пробы валидатора по классам и ноты к ним, пустые поля сметы — всё это в ответе с full=true",
     "evidence rows beyond one per step, position notes (price, duration), the neighbours' positions (frame, input, service, output), the validator's probes by class and their notes, empty estimate fields — all of it is in the answer with full=true"),
    (r"объявленные вход и выход", "declared input and output"),
    (r"профиль модели", "model profile"),
    (r"кадр подтверждён", "frame confirmed"),
    (r"\[(\d+p) ниже заказанного (\d+p) — нужен апскейл\]", r"[\1 below the ordered \2 — upscaling needed]"),
    (r"(\d+) или (\d+) секунд", r"\1 or \2 seconds"),
    (r"ниже заказанного", "below the ordered"),
    (r"разрешение выхода не записано", "output resolution not recorded"),
    # --- источник-оператор
    (r"владелец, чат ([\d-]+)", r"owner, chat \1"),
    (r"\(сырой ответ сохранён файлом (\S+)\)", r"(raw response saved as \1)"),
    # --- заявления заказчика (studio/mcp/screen.предупреждение)
    (r"в брифе есть утверждение, за которое в рекламе отвечает заказчик, а не студия \(([^)]*)\)\. Из-за него работа не отклонена: правда ли это, студия не судит — но проверьте, чем утверждение подтверждается\. В большинстве стран такая реклама требует документа, а ролик остаётся у вас",
     r"the brief makes a claim the customer, not the studio, answers for in advertising (\1). The work is not refused because of it: the studio does not judge whether it is true — but check what supports the claim. In most countries such an ad needs a document, and the clip stays with you"),
    (r"в заказе назван живой человек — ([^.]*)\. Права на образ и голос человека принадлежат ему: студия не может судить, есть ли у вас письменное согласие, и потому не отказывает — но без согласия такой ролик снимать нельзя, и отвечает за это заказчик\.",
     r"the order names a living person — \1. The rights to a person's likeness and voice are theirs: the studio cannot judge whether you have written consent, and so does not refuse — but without consent such a clip must not be made, and the customer answers for it."),
    (r"в заказе просят выдать сделанное видео за настоящую запись \(([^)]*)\)\. Студия не судит, законно это или нет — розыгрыш внутри компании и обман клиентов пишутся одними словами, — и потому не отказывает\. Но ролик, выдаваемый за подлинную запись чужой речи, почти везде запрещён отдельно от прав на образ, и отвечает за это заказчик\.",
     r"the order asks to pass a made video off as a real recording (\1). The studio does not judge whether that is lawful — an internal prank and deceiving customers are written in the same words — and so does not refuse. But a clip passed off as a genuine recording of someone's speech is forbidden almost everywhere, separately from likeness rights, and the customer answers for it."),
    (r" Кроме того: ", " Also: "),
    (r"медицинское утверждение", "medical claim"),
    (r"обещание дохода", "financial claim"),
    # --- нота «нечего строить» (planner)
    (r"План не собирается — пустой шаг честнее выдуманного", "No plan is built — an empty step is more honest than an invented one"),
    (r"пустой шаг честнее выдуманного", "an empty step is more honest than an invented one"),
    # --- проба валидатора: строки мимо условий брифа (pipeline)
    (r"вне условий брифа отброшено: (\d+) строк\(и\) о провале при условиях, которых в брифе нет \(([^)]*)\)",
     r"dropped as outside the brief's conditions: \1 row(s) about failure under conditions the brief does not have (\2)"),
    # --- значения полей ключа отбора (planner._поле, SIGN_WORDS)
    # седьмой круг: провал против объявленной хорошей новости, хостинг, узел семьи со своими весами
    (r"провалов не записано, и есть хорошая новость \(объявленная или чистое измерение\)",
     "no failure recorded, and there is good news (declared, or a clean measurement)"),
    (r"записан провал, или хорошей новости нет", "a failure is recorded, or there is no good news"),
    (r" \(объявлено хорошего: (\d+)\)", r" (declared good: \1)"),
    (r" \(один прогон покрывает ролик\)", " (one run covers the clip)"),
    (r"узел семьи: через API не купить — только свои веса \(self-host\)",
     "a family node: not purchasable via API — own weights only (self-host)"),
    (r"только свои веса \(self-host\): через API не купить, а план без своего GPU",
     "own weights only (self-host): not purchasable via API, and the plan has no own GPU"),
    (r"хостинг/юрисдикция вендора по записи: ([^—]*) — ни одна не ваша \(([^)]*)\): ",
     r"hosting/vendor jurisdiction on record: \1 — none is yours (\2): "),
    (r"измерено, плохих новостей нет", "measured, no bad news"),
    (r"измерено, и всё измеренное — плохое", "measured, and everything measured is bad"),
    (r"по записи ниже заказанного кадра", "below the ordered frame on record"),
    (r"лицензия запрещает", "the licence forbids"),
    (r"другую работу", "another job"),
    (r"эту работу", "this job"),
    (r"не считалось", "not counted"),
    (r"исключает территории, юрисдикция не названа", "excludes territories, jurisdiction not named"),
    (r"текущее поколение", "current generation"),
    (r"вытеснена: ", "superseded: "),
    (r"не измерено", "not measured"),
    # --- бюджет за не-ролик (planner.смета)
    (r"\. Потолок назван за ([^,]*(?:, [^,]*)*?), а посчитана цена ВСЕГО РОЛИКА — это величины разного рода, и сравнение не делалось",
     r". The ceiling is named per \1, while the price computed is for the WHOLE CLIP — different kinds of quantity, and no comparison was made"),
    (r", а с суммой шагов его сравнивает смета ролика \(`pipeline_price`\)", ", and the clip estimate (`pipeline_price`) compares it with the sum of steps"),
    (r" \(цена УСЛОВНАЯ: настоящая выше названной\)", " (price is CONDITIONAL: the real one is above the stated)"),
    # --- срок жизни модели (studio/lifecycle.py, advice)
    (r"снятие на маршруте (\S+) объявлено, но даты в строке нет", r"retirement on route \1 announced, but the row has no date"),
    (r"снятие объявлено, но даты в строке нет", "retirement announced, but the row has no date"),
    (r"снятие на маршруте (\S+) назначено на ([\d-]+) — дата уже прошла", r"retirement on route \1 was set for \2 — the date has passed"),
    (r"снятие назначено на ([\d-]+) — дата уже прошла", r"retirement was set for \1 — the date has passed"),
    (r"снятие назначено на ([\d-]+) — впереди", r"retirement is set for \1 — ahead"),
    (r"(\w+): закрыт с ([\d-]+)", r"\1: closed since \2"),
    (r" \(срок прошёл на каждом записанном маршруте\)", " (the date has passed on every recorded route)"),
    (r" \(модель снята не целиком: выбирайте маршрут\)", " (the model is not retired everywhere: choose the route)"),
    (r"маршрутных сроков снятия нет", "no per-route retirement dates"),
    (r"СНЯТА С ОБСЛУЖИВАНИЯ НА ВСЕХ ЗАПИСАННЫХ МАРШРУТАХ: ", "RETIRED ON EVERY RECORDED ROUTE: "),
    (r"СНЯТА С ОБСЛУЖИВАНИЯ \(([^)]*)\), по записи базы: ", r"RETIRED (\1), per the base's record: "),
    (r"ОБЪЯВЛЕНО СНЯТИЕ \(([^)]*)\), по записи базы: ", r"RETIREMENT ANNOUNCED (\1), per the base's record: "),
    (r"ПО МАРШРУТАМ: ", "BY ROUTE: "),
    (r"срок не назван", "date not named"),
    (r"без даты", "undated"),
    # --- справка (studio/mcp/advice.py, studio/selfrag/modelnames.py)
    (r"ИМЯ ВЫВЕДЕНО ПО СОСЕДУ: ('[^']*') в базе нет, единственный сосед — ('[^']*')\. Ниже — ответ О ('[^']*') \(его исход был ('[^']*')\), но это ПОДСКАЗКА, а не факт о ('[^']*'): если это та же модель, спросите по ('[^']*')\. ",
     r"NAME INFERRED FROM A NEIGHBOUR: \1 is not in the base, its only neighbour is \2. Below is the answer ABOUT \3 (its outcome was \4), but it is a HINT, not a fact about \5: if it is the same model, ask about \6. "),
    (r"('[^']*') разрешено в ('[^']*')", r"\1 read as \2"),
    (r" \(прочитано как имя базы: спрошено без вендора впереди, слово семьи и версия совпадают, сосед единственный\)",
     " (asked without the vendor in front; family word and version match; the only neighbour)"),
    (r" \(разрешено АВТОМАТИЧЕСКИ: единственный сосед отличается только вендором впереди\)",
     " (read AUTOMATICALLY: the only neighbour differs just by the vendor in front)"),
    (r" \(разрешено АВТОМАТИЧЕСКИ: в базе это единственная версия модели\)",
     " (read AUTOMATICALLY: it is the only version of the model in the base)"),
    (r" \(разрешено по вендору впереди спрошенного имени\)", " (read through the vendor in front of the asked name)"),
    (r" \[тождество по курируемой таблице: ", " [identity by the curated table: "),
    (r"; та же модель записана и как ", "; the same model is also recorded as "),
    (r"('[^']*') не найдено среди (\d+) имён базы ни в одном написании", r"\1 was not found among the base's \2 names in any spelling"),
    (r"; база держит близкие имена: ", "; the base holds similar names: "),
    (r"имя модели не названо, искать нечего", "no model name given, nothing to look up"),
    (r"ОСПОРЕНО (\d+) из (\d+): ", r"CONTESTED \1 of \2: "),
    (r" — источники расходятся, все стороны с адресами в claims \(в счёте — среди unmeasured\); на остальное ответ есть",
     " — sources disagree, every side with its URL is in claims (counted among unmeasured); the rest is answered"),
    (r"СЕМЬЯ: у ('[^']*') (\d+) вариант\(а/ов\) в базе \(", r"FAMILY: \1 has \2 variant(s) in the base ("),
    (r"\); их утверждения — в family_claims \((\d+)\), каждое помечено вариантом и НЕ голосует в ответе о самой модели",
     r"); their statements are in family_claims (\1), each labelled with its variant, and they do NOT vote in the answer about the model itself"),
    (r"СЕМЬЯ: это вариант ('[^']*'); утверждения семьи — в family_claims \((\d+)\), помечены scope=family",
     r"FAMILY: this is a variant of \1; the family's statements are in family_claims (\2), labelled scope=family"),
    (r"ИМЯ: ", "NAME: "),
    (r"Из базы фактов: записей о жизненном цикле \(снятие, вывод из обслуживания\) в базе нет\.",
     "From the fact base: no lifecycle records (retirement, end of service) in the base."),
    (r"Из базы фактов: ", "From the fact base: "),
    (r"ОБЛАСТЬ, НЕ СПОР: площадка\(и\) (\S+) — ", r"SCOPE, NOT A DISPUTE: platform(s) \1 — "),
    (r" сообщают предел СВОЕГО эндпоинта, а не модели; оба ответа верны каждый для своего места и показаны рядом",
     " report the limit of THEIR endpoint, not of the model; both answers are right each for its place and are shown side by side"),
    (r"см\. поле availability", "see the availability field"),
    (r"это КРАТКАЯ форма: разбор источников, ноты и находки о классе лежат в полной выдаче — позовите тот же инструмент с `full=True` \(или с `attribute=<имя>`, чтобы получить один атрибут целиком\)",
     "this is the SHORT form: the source breakdown, notes and class findings are in the full answer — call the same tool with `full=True` (or with `attribute=<name>` to get one attribute in full)"),
    # общие куски, последними
    # --- свой GPU, вердикты бюджета, ставки круга 4 (planner, перенесено при интеграции)
    ('с ней план стоит ([\\d.]+) usd — выше потолка ролика ([\\d.]+) usd', 'with it the plan costs \\1 usd — over the clip ceiling \\2 usd'),
    ('цены нет, а потолок ролика ([\\d.]+) usd назван', 'it has no price, and a clip ceiling of \\1 usd is set'),
    ('заказано самое дешёвое, а (\\S+) в той же полосе дешевле', 'the cheapest was asked, and \\1 is cheaper in the same band'),
    ('через свой GPU — ', 'via own GPU — '),
    ('свой GPU: цена — время GPU × ставка аренды; ', 'own GPU: price = GPU time × rental rate; '),
    ('время GPU на клип не записано', 'GPU time per clip not recorded'),
    ('ставка не записана', 'rental rate not recorded'),
    ('\\(GPU не назван\\)', '(no GPU named)'),
    ('ОЦЕНКА: ', 'ESTIMATE: '),
    ('GPU-с на клип ([\\d.]+) с', 'GPU-s per \\1 s clip'),
    ('GPU-с на прогон \\(длина клипа в источнике не названа\\)', 'GPU-s per run (the source names no clip length)'),
    ('\\(линейно — допущение\\)', '(linear — an assumption)'),
    ('GPU-с × ', 'GPU-s × '),
    ('usd/ч ÷ 3600', 'usd/h ÷ 3600'),
    ('; время: ', '; time: '),
    ('; ставка: ', '; rate: '),
    ('НЕОДНОЗНАЧНО: ставки не различить по брифу \\(([^)]*)\\), взята наибольшая', 'AMBIGUOUS: the brief cannot tell the rates apart (\\1), the dearest is taken'),
    ('НИЖНЯЯ ГРАНИЦА: сколько секунд даёт прогон — не записано: посчитан один прогон', 'LOWER BOUND: seconds per run not recorded, one run counted'),
    ('⌈([\\d.]+)/([\\d.]+)⌉ = (\\d+) блок\\(ов\\)', '⌈\\1/\\2⌉ = \\3 block(s)'),
    ('\\(блок = ([\\d.]+) с\\)', '(block = \\1 s)'),
    ('Мп/кадр × (\\d+) кадров', 'MP/frame × \\1 frames'),
    # --- интеграция круга 4: жёсткие требования (planner/hardneed), шоты, цена
    (r"с потолком ([\d.]+) НЕ СРАВНЕНО: цена шагов (.+?) записана не за секунду \(за кадр, мегапиксель или прогон\), и в цену ролика без числа кадров, частоты или длины прогона не переводится",
     r"NOT COMPARED with the ceiling \1: the price of steps \2 is recorded not per second (per image, megapixel or run), and does not convert into a clip price without the number of frames, the fps or the run length"),
    (r"НЕОДНОЗНАЧНО \((.+?)\): в цене — наибольшая, наименьшая известная стоимость плана ([\d.]+) usd",
     r"AMBIGUOUS (\1): the price takes the dearest; the least known plan cost is \2 usd"),
    (r"ставки не различить по брифу \(([^)]*)\), взята наибольшая",
     r"the brief cannot tell the rates apart (\1), the dearest is taken"),
    (r"перевод готового видео: губы под новый язык \(лиц в кадре нет — шаг снимается\)",
     "translating the finished video: lips to the new language (no faces in frame — the step is dropped)"),
    # --- круг 7: вердикт строки бюджета (`planner.сверить_бюджет`)
    (r"^дороже потолка$", "over the ceiling"),
    (r"^в потолок укладывается$", "fits the ceiling"),
    (r"^с потолком не сравнено: цена плана неполна$", "not compared: the plan price is incomplete"),
    (r"цена плана 0 usd \(шагов-моделей нет\) — в потолок укладывается", "plan price 0 usd (no model step) fits the ceiling"),
    # --- круг 7: пометки и причины монтажа маршрутов (`brief_spec.NOTES_EN`, `ASSEMBLY_REASONS`)
    ('новая\\ дорожка\\ кладётся\\ в\\ ВАШЕ\\ видео\\ при\\ сборке;\\ губы\\ не\\ двигаются\\ \\(spec\\.lipsync=false\\)',
     'the new track is laid into YOUR video at assembly; the lips do not move (spec.lipsync=false)'),
    ('отдаётся\\ дорожка\\ на\\ новом\\ языке;\\ видео\\ не\\ трогается\\ и\\ губ\\ не\\ двигает\\ никто',
     'the new-language track is delivered as audio; the video is not touched and no lips are moved'),
    ('стабилизация\\ —\\ монтажный\\ инструмент\\ \\(ffmpeg\\ vidstab\\ или\\ Gyroflow\\ по\\ гироскопу\\),\\ не\\ модель',
     'stabilisation is an assembly tool (ffmpeg vidstab, or Gyroflow from gyro data), not a model'),
    ('реакция\\ на\\ звук\\ делается\\ при\\ сборке;\\ генерируемое\\ видео\\ трек\\ не\\ слышит',
     'audio reactivity is made at assembly; the generated video does not hear the track'),
    ('один\\ референс\\ персонажа,\\ и\\ каждая\\ картинка\\ серии\\ —\\ правка\\ по\\ нему',
     'one character reference, and every picture of the series is an edit from it'),
    ('язык\\ жестов\\ генеративные\\ модели\\ не\\ делают:\\ липсинк\\ и\\ говорящие\\ аватары\\ двигают\\ губы,\\ а\\ не\\ руки\\ —\\ пробел\\ записан,\\ план\\ не\\ строится',
     'sign language is not something generative models do: lip sync and talking avatars move lips, not hands — a recorded gap, no plan is built'),
    ('фрагменты\\ выбираются\\ по\\ расшифровке\\ \\(вами\\ или\\ языковой\\ моделью\\),\\ режутся,\\ перекадрируются\\ и\\ склеиваются\\ ffmpeg\\ —\\ 0\\ usd,\\ модель\\ не\\ нужна',
     'the moments are picked from the transcript (by you or a language model), then cut, reframed and joined with ffmpeg — 0 usd, no model'),
    ('субтитры\\ вжигаются\\ ffmpeg\\ по\\ расшифровке\\ с\\ таймингами\\ —\\ 0\\ usd',
     'captions are burned in with ffmpeg from the timed transcript — 0 usd'),
    ('переведённая\\ дорожка\\ заменяет\\ звук\\ ВАШЕГО\\ видео\\ \\(ffmpeg\\)\\ —\\ 0\\ usd,\\ липсинка\\ нет',
     'the dubbed track replaces the audio of YOUR video (ffmpeg) — 0 usd, no lip sync'),
    ('стабилизация:\\ ffmpeg\\ vidstab\\ \\(vidstabdetect\\ \\+\\ vidstabtransform\\)\\ или\\ Gyroflow\\ по\\ данным\\ гироскопа\\ —\\ 0\\ usd,\\ первой,\\ на\\ исходнике\\ до\\ шагов\\-моделей;\\ генеративной\\ модели\\ стабилизации\\ с\\ записанным\\ свидетельством\\ в\\ реестре\\ нет',
     'stabilisation: ffmpeg vidstab (vidstabdetect + vidstabtransform) or Gyroflow from gyro data — 0 usd, first, on the source before any model step; no generative stabilisation endpoint with recorded evidence is in the registry'),
    ('реакция\\ на\\ звук\\ —\\ при\\ сборке:\\ доли\\ и\\ атаки\\ ВАШЕГО\\ трека\\ \\(librosa\\ /\\ aubio\\)\\ ведут\\ склейки\\ и\\ пульсацию,\\ слой\\ волны\\ или\\ спектра\\ —\\ ffmpeg\\ showwaves\\ /\\ showspectrum\\ \\(или\\ аудио\\-ключи\\ After\\ Effects\\ /\\ TouchDesigner\\);\\ генерируемое\\ t2v\\-видео\\ трек\\ НЕ\\ слышит\\ и\\ само\\ в\\ такт\\ не\\ попадает',
     'audio reactivity is made at assembly: the beats and onsets of YOUR track (librosa / aubio) drive cuts and pulses, a waveform or spectrum layer comes from ffmpeg showwaves / showspectrum (or After Effects / TouchDesigner audio keyframes); generated t2v footage does NOT hear the track and is not audio-reactive'),
    (r'(\d+) картинок — правки по референсу \(а не \1 независимых генераций\); вариант — обучить LoRA',
     r'\1 pictures are edits from the reference (not \1 independent generations); the alternative is training a LoRA on the character'),
    # --- круг 6: пометки маршрутов по spec (`brief_spec.NOTES_EN` — те же слова)
    (r"субтитры вжигает монтаж \(ffmpeg\) по расшифровке с таймингами — модели на это не нужно",
     "captions are burned in at assembly (ffmpeg) from the timed transcript — no model needed for that"),
    (r"правка ГОТОВОГО видео \(стабилизация, рефрейм, замена неба, вырезка\): всё, что не правится, "
     r"остаётся как было; новый ролик не генерируется",
     "an edit of the FINISHED video (stabilise, reframe, sky replacement, cut-out): whatever is not "
     "edited stays as it was; no new clip is generated"),
    (r"\(длина вашего материала\)", "(the length of your material)"),
    (r"\(весь ваш материал\)", "(all of your material)"),
    (r"брифа нет — бюджета в нём тоже нет", "no brief — so no budget in it either"),
    (r"брифа нет — длительности в нём тоже нет", "no brief — so no duration in it either"),
    (r"бюджет в spec не назван — бриф при плане по spec читается только для эха и языка",
     "no budget in the spec — with a spec, the brief text is only echoed and sets the language"),
    (r"потолок ([\d.]+) usd назван параметром вызова", r"a ceiling of \1 usd was named as a call parameter"),
    (r"один и тот же персонаж во всех шотах — по референсу, без дрейфа лица и одежды",
     "one and the same character in every shot — from the reference, no drift of face or clothes"),
    (r"ни предела VRAM, ни числа параметров не записано", "neither a VRAM limit nor a parameter count is recorded"),
    (r"правка ВАШЕГО видео \(стабилизация, рефрейм, замена неба, вырезка\): нового ролика никто не генерирует",
     "an edit of YOUR video (stabilise, reframe, sky replacement, cut-out): no new clip is generated"),
    (r"референс персонажа делается один раз, и каждый шот строится по нему — персонаж не разъезжается",
     "the character reference is made once and every shot is built from it, so the character does not drift"),
    (r"каждый шот — по одному референсу персонажа \(reference-to-video\)",
     "every shot from one character reference (reference-to-video)"),
    (r"только картинка под ВАШ трек: музыка не генерируется, дорожку кладёт монтаж",
     "visuals only, under YOUR track: no music is generated, the track is laid in at assembly"),
    (r"ВАШ снимок поёт ВАШУ дорожку: аватар, ведомый звуком; ни синтеза речи, ни генерации музыки",
     "YOUR photo sings YOUR track: an audio-driven avatar; no speech synthesis, no music generation"),
    (r"расшифровка с таймингами ВАШЕГО длинного видео — по ней выбираются фрагменты",
     "timed transcript of YOUR long video — the moments are picked from it"),
    (r"каждый короткий ролик вырезан и перекадрирован из ВАШЕГО видео — ничего не генерируется",
     "each short is cut and reframed from YOUR video — nothing is generated"),
    (r"под картинку кладётся ВАША дорожка \(её длина — длина ролика\)",
     "YOUR track is laid under the visuals (its length is the clip length)"),
    (r"фрагменты выбираются по расшифровке \(вами или языковой моделью\) и режутся ffmpeg — модель не нужна",
     "the moments are picked from the transcript (by you or a language model) and cut with ffmpeg — no model"),
    (r"(\[[^\]]*?)без звука\]", r"\1no audio]"),
    (r"(\[[^\]]*?)со звуком\]", r"\1with audio]"),
    (r"(\d+) шот\(ов\) по ([\d.]+) с × ", r"\1 shot(s) of \2 s × "),
    (r"шот\(ов\)", "shot(s)"),
    (r"ролик ([\d.]+) с = (\d+) шот\(ов\) × ([\d.]+) с", r"clip \1 s = \2 shot(s) × \3 s"),
    (r"шот ([\d.]+) с \((\w+)\)", r"shot \1 s (\2)"),
    (r"^ролик ([\d.]+) с$", r"clip \1 s"),
    (r"^другая модель$", "another model"),
    (r"^кадр ниже$", "a lower frame"),
    (r"^допущение$", "assumption"),
    (r"^свой GPU$", "own GPU"),
    (r"(\S+) через свой GPU: ", r"\1 via own GPU: "),
    (r"кадр (\d+p): ", r"frame \1: "),
    (r"заказанный кадр родной, и тариф к нему есть", "the frame asked is native, and there is a rate for it"),
    (r"кадр родной по записи, но купить его не по чему: цены нет",
     "the frame is native by the record, but there is nothing to buy it by: no price"),
    (r"родной ли кадр — не записано", "whether the frame is native is not recorded"),
    (r"родной кадр НИЖЕ заказанного", "the native frame is BELOW the one asked"),
    (r"; доводы семьи (\S+): ", r"; family evidence \1: "),
    (r"\(перенос, не замер варианта\)", "(carried over, not measured on the variant)"),
    (r"цель («Q»): ", r"objective \1: "),
    (r" — апскейл не замена, когда цена не важна", " — upscaling is no substitute when price does not matter"),
    (r"свой GPU (\S*) ?([\d.]+) ГБ: нужно ([\d.]+) ГБ — ", r"own GPU \1 \2 GB: needs \3 GB — "),
    (r"по семье (\S+): ", r"by the family \1: "),
    (r"ОЦЕНКА снизу: ([\d.]+)B параметров × ([\d.]+) байт \(FP8\) = ([\d.]+) ГБ одних весов \(([^)]*)\); числа VRAM вендор не назвал",
     r"LOWER-BOUND ESTIMATE: \1B parameters × \2 byte (FP8) = \3 GB for the weights alone (\4); the vendor names no VRAM figure"),
    (r"свой GPU: ", "own GPU: "),
    (r"нужны открытые веса: ", "open weights required: "),
    (r"веса открыты у семьи, у варианта не записаны", "weights open for the family, not recorded for the variant"),
    (r"весов нет: только API", "no weights: API only"),
    (r"о весах не записано", "nothing recorded about weights"),
    (r"веса открыты", "weights open"),
    (r"веса: ", "weights: "),
    # Восьмой круг: лицензия бывает фразой («openrail++ — так объявлено…»), не словом.
    (r"лицензия весов (.+?) на странице весов", r"weights licence \1 on the weights page"),
    (r"ни лицензии на странице весов, ни строки open_weights", "neither a licence on the weights page nor an open_weights row"),
    (r"НЕ влезает в память GPU", "does NOT fit the GPU memory"),
    (r"влезает в память GPU", "fits the GPU memory"),
    (r"сколько памяти нужно — не записано", "how much memory is needed is not recorded"),
    (r"память: ", "memory: "),
    (r" — нужно ([\d.]+) ГБ при ([\d.]+) ГБ", r" — needs \1 GB of \2 GB"),
    (r"источники расходятся в (\S+): (.+) — сторона не выбирается", r"sources disagree on \1: \2 — no side is taken"),
    # --- справка: разворот спрошенного и ответ семьи (attrfamily.как_отвечено,
    # advice._ответ_семьи) — валидатор 5-го круга нашёл их по-русски в
    # английском ответе.
    (r"спрошено ('[^']*'), а записано под именами: (.+?)\. Единицы у них РАЗНЫЕ и между собой не переводятся — сравнивать значения можно только внутри одного имени\.",
     r"asked \1, recorded under the names: \2. Their units DIFFER and do not convert into each other — compare values only within one name."),
    (r"спрошено ('[^']*'), а записано под именем ('[^']*') — единица ответа в этом имени, не в вопросе\.",
     r"asked \1, recorded under the name \2 — the unit of the answer is in that name, not in the question."),
    (r"о самой ('[^']*')((?:\.[\w.\-]+)?) не записано ничего; ответ — из утверждений вариантов семьи \(([^)]*)\): (\d+) из (\d+) в family_claims, каждое помечено, О КАКОМ ИМЕНИ оно\. Это НЕ измерение спрошенной модели\.",
     r"nothing is recorded about \1\2 itself; the answer comes from the family's variants (\3): \4 of \5 in family_claims, each labelled with the NAME it is about. This is NOT a measurement of the model asked about."),
    (r"о самой ('[^']*')((?:\.[\w.\-]+)?) не записано ничего; ответ — из утверждений семьи \(([^)]*)\): (\d+) из (\d+) в family_claims, каждое помечено, О КАКОМ ИМЕНИ оно\. Это НЕ измерение спрошенной модели\.",
     r"nothing is recorded about \1\2 itself; the answer comes from the family (\3): \4 of \5 in family_claims, each labelled with the NAME it is about. This is NOT a measurement of the model asked about."),
    (r" Спорно: ", " Contested: "),
    (r"ВНИМАНИЕ: ", "WARNING: "),
    # --- отказ SSRF и разбор хоста (studio/mcp/fetch.py)
    (r"(\S+) лежит во внутренней сети (\S+)", r"\1 lies in the internal network \2"),
    (r"(\S+) — не публичный адрес", r"\1 is not a public address"),
    (r"(\S+) — служебное внутреннее имя", r"\1 is a reserved internal name"),
    (r"('[^']*') похоже на IP-адрес, но адресом не является \(invalid IP literal\)", r"\1 looks like an IP address but is not one (invalid IP literal)"),
    (r"('[^']*') не похоже на имя хоста", r"\1 does not look like a host name"),
    (r"('[^']*') не IP-адрес", r"\1 is not an IP address"),
    (r"('[^']*') не разбирается как адрес: ", r"\1 does not parse as an address: "),
    (r"('[^']*'): схема ('[^']*'), а пробуются только http и https", r"\1: scheme \2, and only http and https are probed"),
    (r"адрес не разбирается: ", "the address does not parse: "),
    (r"схема ('[^']*'): запрашиваются только http и https", r"scheme \1: only http and https are requested"),
    (r"в адресе нет хоста", "the address has no host"),
    (r"^пустая строка$", "an empty string"),
    # --- вердикты потолка в смете (planner: цена ролика) — валидатор 5-го круга
    (r" — ПОТОЛОК ([\d.]+) ПРЕВЫШЕН \(usd\): наименьшая известная стоимость ([\d.]+) против ([\d.]+) даже на самых дешёвых тарифах, это дороже в ([\d.]+) раза",
     r" — CEILING \1 EXCEEDED (usd): the least known cost is \2 vs \3 even on the cheapest tiers, \4 times over"),
    (r" — и это без шагов, у которых цены нет или она нижняя граница",
     " — and that is without the steps that have no price or only a lower bound"),
    (r" — ПОТОЛОК ([\d.]+) ПРЕВЫШЕН \(([^)]*)\): ([\d.]+) против ([\d.]+), это дороже в ([\d.]+) раза",
     r" — CEILING \1 EXCEEDED (\2): \3 vs \4, \5 times over"),
    (r" — в потолок ([\d.]+) влезает только нижний край неоднозначных ставок \(([\d.]+) usd\); по наибольшей ([\d.]+) usd — ПРЕВЫШЕН\. Не проверить",
     r" — only the lower edge of the ambiguous rates fits the ceiling \1 (\2 usd); at the highest, \3 usd — EXCEEDED. Cannot be checked"),
    (r" — ПОТОЛОК ([\d.]+): работа столько не стоит: самый дешёвый записанный кандидат шага (\S+) стоит ([\d.]+) (\w+)",
     r" — CEILING \1: the work does not cost that little: the cheapest recorded candidate of step \2 costs \3 \4"),
    (r"ПРЕВЫШЕН — наименьшая известная стоимость ([\d.]+) usd", r"over budget — the least known cost is \1 usd"),
    (r"шаг один стоит ([\d.]+) usd \(", r"this step alone costs \1 usd ("),
    (r"\) — ВЫШЕ потолка ([\d.]+) usd на весь ролик", r") — ABOVE the ceiling \1 usd for the whole clip"),
    (r"\) — ВЫШЕ потолка ([\d.]+) usd на шаг", r") — ABOVE the ceiling \1 usd per step"),
    (r"; и после перевыбора ([\d.]+) usd ВЫШЕ потолка ([\d.]+) usd — дешевле можно только ниже по доводам",
     r"; and after re-selection \1 usd is ABOVE the ceiling \2 usd — cheaper is only lower on evidence"),
    (r"; юрисдикцию не спрашиваем — отодвинутая лицензией модель не выиграла бы и при ответе («Q»): ",
     r"; jurisdiction not asked — the model pushed aside by its licence would not win even with the answer \1: "),
    (r"веса семьи (\S+): ", r"family weights \1: "),
    (r"; что этот вариант — опубликованный чекпойнт, в базе НЕ записано",
     "; that this variant is a published checkpoint is NOT recorded in the base"),
    # --- смета дороже потолка (planner.дороже_потолка)
    (r"смета дороже потолка: наименьшая известная стоимость ([\d.]+) usd против потолка ([\d.]+) usd, в ([\d.]+) раза; ",
     r"the estimate is over the ceiling: the least known cost is \1 usd against a ceiling of \2 usd, \3 times over; "),
    (r"смета дороже потолка: наименьшая известная стоимость ([\d.]+) usd против потолка ([\d.]+) usd; ",
     r"the estimate is over the ceiling: the least known cost is \1 usd against a ceiling of \2 usd; "),
    # --- страница полного плана (server.page_full_plan)
    (r"\[страница полного плана: шагов (\d+) из (\d+), подробно — куски (\d+)\.\.(-?\d+) из (\d+); следующая страница offset=(\d+)\]",
     r"[page of the full plan: steps \1 of \2, in full — chunks \3..\4 of \5; next page offset=\6]"),
    (r"\[страница полного плана: шагов (\d+) из (\d+), подробно — куски (\d+)\.\.(-?\d+) из (\d+); последняя страница\]",
     r"[page of the full plan: steps \1 of \2, in full — chunks \3..\4 of \5; last page]"),
)


#: ОБРЫВКИ ШАБЛОНОВ — единицы цены, связки. Идут ПОСЛЕ целых оборотов и в
#: записанном порядке: обрывок, применённый раньше, съел бы середину оборота
#: («usd за second» внутри «нижняя цена … usd за second (…) укладывается»).
EN_FRAGMENTS: tuple[tuple[str, str], ...] = (
    # формы цены (до 4-го круга — `planner.ФОРМЫ_ПО_АНГЛИЙСКИ`)
    (r"ffmpeg или монтажная программа \(не модель\)", "ffmpeg or an editing app (not a model)"),
    (r"0 usd \(не модель\)", "0 usd (not a model)"),
    (r"видео сводится с отдельными дорожками: ", "the video is mixed with separate tracks: "),
    (r"озвучка за кадром", "off-screen voiceover"),
    (r"за один прогон ролик не отдаёт", "cannot deliver the clip in one run"),
    (r"ролик собирается из нескольких клипов", "the clip is assembled from several clips"),
    (r"ролик ([\d.]+) с ДЛИННЕЕ предела ([\d.]+) с", r"clip \1 s is LONGER than the \2 s limit"),
    (r"предел ([\d.]+) с: ", r"limit \1 s: "),
    (
        r"о речи на языке брифа \(([^)]*)\) у (\S+) ничего не записано — проверить пробным "
        r"прогоном до заказа",
        r"nothing is recorded about \2 speaking the brief's language (\1) — "
        r"test it with a trial run before ordering",
    ),
    (r"лицензия СЕМЬИ (\S+) исключает вашу территорию", r"the licence of the FAMILY \1 EXCLUDES your territory"),
    (r"лицензия СЕМЬИ (\S+) исключает территории ", r"the licence of the FAMILY \1 excludes territories "),
    (r"лицензия СЕМЬИ (\S+) исключает ", r"the licence of the FAMILY \1 excludes "),
    (r"лицензия семьи исключает территории, у варианта не записана", "the family's licence excludes territories; the variant has none recorded"),
    (
        r"лицензия для варианта (\S+) в базе НЕ записана — перенесена осторожность семьи, а не факт",
        r"no licence is recorded for the variant \1 — the family's caution is carried over, not a fact",
    ),
    (r"лицензия ИСКЛЮЧАЕТ вашу территорию", "the licence EXCLUDES your territory"),
    (r"лицензия исключает территории ", "the licence excludes territories "),
    (r"лицензия исключает ", "the licence excludes "),
    (r"; ваша \(([^)]*)\) не исключена", r"; yours (\1) is not excluded"),
    (r" — где работает заказчик\?", " — where will you use it?"),
    (r"порог выручки ", "revenue threshold "),
    (r" — выше него нужна отдельная лицензия", " — above it a separate licence is needed"),
    (
        r"лицензия записана о ВЕСАХ \(самостоятельный запуск\); при доступе через API-площадку "
        r"действуют условия площадки — прочитать их отдельно",
        "the licence recorded is for the WEIGHTS (self-hosting); through an API platform its own "
        "terms apply — read them separately",
    ),
    (
        r"это лицензия ВЕСОВ \(самостоятельный запуск\); условия API-площадки — другой документ: "
        r"в базе НЕ записаны — переносятся ли на API исключения весов, неизвестно",
        "this is the WEIGHTS licence (self-hosting); the API platform's terms are another document: "
        "NOT recorded in the base — whether the weights' exclusions carry over to the API is unknown",
    ),
    (
        r"это лицензия ВЕСОВ \(самостоятельный запуск\); условия API-площадки — другой документ: ",
        "this is the WEIGHTS licence (self-hosting); the API platform's terms are another document: ",
    ),
    (r" — при условии: ", " — when: "),
    (r"текст в кадре", "text in frame"),
    (r"USD в год", "USD a year"),
    (r"usd за шаг: ", "usd per step: "),
    (r"; дешевле: ", "; cheaper: "),
    (r"через (\S+) — ", r"via \1 — "),
    (r"; другие маршруты: ", "; other routes: "),
    (r"ИСТОЧНИКИ РАСХОДЯТСЯ: ", "SOURCES DISAGREE: "),
    (r"\) против ", ") vs "),
    (r" — в смету взято ", " — the estimate takes "),
    (r"\(ступень (\w+), из равных по ступени — дороже\)", r"(\1 tier; of equal tiers, the dearer)"),
    (r"\(ступень (\w+)\)", r"(\1 tier)"),
    (
        r"usd за прогон \(сколько секунд даёт прогон — не записано\)",
        "usd per run (seconds per run not recorded)",
    ),
    # Реестр эндпоинтов (пятый круг): основание длины прогона, метки строк, ноты отсева.
    (
        r"\(прогон = ([\d.]+) с; длина прогона — семья (\S+): [\d.]+ с\)",
        r"(run = \1 s; run length taken from the family \2)",
    ),
    (
        r"\(прогон = ([\d.]+) с; длина прогона не записана ни у модели, ни у семьи — допущено [\d.]+ с "
        r"\(осторожно: больше прогонов\)\)",
        r"(run = \1 s; ASSUMED — no run length recorded for the model or its family, cautious: more runs)",
    ),
    (
        r"длина прогона не записана ни у модели, ни у семьи — допущено ([\d.]+) с \(осторожно: больше прогонов\)",
        r"no run length recorded for the model or its family — \1 s assumed (cautious: more runs)",
    ),
    (r"длина прогона — семья (\S+): ([\d.]+) с", r"run length from the family \1: \2 s"),
    # Интеграция пятого круга: вес, перенесённый у семьи (`hardneed.weights_stance`).
    # СТОИТ ПОСЛЕ правил длины прогона: раньше них он съедал «семья X:» внутри
    # «(прогон = 10 с; длина прогона — семья X: 10 с)», и та оставалась русской.
    (r"(?<![а-яё])семья (\S+): ", r"family \1: "),
    # Ключ сравнения кандидатов (`why_not`): поле-флаг печатается «да»/«нет».
    (r"\(да vs нет\)", "(yes vs no)"),
    (r"\(нет vs да\)", "(no vs yes)"),
    (r"\(нет vs ", "(no vs "),
    (r" vs нет\)", " vs no)"),
    (r"\bимя эндпоинта \(", "endpoint name ("),
    (r"шагов выведено (\d+), из них без единого кандидата (\d+): модель по умолчанию не подставляется",
     r"steps derived \1, of them without a single candidate \2: no default model is substituted"),
    (r"о модели в базе (\d+) утверждений при пороге (\d+): опереть шаг не на что",
     r"the base holds \1 statements about the model, the threshold is \2: nothing to rest the step on"),
    (r"реестр: работа модели не установлена, а эндпоинты этой работы известны",
     "registry: the model's job is not established, and endpoints of this job are known"),
    (r"реестр эндпоинтов", "endpoint registry"),
    (r"применимость семьи (\S+)", r"applicability lent by the family \1"),
    (r"работа не установлена реестром", "job not established by the endpoint registry"),
    (
        r"узел семьи: вариантов в базе (\d+), своей цены и идентификатора площадки нет",
        r"a family node: \1 variants in the base, no own price and no platform id",
    ),
    # --- шестой круг: реестр (маршрут), цена (кадры, вычисление), ничья по цене
    (
        r"маршрута нет: ни идентификатора площадки, ни строки цены, ни страницы API вендора, "
        r"ни страницы весов с лицензией",
        "no route: no platform id, no price row, no vendor API page, no weights page with a licence",
    ),
    (r"частота не названа, допущено", "fps not named, assumed"),
    (r"([\d.]+) с = ([\d.]+) мин: ", r"\1 s = \2 min: "),
    (r"\(блок = ([\d.]+) мин\)", r"(block = \1 min)"),
    (r"⌉ Мп\b", "⌉ MP"),
    (r"с ролика × ([\d.]+) с вычисления/с = ([\d.]+) с GPU", r"s of video × \1 compute-s per s = \2 GPU-s"),
    (
        r"заказанный кадр родным не отдаёт ни один кандидат — ближайший родной \+ ",
        "no candidate delivers the frame asked natively — the nearest native + ",
    ),
    (r"\bполной цены шага нет\b", "no full price for the step"),
    (r"\bцена шага записана\b", "the step's price is recorded"),
    (r"реестр: делает (.+?) \(([\w-]+)\), а шагу нужна (.+)$", r"registry: does \1 (\2), the step needs \3"),
    # --- интеграция шестого круга: что правит шаг «правка видео» (`spec.edit`)
    (
        r"реестр: эндпоинт делает НОВОЕ видео \(продление / по референсу / по движению / черновик\), "
        r"а шагу нужна правка вашего ролика",
        "registry: the endpoint makes a NEW video (extend / reference / motion / draft), "
        "and the step needs an edit of your footage",
    ),
    (r"правка: умеет (.+?), а нужно (.+)$", r"edit: does \1, the step needs \2"),
    (r"\bне названо\b", "not named"),
    (r"\(прогон = 1 кадр\)", "(run = 1 image)"),
    (r"\(прогон = ([\d.]+) с\)", r"(run = \1 s)"),
    (r"usd за первые ([\d.]+) с", r"usd for the first \1 s"),
    (r"\[(\d+p) со звуком\]", r"[\1 with audio]"),
    (r"прогон\(ов\)", "run(s)"),
    (r"кадр\(ов\)", "image(s)"),
    (r"клон\(ов\)", "clone(s)"),
    (r"посчитана только плата за клон: прочие ставки шага к брифу не привязались",
     "only the clone fee is counted: the step's other rates did not bind to the brief"),
    (r"знаков", "chars"),
    (r"usd за 1000_chars", "usd per 1000 chars"),
    (r"usd за знак", "usd per char"),
    (r"usd за compute_second\b", "usd per compute second (GPU time, not video time)"),
    (r"usd за (character|minute|second|megapixel|generation|image|run|step|1000_chars|token|video|clip|clone)\b",
     r"usd per \1"),
    (r"usd/мин", "usd/min"),
    (r"usd/с\b", "usd/s"),
    (r"(\d) с\b", r"\1 s"),
    (r"(\d) Мп\b", r"\1 MP"),
    (r"([\d.]+) секунд\b", r"\1 seconds"),
    (r"путь к креативу не назван", "no path to the creative was given"),
    (r" — это адрес в сети, а не путь к файлу на диске", " is a web address, not a path to a file on disk"),
    (r" — это каталог, а не файл", " is a directory, not a file"),
    (r" существует, но это не обычный файл", " exists but is not a regular file"),
    (r"по пути (.+) файла нет", r"nothing at \1"),
    (r"не менее ", "at least "),
    (r"ставки шагов = ", "step rates = "),
    (r"(\S+) через (\S+): ", r"\1 via \2: "),
    (r" против ", " vs "),
    (r"длительность: ", "duration: "),
    (r"кадр: ", "frame: "),
    (r", цена: ", ", price: "),
    (r"\. выбран ", ". chose "),
    (r"(?<![\w-])семья (\S+): ", r"family \1: "),
    (r" ВЫШЕ потолка ", " ABOVE the ceiling "),
    (r" на весь ролик", " for the whole clip"),
    (r"\bи\b", "and"),
    # ОБРЫВОК ШАБЛОНА В КОНЦЕ ОБРЕЗАННОЙ СТРОКИ (восьмой круг: «…; время…»):
    # обрезка `clip` прошла по русской форме ДО перевода, и целый оборот
    # таблицы уже не совпадает. Обрывок своей формы — не цитата: снимается.
    (r"; [а-яё][а-яё ]*…", "; …"),
)


#: ЯРЛЫКИ В «ЁЛОЧКАХ», КОТОРЫЕ ПИШЕМ МЫ, А НЕ ИСТОЧНИК: имена полей ключа
#: отбора (`planner.KEY_FIELDS`, «разошлись по «…»»), «за что» бюджета.
#: «Ёлочки» здесь — оформление шаблона, а не цитата; тест сверяет, что у
#: каждого поля `KEY_FIELDS` ярлык есть.
LABELS_EN: dict[str, str] = {
    "требования заказчика (свой GPU, качество) подтверждены записью, а не молчанием":
        "customer's hard requirements (own GPU, quality) confirmed by a record, not by silence",
    "качество": "quality",
    # Ответ заказчика, который планировщик приводит в «ёлочках» (нота о юрисдикции).
    "не исключена": "not excluded",
    "нельзя ли этим воспользоваться": "can it be used at all",
    "делает ли модель эту работу, а не соседнюю": "does the model do this job, not a neighbouring one",
    "принимает ли кадр": "does it accept the frame",
    "влезает ли по длительности": "does it fit the duration",
    "положение по цене": "price position",
    "лицензия исключает территории, а юрисдикция заказчика не названа":
        "the licence excludes territories and the customer's jurisdiction is not named",
    "отдаёт ли заказанный кадр сам, без апскейла": "does it deliver the ordered frame itself, without upscaling",
    "модель сообщества (воркфлоу, LoRA, мёрж), а не продукт": "a community model (workflow, LoRA, merge), not a product",
    "вытеснена более новым поколением": "superseded by a newer generation",
    "свидетельство на заявленном условии: за / не записано / против":
        "evidence on your stated condition: for / not recorded / against",
    "за на заявленном условии": "for, on your stated condition",
    "на заявленном условии не записано": "nothing recorded on your stated condition",
    "против на заявленном условии": "against, on your stated condition",
    "записанный провал против объявленной хорошей новости без провалов":
        "a recorded failure against declared good news with no failures",
    "провалов не записано, и есть хорошая новость (объявленная или чистое измерение)":
        "no failure recorded, and there is good news (declared, or a clean measurement)",
    "записан провал, или хорошей новости нет": "a failure is recorded, or there is no good news",
    "сколько прогонов (кусков) нужно на ролик": "how many runs (chunks) the clip needs",
    "знак измеренного: чисто / спорно / только плохое / молчание":
        "sign of what was measured: clean / disputed / only bad / silence",
    "строк применимости ЗА модель": "applicability rows FOR the model",
    "строк применимости всего": "applicability rows in total",
    "есть ли полная цена шага (при равных доводах цена записанная старше незаписанной)": "is the step's full price recorded (at equal evidence a recorded price beats none)",
    "цена шага записана": "the step's price is recorded",
    "полной цены шага нет": "no full price for the step",
    "сколько подтверждено записью: входы, кадр, длительность": "how much is confirmed by records: inputs, frame, duration",
    "утверждений по якорям операции": "statements on the operation's anchors",
    "имя модели несёт якорь": "the model name carries an anchor",
    "строк способности": "capability rows",
    "имя — только для воспроизводимости порядка, НЕ довод (равенство всего прочего печатается как ничья)":
        "name — only to keep the order reproducible, NOT a reason (equality on everything else prints as a tie)",
    "за что": "per what",
    "снимок + голос -> говорящее видео": "photo + voice -> talking video",
}


# ---------------------------------------------------------------------------
# RU: английские шаблоны (справка, отказы) -> русские.
# ---------------------------------------------------------------------------

RU: tuple[tuple[str, str], ...] = (
    # --- пробел в записанном (advice: ветка «атрибут не записан»)
    (r"nothing is recorded about (\S+)\. The model itself IS in the fact base, so this is a gap in what was recorded, not an unknown name\.",
     r"о \1 ничего не записано. Сама модель В базе фактов есть, так что это пробел в записанном, а не незнакомое имя."),
    (r"(\d+) of (\d+) attribute\(s\) rest on blog-tier or stale sources only, and repetition is not corroboration\. The model itself IS in the fact base, so this is a gap in what was recorded, not an unknown name\.",
     r"атрибутов \1 из \2 стоят только на источниках ступени blog или устаревших, а повтор — не подтверждение. Сама модель В базе фактов есть, так что это пробел в записанном, а не незнакомое имя."),
    (r" Recorded attributes for this model \((\d+)\): ", r" Записанные атрибуты этой модели (\1): "),
    (r", … and (\d+) more\.", r", … и ещё \1."),
    (r"the model itself is unusable: ", "сама модель непригодна: "),
    # --- заявленные условия (capability.condition_state, шестой круг)
    (r"\bfor — (\S+): ", r"за — \1: "),
    (r"\bagainst — (\S+): ", r"против — \1: "),
    (r"nothing recorded on ", "на условии ничего не записано: "),
    (r" The base does hold (.+?) — if that is the same model under another name, ask again by that id\.",
     r" В базе есть \1 — если это та же модель под другим именем, спросите по нему."),
    # --- смежное, не ответ (advice, валидатор 5-го круга)
    (r"RELATED, NOT AN ANSWER: recorded for ('[^']*') under the same topic as ('[^']*'), but each answers a different question and none is counted as answering ('[^']*'): (.+?) \(in substitutes\)\.",
     r"СМЕЖНОЕ, НЕ ОТВЕТ: у \1 записано на ту же тему, что \2, но каждое отвечает на другой вопрос, и ничто из этого не считается ответом на \3: \4 (в substitutes)."),
    # --- отказ SSRF (fetch_url по-русски)
    (r"('[^']*') is refused before sending: (.+?)\. Requests from a tool call never go to private, loopback, link-local or metadata addresses\. Nothing was sent and nothing was recorded in the denial journal\.",
     r"\1 отвергнут до отправки: \2. Запросы инструмента не ходят на частные, петлевые, локальные и служебные (metadata) адреса. Ничего не отправлено и ничего не записано в журнал отказов."),
    (r"('[^']*') is not an http\(s\) URL, so nothing was attempted", r"\1 — не адрес http(s), поэтому ничего не запрашивалось"),
    # --- потолок ответа и листание плана (server)
    (r"plan_pipeline — call again with the same brief/spec, full=True and offset=page\.next_offset \(the next chunk of steps and plan fields not yet shown in full\); or full=False for the compact plan",
     "plan_pipeline — тот же бриф/spec, full=True и offset=page.next_offset (следующий кусок шагов и полей плана, ещё не показанный целиком); или full=False — краткий план"),
    (r"\[page of the full answer: attributes (\d+)\.\.(\d+) of (\d+); next page offset=(\d+)\]",
     r"[страница полного ответа: атрибуты \1..\2 из \3; следующая страница — offset=\4]"),
    (r"\[page of the full answer: attributes (\d+)\.\.(\d+) of (\d+); last page\]",
     r"[страница полного ответа: атрибуты \1..\2 из \3; последняя страница]"),
    (r"(\d+) value\(s\) recorded, but every source is blog tier \((\d+) of them\)\. Repetition is not corroboration: blogs quoting each other are one source\.",
     r"значений записано: \1, но все источники — ступени blog (\2). Повтор — не подтверждение: блоги, цитирующие друг друга, — один источник."),
    (r"; (\d+) source\(s\) older than (\d+) days", r"; источников старше \2 дн.: \1"),
    (r"; (\d+) of (\d+) source\(s\) were NOT read — known through somebody else's summary, not the page itself",
     r"; не прочитано источников: \1 из \2 — известны по чужому пересказу, а не по самой странице"),
    (r"same tier, older statement \(([^)]*) vs ([^)]*)\) — may describe an earlier version or another endpoint",
     r"та же ступень, утверждение старше (\1 против \2) — может описывать прежнюю версию или другой эндпоинт"),
    (r"endpoint scope: (\S+) reports the limit of ITS endpoint, not of the model",
     r"область эндпоинта: \1 сообщает предел СВОЕГО эндпоинта, а не модели"),
    (r"lower tier \((\w+)\)", r"ступень ниже (\1)"),
    (r"^card is silent$", "карточка молчит"),
    (r"^card contradicts$", "карточка противоречит базе"),
    (r"the card leaves (\S+) unset while the base holds (\d+) recorded value\(s\)\. The card is behind the base\.",
     r"в карточке поле \1 не заполнено, а в базе записано значений: \2. Карточка отстала от базы."),
    (r"the card states (\S+)=(.+?) and no recorded source says so\. Neither is corrected here; both are shown\.",
     r"карточка говорит \1=\2, и ни один записанный источник этого не говорит. Здесь не исправляется ни то, ни другое; показаны оба."),
    (r"(\d+) claim\(s\) older than (\d+) days and (\d+) ", r"утверждений старше \2 дн.: \1, и \3 "),
    (r"(\d+) attribute\(s\) are prices or facts about a video model whose newest source is older than its freshness window \((\d+) days for prices and most facts, (\d+) for licence, architecture and maximum specs\): ",
     r"атрибутов \1 — цены или факты о видеомодели, у которых свежайший источник старше окна свежести (\2 дн. для цен и большинства фактов, \3 — для лицензии, архитектуры и предельных характеристик): "),
    (r"\. Possibly stale — re-check before quoting\.", ". Возможно, устарело — перепроверьте перед цитатой."),
    (r"highest tier present \((\w+)\) disagrees with itself; newest statement taken", r"высшая из имеющихся ступеней (\1) спорит сама с собой; взято новейшее утверждение"),
    (r"highest tier present \((\w+)\)", r"высшая из имеющихся ступеней (\1)"),
    (r"full=True for everything, or attribute=<name> for one attribute in full",
     "full=True — всё, или attribute=<имя> — один атрибут целиком"),
    (r"card is (\d+) days old, past the (\d+)-day limit", r"карточке \1 дн., срок — \2 дн."),
    (r"end of life ([\d-]+), (\d+) days away", r"конец жизни \1, через \2 дн."),
    (r"(\S+) reached end of life on ([\d-]+)", r"\1: конец жизни наступил \2"),
    (r"(\S+) is retired; ", r"\1 снята с обслуживания; "),
    (r"^callable$", "вызывается"),
    (r"(\d+) attribute\(s\) answered from (\d+) recorded statement\(s\) across (\d+) source\(s\), (\d+) of them only weakly\.",
     r"отвечено атрибутов: \1, по записанным утверждениям: \2, источников: \3, из них слабых: \4."),
    (r"('[^']*') is not in the registry: the registry axis \(hand-checked availability cards\) is maintained for (\d+) models only and is NOT maintained for this one\. That says nothing about whether the model exists or can be called; nothing was checked on this axis\.",
     r"\1 нет в реестре: ось реестра (карточки доступности, сверенные вручную) ведётся только для \2 моделей, и для этой НЕ ведётся. О том, существует ли модель и можно ли её вызвать, это не говорит ничего; по этой оси не проверено ничего."),
    (r"The FACT BASE is a different and much larger set: it holds (\d+) ids, among them ", r"БАЗА ФАКТОВ — другой и куда больший набор: в ней \1 имён, среди них "),
    (r"Availability is a SEPARATE axis, and it says ", "Доступность — ОТДЕЛЬНАЯ ось, и она говорит "),
    (r"; (\d+) source\(s\) have no reading recorded either way", r"; у источников (\1) не записано, читали ли их"),
    (r", from (\d+) source\(s\), best tier (\w+)", r", источников: \1, лучшая ступень \2"),
    (r": (\d+) value\(s\)", r": значений \1"),
    (r"(\d+) attribute\(s\) are prices or facts about a video model whose newest source is older than its freshness window \((\d+) days for prices and most facts, (\d+) for licence, architecture and maximum specs\); check before quoting",
     r"атрибутов (\1) — цены или факты о видеомодели, у которых свежайший источник старше окна свежести (\2 дн. для цен и большинства фактов, \3 — для лицензии, архитектуры и предельных характеристик); проверьте перед цитатой"),
    (r"(\d+) of (\d+) findings about the class, strongest tier first\. These were said about the field or about a vendor's line, NOT measured on this model\.",
     r"находок о классе: \1 из \2, сильнейшая ступень первой. Это сказано о поле или о линейке вендора, НЕ измерено на этой модели."),
    (r"sources disagree on (\S+): ", r"источники расходятся по \1: "),
    (r"sources disagree on (\S+)\. Every side is returned with its URL and its date; nothing here votes, averages or takes the newest\.",
     r"источники расходятся по \1. Каждая сторона возвращена со своим адресом и датой; здесь никто не голосует, не усредняет и не берёт новейшее."),
    (r"Reported as contested rather than resolved: picking one would invent a confidence nobody published\.",
     "Показано как спор, а не решение: выбрать одно значило бы выдумать уверенность, которую никто не публиковал."),
    (r"RECOMMENDED \(by the tier ladder, not a vote\): ", "РЕКОМЕНДОВАНО (по лестнице ступеней, не голосованием): "),
    (r" — highest tier present \((\w+)\) disagrees with itself; newest statement taken; the others are context in `recommended\.others`\.",
     r" — высшая ступень (\1) спорит сама с собой; взято новейшее утверждение; остальные — контекст в `recommended.others`."),
    (r" — highest tier present \((\w+)\); the others are context in `recommended\.others`\.",
     r" — высшая из имеющихся ступеней (\1); остальные — контекст в `recommended.others`."),
    (r"Nothing was checked, which is not the same as nothing being wrong\.", "Не проверено ничего, а это не то же, что «всё в порядке»."),
    (r"is in neither the registry nor the fact base under that exact name", "нет ни в реестре, ни в базе фактов под этим точным именем"),
    (r"Search the web and call `record_model_fact` to put it there", "Поищите в сети и позовите `record_model_fact`, чтобы записать"),
    (r"Search the web and call", "Поищите в сети и позовите"),
    (r"to put it there", "чтобы записать"),
    (r"the same call with offset=next_offset gives the next attributes", "тот же вызов с offset=next_offset даёт следующие атрибуты"),
    (r"call again with full=True for everything, or attribute=<name> for one attribute in full",
     "позовите снова с full=True — всё, или с attribute=<имя> — один атрибут целиком"),
    (r"no model was named, so nothing was looked up", "модель не названа, поэтому ничего не искали"),
    (r"card is second-hand: no vendor document was read", "карточка из вторых рук: документ вендора не читали"),
    (r"price band is ", "ценовой коридор: "),
    (r"is a premium tier on", "— премиальный тариф на"),
    (r"re-selected within the same evidence band \(every key above the row counts equal, price aside\): ",
     "перевыбрано внутри полосы доводов (всё старше счёта строк — то же, кроме цены): "),
    (r"total ([\d.]+) usd is over the clip ceiling ([\d.]+) usd", r"сумма \1 usd выше потолка ролика \2 usd"),
    # --- понято как (`brief_spec.echo`), интеграция круга 4
    (r"call plan_pipeline again with spec=\{\.\.\.\}: any field named there overrides what was read from the text \(fields: ([^)]*)\)",
     r"вызовите plan_pipeline ещё раз со spec={...}: любое названное там поле перекрывает прочитанное из текста (поля: \1)"),
    (r"resolution not named — (\S+) assumed \(9:16 ad standard\); pass spec\.resolution to change",
     r"разрешение не названо — принято \1 (стандарт рекламы 9:16); изменить — spec.resolution"),
    (r"resolution not named — (\S+) assumed \(delivery standard\); pass spec\.resolution to change",
     r"разрешение не названо — принято \1 (стандарт сдачи); изменить — spec.resolution"),
    (r"your video's resolution is not named — (\S+) assumed for pricing \(ad delivery standard\), not the cheapest tier; pass spec\.resolution to change",
     r"разрешение вашего видео не названо — для цены принято \1 (стандарт сдачи рекламы), а не самый дешёвый тариф; изменить — spec.resolution"),
    (r"the voice plays over the picture, nobody on screen moves their lips — pass spec\.task='avatar' \(or 'lipsync'\) for an on-screen speaker, or spec\.audio='native'",
     r"голос звучит поверх картинки, губы в кадре не двигаются — для говорящего в кадре передайте spec.task='avatar' (или 'lipsync'), либо spec.audio='native'"),
    (r"the new face/character comes from YOUR reference image — none is named in the brief; attach it, or pass spec\.inputs=\['video', 'photo'\]",
     r"новое лицо/персонаж берётся с ВАШЕГО референса — в брифе его нет; приложите его или передайте spec.inputs=['video', 'photo']"),
    (r"^count named in the brief$", "число названо в брифе"),
    (r"ceil\(([\d.]+) s / ([\d.]+) s max run of the chosen model\)", r"ceil(\1 с / \2 с — предел прогона выбранной модели)"),
    (r"ceil\(([\d.]+) s / ([\d.]+) s assumed shot — the model records no max run\)",
     r"ceil(\1 с / \2 с — принятый шот: предел прогона модели не записан)"),
)


# ---------------------------------------------------------------------------
# Цитаты из базы: перевод НАШЕЙ лексики и глосс к русской цитате оператора.
# ---------------------------------------------------------------------------

#: Значения, которые пишут НАШИ скрипты разбора, а не источник: виды входа и
#: выхода, счётчики HuggingFace, флаги прав Civitai. Это наша лексика, и она
#: переводится целиком; всё прочее — цитата.
VALUE_FORMS_EN: tuple[tuple[str, str], ...] = (
    (r"^(\d[\d ]*) скачиваний, (\d[\d ]*) лайк(?:ов|а)? на HuggingFace$", r"\1 downloads, \2 likes on HuggingFace"),
    (r"^(\d[\d ]*) скачиваний, (\d[\d ]*) лайк(?:ов|а)?$", r"\1 downloads, \2 likes"),
    (r"^(менее|более) (\d+) тыс\. скачиваний$", r"\1 \2k downloads"),
    (r"^менее (\d+k downloads)$", r"fewer than \1"),
    (r"^более (\d+k downloads)$", r"more than \1"),
    (r"^некоммерческая оговорка$", "non-commercial clause"),
    (r"^только для исследований$", "research only"),
    (r"коммерческое использование ограничено: ", "commercial use restricted: "),
    (r"требуется указание автора: ", "attribution required: "),
    (r"производную нельзя перелицензировать: ", "derivatives cannot be relicensed: "),
    (r"производные запрещены: ", "derivatives forbidden: "),
    (r"НЕКОММЕРЧЕСКАЯ: allowCommercialUse пуст — коммерческого права не дано",
     "NON-COMMERCIAL: allowCommercialUse is empty — no commercial right given"),
    (r"НЕ СМОГЛИ ПРОЧИТАТЬ: это указатель git-lfs, а не сам файл", "COULD NOT READ: this is a git-lfs pointer, not the file"),
    (r"НЕ СМОГЛИ ПРОЧИТАТЬ: язык не тот, оговорки не проверены", "COULD NOT READ: wrong language, clauses not checked"),
    (r"^(\d[\d ]*) USD в год$", r"\1 USD a year"),
    (r"^нельзя улучшать другие модели на выходах$", "outputs may not be used to improve other models"),
    (r"^доступна только на тарифе (.+)$", r"available only on the \1 plan"),
)

#: ГЛОССЫ К ЗАПИСЯМ ОПЕРАТОРА: его собственные наблюдения (прогоны, чат
#: владельца, пересказ обсуждений) и его же ноты к источникам. Ключ — начало
#: цитаты (регулярное выражение), значение — короткий английский пересказ.
#: Цитата при этом печатается дословно: глосс — подсказка, а не замена.
GLOSSES: tuple[tuple[str, str], ...] = (
    (r"^Рот читается как вставленный", "the mouth reads as pasted-in on close-ups: teeth and lip edge look wrong"),
    (r"^На крупном плане не ставить без проверки", "do not use on close-ups without checking by eye; filmed input was not checked"),
    (r"^Лицо остаётся тем же человеком", "the face stays the same person from first to last frame; only the mouth area has issues"),
    (r"^На снятом видео держится ВТРОЕ лучше latentsync", "on filmed video it keeps mouth sharpness about three times better than latentsync"),
    (r"^ОГРАНИЧЕНИЕ ВХОДА", "input caveat: the input was synthetic and already moving its lips"),
    (r"^Вход — СНЯТОЕ ВИДЕО ЧЕЛОВЕКА", "input was a filmed human video, not synthetic"),
    (r"^Прогон [\d-]+", "the operator's own run: setup and request id"),
    (r"^Тот же прогон", "same run: frames compared outside the mouth area"),
    (r"^ОПРОВЕРГНУТО", "REFUTED by the operator's own runs"),
    (r"^НЕ СМОГЛИ: на счёте Kling нет средств", "COULD NOT: no balance on the Kling account; the duration limit stayed unmeasured"),
    (r"^ПЕРЕНЕСЕНО", "moved from another attribute: why the measurement did not happen"),
    (r"^один POST", "one POST request"),
    (r"^мелкое лицо в кадре теряет структуру", "a small face in frame loses structure; worse with fast motion"),
    (r"^крупнее кадрировать лицо", "frame the face larger; upscaling to 4K does not fix it"),
    (r"^Пересказ обсуждения", "summary of a community discussion thread"),
    (r"^держит заранее отрисованный текст", "keeps pre-rendered text supplied as an image"),
    (r"^Overall satisfaction", "benchmark scores with the operator's note on rank"),
    (r"^поле лицензии карточки HuggingFace", "licence field of the HuggingFace card"),
    (r"^единица биллинга", "billing unit from the endpoint page"),
    (r"^счётчик HuggingFace", "HuggingFace download/like counter"),
    (r"^цена словами страницы эндпоинта", "price wording on the endpoint page"),
    (r"^страница эндпоинта fal\.ai", "fal.ai endpoint page: status / deprecation"),
    (r"^отозвано", "withdrawn, with the reason"),
    (r"^перезаписано", "rewritten in assembled form"),
    (r"^карточка каталога fal\.ai", "fal.ai catalogue card"),
    (r"^описание модели на fal\.ai", "model description on fal.ai"),
    (r"^описание автора модели", "the model author's description"),
    (r"^флаги прав карточки Civitai", "rights flags of the Civitai card"),
    (r"^настройки из meta", "settings from published meta"),
    (r"^OpenAPI входа эндпоинта", "endpoint input OpenAPI schema"),
    (r"^тело треда|^тред #", "body of a community thread"),
    (r"^прочитан файл", "the file was read"),
    (r"^страница модели на HuggingFace", "model page on HuggingFace"),
    (r"^READ", "read by the operator; reading notes"),
    (r"^Прочитано|^Перечитано", "read by the operator; what the page says"),
    (r"^Снято [\d-]+", "the operator's own measurement"),
    (r"^Не один монолит", "not one monolith but a three-stage pipeline"),
    (r"^Свыше этого порога", "above this revenue threshold a separate licence is needed"),
    (r"^Дата — дата САМОЙ СТРАНИЦЫ", "the date is the page's own date, not today's reading"),
    (r"^commercial — тип лицензии", "commercial — licence type declared by the platform; no licence URL"),
    (r"^ДОСЛОВНО", "verbatim licence quote with the operator's reading"),
    (r"^MiniMax H3 Community License", "MiniMax H3 Community License (not OSI)"),
    (r"^omni-modal", "architecture summary"),
    (r"^MEASURED under approved proposal", "measured under an approved proposal"),
    (r"^`license", "licence fields of the card"),
    (r"^«", "a source quote with the operator's remark"),
    (r"^только T2V", "text-to-video and image-to-video only; reference inputs not accepted"),
)

#: Глосс, когда своего нет: честно — «по-русски, как записано».
GLOSS_DEFAULT = "operator's note in Russian, kept as recorded"


def gloss(текст: str) -> str:
    """Короткий английский пересказ русской цитаты (`GLOSSES`) или общий."""
    t = str(текст or "").strip().lstrip("«")
    for образец, пересказ in GLOSSES:
        if re.search(образец, t):
            return пересказ
    return GLOSS_DEFAULT


def _термины(текст: str, terms: Mapping[str, str]) -> str:
    for ru in sorted(terms, key=len, reverse=True):
        текст = re.sub(rf"(?<![А-Яа-яЁё_]){re.escape(ru)}(?![А-Яа-яЁё_])", terms[ru], текст)
    return текст


def _value_form_en(текст: str) -> str:
    t = текст
    for образец, замена in VALUE_FORMS_EN:
        t = re.sub(образец, замена, t)
    # Перечень видов входа/выхода: «аудио, видео, текст».
    if re.fullmatch(r"[а-яё_, ]+", t) and all(
        ч.strip() in TERMS_EN for ч in t.split(",") if ч.strip()
    ):
        t = ", ".join(TERMS_EN[ч.strip()] for ч in t.split(",") if ч.strip())
    return t


def quote_fact(текст: object, lang: str) -> object:
    """Значение из базы: наша лексика — переводится, цитата — «ёлочки» и глосс.

    По-русски значение возвращается как есть: оно уже на языке ответа или
    это цитата чужого источника, которую не переводят.
    """
    if not isinstance(текст, str) or lang != "en" or not CYR.search(текст):
        return текст
    if GLOSS_MARK in текст:
        return текст  # уже помечено: перевод идемпотентен
    переведено = _value_form_en(текст)
    if not CYR.search(переведено):
        return переведено
    if переведено.startswith("«") and переведено.endswith(("»", "…»")) and "«" not in переведено[1:]:
        тело = переведено
    else:
        тело = f"«{переведено.replace('«', '‹').replace('»', '›')}»"
    return f"{тело} {GLOSS_MARK} {gloss(текст)}]"


def _ярлык(цитата: str) -> str:
    """«…» нашего шаблона — по-английски; «…» источника — как есть."""
    тело = цитата[1:-1]
    if тело in LABELS_EN:
        return f"«{LABELS_EN[тело]}»"
    переведено = _термины(тело, TERMS_EN)
    return f"«{переведено}»" if not CYR.search(переведено) else цитата


def _в_ёлочки(кусок: str, цитаты: list[str]) -> str:
    """'…' с кириллицей внутри — значение из базы. Наша лексика — переводится,
    остальное — цитата: прячется держателем места ДО таблицы, чтобы ни образец,
    ни термин не переписали чужие слова.

    Вложенная цитата раскрывается в ‹…›: «ёлочки» остаются одноуровневыми —
    по ним работает `QUOTE`.
    """

    def заменить(m: re.Match[str]) -> str:
        тело = _ДЕРЖАТЕЛЬ.sub(lambda м: цитаты[int(м.group(1))], m.group(1))
        if not CYR.search(тело):
            return m.group(0)
        переведено = _value_form_en(тело)
        if not CYR.search(переведено):
            return f"'{переведено}'"
        цитаты.append("«" + тело.replace("«", "‹").replace("»", "›") + "»")
        return f"\ue000{len(цитаты) - 1}\ue001"

    return re.sub(r"(?<![\w’])'([^'\n]{1,600}?)'(?![\w])", заменить, кусок)


def _глоссы(текст: str) -> str:
    """К каждой русской цитате в английском тексте — `[ru: …]`, если его нет."""

    def заменить(m: re.Match[str]) -> str:
        цитата = m.group(0)
        if not CYR.search(цитата):
            return цитата
        хвост = текст[m.end() : m.end() + len(GLOSS_MARK) + 1]
        if хвост.lstrip().startswith(GLOSS_MARK):
            return цитата
        return f"{цитата} {GLOSS_MARK} {gloss(цитата[1:-1])}]"

    return QUOTE.sub(заменить, текст)


_ДЕРЖАТЕЛЬ = re.compile("\ue000(\\d+)\ue001")


def _образец(образец: str) -> str:
    """`«Q»` в образце таблицы — «любая цитата» (держатель места цитаты)."""
    return образец.replace("«Q»", "\ue000\\d+\ue001")


#: Таблицы, собранные один раз: длинные образцы раньше коротких — иначе
#: «цена не записана» съест конец более длинного оборота, где она стоит.
_EN = tuple(
    (re.compile(_образец(о)), з)
    for о, з in [*sorted(EN, key=lambda п: -len(п[0])), *EN_FRAGMENTS]
)
_RU = tuple((re.compile(_образец(о)), з) for о, з in sorted(RU, key=lambda п: -len(п[0])))


def _по_таблице(текст: str, таблица: tuple, en: bool) -> str:
    """Таблица — к тексту, где каждая цитата «…» заменена держателем места.

    Образец может перешагнуть цитату (`модель без «аудио» не запускается`) и
    может её захватить (`(«Q»)`), но не может её переписать: цитата
    возвращается на место дословно (по-английски — ярлык шаблона переведён).
    """
    цитаты: list[str] = []

    def спрятать(m: re.Match[str]) -> str:
        цитаты.append(_ярлык(m.group(0)) if en else m.group(0))
        return f"\ue000{len(цитаты) - 1}\ue001"

    t = QUOTE.sub(спрятать, текст)
    if en:
        t = _в_ёлочки(t, цитаты)
    for образец, замена in таблица:
        t = образец.sub(замена, t)
    if en:
        t = _термины(t, TERMS_EN)
    return _ДЕРЖАТЕЛЬ.sub(lambda m: цитаты[int(m.group(1))], t)


def localise(текст: object, lang: str) -> object:
    """Строка шаблона — на язык ответа. Не строка — как есть.

    По-английски: таблица `EN`, потом термины `TERMS_EN`, потом русские
    значения в '…' становятся цитатами «…»; к каждой русской цитате — глосс.
    Цитаты «…» не переписываются ни на одном шаге. По-русски: таблица `RU`.
    """
    if not isinstance(текст, str) or not текст:
        return текст
    if lang == "en":
        if not CYR.search(текст):
            return текст
        return _глоссы(_по_таблице(текст, _EN, True))
    if lang == "ru":
        return _по_таблице(текст, _RU, False)
    return текст


#: ТРИ ИСХОДА (П1) русскими словами -> те же исходы, какими говорит английский
#: ответ (`outcome` верхнего уровня). Восьмой круг: «годно» в
#: `pipeline_price.outcome` английского ответа рядом с «pass» наверху.
OUTCOME_EN: dict[str, str] = {"годно": "pass", "не годно": "fail", "не смогли": "could not measure"}

#: Поля-КОДЫ с именем шага: по-английски рядом кладётся читаемое имя
#: (`step_label`, `<поле>_labels`), сам код не трогается. Восьмой круг:
#: «генерация_видео» без ярлыка в `validator.steps[]`, смете, сборке.
STEP_CODE_KEY = "step"
STEP_LABEL_KEY = "step_label"
STEP_LIST_KEYS: frozenset[str] = frozenset({"steps_without_price", "steps_without_cost"})


def step_label_en(код: str) -> str:
    """Имя шага по-английски: термин `TERMS_EN`, иначе — код словами через таблицу."""
    if код in TERMS_EN:
        return TERMS_EN[код]
    текст = localise(код.replace("_", " "), "en")
    return текст if isinstance(текст, str) and not CYR.search(текст) else код.replace("_", " ")


def localise_payload(
    obj: Any, lang: str, *, _key: str = "", _in_sources: bool = False, _fact: bool = False
) -> Any:
    """Весь ответ — на язык `lang`: коды не трогаются, цитаты помечаются.

    Возвращает НОВЫЙ объект; вход не меняется (его мог закэшировать вызвавший).
    """
    if isinstance(obj, dict):
        out: dict = {}
        for k, v in obj.items():
            ks = str(k)
            if ks in TRANSPORT_SUBTREES:
                out[k] = v
                continue
            близнец = obj.get(ks + EN_SUFFIX)
            # Близнец-список тоже (`options`/`options_en` противоречия брифа,
            # валидатор 5-го круга): раньше брался только строковый.
            if lang == "en" and not ks.endswith(EN_SUFFIX) and (
                isinstance(близнец, str)
                or (isinstance(близнец, list) and isinstance(v, list) and len(близнец) == len(v))
            ):
                v = близнец
            out[k] = localise_payload(
                v,
                lang,
                _key=ks,
                _in_sources=_in_sources or ks == "sources",
                _fact=_fact or ks in FACT_SUBTREES,
            )
        if lang == "en" and not _fact and not _in_sources:
            код = obj.get(STEP_CODE_KEY)
            if isinstance(код, str) and CYR.search(код) and STEP_LABEL_KEY not in obj:
                out[STEP_LABEL_KEY] = step_label_en(код)
            for ks in STEP_LIST_KEYS & {str(k) for k in obj}:
                коды = obj[ks]
                if isinstance(коды, list) and any(isinstance(к, str) and CYR.search(к) for к in коды):
                    out.setdefault(ks + "_labels", [step_label_en(str(к)) for к in коды])
        return out
    if isinstance(obj, (list, tuple)):
        готово = [
            localise_payload(v, lang, _key=_key, _in_sources=_in_sources, _fact=_fact) for v in obj
        ]
        return готово if isinstance(obj, list) else tuple(готово)
    if not isinstance(obj, str):
        return obj
    if _key == "outcome" and lang == "en" and obj in OUTCOME_EN:
        return OUTCOME_EN[obj]
    if _key in CODE_KEYS:
        return obj
    if _fact:
        return quote_fact(obj, lang)
    if lang == "ru" and _key == "requirement":
        # Требование шага: русская половина — наша, английская — поисковые
        # якоря на языке базы. Якоря — цитатой: это слова базы, не перевод.
        return re.sub(r"; ([a-z0-9][a-z0-9 ,\-/]*)$", r"; якоря поиска: «\1»", obj)
    if _key.endswith(EN_SUFFIX):
        # Английский близнец по-русски не переводится, по-английски — дочищается
        # (в нём бывают имена шагов: «генерация_видео: a -> b»).
        return localise(obj, "en") if lang == "en" else obj
    if _key in FACT_KEYS or (_in_sources and _key == "note"):
        return quote_fact(obj, lang)
    return localise(obj, lang)


# ---------------------------------------------------------------------------
# Проверка: что в ответе НЕ на языке ответа (тест и разовый замер — одно).
# ---------------------------------------------------------------------------

#: Английский шаблонный оборот в русском ответе: три слова подряд.
_АНГЛ_ОБОРОТ = re.compile(r"\b[a-z]{2,}(?:\(s\))? [a-z]{2,}(?:\(s\))? [a-z]{2,}\b")
#: Что в русском ответе вырезается перед поиском оборотов: цитаты, адреса,
#: код в обратных кавычках, имена в одинарных кавычках.
_НЕ_ШАБЛОН = re.compile(
    r"\[RESPONSE CUT[^\]]*\]|«[^«»]*(?:»|$)|https?://\S+|`[^`]*`|'(?:[^'\\\n]|\\.)*'|\"(?:[^\"\\\n]|\\.)*\"|\([^()]*=[^()]*\)"
)


def _walk(
    obj: Any, path: str = "", key: str = "", in_sources: bool = False
) -> Iterable[tuple[str, str, str, bool]]:
    """(путь, ключ, строка, внутри-цитаты?) — по всем строкам ответа.

    Последнее поле — «строка из базы»: под `sources` или в поддереве-данных.
    Поддеревья транспорта не обходятся вовсе.
    """
    if isinstance(obj, dict):
        for k, v in obj.items():
            if str(k) in TRANSPORT_SUBTREES:
                continue
            yield from _walk(v, f"{path}.{k}", str(k), in_sources or k == "sources" or k in FACT_SUBTREES)
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _walk(v, f"{path}[{i}]", key, in_sources)
    elif isinstance(obj, str):
        yield path, key, obj, in_sources


def leaks(obj: Any, lang: str) -> list[tuple[str, str]]:
    """(путь, строка) там, где ответ говорит не на языке `lang`.

    en: кириллица вне цитат «…» (коды `CODE_KEYS` не в счёт), и русская
        цитата без английского глосса `[ru: …]`.
    ru: английский шаблонный оборот (три слова подряд) вне цитат, адресов,
        кода и имён; коды, цитаты из базы и поля `*_en` не в счёт.
    """
    out: list[tuple[str, str]] = []
    for path, key, s, in_sources in _walk(obj):
        if key in CODE_KEYS:
            continue
        if lang == "en":
            # Цитата, обрезанная краткой формой на конце строки, — тоже цитата.
            вне = re.sub(r"«[^«»]*$", "", QUOTE.sub("", s))
            if CYR.search(вне):
                out.append((path, s))
                continue
            for m in QUOTE.finditer(s):
                if CYR.search(m.group(0)) and not s[m.end() :].lstrip().startswith(GLOSS_MARK):
                    out.append((path, s))
                    break
        elif lang == "ru":
            if key.endswith(EN_SUFFIX) or key in FACT_KEYS or in_sources:
                continue
            вне = _НЕ_ШАБЛОН.sub(" ", s)
            if _АНГЛ_ОБОРОТ.search(вне):
                out.append((path, s))
    return out
