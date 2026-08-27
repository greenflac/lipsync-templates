# HANDOFF: ветка claude/product-summary-manual-quiz-n5s0gf

Append-only. Каждая запись — что сделано и чем подтверждено.

## 2026-08-26 — сессия 1

**Задача владельца:** (1) человекочитаемое саммари по продукту, (2) большой
подробный мануал «что, почему и как сделано» — до уровня объяснения каждой
переменной техлиду, (3) потом большой интерактивный квиз.

**Сделано:**

- Прочитан весь исходник (17 модулей, ~10 тыс. строк), README (RU+EN), дека
  `docs/deck/lipsync.html`, база эстетик, CI и конфиги.
- Прогнан тестовый набор. Вывод команды
  `python3 -m unittest discover -s lipsync/tests -t .`:
  `Ran 770 tests in 9.831s / OK (skipped=12)`.
  Перед прогоном пришлось поставить `numpy` и `pillow` (в контейнере их не было;
  без них 91 ошибка импорта — это была не поломка кода).
- Написан `docs/MANUAL_ru.md` (770 строк): продукт, экономика, три сквозных
  принципа, карта модулей, восемь ступеней, прибор сборки шаблонов, план кадра,
  ось личности, сборка звука, **сквозной справочник всех констант по 15 модулям**
  с пометками происхождения (ИЗМЕРЕНО/РАСЧЁТ/ВЫБРАНО/НЕПРОВЕРЕНО), тесты, раздел
  границ и долгов, шпаргалка из десяти вопросов техлида.

**Замечено по ходу (НЕ правилось, чужой код — Ц2):**

- `DEBT`: докстринг `fork_e2e.live_kling` говорит «ровно $0.21 за вызов» — это
  цена 3 с; действующая цена ячейки `KLING_PRICE_USD = $0.35` при
  `PRODUCT_SECONDS = 5.0`. Число в коде верное, устарел комментарий. Записано в
  раздел 12 мануала.
- `creative_eval.style` и `lipsync.fork_channels` в дереве отсутствуют: стилевая
  карточка не читается, ось «голова» в `fork_looper` всегда «головы нет».
  Оба случая честно печатаются кодом. Записано в раздел 12.

**Не сделано:** интерактивный квиз — следующий шаг, ждёт слова владельца.

**Артефакт мануала:** `scripts/manual_html.py` рендерит `docs/MANUAL_ru.md` в
одностраничный HTML (`build/manual.html`) — markdown остаётся единственным
источником, HTML пересобирается командой `python3 scripts/manual_html.py`.
Опубликовано: https://claude.ai/code/artifact/ff4e4c94-05c4-4758-8a88-be3cb9bff409

## 2026-08-26 — сессия 1, продолжение: паддинг на входе

**Вопрос владельца:** почему часть результата true 9:16, а часть паддинг; сам
nanobanana-2 не отдаёт 9:16 или это от промта?

**Найденный корень (не модель и не промт — наш собственный вызов):**
`pollinations.compose` — единственный из трёх маршрутов модуля — имел дефолт
`width=768, height=1024` (3:4), тогда как `image` и `images_edit` оба стояли на
`1080×1920`. `live_stylize` размер не передавал вообще. Модель честно вернула
3:4 (`896×1200` = 56×16 × 75×16), и весь паддинг ниже по конвейеру был нашим же
запросом, вернувшимся обратно.

**Сделано:**

- `fork_e2e.STYLED_SIZE = (720, 1280)` — ВЫБРАНО из ИЗМЕРЕННОГО: ровно 9:16
  (720×16 == 1280×9) и обе стороны кратны 16 — сетке, к которой модель снапит.
  `1080×1920` не годится: 1080 не кратно 16, дефект вернулся бы через починку.
- `live_stylize` передаёт размер в `pollinations.compose`.
- Дефолт `compose` приведён к `1080×1920`, как у соседних маршрутов: маршрут
  перестал быть ловушкой.
- `fork_plan.to_plan` возвращает `source: {width, height}` — чтобы вызывающий
  судил стилизатор, не декодируя файл второй раз.
- `stage_stylize`: новая именованная строка `styliser returned the plan`
  (три исхода) и **пропуск аутпейнта, когда `added_share == 0`** — вызов там
  стоил бы генерации и мог перерисовать человека впустую.

**Проверено:**

- `scripts/check`: `ruff check` — All checks passed; `ruff format` — 31 files
  already formatted; `mypy` — Success: no issues found in 31 source files;
  тесты — `Ran 776 tests in 11.372s / OK (skipped=12)` (было 770).
- Мутации константы-решения в обе стороны, каждая роняет тесты:
  `STYLED_SIZE=(1080,1920)` → падают 2; `(768,1280)` → падают 2; убрать передачу
  размера в шлюз → падает 1; откатить дефолт `compose` на 768×1024 → падает 1;
  `if added == 0` → `if added is None` → падают 2. Без мутаций — OK.

**Исправлено в мануале:** прежний пассаж §7.1 утверждал, что при отказе
аутпейнтера паддинг уезжает в Kling. Это неверно: `run()` останавливается на
любом не-`pass`, то есть отказ аутпейнта уже тогда вставал ДО платного вызова.
Раздел переписан по факту.

**НЕПРОВЕРЕНО (Ц4/Ц10):** что модель отдаёт ровно `720×1280`. Нужен живой вызов
с ключом; здесь нет ни ключа, ни доступа к их API. До первого живого прогона
строка `styliser returned the plan` — это и есть тот замер, который его закроет.

## DEBT(2026-08-26): the whole 9:16 repair is UNVERIFIED by a live run

Owner's decision, verbatim: «прогон запиши в долг до завтра».

Nothing in the aspect-ratio work has ever run against the real route. The
Pollinations balance was spent on the measurements that produced the
diagnosis (18 calls), and every call since answers HTTP 402. What exists is
873 green tests and a code path read by eye.

That is the weaker kind of evidence, and it has already failed twice today:
two claims about padding that survived a full test suite were wrong when
someone finally looked at the pixels.

What the run has to settle, in one pass:
1. Does `compose` honour a 1152x2048 request, or answer on its own grid? If
   it answers 768x1376 as measured, the crop takes 0.87% and nothing is
   padded — that is the expected path, not a failure.
2. Is the frame that reaches the paid call free of blurred bands, by eye at
   full resolution, not by a detector?
3. Does Kling return 720x1280 for a template run, as it did for all six
   shipped clips, or does it drift as it did on the earlier runs
   (816x1104, 960x960)?

Until that run: the sentence "no more bands" rests on reading the code, not
on measuring the result. Say so in every report.

## What the owner's own observation settled (2026-08-26)

«когда грузили драйвинг и юзерфото без шаблона — никаких полос не было»

That is the cleanest evidence in the whole investigation, and it is not ours:
one image goes through `images_edit`, two images go through `compose`, and the
3:4 default lived on `compose` alone. The route chose the aspect ratio; the
prompt never had anything to do with it. Every run with a template got 3:4,
got padded by 24.6% of its area, and then depended on a flaky outpaint call to
hide it. Every run without a template went vertical from the start.

Six styliser returns, six unrelated prompts, one ratio: 896x1200 = 0.7467.
That is what rules out the prompt as a cause, and the owner's observation is
what rules in the route.
