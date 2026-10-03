import type { IncomingMessage, ServerResponse } from "node:http";
import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, resolve } from "node:path";
import { PY_ENV, REPO_ROOT, json, readBody, readRaw, sessionDir } from "./lib.ts";
import { noteSelfWrite } from "./files.ts";

// SPEC.md Part 5 (M8.3): the Style stage's Look card. tools/look/refs.py owns the index; these routes only
// shuttle files and flags to it. The images themselves are served by the normal session-file route.

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;

const readJson = (p: string): Row | null => {
	try {
		return JSON.parse(readFileSync(p, "utf8"));
	} catch {
		return null;
	}
};

function refs(args: string[]): { status: number; body: Row } {
	const r = spawnSync("python", ["tools/look/refs.py", ...args], { cwd: REPO_ROOT, encoding: "utf8", env: PY_ENV, windowsHide: true });
	try {
		const body = JSON.parse(r.stdout.trim().split("\n").pop() || "{}");
		return { status: body.ok ? 200 : 400, body };
	} catch {
		return { status: 500, body: { error: (r.stderr || "refs.py failed").trim().slice(-300) } };
	}
}

export function lookIndex(res: ServerResponse, session: string) {
	const dir = sessionDir(session);
	if (!dir || !existsSync(dir)) return json(res, 404, { error: "no such session" });
	const idx = readJson(resolve(dir, "look_refs.json")) ?? { images: [] };
	json(res, 200, { ...idx, look_style: readJson(resolve(dir, "requirements.json"))?.look_style ?? "" });
}

export async function lookAdd(req: IncomingMessage, res: ServerResponse, session: string) {
	const dir = sessionDir(session);
	if (!dir || !existsSync(dir)) return json(res, 404, { error: "no such session" });
	const name = basename(String(req.headers["x-filename"] || "ref.png")).replace(/[^\w.-]/g, "_");
	const tmp = mkdtempSync(resolve(tmpdir(), "esta-look-"));
	try {
		const file = resolve(tmp, name);
		writeFileSync(file, await readRaw(req));
		const r = refs(["add", "--session", dir, file]);
		json(res, r.status, r.body);
	} finally {
		rmSync(tmp, { recursive: true, force: true });
	}
}

export async function lookEdit(req: IncomingMessage, res: ServerResponse, session: string, op: "role" | "remove") {
	const dir = sessionDir(session);
	if (!dir || !existsSync(dir)) return json(res, 404, { error: "no such session" });
	const body = await readBody(req).catch(() => ({}) as Row);
	const file = basename(String(body.file || ""));
	if (!file) return json(res, 400, { error: "file is required" });
	const r = refs(op === "role" ? ["role", "--session", dir, "--file", file, "--role", String(body.role)] : ["remove", "--session", dir, "--file", file]);
	json(res, r.status, r.body);
}

// look_style alone: the full requirements update re-validates topic, style and duration.
export async function lookStyle(req: IncomingMessage, res: ServerResponse, session: string) {
	const dir = sessionDir(session);
	const path = dir ? resolve(dir, "requirements.json") : "";
	const reqs = path ? readJson(path) : null;
	if (!reqs) return json(res, 404, { error: "no requirements.json yet" });
	const body = await readBody(req).catch(() => ({}) as Row);
	reqs.look_style = String(body.look_style ?? "").trim();
	writeFileSync(path, JSON.stringify(reqs, null, 2), "utf8");
	noteSelfWrite(path, req.headers["x-esta-client"]);
	json(res, 200, { ok: true, look_style: reqs.look_style });
}
