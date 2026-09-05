"""Вопрос спрашивают одним словом, а записано оно под восемнадцатью.

ИЗМЕРЕНО 2026-09-02 на живой базе (1781 строка, 478 моделей):

    моделей, у которых записана цена           79
    из них отвечают на вопрос `price`           7
    молчат, имея цену в базе                   72

То же самое нашлось на вопросе о ЛИЦЕНЗИИ, и там оно в опасную сторону: из 253
моделей с лицензионной строкой на вопрос `license` молчали 14, и у 11 из них
записана НЕКОММЕРЧЕСКАЯ оговорка и больше ничего:

    sd-turbo / license_restriction = «некоммерческая оговорка»
    model_advice("sd-turbo", "license") -> «nothing is recorded»

То есть модель, которую нельзя брать в коммерческую работу, отвечала «о
лицензии ничего не известно» — ровно перед тем решением, которое правило Ц5
велит принимать ПОСЛЕ чтения лицензии. После правки молчит один `fal.ai-*`,
и это верно: у него `portal_license`, условия площадки, а не модели.

СЧИТАТЬ НАДО ТЕМ ЖЕ ПУТЁМ, КАКИМ ИДЁТ ПОЛЬЗОВАТЕЛЬ. Первый замер дал 15 и
включал `ltx-2-3`, у которого лицензия записана — просто под именем `ltx-2.3`.
Считал я по сырым строкам, а `advise` сводит написания (`modelnames.fold`), и
через него молчащих 14. Цифра, снятая мимо продукта, называет работой то, чего
нет.

Проверено глазами (П3) на трёх вопросах подряд:

    model_advice("sync-lipsync-2", "price")  -> "nothing is recorded"
    в базе                                   -> price_per_minute = "$3 per minute of video"
    model_advice("veo-3.1", "price")         -> "nothing is recorded"
    в базе                                   -> price_per_second = "Standard $0.40/s at 720p and 1080p"

Это не «база пустая», это промах ключа: цена записана как `price_per_minute`,
`price_per_second_usd`, `price_per_image_usd` — восемнадцать имён, — а спросили
`price`. Ответ «не измерено» при измеренном факте — та же ложь в заголовке, что
и обратная, и стоит она дороже: спросивший идёт искать заново то, что лежит.

ЧТО ЭТОТ МОДУЛЬ ДЕЛАЕТ

Из спрошенного слова разворачивает СПИСОК ЗАПИСАННЫХ имён, которые на него
отвечают. Ничего не переименовывает и не сливает: ответ возвращается под
настоящими именами атрибутов, каждое со своей единицей, а разворот называется
вслух — молчаливая подмена спрошенного на похожее была бы новым враньём.

ЧЕГО НАРОЧНО НЕ ДЕЛАЕТ (И5: у семьи есть негативный контроль)

Не тянет в семью всё, что звучит похоже. Разобрано по строкам живой базы:

    price_relative = "50% lower"   насколько дешевле другой, а не сколько стоит
    fps = "24"                     частота КАДРОВ на выходе, не скорость работы
    speed_range = "0.7-1.2"        параметр темпа речи, не скорость генерации
    rendering_speed = "TURBO, ..." имя режима, не время
    training_time = "3-6 hours"    обучение голоса, не генерация
    indexing_latency = "0.39 s"    индексация корпуса, не модель

Каждое из них при подстроечном совпадении («time», «speed», «latency») попало
бы в ответ на вопрос «как быстро генерит» и дало бы число, отвечающее не на
тот вопрос. Семья скорости поэтому — закрытый список, а не образец.
"""

from __future__ import annotations

#: Семьи: спрошенное слово -> как узнать записанное имя, которое на него
#: отвечает. `prefixes` для семьи, растущей от канала (цена: портал заводит
#: новую единицу с каждой моделью — `price_per_megapixel_usd` появилось само),
#: `exact` для семьи, где похожие имена означают РАЗНОЕ (скорость).
СЕМЬИ: dict[str, dict[str, tuple[str, ...]]] = {
    "price": {
        "prefixes": ("price",),
        "exact": (),
        # НЕГАТИВНЫЙ КОНТРОЛЬ ЦЕНОВОЙ СЕМЬИ (И5). Поймано чтением собственной
        # выдачи: на вопрос `price` про `eleven_flash_v2_5` приходило
        # `price_relative = "50% lower price per character"`. Это не цена, а
        # сравнение с другой моделью: сколько платят — из него не следует, а
        # разборщик цен уже однажды прочёл ровно эту строку как «50.0»
        # (см. `studio/pipeline.py`). Имя начинается с `price` и потому
        # обязано исключаться поимённо.
        "кроме": ("price_relative",),
    },
    # СЕМЬЯ ПОВЕДЕНИЯ. Заведена 2026-09-03 по находке голден-сета: на вопрос
    # «на что жалуются практики» (`observed_behaviour`) про latentsync ответ
    # был «ничего не записано», а база в этот момент держала о нём ТРИНАДЦАТЬ
    # живых строк ровно об этом — `failure_mode`, `degrades_when`,
    # `limitation`, `artifact_taxonomy`, `metric_blind_spot`. Данные собраны,
    # потребитель смотрит не туда, молчание читается как отсутствие. Это
    # четвёртый случай того же класса за два дня, и первый, который нашёл не
    # человек, а набор задач.
    #
    # ИЗМЕРЕНО на живой базе: `failure_mode` 388 строк, `observed_behaviour`
    # 253, `limitation` 119, `metric_blind_spot` 76, `degrades_when` 59,
    # `artifact_taxonomy` 23.
    #
    # `exact` ПЛЮС УЗКИЕ ПОДСТРОКИ, И ПОДСТРОКИ «limit» СРЕДИ НИХ НЕТ — это и
    # есть негативный контроль семьи (И5). Рядом в базе лежат `character_limit`,
    # `prompt_length_limit`, `text_input_limit`, `file_size_limits`,
    # `upload_limits`, `concurrency_limits`, `keyterms_limit`,
    # `input_image_limits`: это ЧИСЛА API, а не поведение. Семья, ловящая
    # подстроку «limit», ответила бы на «на что жалуются» строкой
    # «character_limit = 5000», и это выглядело бы как ответ.
    #
    # Подстроки взяты те, что не встречаются ни в одном имени-числе:
    # `failure_mode` (ловит `lipsync_identity_failure_mode`), `blind_spot`
    # (ловит `fvd_blind_spot_spatial_bias` и `metric_blind_spots_...`),
    # `artifact` (ловит `upscale_artifacts`).
    "observed_behaviour": {
        "prefixes": (),
        # В `exact` только то, чего НЕ ловит подстрока. Сначала здесь лежали
        # ещё `failure_mode`, `artifact_taxonomy` и `metric_blind_spot` — и
        # мутация, убирающая любое из них, НЕ КРАСИЛА НИЧЕГО: их держала
        # подстрока, а поимённый список был поясом поверх подтяжек. Заслон,
        # который нельзя нарушить наблюдаемо, — не заслон (тот же разбор, что
        # у `portal_license` в семье лицензии).
        "exact": ("observed_behaviour", "degrades_when", "limitation"),
        "подстроки": ("failure_mode", "blind_spot", "artifact"),
        "кроме": (),
    },
    # СЕМЬЯ ВХОДОВ. Заведена 2026-09-03 системным замером, а не по случаю:
    # из 287 имён атрибутов базы семьями достижимы 62, а 1140 строк из 2827
    # отвечают только на своё точное написание. Самый крупный отвечаемый
    # кусок — входы: `requires_inputs` 92 строки, `accepts_inputs` 47, и на
    # естественный вопрос «inputs» продукт отвечал «ничего не записано».
    #
    # ВЫХОД — ОТДЕЛЬНАЯ СЕМЬЯ, И ЭТО НЕ МЕЛОЧЬ. «Что принимает» и «что отдаёт»
    # — разные вопросы, и ответить на один другим значило бы солгать ровно тем
    # способом, от которого семьи и заводились.
    "accepts_inputs": {
        "prefixes": (),
        "exact": (),
        "подстроки": ("input", "accepts", "reference"),
        "кроме": (),
    },
    "produces_outputs": {
        "prefixes": (),
        "exact": (),
        "подстроки": ("output", "produces"),
        "кроме": (),
    },
    # СЕМЬЯ ПРЕДЕЛА ТЕКСТА. Заведена 2026-09-03 тем же системным замером, что
    # и входы: 28 моделей записывают, сколько текста в них влезает, и ни на
    # один естественный вопрос об этом продукт не отвечал.
    #
    # ЗАКРЫТЫЙ СПИСОК, А НЕ ПОДСТРОКА, И ЭТО НЕГАТИВНЫЙ КОНТРОЛЬ (И5). Рядом в
    # базе лежат `text_rendering`, `text_rendering_non_latin`,
    # `text_normalization_default`, `ratio_enum_text_to_video` — все содержат
    # «text» и НЕ отвечают на «сколько текста влезает»; `character_orientation`
    # содержит «character» и говорит про поворот; `long_context_surcharge` —
    # деньги. Подстрочная семья втянула бы все шесть.
    #
    # `max_output_tokens_recommended` СЮДА НЕ ВХОДИТ НАРОЧНО: это предел
    # ВЫХОДА, а вход и выход в этом модуле — разные вопросы (см. семьи
    # `accepts_inputs` и `produces_outputs`). Держать одно правило на входе и
    # другое здесь значило бы иметь два разных представления об одном.
    "text_limit": {
        "prefixes": (),
        "exact": (
            # `max_script_length` («90000 characters») переехал сюда 2026-09-05:
            # он лежал в семье нижней границы длительности, а на вопрос о
            # пределе текста vibevoice отвечал пустотой. Имя-сосед
            # `max_script_characters` означает ровно то же.
            "max_script_length",
            "character_limit",
            "max_text_length",
            "context_window_tokens",
            "prompt_length_limit",
            "text_input_limit",
            "keyterms_limit",
            "max_prompt_length",
            "max_script_characters",
        ),
        "подстроки": (),
        "кроме": (),
    },
    "license": {
        # Приставкой и хвостом: вендоры и каналы заводят имена сами
        # (`license_restriction`, `license_excluded_territories`,
        # `license_no_model_training`), а два имени пишут лицензию ХВОСТОМ —
        # `architecture_and_license`.
        #
        # ПРИСТАВКА, А НЕ ПОДСТРОКА, И ЭТО НЕГАТИВНЫЙ КОНТРОЛЬ СЕМЬИ (И5).
        # `portal_license` — условия ПЕРЕПРОДАЖИ площадкой, а не лицензия
        # весов: на fal.ai все 57 карточек помечены `commercial`, и у модели,
        # чьи веса лежат под «research only», такой ответ дал бы ложный зелёный
        # на правиле Ц5. От семьи его держит ровно то, что он не НАЧИНАЕТСЯ с
        # `license`.
        #
        # ОТДЕЛЬНОГО «КРОМЕ» ЗДЕСЬ НЕТ НАРОЧНО. Оно тут было и оказалось
        # НЕНАБЛЮДАЕМЫМ: мутация, убирающая его, не красит ни одного теста —
        # приставка держит и без него (прогон `scripts/mutate_channels.py`
        # 2026-09-02, мутант промолчал дважды подряд). Заслон, который нельзя
        # нарушить наблюдаемо, — не заслон, а строка в файле.
        #
        # ЕСЛИ ЭТА СЕМЬЯ КОГДА-НИБУДЬ СТАНЕТ ЛОВИТЬ ПОДСТРОКОЙ (как уже сделано
        # у `resolution`), исключение обязано вернуться — и вернуться ВМЕСТЕ с
        # мутацией, которая его показывает. Сейчас это сторожит мутант
        # «приставка стала подстрокой»: он краснеет.
        "prefixes": ("license", "licence"),
        "exact": ("architecture_and_license",),
    },
    "max_seconds": {
        "prefixes": (),
        # СКОЛЬКО СЕКУНД МОЖЕТ ВЫЙТИ НА ВЫХОДЕ. Закрытый список: у соседних
        # имён то же слово «seconds» означает ДРУГУЮ длительность, и разбор
        # сделан по значениям в базе, а не по звучанию.
        #
        #   max_seconds            = 15                    выход
        #   duration_enum          = «4, 6, 8 seconds only» выход
        #   max_duration_ms        = 600000 ms (10 min)     выход, другая единица
        #   duration_quantisation  = «4, 6 or 8 — not continuous» выход
        #
        # ИЗМЕРЕНО 2026-09-02 через `advise`: строка о длительности записана у
        # 45 моделей, а на вопрос `max_seconds` отвечали 25.
        "exact": (
            # Переехало сюда 2026-09-05. `video_lengths_vertex` («4, 6 or 8
            # seconds») лежал в семье НИЖНЕЙ границы, а на вопрос «сколько
            # секунд» про veo-3.1-generate-001 приходила пустота.
            "video_lengths_vertex",
            # ЗАПИСЬ «НЕ СМОГЛИ ИЗМЕРИТЬ» ОТВЕЧАЕТ НА ТОТ ЖЕ ВОПРОС, ЧТО И
            # ИЗМЕРЕНИЕ (Р1): спросивший «сколько секунд» обязан узнать, что
            # мерить пробовали и не смогли, — иначе третий исход лежит в базе
            # и не доезжает до того, кому он адресован.
            "probe_cannot_settle_duration",
            "max_seconds",
            "max_duration_seconds",
            "max_duration_ms",
            "max_video_seconds",
            "duration_enum",
            "duration_enum_seconds",
            "duration_range_seconds",
            "duration_range_t2v_i2v",
            "duration_range_v2v",
            "duration_quantisation",
        ),
        # НЕГАТИВНЫЙ КОНТРОЛЬ (И5): те же слова о ВХОДЕ, не о выходе.
        #   max_audio_seconds              = 30    длина поданного звука
        #   max_input_seconds              = 30    длина поданного видео
        #   reference_video_duration_range = 3..30 длина референса
        #   max_frames                     = 161   кадры, а не секунды: без
        #                                          частоты это не длительность
        "кроме": (),
    },
    "resolution": {
        # Приставки нет: вендоры пишут `max_resolution`, `native_resolution`,
        # `resolutions_vertex` — слово стоит и в начале, и в середине, и в
        # конце. ИЗМЕРЕНО через `advise`: строка о разрешении записана у 40
        # моделей, а на вопрос `resolution` отвечали 2 — канонического имени
        # `resolution` почти ни у кого нет.
        "prefixes": (),
        "exact": (),
        "подстроки": ("resolution",),
        # Разрешение ОБУЧЕНИЯ — не предел входа, и сравнивать с ним креатив
        # значит отвечать не на тот вопрос (то же исключение стоит в
        # `scripts/creative_fit.py`, и берётся оно отсюда — Е1).
        "кроме": ("training_resolution",),
    },
    "generation_time": {
        "prefixes": (),
        "кроме": (),
        # Закрытый список, каждое имя проверено по значению в базе, а не по
        # звучанию. `latency_penalty` — качественное («синтезирует медленнее»),
        # но именно о скорости работы; `realtime_dubbing` — о том, успевает ли
        # модель в реальное время. Оба отвечают на «как быстро».
        "exact": ("generation_time", "latency", "latency_penalty", "realtime_dubbing"),
    },
    # === ПЯТЬ СЕМЕЙ, ЗАВЕДЁННЫХ 2026-09-04 ПО ЗАМЕРУ НЕДОСТИЖИМОСТИ =======
    #
    # ИЗМЕРЕНО: 594 строки базы из 2099 (28.3%) не достаёт НИ ОДИН вопрос, и
    # 256 из них — один атрибут `adoption`. Критерий релиза R3 требует ниже
    # 10%. Ниже — семьи, закрывающие голову этого списка; у каждой назван
    # негативный контроль, потому что семья без него собирает похожее, а не
    # отвечающее.
    # СКОЛЬКО ЛЮДЕЙ ЭТИМ ПОЛЬЗУЕТСЯ. Самая крупная дыра базы: 256 строк, и
    # спросить их было нечем. Приставка, а не подстрока: `adoption` — цельное
    # слово, и ловить им «adopt» внутри чужого имени незачем.
    "adoption": {
        "prefixes": ("adoption",),
        "exact": (),
    },
    # ДЛЯ ЧЕГО ЭТА МОДЕЛЬ ВООБЩЕ. Поимённо, а не подстрокой: рядом в базе
    # лежит `product_identity` — это про бренд площадки, а не про то, какую
    # работу модель делает.
    "positioning": {
        "prefixes": ("positioning",),
        # `tradeoff` = «выше задержка и цена за символ, зато качество» —
        # сравнительное утверждение о нише. В семье «чем мерили» он отвечал на
        # вопрос о МЕТОДЕ измерения текстом без единого числа.
        "exact": ("tradeoff",),
    },
    # ЧТО У НЕЁ НА БЕНЧМАРКАХ. ЗАКРЫТЫЙ СПИСОК, И ЭТО НЕГАТИВНЫЙ КОНТРОЛЬ
    # (И5): подстрока «benchmark» затянула бы
    # `faithfulness_benchmark_saturation` — это оговорка о том, что бенчмарк
    # НАСЫТИЛСЯ, то есть утверждение против числа, а не число. Такая строка
    # принадлежит семье поведения и приходит по вопросу «на что жалуются».
    "benchmark_score": {
        "prefixes": (),
        "exact": ("benchmark_score",),
    },
    # ДЕРЖИТ ЛИ ЛИЦО. Подстрока «identity» НАРОЧНО: спросивший «держит ли
    # лицо» обязан получить и `lipsync_identity_failure_mode`, и
    # `identity_drift_in_commercial_models` — плохая новость по этому вопросу
    # и есть ответ на него. Исключается ровно одно имя: `product_identity` —
    # оно про бренд площадки и на вопрос о лице не отвечает.
    "holds_identity": {
        "prefixes": (),
        "exact": (),
        "подстроки": ("identity",),
        "кроме": ("product_identity",),
    },
    # СНЯТА ЛИ МОДЕЛЬ. Блюпринт называл эту дыру самой опасной: канал сбора
    # специально ходит за «снята ли», а спросить это было нечем. Подстроки
    # закрытые и все — про срок службы; `status` среди них потому, что база
    # несёт `status` и `remix_endpoint_status`, и оба отвечают именно на это.
    "availability": {
        "prefixes": (),
        "exact": (),
        "подстроки": ("avail", "status", "end_of_life", "lifecycle", "deprecat"),
    },
    # НА ЧЁМ ПОСТРОЕНА. Подстрока «architect» ловит и `architecture`, и
    # `architecture_and_license`, и `motion_control_architecture`.
    "architecture": {
        "prefixes": (),
        # `vae_compression` («video length 4, space 8, channel 16») — устройство
        # модели, и 2026-09-05 он лежал в семье «как её позвать»: на вопрос об
        # архитектуре hunyuan-video приходила пустота при записанном факте.
        # Нашла это независимая проверка чтением значений, а не имён.
        "exact": ("vae_compression",),
        "подстроки": ("architect",),
    },
    # ЧТО НУЖНО, ЧТОБЫ ЗАПУСТИТЬ. Одна семья на три вопроса владельца
    # («пойдёт ли на моей карте», «сколько весит», «где крутится»), потому что
    # ответ на них живёт в одной строке карточки модели.
    "hardware": {
        "prefixes": (),
        # `storage_cost` = «257.5 КБ на страницу в float16» — место на диске, а
        # не деньги. Слово `cost` в имени без денег в значении — ровно та же
        # форма, что у документированного `price_relative`; в семье «условия
        # оплаты» он был единственным ответом и читался как цена.
        "exact": ("storage_cost",),
        "подстроки": ("vram", "runs_on", "parameter_count"),
    },
    # НА КАКИХ ЯЗЫКАХ. Подстрока «language» ловит `languages`,
    # `prompt_language`, `language_control`.
    "languages": {
        "prefixes": (),
        "exact": (),
        "подстроки": ("language",),
    },
    # === ЗАВЕДЕНО 2026-09-05 РАДИ R3 =======================================
    # Владелец потребовал довести достижимость базы до 95%: строка, до которой
    # не доводит ни одно спрашиваемое слово, для продукта не существует.
    # Было недостижимо 197 строк из 2127 (9.3%) под потолком 10% — то есть
    # потолок разрешал не уметь спросить каждую одиннадцатую собранную строку.
    # Каждая семья ниже названа ВОПРОСОМ, который заказчик действительно
    # задаёт, и у каждой выписан негативный контроль: имя, которое звучит
    # похоже и в семью НЕ берётся, с причиной (И5).
    "aspect_ratio": {
        # «В каких пропорциях кадр» — первый вопрос про вертикальный ролик.
        # ПРЕФИКС, А НЕ ПОДСТРОКА `ratio`: подстрока тянет `duration_range`,
        # `moderation`, `generation_time`, `price_per_generation` и
        # `faithfulness_benchmark_saturation` — 26 имён вместо 9, и на вопрос
        # о пропорциях пришла бы цена.
        "prefixes": ("aspect_ratio", "ratio_enum"),
        "exact": (),
        "подстроки": (),
        "кроме": (),
    },
    "frame_rate": {
        # «Сколько кадров в секунду и сколько их всего».
        # ЗАКРЫТЫЙ СПИСОК: подстрока `frame` тянет `first_last_frame` (это про
        # монтаж, а не про частоту), `native_resolution_and_frames` (там
        # разрешение) и `keyframe_conditioning_tradeoff` (находка бенчмарка).
        "prefixes": (),
        "exact": (
            "fps",
            "frame_rate",
            "frames_and_fps",
            "num_frames_range",
            "max_frames",
        ),
        "подстроки": (),
        "кроме": (),
    },
    "voice": {
        # «Что модель умеет с голосом»: клонирование, дикторы, длина дорожки.
        # `speed_range` живёт ЗДЕСЬ, а не в семье скорости, и это записано в
        # шапке модуля с самого начала: `0.7-1.2` — темп РЕЧИ, и в ответе на
        # «как быстро генерит» он был бы числом не про то.
        # ЗАКРЫТЫЙ СПИСОК ПО ЗВУКУ: подстрока `audio` тянет
        # `price_per_audio_second`, то есть цену.
        "prefixes": ("voice_", "tts_"),
        "exact": (
            "own_voice_only",
            "max_speakers",
            "cloning_strength",
            "audio_required",
            "audio_default",
            "max_audio_seconds",
            "training_audio_minutes",
            "stress_control",
            "text_normalization_default",
            "speech_timing_guidance",
            "speed_range",
        ),
        "подстроки": (),
        "кроме": (),
    },
    "editing": {
        # «Умеет ли править готовое и продолжать ролик».
        # ЗАКРЫТЫЙ СПИСОК ПО `edit`: подстрока тянет `prompt_rule_edit` — это
        # правило НАПИСАНИЯ промта, оно отвечает на другой вопрос и живёт в
        # семье `prompt_rule`.
        # ПРЕФИКС `expand` ОТСЮДА УБРАН ПОСЛЕ ЧТЕНИЯ ВЫДАЧИ ГЛАЗАМИ (П3).
        # `expands_internally` и `expander_evidence` — это про РАСШИРЕНИЕ
        # ПРОМПТА (`--use_prompt_extend`, «переписывание в 80-100 слов»), а не
        # про продление ролика. На вопрос «умеет ли править готовое» приходила
        # строка «длина промпта коррелирует с качеством на -0.07» — ответ не на
        # тот вопрос. Семья `prompt_rule` его и забрала.
        "prefixes": ("extension",),
        "exact": (
            "editing",
            "edit_support",
            "editing_rule",
            "editing_reference_syntax",
            "video_edit_upload_gated",
            "video_to_video",
            "first_last_frame",
            "mask_requirements",
            "max_total_length_via_extension",
            # `keyframes_max` («1-10 images; [seconds, image] pairs pin exact
            # times») — это раскадровка на входе, а не частота кадров на выходе.
            "keyframes_max",
            "loop_mode",
            "long_video_method",
            "segment_duration",
        ),
        "подстроки": (),
        "кроме": (),
    },
    "prompt_rule": {
        # «Как писать промт именно для этой модели» — вопрос, ради которого
        # продукт и существует.
        # ЗАКРЫТЫЙ СПИСОК: подстрока `prompt` тянет `max_prompt_length` и
        # `prompt_length_limit` (это предел текста, семья `text_limit`) и
        # `arena_rank_vs_prompt_adherence` (это бенчмарк). Разные вопросы.
        "prefixes": ("prompt_rule", "expand"),
        "exact": (
            "prompt_skeleton",
            "prompt_upsampling",
            "prompt_upsampling_scope",
            "negative_prompts",
            "lipsync_prompt_rule",
            "dialogue_prompt_rule",
            "hex_color_control",
            "steps_and_guidance",
            "sample_guidance",
            "safety_tolerance",
            "expression_intensity_range",
            "character_orientation",
            "strength",
            "controls",
            "sync_mode_enum",
        ),
        "подстроки": (),
        "кроме": (),
    },
    "limits": {
        # «Сколько за раз и как часто» — квоты, параллельность, размеры файлов.
        # НЕ БЕРЁТСЯ `text_limit`: предел ТЕКСТА — свой вопрос и своя семья;
        # смешать их значило бы на вопрос «сколько роликов за раз» получить
        # длину промпта.
        "prefixes": (),
        "exact": (
            "concurrency",
            "concurrency_limits",
            "upload_limits",
            "plan_slots",
            "images_per_request",
            "max_videos_per_prompt_vertex",
            "file_size_limits",
            "max_image_payload",
            "size_constraints",
            "result_url_expiry",
            "probe_discloses_limits",
            "unsupported_params",
            "reasoning_effort_levels",
        ),
        "подстроки": (),
        "кроме": (),
    },
    "billing": {
        # «Как за это платят» — не СКОЛЬКО (это семья `price`), а на каких
        # условиях: план, хранение, порог выручки, доплата за длинный контекст.
        # `price_relative` попадает СЮДА, а не в `price`, и это то же решение,
        # что записано в негативном контроле ценовой семьи: «на 50% дешевле» —
        # сравнение с другой моделью, из него не следует, сколько платят.
        "prefixes": (),
        "exact": (
            "billing_requirement",
            "commercial_revenue_threshold",
            "long_context_surcharge",
            "search_grounding_price",
            "price_relative",
            "probe_blocked_by_balance",
            "portal_license",
        ),
        "подстроки": (),
        "кроме": (),
    },
    "model_identity": {
        # «Как её позвать» — идентификатор, версия, эндпоинт, снимок.
        # НЕ БЕРЁТСЯ `availability`: «снята ли модель» — вопрос о том, работает
        # ли она вообще, и он решает судьбу плана; «как её позвать» — вопрос о
        # строке в запросе. Слить их значило бы отвечать на первый вторым.
        # `endpoint_` НЕ ПРЕФИКС: имён с ним ровно два, и они отвечают на разные
        # вопросы — `endpoint_pinning` («как её позвать», сюда) и
        # `endpoint_purpose` («что этот эндпоинт делает», в семью умений).
        "prefixes": ("version_",),
        "exact": (
            "endpoint_pinning",
            "model_id",
            "model_enum",
            "underlying_model",
            "vertex_endpoint_migration",
            "default_snapshot",
            "comfyui_node",
            "provenance",
            "model_sizes",
            "knowledge_cutoff",
        ),
        "подстроки": (),
        "кроме": (),
    },
    "capabilities": {
        # «Что она вообще умеет и для чего» — рядом с `positioning`, но
        # отвечает на вопрос о СПИСКЕ умений, а не о нише.
        # ПРЕФИКС `lipsync` ОТСЮДА УБРАН: он забирал `lipsync_identity_failure_mode`
        # и `lipsync_artefacts` у семей «держит ли лицо» и «как ведёт себя», то
        # есть уводил ПЛОХИЕ НОВОСТИ из ответа на вопрос, ради которого их и
        # записывали. Поймали это чужие тесты, а не мои: сторож семьи поведения
        # проверяет полный список её имён и потому краснеет на любом уводе.
        "prefixes": (),
        "exact": (
            "lipsync",
            "lipsync_support",
            "lipsync_model_selection",
            "capabilities",
            # Переехали 2026-09-05 из «как её позвать» и «лимиты»: это про то,
            # ЧТО отдаёт эндпоинт и что модель умеет, а не про строку в запросе.
            "images_endpoint_metadata",
            "authenticated_read_reachable",
            "prompt_metadata_exposed",
            "tool_use",
            "modes",
            "modalities",
            "modality",
            "role",
            "product_identity",
            "best_for",
            "summary_line",
            "text_rendering",
            "text_rendering_non_latin",
            "transparent_background",
            "watermark",
            "moderation",
            "consent_gate",
            "face_requirement",
            "human_face_restriction",
            "grounding_search",
            "retrieval_grounding",
            "embedding_types",
            "endpoint_purpose",
        ),
        "подстроки": (),
        "кроме": (),
    },
    "image_size": {
        # «Какого размера картинка на выходе» — отдельно от `resolution`,
        # которая про видео: `default_short_side` и `upscale_path` бессмысленны
        # в ответе на вопрос о разрешении ролика.
        # ПРЕФИКС `upscale` ОТСЮДА УБРАН ПО ТОЙ ЖЕ ПРИЧИНЕ, ЧТО И `lipsync` В
        # СЕМЬЕ УМЕНИЙ: он забирал `upscale_artifacts` у семьи «как ведёт себя»,
        # то есть уводил жалобу на артефакты из ответа на вопрос о проблемах.
        # Два увода за один заход — поэтому дальше в этих семьях только
        # поимённые списки: префикс дешевле писать и дороже проверять.
        "prefixes": (),
        "exact": (
            "upscale_path",
            "upscale_mechanism",
            "size_options",
            "image_size_options",
            "sample_image_size_models_vertex",
            "quality_options",
            "default_short_side",
            "training_resolution",
        ),
        "подстроки": (),
        "кроме": (),
    },
    "duration_floor": {
        # «Короче какого предела нельзя» и какие длины вообще бывают. Семья
        # `max_seconds` отвечает на ПОТОЛОК, и подмешать туда минимум значило
        # бы отдать на вопрос «сколько максимум» число «сколько минимум».
        "prefixes": (),
        "exact": (
            "min_seconds",
            "supported_durations",
        ),
        "подстроки": (),
        "кроме": (),
    },
    "measurement_method": {
        # «Чем это мерили и насколько мерке верить» — находки о самих
        # бенчмарках и о протоколе оценки. Отдельно от `benchmark_score`:
        # там ЧИСЛО, здесь — можно ли этому числу верить.
        "prefixes": ("vlm_judge",),
        "exact": (
            "evaluation_protocol",
            "arena_rank_vs_prompt_adherence",
            "faithfulness_benchmark_saturation",
            "single_vs_multishot_quality_drop",
            "keyframe_conditioning_tradeoff",
            "retrieval_quality",
            "physics_ceiling",
            "speed_publication",
            "training_time_contested",
        ),
        "подстроки": (),
        "кроме": (),
    },
    "serving": {
        # «Где стоит и как быстро отвечает СЛУЖБА» — не модель. Семья
        # `generation_time` закрыта списком именно потому, что `queue_latency`
        # и `ttfb_by_region` — про очередь и регион, а не про то, сколько
        # считается кадр; в ответе на «как быстро генерит» они дали бы число
        # не про то (это записано в шапке модуля).
        "prefixes": (),
        "exact": (
            "serving_regions",
            "ttfb_by_region",
            "queue_latency",
            "indexing_latency",
            "rendering_speed",
            "speed_relative",
            "training_time",
        ),
        "подстроки": (),
        "кроме": (),
    },
}

#: Слова, которыми спрашивают то же самое. Спрашивает человек и модель, а не
#: схема базы, и «cost» вместо `price` — не опечатка, а нормальный язык.
СИНОНИМЫ: dict[str, str] = {
    "cost": "price",
    "pricing": "price",
    "цена": "price",
    "стоимость": "price",
    "speed": "generation_time",
    "лицензия": "license",
    "licence": "license",
    "licensing": "license",
    "latency": "generation_time",
    "generation_speed": "generation_time",
    "скорость": "generation_time",
    # Слова, которыми про поведение спрашивают на самом деле. «Применимость» —
    # наше внутреннее слово, «проблемы» — слово владельца из постановки задачи.
    "behaviour": "observed_behaviour",
    "behavior": "observed_behaviour",
    "problems": "observed_behaviour",
    "issues": "observed_behaviour",
    "проблемы": "observed_behaviour",
    "жалобы": "observed_behaviour",
    "наблюдения": "observed_behaviour",
    "применимость": "observed_behaviour",
    # Слова, которыми про эти пять семей спрашивают на самом деле.
    "popularity": "adoption",
    "популярность": "adoption",
    "downloads": "adoption",
    "используют": "adoption",
    "для_чего": "positioning",
    "позиционирование": "positioning",
    "benchmark": "benchmark_score",
    "бенчмарк": "benchmark_score",
    "identity": "holds_identity",
    "лицо": "holds_identity",
    "идентичность": "holds_identity",
    "снята": "availability",
    "end_of_life": "availability",
    "deprecated": "availability",
    "status": "availability",
    "доступность": "availability",
    "архитектура": "architecture",
    "vram": "hardware",
    "железо": "hardware",
    "runs_on": "hardware",
    "parameter_count": "hardware",
    "языки": "languages",
    "duration": "max_seconds",
    "max_duration": "max_seconds",
    "длительность": "max_seconds",
    "длина": "max_seconds",
    "разрешение": "resolution",
    # Вход и выход спрашивают этими словами.
    "inputs": "accepts_inputs",
    "input": "accepts_inputs",
    "вход": "accepts_inputs",
    "входы": "accepts_inputs",
    "что принимает": "accepts_inputs",
    "outputs": "produces_outputs",
    "text_limit": "text_limit",
    "character_limit": "text_limit",
    "max_text_length": "text_limit",
    "context_window": "text_limit",
    "предел текста": "text_limit",
    "сколько текста": "text_limit",
    "output": "produces_outputs",
    "выход": "produces_outputs",
    "что отдаёт": "produces_outputs",
    "max_resolution": "resolution",
}


def приставки_семей() -> tuple[str, ...]:
    """Все приставки, объявленные семьями: занятое ими имя подстрокой не берётся.

    ИЗМЕРЕНО 2026-09-03: без этого правила семья входов забирала
    `price_per_input_second`, `price_per_input_minute` и
    `price_per_million_input_usd` — три строки, каждая из которых отвечает на
    вопрос «что принимает модель» ценой в долларах.

    СВОЯ ПРИСТАВКА ИЗ СПИСКА НЕ ВЫЧИТАЕТСЯ, и это не недосмотр. Сначала
    вычиталась — и мутация, убирающая вычитание, ПРОМОЛЧАЛА: своё имя семья
    берёт ВЕТКОЙ ПРИСТАВКИ, которая стоит в `or` раньше подстрочной, так что
    вычитание не меняло ни одного исхода. Третий такой пояс поверх подтяжек за
    день; снят по тому же правилу, что `portal_license` и поимённый список в
    семье поведения.
    """
    return tuple(sorted({п for правило in СЕМЬИ.values() for п in правило.get("prefixes", ())}))


def семья(спрошено: str) -> str:
    """Имя семьи для спрошенного слова, или пустая строка.

    Пустая строка — это «семьи нет», и она обязана оставаться отличимой от
    имени семьи: атрибут без семьи спрашивается ТОЧНО так, как назван, и
    разворачивать его нельзя (Р1: третий исход не сворачивается во второй).
    """
    ключ = str(спрошено or "").strip().lower()
    ключ = СИНОНИМЫ.get(ключ, ключ)
    return ключ if ключ in СЕМЬИ else ""


def expand(asked: str, recorded: list[str] | tuple[str, ...]) -> list[str]:
    """Записанные имена, отвечающие на `asked`. Спрошенное — всегда первым.

    :param asked: слово из вопроса (`price`, `cost`, `скорость`, `max_seconds`).
    :param recorded: имена атрибутов, ЗАПИСАННЫЕ у этой модели.
    :returns: имена из `recorded`; пустой список, если не отвечает ничто.

    Разворот идёт по тому, что записано у ЭТОЙ модели, а не по словарю всех
    возможных имён: список ради полноты вернул бы `price_per_token` там, где
    его нет, и ответ распух бы пустыми ключами.
    """
    слово = str(asked or "").strip()
    имена = [str(и) for и in recorded]
    if not слово:
        return list(имена)

    имя_семьи = семья(слово)
    if not имя_семьи:
        return [слово] if слово in имена else []

    правило = СЕМЬИ[имя_семьи]
    занятые = приставки_семей()
    подошли = [
        и
        for и in имена
        if и not in правило.get("кроме", ())
        and (
            и in правило["exact"]
            or any(и.lower().startswith(п) for п in правило["prefixes"])
            or (
                any(п in и.lower() for п in правило.get("подстроки", ()))
                # ЧУЖАЯ ПРИСТАВКА СИЛЬНЕЕ СВОЕЙ ПОДСТРОКИ. `price_per_input_second`
                # содержит «input», и семья входов ответила бы на «что она
                # принимает» СУММОЙ В ДОЛЛАРАХ. Правило общее, а не список
                # исключений: списки исключений гниют, а приставка ценовой семьи
                # объявлена в ней самой и живёт в одном месте (Е1).
                and not any(и.lower().startswith(п) for п in занятые)
            )
        )
    ]
    # Спрошенное буквальное имя — первым, если оно записано: читают сверху, и
    # ответ на заданный вопрос не должен стоять третьим среди родственников.
    подошли.sort(key=lambda и: (и != слово, и))
    return подошли


def как_отвечено(asked: str, использованы: list[str]) -> str:
    """Строка «спросили одно, ответили другим» — или пустая, если совпало.

    Разворот называется ВСЛУХ. Молча подставить `price_per_minute` на вопрос
    `price` значит ответить на другой вопрос и не сказать об этом: читающий
    сравнит минуту с секундой соседней модели и получит разницу в шестьдесят
    раз на ровном месте.
    """
    слово = str(asked or "").strip()
    if not слово or not использованы or использованы == [слово]:
        return ""
    if len(использованы) == 1:
        return (
            f"спрошено {слово!r}, а записано под именем {использованы[0]!r} — "
            "единица ответа в этом имени, не в вопросе."
        )
    return (
        f"спрошено {слово!r}, а записано под именами: {', '.join(использованы)}. "
        "Единицы у них РАЗНЫЕ и между собой не переводятся — сравнивать значения "
        "можно только внутри одного имени."
    )
