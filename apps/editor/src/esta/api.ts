export const BACKEND = process.env.NEXT_PUBLIC_ESTA_BACKEND || "http://localhost:8787";

// Identifies this tab's own writes in file events, so a save doesn't echo back
// as an "external change".
export const CLIENT_ID =
	typeof crypto !== "undefined" && "randomUUID" in crypto ? crypto.randomUUID() : String(Math.random());

export class ApiError extends Error {
	status: number;
	body: Record<string, unknown>;
	constructor({ status, body }: { status: number; body: Record<string, unknown> }) {
		super(typeof body.error === "string" ? body.error : `HTTP ${status}`);
		this.status = status;
		this.body = body;
	}
}

async function request<T>({ path, method, body: payload }: { path: string; method: string; body?: unknown }): Promise<T> {
	const res = await fetch(BACKEND + path, {
		method,
		headers: { "Content-Type": "application/json", "X-Esta-Client": CLIENT_ID },
		body: payload !== undefined ? JSON.stringify(payload) : undefined,
		cache: "no-store",
	});
	const text = await res.text();
	let body: Record<string, unknown> = {};
	try {
		body = text ? JSON.parse(text) : {};
	} catch {
		body = { error: text };
	}
	if (!res.ok) throw new ApiError({ status: res.status, body });
	const out: T = JSON.parse(text || "{}");
	return out;
}

export const api = <T>(path: string) => request<T>({ path, method: "GET" });
export const post = <T>({ path, body }: { path: string; body?: unknown }) => request<T>({ path, method: "POST", body: body ?? {} });

export async function apiText(path: string) {
	const res = await fetch(BACKEND + path, { cache: "no-store" });
	if (!res.ok) throw new ApiError({ status: res.status, body: { error: await res.text() } });
	return res.text();
}

export const sessionFileUrl = ({ session, path }: { session: string; path: string }) =>
	`${BACKEND}/api/sessions/${encodeURIComponent(session)}/${path.split("/").map(encodeURIComponent).join("/")}`;

export type Badge = "idle" | "running" | "failed" | "done" | "overridden" | "locked" | "review" | "skipped" | "not-in-flow";

export type Stage = {
	id: string;
	label: string;
	checkpoint: string | null;
	approval: { at: string; by: string } | null;
	inFlow: boolean;
	badge: Badge;
	isNext: boolean;
	steps: string[];
	current: string | null;
	locked: boolean;
	missing: string[];
	pendingApprovals: string[];
	overridden: boolean;
};

export type StepState = {
	order: number;
	token: string;
	skill: string;
	state: "skipped" | "done" | "ready" | "blocked";
	needs: string[];
	produces: string[];
	missing: string[];
	pendingApprovals: string[];
	locked: boolean;
	overridden: boolean;
	parallel: boolean;
};

export type ActionParam = { name: string; label: string; kind: "select" | "text"; options?: string[]; optional?: boolean };

export type StageAction = {
	id: string;
	stage: string;
	label: string;
	hint: string | null;
	warn: string | null;
	kind: "tool" | "skill";
	params: ActionParam[];
	blocked: string | null;
	forceable: boolean;
	running: boolean;
};

export type PipelineState = {
	session: string;
	hasPipeline: boolean;
	template: string | null;
	conductorNext: { next?: string; blocked?: string; missing?: string[]; done?: boolean; fallback?: string };
	requirements: { topic: string; skip_scriptwriter: boolean; example_scripts_is_list: boolean } | null;
	approvals: Record<string, { at: string; by: string }>;
	overrides: Record<string, { at: string; missing: string[]; pendingApprovals: string[] }>;
	taggedScript: { exists: boolean; approved: boolean };
	checkpointFiles: Record<string, boolean>;
	steps: StepState[];
	stages: Stage[];
	actions: StageAction[];
	preflight: { esta: boolean; conda: boolean; claude: string };
	templates: Record<string, string>;
};

export type Job = {
	id: string;
	session: string;
	stage: string;
	action: string;
	label: string;
	kind: "tool" | "skill";
	cmd: string;
	args: string[];
	status: "running" | "done" | "failed" | "cancelled" | "interrupted";
	startedAt: number;
	endedAt: number | null;
	exitCode: number | null;
	error: string | null;
	cost: number | null;
	progress: { done: number; total: number; label: string } | null;
	detached?: boolean;
};

export type FileEvent = { session: string; path: string; exists: boolean; mtimeMs: number; size: number; by: string | null };

export type SessionSummary = { id: string; topic: string; template: string | null; modifiedAt: number; hasProject: boolean; existsInV3?: boolean };
