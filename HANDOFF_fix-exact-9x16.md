# HANDOFF fix/exact-9x16 — one frame for the whole pipeline

## 2026-08-26 — unification onto `fork_plan.FRAME` (not committed, working tree only)

Owner's decision: one frame by resolution. Gate `lipsync/tests/test_one_frame.py`
was written by someone else and was NOT edited.

- `fork_plan.FRAME = (720, 1280)` — MEASURED (six shipped clips: Kling returned
  this size, all six final videos carry it). Single declaration.
- `fork_plan.EXTEND_SIZE = FRAME` (was literal 1152x2048).
- `pollinations.PLAN_SIZE = fork_plan.FRAME` (was literal 1152x2048).
- `fork_e2e.STYLED_SIZE = fork_plan.FRAME` (was literal 720x1280).
- Layering: the gateway now imports the domain module. Deliberate — the gate
  requires `fork_plan.FRAME` to be the source, no import cycle exists
  (`fork_plan` reaches `pollinations` only from inside a function), and a
  neutral leaf module would move the declaration out of the modules the gate's
  ast check watches.

Runs: gate 7 tests OK; full suite `Ran 896 tests ... OK (skipped=12)`.

Mutations run with `python3 -B` on wiped `__pycache__`, each substitution
asserted present in the file before the run:

| mutation | gate result |
|---|---|
| `FRAME = (720, 1296)` (on grid, not 9:16) | 3 failures incl. `test_it_is_exactly_nine_by_sixteen` |
| `FRAME = (1080, 1920)` (9:16, off grid) | 2 failures incl. `test_both_sides_sit_on_the_grid_the_model_snaps_to` |
| `STYLED_SIZE = (1152, 2048)` literal | `test_no_module_repeats_a_frame_as_a_literal_pair`, `test_every_name_for_a_frame_is_the_same_frame` |
| `STYLED_SIZE = (720, 1280)` literal (same value) | `..._literal_pair`, `test_moving_the_frame_moves_every_user_of_it` |
| `PLAN_SIZE = (720, 1280)` literal (same value) | `..._literal_pair`, `test_moving_the_frame_moves_every_user_of_it` |

Open, for whoever owns `docs/`: `docs/MANUAL_ru.md` still describes
`STYLED_SIZE` as ВЫБРАНО and does not know about `FRAME`, `EXTEND_SIZE` or
`PLAN_SIZE` being derived. Not edited here (another writer's file).

## 2026-08-27 — dead weight in `identity_arcface` / `fork_e2e` (working tree only, NOT committed)

Gate `lipsync/tests/test_no_dead_weight.py` was written by someone else and was
NOT edited. Only my files were touched: `lipsync/identity_arcface.py`,
`lipsync/fork_e2e.py`, plus the new `lipsync/tests/test_identity_arcface.py`.

Removed (each had exactly one occurrence in the package — its own definition):

- `identity_arcface.START_MIN_FACE_PX = 70`. Both entry points judge by
  `MIN_FACE_PX = 100`, which has a measurement behind it (README: faces 34–56 px
  drifted, 85–139 px held). 70 had none, and no caller.
- `identity_arcface.arcface_drift` (96 lines) — a second implementation of
  `fork_identity.distances`, zero callers. `_quantile` stays: `fork_identity`
  calls it.
- `identity_arcface.face_embedding`, `identity_arcface.face_attributes` — zero
  callers; `face_detail` (the one both wrapped) keeps its two real callers in
  `fork_identity` and `fork_intake`.
- `fork_e2e.KLING_PRO_PRICE_USD` — byte-identical duplicate of
  `KLING_PRO_PRICE_3S_USD = 2.6880`, which is the one line 212 reads.

Added `lipsync/tests/test_identity_arcface.py`, 12 tests, so the
`cosine_distance` docstring's "unit-tested" is true: 0 for identical, 1 for
orthogonal, 2 for opposite, 0.2929 at 45 deg, 0.5 at 60 deg, scale invariance,
zero vector -> 1.0 (not 0.0), 4-decimal rounding, and a negative control that
three different pairs give three different numbers. Every expectation is a
literal; nothing is imported from the module under test except the function.

Mutations, `python3 -B` on wiped `__pycache__`, each substitution grepped in the
file before the run:

| mutation | result |
|---|---|
| `START_MIN_FACE_PX = 70` back | `test_the_names_the_course_found_dead_are_gone_or_wired` |
| `face_embedding` back | same test |
| `KLING_PRO_PRICE_USD` back | same test |
| new test file removed | `test_nothing_claims_to_be_unit_tested_without_a_test_file` |
| `cosine_distance`: zero vector returns 0.0 | 2 failures in `TheUnmeasurableInputSaysUnrelated` |
| `cosine_distance`: round to 2 places | 2 failures incl. `test_a_known_angle_...` |
| `cosine_distance`: drop the `/(na*nb)` normalisation | 7 failures |
| `cosine_distance`: return `sim` instead of `1 - sim` | 8 failures |
| `cosine_distance`: drop the `max(0.0, ...)` clamp | 1 failure, and ONLY after the test was made sharper — see below |

Negative result worth keeping: the clamp `max(0.0, 1.0 - sim)` is invisible at
the function's own resolution. float64 puts the self-similarity of a vector at
most 2.2e-16 above 1, so unclamped the result is -0.0, and
`assertEqual(-0.0, 0.0)` passes. The first version of the clamp test was green
on the mutant. The guard now reads the sign with `math.copysign` on the one
input where it is observable (`[0.1, 0.1, 0.3]`).

Runs: gate 6 tests, 4 pass, 2 fail (both outside my files, see below); full
suite from the repo root `Ran 914 tests ... FAILED (failures=2, skipped=12)` —
896 before, +12 new, +6 gate; no pre-existing test broke.

Open, NOT mine to fix:

- `test_no_new_module_level_constant_is_declared_and_unused` still lists 13
  constants. 8 are in other writers' modules (`fork_plan`, `fork_identity`,
  `fork_style_prompt`, `motion`, `framemath`, `pose`, `fork_batch`). 5 are in
  `fork_e2e` (`KLING_PRICE_3S_USD`, `STYLE_HIT_REFERENCE`, `STYLE_HIT_REJECTED`,
  `STYLE_FLOOR_REFERENCE`, `STYLE_TEXT_ROUTE_REFERENCE`) and are NOT dead in the
  sense the gate's own docstring describes: each is read by
  `lipsync/tests/test_fork_e2e.py`, which the gate's counter excludes by design.
  Deleting them would delete measured evidence and gut four live tests, so they
  were left alone and reported instead.
- `test_every_documented_command_collects_the_whole_suite`: README lines 114 and
  247 still say `discover -s lipsync/tests`. README belongs to another writer.
- `docs/MANUAL_ru.md` lines 552 and 566 still document `START_MIN_FACE_PX` and
  `KLING_PRO_PRICE_USD`, which no longer exist. For whoever owns `docs/`.

---

## Четыре мёртвые константы: `motion`, `framemath`, `fork_batch` (писатель 2)

Файлы: `lipsync/motion.py`, `lipsync/framemath.py`, `lipsync/fork_batch.py`,
`lipsync/tests/test_fork_batch.py`. Гейт `test_no_dead_weight.py` не правился.

Исходное падение воспроизведено до починки:
`Lists differ: ['motion.py:287 PHYSICAL_MOTION', 'motion.py:294 LOOP_MOTION',
'framemath.py:5 SIDE_MULTIPLE', 'fork_batch.py:15 OWNER_MATRIX'] != []`.

| константа | решение | основание |
|---|---|---|
| `PHYSICAL_MOTION` | удалена | остаток текстового text-to-video маршрута |
| `LOOP_MOTION` | удалена | тот же маршрут |
| `SIDE_MULTIPLE` | удалена | наследие ComfyUI/WanAnimate, продукт сторону не проверяет |
| `OWNER_MATRIX` | ПОДКЛЮЧЕНА + возвращён комментарий о происхождении | называла решение владельца, лежавшее в тестах голыми литералами |

Ресёрч-репозиторий `/home/user/ball-reel` (пакет `ball_reel`):

- `ball_reel/motion.py:315,325` — обе строки промта живы, их читает
  `ball_reel/produce.py:48,208,210`, собирая `base_motion`. В продукте
  `produce.py` нет, `pollinations.video_loop` не вызывается ниоткуда, движение
  задаёт драйвинг-видео через Kling, а не слова. Потребителя нет и быть не может
  — удалено, а не подключено.
- `ball_reel/fork_comfy.py:252` и `fork_channels.py:285` — `SIDE_MULTIPLE`
  живая: ею проверяют кратность ширины/высоты 16 (источник —
  `workflows/upstream/WanAnimateToVideo.doc.md`, строки 18–20). В продукте
  функции проверки стороны не переехали: голого «16» с этим смыслом в
  продакшене `lipsync/` нет (грепом по значению), есть только литералы в
  ожиданиях чужих тестов (`test_fork_plan.py:312`, `test_fork_e2e.py:989`) —
  там литерал и правилен по Т2. `docs/MANUAL_ru.md:838` сам называет её
  наследием параллельного опенсорсного пайплайна.
- `ball_reel/fork_batch.py:85` — `OWNER_MATRIX` мертва и там, но с комментарием
  о происхождении: «ВЫБРАНО ВЛАДЕЛЬЦЕМ: затронуть 5 драйвингов, 5 стилей,
  2 личности… происхождение чисел 50 ячеек и $10.50». В продукте эти 5/5/2
  лежали голыми литералами в `test_fork_batch.py:29-31`, а тесты рядом уже
  назывались `test_full_on_the_owner_matrix_is_fifty_cells`. Подключено:
  фикстуры строит `_owner_axes()` из `B.OWNER_MATRIX`; ожидаемые числа (50, 5,
  `[5, 5, 2]`) остались литералами (Т2).

Мутации — в чистой копии `scratchpad/mut` (архив HEAD + мои и соседские рабочие
файлы), `python3 -B`, `__pycache__` снесён, подмена подтверждена грепом файла:

| мутация | грep-подтверждение | покраснело |
|---|---|---|
| вернуть `PHYSICAL_MOTION` в `motion.py` | `motion.py:288:PHYSICAL_MOTION = (` | `test_no_new_module_level_constant_is_declared_and_unused` |
| вернуть `SIDE_MULTIPLE = 16` в `framemath.py` | `framemath.py:5:SIDE_MULTIPLE = 16` | тот же тест |
| `OWNER_MATRIX = (4, 5, 2)` (слабее) | `fork_batch.py:19:OWNER_MATRIX = (4, 5, 2)` | 6 тестов, в т.ч. `test_the_axes_come_out_at_the_sizes_the_owner_ordered`, `test_full_on_the_owner_matrix_is_fifty_cells` |
| `OWNER_MATRIX = (5, 5, 3)` (строже) | `fork_batch.py:19:OWNER_MATRIX = (5, 5, 3)` | 5 тестов, те же ключевые |

Прогоны (снимались, когда соседи могли писать в дерево):

- гейт целиком, внешний: `Ran 7 tests in 25.154s / OK` — включая
  `test_every_documented_command_collects_the_whole_suite`, который у прошлого
  писателя падал: README к этому моменту починен его владельцем.
- полный набор из корня: `Ran 917 tests in 10.607s / OK (skipped=14)`
  (было 915 с одним падением; +2 моих теста, падение снято).

Для владельца `docs/` (чужие файлы, не правил):

- `docs/MANUAL_ru.md:643` — строка таблицы про `SIDE_MULTIPLE` (константы больше нет).
- `docs/MANUAL_ru.md:838` — там же `SIDE_MULTIPLE` в списке наследия.
- `docs/MANUAL_ru.md:745` — `OWNER_MATRIX`: строка остаётся верной, константа жива.
- `PHYSICAL_MOTION`/`LOOP_MOTION` в продуктовых `docs/` и `README.md` не упоминаются
  (упоминание есть только в ресёрч-репозитории: `docs/internal/REFERENCE.md:57`).

## Writer: fork_identity / fork_looper / fork_intake / fork_style_prompt / fork_aesthetic (2026-08-27)

Deleted (previous stack, no product counterpart):
- `fork_identity.lora_regression` (31L) — LoRA per template; this product has none.
- `fork_identity.before_after_restore` (64L) — a "before/after the face restore"
  pair; `grep -rni "restor|upscale|enhance"` over the sources finds no restore
  stage at all, `fork_finish` is crop plus audio.
- `fork_intake.window_argv` (21L) + `WINDOW_FPS_PROVEN` — the `select`/`setpts`
  cut the old backend needed (its test said "without setpts Wan answered 422").
  The live cut is `fork_e2e.cut_argv`, `-ss` plus `-frames:v`, a different
  decision, not a duplicate.
- `fork_looper.select` (17L) — the same overlap suppression `pick_finalists`
  implements again; its three tests now run against `pick_finalists`, which had
  none. It was invisible to the shape gate: `\bselect\b` matched the ffmpeg
  filter string inside `window_argv`.
- `fork_looper.admissible_lengths` (8L) — a test enumerator; moved into
  `test_fork_looper.py`, the decision `length_is_admissible` stays in the module.
- `fork_style_prompt.report_text` (8L) — a renderer for a module with no CLI.

Declared INSTRUMENTS (data, with the reason in a comment above the tuple):
- `fork_identity`: `restore_negative_control`, `acceptance_report`.
- `fork_aesthetic`: `leak_verdict`.

Renamed: `framemath as fork_comfy` -> `framemath` in the looper tests; the
`fork_props` note in `fork_looper` and its test now say there is no protagonist
markup in this product rather than naming a module that does not exist.

Fixed: `driving_intake` docstring said "five axes, four hard and one soft"; the
code runs six and two. Pinned by `test_the_intake_reports_six_axes_of_which_two_are_soft`.

Mutations (python3 -B, __pycache__ removed, substitution grepped in the file):
OVERLAP_MAX 0.5->0.95 red / ->0.2 red; TOP_LOOPS 5->4 red / ->6 red;
LOOP_MIN_FRAMES 41->37 red / ->45 red; RESTORE_PULL_MAX 0.05->0.5 red / ->0.005 red.
Negative controls: breaking the overlap sieve in `pick_finalists` reddens 2 of the
moved tests; `soft=("orphan_wrists",)` reddens 3 intake tests.
OVERLAP_MAX 0.5->0.9 did NOT redden — the fixture overlaps by 41/45=0.911, so the
bar is only clamped from below by that pair; the new parameter test clamps both.

---

## Атавизмы прежнего стека в `motion` / `pose` / `framemath` (писатель 3)

Файлы: `lipsync/motion.py`, `lipsync/pose.py`, `lipsync/framemath.py`,
`lipsync/tests/test_pose.py`. Гейты `test_product_shape.py` и
`test_no_dead_weight.py` НЕ правились. Не коммичено, только рабочее дерево.

Исходное падение воспроизведено до починки (И2): в списке гейта
`test_no_public_function_is_both_uncalled_and_undeclared` было 35 сирот, из них
10 моих — `motion.py` (`loop_seam` 35L, `motion_quality` 46L,
`best_loop_window_pose` 62L, `best_loop_window` 41L, `trim_to_loop` 26L),
`framemath.py` (`window_plan` 27L), `pose.py` (`world_proportions` 38L,
`pose_distance` 4L, `pose_drift` 67L, `limb_consistency` 52L).

| имя | решение | основание |
|---|---|---|
| `loop_seam` | удалено | `fork_looper` меряет стык сам, тремя осями |
| `motion_quality` | удалено | то же знание, что `fork_looper.cuts` |
| `best_loop_window` | удалено | выбор окна делает `fork_looper` |
| `best_loop_window_pose` | удалено | то же |
| `best_loop_cut` + `trim_to_loop` | удалено | подрезка mp4 после локального сэмплинга |
| `_steps`, `SEAMLESS_MAX`, `STILL_MIN` | удалено | остались без читателя |
| `window_plan` + `WRAP_WINDOW = 77` | удалено | `frame_window_size` ноды WanAnimateToVideo |
| `world_proportions` + `world_landmarks` | удалено | маршрут «нужна ли LoRA» |
| `pose_drift`, `limb_consistency`, `LIMBS` | удалено | судили клип ПОСЛЕ локального сэмплинга |
| `SAME_POSE_MAX`, `POSE_WANDER_MAX`, `WORST_JOINT_MAX`, `LIMB_WOBBLE_MAX` | удалено | пороги удалённых мер; их «замер» — про veo/wan/happyhorse |
| `pose_distance` | удалено | 4 строки поверх `pose_delta` (Е1) |
| `pose_delta` | **ПРИБОР** (`pose.INSTRUMENTS`) | эталон для `fork_looper.pose_gap` |
| `JUMP_MAX`, `_gray` | оставлены + возвращён комментарий о происхождении | их читает `fork_looper` |

`pose.py:203` (текст отказа про ControlNet и manifest.json) переписан на
причину, которая в этом продукте существует.

Ресёрч (`/home/user/ball-reel`): `produce.py:48-50` и `run_local.py:909-921,
1236-1256, 1666` — единственные потребители мер движения и позы; ни одного из
этих модулей в продукте нет. `fork_comfy.py:1440` — происхождение
`WRAP_WINDOW`: «ИЗМЕРЕНО в боевом воркфлоу владельца (узел 62,
`frame_window_size`)». `fork_build_route.py:185` — единственный потребитель
`world_proportions`. `fork_looper.py:884-897` — обоснование прибора: «Своя
реализация нужна ровно потому, что `pose_delta` принимает СЫРЫЕ точки и
приводит их заново на каждый вызов… Второе такое число рядом было бы копией
знания, которую нечем нарушить (Е1)». Комментарий возвращён в `pose.py`
по-английски.

Тесты: `test_pose.py` переписан. Удалены три класса, сторожившие удалённое
(`LimbConsistencyDetectsRubberBodies` 3, `BuildIsMeasuredIn3DNotProjection` 5,
`PoseDriftAggregatesLikeTheIdentityCheck` 5 — 13 тестов). Класс про
`pose_distance` (7 тестов) переписан на `pose_delta` с литералами вместо
констант модуля (Т2). Итого 13 тестов вместо 20.

Мутации — чистая копия `scratchpad/w4/run` (архив HEAD + мои файлы), `python3
-B`, `__pycache__` снесён, подмена подтверждена грепом файла перед прогоном:

| мутация | грep | покраснело |
|---|---|---|
| вернуть `window_plan` + `WRAP_WINDOW` | `framemath.py:59` | сироты: `framemath.py:59 window_plan` |
| вернуть `WRAP_WINDOW` одну | `framemath.py:10` | мёртвые константы: `WRAP_WINDOW` |
| вернуть `loop_seam` | `motion.py:42` | сироты: `motion.py:42 loop_seam` |
| вернуть `pose_drift` | `pose.py:159` | сироты + `test_the_measures_of_the_local_sampling_era_are_gone` |
| снять `INSTRUMENTS` + комментарий + самоупоминание в тексте ошибки | `pose.py:26` | сироты: `pose.py:117 pose_delta` |
| то же, но `INSTRUMENTS` оставлен (контроль) | `pose.py:26` | ничего — объявление и есть то, что держит |
| `INSTRUMENTS = ("pose_drift",)` | `pose.py:37` | `test_an_instrument_declaration_names_something_real` |
| вернуть исходный текст отказа дословно | `pose.py:139` | гейт: `pose.py:137 ControlNet` + мой `..._names_a_cause_that_exists...` |
| `JUMP_MAX 4.0 → 3.0` / `→ 22.0` | `motion.py:28` | 3 / 4 теста соседей, обе стороны |
| `MIN_VISIBILITY 0.5 → 0.05` / `→ 0.95` | `pose.py:24` | 6 / 6 тестов, обе стороны |
| `LENGTH_STEP 4 → 3` / `→ 5` | `framemath.py:5` | 26 / 22 теста |
| `SECONDS_MAX 10.0 → 9.0` / `→ 11.0` | `framemath.py:11` | 1 / 3 |
| `SECONDS_MIN 5.0 → 4.0` / `→ 6.0` | `framemath.py:10` | 2 / 4 |
| `WRAP_FPS 30 → 24` / `→ 60` | `framemath.py:8` | 3 / 3 |
| убрать деление на торс в `_normalise` | `pose.py:125` | 3 моих + 4 соседских |
| убрать центрирование по бёдрам | `pose.py:125` | 2 моих |
| `worst` считает среднее, а не максимум | `pose.py:150` | 2 моих |
| округление до 2 знаков вместо 4 | `pose.py:149` | 2 моих + `test_pose_gap_is_the_same_number_as_pose_delta` |
| `coverage` всегда 1.0 | `pose.py:154` | `..._skipped_and_counted_not_scored` |
| отсутствующая поза возвращает None вместо исключения | `pose.py:133` | 2 моих |
| `mean` всегда 0.0 | `pose.py:149` | 3 моих, в т.ч. негативный контроль про три разных числа |

Прогоны (соседи в этот момент писали — в дереве были правки в `cure`, `device`,
`fork_aesthetic`, `fork_identity`, `fork_intake`, `fork_looper`,
`fork_style_prompt`, `pollinations`, `pyproject.toml`; поэтому все замеры на
изолированных копиях `git archive HEAD` + только мои файлы):

- гейты: `Ran 14 tests`, 4 падения — все ВНЕ моих файлов (см. ниже).
- полный набор: `Ran 918 tests in 42.872s / FAILED (failures=3, skipped=14)`,
  те же три, ни одного моего. Из моих файлов гейт не называет теперь ничего.

Убрано: 662 строки, добавлено 138, чистое −524.

### Гейт прав, но у него есть щель — для владельца гейта, не правил

`test_product_shape._callers_in_production` считает вхождения регуляркой по
тексту модуля и вычитает РОВНО ОДНО «на своё определение». Любое второе
самоупоминание внутри функции — префикс в тексте ошибки, рекурсивный вызов,
имя в докстринге — читается как внешний вызов. Показано мутацией: без
`INSTRUMENTS`, но с `f"pose_delta: no body found…"` в собственном тексте
отказа, `pose_delta` сиротой НЕ считается. Объявление прибора я всё равно
поставил: оно и есть настоящее основание, а щель однажды закроют.

### Чужое, не правил

- `snap_frames`/`frames_for_seconds` и `LENGTH_STEP=4`/`LENGTH_BASE=1` — правило
  4n+1 — это упаковка латентов прежнего сэмплера. В продукте их читает только
  `fork_looper` (`admissible_lengths`, сама сирота в списке гейта, и одна строка
  отчёта). Если у Kling такого ограничения нет, `framemath` теряет половину
  содержимого. Решение за владельцем `fork_looper`.
- Имена `WRAP_FPS`/«wrapper» в `framemath` — словарь прежней обёртки, но имя
  читают `fork_looper` и `fork_video`; переименование пересекает чужие файлы.
- `pose_delta`: ветка `if len(shared) < 4: return None` недостижима —
  `_normalise` не возвращает позу без обоих бёдер и обоих плеч, значит общих
  суставов заведомо ≥ 4. Наблюдаемо сломать её нельзя, поэтому не трогал (И2).
- Незадекларированные импорты (`motion.py` PIL, `pose.py` mediapipe/PIL) —
  часть общего падения `test_no_import_is_undeclared` на 33 импорта в 10
  модулях; лечится в `pyproject.toml`/`requirements-dev.txt`, которые сейчас
  правит сосед.
- Оставшиеся падения гейта: 25 сирот в чужих модулях, 33 незадекларированных
  импорта, `fork_looper.py:1288 fork_props` и шесть вхождений в
  `test_fork_looper.py`.

### DEBT

- `# DEBT(2026-08-27)`: общий каталог `scratchpad` — я записал в него
  `mutate.sh`, `mine.py` и `mut3/`, не проверив, что это чужие рабочие имена.
  Дальше работал в `scratchpad/w4/`. Если у соседа были файлы с этими именами,
  они потеряны.

---

## Гейтвей, устройство, лечилка и зависимости (писатель 3)

Мои файлы: `lipsync/pollinations.py`, `lipsync/device.py`, `lipsync/cure.py`,
их тесты, `pyproject.toml`, `requirements-dev.txt`. Гейты
`test_product_shape.py` и `test_no_dead_weight.py` не правились. Чужие модули
не трогались.

Отказ воспроизведён до починки, `python3 -B` на чистой копии `git archive HEAD`
плюс новый гейт:
`35 public functions with no caller and no INSTRUMENTS declaration`,
`undeclared third-party imports: [... 'pollinations.py:54 requests' ... 'device.py:32 torch' ...]`.

### Решение по каждой мёртвой функции

| имя | решение | основание (ресёрч-репозиторий `/home/user/ball-reel`) |
|---|---|---|
| `pollinations.video` | удалена | звали `chain.py`, `produce.py`, `doctor.py` — ни одного нет в продукте; видео делает Kling через fal.ai |
| `pollinations.video_loop` | удалена | тот же маршрут |
| `pollinations.LAST_VIDEO_USAGE`, `_usage_of` | удалены | счётчики видеосекунд того же маршрута |
| `pollinations.extract_frames` | удалена | звали `produce.py`, `run_local.py`; кадры режет `fork_video` через ffmpeg |
| `pollinations.FRAME_PATTERN`, `frame_names_sort_correctly` | удалены | см. отдельный разбор ниже |
| `pollinations.chat`, `judge_frame`, `opinion_of`, `JUDGE_SYSTEM`, `_parse_json` | удалены | мертвы и в ресёрче тоже: грепом ноль вызовов в обоих деревьях; эстетический вердикт даёт внешний `creative_eval` |
| `pollinations.tts` | удалена | звал только `doctor.py`; в продукте звук приходит с драйвинг-видео |
| `pollinations.image` | ОСТАВЛЕНА, объявлена прибором | не имеет вызова на платном пути, но два гейта (`test_route_defaults`, `test_fork_e2e`) сравнивают дефолтный размер ТРЁХ маршрутов между собой. Именно это сравнение поймало 3:4 на `compose`. Удалить — оставить сравнению две пробы вместо трёх |
| `device.describe`, `torch_state`, `torch_build_cuda`, `dtype_for`, `onnx_providers`, `smi_probe`, `smi_run`, `smi_cards`, `smi_cuda`, `driver_covers`, `version_pair`, `empty_cache` | удалены целиком | вся ветка обслуживала `preflight_gpu.py` (GPU-доктор), `gpu_keyframes.py`, `dwpose.py`, `run_local.py`, `train.py`. Ни одного из этих модулей в продукте нет |
| `cure.py_snippet`, `cure.PY` | удалены | строили однострочники для `preflight_gpu.py` |
| `cure.set_env` | ПОДКЛЮЧЕНА | называла решение, лежавшее ненаписанным: `pollinations._key()` сообщал «ключа нет», но не как его поставить |

Прибором ветку диагностики НЕ объявлял. Прибор доказывает, что другой прибор
умеет сказать «нет»; строка отчёта про модель карты не доказывает ничего ни об
одном измерении этого продукта. Это было бы «жалко удалять».

### Отдельно: `detect()` спрашивал не тот рантайм

Не атавизм, а живой дефект, найденный при разборе необъявленного `import torch`.
ArcFace крутится на onnxruntime, а `detect()` спрашивал torch. Torch в продукте
не объявлен и не ставится (`pip install .` его не тянет), поэтому `ImportError`
ловился и возвращался `"cpu"` — на ЛЮБОЙ машине, включая ту, где onnxruntime
рапортует `CUDAExecutionProvider`. Вердикт описывал отсутствующий пакет, а не
железо. Теперь спрашивается onnxruntime — тот, кто реально исполняет модель.
Сигнатура и область значений сохранены, `identity_arcface.py:27` не трогался.
Побочно: единственный `import torch` в пакете исчез, объявлять его не пришлось.

Наблюдаемо: с подставленным onnxruntime, рапортующим CUDA, старый код отвечал
`cpu`, новый отвечает `cuda` (`test_the_old_oracle_no_longer_decides_the_answer`).
Обратный контроль: torch, который «видит карту», больше не переопределяет
рантайм (`test_a_torch_that_sees_a_card_does_not_override_the_runtime`).
На реальной карте НЕ ПРОВЕРЕНО — здесь ни torch, ни GPU не доступны.

### `FRAME_PATTERN` — противоречие подтверждено, решено удалением

`FRAME_PATTERN = "%04d.png"` держит 9999 имён. Потолок кадров —
`fork_looper.MAX_FRAMES = 36000` (проверено грепом), то есть шаблон был в 3.6
раза уже потолка и переполнялся молча: 10000-й кадр получал имя `10000.png`,
которое сортируется ПОСЛЕ `0999.png`, но ПЕРЕД `1000.png`. Выживший
именователь — `fork_video.NAME_DIGITS = 5` (99999), он потолок покрывает.
Константа была мёртвой, поэтому чинить её незачем — удалена, и одно знание
осталось в одном месте. Тест `test_the_frame_width_that_overflowed_is_not_declared_here`
сторожит и отсутствие константы, и ширину пять у выжившего.

### Тесты на `pollinations`: было 7, стало 58

Сеть закрыта РАННЕРОМ, двумя независимыми замками, у каждого свой негативный
контроль в том же файле:

1. `setUpModule` подменяет `socket.socket.connect` на всё время модуля.
2. `sys.modules["requests"]` подменяется заглушкой через `mock.patch.dict`.

Оба замка проверены на несущесть, а не на слова:

- снять замок 1 → краснеет `test_a_real_socket_cannot_leave_the_machine`;
- снять замок 2 (подменять `requests_unused` вместо `requests`) → 41 тест
  краснеет, и краснеет ИМЕННО замком 1:
  `AssertionError: a test tried to open a socket to (('127.0.0.1', 41501),)`.
  То есть без заглушки код действительно пошёл бы на провод, и баланс
  Pollinations (402) тут ни при чём — до провода не доходит.

Покрыто: сборка URL и экранирование промта (`/`, пробел, кириллица), Bearer,
дефолты и переопределение хостов, схлопывание `//`, параметры каждого живого
маршрута, запись байтов и создание родительских каталогов, отказ по HTTP,
проверка content-type, три исхода у `compose` (картинка / отказ / 200 не с
картинкой) и три исхода у `upload` (url / id / ни то ни другое), плюс сводки
с числами рядом с вердиктом (`checked N, violations M, unmeasurable K`).

Тесты на `cure`: 0 → 21, и ветка Windows исполнена впервые — `WINDOWS`
патчится на объекте модуля, обе половины каждой функции проверены.
Тесты на `device`: 44 → 15, потому что 29 из них измеряли удалённый GPU-доктор.

### Зависимости

`requests` и `fal-client` объявлены как основные (в ресёрче `requests>=2.31`
был объявлен — декларация потерялась при вырезании, а не зависимость).
`insightface`, `onnxruntime`, `mediapipe` разложены по строкам: гейт читает
имена только с начала строки, и в однострочном `identity = [...]` он видел
слово `identity`, а не пакеты. Существование каждого имени доказано командой
(Ц10): `requests` 2.33.1, `fal-client` 1.0.1, `insightface` 1.0.1,
`mediapipe` 1.0.0, `onnxruntime` 1.28.0.

`creative-eval` объявлен отдельным extra `style` и помечен UNVERIFIED:
существование доказано только как импортируемый модуль на машине владельца
(`creative_eval` 0.1.0, `/home/user/greenflac/vertical-creative-eval`),
как имя в индексе — не доказано и в сеть за этим не ходил (Ц3).

### Мутации

Все — на чистой копии, `python3 -B`, `__pycache__` снесён, подмена подтверждена
грепом файла ПОСЛЕ записи (С10). Каждый порог сдвинут в обе стороны (С12).

| мутация | покраснело |
|---|---|
| `compose`: `< 2` → `< 3` (строже) | 14 тестов |
| `compose`: `< 2` → `< 1` (слабее) | `test_one_reference_is_the_wrong_route_and_says_so`, `test_the_wrong_route_costs_nothing` |
| `compose`: снять проверку content-type | 3 теста |
| `compose`: content-type строго `image/png` (строже) | `test_an_image_answer_is_written` |
| `image`: снять `raise_for_status` | `test_a_refusal_is_raised_rather_than_written_to_disk` |
| `quote(prompt, safe="")` → `safe="/"` | `test_a_slash_in_the_prompt_does_not_become_a_path_segment` |
| `_base()`: снять `rstrip("/")` | `test_a_trailing_slash_does_not_become_a_double_slash` |
| `_key()`: убрать команду-лечение | `test_a_missing_key_hands_the_reader_a_command_for_their_shell` |
| `upload`: id вперёд url | `test_a_url_wins_over_an_id` |
| `images_edit`: `WxH` → `W,H` | `test_images_edit_sends_the_plan_frame_as_one_string` |
| `PLAN_SIZE` → литерал `(1080, 1920)` | 6 тестов |
| `CUDA_PROVIDER` → несуществующее имя (строже) | 2 теста |
| `CUDA_PROVIDER` → `CPUExecutionProvider` (слабее) | 2 теста |
| `detect()` назад на torch | 3 теста |
| `INSIGHTFACE_GPU_DEVICES` → `()` | `test_cuda_gets_the_first_gpu` |
| `INSIGHTFACE_GPU_DEVICES` → `("cuda","cpu")` | `test_cpu_gets_minus_one` |
| `DEVICE_ORDER` перевёрнут | `test_the_order_prefers_the_accelerator_and_ends_on_the_fallback` |
| `WINDOWS = os.name == "posix"` | 2 теста |
| `set_env`: `export` и на Windows | 2 теста |
| вернуть `tts` | `test_none_of_them_is_back` + гейт `test_no_public_function_is_both_uncalled_and_undeclared` |
| вернуть `FRAME_PATTERN` | 2 теста |
| вернуть `device.describe` | `test_none_of_them_is_back` |
| вернуть `cure.py_snippet` | `test_the_snippet_builder_is_gone` |
| `INSTRUMENTS = ("image", "no_such_route")` | гейт `test_an_instrument_declaration_names_something_real` |

ОТРИЦАТЕЛЬНЫЙ РЕЗУЛЬТАТ (И6): `INSTRUMENTS = ()` при живом `image` гейт НЕ
ловит. `_callers_in_production` считает `\bimage\b` по всем исходникам и
вычитает одно вхождение (определение), а слово `image` встречается в теле
самого модуля как ключ параметров и файлов. Моё объявление `INSTRUMENTS` —
документация настоящего решения, а не способ пройти гейт: гейт этот случай
сейчас не видит вовсе.

### Прогоны

Снимались на чистой копии `git archive HEAD` + только мои файлы, потому что
соседи писали в дерево во время работы (`fork_identity`, `fork_style_prompt`,
`fork_aesthetic`, `fork_intake`, `fork_looper`, `pose`, `motion`, `framemath`
менялись между 06:54 и 06:58 UTC). Поэтому числа ниже описывают HEAD плюс мои
файлы, а не текущее состояние рабочего дерева (С6).

- До: `Ran 925 tests ... FAILED (failures=3, skipped=14)`
- После: `Ran 968 tests ... FAILED (failures=3, skipped=14)` — те же три
  падения, ни одно не моё, +43 теста (pollinations 7→58, cure 0→21,
  device 44→15).
- `ruff check` и `ruff format --check` по моим шести файлам — чисто.
- `python3 -m mypy lipsync/ --ignore-missing-imports`: мои файлы дают 0 ошибок
  (было 2 в `test_pollinations.py`); оставшиеся 2 — в чужих файлах.
- Продакшен-строк убрано: `device.py` −237/+35, `pollinations.py` −165/+30,
  `cure.py` −12/+27 (докстринги с примерами по К3). Итого −414 удалённых строк
  продакшена при +92 добавленных.

### ГЕЙТ, КОТОРЫЙ Я СЧИТАЮ НЕПРАВЫМ — НЕ ПРАВИЛ, СООБЩАЮ

`test_product_shape.EveryThirdPartyImportIsDeclared.test_no_import_is_undeclared`
после моей работы оставляет 13 нарушений, и ни одно из них нельзя закрыть
честной декларацией:

1. **12 × `PIL`.** `pillow` объявлен в `pyproject.toml` — в том самом файле,
   который читает гейт. Гейт сравнивает КОРЕНЬ ИМПОРТА (`PIL`) с именами
   дистрибутивов, а нормализация `-`→`_` разницу `PIL`/`pillow` не покрывает.
   Правило гейта («каждый сторонний импорт объявлен») выполнено, проверка
   гейта — нет.
2. **1 × `bisect`** (`fork_looper.py:1363`) — модуль стандартной библиотеки,
   отсутствующий в списке `STDLIB_OK`. Доказано командой:
   `python3 -c "import bisect,sys; print('bisect' in sys.stdlib_module_names)"`
   → `True`, файл `/usr/lib/python3.11/bisect.py`. Объявить его зависимостью
   было бы ложной декларацией и ровно тем «несуществующим именем», от которого
   бережёт Ц10.

Пока это не поправлено в гейте, тест не может стать зелёным ни при каких
действиях писателей, а `test_no_dead_weight.test_every_documented_command_collects_the_whole_suite`
краснеет каскадом от него. Предлагаемая правка — владельцу гейта: добавить
`bisect` в `STDLIB_OK` и таблицу «корень импорта → дистрибутив»
(как минимум `PIL: pillow`).

Прочее в гейте, что не моё: 26 публичных функций без вызова в чужих модулях
(`fork_plan`, `fork_identity`, `motion`, `pose`, `fork_video`, `framemath`,
`fork_looper`, `fork_e2e`, `fork_style_prompt`, `fork_intake`, `fork_finish`,
`fork_aesthetic`) — было 35, мои девять закрыты. Дофорковые имена
(`fork_props`, `ControlNet`, `fork_comfy`) — в `fork_looper.py`, `pose.py`,
`test_fork_looper.py`.

Поправка по ходу (П3, прочитал произведённое глазами): комментарий у
`DEVICE_ORDER` описывал перебор, которого в новом `detect()` нет. Константа
теперь не описание, а источник: `detect` возвращает `DEVICE_ORDER[0]` или
`DEVICE_ORDER[-1]`. Мутации после этого: переворот `("cpu", "cuda")` — 6
падений (было 1), `("cuda",)` без запасного варианта — 4 падения.
Финальный прогон после правки: `Ran 968 tests ... FAILED (failures=3, skipped=14)`.

---

## 2026-08-27 — писатель: 12 несвязанных публичных функций (гейт `test_product_shape`)

НЕПРОВЕРЕНО (Ц4), чужие утверждения предыдущих агентов:
- «`bias_from_columns` — прибор с границей собственного шума 1.0024 против порога
  1.05». **Проверено, число неверно**: на `REAL_COLUMNS` (48 колонок) прогон даёт
  `gain = 1.0009`, не 1.0024. Суть (шум сильно ниже порога) подтверждается,
  названное число — нет. Источник числа не найден.
- «`differ` — негативный контроль стилизатора». Подтверждено чтением тестов
  `test_fork_style_prompt.py:29/32/63`: разные карточки → PASS, одинаковые → FAIL,
  нечитаемая → UNMEASURED.

Старт: 946 тестов, 2 падения. Финал: 953 теста, 0 падений.
Второе стартовое падение (`test_no_dead_weight`, «документированная команда вышла
с кодом 1») было следствием первого и ушло вместе с ним.

Решения — 7 удалить, 3 подключить, 2 объявить прибором; плюс 13-е, вскрытое
удалением: `framemath.frames_for_seconds` жила только через удалённую обёртку
`fork_video.plan_for_seconds`. Удалено 116 строк продакшна в 5 файлах.

Подключения (каждое с негативным контролем «сломай ровно названный дефект»):
- `fork_plan.plan_verdict` → `fork_e2e._person_in_plan`. Там лежала ВТОРАЯ
  реализация четырёх полос плана; вернул её мутацией — 2 теста покраснели.
- `fork_plan.composition_card` → `fork_e2e.run` через новый `driving_card`.
  Карточку не производил никто, `main` её не передавал: `framing_clause` и
  `in_card` были мертвы в каждом отгруженном прогоне.
- `fork_e2e.similarity_source` → в отчёт стадии приёмки стиля. `shipped_similarity`
  молча падает на палитру, и число выглядит одинаково (С13).

ВАЖНО для следующего: `_person_in_plan` теперь ветвится на
`card.get("outcome") == PASS`, а НЕ на `card is not None`. `driving_card` отвечает
всегда, и объект карточки — не карточка; ветвление на существовании отбирало у
прогона проверку по полосам (11 тестов краснеют на этой мутации).

Дыра гейта (не правил, гейт чужой): `_referenced_names` считает вызывающим любой
строковый литерал, равный имени. Поэтому переименование `INSTRUMENTS` в
`_INSTRUMENTS_OFF` гейт НЕ ловит — имя внутри кортежа продолжает голосовать за
себя. Ловится только удаление строки целиком.

Остаток (не в моём наряде из 12): `test_fork_video.py:615`
`test_the_output_rate_is_not_copied_from_fork_comfy` — до-форковое имя в названии
теста. Гейт его не видит: перед `fork` стоит `_`, границы слова нет.

## External audit and what it changed (this session, after a41fd91)

An audit run that took no part in the work reported 26 checks, 11 violations,
3 unmeasurable. Five violations are closed here; the rest are listed below as
open, not as done.

Closed:

- `scripts/check` was red on HEAD. The formatter complaint was real but not
  the cause: the documented-command test substituted the interpreter path
  twice into its own output whenever the running interpreter is named
  `python` (`/usr/local/bin//usr/local/bin/python`), so the child exited 127.
  Manual runs use `python3` and stayed green — locally green, CI red, which is
  the split K7 forbids. Anchored substitution; the old form now reddens under
  `python`.
- The same failure reported only `exited 127` and dropped the child's output,
  which is why the cause was not visible at once. The whole text is kept now.
- The pre-fork sweep's negative control held its own copy of the pattern, so
  restoring the defective sweep left both green. The sweep is a function and
  the control calls it. Clamped from above too: dropping the trailing boundary
  now reddens.
- `PERSON_AXES` was clamped from one side only — removing an axis reddened,
  adding an axis no judge produces did not. Both sides redden now.
- The README quoted `Ran 917 tests` twice, once per language, against a real
  979. The quoted figure is now compared with the run that the same test
  performs, so it cannot drift again.

Corrected on the way: `BIAS_GAIN_MIN` carried "1.0024" as the instrument's own
noise. Measured on the 48-column `REAL_COLUMNS` fixture the gain is 1.0009.
The claim was right, the number was not, and no source for 1.0024 was found.

A writer was mid-way through the provenance work when its session ended. Its
finished part is kept (contiguous-comment window, so a neighbour's mark no
longer satisfies a constant's test); the unfinished part — a tuple assignment
the helper could not find — is completed here, and each of four marks was
stripped in turn to prove it is guarded alone.

Open, from the same audit, not addressed:

- `test_fork_finish.py:726,739` check for a string in the module's own source
  instead of behaviour (introduced before this branch).
- `[:N]` truncation of evidence in `fork_e2e.py` — 18 occurrences, unclassified
  into evidence and data.
- Provenance marks are still absent on `CARD_SAMPLE_FRAMES`, `PERSON_AXES` and
  the three `device.py` constants.
- The journal is still written in blocks rather than as work proceeds.
