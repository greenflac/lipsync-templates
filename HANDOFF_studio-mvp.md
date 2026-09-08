# HANDOFF — branch studio/mvp

Append-only. Each agent appends its own section and edits nobody else's.

## Agent: knowledge / RAG (studio/knowledge.py) — 2026-08-25

Owned and written here: `studio/knowledge.py`, `studio/tests/test_knowledge.py`,
`studio/knowledge/core_rules.md`, `studio/knowledge/eval_set.jsonl`.
Nothing else was touched. No git command beyond reads was run.

### What exists now

- `build_index(...) -> KnowledgeIndex` over one sqlite file with FTS5.
  822 entries: core 12, ours 288, reference_card 522, gallery 0.
- `retrieve(spec_or_text, *, k=5, index=None) -> dict` — three outcomes, core
  rules in their own field, at most 2 examples per provenance, near-duplicate
  suppression inside the answer.
- `evaluate(index, eval_set, *, k=5) -> dict` — recall@k, precision@k, three
  outcomes, and two mandatory controls (an absent topic that must come back
  empty, a verbatim phrase that must come back with full recall). Either
  control failing makes the run FAIL regardless of the averages.
- Gold set: 40 records in `studio/knowledge/eval_set.jsonl`.

### Numbers (MEASURED 2026-08-25, k=5, 40 gold records, 822 entries)

| fusion | recall@5 | precision@5 | outcome |
|---|---|---|---|
| bm25 + phrase + structural + dense | 0.9737 | 0.7237 | pass |
| bm25 + phrase + structural (no weights) | 0.8947 | 0.6711 | pass |
| bm25 only (mutation) | 0.8289 | 0.7039 | fail |

Dense channel: `sentence-transformers` installed and
`sentence-transformers/all-MiniLM-L6-v2` (apache-2.0, license read from the HF
API) downloads and runs on this machine. It is OFF by default: tests must not
reach the network. Turn it on with `dense=True` or `STUDIO_KNOWLEDGE_DENSE=1`.

### Measured negative result

The structural channel buys 0 recall on this gold set and costs 0.079
precision. It is kept because it is the only channel that can rank a query
carrying no corpus vocabulary — but that case does not occur in the gold set,
so the justification is unproven rather than proven.

### Open items for whoever comes next

- `studio/knowledge/gallery_prompts.jsonl` did not exist at build time. The
  loader is written and the index builds without it; drop the file in and
  rebuild, then re-run `evaluate` before trusting any before/after comparison.
- DEBT(2026-08-25): the default persisted index lands at
  `studio/knowledge/index.sqlite3` and `.gitignore` does not cover `*.sqlite3`.
  Whoever owns `.gitignore` should add it; this agent does not.
- `studio/knowledge.py` (module) and `studio/knowledge/` (data dir) share a
  name deliberately. A regression test asserts the module still wins the
  import; do not add `studio/knowledge/__init__.py`.

### Late addition, same session

`knowledge/PROVENANCE.md` and `knowledge/NOTICE_replacement.md` appeared from
the harvester agent mid-session. `load_gallery_prompts` was aligned to the row
format documented there: the row's own `provenance` value is carried through
(`third_party_gallery`, weight 0.6, its own quota bucket) and its `rights`
marker travels into the `source` field of every retrieved example. Three tests
cover it. The file `gallery_prompts.jsonl` itself still did not exist at the
close of this session.

## Agent: hiring artifact review — 2026-09-08

Ничего в коде не трогал. Только чтение и эта секция.

### Зачем смотрел

Владелец ведёт активный поиск работы. Требование «RAG: чанкинг, ретрив,
реранкинг, эмбеддинги, векторные БД» встретилось **в семи вакансиях подряд**
(Effective, Ubego, Farsight, Rambler, iTransition, Сбер, 1С/CDEK) — где
требованием, где плюсом. В откликах до сегодняшнего дня стояло «RAG в проде
не строил». **Это неверно**: `studio/knowledge.py` закрывает пункт целиком,
причём сильнее, чем у большинства кандидатов.

### Что здесь есть, в терминах найма

Не «пайплайн по туториалу», а измеренный поиск:

- гибридное слияние каналов (bm25 + phrase + structural + dense), и **вклад
  каждого канала измерен по отдельности** — recall@5 0.9737 против 0.8947 без
  весов и 0.8289 на одном bm25;
- золотой набор 40 записей, лежит файлом в репозитории;
- **два обязательных контроля**: отсутствующая тема обязана вернуть пусто,
  дословная фраза — полный recall; провал любого делает прогон FAIL независимо
  от средних. Это ровно то, чего почти никто не делает;
- мутация как проверка: bm25-only помечен `fail` — канал сторожат, а не
  декларируют;
- **записанный отрицательный результат с числом**: structural даёт 0 recall
  и стоит 0.079 precision, оставлен по названной причине, и причина честно
  помечена как недоказанная;
- лицензия dense-модели прочитана до встраивания (apache-2.0, из HF API);
- тесты не ходят в сеть — dense выключен по умолчанию.

Это и есть аргумент на собеседовании: пайплайн строят все, эвалы с
негативными контролями — единицы.

### Что мешает использовать это как артефакт

1. **Репозиторий приватный, ветка не влита.** Показать нечем: ссылку в отклик
   не поставить. Это главное, остальное косметика.
2. **README про knowledge молчит** (одно упоминание на весь файл). Для найма
   первым экраном должна идти таблица чисел, а не архитектура.
3. **Провенанс заголовочного числа.** 0.9737 получен с включённым dense, а
   dense выключен по умолчанию. При публикации это надо назвать явно, иначе
   первый же внимательный читатель поймает на несоответствии — а вся ценность
   артефакта именно в честности замеров.

### Открытые пункты предыдущей секции — статус на сегодня

- `studio/knowledge/gallery_prompts.jsonl` — **по-прежнему отсутствует**.
  Любое сравнение «до/после» без него недействительно.
- DEBT(2026-08-25) по `.gitignore` — **закрыт**: `*.sqlite3` покрыт (строка 7).
- Коллизия имён `knowledge.py` / `knowledge/` — оставлена как есть,
  регрессионный тест на месте. Не трогать.

### Рекомендация

Отдельный публичный репозиторий под knowledge-слой не нужен и вреден:
он потеряет контекст, ради которого корпус собран. Достаточно вынести
результаты в README и сделать ветку показываемой. Решение за владельцем —
здесь только фиксация того, что артефакт готов на 90% и не используется.
