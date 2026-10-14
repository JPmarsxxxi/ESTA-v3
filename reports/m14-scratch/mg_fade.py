import json
from pathlib import Path

S = Path("C:/Users/User/ESTA-v3/sessions/fade-the-crowd-2026-10-13")
plan = {s["shot_number"]: s for s in json.loads((S / "plan.json").read_text(encoding="utf-8"))["shots"]}
OUT = S / "assets" / "mg" / "_kit" / "slots"


def bg(c):
    return f"<div class='bg {c}' id='bg'></div>"


def gs(text, top=150, size=96, plate=False):
    if plate:
        text = f"<span style='background:#0A0A12;padding:0 0.25em'>{text}</span>"
    return f"<div class='gs' id='w' style='top:{top}px;font-size:{size}px'>{text}</div>"


def crowd(n, x0, y0, cols, dx=56, dy=100):
    return "".join(f"<div class='fig' style='left:{x0 + (i % cols) * dx}px;top:{y0 + (i // cols) * dy}px'></div>" for i in range(n))


def pills(n, seed=1):
    out = []
    for i in range(n):
        x = (i * 263 + seed * 97) % 940
        y = 120 + (i * 377 + seed * 53) % 1150
        r = (i * 47 + seed * 31) % 180 - 90
        c = ["#FF4F8B", "#3A86FF", "#2BD67B", "#FFD23F", "#8338EC"][i % 5]
        out.append(f"<div class='pill pl' style='left:{x}px;top:{y}px;transform:rotate({r}deg);background:linear-gradient({c} 0 50%,#F4F4F4 50%)'></div>")
    return "".join(out)


def arrow(x, y, color="#FFF", rot=0, idn="ar", size=1.0):
    return (f"<svg id='{idn}' style='position:absolute;left:{x}px;top:{y}px;transform:rotate({rot}deg)' width='{int(200*size)}' height='{int(300*size)}' viewBox='0 0 200 300'>"
            f"<polygon points='100,0 200,120 130,120 130,300 70,300 70,120 0,120' fill='{color}'/></svg>")


C = {}
C[1] = (bg("rings") + "<div class='coin' id='c' style='left:360px;top:440px;opacity:0;font-size:150px'>LONG</div>" + gs("every 5 minutes", plate=True),
        "drift(tl, '#bg', 4); pop(tl, '#c', 0.2); word(tl, '#w', 0.4);")
C[2] = (bg("dark") + crowd(60, 70, 900, 17) + "<div class='coin' id='c' style='left:360px;top:320px;opacity:0'>&#8383;</div>" + gs("% of accounts long", 150),
        "drift(tl, '#bg', 3); pop(tl, '#c', 0.1); tl.to('#c', {y: -60, duration: 1.6, ease: 'sine.out'}, 0.4); word(tl, '#w', 0.3);")
C[3] = (bg("bokeh") + "<div id='cl' style='position:absolute;left:0;top:780px;width:620px;height:600px;background:#0A0A12;clip-path:polygon(0 0,100% 0,100% 100%,0 100%)'></div>"
        + "<div id='cr' style='position:absolute;left:0;top:0'>" + crowd(12, 40, 690, 12, 48) + "</div>" + gs("reliably wrong", 420, 120),
        "drift(tl, '#bg', 3.5); tl.to('#cr', {x: 420, duration: 2.2, ease: 'power1.in'}, 0.1); word(tl, '#w', 0.5);")
C[4] = (bg("bokeh") + "<div id='bk' style='position:absolute;left:190px;top:330px;width:700px;height:860px;background:#0E3B2E;border:14px solid #D4AF37;border-radius:12px;"
        "color:#D4AF37;font:700 84px Georgia;text-align:center;padding-top:250px;opacity:0;box-shadow:16px 18px 0 rgba(0,0,0,.35)'>The<br>Mathematics<br>of Poker</div>",
        "drift(tl, '#bg', 3); pop(tl, '#bk', 0.1);")
C[5] = (bg("bokeh") + "".join(f"<div class='card' id='k{i}' style='left:{150 + i * 160}px;top:520px;transform:rotate({-24 + i * 12}deg)'>{s}</div>"
                              for i, s in enumerate(["A", "K", "Q", "J", "10"])) + gs("EV = p &times; win &minus; cost", 150, 84),
        "drift(tl, '#bg', 2.5); " + " ".join(f"pop(tl, '#k{i}', {0.05 + i * 0.07:.2f});" for i in range(5)) + " word(tl, '#w', 0.35);")
C[6] = (bg("rays") + "<div id='tb' style='position:absolute;left:90px;top:520px;width:900px;height:520px;border-radius:260px;background:#0F6B3A;border:22px solid #5A2E0E;opacity:0'></div>"
        + "".join(f"<div class='fs' style='position:absolute;left:{x}px;top:{y}px;font-size:120px;opacity:0'>&#128031;</div>" for x, y in
                  [(120, 420), (460, 360), (800, 420), (120, 980), (460, 1030), (800, 980)]) + gs("bad players", 150, 110, True),
        "spin(tl, '#bg', 5, 20); pop(tl, '#tb', 0.05); tl.to('.fs', {opacity: 1, duration: 0.15, stagger: 0.12}, 0.4); word(tl, '#w', 0.9);")
C[7] = ("<div class='bg' id='bg' style='background:repeating-linear-gradient(45deg,#000 0 6px,#140A26 6px 60px),radial-gradient(#FFE14F,#000 40%)'></div>"
        + "".join(f"<div class='ch' style='position:absolute;left:390px;top:{820 - i * 44}px;width:300px;height:60px;border-radius:50%;background:{['#C8102E','#F4F4F4','#2B59FF'][i % 3]};"
                  f"border:6px dashed #fff;opacity:0'></div>" for i in range(8)) + gs("all in, against them", 150, 96),
        "drift(tl, '#bg', 2.5); tl.to('.ch', {opacity: 1, duration: 0.08, stagger: 0.06}, 0.05); tl.to('.ch', {x: 260, duration: 0.5, ease: 'power3.in'}, 1.0); word(tl, '#w', 0.4);")
C[8] = (bg("blob") + "<svg style='position:absolute;left:90px;top:300px' width='900' height='700'><polyline id='ln' points='0,640 150,560 300,520 450,400 600,330 750,220 900,90' "
        "fill='none' stroke='#0A0A12' stroke-width='18' stroke-linecap='round' stroke-dasharray='1400' stroke-dashoffset='1400'/></svg>"
        + "<div class='gs' style='top:1040px;font-size:70px;color:#0A0A12;opacity:1'>2020 &rarr; 2023</div>" + gs("it worked everywhere", 150, 96, True),
        "drift(tl, '#bg', 3.5); tl.to('#ln', {strokeDashoffset: 0, duration: 1.4, ease: 'power2.out'}, 0.1); word(tl, '#w', 0.9);")
C[9] = ("<div class='bg' id='bg' style='background:linear-gradient(#1A1040,#3B1E70)'></div>" + pills(14, 2)
        + "".join(arrow(110 + (i % 4) * 230, 360 + (i // 4) * 300, "#45F55B", 180, f"a{i}", 0.6) for i in range(8)) + gs("same sign", 150, 120),
        "floatUp(tl, '.pl', 3, 120); " + " ".join(f"pop(tl, '#a{i}', {0.05 + i * 0.08:.2f});" for i in range(8)) + " word(tl, '#w', 0.6);")
C[10] = ("<div class='bg' id='bg' style='background:linear-gradient(#1A1040,#3B1E70)'></div>" + pills(30, 5)
         + "<div class='pill' id='real' style='left:470px;top:560px;width:150px;height:380px;background:linear-gradient(#45F55B 0 50%,#F4F4F4 50%);opacity:0'></div>"
         + gs("30 shuffled fakes. 0 beat it.", 150, 84) + "<div class='gs' id='p' style='top:270px;font-size:72px'>p = 0.032</div>",
         "floatUp(tl, '.pl', 5, 220); tl.to('.pl', {opacity: 0.35, duration: 1.0, ease: 'power2.out'}, 1.6); pop(tl, '#real', 1.4); word(tl, '#w', 0.3); word(tl, '#p', 2.2);")
C[11] = ("<div class='bg' id='bg' style='background:linear-gradient(#1A1040,#3B1E70)'></div>" + pills(14, 9)
         + "<div id='dr' style='position:absolute;left:340px;top:380px;width:400px;height:700px;background:#0A0A12;border:16px solid #FFD23F;transform-origin:left;"
         "color:#FFD23F;font:700 110px Georgia;text-align:center;padding-top:260px'>2023</div>" + gs("the validation year", 150, 100),
         "floatUp(tl, '.pl', 2.5, 100); tl.fromTo('#dr', {scaleX: 0}, {scaleX: 1, duration: 0.4, ease: 'power3.out'}, 0.1); word(tl, '#w', 0.4);")
C[12] = (bg("bubbles") + arrow(240, 380, "#45F55B", 180, "up", 1.0) + arrow(640, 380, "#FF3D7F", 0, "dn", 1.0)
         + "<div style='position:absolute;left:538px;top:330px;width:6px;height:420px;background:#FFF'></div>" + gs("it flipped", 150, 130),
         "drift(tl, '#bg', 3); pop(tl, '#up', 0.05); tl.fromTo('#dn', {opacity: 0, rotation: 180}, {opacity: 1, rotation: 0, duration: 0.5, ease: 'back.out(1.6)'}, 0.9); word(tl, '#w', 1.0);")
C[13] = (bg("bubbles") + "<div class='num' id='a' style='left:40px;top:540px;font-size:130px;color:#FF3D7F'>&minus;0.087</div><div class='num' id='b' style='left:580px;top:540px;font-size:130px;color:#45F55B'>+0.089</div>"
         + "<div style='position:absolute;left:538px;top:430px;width:6px;height:420px;background:#FFF'></div>" + gs("same size, opposite sign", 150, 90),
         "drift(tl, '#bg', 2.5); pop(tl, '#a', 0.05); pop(tl, '#b', 0.35); word(tl, '#w', 0.5);")
C[19] = (bg("grid") + "".join(f"<div class='tile' style='position:absolute;left:{170 + (i % 4) * 190}px;top:{260 + (i // 4) * 190}px;width:160px;height:160px;border-radius:24px;"
                              f"background:linear-gradient(135deg,#FF2BD6,#22D3EE);box-shadow:0 0 0 6px #FFF'></div>" for i in range(12))
         + gs("forgetting only pays<br>when something changes", 150, 84),
         "drift(tl, '#bg', 5); tl.to('.tile', {opacity: 0, y: 180, scale: 0.4, duration: 0.6, stagger: 0.12, ease: 'power2.in'}, 0.8); word(tl, '#w', 0.3);")
C[20] = (bg("purple") + "<div id='hd' style='position:absolute;left:330px;top:300px;width:420px;height:300px;border-radius:200px 200px 80px 80px;background:linear-gradient(#FFE58A,#D4A017);opacity:0'></div>"
         + "".join(f"<div class='card' id='k{i}' style='left:{40 + i * 205}px;top:620px'>{s}</div>" for i, s in enumerate(["&#9824;", "&#9829;", "&#9830;", "&#9827;", "A"]))
         + gs("the odds", 150, 120),
         "drift(tl, '#bg', 2.5); pop(tl, '#hd', 0.05); " + " ".join(f"pop(tl, '#k{i}', {0.15 + i * 0.08:.2f});" for i in range(5)) + " word(tl, '#w', 0.4);")
C[21] = (bg("purple") + "".join(f"<div class='card' style='left:{40 + i * 205}px;top:620px;opacity:1'>?</div>" for i in range(5))
         + "<div id='fog' style='position:absolute;inset:0;background:radial-gradient(ellipse at 50% 55%,rgba(255,255,255,.95),rgba(220,210,255,.6) 50%,transparent 75%);opacity:0'></div>"
         + gs("guess them", 150, 120),
         "drift(tl, '#bg', 2.5); tl.to('#fog', {opacity: 1, duration: 1.0, ease: 'power2.out'}, 0.2); word(tl, '#w', 0.4);")
C[22] = (bg("purple") + "<div class='card' id='k1' style='left:300px;top:520px;transform:rotate(-10deg);background:repeating-linear-gradient(45deg,#C8102E 0 14px,#8E0A20 14px 28px)'></div>"
         "<div class='card' id='k2' style='left:470px;top:500px;transform:rotate(8deg);background:repeating-linear-gradient(45deg,#C8102E 0 14px,#8E0A20 14px 28px)'></div>"
         + gs("not folding yet", 150, 120),
         "drift(tl, '#bg', 4); pop(tl, '#k1', 0.1); pop(tl, '#k2', 0.25); word(tl, '#w', 0.6);")

OUT.mkdir(parents=True, exist_ok=True)
for k, (body, timeline) in C.items():
    assert plan[k]["visual"]["type"] == "MOTION_GRAPHICS", k
    d = round(plan[k]["end"] - plan[k]["start"], 3)
    (OUT / f"{k}.json").write_text(json.dumps({"key": str(k), "flavor": "full_frame", "duration": d, "body": body, "timeline": timeline}), encoding="utf-8")
print(len(C), "slots; missing:", [n for n, s in plan.items() if s["visual"]["type"] == "MOTION_GRAPHICS" and n not in C])
