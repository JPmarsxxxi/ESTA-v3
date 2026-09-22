import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { relative, resolve, sep } from "node:path";
import { ROOT, json, readBody, send, sessionDir } from "./lib.ts";
import { subscribe, publish } from "./hub.ts";
import { onFileChange, startWatcher } from "./files.ts";
import { serveSessionFile, streamAssets } from "./media.ts";
import { handleAck, handleFrame, handleState, injectCmd, streamCmds } from "./livecmd.ts";
import { pickerCandidates, pickerJobs, pickerPick, pickerRefetch, pickerShots, pickerSources } from "./picker.ts";
import { planCommand, planCommandStatus, planRewrite, planRewriteStatus, planSave, planShots } from "./planner.ts";
import { chatHealth, chatInterrupt, chatOpen, chatSend, chatStatus, chatStop, chatStream, stopAllChats } from "./chat.ts";
import { createSession, importSession, listAllSessions, listSessions, listV2Sessions } from "./sessions.ts";
import { activeJobs, cancelJob, getJob, jobLog, listJobs, loadJobs, onJobEnd, retryJob, setProgress, startJob, type Job } from "./jobs.ts";
import { artifactPresent, computeState, mutateUi, rebuildPipeline, setCustomFlow, templates, type Checkpoint } from "./pipeline.ts";
import { ACTIONS, actionBlock, buildJob, preflight, voiceSamples } from "./actions.ts";

const PORT = Number(process.env.ASSET_PORT) || 8787;

function runInfo(session: string) {
	const running = new Set(activeJobs(session).map((j) => j.stage));
	const failed = new Set<string>();
	const seen = new Set<string>();
	for (const j of listJobs(session)) {
		if (seen.has(j.stage)) continue;
		seen.add(j.stage);
		if (j.status === "failed" || j.status === "interrupted") failed.add(j.stage);
	}
	return { running, failed };
}

function pipelineState(session: string) {
	const state = computeState(session, runInfo(session));
	const dir = sessionDir(session) as string;
	const pre = preflight();
	const tokens = new Set(state.steps.map((s) => s.token));
	const actions = ACTIONS.filter((a) => ([] as string[]).concat(a.step ?? []).every((t) => tokens.has(t))).map((a) => {
		const block = actionBlock(a, state, (x) => artifactPresent(dir, x));
		return {
			id: a.id,
			stage: a.stage,
			label: a.label,
			hint: a.hint ?? null,
			warn: a.warn ?? null,
			kind: a.kind,
			params: (a.params ?? []).map((p) => (p.name === "sample" ? { ...p, options: voiceSamples() } : p)),
			blocked: block?.reason ?? null,
			forceable: block?.forceable ?? false,
			running: activeJobs(session).some((j) => j.action === a.id),
		};
	});
	return { ...state, actions, preflight: pre, templates: Object.fromEntries(Object.entries(templates()).map(([k, v]) => [k, v.description])) };
}

function publishPipeline(session: string) {
	try {
		publish({ ch: "pipeline", session, data: pipelineState(session) });
	} catch {
		/* session folder gone */
	}
}

// Progress from the *_progress.jsonl files the tools already write.
function progressFor(job: Job): Job["progress"] {
	const dir = sessionDir(job.session);
	if (!dir) return null;
	const action = ACTIONS.find((a) => a.id === job.action);
	const lines = (f: string) => {
		const p = resolve(dir, f);
		if (!existsSync(p)) return [];
		return readFileSync(p, "utf8").split("\n").filter((l) => l.trim()).map((l) => {
			try {
				return JSON.parse(l);
			} catch {
				return null;
			}
		}).filter(Boolean);
	};
	const readJson = (f: string) => {
		try {
			return JSON.parse(readFileSync(resolve(dir, f), "utf8"));
		} catch {
			return null;
		}
	};
	if (action?.progress === "timestamps") {
		const segs = lines("timestamps_progress.jsonl");
		const total = Number(readJson("audio_metadata.json")?.duration_seconds ?? readJson("audio_metadata.json")?.duration ?? 0);
		const last = segs[segs.length - 1];
		const done = Number(last?.end ?? last?.segment?.end ?? 0);
		return total ? { done: Math.min(done, total), total, label: `${Math.round(done)}s / ${Math.round(total)}s transcribed` } : { done: segs.length, total: 0, label: `${segs.length} segments` };
	}
	if (action?.progress === "assets") {
		const shots = new Set(lines("assets_progress.jsonl").map((r) => String(r.shot_number)).filter((n) => !n.includes("-")));
		const total = (readJson("plan.json")?.shots ?? []).length;
		return { done: shots.size, total, label: `${shots.size} / ${total} shots` };
	}
	if (action?.progress === "plan") {
		const n = lines("plan_progress.jsonl").length;
		return { done: n, total: 0, label: `${n} shots planned` };
	}
	return null;
}

onFileChange((ev) => {
	publishPipeline(ev.session);
	for (const job of activeJobs(ev.session)) setProgress(job, progressFor(job));
});

onJobEnd((job) => {
	const action = ACTIONS.find((a) => a.id === job.action);
	if (job.status === "done" && action?.then) {
		const next = ACTIONS.find((a) => a.id === action.then);
		const dir = sessionDir(job.session) as string;
		const state = computeState(job.session, runInfo(job.session));
		if (next && !actionBlock(next, state, (x) => artifactPresent(dir, x))) startJob(buildJob(next, job.session, {}));
	}
	publishPipeline(job.session);
});

async function pipelineRoute(req: IncomingMessage, res: ServerResponse, session: string, sub: string) {
	const dir = sessionDir(session);
	if (!dir || !existsSync(dir)) return json(res, 404, { error: "no such session" });
	if (req.method === "GET" && !sub) return json(res, 200, pipelineState(session));
	if (req.method !== "POST") return json(res, 405, { error: "method not allowed" });
	const body = await readBody(req).catch(() => ({}) as Record<string, unknown>);
	try {
		if (sub === "approve") {
			const cp = String(body.checkpoint) as Checkpoint;
			if (!["requirements", "script", "tagged_script", "plan"].includes(cp)) return json(res, 400, { error: "unknown checkpoint" });
			const needs: Record<Checkpoint, string> = { requirements: "requirements.json", script: "script.md", tagged_script: "script.tagged.md", plan: "plan.json" };
			if (!artifactPresent(dir, needs[cp]) && body.revoke !== true) return json(res, 409, { error: `nothing to approve: ${needs[cp]} is missing` });
			if (cp === "requirements" && body.template && body.revoke !== true) rebuildPipeline(dir, String(body.template));
			mutateUi(dir, (ui) => {
				if (body.revoke === true) delete ui.approvals[cp];
				else ui.approvals[cp] = { at: new Date().toISOString(), by: "user" };
			});
		} else if (sub === "force") {
			const stage = String(body.stage);
			const state = computeState(session, runInfo(session));
			const st = state.stages.find((s) => s.id === stage);
			if (!st) return json(res, 400, { error: "unknown stage" });
			const locked = state.steps.filter((s) => st.steps.includes(s.token) && s.locked);
			if (!locked.length) return json(res, 409, { error: "stage is not locked" });
			mutateUi(dir, (ui) => {
				for (const s of locked) ui.overrides[s.token] = { at: new Date().toISOString(), missing: s.missing, pendingApprovals: s.pendingApprovals };
			});
		} else if (sub === "template") {
			rebuildPipeline(dir, String(body.template));
		} else if (sub === "flow") {
			setCustomFlow(dir, (Array.isArray(body.tokens) ? body.tokens : []).map(String));
		} else if (sub === "run") {
			const action = ACTIONS.find((a) => a.id === body.action);
			if (!action) return json(res, 404, { error: "unknown action" });
			const params = (body.params ?? {}) as Record<string, string>;
			for (const p of action.params ?? []) {
				if (!p.optional && p.kind === "select" && !params[p.name]) return json(res, 400, { error: `choose ${p.label}` });
			}
			if (params.sample && !voiceSamples().includes(params.sample)) return json(res, 400, { error: "unknown voice sample" });
			if (params.only && !/^[A-Za-z0-9,]+$/.test(params.only)) return json(res, 400, { error: "lines must look like L04,L07" });
			const state = computeState(session, runInfo(session));
			const block = actionBlock(action, state, (x) => artifactPresent(dir, x));
			if (block) return json(res, 409, { error: block.reason, forceable: block.forceable });
			if (activeJobs(session).some((j) => j.action === action.id)) return json(res, 409, { error: "already running" });
			const job = startJob(buildJob(action, session, params));
			publishPipeline(session);
			return json(res, 202, { ok: true, job });
		} else return json(res, 404, { error: "unknown pipeline route" });
	} catch (e) {
		return json(res, 400, { error: String((e as Error).message || e) });
	}
	publishPipeline(session);
	json(res, 200, { ok: true, state: pipelineState(session) });
}

async function jobsRoute(req: IncomingMessage, res: ServerResponse, rest: string[], query: URLSearchParams) {
	const [id, verb] = rest;
	if (!id) return json(res, 200, { jobs: listJobs(query.get("session")) });
	const job = getJob(id);
	if (!job) return json(res, 404, { error: "no such job" });
	if (req.method === "GET" && verb === "log") {
		res.writeHead(200, { "Content-Type": "text/plain; charset=utf-8", "Cache-Control": "no-store" });
		return res.end(jobLog(id));
	}
	if (req.method === "GET") return json(res, 200, { job });
	if (verb === "cancel") return json(res, cancelJob(id) ? 200 : 409, { ok: true });
	if (verb === "retry") {
		const next = retryJob(id);
		if (!next) return json(res, 409, { error: "job is still running" });
		publishPipeline(job.session);
		return json(res, 202, { ok: true, job: next });
	}
	json(res, 404, { error: "unknown job route" });
}

// Session file listing for the Files panel; media pools are summarised, not walked.
function listFiles(dir: string) {
	const out: Array<{ path: string; size: number; mtimeMs: number }> = [];
	const walk = (d: string, depth: number) => {
		for (const e of readdirSync(d, { withFileTypes: true })) {
			if (e.name === "__pycache__" || out.length > 1500) continue;
			const p = resolve(d, e.name);
			if (e.isDirectory()) {
				if (depth < 3) walk(p, depth + 1);
				continue;
			}
			const st = statSync(p);
			out.push({ path: relative(dir, p).split(sep).join("/"), size: st.size, mtimeMs: st.mtimeMs });
		}
	};
	walk(dir, 0);
	return out;
}

function filesRoute(req: IncomingMessage, res: ServerResponse, session: string, list: boolean) {
	const dir = sessionDir(session);
	if (!dir || !existsSync(dir)) return json(res, 404, { error: "no such session" });
	if (list) return json(res, 200, { files: listFiles(dir) });
	// Session-scoped view of the shared /_events stream.
	return subscribe(req, res, new URLSearchParams({ session }));
}

async function handleRequest(req: IncomingMessage, res: ServerResponse) {
	res.setHeader("Access-Control-Allow-Origin", "*");
	// Without these, preflight for a cross-origin JSON POST fails and the editor can't talk back.
	res.setHeader("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS");
	res.setHeader("Access-Control-Allow-Headers", "Content-Type, X-Esta-Client");
	res.setHeader("Cross-Origin-Resource-Policy", "cross-origin");
	res.setHeader("Accept-Ranges", "bytes");
	if (req.method === "OPTIONS") return void res.writeHead(204).end();

	const url = new URL(req.url || "/", "http://localhost");
	const urlPath = decodeURIComponent(url.pathname);
	const pk = urlPath.replace(/\/+$/, "") || "/";
	const q = url.searchParams;
	const is = (method: string, path: string) => req.method === method && pk === path;

	if (is("GET", "/_events")) return subscribe(req, res, q);
	if (is("GET", "/_preflight")) return json(res, 200, preflight(q.get("refresh") === "1"));

	if (is("GET", "/_picker/api/shots")) return pickerShots(res, q);
	if (is("GET", "/_picker/api/candidates")) return pickerCandidates(res, q);
	if (is("POST", "/_picker/api/pick")) return pickerPick(req, res);
	if (is("POST", "/_picker/api/refetch")) return pickerRefetch(req, res);
	if (is("GET", "/_picker/api/sources")) return pickerSources(res, q);
	if (is("GET", "/_picker/api/jobs")) return pickerJobs(res, q);

	if (is("GET", "/_plan/api/plan")) return planShots(res, q);
	if (is("POST", "/_plan/api/shot")) return planSave(req, res);
	if (is("POST", "/_plan/api/rewrite")) return planRewrite(req, res);
	if (is("GET", "/_plan/api/rewrite")) return planRewriteStatus(res, q);
	if (is("POST", "/_plan/api/command")) return planCommand(req, res);
	if (is("GET", "/_plan/api/command")) return planCommandStatus(res, q);

	if (is("GET", "/_cmd_stream")) return streamCmds(req, res);
	if (is("POST", "/_cmd")) return injectCmd(req, res);
	if (pk === "/_state" && (req.method === "GET" || req.method === "POST")) return handleState(req, res);
	if (pk === "/_ack" && (req.method === "GET" || req.method === "POST")) return handleAck(req, res, q);
	if (pk === "/_frame" && (req.method === "GET" || req.method === "POST")) return handleFrame(req, res, q);

	if (is("GET", "/chat/health")) return chatHealth(res);
	if (is("GET", "/chat/stream")) return chatStream(req, res, q);
	if (is("GET", "/chat/status")) return chatStatus(res, q);
	if (is("POST", "/chat/open")) return chatOpen(req, res);
	if (is("POST", "/chat/send")) return chatSend(req, res);
	if (is("POST", "/chat/interrupt")) return chatInterrupt(req, res);
	if (is("POST", "/chat/stop")) return chatStop(req, res);

	if (is("GET", "/_sessions/list")) return q.get("all") === "1" ? listAllSessions(res) : listSessions(res);
	if (is("POST", "/_sessions/create")) return createSession(req, res);
	if (is("GET", "/_sessions/import")) return listV2Sessions(res);
	if (is("POST", "/_sessions/import")) return importSession(req, res);

	const pipe = /^\/_pipeline\/([^/]+)(?:\/([^/]+))?$/.exec(pk);
	if (pipe) return pipelineRoute(req, res, pipe[1], pipe[2] || "");
	if (pk === "/_jobs" || pk.startsWith("/_jobs/")) return jobsRoute(req, res, pk.split("/").slice(2), q);
	const files = /^\/_files\/([^/]+)(\/list)?$/.exec(pk);
	if (files && req.method === "GET") return filesRoute(req, res, files[1], Boolean(files[2]));

	// Media: /api/sessions/<id>/... (v2's Vite proxy stripped this prefix; both forms work).
	const mediaPath = urlPath.startsWith("/api/sessions/") ? urlPath.slice("/api/sessions".length) : urlPath;
	const sse = /^\/([^/]+)\/_assets_stream\/?$/.exec(mediaPath);
	if (sse) return streamAssets(req, res, sse[1]);
	if (mediaPath === "/" || mediaPath.startsWith("/_")) return send(res, 404, "Not found");
	return serveSessionFile(req, res, mediaPath);
}

// One bad request must never take the server down (media, SSE and jobs share it).
const server = createServer((req, res) => {
	handleRequest(req, res).catch((err) => {
		console.error(`[500] ${req.method} ${req.url}`, err);
		if (!res.headersSent) json(res, 500, { error: String((err && err.message) || err) });
		else res.end();
	});
});

loadJobs((session, a) => {
	const dir = sessionDir(session);
	return Boolean(dir) && artifactPresent(dir as string, a);
});
startWatcher();
server.listen(PORT, () => console.log(`ESTA server on http://localhost:${PORT} serving ${ROOT}`));

// Jobs are left running on shutdown (a Kaggle run shouldn't die with the dev
// server); the next start picks them up as detached. Chats are ours to end.
for (const sig of ["SIGINT", "SIGTERM"] as const) {
	process.on(sig, () => {
		stopAllChats();
		process.exit(0);
	});
}
