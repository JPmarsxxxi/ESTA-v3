import { existsSync, readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { homedir } from "node:os";
import { spawnSync } from "node:child_process";
import { REPO_ROOT, claudeBin } from "./lib.ts";
import type { PipelineState } from "./pipeline.ts";
import type { JobSpec } from "./jobs.ts";

// Every button in a stage workspace. Tool actions shell out to the same CLIs
// the v2 skills call (conda run for the esta env, system python for the Kaggle
// lanes). Skill actions run the skill as one scoped headless `claude -p` job.

export type Param = { name: string; label: string; kind: "select" | "text"; options?: string[]; optional?: boolean };
export type Action = {
	id: string;
	stage: string;
	label: string;
	hint?: string;
	kind: "tool" | "skill";
	// The pipeline step whose gate this action obeys.
	step?: string | string[];
	needs?: string[];
	requiresApproval?: "tagged_script";
	python?: "esta" | "system";
	params?: Param[];
	args: (p: Record<string, string>, session: string) => string[];
	produces?: string[];
	then?: string;
	progress?: "timestamps" | "assets" | "plan";
	warn?: string;
};

const S = (session: string) => `sessions/${session}`;

function configValue(key: string, fallback: string) {
	try {
		const m = new RegExp(`^${key}:\\s*([^#\\s]+)`, "m").exec(readFileSync(resolve(REPO_ROOT, "config.yaml"), "utf8"));
		return m ? m[1].replace(/["']/g, "") : fallback;
	} catch {
		return fallback;
	}
}

export function voiceSamples() {
	try {
		return readdirSync(resolve(REPO_ROOT, "voice_samples")).filter((f) => /\.(wav|mp3|m4a)$/i.test(f));
	} catch {
		return [];
	}
}

const HEADLESS =
	"You are running headless from the ESTA v3 UI as a single background job: nobody can reply to you. " +
	"Do not ask questions; use the skill's documented defaults and what is in the session files. " +
	"Run long commands in the foreground (never run_in_background), since this process ends when you finish. " +
	"Where the skill asks for user approval or a paste-back, write the artifact and stop: the UI owns approvals. " +
	"Do not advance to the next pipeline step.";

const skill = (name: string, extra = "") => (_p: Record<string, string>, session: string) => [
	"-p",
	`Run the ${name} skill for session ${S(session)} (session id ${session}). ${extra}\n\n${HEADLESS}`,
	"--output-format", "stream-json",
	"--verbose",
	"--permission-mode", "bypassPermissions",
];

const sample: Param = { name: "sample", label: "Voice sample", kind: "select", options: [] };

export const ACTIONS: Action[] = [
	{ id: "voice-profiler", stage: "voice-profile", label: "Build voice profile", kind: "skill", step: "voice-profiler", args: skill("voice-profiler"), produces: ["voice_profile.md"] },
	{ id: "research", stage: "research", label: "Run research", hint: "Append-only; re-run any time to deepen.", kind: "skill", step: "research", args: skill("research"), produces: ["research.json"] },
	{
		id: "scriptwriter", stage: "script", label: "Draft script", kind: "skill", step: "scriptwriter:author",
		args: skill("scriptwriter", "Mode: author. Write talking points and the full draft, run the humanizer, and save the humanized draft as script.md plus script_metadata.json; the user finalizes it in the UI."),
		produces: ["script.md", "script_metadata.json"],
	},
	{
		id: "arranger", stage: "script", label: "Arrange from audio pool", kind: "skill", step: "scriptwriter:arranger",
		args: skill("scriptwriter", "Mode: arranger (found-audio flow). Write script.md and arrangement.json from the analysed pool."),
		produces: ["script.md", "arrangement.json"],
	},
	{
		id: "tag-script", stage: "voice", label: "Tag script for delivery", hint: "Claude writes script.tagged.md (emotion, stress, pauses), then tag-check.",
		kind: "skill", step: "audio:clone", params: [sample],
		args: (p, session) => skill("audio", `Expressive clone path, steps up to and including tag-check only: write script.tagged.md from script.md, then run tag-check with --sample voice_samples/${p.sample}. Stop before generation.`)(p, session),
		produces: ["script.tagged.md", "voice_script.json"],
	},
	{
		id: "tag-check", stage: "voice", label: "Re-run tag-check", kind: "tool", python: "esta", step: "audio:clone", needs: ["script.tagged.md"], params: [sample],
		args: (p, s) => ["tools/audio/run.py", "tag-check", "--session", S(s), "--sample", `voice_samples/${p.sample}`], produces: ["voice_script.json"],
	},
	{
		id: "expressive", stage: "voice", label: "Generate voice (IndexTTS2 on Kaggle)", hint: "~8 min on Kaggle's free T4. Leave lines blank to voice every line.",
		kind: "tool", python: "system", step: "audio:clone", needs: ["voice_script.json"], requiresApproval: "tagged_script",
		params: [{ name: "only", label: "Only lines (e.g. L04,L07)", kind: "text", optional: true }],
		args: (p, s) => ["tools/audio/run.py", "expressive", "--session", S(s), ...(p.only ? ["--only", p.only] : [])], then: "stitch",
	},
	{ id: "stitch", stage: "voice", label: "Stitch lines into audio.wav", kind: "tool", python: "esta", step: "audio:clone", needs: ["voice_script.json"], requiresApproval: "tagged_script", args: (_p, s) => ["tools/audio/run.py", "stitch", "--session", S(s)], produces: ["audio.wav", "audio_metadata.json"] },
	{
		id: "xtts", stage: "voice", label: "Legacy XTTS clone", kind: "tool", python: "esta", step: "audio:clone", params: [sample],
		warn: "XTTS is under the Coqui CPML licence: non-commercial only. Never use it for a monetised video.",
		args: (p, s) => ["tools/audio/run.py", "xtts", "--session", S(s), "--sample", `voice_samples/${p.sample}`, "--speed", "1.0", ...(configValue("gpu_available", "false") === "true" ? ["--gpu"] : [])],
		produces: ["audio.wav", "audio_metadata.json"],
	},
	{ id: "validate-audio", stage: "voice", label: "Validate audio.wav", kind: "tool", python: "esta", needs: ["audio.wav"], args: (_p, s) => ["tools/audio/run.py", "validate", "--path", `${S(s)}/audio.wav`] },
	{ id: "found-fetch", stage: "voice", label: "Fetch found-audio pool", kind: "skill", step: "audio:found-fetch", args: skill("audio", "Mode: found-fetch. Pick short keyword queries from requirements.json and research.json and build the pool."), produces: ["audio_pool.json"] },
	{ id: "analyze-pool", stage: "voice", label: "Analyze pool", kind: "tool", python: "esta", step: "audio:analyze-pool", args: (_p, s) => ["tools/audio/run.py", "analyze-pool", "--session", S(s)], produces: ["audio_pool_analysis.json"] },
	{ id: "assemble", stage: "voice", label: "Assemble audio.wav", kind: "tool", python: "esta", step: "audio:assemble", args: (_p, s) => ["tools/audio/run.py", "assemble", "--session", S(s)], produces: ["audio.wav", "audio_metadata.json"] },
	{
		id: "transcribe", stage: "timestamps", label: "Transcribe (faster-whisper)", kind: "tool", python: "esta", step: "timestamps",
		args: (_p, s) => ["tools/timestamps/run.py", "transcribe", "--session", S(s), "--model", configValue("whisper_model", "small")],
		produces: ["timestamps.json"], then: "reconcile", progress: "timestamps",
	},
	{ id: "reconcile", stage: "timestamps", label: "Reconcile plan timing", kind: "tool", python: "esta", needs: ["timestamps.json", "plan.json"], args: (_p, s) => ["tools/timestamps/run.py", "reconcile", "--session", S(s)] },
	{ id: "style-analysis", stage: "style", label: "Analyse reference style", hint: "Downloads reference clips, extracts frames, then synthesises style_analysis.json.", kind: "skill", step: "style-analysis", args: skill("style-analysis"), produces: ["style_analysis.json"] },
	{ id: "plan", stage: "plan", label: "Generate plan (bulk)", kind: "skill", step: "plan", args: skill("plan", "Mode: bulk. Stop after plan.json is written and reconciled; do not run render or assets."), produces: ["plan.json"], progress: "plan" },
	{ id: "early-render", stage: "plan", label: "Early render (placeholders + VO + subs)", kind: "tool", python: "esta", needs: ["plan.json"], args: (_p, s) => ["tools/render/run.py", "build", "--session", S(s)] },
	{ id: "fetch-assets", stage: "assets", label: "Fetch all shots (bulk)", kind: "tool", python: "esta", step: "assets", args: (_p, s) => ["tools/assets/run.py", "fetch", "--session", S(s)], produces: ["assets.json"], progress: "assets" },
	{ id: "motion-graphics", stage: "assets", label: "Generate motion graphics", kind: "skill", step: "motion-graphics", args: skill("motion-graphics"), produces: ["motion_graphics.json"] },
	{
		id: "genvideo-push", stage: "assets", label: "AI video: push to Kaggle", kind: "tool", python: "system", needs: ["plan.json"],
		params: [{ name: "seed", label: "Seed from fetched frames", kind: "select", options: ["no", "yes"] }],
		args: (p, s) => ["tools/genvideo/run.py", "push", "--session", S(s), ...(p.seed === "yes" ? ["--seed-from-assets"] : [])],
	},
	{ id: "genvideo-status", stage: "assets", label: "AI video: status", kind: "tool", python: "system", needs: ["plan.json"], args: (_p, s) => ["tools/genvideo/run.py", "status", "--session", S(s)] },
	{ id: "genvideo-apply", stage: "assets", label: "AI video: apply clips", kind: "tool", python: "system", needs: ["plan.json"], args: (_p, s) => ["tools/genvideo/run.py", "apply", "--session", S(s)], produces: ["gen_video.json"] },
	{ id: "sfx", stage: "edit", label: "Fulfil plan SFX", kind: "tool", python: "esta", needs: ["plan.json", "timestamps.json"], args: (_p, s) => ["tools/audio/sfx_from_plan.py", "--session", S(s)] },
	{ id: "tighten", stage: "edit", label: "Tighten dead air", kind: "tool", python: "esta", needs: ["audio.wav", "timestamps.json"], args: (_p, s) => ["tools/audio/tighten.py", "--session", S(s)] },
	{ id: "mix", stage: "edit", label: "Mix + bake loudness", kind: "tool", python: "esta", needs: ["audio.wav"], args: (_p, s) => ["tools/audio/mix.py", "--session", S(s), "--bake"] },
	{ id: "render", stage: "edit", label: "Final render", kind: "tool", python: "esta", step: "render", args: (_p, s) => ["tools/render/run.py", "build", "--session", S(s)], produces: ["*.openreel.json"] },
	{ id: "proxies", stage: "edit", label: "Generate editing proxies", kind: "tool", python: "esta", needs: ["plan.json"], args: (_p, s) => ["tools/media/proxy.py", "generate", "--session", S(s)] },
];

// Python stages need the esta env; checked like v2 skills do (`conda env list`).
let condaExe: string | null | undefined;
export function conda(): string | null {
	if (condaExe !== undefined) return condaExe;
	const tries = [
		process.env.CONDA_EXE,
		"C:\\ProgramData\\anaconda3\\Scripts\\conda.exe",
		resolve(homedir(), "anaconda3", "Scripts", "conda.exe"),
		resolve(homedir(), "miniconda3", "Scripts", "conda.exe"),
		resolve(homedir(), "anaconda3", "bin", "conda"),
		resolve(homedir(), "miniconda3", "bin", "conda"),
	].filter((p): p is string => Boolean(p));
	condaExe = tries.find((p) => existsSync(p)) || null;
	return condaExe;
}

let preflightCache: { esta: boolean; conda: boolean; claude: string; checkedAt: number } | null = null;
export function preflight(refresh = false) {
	if (preflightCache && !refresh) return preflightCache;
	const c = conda();
	let esta = false;
	if (c) {
		const r = spawnSync(c, ["env", "list"], { encoding: "utf8", windowsHide: true });
		esta = /^esta\s/m.test(r.stdout || "");
	}
	preflightCache = { esta, conda: Boolean(c), claude: claudeBin(), checkedAt: Date.now() };
	return preflightCache;
}

export function buildJob(action: Action, session: string, params: Record<string, string>): JobSpec {
	const args = action.args(params, session);
	const base = { session, stage: action.stage, action: action.id, label: action.label, kind: action.kind, produces: action.produces };
	if (action.kind === "skill") return { ...base, cmd: claudeBin(), args };
	if (action.python === "system") return { ...base, cmd: "python", args };
	return { ...base, cmd: conda() || "conda", args: ["run", "--no-capture-output", "-n", "esta", "python", ...args] };
}

// Why an action can't run right now, or null. Force on the stage bypasses gate
// reasons (recorded as an override), never missing-env reasons.
export function actionBlock(action: Action, state: PipelineState, present: (a: string) => boolean) {
	if (action.python === "esta" && !preflight().esta) return { reason: "The esta conda env is missing — run `.\\setup.ps1` once to create it.", forceable: false };
	const steps = ([] as string[]).concat(action.step ?? []);
	const stepStates = state.steps.filter((s) => steps.includes(s.token));
	if (steps.length && !stepStates.length) return { reason: `Not part of this session's flow (${steps.join(", ")}).`, forceable: false };
	const locked = stepStates.find((s) => s.locked);
	if (locked) {
		const parts = [];
		if (locked.missing.length) parts.push(`needs ${locked.missing.join(", ")}`);
		if (locked.pendingApprovals.length) parts.push(`awaiting approval: ${locked.pendingApprovals.join(", ")}`);
		return { reason: parts.join("; "), forceable: true };
	}
	const missing = (action.needs ?? []).filter((a) => !present(a));
	if (missing.length) return { reason: `needs ${missing.join(", ")}`, forceable: false };
	if (action.requiresApproval === "tagged_script" && !state.taggedScript.approved) {
		return { reason: "awaiting approval: tagged script (script.tagged.md)", forceable: false };
	}
	for (const p of action.params ?? []) if (p.kind === "select" && p.name === "sample" && !voiceSamples().length) return { reason: "no voice samples in voice_samples/", forceable: false };
	return null;
}
