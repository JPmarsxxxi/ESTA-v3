import json
from pathlib import Path

S = Path("C:/Users/User/ESTA-v3/sessions/five-ways-backtest-lies-2026-10-13")
plan = {s["shot_number"]: s for s in json.loads((S / "plan.json").read_text(encoding="utf-8"))["shots"]}
OUT = S / "assets" / "mg" / "_kit" / "slots"


def bg(c):
    return f"<div class='{c}' style='position:absolute;inset:0'></div>"


def tag(text):
    return f"<div class='tag' id='tag'>{text}</div>"


HEAD = ("<svg class='cut' id='head' style='left:180px;top:200px' width='720' height='840' viewBox='0 0 600 700'>"
        "<path fill='#0E0E0E' d='M300,60 C450,60 540,170 540,300 C540,360 570,390 600,450 L560,470 C570,520 560,560 520,570 "
        "L520,640 L300,700 L180,700 L190,560 C110,500 80,420 80,320 C80,170 170,60 300,60 Z'/></svg>")
BEAR = ("<svg class='cut' id='bear' style='left:140px;top:380px' width='800' height='520' viewBox='0 0 400 260'>"
        "<g fill='#3A2A20'><ellipse cx='190' cy='150' rx='140' ry='80'/><circle cx='330' cy='110' r='52'/>"
        "<circle cx='310' cy='62' r='16'/><circle cx='352' cy='66' r='16'/><rect x='80' y='190' width='34' height='66' rx='10'/>"
        "<rect x='140' y='196' width='34' height='60' rx='10'/><rect x='230' y='196' width='34' height='60' rx='10'/>"
        "<rect x='280' y='190' width='34' height='66' rx='10'/><ellipse cx='372' cy='122' rx='22' ry='14'/></g></svg>")


def person(x, y, s=1.0, c="#8E8B86"):
    return (f"<svg style='position:absolute;left:{x}px;top:{y}px' width='{int(110*s)}' height='{int(200*s)}' viewBox='0 0 110 200'>"
            f"<circle cx='55' cy='30' r='26' fill='{c}'/><rect x='18' y='62' width='74' height='120' rx='30' fill='{c}'/>"
            "<rect x='30' y='86' width='50' height='62' fill='#FFF'/></svg>")


def tomb(x, y, txt="?", s=1.0):
    return (f"<div class='cut tb' style='left:{x}px;top:{y}px;width:{int(130*s)}px;height:{int(170*s)}px;background:#9C9891;"
            f"border-radius:{int(65*s)}px {int(65*s)}px 6px 6px;color:#111;font:700 {int(70*s)}px Georgia;text-align:center;"
            f"padding-top:{int(30*s)}px;opacity:0'>{txt}</div>")


def clock(x, y, r, hh=300, mm=0, idn="ck"):
    return (f"<svg class='cut' id='{idn}' style='left:{x}px;top:{y}px' width='{2*r}' height='{2*r}' viewBox='-100 -100 200 200'>"
            "<circle r='96' fill='#F7F3EA' stroke='#111' stroke-width='8'/>"
            + "".join(f"<rect x='-3' y='-90' width='6' height='16' fill='#111' transform='rotate({i*30})'/>" for i in range(12))
            + f"<rect x='-5' y='-55' width='10' height='60' fill='#111' transform='rotate({hh})'/>"
            f"<rect x='-3' y='-80' width='6' height='85' fill='#C8102E' transform='rotate({mm})'/><circle r='8' fill='#111'/></svg>")


C = {}
C[1] = (bg("red") +
        "<svg class='cut' id='ch' style='left:120px;top:300px' width='840' height='600' viewBox='0 0 840 600'>"
        "<rect width='840' height='600' fill='#F7F3EA'/><polyline id='ln' points='40,540 180,470 300,500 420,360 560,300 700,140' "
        "fill='none' stroke='#111' stroke-width='12'/><polygon id='nose' points='700,128 700,152 700,140' fill='#C8102E'/></svg>"
        + tag("5 ways to make your backtest <b>LIE</b> to you"),
        "slideIn(tl, '#ch', 0.05); tl.to('#nose', {attr: {points: '700,118 700,162 830,140'}, duration: 0.6, ease: 'power3.out'}, 0.5); tagIn(tl, '#tag', 0.3);")
C[2] = (bg("cream") +
        "<div class='cut paper mono' id='r1' style='left:250px;top:240px;width:290px;height:720px;padding:40px 24px;font-size:34px;line-height:1.7'>"
        "SPREAD .....0.29<br>SWAP ........0.34<br>SLIPPAGE ...0.10<br>---------<br>COMMISSION</div>"
        "<div class='cut paper mono' id='r2' style='left:540px;top:240px;width:290px;height:720px;padding:40px 24px;font-size:34px;line-height:1.7'>"
        "<br><br><br><br>6.50 bp</div>" + tag("1. Forget the commission."),
        "slideIn(tl, '#r1', 0.05); slideIn(tl, '#r2', 0.12, 260); tagIn(tl, '#tag', 0.2); tl.to('#r1', {rotation: -8, x: -40, duration: 0.5, ease: 'power3.out'}, 1.0); tl.to('#r2', {rotation: 7, x: 40, duration: 0.5, ease: 'power3.out'}, 1.0);")
C[3] = (bg("black") +
        "<div class='cut paper' id='p' style='left:150px;top:320px;width:780px;height:640px;padding:60px;font-size:64px;line-height:1.6;transform:rotate(-3deg)'>"
        "<div class='it' style='opacity:0'>&#10003; spread</div><div class='it' style='opacity:0'>&#10003; swap</div><div class='it' style='opacity:0'>&#10003; slippage</div>"
        "<div class='it' style='opacity:0;color:#C8102E'>&#9744; the invoice</div></div>",
        "slideIn(tl, '#p', 0.0); tl.to('.it', {opacity: 1, duration: 0.12, stagger: 0.14}, 0.25);")
C[7] = (bg("red") +
        "<div class='cut' id='pie' style='left:190px;top:260px;width:700px;height:700px;border-radius:50%;"
        "background:conic-gradient(#0E0E0E 0 94%, #F7F3EA 94% 100%)'></div>"
        "<div class='cut paper' id='l' style='left:120px;top:1000px;padding:16px 30px;font:700 64px Georgia'>COMMISSION 94%</div>",
        "popIn(tl, '#pie', 0.05); slideIn(tl, '#l', 0.4);")
C[8] = (bg("cream") +
        "<div class='cut' id='aw' style='left:140px;top:300px;width:800px;height:170px;background:repeating-linear-gradient(90deg,#C8102E 0 100px,#F7F3EA 100px 200px)'></div>"
        "<div class='cut paper mono' id='st' style='left:200px;top:470px;width:680px;height:420px;padding:50px;font-size:46px;line-height:1.6'>"
        "S&amp;P 500 DATA<br>OPEN ... 330.22<br>CLOSE .. 330.22<br>FRESH! CHEAP!</div>" + tag("2. Trust the vendor."),
        "slideIn(tl, '#aw', 0.05, 0); slideIn(tl, '#st', 0.15); tagIn(tl, '#tag', 0.3);")
B = ["1990 open = 1989 close", "1996 open = prev close", "2003 open = prev close", "2011 open = prev close"]
C[11] = (bg("black") + "".join(f"<div class='bub' id='b{i}' style='top:{300+i*190}px'>\u201c{t}\u201d</div>" for i, t in enumerate(B)),
         "".join(f"slideIn(tl, '#b{i}', {0.1+i*0.25:.2f});" for i in range(4)))
C[12] = (bg("black") + "".join(f"<div class='bub' style='top:{300+i*190}px;opacity:1' id='c{i}'>\u201c{t}\u201d</div>" for i, t in enumerate(B))
         + "<div class='big' id='yr' style='left:90px;top:1120px;color:#FFF;font-size:150px;opacity:0'>1990\u20132014</div>"
         "<div class='x' id='x' style='left:80px;top:1195px;width:900px'></div>",
         "tl.to('.bub', {opacity: 0.12, duration: 0.5, stagger: 0.08, ease: 'power2.out'}, 0.2); popIn(tl, '#yr', 0.4); strike(tl, '#x', 1.0);")
C[13] = (bg("red") + clock(240, 260, 300, 300, 0) + tag("3. Trust the clock."),
         "popIn(tl, '#ck', 0.05); tagIn(tl, '#tag', 0.2); tl.to('#ck rect:last-of-type', {rotation: 90, transformOrigin: '50% 100%', duration: 1.2, ease: 'power2.inOut'}, 0.3);")
C[14] = (bg("red") + "<div id='eye' style='position:absolute;left:290px;top:300px;width:500px;height:500px;border-radius:50%;background:#0E0E0E'></div>",
         "popIn(tl, '#eye', 0.02);")
C[15] = (bg("red") + "<div class='cut paper' id='sb' style='left:120px;top:360px;padding:40px 60px;border-radius:60px;font:700 80px Georgia'>server time<br>= Athens</div>",
         "popIn(tl, '#sb', 0.05);")
C[16] = (bg("cream") +
         "<div class='cut' id='col' style='left:160px;top:330px;width:200px;height:800px;background:repeating-linear-gradient(90deg,#D8D0C0 0 26px,#B9AF9C 26px 34px)'></div>"
         + clock(420, 360, 250, 330, 0, "ck2") + "<div class='lbl' id='t' style='left:420px;top:900px;font:700 90px Georgia;opacity:0'>ATHENS<br>TIME</div>",
         "slideIn(tl, '#col', 0.0); popIn(tl, '#ck2', 0.1); popIn(tl, '#t', 0.25);")
C[17] = (bg("space") + clock(90, 380, 220, 330, 0, "a") + clock(590, 380, 220, 300, 0, "b")
         + "<div class='lbl' style='left:150px;top:860px;color:#FFF'>Athens</div><div class='lbl' style='left:660px;top:860px;color:#FFF'>the broker</div>"
         "<div class='big' id='d' style='left:330px;top:1000px;color:#C8102E;font-size:170px;opacity:0'>\u221260</div>",
         "popIn(tl, '#a', 0.05); popIn(tl, '#b', 0.2); tl.to('#b rect:nth-last-of-type(2)', {rotation: -30, transformOrigin: '50% 100%', duration: 0.6, ease: 'power3.out'}, 0.8); popIn(tl, '#d', 1.2);")
C[18] = (bg("space") +
         "<div class='cut' id='m' style='left:140px;top:420px;width:800px;height:340px;border-radius:170px;background:#111;padding:26px'>"
         "<div style='width:100%;height:100%;border-radius:150px;background:linear-gradient(#AFC4D6,#5E7D99);color:#111;font:700 110px Georgia;text-align:center;padding-top:80px'>"
         "<span id='mt' style='opacity:0'>1 hour ago</span></div></div>"
         "<div class='lbl' id='c' style='left:140px;top:860px;color:#FFF;font-size:64px;opacity:0'>an hour of hindsight</div>",
         "slideIn(tl, '#m', 0.05, 300); tl.to('#mt', {opacity: 1, duration: 0.3}, 0.5); tagIn(tl, '#c', 1.0);")
grid = "".join(f"<div style='border:3px solid #111;height:110px'>{('2022-%02d' % (r+1)) if c == 0 else ''}</div>" for r in range(6) for c in range(4))
C[19] = (bg("cream") + f"<div class='cut paper mono' id='g' style='left:110px;top:260px;width:860px;display:grid;grid-template-columns:repeat(4,1fr);font-size:34px'>{grid}</div>"
         "<div id='hl' style='position:absolute;left:110px;top:260px;width:860px;height:110px;background:rgba(200,16,46,0.35);opacity:0'></div>"
         + tag("4. Check the rows, not the columns."),
         "slideIn(tl, '#g', 0.05); tagIn(tl, '#tag', 0.2); tl.to('#hl', {opacity: 1, duration: 0.2}, 0.8); tl.to('#hl', {y: 550, duration: 1.2, ease: 'power2.inOut'}, 1.0);")
files = "".join(f"<div class='fl' style='position:absolute;left:{560 + (i % 2) * 18}px;top:{900 - i * 70}px;width:300px;height:56px;background:#F7F3EA;border:4px solid #111;opacity:0'></div>" for i in range(10))
C[20] = (bg("cream") + HEAD + files, "slideIn(tl, '#head', 0.0); tl.to('.fl', {opacity: 1, duration: 0.1, stagger: 0.09}, 0.2);")
C[21] = (bg("cream") + HEAD + files.replace("opacity:0", "opacity:1")
         + "<div class='stamp' id='s' style='left:180px;top:520px;font-size:110px'>288 / 288</div>",
         "stampIn(tl, '#s', 0.25);")
crowd = "".join(person(90 + (i % 6) * 150, 230 + (i // 6) * 230, 1.0) for i in range(24))
C[22] = (bg("cream") + f"<div id='cr' style='position:absolute;inset:0;opacity:0'>{crowd}</div>"
         "<div class='cut paper mono' id='n' style='left:200px;top:1180px;padding:16px 30px;font-size:52px'>top_trader = \u2205</div>",
         "tl.to('#cr', {opacity: 1, duration: 0.3, ease: 'power2.out'}, 0.05); popIn(tl, '#n', 0.6);")
C[23] = (bg("grey") + BEAR + "<div class='big' id='p' style='left:120px;top:960px;color:#C8102E;opacity:0'>87%</div>"
         "<div class='cut' id='er' style='left:140px;top:560px;width:120px;height:200px;background:#C8102E;border-radius:14px'></div>",
         "slideIn(tl, '#bear', 0.0); wipe(tl, '#bear', 0.5, 1.6); tl.fromTo('#er', {x: 0}, {x: 660, duration: 1.6, ease: 'power2.inOut'}, 0.5); popIn(tl, '#p', 0.6);")
pan = [("2020", "#F7F3EA"), ("2021", "#F7F3EA"), ("2022", "#BDBAB4"), ("2023", "#F7F3EA")]
C[24] = (bg("black") + "".join(f"<div class='cut pn' style='left:{90 + (i % 2) * 470}px;top:{260 + (i // 2) * 470}px;width:430px;height:430px;background:{c};"
                               f"font:700 80px Georgia;padding:30px;opacity:0'>{y}</div>" for i, (y, c) in enumerate(pan))
         + "<div class='stamp' id='s' style='left:120px;top:850px;font-size:90px'>BLANK</div>",
         "tl.to('.pn', {opacity: 1, duration: 0.15, stagger: 0.1}, 0.05); stampIn(tl, '#s', 0.7);")
C[25] = (bg("black") + tomb(330, 330, "RIP", 3.2) + tag("5. Kill ideas early."),
         "tl.to('.tb', {opacity: 1, duration: 0.01}, 0); popIn(tl, '.tb', 0.05); tagIn(tl, '#tag', 0.25);")
C[26] = (bg("white") + "<div class='stamp' id='k' style='left:160px;top:420px'>KILLED</div>"
         "<div class='stamp' id='r' style='left:120px;top:700px;transform:rotate(8deg);border-color:#111;color:#111'>REVERSED</div>",
         "stampIn(tl, '#k', 0.1); stampIn(tl, '#r', 1.0);")
C[27] = (bg("white") + "".join(tomb(90 + (i % 3) * 320, 300 + (i // 3) * 420, "?", 1.6) for i in range(6)),
         "tl.to('.tb', {opacity: 1, duration: 0.15, stagger: 0.12}, 0.1);")
SL = ("<svg style='position:absolute;left:0;top:0' width='1080' height='1400'><polygon points='0,1300 1080,500 1080,1400 0,1400' fill='#111'/></svg>")
BALL = "<div class='cut' id='ball' style='left:{x}px;top:{y}px;width:300px;height:300px;border-radius:50%;background:repeating-radial-gradient(circle at 40% 40%,#C8102E 0 10px,#9E0B22 10px 14px)'></div>"
C[28] = (bg("white") + SL + BALL.format(x=560, y=500) + "<div class='tag' id='tag' style='top:180px'>Part 2</div>",
         "popIn(tl, '#ball', 0.05); tl.to('#ball', {x: 60, y: -40, rotation: 40, duration: 1.4, ease: 'power2.out'}, 0.2); tagIn(tl, '#tag', 0.3);")
C[29] = (bg("white") + SL + BALL.format(x=620, y=460),
         "tl.to('#ball', {x: -600, y: 480, rotation: -300, duration: 0.45, ease: 'power2.in'}, 0.0);")

OUT.mkdir(parents=True, exist_ok=True)
for k, (body, timeline) in C.items():
    d = round(plan[k]["end"] - plan[k]["start"], 3)
    assert plan[k]["visual"]["type"] == "MOTION_GRAPHICS", k
    (OUT / f"{k}.json").write_text(json.dumps({"key": str(k), "flavor": "full_frame", "duration": d, "body": body, "timeline": timeline}), encoding="utf-8")
missing = [n for n, s in plan.items() if s["visual"]["type"] == "MOTION_GRAPHICS" and n not in C]
print(len(C), "slots; MG shots without a config:", missing)
