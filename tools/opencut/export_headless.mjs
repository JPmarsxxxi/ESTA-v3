// Build for export (originals) + Export for one session, in a headless Chrome with its own profile.
//   bun run export <session-id> [--out <dir>] [--software-decode]
// Needs `bun run dev` running (the editor on :3000, the backend on :8787). Chrome defers media loading in hidden
// tabs, so a build in a minimised window stalls; a headless page counts as visible (SPEC.md Part 12, F7). The
// page's download is posted to a local receiver instead of Chrome's download manager, which once stalled at
// .crdownload. Above 30 video clips the hardware decoders run out, so software decode turns on by itself.
import fs from "node:fs";
import http from "node:http";
import path from "node:path";
import { findChrome, loadPuppeteer, ROOT } from "./chrome.mjs";

const argv = process.argv.slice(2);
const sid = argv.find((a) => !a.startsWith("--"));
const opt = (name) => { const i = argv.indexOf(name); return i >= 0 ? argv[i + 1] : undefined; };
if (!sid) {
	console.error("usage: bun run export <session-id> [--out <dir>] [--software-decode]");
	process.exit(2);
}
const session = path.join(ROOT, "sessions", sid);
const outDir = path.resolve(opt("--out") || path.join(session, "exports"));
const editor = process.env.ESTA_EDITOR_URL || "http://localhost:3000";
const port = Number(process.env.ESTA_EXPORT_PORT || 8796);
const SOFTWARE_DECODE_ABOVE = 30;
fs.mkdirSync(outDir, { recursive: true });
const log = (...a) => console.log(new Date().toTimeString().slice(0, 8), ...a);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function videoClips(project) {
	const items = new Map((project?.project?.mediaLibrary?.items || []).map((m) => [m.id, m.type]));
	return (project?.project?.timeline?.tracks || [])
		.filter((t) => t.type === "video")
		.flatMap((t) => t.clips || [])
		.filter((c) => items.get(c.mediaId) === "video").length;
}

const projectFile = path.join(session, `${sid}.openreel.json`);
if (!fs.existsSync(projectFile)) {
	console.error(`no ${sid}.openreel.json in ${session}: run render first`);
	process.exit(2);
}
const clips = videoClips(JSON.parse(fs.readFileSync(projectFile, "utf8")));
const softwareDecode = argv.includes("--software-decode") || clips > SOFTWARE_DECODE_ABOVE;
log(`${sid}: ${clips} video clips${softwareDecode ? ", software decode" : ""}`);

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
}).listen(port, "127.0.0.1");

const chrome = findChrome();
if (!chrome) {
	console.error("no Chrome found: install Google Chrome or set ESTA_CHROME to its executable");
	server.close();
	process.exit(2);
}
const gpu = process.platform === "win32" ? ["--use-angle=d3d11"] : [];
const browser = await loadPuppeteer().launch({
	executablePath: chrome,
	headless: true,
	userDataDir: path.join(ROOT, "cache", "export-chrome-profile"),
	defaultViewport: { width: 1600, height: 950 },
	args: ["--autoplay-policy=no-user-gesture-required", "--window-size=1600,950", "--no-first-run", "--enable-unsafe-webgpu",
		"--enable-gpu", "--ignore-gpu-blocklist", ...gpu, ...(softwareDecode ? ["--disable-accelerated-video-decode"] : [])],
	protocolTimeout: 600000,
});
const page = await browser.newPage();
page.on("console", (m) => { const t = m.text(); if (/error|fail|export/i.test(t)) log("console:", t.slice(0, 200)); });
page.on("pageerror", (e) => log("pageerror:", String(e).slice(0, 200)));
const cdp = await page.createCDPSession();
await cdp.send("Browser.setDownloadBehavior", { behavior: "deny" });
await page.evaluateOnNewDocument((port) => {
	const revoke = URL.revokeObjectURL.bind(URL);
	URL.revokeObjectURL = (u) => setTimeout(() => revoke(u), 120000);
	const click = HTMLAnchorElement.prototype.click;
	HTMLAnchorElement.prototype.click = function () {
		if (this.download && this.href.startsWith("blob:")) {
			fetch(this.href).then((r) => r.arrayBuffer()).then((b) =>
				fetch(`http://127.0.0.1:${port}/?name=` + encodeURIComponent(this.download), { method: "POST", body: b }))
				.catch((e) => console.log("export post failed " + e));
			return;
		}
		return click.call(this);
	};
}, port);

const text = () => page.evaluate(() => document.body.innerText);
const clickButton = (re, last = false) => page.evaluate((src, last) => {
	const rx = new RegExp(src);
	const bs = [...document.querySelectorAll("button")].filter((b) => rx.test(b.innerText.trim()) && b.offsetParent !== null);
	const b = last ? bs[bs.length - 1] : bs[0];
	if (b) b.click();
	return bs.length;
}, re.source, last);

try {
	await page.goto(`${editor}/esta/${sid}`, { waitUntil: "domcontentloaded", timeout: 180000 });
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
	log("export buttons:", await clickButton(/^Export$/));
	await sleep(2500);
	const pop = await text();
	if (/Export blocked/.test(pop)) throw new Error("export blocked: " + pop.slice(pop.indexOf("Export blocked"), pop.indexOf("Export blocked") + 300));
	await clickButton(/^Export$/, true);
	log("export started");
	const before = new Set(fs.readdirSync(outDir));
	let done = "";
	for (let i = 0; i < 900; i++) {
		await sleep(4000);
		const files = fs.readdirSync(outDir).filter((f) => /\.(mp4|webm)$/.test(f) && !before.has(f));
		if (files.length) { done = files[0]; break; }
		const tt = await text().catch(() => "");
		if (/Export failed/.test(tt)) throw new Error("export failed: " + tt.slice(tt.indexOf("Export failed"), tt.indexOf("Export failed") + 300));
		if (i % 15 === 0) log("exporting:", (tt.match(/\n(\d{1,3}%)\n/) || ["", "?"])[1]);
	}
	if (!done) throw new Error("no download after 60 min");
	await sleep(3000);
	log("DONE", path.join(outDir, done), fs.statSync(path.join(outDir, done)).size);
	console.log(JSON.stringify({ ok: true, file: path.join(outDir, done) }));
} catch (e) {
	log("FAIL", e.message);
	await page.screenshot({ path: path.join(outDir, "fail.png") }).catch(() => {});
	console.log(JSON.stringify({ ok: false, error: e.message }));
	process.exitCode = 1;
} finally {
	await browser.close();
	server.close();
}
