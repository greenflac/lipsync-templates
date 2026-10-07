#!/usr/bin/env python3
"""Эфирная графика и звуковые эффекты ролика — генерируются, а не скачиваются.

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

import math
import wave
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

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


def bug() -> None:
    """Плашка трансляции: лига + LIVE слева сверху, MAIN EVENT справа."""
    im, d = canvas()
    d.rounded_rectangle((40, 70, 420, 150), 10, fill=(10, 10, 12, 215))
    d.text((62, 84), "SECURITY ARENA", font=font("Black", 30), fill=WHITE)
    d.text((62, 118), "ГЛАВНЫЙ БОЙ ВЕЧЕРА", font=font("SemiBold", 20), fill=(200, 200, 200))
    d.rounded_rectangle((440, 88, 560, 132), 8, fill=RED + (235,))
    d.ellipse((456, 102, 472, 118), fill=WHITE)
    d.text((482, 94), "LIVE", font=font("Black", 26), fill=WHITE)
    save(im, "bug_live.png")


def lower_third(name: str, file: str, brand: str, who: str, stats: str, color: tuple[int, ...]) -> None:
    im, d = canvas()
    y = 1080
    assert y + 190 < SAFE_BOTTOM
    d.rectangle((0, y, W, y + 190), fill=(10, 10, 12, 225))
    d.rectangle((0, y, 18, y + 190), fill=color + (255,))
    d.text((52, y + 20), brand, font=font("Black", 64), fill=color)
    d.text((52, y + 100), who, font=font("Bold", 36), fill=WHITE)
    d.text((52, y + 146), stats, font=font("Medium", 26), fill=(190, 190, 190))
    save(im, file)


def buffering() -> None:
    im, d = canvas()
    cx, cy, r = W // 2, H // 2 - 80, 70
    for i in range(12):
        a = 2 * math.pi * i / 12
        alpha = int(60 + 195 * i / 11)
        x, y = cx + r * math.cos(a), cy + r * math.sin(a)
        d.ellipse((x - 13, y - 13, x + 13, y + 13), fill=(255, 255, 255, alpha))
    t = "Буферизация… 3%"
    f = font("SemiBold", 40)
    d.text((cx - d.textlength(t, font=f) / 2, cy + 110), t, font=f, fill=WHITE)
    save(im, "buffering.png")


def connection_lost() -> None:
    im, d = canvas()
    d.rectangle((0, 0, W, H), fill=(0, 0, 0, 120))
    rng = np.random.default_rng(3)
    for _ in range(26):  # полосы «развалившегося» сигнала
        y = int(rng.integers(0, H))
        hgt = int(rng.integers(4, 26))
        col = [(255, 0, 80, 110), (0, 220, 255, 110), (255, 255, 255, 70)][int(rng.integers(0, 3))]
        d.rectangle((0, y, W, y + hgt), fill=col)
    f1, f2 = font("Black", 92), font("SemiBold", 40)
    for txt, f, y, col in (
        ("CONNECTION", f1, 780, RED),
        ("LOST", f1, 880, RED),
        ("Соединение потеряно", f2, 1010, WHITE),
    ):
        d.text(((W - d.textlength(txt, font=f)) / 2, y), txt, font=f, fill=col)
    save(im, "connection_lost.png")


def popups() -> None:
    """Всплывающая реклама поверх бойца: безобидный спам, без азартных игр и 18+."""
    ads = [
        ("ВНИМАНИЕ!", "Ваш телефон заражён\n47 вирусами", "ОЧИСТИТЬ", (40, 120, 255), (90, 250)),
        ("ПОЗДРАВЛЯЕМ!", "Вы миллионный\nпосетитель", "ЗАБРАТЬ", (240, 150, 0), (380, 450)),
        ("УСКОРИТЕЛЬ", "Интернет в 100 раз\nбыстрее! Скачать?", "ДА", (30, 170, 80), (110, 660)),
        ("РЕКЛАМА", "Этот боец спонсируется\nвашими данными", "OK", (200, 30, 160), (340, 880)),
    ]
    for k in range(1, len(ads) + 1):
        im, d = canvas()
        for title, body, btn, col, (x, y) in ads[:k]:
            box = (x, y, x + 640, y + 330)
            shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            ImageDraw.Draw(shadow).rectangle((x + 14, y + 18, x + 654, y + 348), fill=(0, 0, 0, 120))
            im.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(10)))
            d.rectangle(box, fill=(245, 245, 245, 255), outline=(60, 60, 60, 255), width=3)
            d.rectangle((x, y, x + 640, y + 70), fill=col + (255,))
            d.text((x + 24, y + 14), title, font=font("Black", 36), fill=WHITE)
            d.text((x + 590, y + 10), "×", font=font("Bold", 44), fill=WHITE)
            d.multiline_text((x + 24, y + 96), body, font=font("SemiBold", 34), fill=INK, spacing=8)
            d.rounded_rectangle((x + 24, y + 250, x + 260, y + 310), 8, fill=col + (255,))
            d.text((x + 44, y + 262), btn, font=font("Black", 30), fill=WHITE)
        save(im, f"popups_{k}.png")


def win_card() -> None:
    im, d = canvas()
    d.rectangle((0, 1080, W, 1340), fill=(10, 10, 12, 230))
    d.rectangle((0, 1080, W, 1092), fill=YELLOW + (255,))
    f1, f2 = font("SemiBold", 34), font("Black", 88)
    for txt, f, y, col in (("ПОБЕДА · WIN BY", f1, 1120, (200, 200, 200)), ("DISCONNECT", f2, 1175, YELLOW)):
        d.text(((W - d.textlength(txt, font=f)) / 2, y), txt, font=f, fill=col)
    save(im, "win_disconnect.png")


def qr_image(size: int) -> Image.Image:
    import qrcode

    q = qrcode.QRCode(border=2, box_size=10, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data(URL)
    q.make(fit=True)
    img = q.make_image(fill_color="black", back_color="white").convert("RGB")
    return img.resize((size, size), Image.Resampling.NEAREST)


def packshot() -> None:
    im = Image.new("RGBA", (W, H), INK + (255,))
    d = ImageDraw.Draw(im)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(glow).ellipse((140, 260, 940, 900), fill=YELLOW + (70,))
    im.alpha_composite(glow.filter(ImageFilter.GaussianBlur(120)))
    f_logo = font("Black", 128)
    t = "АвгустVPN"
    d.text(((W - d.textlength(t, font=f_logo)) / 2, 470), t, font=f_logo, fill=YELLOW)
    f3 = font("Bold", 62)
    for i, word in enumerate(("Быстрее.", "Надёжнее.", "Безопаснее.")):
        d.text(((W - d.textlength(word, font=f3)) / 2, 680 + i * 84), word, font=f3, fill=WHITE)
    d.rounded_rectangle((150, 1000, 930, 1120), 24, fill=YELLOW + (255,))
    cta = "Попробовать 1 день за 10 ₽"
    f4 = font("Black", 46)
    d.text(((W - d.textlength(cta, font=f4)) / 2, 1032), cta, font=f4, fill=INK)
    q = qr_image(340)
    im.paste(q, ((W - 340) // 2, 1190))
    f5 = font("SemiBold", 36)
    d.text(((W - d.textlength("august-vpn.com", font=f5)) / 2, 1560), "august-vpn.com", font=f5, fill=WHITE)
    save(im, "packshot.png")


def watermark() -> None:
    im, d = canvas()
    f = font("SemiBold", 26)
    d.text((W - 40 - d.textlength("@greenflac", font=f), 100), "@greenflac", font=f, fill=(255, 255, 255, 120))
    save(im, "watermark.png")


def check_qr() -> str:
    try:
        import cv2
    except ImportError:
        return "не смогли: нет OpenCV, QR не проверен"
    img = cv2.imread(str(GFX / "packshot.png"))
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
    ding = (np.sin(2 * np.pi * 1320 * t4) + 0.5 * np.sin(2 * np.pi * 1980 * t4)) * env(n4, 0.002, 0.08)
    wav("popup.wav", ding)
    # отключение: падающий тон «выдернули шнур»
    n5 = int(SR * 0.9)
    t5 = np.arange(n5) / SR
    fdown = 880 * np.exp(-t5 * 4)
    wav("powerdown.wav", np.sin(2 * np.pi * np.cumsum(fdown) / SR) * np.linspace(1, 0, n5) ** 1.5)


def main() -> None:
    bug()
    lower_third(
        "adgar", "lower_adgar.png", "FREE VPN", "Адгар «Бесплатный» Фрибетов",
        "150 кг · скорость: не измерялась · реклама: включена", RED,
    )
    lower_third(
        "august", "lower_august.png", "АвгустVPN", "Август Побединский",
        "77 кг · быстрее · надёжнее · безопаснее", YELLOW,
    )
    buffering()
    connection_lost()
    popups()
    win_card()
    packshot()
    watermark()
    sfx()
    print(check_qr())


if __name__ == "__main__":
    main()
