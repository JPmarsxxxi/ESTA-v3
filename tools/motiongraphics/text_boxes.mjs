// Text boxes of built motion-graphics slots, measured in headless Chrome across the slot's timeline.
//   node tools/motiongraphics/text_boxes.mjs <slot index.html> ...   -> JSON {path: [{text, x0, y0, x1, y1, t}]}
// build.py checks them against the caption band (SPEC.md Part 12, F11).
import fs from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";
import { findChrome, loadPuppeteer } from "../opencut/chrome.mjs";

const puppeteer = loadPuppeteer();
const files = process.argv.slice(2);
const chrome = findChrome();
if (!chrome) {
	console.log(JSON.stringify({ ok: false, error: "no Chrome found (set ESTA_CHROME, or run `npx hyperframes browser ensure`)" }));
	process.exit(0);
}
const browser = await puppeteer.launch({ executablePath: chrome, headless: true, args: ["--no-sandbox", "--no-first-run"] });
const out = {};
try {
	for (const f of files) {
		const html = fs.readFileSync(f, "utf8");
		const w = Number(/data-width="(\d+)"/.exec(html)?.[1] || 1080);
		const h = Number(/data-height="(\d+)"/.exec(html)?.[1] || 1920);
		const page = await browser.newPage();
		await page.setViewport({ width: w, height: h });
		await page.goto(pathToFileURL(path.resolve(f)).href, { waitUntil: "load", timeout: 30000 }).catch(() => {});
		out[f] = await page.evaluate(() => {
			const tl = window.__timelines?.main;
			const dur = tl?.duration?.() || 0;
			const boxes = [];
			for (const t of dur ? [0.25, 0.5, 0.75, 1].map((k) => k * dur) : [0]) {
				tl?.seek?.(t, false);
				const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
				for (let n = walker.nextNode(); n; n = walker.nextNode()) {
					const text = n.textContent.trim();
					const el = n.parentElement;
					if (!text || !el || el.closest("script,style")) continue;
					const cs = getComputedStyle(el);
					if (cs.display === "none" || cs.visibility === "hidden") continue;
					let alpha = 1;
					for (let a = el; a; a = a.parentElement) alpha *= Number(getComputedStyle(a).opacity);
					if (alpha < 0.05) continue;
					const range = document.createRange();
					range.selectNodeContents(n);
					const r = range.getBoundingClientRect();
					if (r.width < 1 || r.height < 1) continue;
					boxes.push({ text: text.slice(0, 60), x0: r.left, y0: r.top, x1: r.right, y1: r.bottom, t });
				}
			}
			return boxes;
		});
		await page.close();
	}
} finally {
	await browser.close();
}
console.log(JSON.stringify({ ok: true, boxes: out }));
