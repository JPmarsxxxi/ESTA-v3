import type { IncomingMessage, ServerResponse } from "node:http";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { spawn, type ChildProcess } from "node:child_process";
import { resolve } from "node:path";
import { PY_ENV, REPO_ROOT, ROOT, claudeBin, estaPython, json, readBody, sessionDir } from "./lib.ts";
import { noteSelfWrite } from "./files.ts";

// Plan editor API, ported from v2 asset-server.mjs.

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;

export function planShots(res: ServerResponse, query: URLSearchParams) {
	const dir = sessionDir(query.get("session"));
	if (!dir) return json(res, 400, { error: "bad session" });
	const planPath = resolve(dir, "plan.json");
	if (!existsSync(planPath)) return json(res, 404, { error: "no plan.json" });
	const plan = JSON.parse(readFileSync(planPath, "utf8"));
	// Whole shots go to the client; it round-trips fields it doesn't surface.
	json(res, 200, {
		session: query.get("session"),
		video_metadata: plan.video_metadata || {},
		timing_source: plan.timing_source || "estimated",
		shots: plan.shots || [],
	});
}

export async function planSave(req: IncomingMessage, res: ServerResponse) {
	let body: Row;
	try {
		body = await readBody(req);
	} catch (e) {
		return json(res, 400, { error: String((e as Error).message || e) });
	}
	const dir = sessionDir(body.session);
	if (!dir) return json(res, 400, { error: "bad session" });
	const planPath = resolve(dir, "plan.json");
	if (!planPath.startsWith(ROOT) || !existsSync(planPath)) return json(res, 404, { error: "no plan.json" });
	const shot = body.shot;
	if (!shot || shot.shot_number == null) return json(res, 400, { error: "missing shot / shot_number" });
	const plan = JSON.parse(readFileSync(planPath, "utf8"));
	const shots: Row[] = plan.shots || [];
	const idx = shots.findIndex((s) => s.shot_number === shot.shot_number);
	if (idx < 0) return json(res, 404, { error: `no shot ${shot.shot_number}` });
	shots[idx] = shot;
	// Back up before the first overwrite so a bad edit is recoverable.
	const bak = resolve(dir, "plan.json.pre-edit.bak");
	if (!existsSync(bak)) writeFileSync(bak, readFileSync(planPath, "utf8"), "utf8");
	writeFileSync(planPath, JSON.stringify(plan, null, 2), "utf8");
	noteSelfWrite(planPath, req.headers["x-esta-client"]);
	json(res, 200, { ok: true, shot_number: shot.shot_number });
}

// One headless `claude -p` per click (lean system prompt, Haiku). Nothing
// touches plan.json until the human saves the proposal.
const REWRITES = new Map<string, Row>();

const REWRITE_SYSTEM =
	"You are a terse editor for a short-form video pipeline. You rewrite ONE shot's " +
	"fields per the user's instruction. Output ONLY a JSON object with the fields you " +
	"changed, no prose, no code fences. Editable fields: desc (string, what the shot " +
	"shows), type (REAL_FOOTAGE|REAL_IMAGE|MOTION_GRAPHICS), fx (array of zoom_in/" +
	"slow_motion), search_queries (array of short stock-search strings), music (string " +
	"mood), sfx (array; each item is a string or {sound,on} where on=the spoken word " +
	"it hits), caption (string). Keep it tight and on-voice; do not change the spoken " +
	"line. Return {} if nothing should change.";

function spawnClaude(args: string[]): ChildProcess {
	return spawn(claudeBin(), args, { cwd: REPO_ROOT, env: PY_ENV });
}

export async function planRewrite(req: IncomingMessage, res: ServerResponse) {
	let body: Row;
	try {
		body = await readBody(req);
	} catch (e) {
		return json(res, 400, { error: String((e as Error).message || e) });
	}
	const dir = sessionDir(body.session);
	if (!dir) return json(res, 400, { error: "bad session" });
	const shot = body.shot || {};
	const instruction = String(body.instruction || "").trim();
	if (shot.shot_number == null || !instruction) return json(res, 400, { error: "need shot + instruction" });
	const key = `${body.session}:${Number(shot.shot_number)}`;
	if (REWRITES.get(key)?.status === "running") return json(res, 409, { error: "already rewriting this shot" });

	const v = shot.visual || {};
	const context = {
		spoken: shot.audio || "",
		desc: v.desc || "",
		type: v.type || "REAL_FOOTAGE",
		fx: v.fx || [],
		search_queries: (v.search_sources || []).flatMap((e: Row) => e.queries || []),
		music: shot.audio_layer?.music || "",
		sfx: shot.audio_layer?.sfx || [],
		caption: shot.text?.caption || "",
	};
	const prompt =
		`INSTRUCTION: ${instruction}\n\nCURRENT SHOT:\n${JSON.stringify(context, null, 1)}\n\n` +
		`Return ONLY the JSON object of fields to change.`;
	const model = body.model || "claude-haiku-4-5-20251001";
	REWRITES.set(key, { status: "running", started: Date.now() });

	// spawn() can throw synchronously on Windows; catch it inside the handler.
	let child: ChildProcess;
	try {
		child = spawnClaude(["-p", prompt, "--system-prompt", REWRITE_SYSTEM, "--model", model, "--output-format", "json"]);
	} catch (e) {
		REWRITES.set(key, { status: "error", error: `spawn failed: ${(e as Error).message || e}` });
		return json(res, 500, { error: `could not launch claude: ${(e as Error).message || e}` });
	}
	let out = "";
	let err = "";
	child.stdout?.on("data", (d) => (out += d));
	child.stderr?.on("data", (d) => (err += d));
	child.on("error", (e) => REWRITES.set(key, { status: "error", error: String(e.message || e) }));
	child.on("close", () => {
		let env2: Row | null;
		try {
			env2 = JSON.parse(out);
		} catch {
			env2 = null;
		}
		if (!env2 || env2.is_error) {
			return REWRITES.set(key, { status: "error", error: (env2 && env2.result) || err.slice(-300) || "claude failed" });
		}
		const raw = String(env2.result || "").replace(/```json\s*|\s*```/g, "").trim();
		let proposal: unknown;
		try {
			proposal = JSON.parse(raw);
		} catch {
			proposal = null;
		}
		if (!proposal || typeof proposal !== "object") {
			return REWRITES.set(key, { status: "error", error: "model did not return JSON: " + raw.slice(0, 200) });
		}
		REWRITES.set(key, { status: "done", proposal, cost: env2.total_cost_usd || 0, ms: env2.duration_ms || 0, model });
	});
	json(res, 202, { ok: true, shot: shot.shot_number, status: "running" });
}

export function planRewriteStatus(res: ServerResponse, query: URLSearchParams) {
	const j = REWRITES.get(`${query.get("session")}:${Number(query.get("shot"))}`);
	json(res, 200, j || { status: "none" });
}

// The agent only parses intent into an op; tools/plan/ops.py does the timing,
// renumbering and feed migration deterministically.
const COMMANDS = new Map<string, Row>();

const COMMAND_SYSTEM =
	"You convert one natural-language plan-edit instruction into a JSON op. Output " +
	"ONLY the JSON, no prose. Ops:\n" +
	'  {"op":"split","shot":<n>,"at_word":"<the spoken word to cut at>"}\n' +
	'  {"op":"merge","shots":[<n>,<n+1>]}  (two ADJACENT shots)\n' +
	'  {"op":"overlay","shot":<n>,"caption":"<text on the card>","desc":"<optional visual note>"}\n' +
	"The user is editing a specific shot (its number is given as CURRENT_SHOT); if " +
	"they don't name a shot, use CURRENT_SHOT. For split, at_word must be an exact " +
	"word from the shot's spoken line. Return {\"error\":\"...\"} if the instruction " +
	"isn't one of these ops.";

export async function planCommand(req: IncomingMessage, res: ServerResponse) {
	let body: Row;
	try {
		body = await readBody(req);
	} catch (e) {
		return json(res, 400, { error: String((e as Error).message || e) });
	}
	const dir = sessionDir(body.session);
	if (!dir) return json(res, 400, { error: "bad session" });
	const text = String(body.text || "").trim();
	if (!text) return json(res, 400, { error: "need a command" });
	const session = String(body.session);
	if (COMMANDS.get(session)?.status === "running") return json(res, 409, { error: "a command is already running" });

	const prompt =
		`CURRENT_SHOT: ${body.shot}\nSPOKEN LINE: ${JSON.stringify(body.audio || "")}\n\n` +
		`INSTRUCTION: ${text}\n\nReturn ONLY the op JSON.`;
	COMMANDS.set(session, { status: "running", started: Date.now() });
	let child: ChildProcess;
	try {
		child = spawnClaude(["-p", prompt, "--system-prompt", COMMAND_SYSTEM, "--model", "claude-haiku-4-5-20251001", "--output-format", "json"]);
	} catch (e) {
		COMMANDS.set(session, { status: "error", error: `spawn failed: ${(e as Error).message || e}` });
		return json(res, 500, { error: `could not launch claude: ${(e as Error).message || e}` });
	}
	let out = "";
	child.stdout?.on("data", (d) => (out += d));
	child.on("error", (e) => COMMANDS.set(session, { status: "error", error: String(e.message || e) }));
	child.on("close", () => {
		let env2: Row | null;
		try {
			env2 = JSON.parse(out);
		} catch {
			env2 = null;
		}
		const raw = env2 ? String(env2.result || "").replace(/```json\s*|\s*```/g, "").trim() : "";
		let op: Row | null;
		try {
			op = JSON.parse(raw);
		} catch {
			op = null;
		}
		if (!op || op.error) {
			return COMMANDS.set(session, { status: "error", error: (op && op.error) || "could not parse: " + raw.slice(0, 150) });
		}
		const p = spawn(estaPython() || "python", ["tools/plan/ops.py", "--session", `sessions/${session}`, "--op", JSON.stringify(op)], {
			cwd: REPO_ROOT,
			env: PY_ENV,
		});
		let pout = "";
		let perr = "";
		p.stdout.on("data", (d) => (pout += d));
		p.stderr.on("data", (d) => (perr += d));
		p.on("close", () => {
			let result: Row | null;
			try {
				result = JSON.parse(pout);
			} catch {
				result = null;
			}
			if (!result || !result.ok) {
				return COMMANDS.set(session, { status: "error", op, error: (result && result.error) || perr.slice(-200) || "engine failed" });
			}
			COMMANDS.set(session, { status: "done", op, result, cost: (env2 && env2.total_cost_usd) || 0 });
		});
	});
	json(res, 202, { ok: true, status: "running" });
}

export function planCommandStatus(res: ServerResponse, query: URLSearchParams) {
	json(res, 200, COMMANDS.get(String(query.get("session"))) || { status: "none" });
}
