#!/usr/bin/env python3
"""Звуковые эффекты и печать на форме — генерируются, а не скачиваются.

Эфирная графика живёт в `render_gfx.py` (HTML/CSS → .webm с альфой): статичные
плашки Pillow, что были здесь до 2026-10-08, владелец назвал дешёвыми.

    python productions/augustvpn_main_event/make_assets.py

ПОЧЕМУ СВОЁ. ТЗ запрещает чужие логотипы, а у стоковых звуков и шрифтов своя
лицензия, которую на массовом контенте никто не перечитывает. Графика рисуется
Pillow шрифтом Inter (SIL OFL), звук синтезируется numpy — ни одного файла с
чужими правами.

ПОЧЕМУ «ЭФИР», А НЕ ПЛАШКИ. Ролик снят как прямая PPV-трансляция (студийные
посты камер, `studio/shoot/camera.py`), и графика v0 2026-10-07 — жёлтые
YouTube-плашки — этот приём ломала. Здесь: плашка с логотипом лиги и LIVE,
нижние трети с «таблицей бойца», заставка WIN BY.

QR проверяется декодером (OpenCV), если тот установлен: QR, который не
читается, хуже, чем никакого.
"""

from __future__ import annotations

import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
GFX, SFX = HERE / "gfx", HERE / "sfx"
W, H = 1080, 1920
FONTS = Path("/usr/share/fonts/opentype/inter")
YELLOW, RED, WHITE, INK = (255, 200, 40), (225, 40, 45), (255, 255, 255), (12, 12, 14)
URL = "https://august-vpn.com"
#: Нижние ~400 px вертикального кадра в Reels/TikTok/Shorts закрывает интерфейс
#: площадки (подпись, кнопки), правые ~120 px — колонка лайков. Вся графика
#: и субтитры — выше этой линии (студия: `edit.SUB_Y` — та же граница).
SAFE_BOTTOM = 1500


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"Inter-{weight}.otf"), size)


def canvas() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    return im, ImageDraw.Draw(im)


def save(im: Image.Image, name: str) -> None:
    GFX.mkdir(exist_ok=True)
    im.save(GFX / name)


def check_qr() -> str:
    try:
        import cv2
    except ImportError:
        return "не смогли: нет OpenCV, QR не проверен"
    img = cv2.imread(str(GFX / "packshot.still.png"))  # кадр пэкшота из render_gfx.py
    text, _, _ = cv2.QRCodeDetector().detectAndDecode(img)
    return "годно: QR читается" if text == URL else f"не годно: QR прочитан как {text!r}"


# ------------------------------------------------------------------ звук
SR = 48000


def wav(name: str, x: np.ndarray) -> None:
    SFX.mkdir(exist_ok=True)
    x = np.clip(x / (np.abs(x).max() + 1e-9) * 0.89, -1, 1)
    with wave.open(str(SFX / name), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())


def env(n: int, attack: float, decay: float) -> np.ndarray:
    t = np.arange(n) / SR
    return np.minimum(1, t / max(attack, 1e-4)) * np.exp(-t / decay)


def sfx() -> None:
    rng = np.random.default_rng(7)
    n = int(SR * 1.6)
    t = np.arange(n) / SR
    # удар: суббас с падающей частотой + щелчок
    f = 55 + 90 * np.exp(-t * 18)
    hit = np.sin(2 * np.pi * np.cumsum(f) / SR) * env(n, 0.002, 0.45)
    hit[:400] += rng.normal(0, 0.6, 400) * np.linspace(1, 0, 400)
    wav("hit.wav", hit)
    # свист перед пэкшотом: шум с растущей «высотой» (разность сглаживаний)
    n2 = int(SR * 0.7)
    noise = rng.normal(0, 1, n2)
    out = np.zeros(n2)
    lp = 0.0
    for i in range(n2):
        a = 0.02 + 0.5 * (i / n2) ** 2
        lp += a * (noise[i] - lp)
        out[i] = lp
    wav("whoosh.wav", out * np.sin(np.pi * np.arange(n2) / n2))
    # глитч: рваные пачки цифрового шума и писка
    n3 = int(SR * 0.6)
    g = np.zeros(n3)
    for _ in range(14):
        s0 = int(rng.integers(0, n3 - 2400))
        ln = int(rng.integers(300, 2400))
        tone = np.sign(np.sin(2 * np.pi * rng.uniform(300, 2400) * np.arange(ln) / SR))
        g[s0 : s0 + ln] += tone * rng.uniform(0.3, 1)
    wav("glitch.wav", g)
    # всплывающее окно: короткий «дзынь»
    n4 = int(SR * 0.35)
    t4 = np.arange(n4) / SR
    ding = (np.sin(2 * np.pi * 1320 * t4) + 0.5 * np.sin(2 * np.pi * 1980 * t4)) * env(
        n4, 0.002, 0.08
    )
    wav("popup.wav", ding)
    # отключение: падающий тон «выдернули шнур»
    n5 = int(SR * 0.9)
    t5 = np.arange(n5) / SR
    fdown = 880 * np.exp(-t5 * 4)
    wav("powerdown.wav", np.sin(2 * np.pi * np.cumsum(fdown) / SR) * np.linspace(1, 0, n5) ** 1.5)


def kit_prints() -> None:
    """Спонсор на груди — печать, а не нашивка: знак + надпись одним цветом.

    НАБЛЮДЕНО 2026-10-08, владелец о форме Адгара: «патчи выглядят дёшево и
    нереалистично, ориентируйся на референс формы UFC». На референсе один
    главный спонсор в центре груди — плоская белая печать (знак над словом),
    лига на плече, имя на шортах. Мультяшный шеврон с пунктирной строчкой и
    два десятка разномастных нашивок так не выглядят ни у кого.
    """
    refs = HERE / "refs"
    # FREE VPN: щит-знак и строчное слово, белая печать
    im = Image.new("RGBA", (900, 520), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx = 450
    shield = [(cx - 70, 40), (cx + 70, 40), (cx + 70, 150), (cx, 215), (cx - 70, 150)]
    d.polygon(shield, fill=WHITE + (255,))
    d.polygon(
        [(cx - 44, 66), (cx + 44, 66), (cx + 44, 140), (cx, 182), (cx - 44, 140)], fill=(0, 0, 0, 0)
    )
    d.rectangle((cx - 22, 110, cx + 22, 150), fill=WHITE + (255,))
    d.arc((cx - 18, 82, cx + 18, 122), 180, 360, fill=WHITE + (255,), width=8)
    f = ImageFont.truetype(str(HERE / "fonts" / "Oswald-Variable.ttf"), 190)
    f.set_variation_by_axes([700])
    t = "freevpn"
    d.text(((900 - d.textlength(t, font=f)) / 2, 225), t, font=f, fill=WHITE)
    im.save(refs / "print_freevpn.png")
    # АвгустVPN: жёлтая надпись бренда, без плашки
    im = Image.new("RGBA", (1100, 300), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    f = font("Black", 170)
    t = "АвгустVPN"
    d.text(((1100 - d.textlength(t, font=f)) / 2, 50), t, font=f, fill=YELLOW)
    im.save(refs / "print_august.png")


def main() -> None:
    kit_prints()
    sfx()
    print(check_qr())


if __name__ == "__main__":
    main()
