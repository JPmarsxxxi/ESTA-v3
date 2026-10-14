import json
from pathlib import Path

S = Path("C:/Users/User/ESTA-v3/sessions/the-label-was-the-defect-2026-10-13")
plan = {s["shot_number"]: s for s in json.loads((S / "plan.json").read_text(encoding="utf-8"))["shots"]}
OUT = S / "assets" / "mg" / "_kit" / "slots"


def f(c):
    return f"<div class='f {c}'></div>"


def t(text, cls, x, y, idn="w", style=""):
    return f"<div class='t {cls}' id='{idn}' style='left:{x}px;top:{y}px;opacity:0;{style}'>{text}</div>"


dots = "".join(f"<div class='ball dt' style='left:{180 + (i * 137) % 1560}px;top:{120 + (i * 61) % 300}px;width:18px;height:18px;background:#6CC490'></div>" for i in range(40))
C = {}
C[1] = (f("beige") + t("0", "xl", 160, 330, "n") + t("models", "m", 900, 470, "w"),
        "countUp(tl, '#n', 111, 0, 0.05, 0.9); slideIn(tl, '#w', 0.6);")
C[2] = (f("lav") + "<div id='ln' style='position:absolute;left:180px;top:560px;width:420px;height:14px;background:#0E0E0E;transform:rotate(-20deg);opacity:0'></div>"
        + "<svg id='tr' style='position:absolute;left:760px;top:300px;opacity:0' width='360' height='480' viewBox='0 0 360 480'><polygon points='180,0 330,180 30,180' fill='#2F9E5B'/>"
          "<polygon points='180,120 360,330 0,330' fill='#2F9E5B'/><rect x='155' y='330' width='50' height='150' fill='#6B4423'/></svg>"
        + "".join(f"<div class='ball sc' style='left:{1320 + (i * 83) % 360}px;top:{340 + (i * 131) % 380}px;width:44px;height:44px;background:#3B4BF5;opacity:0'></div>" for i in range(14))
        + t("lines, forests, everything", "s", 180, 880),
        "popIn(tl, '#ln', 0.05); popIn(tl, '#tr', 0.5); tl.to('.sc', {opacity: 1, duration: 0.05, stagger: 0.04}, 1.0); slideIn(tl, '#w', 1.4);")
C[3] = (f("black") + "<div style='position:absolute;left:160px;top:700px;width:1600px;height:6px;background:#FFF'></div>"
        + "".join(f"<div class='t s' style='left:{160 + i * 320 - 40}px;top:740px;color:#FFF'>{0.5 + i * 0.1:.1f}0</div>" for i in range(6))
        + "<div id='band' style='position:absolute;left:{0}px;top:200px;width:{1}px;height:500px;background:#6CC490;opacity:0'></div>".format(160 + int(0.03 / 0.5 * 1600), int(0.05 / 0.5 * 1600))
        + "".join(f"<div class='ball dp' style='left:{160 + int((0.53 + (i % 10) * 0.005) / 1 * 0 + (0.03 + (i % 10) * 0.005) / 0.5 * 1600)}px;top:{-60 - (i % 7) * 40}px;width:16px;height:16px;background:#FFF'></div>" for i in range(60))
        + t("AUC 0.53 \u2013 0.58", "m", 760, 840),
        "popIn(tl, '#band', 0.1); tl.to('.dp', {y: 640, duration: 0.9, ease: 'power2.in', stagger: 0.02}, 0.2); slideIn(tl, '#w', 1.8);")
C[4] = (f("yellow") + t("0.58", "xl", 480, 360), "popIn(tl, '#w', 0.02);")
C[5] = (f("beige") + "<div id='cap' style='position:absolute;left:300px;top:260px;width:1320px;height:12px;background:#E4322B;transform-origin:left;transform:scaleX(0)'></div>"
        + "<div id='b' style='position:absolute;left:820px;top:272px;width:280px;height:560px;background:#0E0E0E;transform-origin:bottom;transform:scaleY(0)'></div>",
        "rule(tl, '#cap', 0.0); tl.to('#b', {scaleY: 1, duration: 0.35, ease: 'power4.out'}, 0.2); tl.to('#b', {scaleY: 0.97, duration: 0.12, yoyo: true, repeat: 1}, 0.55);")
C[6] = (f("beige") + "<div style='position:absolute;left:300px;top:260px;width:1320px;height:12px;background:#E4322B'></div>"
        + "<div style='position:absolute;left:820px;top:272px;width:280px;height:560px;background:#0E0E0E'></div>" + t("fine.", "l", 1180, 560),
        "drawOn(tl, '#w', 0.1, 0.07); tl.set('#w', {opacity: 1}, 0.1);")
C[8] = (f("black") + t("the wrong", "l", 220, 420), "slideIn(tl, '#w', 0.02);")
C[9] = (f("black") + t("question<span style='color:#E4322B'>?</span>", "l", 220, 420), "popIn(tl, '#w', 0.02);")
C[13] = (f("dots") + t("200 bp", "l", 520, 380) + "<div class='ball' id='mk' style='left:430px;top:450px;width:60px;height:60px;background:#E4322B;opacity:0'></div>",
         "popIn(tl, '#mk', 0.05); popIn(tl, '#w', 0.15);")
C[15] = (f("black") + t("12 hours", "l", 200, 430)
         + "<svg style='position:absolute;left:1240px;top:240px' width='520' height='520'><path id='ar' d='M40,480 L480,40 M300,40 L480,40 L480,220' fill='none' stroke='#3B4BF5' stroke-width='44' "
           "stroke-linecap='square' stroke-dasharray='1100' stroke-dashoffset='1100'/></svg>",
         "drawOn(tl, '#w', 0.02, 0.05); tl.set('#w', {opacity: 1}, 0.02); tl.to('#ar', {strokeDashoffset: 0, duration: 0.5, ease: 'power3.out'}, 0.3);")
C[16] = (f("green") + t("the question", "l", 200, 430), "slideIn(tl, '#w', 0.02);")
C[17] = (f("red") + t("that pays is\u2026", "l", 200, 430), "slideIn(tl, '#w', 0.02, -400);")
C[19] = (f("black") + "".join(f"<div class='bar rb' style='left:{260 + i * 180}px;height:{200 + (i % 4) * 110}px;width:120px;background:repeating-linear-gradient(#3B4BF5 0 18px,#1E2A9C 18px 26px)'></div>" for i in range(8))
         + t("would it clear the cost?", "s", 260, 860, "w", "color:#FFF"),
         "grow(tl, '.rb', 0.02, 0.35); slideIn(tl, '#w', 0.5);")
C[21] = (f("grey") + "<div class='ball' id='b1' style='left:150px;top:120px;width:520px;height:420px;background:#6CC490;opacity:0;border-radius:48% 52% 60% 40%'></div>"
         "<div class='ball' id='b2' style='left:1350px;top:560px;width:420px;height:380px;background:#3B4BF5;opacity:0;border-radius:60% 40% 45% 55%'></div>"
         "<div class='ball' id='b3' style='left:1250px;top:100px;width:260px;height:260px;background:#F2A3C7;opacity:0'></div>"
         + t("~10 bp", "xl", 560, 380),
         "popIn(tl, '#b1', 0.05); popIn(tl, '#b2', 0.15); popIn(tl, '#b3', 0.25); popIn(tl, '#w', 0.4);")
C[22] = (f("grey") + t("did it move 1 vol?", "m", 200, 300, "a") + "<div class='rule' id='x' style='left:190px;top:360px;width:1180px;color:#E4322B'></div>"
         + t("did it clear the cost?", "m", 200, 560, "b", "color:#2F9E5B"),
         "slideIn(tl, '#a', 0.02); rule(tl, '#x', 0.4); tl.set('#b', {opacity: 1}, 0.7); drawOn(tl, '#b', 0.7, 0.03);")
C[23] = ("<div class='f' style='background:#EEF0F6'></div>" + "<div class='glass' id='g0' style='left:620px;top:160px;width:720px;height:720px;opacity:0'></div>"
         + "".join(f"<div class='glass gs' style='left:{x}px;top:{y}px;width:{w}px;height:{w}px;opacity:0'></div>" for x, y, w in [(180, 160, 220), (360, 640, 160), (1450, 120, 200), (1500, 700, 240)])
         + t("profit &gt; cost", "m", 690, 470),
         "popIn(tl, '#g0', 0.02); tl.to('.gs', {opacity: 1, duration: 0.2, stagger: 0.08}, 0.2); popIn(tl, '#w', 0.35);")
C[24] = (f("pastel") + t("long is good", "l", 260, 430), "popIn(tl, '#w', 0.02);")
C[28] = (f("beige") + "<div class='bar' id='p48' style='left:620px;height:576px;background:#2F9E5B'></div><div class='bar' id='p27' style='left:1080px;height:324px;background:#9E9A93'></div>"
         + t("48%", "m", 610, 120, "a") + t("27%", "m", 1070, 380, "b"),
         "grow(tl, '#p48', 0.02, 0.3); grow(tl, '#p27', 0.08, 0.3); popIn(tl, '#a', 0.2); popIn(tl, '#b', 0.25);")
C[29] = (f("blue") + "<svg id='tp' style='position:absolute;left:220px;top:250px;opacity:0' width='380' height='520' viewBox='0 0 380 520'>"
         "<path d='M60,20 H320 V140 C320,260 250,320 190,320 C130,320 60,260 60,140 Z M150,320 H230 V420 H150 Z M90,420 H290 V480 H90 Z' fill='#F5C518'/></svg>"
         + t("edge / trade", "l", 700, 430),
         "popIn(tl, '#tp', 0.02); slideIn(tl, '#w', 0.15);")
C[30] = ("<div class='f' style='background:#D9CCF5'></div><div class='ball' id='c' style='left:760px;top:340px;width:400px;height:400px;background:#5B2EA6;opacity:0'></div>"
         "<svg id='a' style='position:absolute;left:860px;top:400px;opacity:0' width='200' height='280'><polygon points='100,0 200,120 130,120 130,280 70,280 70,120 0,120' fill='#FFF'/></svg>",
         "popIn(tl, '#c', 0.0); popIn(tl, '#a', 0.08);")
C[34] = (f("black") + t("\u00d73", "xl", 560, 300, "x", "font-size:420px;color:#2EC4B6") + t("tripled", "m", 1180, 560, "w", "color:#FF8A3D"),
         "slideIn(tl, '#x', 0.05, -600); slideIn(tl, '#w', 0.9);")
C[37] = (f("navy") + "".join(f"<div class='glass' style='left:{x}px;top:{y}px;width:{w}px;height:{w}px'></div>" for x, y, w in [(200, 200, 160), (1500, 160, 220), (1350, 700, 140), (380, 760, 120)])
         + t("right.", "l", 640, 420), "popIn(tl, '#w', 0.02);")
C[38] = (f("blue") + t("50%", "l", 260, 420, "a") + t("56%", "l", 1060, 420, "b"),
         "drawOn(tl, '#a', 0.02, 0.06); tl.set('#a', {opacity: 1}, 0.02); drawOn(tl, '#b', 0.75, 0.06); tl.set('#b', {opacity: 1}, 0.75);")
C[39] = ("<div class='f' style='background:#F6F1E7'></div>"
         + "".join(f"<div class='ball cc' style='left:{x}px;top:{y}px;width:{w}px;height:{w}px;background:{c};mix-blend-mode:multiply;opacity:0'></div>"
                   for x, y, w, c in [(420, 160, 620, "#F5C518"), (820, 260, 560, "#3B4BF5"), (640, 420, 480, "#E4322B")])
         + t("61%", "xl", 640, 380, "w", "color:#0E0E0E"),
         "tl.to('.cc', {opacity: 1, duration: 0.15, stagger: 0.08}, 0.02); popIn(tl, '#w', 0.3);")
C[41] = ("<div class='f' style='background:#D8D8D4'></div>" + t("closer", "xl", 300, 360, "w", "color:#2F9E5B"),
         "tl.set('#w', {opacity: 1}, 0.05); drawOn(tl, '#w', 0.05, 0.08);")
C[42] = ("<div class='f' style='background:#1A1A1A'></div><div style='position:absolute;left:260px;top:440px;width:1400px;height:180px;border-radius:40px;background:#2A2A2A;border:6px solid #444'></div>"
         "<div id='fill' style='position:absolute;left:275px;top:455px;width:1148px;height:150px;border-radius:30px;background:#E4FF3A;transform-origin:left;transform:scaleX(0)'></div>"
         "<div style='position:absolute;left:1520px;top:400px;width:10px;height:260px;background:#FFF'></div>"
         + t("0.82", "s", 1180, 300, "a", "color:#E4FF3A") + t("0.90", "s", 1480, 680, "b", "color:#FFF"),
         "tl.to('#fill', {scaleX: 1, duration: 0.35, ease: 'power3.out'}, 0.0); popIn(tl, '#a', 0.2); popIn(tl, '#b', 0.1);")
C[43] = (f("beige") + t("same data.", "m", 220, 260, "a") + t("same models.", "m", 220, 420, "b") + t("different question.", "m", 220, 580, "c", "color:#3B4BF5"),
         "slideIn(tl, '#a', 0.05); slideIn(tl, '#b', 0.7); slideIn(tl, '#c', 1.5);")

OUT.mkdir(parents=True, exist_ok=True)
for k, (body, timeline) in C.items():
    assert plan[k]["visual"]["type"] == "MOTION_GRAPHICS", k
    d = round(plan[k]["end"] - plan[k]["start"], 3)
    (OUT / f"{k}.json").write_text(json.dumps({"key": str(k), "flavor": "full_frame", "duration": d, "body": body, "timeline": timeline}), encoding="utf-8")
print(len(C), "slots; missing:", [n for n, s in plan.items() if s["visual"]["type"] == "MOTION_GRAPHICS" and n not in C])
