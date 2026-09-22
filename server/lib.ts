import type { IncomingMessage, ServerResponse } from "node:http";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { homedir } from "node:os";

export const REPO_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..");
export const ROOT = resolve(process.env.ASSET_ROOT || resolve(REPO_ROOT, "sessions"));
export const V2_SESSIONS = resolve(
	process.env.ESTA_V2_SESSIONS || resolve(REPO_ROOT, "..", "ESTA-v2", "sessions"),
);
export const STATE_DIR = resolve(REPO_ROOT, ".esta");

export type Json = Record<string, unknown>;

export function send(res: ServerResponse, status: number, body = "") {
	res.writeHead(status, { "Content-Type": "text/plain" });
	res.end(body);
}

export function json(res: ServerResponse, status: number, obj: unknown) {
	res.writeHead(status, { "Content-Type": "application/json", "Cache-Control": "no-store" });
	res.end(JSON.stringify(obj));
}

export function readBody(req: IncomingMessage): Promise<Json> {
	return new Promise((resolve_, reject) => {
		let raw = "";
		req.on("data", (d) => {
			raw += d;
			if (raw.length > 1e6) reject(new Error("body too large"));
		});
		req.on("end", () => {
			try {
				resolve_(raw ? JSON.parse(raw) : {});
			} catch (e) {
				reject(e);
			}
		});
		req.on("error", reject);
	});
}

export function readRaw(req: IncomingMessage): Promise<Buffer> {
	return new Promise((resolve_, reject) => {
		const chunks: Buffer[] = [];
		req.on("data", (c: Buffer) => chunks.push(c));
		req.on("end", () => resolve_(Buffer.concat(chunks)));
		req.on("error", reject);
	});
}

// The id comes from a query string or body, so a traversal attempt must not escape ROOT.
export function sessionDir(sessionId: unknown): string | null {
	const dir = resolve(ROOT, String(sessionId || ""));
	if (!dir.startsWith(ROOT) || dir === ROOT) return null;
	return dir;
}

// Mirror tools/render/run.py:_asset_url so the client never has to know on-disk paths.
export function fileToUrl(file: unknown, sessionId: string): string {
	if (!file) return "";
	let rel = String(file).replace(/\\/g, "/");
	const marker = "sessions/";
	const idx = rel.indexOf(marker);
	rel = idx >= 0 ? rel.slice(idx + marker.length) : `${sessionId}/${rel.replace(/^\/+/, "")}`;
	return "/api/sessions/" + rel;
}

let ESTA_PYTHON: string | null | undefined;
export function estaPython(): string | null {
	if (ESTA_PYTHON !== undefined) return ESTA_PYTHON;
	const tries = [
		process.env.ESTA_PYTHON,
		resolve(homedir(), ".conda", "envs", "esta", "python.exe"),
		resolve(homedir(), ".conda", "envs", "esta", "bin", "python"),
		resolve(homedir(), "anaconda3", "envs", "esta", "python.exe"),
		resolve(homedir(), "miniconda3", "envs", "esta", "bin", "python"),
		"C:\\ProgramData\\anaconda3\\envs\\esta\\python.exe",
	].filter((p): p is string => Boolean(p));
	ESTA_PYTHON = tries.find((p) => existsSync(p)) || null;
	return ESTA_PYTHON;
}

// Spawn the real .exe, not the claude.cmd shim: Node can't spawn a .cmd without
// shell:true, and prompts carry user text that must never reach a shell.
let CLAUDE_BIN: string | undefined;
export function claudeBin(): string {
	if (CLAUDE_BIN !== undefined) return CLAUDE_BIN;
	const npm = resolve(homedir(), "AppData", "Roaming", "npm");
	const tries = [
		process.env.CLAUDE_BIN,
		process.env.CLAUDE_CODE_EXECPATH,
		resolve(npm, "node_modules", "@anthropic-ai", "claude-code", "bin", "claude.exe"),
	].filter((p): p is string => Boolean(p));
	CLAUDE_BIN = tries.find((p) => existsSync(p)) || "claude";
	return CLAUDE_BIN;
}

export const PY_ENV = { ...process.env, PYTHONIOENCODING: "utf-8" };
