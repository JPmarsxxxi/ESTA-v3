// Build for export (originals) + Export for one session, in a headless Chrome with its own profile.
//   node D:/esta-perf/m14t/export.mjs <session-id>
// The user's Chrome window is minimized overnight, and Chrome defers media loading in hidden tabs, so the build
// stalls there; a headless page counts as visible.
import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";
import http from "node:http";

const require = createRequire("C:/Users/User/ESTA-v3/node_modules/.bun/puppeteer-core@24.43.1/node_modules/puppeteer-core/package.json");
const puppeteer = require("puppeteer-core");
const sid = process.argv[2];
const outDir = path.resolve("D:/esta-perf/m14t/exports", sid);
fs.mkdirSync(outDir, { recursive: true });
const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// Chrome's own download of the blob stalled at .crdownload once; the page posts the file here instead.
const server = http.createServer((req, res) => {
	res.setHeader("Access-Control-Allow-Origin", "*");
	res.setHeader("Access-Control-Allow-Methods", "POST, OPTIONS");
	res.setHeader("Access-Control-Allow-Headers", "*");
	res.setHeader("Access-Control-Allow-Private-Network", "true");
	if (req.method !== "POST") { res.end(); return; }
	const name = (new URL(req.url, "http://x").searchParams.get("name") || "export.mp4").replace(/[<>:"/\\|?*]/g, "-");
	const chunks = [];
	req.on("data", (c) => chunks.push(c));
	req.on("end", () => {
		const tmp = path.join(outDir, name + ".part");
		fs.writeFileSync(tmp, Buffer.concat(chunks));
		fs.renameSync(tmp, path.join(outDir, name));
		res.end("ok");
	});
}).listen(8796, "127.0.0.1");

const browser = await puppeteer.launch({
	executablePath: "C:/Program Files/Google/Chrome/Application/chrome.exe",
	headless: true,
	userDataDir: "D:/esta-perf/m14t/chrome-profile",
	defaultViewport: { width: 1600, height: 950 },
	args: ["--autoplay-policy=no-user-gesture-required", "--window-size=1600,950", "--no-first-run", "--enable-unsafe-webgpu", "--use-angle=d3d11", "--enable-gpu", "--ignore-gpu-blocklist", ...(process.env.SWDEC ? ["--disable-accelerated-video-decode"] : [])],
	protocolTimeout: 600000,
});
const page = await browser.newPage();
page.on("console", (m) => { const t = m.text(); if (/error|fail|export/i.test(t)) log("console:", t.slice(0, 200)); });
page.on("pageerror", (e) => log("pageerror:", String(e).slice(0, 200)));
const cdp = await page.createCDPSession();
await cdp.send("Browser.setDownloadBehavior", { behavior: "deny" });
await page.evaluateOnNewDocument(() => {
	const revoke = URL.revokeObjectURL.bind(URL);
	URL.revokeObjectURL = (u) => setTimeout(() => revoke(u), 120000);
	const click = HTMLAnchorElement.prototype.click;
	HTMLAnchorElement.prototype.click = function () {
		if (this.download && this.href.startsWith("blob:")) {
			fetch(this.href).then((r) => r.arrayBuffer()).then((b) =>
				fetch("http://127.0.0.1:8796/?name=" + encodeURIComponent(this.download), { method: "POST", body: b }))
				.catch((e) => console.log("export post failed " + e));
			return;
		}
		return click.call(this);
	};
});

const text = () => page.evaluate(() => document.body.innerText);
const clickButton = (re, last = false) => page.evaluate((src, last) => {
	const rx = new RegExp(src);
	const bs = [...document.querySelectorAll("button")].filter((b) => rx.test(b.innerText.trim()) && b.offsetParent !== null);
	const b = last ? bs[bs.length - 1] : bs[0];
	if (b) b.click();
	return bs.length;
}, re.source, last);

try {
	await page.goto(`http://localhost:3000/esta/${sid}`, { waitUntil: "domcontentloaded", timeout: 180000 });
	for (let i = 0; i < 60 && !(await clickButton(/Edit$/)); i++) await sleep(2000);
	await sleep(3000);
	log("Edit stage open; building for export");
	const stamp = ((await text()).match(/Built [^\n]* from/) || [""])[0];
	for (let i = 0; i < 30 && !(await clickButton(/^Build for export/)); i++) await sleep(2000);
	let t = "";
	for (let i = 0; i < 300; i++) {
		await sleep(3000);
		t = await text();
		const m = t.match(/(Converting[^\n]*|Syncing media[^\n]*|Saving project[^\n]*)/);
		if (i % 10 === 0) log("build:", m ? m[1] : "(idle)");
		const now = (t.match(/Built [^\n]* from/) || [""])[0];
		if (/originals \(export-ready\)/.test(t) && now && now !== stamp && !m) break;
		if (/Missing on disk|failed|Error/.test(t) && !m) log("build note:", (t.match(/(Missing on disk[^\n]*|[^\n]*failed[^\n]*)/) || [""])[0].slice(0, 300));
	}
	if (!/originals \(export-ready\)/.test(t)) throw new Error("build did not finish");
	log("built:", (t.match(/media \d+[^\n]*/) || [""])[0]);
	await sleep(3000);
	const n = await clickButton(/^Export$/);
	log("export buttons:", n);
	await sleep(2500);
	const pop = await text();
	if (/Export blocked/.test(pop)) throw new Error("export blocked: " + pop.slice(pop.indexOf("Export blocked"), pop.indexOf("Export blocked") + 300));
	await clickButton(/^Export$/, true);
	log("export started");
	let done = "";
	for (let i = 0; i < 900; i++) {
		await sleep(4000);
		const files = fs.readdirSync(outDir).filter((f) => /\.(mp4|webm)$/.test(f));
		if (files.length) { done = files[0]; break; }
		const tt = await text().catch(() => "");
		if (/Export failed/.test(tt)) throw new Error("export failed: " + tt.slice(tt.indexOf("Export failed"), tt.indexOf("Export failed") + 300));
		if (i % 15 === 0) log("exporting:", (tt.match(/\n(\d{1,3}%)\n/) || ["", "?"])[1]);
	}
	if (!done) throw new Error("no download after 60 min");
	await sleep(3000);
	log("DONE", path.join(outDir, done), fs.statSync(path.join(outDir, done)).size);
} catch (e) {
	log("FAIL", e.message);
	await page.screenshot({ path: path.join(outDir, "fail.png") }).catch(() => {});
	process.exitCode = 1;
} finally {
	await browser.close();
	server.close();
}
