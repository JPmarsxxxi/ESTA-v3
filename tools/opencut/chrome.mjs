// Headless Chrome for the repo's Node tools: puppeteer-core (it arrives with hyperframes) and a Chrome to drive.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");

export function loadPuppeteer() {
	// bun keeps puppeteer-core beside hyperframes, not at the top level of node_modules.
	const hf = fs.realpathSync(path.join(ROOT, "node_modules", "hyperframes", "package.json"));
	return createRequire(hf)("puppeteer-core");
}

export function findChrome() {
	const env = process.env.ESTA_CHROME || process.env.PRODUCER_HEADLESS_SHELL_PATH;
	if (env && fs.existsSync(env)) return env;
	for (const p of ["C:/Program Files/Google/Chrome/Application/chrome.exe", "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
		"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "/usr/bin/google-chrome", "/usr/bin/chromium",
		"/opt/pw-browsers/chromium-1194/chrome-linux/chrome"]) {
		if (fs.existsSync(p)) return p;
	}
	// hyperframes' own headless shell: fine for measuring pages, but it has no proprietary codecs, so export
	// prefers a real Chrome above.
	const shells = path.join(os.homedir(), ".cache", "puppeteer", "chrome-headless-shell");
	if (fs.existsSync(shells)) {
		for (const v of fs.readdirSync(shells).sort().reverse()) {
			for (const sub of ["chrome-headless-shell-win64/chrome-headless-shell.exe", "chrome-headless-shell-linux64/chrome-headless-shell",
				"chrome-headless-shell-mac-arm64/chrome-headless-shell", "chrome-headless-shell-mac-x64/chrome-headless-shell"]) {
				const p = path.join(shells, v, sub);
				if (fs.existsSync(p)) return p;
			}
		}
	}
	return null;
}
