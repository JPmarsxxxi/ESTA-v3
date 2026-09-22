import type { IncomingMessage, ServerResponse } from "node:http";
import { appendFileSync, existsSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { spawn } from "node:child_process";
import { resolve } from "node:path";
import { PY_ENV, REPO_ROOT, ROOT, estaPython, fileToUrl, json, readBody, sessionDir } from "./lib.ts";
import { noteSelfWrite } from "./files.ts";

// Shot picker, ported from v2 asset-server.mjs. The human is the visual
// validator: `run.py candidates` downloads options, a click writes the winner
// to assets_progress.jsonl (the same feed line the auto path writes).

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;

function feedRows(dir: string): Row[] {
	const p = resolve(dir, "assets_progress.jsonl");
	if (!existsSync(p)) return [];
	const out: Row[] = [];
	for (const line of readFileSync(p, "utf8").split("\n")) {
		if (!line.trim()) continue;
		try {
			out.push(JSON.parse(line));
		} catch {}
	}
	return out;
}

// The motion-graphics skill and the stock fetch race on the feed; a successful
// generation is the shot's default and always offered, so replacing it is a
// deliberate, reversible click.
function generatedSlots(dir: string) {
	const out = new Map<string, Row>();
	const p = resolve(dir, "motion_graphics.json");
	if (!existsSync(p)) return out;
	try {
		const d = JSON.parse(readFileSync(p, "utf8"));
		for (const s of d.slots || []) if (s && s.ok && s.file) out.set(String(s.key), s);
	} catch {}
	return out;
}

function generatedCandidate(slot: Row, session: string) {
	const file = String(slot.file).replace(/\\/g, "/");
	return {
		candidate_id: "generated",
		generated: true,
		source: "hyperframes",
		asset_type: "video",
		file,
		url: fileToUrl(file, session),
		url_original: "",
		query: `generated · ${slot.flavor || "motion graphic"}`,
		thumb: "",
		width: null,
		height: null,
		in_point: 0,
		out_point: null,
	};
}

// A collector killed mid-write leaves a 0-byte shot_<n>.json; treat it as "no candidates yet".
function readCandidates(path: string): Row | null {
	if (!existsSync(path)) return null;
	try {
		const raw = readFileSync(path, "utf8");
		return raw.trim() ? JSON.parse(raw) : null;
	} catch {
		return null;
	}
}

export function pickerShots(res: ServerResponse, query: URLSearchParams) {
	const dir = sessionDir(query.get("session"));
	if (!dir) return json(res, 400, { error: "bad session" });
	const planPath = resolve(dir, "plan.json");
	if (!existsSync(planPath)) return json(res, 404, { error: "no plan.json" });
	const plan = JSON.parse(readFileSync(planPath, "utf8"));
	const session = String(query.get("session"));

	// Last writer wins, mirroring render's merge.
	const picked: Record<string, Row> = {};
	for (const e of feedRows(dir)) picked[String(e.shot_number)] = e;

	const candDir = resolve(dir, "assets", "candidates");
	const gen = generatedSlots(dir);
	const shots = (plan.shots || []).map((s: Row) => {
		const n = s.shot_number;
		const p = picked[String(n)];
		const g = gen.get(String(n));
		const sources: Row[] = (s.visual || {}).search_sources || [];
		return {
			shot_number: n,
			audio: s.audio || "",
			desc: (s.visual || {}).desc || "",
			type: (s.visual || {}).type || "",
			duration: Number(((s.end || 0) - (s.start || 0)).toFixed(2)),
			// The plan lists queries once per source and they're usually the same set.
			queries: [...new Set(sources.flatMap((e) => e.queries || []))],
			sources: [...new Set(sources.map((e) => e.source))],
			has_candidates: !!readCandidates(resolve(candDir, `shot_${n}.json`)) || !!g,
			generated: g ? { file: String(g.file).replace(/\\/g, "/"), flavor: g.flavor || "" } : null,
			user_picked: p ? p.visual_verdict === "user_picked" : false,
			picked: p ? { source: p.source, file: p.file, url: fileToUrl(p.file, session), ok: p.ok } : null,
		};
	});
	json(res, 200, { session, shots });
}

export function pickerCandidates(res: ServerResponse, query: URLSearchParams) {
	const dir = sessionDir(query.get("session"));
	if (!dir) return json(res, 400, { error: "bad session" });
	const session = String(query.get("session"));
	const p = resolve(dir, "assets", "candidates", `shot_${Number(query.get("shot"))}.json`);
	if (!p.startsWith(ROOT)) return json(res, 400, { error: "bad shot" });
	const gen = generatedSlots(dir).get(String(Number(query.get("shot"))));
	const m = readCandidates(p) || (gen ? { queries: [], sources: [], candidates: [] } : null);
	if (!m) return json(res, 404, { error: "no candidates — fetch first" });
	for (const c of m.candidates || []) c.url = fileToUrl(c.file, session);
	if (gen) {
		m.candidates = [generatedCandidate(gen, session), ...(m.candidates || []).filter((c: Row) => !c.generated)];
		m.generated = true;
	}
	json(res, 200, m);
}

// source_pool dedupes across shots, so never delete a file another shot still references.
function filesInUseElsewhere(dir: string, exceptShot: unknown) {
	const used = new Set<string>();
	const base = (f: unknown) => String(f || "").replace(/\\/g, "/").split("/").pop() as string;
	const picked: Record<string, Row> = {};
	for (const e of feedRows(dir)) picked[String(e.shot_number)] = e;
	for (const [k, e] of Object.entries(picked)) {
		if (k === String(exceptShot)) continue;
		if (e.file) used.add(base(e.file));
	}
	const candDir = resolve(dir, "assets", "candidates");
	if (existsSync(candDir)) {
		for (const f of readdirSync(candDir)) {
			const m = /^shot_(.+)\.json$/.exec(f);
			if (!m || m[1] === String(exceptShot)) continue;
			const mm = readCandidates(resolve(candDir, f));
			for (const c of (mm && mm.candidates) || []) if (c.file) used.add(base(c.file));
		}
	}
	return used;
}

function updateAssetsJson(dir: string, shot: unknown, row: Row) {
	const aj = resolve(dir, "assets.json");
	if (!existsSync(aj)) return;
	const d = JSON.parse(readFileSync(aj, "utf8"));
	d.shots = d.shots || {};
	d.shots[String(shot)] = row;
	d.shots_fetched = Object.values(d.shots as Record<string, Row>).filter((v) => v.ok).length;
	d.shots_failed = Object.keys(d.shots).length - d.shots_fetched;
	d.timestamp = new Date().toISOString();
	writeFileSync(aj, JSON.stringify(d, null, 2), "utf8");
}

export async function pickerPick(req: IncomingMessage, res: ServerResponse) {
	let body: Row;
	try {
		body = await readBody(req);
	} catch (e) {
		return json(res, 400, { error: String((e as Error).message || e) });
	}
	const dir = sessionDir(body.session);
	if (!dir) return json(res, 400, { error: "bad session" });
	const by = req.headers["x-esta-client"];
	const feed = resolve(dir, "assets_progress.jsonl");

	const manifestPath = resolve(dir, "assets", "candidates", `shot_${Number(body.shot)}.json`);
	if (!manifestPath.startsWith(ROOT)) return json(res, 404, { error: "no candidates for that shot" });
	const gen = generatedSlots(dir).get(String(Number(body.shot)));
	const m = readCandidates(manifestPath) || (gen ? { candidates: [] } : null);
	if (!m) return json(res, 404, { error: "no candidates for that shot" });
	const c =
		body.candidate_id === "generated" && gen
			? generatedCandidate(gen, body.session)
			: (m.candidates || []).find((x: Row) => x.candidate_id === body.candidate_id);
	if (!c) return json(res, 404, { error: "candidate not in manifest" });

	// Restoring a generated graphic replays the row the motion-graphics skill
	// wrote (it carries the real in/out points); only the verdict changes.
	if (c.generated) {
		const prior = feedRows(dir)
			.filter((e) => String(e.shot_number) === String(Number(body.shot)) && e.source === "hyperframes")
			.pop();
		if (prior) {
			const restored = { ...prior, visual_verdict: "user_picked", visual_confidence: 100 };
			noteSelfWrite(feed, by);
			appendFileSync(feed, JSON.stringify(restored) + "\n", "utf8");
			updateAssetsJson(dir, body.shot, restored);
			return json(res, 200, { ok: true, shot: body.shot, picked: restored, cleaned: 0, kept_shared: 0 });
		}
	}

	// Exactly tools/assets/schema.py:ShotAsset — the picker is a different way to choose, not a different contract.
	const row = {
		shot_number: Number(body.shot),
		ok: true,
		source: c.source,
		asset_type: c.asset_type,
		url: c.url_original || c.url || "",
		file: c.file,
		search_query: c.query || "",
		in_point: body.in_point != null ? Number(body.in_point) : c.in_point,
		out_point: body.out_point != null ? Number(body.out_point) : c.out_point,
		visual_verdict: "user_picked",
		visual_confidence: 100,
		error: "",
	};
	noteSelfWrite(feed, by);
	appendFileSync(feed, JSON.stringify(row) + "\n", "utf8");
	updateAssetsJson(dir, body.shot, row);

	const cleaned: string[] = [];
	const kept: string[] = [];
	if (body.cleanup !== false) {
		const inUse = filesInUseElsewhere(dir, body.shot);
		const base = (f: unknown) => String(f || "").replace(/\\/g, "/").split("/").pop() as string;
		// Candidates in one shot routinely share a file (several moments of one
		// video), so never delete the chosen file via a sibling.
		const chosenBase = base(c.file);
		for (const other of m.candidates || []) {
			if (other.candidate_id === c.candidate_id || other.generated) continue;
			const bn = base(other.file);
			if (bn === chosenBase || inUse.has(bn)) {
				kept.push(bn);
				continue;
			}
			const p = resolve(dir, "assets", "source_pool", bn);
			if (p.startsWith(ROOT) && existsSync(p)) {
				try {
					rmSync(p);
					cleaned.push(bn);
				} catch {}
			}
		}
		m.candidates = (m.candidates || []).filter((x: Row) => x.candidate_id === c.candidate_id);
		m.picked_at = new Date().toISOString();
		writeFileSync(manifestPath, JSON.stringify(m, null, 2), "utf8");
	}
	json(res, 200, { ok: true, shot: body.shot, picked: row, cleaned: cleaned.length, kept_shared: kept.length });
}

// In-flight collector runs keyed "<session>:<shot>"; the POST returns once the
// child is spawned so the user can keep working through the shot list.
type PickJob = { status: string; started: number; ended?: number; log: string };
const JOBS = new Map<string, PickJob>();
const jobKey = (session: unknown, shot: unknown) => `${session}:${Number(shot)}`;

export function pickerJobs(res: ServerResponse, query: URLSearchParams) {
	const session = query.get("session");
	const out: Record<string, unknown> = {};
	for (const [k, v] of JOBS) {
		if (!k.startsWith(`${session}:`)) continue;
		out[k.split(":").pop() as string] = {
			status: v.status,
			started: v.started,
			log: v.status === "error" ? v.log : undefined,
		};
	}
	json(res, 200, { jobs: out });
}

// Cached per session; the answer only moves when config.yaml or licensing changes.
const SOURCE_BANK = new Map<string, unknown>();

export function pickerSources(res: ServerResponse, query: URLSearchParams) {
	const session = query.get("session") || "";
	if (SOURCE_BANK.has(session)) return json(res, 200, SOURCE_BANK.get(session));
	const py = estaPython();
	if (!py) return json(res, 500, { error: "esta env python not found — set ESTA_PYTHON to its full path and restart the server" });
	const args = ["tools/assets/run.py", "sources"];
	if (session) args.push("--session", `sessions/${session}`);
	// shell:false: argv never reaches a command interpreter.
	const child = spawn(py, args, { cwd: REPO_ROOT, env: PY_ENV });
	let out = "";
	let err = "";
	child.stdout.on("data", (d) => (out += d));
	child.stderr.on("data", (d) => (err += d));
	child.on("error", (e) => json(res, 500, { error: String(e.message || e) }));
	child.on("close", (code) => {
		// conda/py can print warnings before the payload; take the last JSON line.
		const line = out.trim().split("\n").filter((l) => l.trim().startsWith("{")).pop();
		let parsed: Row | null = null;
		try {
			parsed = line ? JSON.parse(line) : null;
		} catch {}
		if (code !== 0 || !parsed || !parsed.ok) {
			return json(res, 500, { error: (parsed && parsed.error) || err.slice(-500) || `sources exited ${code}` });
		}
		SOURCE_BANK.set(session, parsed);
		json(res, 200, parsed);
	});
}

export async function pickerRefetch(req: IncomingMessage, res: ServerResponse) {
	let body: Row;
	try {
		body = await readBody(req);
	} catch (e) {
		return json(res, 400, { error: String((e as Error).message || e) });
	}
	const dir = sessionDir(body.session);
	if (!dir) return json(res, 400, { error: "bad session" });
	const key = jobKey(body.session, body.shot);
	if (JOBS.get(key)?.status === "running") return json(res, 409, { error: "already fetching this shot" });
	const py = estaPython();
	if (!py) return json(res, 500, { error: "esta env python not found — set ESTA_PYTHON to its full path and restart the server" });

	const args = [
		"tools/assets/run.py", "candidates",
		"--session", `sessions/${body.session}`,
		"--n", String(Number(body.shot)),
		"--per-source", String(Number(body.per_source) || 4),
	];
	if (body.queries) args.push("--queries", String(body.queries));
	if (body.sources) args.push("--sources", String(body.sources));

	// shell:false is load-bearing: queries carry spaces and `|`. PYTHONIOENCODING
	// because a console-less Python on Windows picks cp1252 and dies on non-ASCII.
	const child = spawn(py, args, { cwd: REPO_ROOT, env: PY_ENV });
	const job: PickJob = { status: "running", started: Date.now(), log: "" };
	JOBS.set(key, job);
	child.stdout.on("data", (d) => (job.log = (job.log + d).slice(-8000)));
	child.stderr.on("data", (d) => (job.log = (job.log + d).slice(-8000)));
	child.on("error", (e) => {
		job.status = "error";
		job.log += `\nspawn failed: ${e.message}`;
	});
	child.on("close", (code) => {
		job.status = code === 0 && !/"ok":\s*false/.test(job.log) ? "done" : "error";
		job.ended = Date.now();
	});
	json(res, 202, { ok: true, started: true, shot: Number(body.shot) });
}
