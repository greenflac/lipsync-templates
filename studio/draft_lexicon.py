"""МНОГОЯЗЫЧНЫЙ СЛОВАРЬ ЧЕРНОВИКА: медиа, владение, работа, длительность — на любом письме.

ЗАЧЕМ (2026-10-16, восьмой круг). Черновик спецификации (`brief_spec.draft`)
читал только латиницу и кириллицу: токенизатор `[a-zа-яё0-9]`. Бриф на
японском, китайском, корейском, арабском, хинди или тайском давал ПУСТОЙ
черновик (валидатор v8: 8 из 103), испанский — тоже. Здесь — маленький
словарь понятий на ja/zh/ko/ar/hi/th/es/pt/de/fr (+ru/kk, уже покрытые
основным разборщиком) и чтение письма. Только для ЧЕРНОВИКА: план по этим
словам не строится, их подтверждает вызывающий.

ПРАВИЛО: незнакомое остаётся отсутствующим. Каждое понятие — список форм;
совпала форма — поле читается, не совпала — поля нет (и вопрос задаётся). У
письма без пробелов (CJK, тайский) «рядом» — окно символов, у остальных — слов.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

#: Окно «рядом» для письма без пробелов, символов (притяжательное перед медиа).
CJK_WINDOW = 10
#: Окно «рядом» для письма с пробелами, слов.
WORD_WINDOW = 3

# --- письмо --------------------------------------------------------------------

#: Письмо -> тег языка, когда язык не назван словом. Порядок важен: кана
#: старше иероглифов (японский текст полон кандзи).
SCRIPTS: tuple[tuple[str, str], ...] = (
    ("ja", r"[぀-ヿ]"),
    ("ko", r"[가-힯ᄀ-ᇿ]"),
    ("zh", r"[一-鿿]"),
    ("ar", r"[؀-ۿ]"),
    ("hi", r"[ऀ-ॿ]"),
    ("th", r"[฀-๿]"),
    ("he", r"[֐-׿]"),
)
#: Письмо без пробелов между словами.
_БЕЗ_ПРОБЕЛОВ = re.compile(r"[぀-ヿ一-鿿฀-๿]")


def script_language(текст: str) -> str | None:
    """Язык по письму брифа (`SCRIPTS`); латиница и кириллица — None (письмо не решает)."""
    for тег, образец in SCRIPTS:
        if len(re.findall(образец, текст or "")) >= 2:
            return тег
    return None


def normalise(текст: str) -> str:
    """Нижний регистр и цифры любого письма -> ASCII («٣٠» -> «30», «๖๐» -> «60»)."""
    out = []
    for ch in str(текст or ""):
        if ch.isdigit() and not ch.isascii():
            try:
                out.append(str(unicodedata.digit(ch)))
                continue
            except (TypeError, ValueError):
                pass
        out.append(ch)
    return " ".join("".join(out).lower().split())


# --- понятия -------------------------------------------------------------------

#: Медиа-существительные по видам входа (`brief_spec.INPUT_KINDS`).
MEDIA: dict[str, tuple[str, ...]] = {
    "video": (
        "视频", "影片", "录像", "動画", "ビデオ", "映像", "영상", "동영상", "비디오", "فيديو", "مقطع",
        "वीडियो", "วิดีโอ", "คลิป", "vídeo", "vídeos", "vidéo", "vidéos", "clip", "film", "película",
    ),
    "photo": (
        "照片", "图片", "图像", "相片", "写真", "画像", "사진", "이미지", "صورة", "صورت", "صور",
        "फोटो", "तस्वीर", "รูป", "ภาพถ่าย", "foto", "fotos", "imagen", "imágenes", "imagem", "bild",
        "bilder", "photo", "photos",
    ),
    "audio": (
        "录音", "音频", "録音", "音声データ", "녹음", "오디오", "تسجيل", "ملف صوتي", "रिकॉर्डिंग",
        "ऑडियो", "ไฟล์เสียง", "audio", "grabación", "gravação", "aufnahme", "enregistrement",
        # Встреча/совещание — запись разговора (материал расшифровки).
        "会議", "会议", "회의", "اجتماع", "मीटिंग", "การประชุม", "reunión", "reunião", "besprechung", "réunion",
    ),
}

#: Притяжательное и указательное, делающее медиа СВОИМ («我们的», «この», «mi»,
#: «tengo»). Третье лицо («su», «его») сюда не входит: чьё — не сказано.
OWN: tuple[str, ...] = (
    "我们的", "我的", "这段", "这个", "这些", "我们", "私の", "弊社の", "当社の", "うちの", "自分の", "この",
    "우리", "저희", "제", "내", "لدينا", "عندي", "هذا", "هذه", "हमारे", "हमारा", "हमारी", "मेरा",
    "मेरे", "मेरी", "ของเรา", "ของฉัน", "นี้", "mi", "mis", "nuestro", "nuestra", "nuestros", "tengo",
    "meu", "minha", "nosso", "nossa", "tenho", "mein", "meine", "unser", "unsere", "habe", "mon", "ma",
    "mes", "notre", "nos", "j'ai", "біздің", "менің",
)

#: Работа словами. Порядок — старшинство (как `DRAFT_TASK_CUES`).
TASKS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "transcribe",
        ("文字起こし", "转录", "转写", "听写", "받아쓰기", "전사", "녹취", "تفريغ", "ट्रांसक्राइब", "ถอดเสียง",
         "ถอดความ", "transcrib", "transcrev", "transkribier", "transcri"),
    ),
    (
        "remove-background",
        ("背景を白", "背景を透明", "背景を消", "背景を削除", "背景を差し替え", "背景を", "去除背景", "去背景",
         "抠图", "移除背景", "배경 제거", "배경을 제거", "إزالة الخلفية", "बैकग्राउंड हटा", "ลบพื้นหลัง",
         "quitar el fondo", "eliminar el fondo", "remover o fundo", "hintergrund entfernen",
         "supprimer l'arrière-plan"),
    ),
    (
        "dub-translate",
        ("配成", "配音成", "翻译成", "翻訳して", "吹き替え", "더빙", "دبلجة", "डब", "พากย์เป็น", "doblar",
         "doblaje", "dublar", "dublagem", "synchronisier", "doublage", "doubler"),
    ),
    (
        "voice-clone",
        ("声音克隆", "克隆声音", "声をクローン", "음성 복제", "목소리 복제", "استنساخ الصوت", "आवाज़ क्लोन",
         "โคลนเสียง", "clonar la voz", "clonar su voz", "stimme klonen", "cloner la voix"),
    ),
    (
        "avatar",
        ("照片说话", "照片开口", "写真を話", "写真がしゃべ", "사진이 말", "تتكلم", "फोटो बोल", "foto hable",
         "foto hablar", "foto fale", "foto falar", "foto sprechen", "photo parle", "аватар"),
    ),
)

#: «Двигать губы» — для дубляжа (`spec.lipsync`).
LIPSYNC: tuple[str, ...] = (
    "口型", "口パク", "リップシンク", "립싱크", "입 모양", "مزامنة الشفاه", "लिप सिंक", "लिपसिंक", "ลิปซิงค์",
    "sincronización labial", "sincronia labial", "lippensynchron", "synchronisation labiale",
)

#: Заказ генерации («сделай», «生成»): работа «generate», когда другой нет.
MAKE: tuple[str, ...] = (
    "生成", "制作", "做一个", "做一段", "作って", "作成", "作りたい", "만들", "생성", "اصنع", "أنشئ", "صمم",
    "बनाइए", "बनाओ", "बनाएं", "बनाना", "สร้าง", "ทำ", "crea", "créer", "genera", "gera", "erstelle",
    "crée", "haz",
)

#: Выходы словами.
OUTPUTS: dict[str, tuple[str, ...]] = {
    "video": MEDIA["video"] + ("广告片", "動画広告"),
    "image": ("图片", "图像", "画像", "이미지", "그림", "صورة", "छवि", "तस्वीर", "ภาพ", "imagen", "imagem", "bild", "image"),
    "speech": (
        "配音", "旁白", "解说", "ナレーション", "吹き替え", "내레이션", "낭독", "오디오북", "성우", "목소리",
        "تعليق صوتي", "بتعليق صوتي", "आवाज़", "आवाज", "वॉयसओवर", "เสียงบรรยาย", "เสียงพากย์", "narración",
        "locución", "voz", "narração", "locução", "sprecher", "vertonung", "voix off", "narration",
    ),
    "music": ("音乐", "音楽", "bgm", "음악", "موسيقى", "संगीत", "เพลง", "música", "musik", "musique"),
}

#: Язык, названный словом (не письмом).
LANGUAGES: dict[str, tuple[str, ...]] = {
    "zh": ("中文", "普通话", "汉语", "國語", "国语", "mandarin"),
    "ja": ("日本語", "日语", "日文"),
    "ko": ("한국어", "韩语", "朝鲜语"),
    "ar": ("العربية", "عربي", "عربية"),
    "hi": ("हिंदी", "हिन्दी"),
    "th": ("ภาษาไทย",),
    "en": ("英文", "英语", "英語", "영어", "الإنجليزية", "अंग्रेज़ी", "अंग्रेजी", "ภาษาอังกฤษ", "inglés", "inglês", "englisch", "anglais"),
    "es": ("español", "castellano", "espanhol", "spanisch", "espagnol"),
    "pt": ("português", "portugués", "portugiesisch", "portugais"),
    "de": ("deutsch", "alemán", "alemão", "allemand"),
    "fr": ("français", "francés", "francês", "französisch"),
    "ru": ("русск", "ruso", "russe", "russisch"),
    "kk": ("қазақ", "казахск"),
}

#: Длительность: число и единица на любом языке.
_СЕКУНДЫ = r"秒钟|秒|초|ثانية|ثوان\w*|सेकंड|सेकेंड|วินาที|segundos?|sekunden|secondes?|seg\b"
_МИНУТЫ = r"分钟|分間|分|분|دقيقة|دقائق|मिनट|นาที|minutos?|minuten|minutes?"
_ЧАСЫ = r"小时|時間|시간|ساعة|ساعات|घंटे|घंटा|ชั่วโมง|horas?|stunden?|heures?"
DURATION = re.compile(rf"(\d+(?:[.,]\d+)?)\s*(?:({_СЕКУНДЫ})|({_МИНУТЫ})|({_ЧАСЫ}))")
#: Счёт картинок («10枚», «10장», «10 صور»).
COUNT = re.compile(r"(\d{1,3})\s*(?:枚|张|張|장|صور|तस्वीरें|ภาพ|fotos|imágenes|imagens|bilder|photos)")

VERTICAL = ("竖屏", "縦型", "縦長", "세로", "عمودي", "वर्टिकल", "แนวตั้ง", "vertical", "vertikal", "verticale", "vertikales")
HORIZONTAL = ("横屏", "横型", "가로", "أفقي", "हॉरिजॉन्टल", "แนวนอน", "horizontal", "horizontale")

#: Валюта словами письма (дополняет `brief_spec.CURRENCY_WORDS`).
CURRENCY: tuple[tuple[str, str], ...] = (
    ("JPY", r"円|日元"),
    ("CNY", r"元人民币|人民币|元"),
    ("KRW", r"원|₩"),
    ("INR", r"रुपये|रुपए"),
    ("THB", r"บาท|฿"),
    ("SAR", r"ريال"),
)


# --- чтение --------------------------------------------------------------------


def _есть(текст: str, формы: Iterable[str]) -> list[int]:
    """Позиции всех форм в тексте (подстрокой для письма без пробелов, словом для остальных)."""
    позиции: list[int] = []
    for ф in формы:
        if _БЕЗ_ПРОБЕЛОВ.search(ф) or not re.match(r"^[\w'’ ]+$", ф):
            позиции += [м.start() for м in re.finditer(re.escape(ф), текст)]
        else:
            позиции += [м.start() for м in re.finditer(rf"(?<![\w]){re.escape(ф)}(?![\w])", текст)]
    return sorted(позиции)


def mentions(текст: str, формы: Iterable[str]) -> bool:
    return bool(_есть(текст, формы))


def owned_media(текст: str) -> dict[str, bool | None]:
    """Виды медиа, названные в тексте: True — со своим притяжательным рядом, None — без."""
    итог: dict[str, bool | None] = {}
    свои = _есть(текст, OWN)
    for вид, формы in MEDIA.items():
        for p in _есть(текст, формы):
            до = текст[max(0, p - CJK_WINDOW) : p]
            рядом = any(max(0, p - CJK_WINDOW) <= s < p for s in свои)
            if not _БЕЗ_ПРОБЕЛОВ.search(до):
                слова = до.split()[-WORD_WINDOW:]
                рядом = any(с.strip(",.;:()¿¡«»\"'") in OWN for с in слова)
            if рядом:
                итог[вид] = True
            else:
                итог.setdefault(вид, None)
    return итог


def task(текст: str) -> str | None:
    for работа, формы in TASKS:
        if mentions(текст, формы):
            return работа
    if mentions(текст, MAKE):
        return "generate"
    return None


#: Назначение перед медиа («สำหรับวิดีโอ» — «для видео»): названное видео —
#: куда пойдёт заказ, а не сам заказ.
PURPOSE: tuple[str, ...] = (
    "สำหรับ", "用于", "为了", "のための", "用の", "向けの", "向け", "위한", "용 ", "के लिए", "para", "für", "pour", "لـ", "من أجل",
)
#: Окно назначения, символов.
PURPOSE_WINDOW = 8


def outputs(текст: str) -> list[str]:
    назначение = _есть(текст, PURPOSE)
    итог = []
    for вид, формы in OUTPUTS.items():
        позиции = _есть(текст, формы)
        if not позиции:
            continue
        if вид == "video" and all(
            any(0 <= p - n <= PURPOSE_WINDOW for n in назначение) for p in позиции
        ):
            continue
        итог.append(вид)
    return итог


def languages(текст: str) -> list[str]:
    return sorted(тег for тег, формы in LANGUAGES.items() if mentions(текст, формы))


def source_languages(текст: str) -> list[str]:
    """Языки, стоящие ПЕРЕД медиа-существительным («英文产品视频»): язык исходника, а не цели."""
    итог = []
    видео = _есть(текст, MEDIA["video"])
    for тег, формы in LANGUAGES.items():
        for p in _есть(текст, формы):
            if any(0 < v - p <= CJK_WINDOW for v in видео):
                итог.append(тег)
    return sorted(set(итог))


def duration_s(текст: str) -> float | None:
    м = DURATION.search(текст)
    if not м:
        return None
    n = float(м.group(1).replace(",", "."))
    return n * (1 if м.group(2) else 60 if м.group(3) else 3600)


def count(текст: str) -> int | None:
    м = COUNT.search(текст)
    return int(м.group(1)) if м else None


def aspect(текст: str) -> str | None:
    if mentions(текст, VERTICAL):
        return "9:16"
    if mentions(текст, HORIZONTAL):
        return "16:9"
    return None


def money(текст: str) -> tuple[float, str] | None:
    for код, слова in CURRENCY:
        м = re.search(rf"(\d[\d,]{{0,12}}(?:\.\d{{1,2}})?)\s*(?:{слова})", текст)
        if м:
            return float(м.group(1).replace(",", "")), код
    return None
