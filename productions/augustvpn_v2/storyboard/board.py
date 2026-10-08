"""Лист раскадровки v2: ключевой кадр + эфирная графика + подпись (время, сцена, звук)."""

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

SB = Path(__file__).parent
G = Path("/home/user/lipsync-templates/productions/augustvpn_main_event/gfx")
F = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FB = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
W, H = 1080, 1920

PANELS = [
    ("kf/K01.jpg", ["bug_live.still.png"], None, "0:00–0:03", "Арена, свет, пиротехника", "Рёв зала, бас-удар"),
    ("kf/K02.jpg", ["bug_live.still.png"], None, "0:03–0:06", "Анонсер в центре октагона", "«Ladies and gentlemen… MAIN EVENT!»"),
    ("kf/K03.jpg", ["name_august.still.png"], None, "0:06–0:11", "Август в углу, спокоен", "«…standing five feet ten… AUGUST POBEDINSKY!»"),
    ("kf/K04.jpg", ["name_adgar.still.png"], None, "0:11–0:17", "Адгар в углу, бьёт в грудь", "«…six feet nine… ADGAR FRIBETOV!»"),
    ("kf2/K05.jpg", ["tale_of_tape.still.png"], None, "0:17–0:22", "Фейс-офф, взгляд снизу вверх", "«Touch gloves.» «Seventy-three kilos…»"),
    ("kf2/K06.jpg", ["scorebug.still.png"], None, "0:22–0:24", "Гонг, общий с возвышения", "Гонг, рёв"),
    ("kf/K07.jpg", ["scorebug.still.png"], "spinner", "0:24–0:29", "Адгар завис, загрузка, рефери машет", "Модем. «Uhh… is he okay?»"),
    ("kf/K08.jpg", ["scorebug.still.png"], None, "0:29–0:31", "Падает назад доской", "Отключение, удар о мат, «Ооо!»"),
    ("kf/K09.jpg", [], "dino", "0:31–0:34", "Пиксели, динозаврик убегает", "8-бит «бип», смех"),
    ("kf/K10.jpg", ["result.still.png"], None, "0:34–0:36", "WIN BY: DISCONNECT, бровь", "Удар"),
    ("kf/K11.jpg", [], None, "0:36–0:39", "Комментаторы", "«Some fighters work fast. Others work for free.»"),
    (None, ["packshot.still.png"], None, "0:39–0:42", "Пэкшот", "Финальный удар"),
]


def frame(src: str | None) -> Image.Image:
    if src is None:
        return Image.new("RGB", (W, H), "black")
    im = Image.open(SB / src).convert("RGB")
    return im.resize((W, H), Image.LANCZOS)


def spinner(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int = 46) -> None:
    for i in range(12):
        a = 2 * math.pi * i / 12
        x1, y1 = cx + r * 0.55 * math.cos(a), cy + r * 0.55 * math.sin(a)
        x2, y2 = cx + r * math.cos(a), cy + r * math.sin(a)
        c = int(255 * (0.25 + 0.75 * i / 11))
        d.line([(x1, y1), (x2, y2)], fill=(c, c, c), width=9)


def dino(d: ImageDraw.ImageDraw, x: int, y: int, s: int = 10) -> None:
    rows = [
        "........XXXXXX",
        "........XX.XXX",
        "........XXXXXX",
        "........XXXX..",
        "X.......XXXXX.",
        "X.....XXXXX...",
        "XX..XXXXXXXX..",
        "XXXXXXXXXX.X..",
        ".XXXXXXXXX....",
        "..XXXXXXX.....",
        "...XXX.XX.....",
        "...XX...X.....",
    ]
    for j, row in enumerate(rows):
        for i, ch in enumerate(row):
            if ch == "X":
                d.rectangle([x + i * s, y + j * s, x + i * s + s - 1, y + j * s + s - 1], fill=(83, 83, 83))


def panel(src, overlays, mark):
    im = frame(src).convert("RGBA")
    for o in overlays:
        ov = Image.open(G / o).convert("RGBA")
        dy = 1050 if o.startswith("name_") else 0  # плашка имени — в нижнюю треть, не на лицо
        im.alpha_composite(ov, (0, dy)) if dy == 0 else im.alpha_composite(ov.crop((0, 0, W, H - dy)), (0, dy))
    d = ImageDraw.Draw(im)
    if mark == "spinner":
        spinner(d, 860, 700)
    if mark == "dino":
        # Адгар рассыпается на пиксели: мозаика по его телу
        box = (720, 1000, 1080, 1560)
        reg = im.crop(box)
        reg = reg.resize((reg.width // 28, reg.height // 28), Image.NEAREST).resize(reg.size, Image.NEAREST)
        im.paste(reg, box)
        d = ImageDraw.Draw(im)
        # динозаврик бежит по настилу от него к краю клетки, без подложки
        dino(d, 380, 1420, 11)
    return im.convert("RGB")


PW, PH, CAP = 360, 640, 150
cols, rows = 6, 2
sheet = Image.new("RGB", (cols * PW, rows * (PH + CAP)), (18, 18, 18))
d = ImageDraw.Draw(sheet)
fb, ft = ImageFont.truetype(FB, 22), ImageFont.truetype(F, 17)


def wrap(text, font, width):
    words, line, out = text.split(), "", []
    for w in words:
        t = (line + " " + w).strip()
        if d.textlength(t, font=font) <= width:
            line = t
        else:
            out.append(line)
            line = w
    out.append(line)
    return out


for k, (src, ovs, mark, tc, scene, sound) in enumerate(PANELS):
    x, y = (k % cols) * PW, (k // cols) * (PH + CAP)
    sheet.paste(panel(src, ovs, mark).resize((PW, PH), Image.LANCZOS), (x, y))
    d.text((x + 10, y + PH + 8), f"{k + 1}. {tc}", font=fb, fill=(255, 210, 0))
    ty = y + PH + 38
    for ln in wrap(scene, ft, PW - 20)[:2]:
        d.text((x + 10, ty), ln, font=ft, fill=(240, 240, 240))
        ty += 22
    for ln in wrap(sound, ft, PW - 20)[:3]:
        d.text((x + 10, ty), ln, font=ft, fill=(170, 170, 170))
        ty += 22
sheet.save(SB / "storyboard_v2.jpg", quality=90)
print(sheet.size)
