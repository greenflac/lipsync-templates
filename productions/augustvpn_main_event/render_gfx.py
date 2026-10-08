#!/usr/bin/env python3
"""Эфирный графический пакет: HTML/CSS → кадры в Chromium → .webm (VP9) с альфой.

    python productions/augustvpn_main_event/render_gfx.py [имя …]

РАСКЛАДКА ПО ВЕРТИКАЛИ (ревью 2026-10-08): верхние ~180 px и нижние ~480 px
кадра в Reels/TikTok/Shorts закрывает интерфейс; титры имени и итога — в
верхней трети, чтобы не закрывать печать спонсора на груди бойца (иначе бренд
на экране ≈4,5 с из 43). Адрес и QR пэкшота — выше 75 % высоты.

ПОЧЕМУ ТАК. НАБЛЮДЕНО 2026-10-08, владелец о графике v1 (статичные PNG из
Pillow): «плашки бойцов, LIVE и пр. выглядят дёшево». Дороговизну эфирной
графике дают движение (шторки, сдвиги, блик по панели), материал (тёмное
стекло, металлическое золото, свечение цвета угла) и типографика (узкий
эфирный шрифт с разрядкой). Pillow не даёт ни того, ни другого, а HTML/CSS даёт
всё, и Chromium с Playwright уже стоит в окружении.

КАДРЫ ДЕТЕРМИНИРОВАНЫ. У каждого элемента своя функция `render(t)`, которая
выставляет состояние на момент t. CSS-анимации не используются: снимок
«в момент t» тогда зависит от скорости машины.

До развязки в графике нет ни слова о VPN: владелец, 2026-10-08, — «до
последнего момента всё выглядит как реальный бой».
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "gfx"
FPS = 24
W, H = 1080, 1920
#: Секунда табло, на которой часы встают: длительность S06+S07+S08 в монтаже.
FROZEN_CLOCK_AT = 7.6

CSS = """
@font-face { font-family: Osw; src: url('fonts/Oswald-Variable.ttf'); font-weight: 200 700; }
@font-face { font-family: Fira; src: url('fonts/FiraSansExtraCondensed-SemiBold.ttf'); font-weight: 600; }
@font-face { font-family: Fira; src: url('fonts/FiraSansExtraCondensed-Bold.ttf'); font-weight: 700; }
@font-face { font-family: Fira; src: url('fonts/FiraSansExtraCondensed-ExtraBold.ttf'); font-weight: 800; }
@font-face { font-family: Fira; src: url('fonts/FiraSansExtraCondensed-Black.ttf'); font-weight: 900; }
:root { --red:#d8262f; --red2:#7a0d13; --blue:#1d6fe6; --blue2:#0b2f6b; --gold1:#fff4cc; --gold2:#e9b84a; --gold3:#9c6b16; }
html,body { margin:0; width:1080px; height:1920px; background:transparent; overflow:hidden; }
* { box-sizing:border-box; }
.glass { position:absolute; background:linear-gradient(180deg, rgba(26,27,32,.94), rgba(7,7,9,.94));
  border:1px solid rgba(255,255,255,.09); box-shadow: 0 18px 50px rgba(0,0,0,.55), inset 0 1px 0 rgba(255,255,255,.12);
  overflow:hidden; }
.sweep { position:absolute; top:-20%; width:30%; height:140%; transform:skewX(-20deg);
  background:linear-gradient(90deg, transparent, rgba(255,255,255,.22), transparent); }
.osw { font-family:Osw; text-transform:uppercase; letter-spacing:.04em; }
.fira { font-family:Fira; }
.gold { background:linear-gradient(180deg,var(--gold1) 0%,var(--gold2) 46%,var(--gold3) 54%,#f3d07a 100%);
  -webkit-background-clip:text; background-clip:text; color:transparent; }
.white { color:#fff; }
.dim { color:rgba(255,255,255,.62); }
"""

JS_LIB = """
const clamp=(x)=>Math.max(0,Math.min(1,x));
const ease=(x)=>1-Math.pow(1-clamp(x),4);            // быстрый вход, мягкая посадка
const easeIn=(x)=>Math.pow(clamp(x),3);
const prog=(t,a,d)=>ease((t-a)/d);
const $=(id)=>document.getElementById(id);
function life(t, inAt, outAt, d){ return Math.min(prog(t,inAt,d), 1-easeIn((t-outAt)/d)); }
"""

ELEMENTS: dict[str, tuple[float, str, str]] = {}


def element(name: str, seconds: float, html: str, js: str) -> None:
    ELEMENTS[name] = (seconds, html, js)


# ---------------------------------------------------------------- плашка эфира до боя
element(
    "bug_live",
    3.0,
    """
<div id=bug class=glass style="left:40px;top:190px;width:470px;height:92px;border-radius:6px">
  <div style="position:absolute;left:0;top:0;width:8px;height:100%;background:linear-gradient(180deg,var(--gold1),var(--gold3))"></div>
  <div class="osw gold" style="position:absolute;left:28px;top:10px;font-size:40px;font-weight:700">Security Arena</div>
  <div class="osw dim" style="position:absolute;left:30px;top:56px;font-size:20px;font-weight:500;letter-spacing:.18em">Main event · PPV</div>
  <div id=sw class=sweep></div>
</div>
<div id=live class=glass style="left:526px;top:190px;width:124px;height:92px;border-radius:6px;background:linear-gradient(180deg,#e2313a,#8c0f16)">
  <div id=dot style="position:absolute;left:20px;top:36px;width:20px;height:20px;border-radius:50%;background:#fff"></div>
  <div class="osw white" style="position:absolute;left:50px;top:22px;font-size:36px;font-weight:700">Live</div>
</div>""",
    """
function render(t){
  const p=prog(t,0,0.6);
  $('bug').style.clipPath=`inset(0 ${100-100*p}% 0 0)`;
  $('live').style.opacity=prog(t,0.35,0.4); $('live').style.transform=`translateX(${(1-prog(t,0.35,0.5))*-30}px)`;
  $('sw').style.left=(-40+170*clamp((t-0.5)/0.9))+'%';
  $('dot').style.opacity=0.35+0.65*(0.5+0.5*Math.cos(t*Math.PI*2));
}""",
)

# ---------------------------------------------------------------- таблица бойцов (хук)
element(
    "tale_of_tape",
    3.2,
    """
<div id=panel class=glass style="left:60px;top:960px;width:960px;height:430px;border-radius:8px">
  <div id=hdr class="osw gold" style="position:absolute;left:0;width:100%;top:18px;text-align:center;font-size:30px;font-weight:600;letter-spacing:.3em">Tale of the tape</div>
  <div style="position:absolute;left:0;top:70px;width:100%;height:2px;background:linear-gradient(90deg,var(--blue),transparent 45%,transparent 55%,var(--red))"></div>
  <div id=nl class="osw white" style="position:absolute;left:34px;top:88px;font-size:56px;font-weight:700">Pobedinsky</div>
  <div id=nr class="osw white" style="position:absolute;right:34px;top:88px;font-size:56px;font-weight:700;text-align:right">Fribetov</div>
  <div class=rowv id=r1 style="position:absolute;left:0;top:176px;width:100%;height:70px">
    <div class="osw white" style="position:absolute;left:34px;font-size:52px;font-weight:600">178 cm</div>
    <div class="osw dim" style="position:absolute;left:0;width:100%;text-align:center;top:14px;font-size:26px;letter-spacing:.25em">Height</div>
    <div class="osw white" style="position:absolute;right:34px;font-size:52px;font-weight:600">205 cm</div></div>
  <div class=rowv id=r2 style="position:absolute;left:0;top:250px;width:100%;height:70px">
    <div class="osw white" style="position:absolute;left:34px;font-size:52px;font-weight:600">77 kg</div>
    <div class="osw dim" style="position:absolute;left:0;width:100%;text-align:center;top:14px;font-size:26px;letter-spacing:.25em">Weight</div>
    <div class="osw white" style="position:absolute;right:34px;font-size:52px;font-weight:600">150 kg</div></div>
  <div id=diff style="position:absolute;left:250px;top:338px;width:460px;height:64px;border-radius:4px;background:linear-gradient(90deg,var(--red2),var(--red));box-shadow:0 0 40px rgba(216,38,47,.55)">
    <div class="osw white" style="position:absolute;width:100%;text-align:center;top:6px;font-size:40px;font-weight:700;letter-spacing:.08em">+73 kg difference</div></div>
  <div style="position:absolute;left:0;top:0;width:10px;height:100%;background:linear-gradient(180deg,#5ea0ff,var(--blue2))"></div>
  <div style="position:absolute;right:0;top:0;width:10px;height:100%;background:linear-gradient(180deg,#ff6a70,var(--red2))"></div>
  <div id=sw class=sweep></div>
</div>""",
    """
function render(t){
  const T=3.2, o=life(t,0,T-0.35,0.35);
  $('panel').style.opacity=o;
  $('panel').style.clipPath=`inset(${50-50*prog(t,0,0.45)}% 0 ${50-50*prog(t,0,0.45)}% 0)`;
  $('nl').style.transform=`translateX(${-60*(1-prog(t,0.2,0.5))}px)`; $('nl').style.opacity=prog(t,0.2,0.4);
  $('nr').style.transform=`translateX(${60*(1-prog(t,0.2,0.5))}px)`; $('nr').style.opacity=prog(t,0.2,0.4);
  $('r1').style.opacity=prog(t,0.45,0.35); $('r2').style.opacity=prog(t,0.6,0.35);
  const d=prog(t,0.85,0.35); $('diff').style.opacity=d; $('diff').style.transform=`scale(${0.85+0.15*d})`;
  $('sw').style.left=(-40+170*clamp((t-0.9)/0.8))+'%';
}""",
)


# ---------------------------------------------------------------- титры выхода бойцов
def name_super(key: str, first: str, last: str, record: str, corner: str, c1: str, c2: str) -> None:
    element(
        key,
        2.3,
        f"""
<div id=bar style="position:absolute;left:0;top:310px;width:820px;height:12px;background:linear-gradient(90deg,{c1},{c2});box-shadow:0 0 36px {c1}"></div>
<div id=panel class=glass style="left:0;top:322px;width:820px;height:220px;border-radius:0 0 8px 0">
  <div id=f class="osw dim" style="position:absolute;left:54px;top:14px;font-size:38px;font-weight:500;letter-spacing:.12em">{first}</div>
  <div id=l class="osw white" style="position:absolute;left:50px;top:52px;font-size:112px;line-height:1;font-weight:700">{last}</div>
  <div id=s class="osw" style="position:absolute;left:54px;top:174px;font-size:28px;font-weight:600;letter-spacing:.16em;color:{c1}">{corner} &nbsp;·&nbsp; <span class=white>{record}</span></div>
  <div id=sw class=sweep></div>
</div>""",
        """
function render(t){
  const o=life(t,0,1.95,0.35);
  $('bar').style.transform=`scaleX(${prog(t,0,0.4)})`; $('bar').style.transformOrigin='left';
  $('bar').style.opacity=o; $('panel').style.opacity=o;
  $('panel').style.clipPath=`inset(0 ${100-100*prog(t,0.08,0.45)}% 0 0)`;
  $('l').style.transform=`translateX(${-40*(1-prog(t,0.2,0.5))}px)`;
  $('f').style.opacity=prog(t,0.3,0.3); $('s').style.opacity=prog(t,0.45,0.3);
  $('sw').style.left=(-40+170*clamp((t-0.5)/0.8))+'%';
}""",
    )


name_super("name_adgar", "Adgar", "Fribetov", "18-0-0", "Red corner", "#ff5059", "#7a0d13")
name_super("name_august", "August", "Pobedinsky", "21-1-0", "Blue corner", "#4f95ff", "#0b2f6b")

# ---------------------------------------------------------------- табло боя с идущими часами
element(
    "scorebug",
    20.0,
    """
<div id=sb class=glass style="left:40px;top:190px;height:84px;border-radius:6px;display:flex;align-items:center">
  <div style="width:8px;align-self:stretch;background:var(--blue)"></div>
  <div class="osw white" style="padding:0 16px 0 20px;font-size:44px;font-weight:700">Pobedinsky</div>
  <div class="osw dim" style="font-size:26px;font-weight:500">vs</div>
  <div class="osw white" style="padding:0 20px 0 16px;font-size:44px;font-weight:700">Fribetov</div>
  <div style="width:8px;align-self:stretch;background:var(--red)"></div>
  <div style="align-self:stretch;display:flex;align-items:center;background:rgba(255,255,255,.06);padding:0 24px">
    <div class="osw gold" style="font-size:44px;font-weight:700;margin-right:22px">R1</div>
    <div id=clk class="osw white" style="font-size:44px;font-weight:600;font-variant-numeric:tabular-nums">5:00</div></div>
</div>""",
    """
function render(t){
  $('sb').style.clipPath=`inset(0 ${100-100*prog(t,0,0.5)}% 0 0)`;
  const s=Math.max(0,300-Math.floor(t*2.2));            // бой «идёт», монтаж его сжимает
  $('clk').textContent=Math.floor(s/60)+':'+String(s%60).padStart(2,'0');
}""",
)

# ---------------------------------------------------------------- развязка: итог боя
element(
    "result",
    3.4,
    """
<div id=panel class=glass style="left:60px;top:300px;width:960px;height:300px;border-radius:8px">
  <div style="position:absolute;left:0;top:0;width:100%;height:10px;background:linear-gradient(90deg,var(--gold3),var(--gold1),var(--gold3))"></div>
  <div id=a class="osw dim" style="position:absolute;width:100%;text-align:center;top:30px;font-size:32px;font-weight:600;letter-spacing:.3em">Official result · R1</div>
  <div id=b class="osw white" style="position:absolute;width:100%;text-align:center;top:76px;font-size:64px;font-weight:700">Pobedinsky wins</div>
  <div id=c class="osw" style="position:absolute;width:100%;text-align:center;top:160px;font-size:96px;font-weight:700;color:#ff3b45;text-shadow:0 0 34px rgba(255,59,69,.6)">by disconnect</div>
  <div id=sw class=sweep></div>
</div>""",
    """
function render(t){
  const o=life(t,0,3.05,0.35);
  $('panel').style.opacity=o; $('panel').style.clipPath=`inset(0 0 ${100-100*prog(t,0,0.45)}% 0)`;
  $('a').style.opacity=prog(t,0.2,0.3); $('b').style.opacity=prog(t,0.35,0.3);
  const c=prog(t,0.8,0.25); $('c').style.opacity=c;
  $('c').style.transform=`translateX(${(t>0.8&&t<1.3)?(Math.sin(t*90)*8*(1-c)):0}px)`;   // дрожь «сбоя»
  $('sw').style.left=(-40+170*clamp((t-0.4)/0.8))+'%';
}""",
)

# ---------------------------------------------------------------- пэкшот
element(
    "packshot",
    6.0,
    """
<div style="position:absolute;inset:0;background:radial-gradient(ellipse at 50% 34%, #2a2414 0%, #0b0b0d 58%)"></div>
<div id=glow style="position:absolute;left:190px;top:250px;width:700px;height:420px;border-radius:50%;background:rgba(255,200,40,.22);filter:blur(90px)"></div>
<div id=tag class="fira white" style="position:absolute;width:100%;text-align:center;top:250px;font-size:52px;font-weight:700;opacity:.9">Не отключается<br>в главном бою.</div>
<div id=logo class="fira" style="position:absolute;width:100%;text-align:center;top:420px;font-size:150px;font-weight:900;color:#ffc828;text-shadow:0 0 60px rgba(255,200,40,.45)">АвгустVPN</div>
<div id=w1 class="osw white" style="position:absolute;width:100%;text-align:center;top:620px;font-size:76px;font-weight:700">Быстрее.</div>
<div id=w2 class="osw white" style="position:absolute;width:100%;text-align:center;top:710px;font-size:76px;font-weight:700">Надёжнее.</div>
<div id=w3 class="osw white" style="position:absolute;width:100%;text-align:center;top:800px;font-size:76px;font-weight:700">Безопаснее.</div>
<div id=cta style="position:absolute;left:150px;top:940px;width:780px;height:116px;border-radius:58px;background:linear-gradient(180deg,#ffd75a,#f2b10f);box-shadow:0 12px 40px rgba(242,177,15,.45)">
  <div class="fira" style="position:absolute;width:100%;text-align:center;top:26px;font-size:50px;font-weight:800;color:#141414">Попробовать 1 день за 10 ₽</div></div>
<img id=qr src="gfx/qr.png" style="position:absolute;left:395px;top:1090px;width:290px;height:290px;border-radius:12px">
<div id=url class="fira white" style="position:absolute;width:100%;text-align:center;top:1390px;font-size:44px;font-weight:600;opacity:.9">august-vpn.com</div>""",
    """
function render(t){
  $('tag').style.opacity=0.82*prog(t,0.0,0.4);
  const l=prog(t,0.35,0.6); $('logo').style.opacity=l; $('logo').style.transform=`scale(${1.12-0.12*l})`;
  $('glow').style.opacity=l;
  ['w1','w2','w3'].forEach((id,i)=>{const p=prog(t,0.9+i*0.28,0.35); $(id).style.opacity=p; $(id).style.transform=`translateY(${30*(1-p)}px)`;});
  const c=prog(t,1.9,0.4); $('cta').style.opacity=c; $('cta').style.transform=`scale(${0.92+0.08*c})`;
  $('qr').style.opacity=prog(t,2.2,0.4); $('url').style.opacity=0.9*prog(t,2.35,0.4);
}""",
)

# ---------------------------------------------------------------- водяной знак
element(
    "watermark",
    0.0,  # статичный кадр
    """
<div class="osw" style="position:absolute;left:-200px;top:820px;width:1480px;text-align:center;transform:rotate(-28deg);
  font-size:190px;font-weight:700;letter-spacing:.06em;color:rgba(255,255,255,.075);
  -webkit-text-stroke:2px rgba(255,255,255,.10)">@greenflac</div>""",
    "function render(t){}",
)


def page(name: str) -> str:
    _, html, js = ELEMENTS[name]
    return f"<!doctype html><html><head><meta charset=utf-8><style>{CSS}</style></head><body>{html}<script>{JS_LIB}{js}</script></body></html>"


def qr_png() -> None:
    import qrcode

    q = qrcode.QRCode(border=2, box_size=12, error_correction=qrcode.constants.ERROR_CORRECT_M)
    q.add_data("https://august-vpn.com")
    q.make(fit=True)
    q.make_image(fill_color="black", back_color="white").save(OUT / "qr.png")


def render(names: list[str]) -> None:
    from playwright.sync_api import sync_playwright

    OUT.mkdir(exist_ok=True)
    qr_png()
    with sync_playwright() as pw, tempfile.TemporaryDirectory() as tmp:
        # в облачном окружении Chromium предустановлен, а версия pip-пакета
        # Playwright может ждать другую сборку — берём явный путь, если он есть
        exe = Path("/opt/pw-browsers/chromium")
        browser = pw.chromium.launch(executable_path=str(exe) if exe.exists() else None)
        pg = browser.new_page(viewport={"width": W, "height": H})
        for name in names:
            seconds = ELEMENTS[name][0]
            src = HERE / f".{name}.html"
            src.write_text(page(name), encoding="utf-8")
            pg.goto(src.as_uri())
            pg.evaluate("document.fonts.ready")
            if seconds <= 0:
                pg.evaluate("render(0)")
                pg.screenshot(path=str(OUT / f"{name}.png"), omit_background=True)
            else:
                frames = Path(tmp) / name
                frames.mkdir()
                for i in range(round(seconds * FPS)):
                    pg.evaluate(f"render({i / FPS})")
                    pg.screenshot(path=str(frames / f"f{i:04d}.png"), omit_background=True)
                subprocess.run(
                    [
                        "ffmpeg",
                        "-v",
                        "error",
                        "-y",
                        "-framerate",
                        str(FPS),
                        "-i",
                        str(frames / "f%04d.png"),
                    ]
                    # VP9 с альфой: 0,2–2 МБ на элемент против 10–57 МБ у qtrle,
                    # поэтому пакет живёт в git рядом с монтажным листом
                    + ["-c:v", "libvpx-vp9", "-pix_fmt", "yuva420p", "-b:v", "0", "-crf", "24"]
                    + ["-row-mt", "1", "-deadline", "good", "-cpu-used", "4"]
                    + [str(OUT / f"{name}.webm")],
                    check=True,
                )
                # кадр-образец для просмотра и для тестов: середина анимации
                pg.evaluate(f"render({seconds * 0.6})")
                pg.screenshot(path=str(OUT / f"{name}.still.png"), omit_background=True)
                if name == "scorebug":
                    # часы табло «зависают» вместе с Адгаром (ревью 2026-10-08):
                    # стоп-кадр табло на моменте, где обрывается пакет боя
                    pg.evaluate(f"render({FROZEN_CLOCK_AT})")
                    pg.screenshot(path=str(OUT / "scorebug_frozen.png"), omit_background=True)
            src.unlink()
            print(name, "готово")
        browser.close()


if __name__ == "__main__":
    render(sys.argv[1:] or list(ELEMENTS))
