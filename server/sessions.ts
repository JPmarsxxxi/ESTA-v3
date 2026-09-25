import type { IncomingMessage, ServerResponse } from "node:http";
import { cpSync, existsSync, mkdirSync, readFileSync, readdirSync, rmSync, statSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { REPO_ROOT, ROOT, V2_SESSIONS, json, readBody, send } from "./lib.ts";
import { STAGES, artifactPresent, mutateUi, readPipeline } from "./pipeline.ts";
import { noteSelfWrite } from "./files.ts";

// v2 behaviour: only session folders that contain a *.openreel.json, newest first.
export function listSessions(res: ServerResponse) {
	let entries: import("node:fs").Dirent[] = [];
	try {
		entries = readdirSync(ROOT, { withFileTypes: true });
	} catch {
		return json(res, 200, { sessions: [] });
	}
	const sessions = [];
	for (const ent of entries) {
		if (!ent.isDirectory()) continue;
		const id = ent.name;
		const dir = resolve(ROOT, id);
		let files: string[];
		try {
			files = readdirSync(dir);
		} catch {
			continue;
		}
		let pick: { file: string; mtimeMs: number } | null = null;
		for (const f of files.filter((f) => f.endsWith(".openreel.json"))) {
			try {
				const st = statSync(resolve(dir, f));
				if (!pick || st.mtimeMs > pick.mtimeMs) pick = { file: f, mtimeMs: st.mtimeMs };
			} catch {}
		}
		if (!pick) continue;
		let name = id;
		try {
			const parsed = JSON.parse(readFileSync(resolve(dir, pick.file), "utf8"));
			const candidate = parsed?.project?.name ?? parsed?.name;
			if (typeof candidate === "string" && candidate.trim()) name = candidate.trim();
		} catch {}
		sessions.push({ id, file: pick.file, name, modifiedAt: pick.mtimeMs });
	}
	sessions.sort((a, b) => b.modifiedAt - a.modifiedAt);
	json(res, 200, { sessions });
}

function summarize(root: string, id: string) {
	const dir = resolve(root, id);
	let topic = "";
	try {
		topic = JSON.parse(readFileSync(resolve(dir, "requirements.json"), "utf8")).topic || "";
	} catch {}
	let modifiedAt = 0;
	try {
		for (const f of readdirSync(dir)) modifiedAt = Math.max(modifiedAt, statSync(resolve(dir, f)).mtimeMs);
	} catch {}
	const pipe = readPipeline(dir);
	return {
		id,
		topic,
		template: pipe?.template ?? null,
		modifiedAt,
		hasProject: artifactPresent(dir, "*.openreel.json"),
	};
}

// Every session folder (the session list page), not just rendered ones.
export function listAllSessions(res: ServerResponse, root = ROOT) {
	let ids: string[] = [];
	try {
		ids = readdirSync(root, { withFileTypes: true })
			.filter((e) => e.isDirectory() && !e.name.startsWith(".") && !e.name.startsWith("_"))
			.map((e) => e.name);
	} catch {}
	const sessions = ids.map((id) => summarize(root, id)).sort((a, b) => b.modifiedAt - a.modifiedAt);
	json(res, 200, { sessions, stages: STAGES.map(({ id, label }) => ({ id, label })) });
}

// Slug a free-text topic; strips path separators so a topic can't escape ROOT.
function slugify(topic: unknown) {
	return String(topic ?? "")
		.toLowerCase()
		.normalize("NFKD")
		.replace(/[^\w\s-]/g, "")
		.replace(/[\s_]+/g, "-")
		.replace(/-+/g, "-")
		.replace(/^-+|-+$/g, "")
		.slice(0, 60);
}

function todayStamp() {
	const d = new Date();
	const pad = (n: number) => String(n).padStart(2, "0");
	return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

// The requirements skill's own validators (tools/requirements/validators.py)
// normalise style and duration exactly as the conversational intake does.
const VALIDATE_PY = `
import json, sys
sys.path.insert(0, "tools")
from requirements.validators import validate_topic, validate_style, validate_duration
d = json.load(sys.stdin)
out, errors = {}, {}
for key, fn in (("topic", validate_topic), ("style", validate_style), ("duration_range", validate_duration)):
    ok, val = fn(d.get(key) or "")
    if ok:
        out[key] = val if key != "topic" else (d.get(key) or "").strip()
    else:
        errors[key] = val
print(json.dumps({"values": out, "errors": errors}))
`;

function validateRequirements(body: Record<string, unknown>): { values: Record<string, string>; errors: Record<string, string> } {
	const r = spawnSync("python", ["-c", VALIDATE_PY], { cwd: REPO_ROOT, input: JSON.stringify(body), encoding: "utf8" });
	try {
		return JSON.parse(r.stdout);
	} catch {
		return { values: {}, errors: { _: (r.stderr || "validator failed").trim().slice(-300) } };
	}
}

function wordCount(text: string) {
	return text.split(/\s+/).filter(Boolean).length;
}

// tools/requirements/schema.py:default_requirements, filled from the form. The
// form collects what the requirements skill's conversation would.
function buildRequirements(id: string, body: Record<string, unknown>) {
	const str = (k: string, d = "") => (typeof body[k] === "string" ? String(body[k]).trim() : d);
	const examples = Array.isArray(body.example_scripts)
		? (body.example_scripts as unknown[])
				.map((t) => String(t ?? "").trim())
				.filter(Boolean)
				.map((text) => ({ text, length: text.length, source: "user_paste" }))
		: [];
	const scriptText = str("script_text");
	const uploaded = Boolean(scriptText);
	const words = wordCount(scriptText);
	return {
		session_id: id,
		created_at: new Date().toISOString(),
		topic: str("topic"),
		style: str("style").toLowerCase(),
		duration_range: str("duration_range"),
		orientation: str("orientation", "vertical") || "vertical",
		comments: str("comments"),
		licensing: str("licensing", "free_only") === "fair_use_ok" ? "fair_use_ok" : "free_only",
		example_scripts: examples.length ? examples : "ASSET_COLLECTOR_PLACEHOLDER",
		script_source: uploaded ? "user_uploaded" : "generate",
		skip_scriptwriter: uploaded,
		script_text: uploaded ? scriptText : null,
		script_file: uploaded ? "script_uploaded.txt" : null,
		script_stats: uploaded ? { word_count: words, char_count: scriptText.length, estimated_duration_min: Math.round((words / 150) * 100) / 100 } : null,
	};
}

// Body: { topic, ...requirements fields }. Picks "<slug>-<YYYY-MM-DD>", suffixing
// -2/-3 on same-day collisions. Writes requirements.json when fields are given
// (v2's bare {topic} call still just creates the folder).
export async function createSession(req: IncomingMessage, res: ServerResponse) {
	let body: Record<string, unknown>;
	try {
		body = await readBody(req);
	} catch {
		return send(res, 400, "Invalid JSON");
	}
	const slug = slugify(body.topic);
	if (!slug) return send(res, 400, "Missing or empty topic");
	const withRequirements = body.requirements !== false && (body.style !== undefined || body.duration_range !== undefined);
	if (withRequirements) {
		const v = validateRequirements(body);
		if (Object.keys(v.errors).length) return json(res, 400, { error: "invalid requirements", fields: v.errors });
		body = { ...body, ...v.values };
	}
	const stamp = todayStamp();
	let id = `${slug}-${stamp}`;
	let path = resolve(ROOT, id);
	let n = 2;
	if (!path.startsWith(ROOT)) return send(res, 400, "Bad topic");
	while (existsSync(path)) {
		id = `${slug}-${stamp}-${n}`;
		path = resolve(ROOT, id);
		if (!path.startsWith(ROOT)) return send(res, 400, "Bad topic");
		if (++n > 50) return send(res, 500, "Too many same-day sessions");
	}
	try {
		mkdirSync(path, { recursive: true });
		if (withRequirements) {
			const reqs = buildRequirements(id, body);
			writeFileSync(resolve(path, "requirements.json"), JSON.stringify(reqs, null, 2), "utf8");
			writeFileSync(
				resolve(path, "conversation.jsonl"),
				JSON.stringify({ ts: new Date().toISOString(), role: "user", text: `Requirements form (ESTA v3): ${JSON.stringify(reqs)}` }) + "\n",
				"utf8",
			);
			if (reqs.script_text) writeFileSync(resolve(path, "script_uploaded.txt"), reqs.script_text, "utf8");
		}
	} catch (e) {
		return send(res, 500, `create failed: ${e}`);
	}
	json(res, 200, { id, path, topic: body.topic ?? "" });
}

export function listV2Sessions(res: ServerResponse) {
	if (!existsSync(V2_SESSIONS)) return json(res, 200, { root: V2_SESSIONS, sessions: [] });
	let ids: string[] = [];
	try {
		ids = readdirSync(V2_SESSIONS, { withFileTypes: true }).filter((e) => e.isDirectory()).map((e) => e.name);
	} catch {}
	json(res, 200, {
		root: V2_SESSIONS,
		sessions: ids.map((id) => ({ ...summarize(V2_SESSIONS, id), existsInV3: existsSync(resolve(ROOT, id)) })),
	});
}

// Copy a v2 session. An existing v3 folder is never merged: 409 unless the
// caller chose overwrite or rename. Checkpoints whose artifacts already exist
// were passed conversationally in v2, so they're recorded as approved by import.
export async function importSession(req: IncomingMessage, res: ServerResponse) {
	const body = await readBody(req).catch(() => ({}) as Record<string, unknown>);
	const src = resolve(V2_SESSIONS, String(body.id || ""));
	if (!src.startsWith(V2_SESSIONS) || src === V2_SESSIONS || !existsSync(src)) return json(res, 404, { error: "no such v2 session" });
	let id = String(body.id);
	if (body.mode === "rename") {
		id = String(body.newId || "").trim() || `${id}-v2`;
		if (!/^[\w.-]+$/.test(id)) return json(res, 400, { error: "invalid session id" });
	}
	const dest = resolve(ROOT, id);
	if (!dest.startsWith(ROOT) || dest === ROOT) return json(res, 400, { error: "bad id" });
	if (existsSync(dest)) {
		if (body.mode !== "overwrite") return json(res, 409, { error: `session ${id} already exists in v3`, exists: true, id });
		rmSync(dest, { recursive: true, force: true });
	}
	cpSync(src, dest, { recursive: true, filter: (p) => !p.includes("__pycache__") });
	// A v2 session without pipeline.json gets the canonical standard-vo rails,
	// so its approvals have somewhere to live.
	const hadPipeline = Boolean(readPipeline(dest));
	const approvals: string[] = [];
	if (artifactPresent(dest, "requirements.json")) {
		const at = new Date().toISOString();
		mutateUi(dest, (ui) => {
			const has = (a: string) => artifactPresent(dest, a);
			ui.approvals.requirements = { at, by: "import" };
			if (has("script.md")) ui.approvals.script = { at, by: "import" };
			if (has("script.tagged.md")) ui.approvals.tagged_script = { at, by: "import" };
			if (has("plan.json")) ui.approvals.plan = { at, by: "import" };
			approvals.push(...Object.keys(ui.approvals));
		});
	}
	json(res, 200, { ok: true, id, approvals, builtPipeline: !hadPipeline && approvals.length > 0 });
}

// Edit an existing session's requirements from the Requirements workspace.
// Same validators and field rules as create; session_id, created_at and any
// field the form doesn't own are preserved, and so are example scripts whose
// text didn't change (they keep their original source).
export async function updateRequirements(req: IncomingMessage, res: ServerResponse, sessionId: string) {
	const dir = resolve(ROOT, sessionId);
	if (!dir.startsWith(ROOT) || dir === ROOT || !existsSync(dir)) return json(res, 404, { error: "no such session" });
	let body: Record<string, unknown>;
	try {
		body = await readBody(req);
	} catch {
		return json(res, 400, { error: "Invalid JSON" });
	}
	const v = validateRequirements(body);
	if (Object.keys(v.errors).length) return json(res, 400, { error: "invalid requirements", fields: v.errors });
	const path = resolve(dir, "requirements.json");
	let prior: Record<string, unknown> = {};
	try {
		prior = JSON.parse(readFileSync(path, "utf8"));
	} catch {}
	const built = buildRequirements(sessionId, { ...body, ...v.values });
	const priorExamples = Array.isArray(prior.example_scripts) ? (prior.example_scripts as Array<{ text?: string }>) : [];
	const examples = Array.isArray(built.example_scripts)
		? built.example_scripts.map((e) => priorExamples.find((p) => p.text === e.text) ?? e)
		: built.example_scripts;
	const next = { ...prior, ...built, example_scripts: examples, session_id: prior.session_id ?? sessionId, created_at: prior.created_at ?? built.created_at };
	writeFileSync(path, JSON.stringify(next, null, 2), "utf8");
	noteSelfWrite(path, req.headers["x-esta-client"]);
	if (built.script_text) writeFileSync(resolve(dir, "script_uploaded.txt"), built.script_text, "utf8");
	json(res, 200, { ok: true, requirements: next });
}
