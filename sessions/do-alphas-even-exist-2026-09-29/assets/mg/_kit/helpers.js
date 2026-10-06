// Words land one at a time, in spoken order: a short rise, power3.out (motion-design M5).
function land(tl, sel, at) {
  tl.fromTo(sel, { opacity: 0, y: 10 }, { opacity: 1, y: 0, duration: 0.14, ease: "power3.out" }, at);
}
function words(tl, sels, times) {
  sels.forEach((s, i) => land(tl, s, times[i]));
}
// A path draws on with its dash offset; the dot rides to its end.
function drawPath(tl, sel, at, dur) {
  const p = document.querySelector(sel);
  const len = p.getTotalLength();
  p.style.strokeDasharray = len;
  p.style.strokeDashoffset = len;
  tl.to(p, { strokeDashoffset: 0, duration: dur, ease: "power2.out" }, at);
}
// A column slides in from the right, the inspo's slides_in reveal.
function slideIn(tl, sel, at) {
  tl.fromTo(sel, { opacity: 0, x: 120 }, { opacity: 1, x: 0, duration: 0.35, ease: "power3.out" }, at);
}
// A number counts up to its value: the inspo's cards land words, so this is for the one stat a card is about.
function countUp(tl, sel, target, decimals, at, dur, prefix, suffix) {
  const el = document.querySelector(sel), o = { v: 0 };
  tl.set(el, { opacity: 1 }, at);
  tl.to(o, { v: target, duration: dur, ease: "power2.out",
             onUpdate: () => { el.textContent = (prefix || "") + o.v.toFixed(decimals) + (suffix || ""); } }, at);
}
// Bars grow from the baseline one after another (negative bars hang below it).
function growBars(tl, sel, at, stagger) {
  tl.to(sel, { scaleY: 1, duration: 0.35, ease: "power3.out", stagger: stagger }, at);
}
