# Lip-sync templates

[![CI](https://github.com/greenflac/lipsync-templates/actions/workflows/ci.yml/badge.svg)](https://github.com/greenflac/lipsync-templates/actions/workflows/ci.yml)

The user uploads a selfie, picks a template, and gets a vertical video with
sound where they are the person on screen.

![Client selfie, driving footage, finished video](docs/img/showcase_icecream.gif)

<sub>Left to right: the client's selfie · the driving footage · the finished
video. One template ("Ice cream"), 10 seconds, real speed. The same clip
**with sound**: [showcase_icecream.mp4](docs/video/showcase_icecream.mp4).</sub>

---

The repository contains two tools.

**The generation pipeline** turns a selfie into a finished video in eight
stages, and orders the video exactly once. On a clean run it makes 32 checks:
**22 of them fire before the video is ordered** and 10 after. That is why most
defects are caught on a still image, for cents, instead of on a rendered clip.

**The template builder** is for the person who designs templates: they write a
prompt, feed in a stock demo person, and get back a style reference (an
"aesthetic") that is ready to sell as a template. Building a new template
takes one run.

**Presentation:** [English (PDF)](docs/deck/lipsync_en.pdf) ·
[по-русски (PDF)](docs/deck/lipsync_ru.pdf)

---

## Numbers

| | |
|---|---|
| `$0.07/s` | the video rate, confirmed by four separate balance measurements. The pipeline's default product is 5 seconds — `$0.35` a clip (`PRODUCT_SECONDS` in `fork_e2e`); the six showcase clips below are 10 seconds, so they cost `$0.70` each |
| `0.5581` | the aspect ratio the image model actually returns for a 9:16 request, on both routes — not the `0.5625` of exact 9:16. Asked for `720×1280` and for `864×1536` through `compose` it returns `768×1376`; asked for `1080×1920` through `images_edit` it returns `1536×2752`. nanobanana-2 has no exact 9:16 point on its vertical grid. This is a fact about the model and still holds; what no longer holds is that the product ships it — see the row below |
| `1530×2720` | the size all ten shipped images are — six templates, two client fixtures, two framing references — measured on the files in `assets/`. That is exactly `0.5625`. They were `1536×2752` until commit `1ca55da` on this branch trimmed them: 32 px off the height (1.16 %) and 6 px off the width (0.39 %), inside the 2 % trim budget |
| `720×1280` | what the video model returns, MEASURED on 11 runs on disk: 7 came back exactly 9:16, 3 came back `816×1104`, 1 came back `960×960`. Kling inherits the ratio of the image it is given — every vertical reference produced a vertical clip, and assembly cropped nothing off all six shipped ones |
| `300 frames` | all six showcase videos came out at exactly 10.0 seconds, 30 fps |
| `0 cuts` | no edit seams inside any of the six videos |

## How it works

The eight stages are `fork_e2e.STAGES`; the check counts are from one clean
run of the end-to-end stand.

```
                                                       cost      checks
1  intake of three inputs   photo, style ref, driving   free        4
2  client photo stylization prompt, frame, person       cents       8
3  styled photo acceptance  style hit, identity         free        2
4  driving window           cuts, scene length, window  free        5
5  upload and call Kling    the one video order         $0.07/s     5
6  output acceptance        geometry, identity, cuts    free        4
7  final assembly           9:16, sound, duration       free        2
8  report                   the run written to disk     free        2
```

Stage 5 is where the video is paid for. Three of its five checks — the pro-tier
guard, the input upload and the request composition — run *before* the order
goes out; the remaining two read what came back. Stage 2 is the only other
paid call, and it costs cents on a still image.

Every check returns one of three outcomes: `pass`, `fail`, or `could not
measure`. The third one is never silently converted into the other two, and
every verdict comes with its numbers: how many items were checked, how many
failed, how many could not be measured. Zero failures out of zero checks is
reported as exactly that, not as success.

## Integration

The pipeline logic is not tied to a specific backend or video model.

Every outward call — the model, file uploads, storage — is passed in as a
parameter. That is also why the test suite covers the whole path without
touching the network.

The acceptance checks don't care where their input came from, so they can sit
in front of an existing pipeline as a standalone quality-control layer.

Switching the video model means replacing one call. Kling's current limits
(3-second minimum, unstable frame-by-frame output) belong to the model, not to
the approach: another API model, or an open-source model on your own GPUs,
lifts them.

## Choosing driving footage

The driving video is the only input that gets bought, so its requirements are
a purchasing checklist:

- **Face at least 100 px tall.** Below that the identity can't be measured and
  the model transfers it poorly. Measured: faces of 34–56 px drifted, faces of
  85–139 px held.
- **A single scene with no cuts.** A cut inside the selected window becomes a
  visible shot change in the finished video.
- **A scene longer than the product duration.** The window is cut from the
  middle of the longest scene.
- **The person stays in frame.** The driving's framing is carried into the
  aesthetic prompt, because the model takes the pose from the video.

Lip-sync footage is the hardest case, especially when the actor turns around:
during the turn the face leaves the frame entirely.

## Tests

From the repository root:

```
python3 -m unittest discover -s . -p "test_*.py"
```

The root is not decoration: the suite uses package-relative imports, so
discovering from `lipsync/tests` collects a smaller suite and errors out on the
first relative import.

**1062 tests in 22 files, no network, no GPU.** Run of 2026-08-28, quoted verbatim:

```
Ran 1062 tests in 91.2s

OK (skipped=12)
```

Each test guards a specific defect that actually happened — the test name says
which one. Decision thresholds are covered by mutation: changing a threshold in
either direction makes tests fail.

**A skipped test is not a passed test.** All 12 skips are one class,
`TheMeasuredRowsAreReproduced` in `test_fork_identity.py`: it runs the real
ArcFace against the recorded acceptance rows, and the `buffalo_l` weights and
the `demo/lora_dataset` frames are not in the repository. Without them there is
nothing to reproduce the numbers from, so the class reports "not measured"
rather than green.

The numbers above are a run, not a target. The count moves as the suite is
written; what is quoted is whatever the last run printed.

## Licence

The source is public so it can be read and audited, but this is **not** open
source: using, copying or embedding it requires an agreement. See
[LICENSE](LICENSE).

One more thing worth knowing: the identity check uses InsightFace `buffalo_l`
weights, which are licensed for non-commercial use. As shipped, the acceptance
layer is a development tool; a commercial deployment would swap the face model
and recalibrate the thresholds.

---

# Липсинк-шаблоны

Пользователь загружает селфи, выбирает шаблон и получает вертикальный ролик со
звуком, где снимается он сам.

![Селфи клиента, драйвинг, готовый ролик](docs/img/showcase_icecream.gif)

<sub>Слева направо: селфи клиента · драйвинг · готовый ролик. Один шаблон
(«Мороженое»), 10 секунд, реальная скорость. Тот же ролик **со звуком**:
[showcase_icecream.mp4](docs/video/showcase_icecream.mp4).</sub>

---

В репозитории два инструмента.

**Пайплайн генерации** превращает селфи в готовый ролик за восемь ступеней и
заказывает видео ровно один раз. На чистом прогоне он делает 32 проверки:
**22 из них срабатывают до того, как видео заказано**, и 10 — после. Поэтому
большинство дефектов ловится на картинке за центы, а не на готовом ролике.

**Сборщик шаблонов** — для того, кто шаблоны придумывает: он пишет промт,
подаёт стоковую демо-личность и получает стилевой референс («эстетику»),
готовый к продаже как шаблон. Новый шаблон собирается за один прогон.

**Презентация:** [по-русски (PDF)](docs/deck/lipsync_ru.pdf) ·
[English (PDF)](docs/deck/lipsync_en.pdf)

---

## Числа

| | |
|---|---|
| `$0.07/с` | ставка за видео, подтверждена четырьмя независимыми замерами баланса. Продуктовая длительность по умолчанию — 5 секунд, то есть `$0.35` за ролик (`PRODUCT_SECONDS` в `fork_e2e`); шесть витринных роликов ниже — десятисекундные, они стоили по `$0.70` |
| `0.5581` | соотношение, которое картиночная модель на самом деле отдаёт на запрос 9:16, на обоих маршрутах, — а не `0.5625` ровного 9:16. На запрос `720×1280` и на запрос `864×1536` через `compose` приходит `768×1376`; на запрос `1080×1920` через `images_edit` приходит `1536×2752`. У nanobanana-2 нет точки ровно 9:16 на вертикальной сетке. Это факт о модели, и он в силе; в силе больше не то, что продукт её отдаёт как есть, — см. строку ниже |
| `1530×2720` | размер всех десяти отгруженных картинок — шесть шаблонов, две клиентские фикстуры, два плановых референса, — замерено на файлах в `assets/`. Это ровно `0.5625`. До коммита `1ca55da` на этой ветке они были `1536×2752`; обрезка сняла 32 px высоты (1.16 %) и 6 px ширины (0.39 %) — внутри двухпроцентного бюджета |
| `720×1280` | что отдаёт видеомодель, ИЗМЕРЕНО на 11 прогонах на диске: 7 вернулись ровно 9:16, 3 вернулись `816×1104`, один `960×960`. Kling наследует соотношение поданной картинки — с каждого вертикального референса выходил вертикальный ролик, и на всех шести отгруженных сборка не срезала ничего |
| `300 кадров` | все шесть витринных роликов вышли ровно по 10.0 секунды, 30 fps |
| `0 склеек` | ни в одном из шести роликов нет монтажных швов |

## Как это работает

Восемь ступеней — это `fork_e2e.STAGES`; числа проверок сняты с одного чистого
прогона сквозного стенда.

```
                                                          цена     проверок
1  приём трёх входов     фото, стилевой реф, драйвинг    бесплатно     4
2  стилизация фото       промт, кадр, человек в плане    центы         8
3  приёмка стилизации    попадание в стиль, личность     бесплатно     2
4  окно драйвинга        склейки, длина сцены, окно      бесплатно     5
5  загрузка и Kling      единственный заказ видео        $0.07/с       5
6  приёмка выхода        геометрия, личность, склейки    бесплатно     4
7  финальная сборка      9:16, звук, длительность        бесплатно     2
8  отчёт                 прогон записан на диск          бесплатно     2
```

Деньги за видео списываются на пятой ступени. Три её проверки из пяти —
запрет pro-тарифа, загрузка входов и состав запроса — идут *до* того, как
заказ ушёл; оставшиеся две читают то, что вернулось. Вторая ступень —
единственный другой платный вызов, и он стоит центы на неподвижной картинке.

Каждая проверка возвращает один из трёх исходов: `годно`, `не годно` или
`не смогли проверить`. Третий никогда молча не превращается в первые два, и
рядом с каждым вердиктом стоят его числа: сколько проверено, сколько не
прошло, сколько не удалось измерить. Ноль нарушений при нуле проверок
печатается именно так, а не как успех.

## Встраивание

Логика пайплайна не привязана ни к конкретному бэкенду, ни к видеомодели.

Каждый внешний вызов — модель, загрузка файлов, хранилище — передаётся
параметром. Поэтому же тесты проходят весь путь, не выходя в сеть.

Проверкам приёмки всё равно, откуда пришёл вход: их можно поставить перед
любым существующим пайплайном как отдельный слой контроля качества.

Смена видеомодели — замена одного вызова. Нынешние ограничения Kling (минимум
3 секунды, нестабильная покадровая выдача) относятся к модели, а не к подходу:
другая модель по API или опенсорсная на своих GPU их снимает.

## Как выбирать драйвинг

Драйвинг — единственный вход, который покупается, поэтому требования к нему —
это чек-лист закупки:

- **Лицо не меньше 100 px.** Ниже личность нечем измерить, и модель переносит
  её плохо. Замерено: лица 34–56 px поплыли, лица 85–139 px удержались.
- **Одна сцена без склеек.** Склейка внутри выбранного окна становится
  видимой сменой плана в готовом ролике.
- **Сцена длиннее продуктовой длительности.** Окно вырезается из середины
  самой длинной сцены.
- **Человек не выходит из кадра.** План драйвинга переносится в промт
  эстетики, потому что позу модель берёт из видео.

Липсинк — самый сложный материал, особенно когда актёр разворачивается: на
развороте лицо полностью уходит из кадра.

## Тесты

Из корня репозитория:

```
python3 -m unittest discover -s . -p "test_*.py"
```

Корень здесь не для красоты: набор пользуется относительными импортами пакета,
поэтому запуск из `lipsync/tests` собирает меньший набор и падает ошибкой на
первом же относительном импорте.

**1062 тестов в 22 файлах, без сети и без GPU.** Прогон 2026-08-28, вывод дословно:

```
Ran 1062 tests in 91.2s

OK (skipped=12)
```

Каждый тест сторожит конкретный дефект, который действительно случился, — имя
теста называет какой. Пороги принятия решений покрыты мутациями: сдвиг порога в
любую сторону роняет тесты.

**Пропущенный тест — не пройденный.** Все 12 пропуска — это один класс,
`TheMeasuredRowsAreReproduced` в `test_fork_identity.py`: он гоняет настоящий
ArcFace против записанных строк приёмки, а весов `buffalo_l` и кадров
`demo/lora_dataset` в репозитории нет. Без них воспроизводить числа нечем, и
класс честно говорит «не смогли измерить», а не зеленеет.

Числа выше — это прогон, а не цель. Счёт двигается по мере того, как набор
дописывается; приведено то, что напечатал последний прогон.

## Лицензия

Исходники открыты, чтобы их можно было прочитать и проверить, но это **не**
open source: использование, копирование и встраивание требуют договорённости.
См. [LICENSE](LICENSE).

Ещё одно, о чём стоит знать: проверка личности использует веса InsightFace
`buffalo_l`, а они лицензированы только для некоммерческого применения. В
поставляемом виде слой приёмки — инструмент разработки; коммерческое
развёртывание заменит модель лица и перекалибрует пороги.
