import type { IncomingMessage, ServerResponse } from "node:http";
import { existsSync, readFileSync } from "node:fs";
import { basename, resolve } from "node:path";
import { json, readBody, sessionDir } from "./lib.ts";
import { activeJobs, startJob } from "./jobs.ts";

// M5 inspo match: the Plan stage's score card reads both reports, Re-score runs
// score.py as a job (no Claude), and Build fetches the colour grades per clip.

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Row = Record<string, any>;

const readJson = (p: string): Row | null => {
	try {
		return JSON.parse(readFileSync(p, "utf8"));
	} catch {
		return null;
	}
};

export function matchReports(res: ServerResponse, session: string) {
	const dir = sessionDir(session);
	if (!dir || !existsSync(dir)) return json(res, 404, { error: "no such session" });
	const running = activeJobs(session).filter((j) => j.action.startsWith("match")).map((j) => j.action);
	json(res, 200, { plan: readJson(resolve(dir, "match_plan.json")), final: readJson(resolve(dir, "match_final.json")), running });
}

export async function matchRescore(req: IncomingMessage, res: ServerResponse, session: string) {
	const dir = sessionDir(session);
	if (!dir || !existsSync(dir)) return json(res, 404, { error: "no such session" });
	const body = await readBody(req).catch(() => ({}) as Row);
	const stage = body.stage === "final" ? "final" : "plan";
	const action = `match-rescore-${stage}`;
	if (activeJobs(session).some((j) => j.action === action)) return json(res, 409, { error: "already scoring" });
	const job = startJob({
		session,
		stage: stage === "final" ? "edit" : "plan",
		action,
		label: `Re-score ${stage} against the inspo`,
		kind: "tool",
		cmd: "python",
		args: ["tools/match/score.py", "--session", `sessions/${session}`, "--stage", stage, "--note", "re-score"],
		produces: [`match_${stage}.json`],
	});
	json(res, 202, { ok: true, job });
}

// The side-by-side review page tools/match/review.py writes after every score.
export function matchReview(res: ServerResponse, session: string) {
	const dir = sessionDir(session);
	const page = dir ? resolve(dir, "match_review.html") : "";
	if (!page || !existsSync(page)) return json(res, 404, { error: "no review page yet: score the plan first" });
	res.writeHead(200, { "Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store" });
	res.end(readFileSync(page));
}

// match_grades.json keys grades by clip (file name + in point), so they
// survive renumbering; Build needs them by the clip ids render gives shots.
export function matchGrades(res: ServerResponse, session: string) {
	const dir = sessionDir(session);
	if (!dir) return json(res, 400, { error: "bad session" });
	const grades = readJson(resolve(dir, "match_grades.json"))?.clips ?? {};
	const rows: Record<string, Row> = {};
	for (const [k, v] of Object.entries(readJson(resolve(dir, "assets.json"))?.shots ?? {})) rows[k] = v as Row;
	const feed = resolve(dir, "assets_progress.jsonl");
	if (existsSync(feed)) {
		for (const line of readFileSync(feed, "utf8").split("\n")) {
			try {
				const r = JSON.parse(line);
				if (r.shot_number != null) rows[String(r.shot_number)] = r;
			} catch {}
		}
	}
	const out: Record<string, string> = {};
	for (const [n, r] of Object.entries(rows)) {
		if (!r.ok || !r.file) continue;
		const key = `${basename(String(r.file).replace(/\\/g, "/"))}|${Number(r.in_point || 0).toFixed(2)}`;
		if (grades[key]) out[`clip-shot-${n}`] = JSON.stringify(grades[key].grade);
	}
	json(res, 200, { grades: out });
}
