import { spawn, spawnSync } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { randomUUID } from "node:crypto";
import { PY_ENV, REPO_ROOT, STATE_DIR } from "./lib.ts";
import { publish } from "./hub.ts";

export type JobStatus = "running" | "done" | "failed" | "cancelled" | "interrupted";
export type JobSpec = {
	session: string;
	stage: string;
	action: string;
	label: string;
	kind: "tool" | "skill";
	cmd: string;
	args: string[];
	// Artifacts whose presence decides the outcome of a job the server lost track of.
	produces?: string[];
};
export type Job = JobSpec & {
	id: string;
	status: JobStatus;
	pid: number | null;
	startedAt: number;
	endedAt: number | null;
	exitCode: number | null;
	error: string | null;
	cost: number | null;
	progress: { done: number; total: number; label: string } | null;
	detached?: boolean;
};

const JOB_DIR = resolve(STATE_DIR, "jobs");
const jobs = new Map<string, Job>();
const cancelled = new Set<string>();

function save(job: Job) {
	writeFileSync(resolve(JOB_DIR, `${job.id}.json`), JSON.stringify(job, null, 2), "utf8");
	publish({ ch: "job", session: job.session, data: { type: "update", job } });
}

function log(job: Job, text: string) {
	appendFileSync(resolve(JOB_DIR, `${job.id}.log`), text, "utf8");
	publish({ ch: "job", session: job.session, data: { type: "log", id: job.id, text } });
}

export function isAlive(pid: number) {
	try {
		process.kill(pid, 0);
		return true;
	} catch {
		return false;
	}
}

// conda run and claude spawn grandchildren; killing only the direct child
// leaves the real worker (python, kaggle poller) running.
export function killTree(pid: number) {
	if (process.platform === "win32") spawnSync("taskkill", ["/pid", String(pid), "/T", "/F"], { windowsHide: true });
	else {
		try {
			process.kill(-pid, "SIGTERM");
		} catch {
			process.kill(pid, "SIGTERM");
		}
	}
}

// Restart recovery: a job recorded as running whose process is gone was
// interrupted; one still alive is detached (its output is lost) and resolves
// from disk when it exits.
export function loadJobs(artifactPresent: (session: string, a: string) => boolean) {
	mkdirSync(JOB_DIR, { recursive: true });
	for (const f of readdirSync(JOB_DIR)) {
		if (!f.endsWith(".json")) continue;
		try {
			const job: Job = JSON.parse(readFileSync(resolve(JOB_DIR, f), "utf8"));
			jobs.set(job.id, job);
			if (job.status !== "running") continue;
			if (job.pid && isAlive(job.pid)) {
				job.detached = true;
				const poll = setInterval(() => {
					if (job.status === "running" && job.pid && isAlive(job.pid)) return;
					clearInterval(poll);
					if (job.status !== "running") return;
					const ok = (job.produces || []).length > 0 && (job.produces || []).every((a) => artifactPresent(job.session, a));
					job.status = ok ? "done" : "interrupted";
					job.endedAt = Date.now();
					save(job);
				}, 5000);
			} else {
				job.status = "interrupted";
				job.endedAt = job.endedAt || Date.now();
				job.error = "backend restarted while this job was running";
				save(job);
			}
		} catch {
			/* corrupt record: ignore */
		}
	}
}

export function listJobs(session: string | null) {
	return [...jobs.values()]
		.filter((j) => !session || j.session === session)
		.sort((a, b) => b.startedAt - a.startedAt);
}

export function getJob(id: string) {
	return jobs.get(id);
}

export function jobLog(id: string) {
	const p = resolve(JOB_DIR, `${id}.log`);
	return existsSync(p) ? readFileSync(p, "utf8") : "";
}

export function activeJobs(session: string, stage?: string) {
	return listJobs(session).filter((j) => j.status === "running" && (!stage || j.stage === stage));
}

// Skill jobs emit stream-json; the log shows what a human watching the terminal would see.
function renderSkillEvent(job: Job, line: string): string {
	let ev: Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any
	try {
		ev = JSON.parse(line);
	} catch {
		return line + "\n";
	}
	if (ev.type === "assistant") {
		const parts: string[] = [];
		for (const c of ev.message?.content || []) {
			if (c.type === "text" && c.text) parts.push(c.text);
			if (c.type === "tool_use") parts.push(`> ${c.name} ${JSON.stringify(c.input).slice(0, 300)}`);
		}
		return parts.length ? parts.join("\n") + "\n" : "";
	}
	if (ev.type === "result") {
		job.cost = ev.total_cost_usd ?? null;
		if (ev.is_error) job.error = String(ev.result || "skill failed").slice(0, 500);
		return `\n[result] ${ev.subtype || ""} cost $${(ev.total_cost_usd ?? 0).toFixed(3)}\n`;
	}
	return "";
}

export function startJob(spec: JobSpec): Job {
	mkdirSync(JOB_DIR, { recursive: true });
	const job: Job = {
		...spec,
		id: `${Date.now().toString(36)}-${randomUUID().slice(0, 6)}`,
		status: "running",
		pid: null,
		startedAt: Date.now(),
		endedAt: null,
		exitCode: null,
		error: null,
		cost: null,
		progress: null,
	};
	jobs.set(job.id, job);
	log(job, `$ ${spec.cmd} ${spec.args.map((a) => (/\s/.test(a) ? JSON.stringify(a) : a)).join(" ")}\n`);
	let child;
	try {
		child = spawn(spec.cmd, spec.args, { cwd: REPO_ROOT, env: PY_ENV, windowsHide: true, detached: true });
	} catch (e) {
		job.status = "failed";
		job.error = `spawn failed: ${(e as Error).message}`;
		job.endedAt = Date.now();
		save(job);
		return job;
	}
	job.pid = child.pid ?? null;
	save(job);
	let buf = "";
	child.stdout?.on("data", (d: Buffer) => {
		if (spec.kind !== "skill") return log(job, d.toString("utf8"));
		buf += d.toString("utf8");
		let nl;
		let out = "";
		while ((nl = buf.indexOf("\n")) >= 0) {
			out += renderSkillEvent(job, buf.slice(0, nl).trim());
			buf = buf.slice(nl + 1);
		}
		if (out) log(job, out);
	});
	child.stderr?.on("data", (d: Buffer) => log(job, d.toString("utf8")));
	child.on("error", (e) => {
		job.error = `spawn failed: ${e.message}`;
		log(job, `\n${job.error}\n`);
	});
	child.on("close", (code) => {
		job.exitCode = code;
		job.endedAt = Date.now();
		if (cancelled.has(job.id)) job.status = "cancelled";
		else if (code === 0 && !job.error) job.status = "done";
		else {
			job.status = "failed";
			job.error = job.error || `exited with code ${code}`;
		}
		log(job, `\n[${job.status}] exit ${code}\n`);
		save(job);
		for (const fn of endListeners) fn(job);
	});
	return job;
}

const endListeners = new Set<(job: Job) => void>();
export function onJobEnd(fn: (job: Job) => void) {
	endListeners.add(fn);
}

export function cancelJob(id: string) {
	const job = jobs.get(id);
	if (!job || job.status !== "running" || !job.pid) return false;
	cancelled.add(id);
	killTree(job.pid);
	if (job.detached) {
		job.status = "cancelled";
		job.endedAt = Date.now();
		save(job);
	}
	return true;
}

export function retryJob(id: string) {
	const job = jobs.get(id);
	if (!job || job.status === "running") return null;
	const { session, stage, action, label, kind, cmd, args, produces } = job;
	return startJob({ session, stage, action, label, kind, cmd, args, produces });
}

export function setProgress(job: Job, progress: Job["progress"]) {
	if (JSON.stringify(job.progress) === JSON.stringify(progress)) return;
	job.progress = progress;
	save(job);
}
