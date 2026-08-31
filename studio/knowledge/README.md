# Where the knowledge corpora go

## Куда класть числа, а не корпуса

| Что | Файл |
|---|---|
| числа про НАС: приборы, корпус, конвейер | `measured.jsonl` |
| что известно про ЧУЖИЕ модели, с тиром и ссылкой | `model_facts.jsonl` |
| заявки на платный замер | `measurements.jsonl` — имя похоже, смысл другой |
| откуда взят каждый корпус и на каком основании | `PROVENANCE.md` |

`measured.jsonl` появился 2026-08-31, когда хэндоф ветки дорос до 2330 строк и
~39 000 токенов: каждая сессия читала их целиком ради трёх чисел, платя
контекстом и дрейфом. Правило «факты не в хэндоф» было и раньше — словами, и не
соблюдалось. Теперь потолок на хэндоф стоит в гейте (`scripts/check_measured.py`).

```bash
python scripts/check_measured.py --find civitai   # три записи вместо 39k токенов
python scripts/check_measured.py --check          # схема + потолок
```

Отрицательный результат здесь полноправен: `outcome` из трёх значений, и
`не годно` с числом и условиями — это измеренная граница, а не пустая строка.


`studio/knowledge.py` builds its index from four sources. Two of them ship in
this directory; two are data you supply.

| source | where | in git? |
|---|---|---|
| core rules | `core_rules.md` | yes |
| gold set | `eval_set.jsonl` | yes |
| our own prompts | `our_prompts/*.json` | no — your data |
| reference style cards | `reference_cards/*.json` | no — your data |
| harvested gallery prompts | `gallery_prompts.jsonl` | no — your data |

## Dropping an archive in

```bash
mkdir -p studio/knowledge/our_prompts studio/knowledge/reference_cards
unzip your-archive.zip -d studio/knowledge/our_prompts/
python -c "from studio.knowledge import build_index; print(build_index().build_report['note'])"
```

Each file in `our_prompts/` is one JSON object with a `prompt` string. Each
file in `reference_cards/` is one JSON object with a `card` key.

If the data lives outside the repository, name it instead of moving it:

```bash
export STUDIO_KNOWLEDGE_OUR_PROMPTS=/path/to/gen
export STUDIO_KNOWLEDGE_REFERENCE_CARDS=/path/to/references
```

The resolver takes the environment variable first, then the in-repo directory,
then — last — the original absolute path this module used to hardcode.

## How to tell it worked

```python
from studio.knowledge import build_index
index = build_index()
index.build_report["outcome"], index.counts()
```

**`could not measure` with `0 examples` in the note means the corpora are not
where the code is looking.** It is not a passing build. That verdict exists
because for one session the index came up with 12 core rules and no examples
on every machine but one, reported `pass`, and answered "could not measure" to
every query — while the recall figures in `HANDOFF_studio-mvp.md` were quoted
as if anybody could reproduce them.

A different prompt corpus — the `prompt / result / model / tags / rating`
format from the product brief — is read by `studio/selfrag/corpus.py` from
`corpus/prompts.jsonl` instead. See `docs/SELFRAG.md`.
