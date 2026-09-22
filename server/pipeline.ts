import { existsSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { spawnSync } from "node:child_process";
import { REPO_ROOT, sessionDir } from "./lib.ts";

// Mirrors tools/pipeline/conductor.py + validate_flow.py (the source of truth)
// and layers the UI gates on top: approvals and overrides, recorded under the
// "ui" key of pipeline.json. conductor.py round-trips unknown keys, so its own
// commands keep working on a v3 pipeline.json.

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Any = any;

const PIPE_DIR = resolve(REPO_ROOT, "tools", "pipeline");
const loadJson = (p: string) => JSON.parse(readFileSync(p, "utf8"));
export const contracts = () => loadJson(resolve(PIPE_DIR, "contracts.json"));
export const templates = () => loadJson(resolve(PIPE_DIR, "templates.json")).templates as Record<string, Any>;

export type Step = {
	order: number;
	skill: string;
	mode: string | null;
	token: string;
	needs: string[];
	produces: string[];
	parallel: boolean;
	status: string;
};

const stepToken = (s: Any) => (s.mode ? `${s.skill}:${s.mode}` : s.skill);

export function resolveStep(c: Any, token: string): { needs: string[]; produces: string[]; errors: string[] } {
	const [skillName, ...rest] = token.split(":");
	let mode = rest.join(":");
	const skill = c.skills[skillName];
	if (!skill) return { needs: [], produces: [], errors: [`unknown skill '${skillName}'`] };
	const baseNeeds = skill.needs ?? skill.base_needs ?? [];
	const baseProduces = skill.produces ?? skill.base_produces ?? [];
	const modes = skill.modes;
	if (modes) {
		mode = mode || skill.default_mode || "";
		if (!mode) return { needs: [], produces: [], errors: [`skill '${skillName}' requires a mode`] };
		const m = modes[mode];
		if (!m) return { needs: [], produces: [], errors: [`skill '${skillName}' has no mode '${mode}'`] };
		return {
			needs: m.needs ?? baseNeeds,
			produces: [...(m.produces ?? baseProduces), ...(m.produces_dirs ?? [])],
			errors: m.status === "not_built" ? [`${token}: mode is not_built`] : [],
		};
	}
	if (mode) return { needs: [], produces: [], errors: [`skill '${skillName}' takes no mode (got '${mode}')`] };
	return { needs: baseNeeds, produces: [...baseProduces, ...(skill.produces_dirs ?? [])], errors: [] };
}

function globToRegex(glob: string) {
	return new RegExp("^" + glob.replace(/[.+^${}()|\\]/g, "\\$&").replace(/\*/g, ".*").replace(/\?/g, ".") + "$");
}

// conductor._artifact_present: repo-level needs (a '/' that isn't a trailing-slash dir) count as satisfied.
export function artifactPresent(dir: string, artifact: string) {
	if (artifact.endsWith("/")) {
		const p = resolve(dir, artifact);
		return existsSync(p) && statSync(p).isDirectory();
	}
	if (artifact.includes("/")) return true;
	if (/[*?[]/.test(artifact)) {
		const re = globToRegex(artifact);
		try {
			return readdirSync(dir).some((f) => re.test(f));
		} catch {
			return false;
		}
	}
	return existsSync(resolve(dir, artifact));
}

function readRequirements(dir: string): Any {
	try {
		return loadJson(resolve(dir, "requirements.json"));
	} catch {
		return null;
	}
}

const exampleScriptsIsList = (req: Any) => Array.isArray(req?.example_scripts) && req.example_scripts.length > 0;

export function buildSteps(templateName: string, dir: string): Step[] {
	const tpl = templates()[templateName];
	if (!tpl) throw new Error(`unknown template '${templateName}'`);
	const c = contracts();
	const req = readRequirements(dir);
	const raw = tpl.steps.filter((s: Any) => s.when !== "example_scripts_is_list" || exampleScriptsIsList(req));
	return raw.map((s: Any, i: number) => {
		const token = stepToken(s);
		const { needs, produces, errors } = resolveStep(c, token);
		if (errors.length) throw new Error(`step '${token}': ${errors.join("; ")}`);
		return { order: i + 1, skill: s.skill, mode: s.mode ?? null, token, needs, produces, parallel: Boolean(s.parallel), status: "pending" };
	});
}

// ── Stage rail ──────────────────────────────────────────────────────────────

export type Checkpoint = "requirements" | "script" | "tagged_script" | "plan";

export const STAGES: Array<{ id: string; label: string; skills: string[]; checkpoint?: Checkpoint }> = [
	{ id: "requirements", label: "Requirements", skills: ["requirements"], checkpoint: "requirements" },
	{ id: "voice-profile", label: "Voice profile", skills: ["voice-profiler"] },
	{ id: "research", label: "Research", skills: ["research"] },
	{ id: "script", label: "Script", skills: ["scriptwriter"], checkpoint: "script" },
	{ id: "voice", label: "Voice", skills: ["audio"] },
	{ id: "timestamps", label: "Timestamps", skills: ["timestamps"] },
	{ id: "style", label: "Style", skills: ["style-analysis"] },
	{ id: "plan", label: "Plan", skills: ["plan"], checkpoint: "plan" },
	{ id: "assets", label: "Assets", skills: ["assets", "motion-graphics", "ai-video"] },
	{ id: "edit", label: "Edit", skills: ["render"] },
];

export const stageOfSkill = (skill: string) => STAGES.find((s) => s.skills.includes(skill))?.id ?? null;

const CHECKPOINT_OF_SKILL: Record<string, Checkpoint> = { requirements: "requirements", scriptwriter: "script", plan: "plan" };

export type UiState = {
	approvals: Partial<Record<Checkpoint, { at: string; by: string }>>;
	overrides: Record<string, { at: string; missing: string[]; pendingApprovals: string[] }>;
};

export function readPipeline(dir: string): Any | null {
	const p = resolve(dir, "pipeline.json");
	if (!existsSync(p)) return null;
	try {
		return loadJson(p);
	} catch {
		return null;
	}
}

function writePipeline(dir: string, pipe: Any) {
	writeFileSync(resolve(dir, "pipeline.json"), JSON.stringify(pipe, null, 2), "utf8");
}

// Approvals and overrides need a pipeline.json to live in. A session without
// one gets the canonical standard-vo rails, built by conductor.py itself.
export function ensurePipeline(dir: string, template = "standard-vo"): Any {
	const existing = readPipeline(dir);
	if (existing) return existing;
	const r = spawnSync("python", ["tools/pipeline/conductor.py", "build", "--session", dir, "--template", template], {
		cwd: REPO_ROOT,
		encoding: "utf8",
	});
	const pipe = readPipeline(dir);
	if (!pipe) throw new Error(`conductor build failed: ${(r.stdout || r.stderr || "").trim()}`);
	return pipe;
}

export function uiState(pipe: Any | null): UiState {
	return { approvals: pipe?.ui?.approvals ?? {}, overrides: pipe?.ui?.overrides ?? {} };
}

export function mutateUi(dir: string, fn: (ui: UiState, pipe: Any) => void) {
	const pipe = ensurePipeline(dir);
	const ui = uiState(pipe);
	fn(ui, pipe);
	pipe.ui = ui;
	writePipeline(dir, pipe);
}

export function rebuildPipeline(dir: string, template: string) {
	const prior = readPipeline(dir);
	const r = spawnSync("python", ["tools/pipeline/conductor.py", "build", "--session", dir, "--template", template], {
		cwd: REPO_ROOT,
		encoding: "utf8",
	});
	const pipe = readPipeline(dir);
	if (r.status !== 0 || !pipe) throw new Error((r.stdout || r.stderr || "conductor build failed").trim());
	// A template change must not silently drop approvals already given.
	if (prior?.ui) {
		pipe.ui = prior.ui;
		writePipeline(dir, pipe);
	}
	return pipe;
}

// Custom orders go through validate_flow.py so they're rejected with its exact message.
export function setCustomFlow(dir: string, tokens: string[]) {
	const r = spawnSync("python", ["tools/pipeline/validate_flow.py", ...tokens], { cwd: REPO_ROOT, encoding: "utf8" });
	if (r.status !== 0) throw new Error((r.stdout || r.stderr || "invalid flow").trim());
	const c = contracts();
	const prior = readPipeline(dir);
	const steps: Step[] = tokens.map((token, i) => {
		const { needs, produces } = resolveStep(c, token);
		const [skill, mode] = token.split(":");
		return { order: i + 1, skill, mode: mode ?? null, token, needs, produces, parallel: skill === "style-analysis", status: "pending" };
	});
	const pipe = {
		session_id: dir.split(/[\\/]/).pop(),
		created_at: new Date().toISOString(),
		template: "custom",
		goal: c.goal_artifact,
		approved: false,
		steps,
		...(prior?.ui ? { ui: prior.ui } : {}),
	};
	writePipeline(dir, pipe);
	return pipe;
}

export type StepState = Step & {
	state: "skipped" | "done" | "ready" | "blocked";
	missing: string[];
	pendingApprovals: Checkpoint[];
	locked: boolean;
	overridden: boolean;
};

export type RunInfo = { running: Set<string>; failed: Set<string> };

export function computeState(sessionId: string, run: RunInfo) {
	const dir = sessionDir(sessionId);
	if (!dir || !existsSync(dir)) throw new Error("no such session");
	const pipe = readPipeline(dir);
	const req = readRequirements(dir);
	const ui = uiState(pipe);
	let steps: Step[] = pipe?.steps ?? buildSteps("standard-vo", dir);

	// voice-profiler re-enters the flow when samples are added after the pipeline was built.
	if (exampleScriptsIsList(req) && !steps.some((s) => s.skill === "voice-profiler")) {
		const { needs, produces } = resolveStep(contracts(), "voice-profiler");
		steps = [steps[0], { order: 1.5, skill: "voice-profiler", mode: null, token: "voice-profiler", needs, produces, parallel: false, status: "pending" }, ...steps.slice(1)];
	}

	const approved = (cp: Checkpoint) => Boolean(ui.approvals[cp]);
	const done = (s: Step) => s.produces.length > 0 && s.produces.every((a) => artifactPresent(dir, a));
	const skipped = (s: Step) => s.status === "skipped" || (s.skill === "scriptwriter" && req?.skip_scriptwriter === true);

	const stepStates: StepState[] = steps.map((s, i) => {
		const isSkipped = skipped(s);
		const isDone = !isSkipped && done(s);
		const missing = s.needs.filter((a) => !artifactPresent(dir, a));
		// Parallel steps only need requirements.json, so only the intake checkpoint gates them.
		const upstream = s.parallel ? steps.filter((u) => u.skill === "requirements") : steps.slice(0, i);
		const pendingApprovals = upstream
			.filter((u) => !skipped(u) && CHECKPOINT_OF_SKILL[u.skill])
			.map((u) => CHECKPOINT_OF_SKILL[u.skill])
			.filter((cp) => !approved(cp));
		const wouldLock = missing.length > 0 || pendingApprovals.length > 0;
		const overridden = wouldLock && Boolean(ui.overrides[s.token]);
		return {
			...s,
			state: isSkipped ? "skipped" : isDone ? "done" : missing.length ? "blocked" : "ready",
			missing,
			pendingApprovals: [...new Set(pendingApprovals)],
			locked: wouldLock && !overridden && !isDone && !isSkipped,
			overridden,
		};
	});

	// conductor.next_step, verbatim semantics: disk only, no approvals.
	let conductorNext: Any = { done: true, goal: pipe?.goal ?? "*.openreel.json" };
	const pending = stepStates.filter((s) => s.state !== "skipped" && s.state !== "done");
	const readyStep = pending.find((s) => s.state === "ready");
	if (readyStep) conductorNext = { next: readyStep.token, skill: readyStep.skill, mode: readyStep.mode, parallel: readyStep.parallel, needs: readyStep.needs, produces: readyStep.produces };
	else if (pending.length) conductorNext = { blocked: pending[0].token, missing: pending[0].missing };
	if (!pipe) conductorNext = { ...conductorNext, fallback: "no pipeline.json — canonical standard-vo order" };

	const nextToken = conductorNext.next ?? conductorNext.blocked ?? null;
	const taggedExists = existsSync(resolve(dir, "script.tagged.md"));

	const stages = STAGES.map((st) => {
		const own = stepStates.filter((s) => st.skills.includes(s.skill));
		const inFlow = own.length > 0;
		const allDone = inFlow && own.every((s) => s.state === "done" || s.state === "skipped");
		const allSkipped = inFlow && own.every((s) => s.state === "skipped");
		const current = own.find((s) => s.state !== "done" && s.state !== "skipped") ?? null;
		const cp = st.checkpoint;
		const needsApproval = Boolean(cp) && allDone && !allSkipped && !approved(cp as Checkpoint);
		const voiceNeedsTagApproval = st.id === "voice" && taggedExists && !approved("tagged_script") && !allDone;
		let badge: string;
		if (run.running.has(st.id)) badge = "running";
		else if (!inFlow) badge = "not-in-flow";
		else if (allSkipped) badge = "skipped";
		else if (allDone && !needsApproval) badge = "done";
		else if (run.failed.has(st.id)) badge = "failed";
		else if (needsApproval || voiceNeedsTagApproval) badge = "review";
		else if (own.some((s) => s.overridden)) badge = "overridden";
		else if (current?.locked) badge = "locked";
		else badge = "idle";
		return {
			id: st.id,
			label: st.label,
			checkpoint: cp ?? null,
			approval: cp ? (ui.approvals[cp] ?? null) : null,
			inFlow,
			badge,
			isNext: own.some((s) => s.token === nextToken),
			steps: own.map((s) => s.token),
			current: current?.token ?? null,
			locked: current?.locked ?? false,
			missing: current?.missing ?? [],
			pendingApprovals: current?.pendingApprovals ?? [],
			overridden: own.some((s) => s.overridden),
		};
	});

	return {
		session: sessionId,
		hasPipeline: Boolean(pipe),
		template: pipe?.template ?? null,
		conductorApproved: pipe?.approved ?? false,
		conductorNext,
		requirements: req ? { topic: req.topic, skip_scriptwriter: req.skip_scriptwriter, example_scripts_is_list: exampleScriptsIsList(req) } : null,
		approvals: ui.approvals,
		overrides: ui.overrides,
		taggedScript: { exists: taggedExists, approved: approved("tagged_script") },
		checkpointFiles: {
			requirements: existsSync(resolve(dir, "requirements.json")),
			script: existsSync(resolve(dir, "script.md")),
			tagged_script: taggedExists,
			plan: existsSync(resolve(dir, "plan.json")),
		} as Record<Checkpoint, boolean>,
		steps: stepStates,
		stages,
	};
}

export type PipelineState = ReturnType<typeof computeState>;
