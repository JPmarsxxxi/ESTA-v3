import type { ServerResponse } from "node:http";
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, statSync } from "node:fs";
import { resolve } from "node:path";
import { PY_ENV, REPO_ROOT, ROOT, STATE_DIR, estaPython, json, sessionDir, type Json } from "./lib.ts";

type Media = Json & { url: string };

// The editor builds its native project from from_openreel.py's intermediate, so
// the track mapping, proxy choice and caption chunking stay v2's code. Each
// media entry gets the file's size and mtime so the editor only re-downloads
// what changed.
export function opencutImport(res: ServerResponse, session: string, originals: boolean) {
	const dir = sessionDir(session);
	if (!dir) return json(res, 400, { error: "bad session" });
	const py = estaPython();
	if (!py) return json(res, 500, { error: "esta env python not found — set ESTA_PYTHON to its full path and restart the server" });
	const outDir = resolve(STATE_DIR, "opencut");
	mkdirSync(outDir, { recursive: true });
	const out = resolve(outDir, `${session}.${originals ? "originals" : "proxies"}.json`);
	const args = ["tools/opencut/from_openreel.py", "--session", `sessions/${session}`, "--out", out];
	if (originals) args.push("--originals");
	// shell:false: argv never reaches a command interpreter.
	const child = spawn(py, args, { cwd: REPO_ROOT, env: PY_ENV });
	let stdout = "";
	let stderr = "";
	child.stdout.on("data", (d) => (stdout += d));
	child.stderr.on("data", (d) => (stderr += d));
	child.on("error", (e) => json(res, 500, { error: String(e.message || e) }));
	child.on("close", (code) => {
		const line = stdout.trim().split("\n").filter((l) => l.trim().startsWith("{")).pop();
		let summary: Json | null = null;
		try {
			summary = line ? JSON.parse(line) : null;
		} catch {}
		if (code !== 0 || !summary?.ok) {
			const error = typeof summary?.error === "string" ? summary.error : stderr.slice(-500) || `from_openreel exited ${code}`;
			return json(res, /No openreel\.json/.test(error) ? 404 : 500, { error });
		}
		const doc = JSON.parse(readFileSync(out, "utf8")) as Json & { media: Media[] };
		for (const m of doc.media) {
			try {
				const st = statSync(resolve(ROOT, decodeURIComponent(m.url.replace(/^\/api\/sessions\//, ""))));
				m.size = st.size;
				m.mtimeMs = Math.round(st.mtimeMs);
			} catch {
				m.missing = true;
			}
		}
		json(res, 200, { ...doc, originals, summary });
	});
}
