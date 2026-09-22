"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { post, type PipelineState, type Stage, type StageAction } from "../api";
import { useWorkspace } from "../store";
import { BadgeDot, badgeLabel, inputClass } from "../ui";

const CHECKPOINT_FILE: Record<string, string> = {
	requirements: "requirements.json",
	script: "script.md",
	tagged_script: "script.tagged.md",
	plan: "plan.json",
};

const CHECKPOINT_LABEL: Record<string, string> = {
	requirements: "requirements",
	script: "the finalized script",
	tagged_script: "the tagged script",
	plan: "the plan",
};

export function StagePanel() {
	const { pipeline, stage } = useWorkspace();
	const [error, setError] = useState<string | null>(null);
	const st = pipeline?.stages.find((s) => s.id === stage);
	if (!pipeline || !st) return null;
	const actions = pipeline.actions.filter((a) => a.stage === stage);

	return (
		<div className="space-y-4 p-3 text-sm">
			<div className="flex items-center gap-2">
				<BadgeDot badge={st.badge} />
				<h2 className="text-base font-semibold">{st.label}</h2>
				<span className="text-muted-foreground text-xs">{badgeLabel(st.badge)}</span>
			</div>
			<NextHint pipeline={pipeline} />
			{error && (
				<div className="border-destructive/40 bg-destructive/10 flex items-start justify-between gap-2 rounded-md border p-2 text-xs">
					<span className="whitespace-pre-wrap">{error}</span>
					<button type="button" className="text-muted-foreground" onClick={() => setError(null)}>
						dismiss
					</button>
				</div>
			)}
			{!st.inFlow && <p className="text-muted-foreground">This stage is not part of this session&apos;s flow{st.id === "voice-profile" ? " (no example scripts were given)" : ""}.</p>}
			{st.badge === "skipped" && <p className="text-muted-foreground">Skipped{st.id === "script" && pipeline.requirements?.skip_scriptwriter ? ": the script was uploaded with the requirements." : "."}</p>}
			<Gate stage={st} onError={setError} />
			{st.id === "requirements" && <RequirementsApproval pipeline={pipeline} onError={setError} />}
			{st.checkpoint && st.id !== "requirements" && <Approval checkpoint={st.checkpoint} pipeline={pipeline} onError={setError} />}
			{st.id === "voice" && pipeline.taggedScript.exists && <Approval checkpoint="tagged_script" pipeline={pipeline} onError={setError} />}
			{actions.length > 0 && (
				<div className="space-y-2">
					<h3 className="text-muted-foreground text-xs font-medium uppercase">Actions</h3>
					{actions.map((a) => (
						<ActionRow key={a.id} action={a} onError={setError} />
					))}
				</div>
			)}
		</div>
	);
}

function NextHint({ pipeline }: { pipeline: PipelineState }) {
	const n = pipeline.conductorNext;
	const text = n.done ? "Pipeline complete." : n.next ? `Conductor: ${n.next} runs next.` : n.blocked ? `Conductor: ${n.blocked} is blocked (needs ${(n.missing ?? []).join(", ")}).` : "";
	return (
		<p className="text-muted-foreground text-xs">
			{text}
			{n.fallback ? ` (${n.fallback})` : ""}
		</p>
	);
}

function Gate({ stage, onError }: { stage: Stage; onError: (e: string) => void }) {
	const { session } = useWorkspace();
	const [busy, setBusy] = useState(false);
	if (stage.overridden) {
		return <div className="bg-caution/15 rounded-md p-2 text-xs">Forced past its gate. This clears once the missing inputs and approvals are in place.</div>;
	}
	if (!stage.locked) return null;
	const force = async () => {
		setBusy(true);
		try {
			await post({ path: `/_pipeline/${encodeURIComponent(session)}/force`, body: { stage: stage.id } });
		} catch (e) {
			onError(e instanceof Error ? e.message : String(e));
		}
		setBusy(false);
	};
	return (
		<div className="bg-accent space-y-2 rounded-md p-2.5">
			<div className="font-medium">Locked</div>
			<ul className="text-muted-foreground list-inside list-disc text-xs">
				{stage.missing.map((m) => (
					<li key={m}>
						needs <code className="text-foreground">{m}</code>
					</li>
				))}
				{stage.pendingApprovals.map((p) => (
					<li key={p}>awaiting approval: {CHECKPOINT_LABEL[p] ?? p}</li>
				))}
			</ul>
			<Button size="sm" variant="outline" disabled={busy} onClick={force} title="Unlock this stage anyway; the override is recorded in pipeline.json">
				Force / skip gate
			</Button>
		</div>
	);
}

function approvalText(a: { at: string; by: string }) {
	return `${a.by === "import" ? "Carried over from v2" : "Approved"} ${new Date(a.at).toLocaleString()}`;
}

function Approval({ checkpoint, pipeline, onError }: { checkpoint: string; pipeline: PipelineState; onError: (e: string) => void }) {
	const { session } = useWorkspace();
	const approval = pipeline.approvals[checkpoint];
	const file = CHECKPOINT_FILE[checkpoint];
	const exists = pipeline.checkpointFiles[checkpoint];
	const call = async (revoke: boolean) => {
		try {
			await post({ path: `/_pipeline/${encodeURIComponent(session)}/approve`, body: { checkpoint, revoke } });
		} catch (e) {
			onError(e instanceof Error ? e.message : String(e));
		}
	};
	return (
		<div className="space-y-1.5 rounded-md border p-2.5">
			<div className="font-medium">Approve {CHECKPOINT_LABEL[checkpoint]}</div>
			{approval ? (
				<div className="flex items-center justify-between gap-2 text-xs">
					<span className="text-muted-foreground">{approvalText(approval)}</span>
					<Button size="sm" variant="ghost" onClick={() => call(true)}>
						Revoke
					</Button>
				</div>
			) : (
				<div className="flex items-center justify-between gap-2 text-xs">
					<span className="text-muted-foreground">{exists ? `Review ${file}, then approve to unlock what depends on it.` : `Waiting for ${file}.`}</span>
					<Button size="sm" disabled={!exists} onClick={() => call(false)}>
						Approve
					</Button>
				</div>
			)}
		</div>
	);
}

// Approving requirements also lays down the rails: a template (conductor.py
// build) or a custom order that must pass validate_flow.py.
function RequirementsApproval({ pipeline, onError }: { pipeline: PipelineState; onError: (e: string) => void }) {
	const { session } = useWorkspace();
	const [template, setTemplate] = useState(pipeline.template && pipeline.template !== "custom" ? pipeline.template : "standard-vo");
	const [custom, setCustom] = useState("");
	const [showCustom, setShowCustom] = useState(false);
	const approval = pipeline.approvals.requirements;
	const hasReqs = Boolean(pipeline.requirements);
	const base = `/_pipeline/${encodeURIComponent(session)}`;
	const run = async (fn: () => Promise<unknown>) => {
		try {
			await fn();
		} catch (e) {
			onError(e instanceof Error ? e.message : String(e));
		}
	};
	return (
		<div className="space-y-2 rounded-md border p-2.5">
			<div className="font-medium">Approve requirements</div>
			<label className="block space-y-1 text-xs">
				<span className="text-muted-foreground">Flow template</span>
				<select className={inputClass} value={template} onChange={(e) => setTemplate(e.target.value)}>
					{Object.entries(pipeline.templates).map(([name, desc]) => (
						<option key={name} value={name} title={desc}>
							{name}
						</option>
					))}
				</select>
				<span className="text-muted-foreground block">{pipeline.templates[template]}</span>
			</label>
			{approval ? (
				<div className="flex flex-wrap items-center justify-between gap-2 text-xs">
					<span className="text-muted-foreground">
						{approvalText(approval)} · flow: {pipeline.template ?? "canonical"}
					</span>
					<div className="flex gap-1">
						{template !== pipeline.template && (
							<Button size="sm" variant="outline" onClick={() => run(() => post({ path: `${base}/template`, body: { template } }))}>
								Switch to {template}
							</Button>
						)}
						<Button size="sm" variant="ghost" onClick={() => run(() => post({ path: `${base}/approve`, body: { checkpoint: "requirements", revoke: true } }))}>
							Revoke
						</Button>
					</div>
				</div>
			) : (
				<Button size="sm" disabled={!hasReqs} onClick={() => run(() => post({ path: `${base}/approve`, body: { checkpoint: "requirements", template } }))}>
					{hasReqs ? `Approve and build ${template} pipeline` : "Waiting for requirements.json"}
				</Button>
			)}
			<button type="button" className="text-muted-foreground block text-xs underline" onClick={() => setShowCustom(!showCustom)}>
				{showCustom ? "Hide custom order" : "Custom step order…"}
			</button>
			{showCustom && (
				<div className="space-y-1.5">
					<input
						className={`${inputClass} font-mono text-xs`}
						value={custom}
						placeholder="requirements research scriptwriter:author audio:clone timestamps style-analysis plan assets render"
						onChange={(e) => setCustom(e.target.value)}
					/>
					<Button size="sm" variant="outline" disabled={!custom.trim()} onClick={() => run(() => post({ path: `${base}/flow`, body: { tokens: custom.trim().split(/\s+/) } }))}>
						Validate and use this order
					</Button>
				</div>
			)}
		</div>
	);
}

function ActionRow({ action, onError }: { action: StageAction; onError: (e: string) => void }) {
	const { session, sendChat } = useWorkspace();
	const [params, setParams] = useState<Record<string, string>>(() =>
		Object.fromEntries(action.params.filter((p) => p.kind === "select" && p.options?.length).map((p) => [p.name, p.options?.[0] ?? ""])),
	);
	const [busy, setBusy] = useState(false);
	const run = async () => {
		if (action.warn && !window.confirm(action.warn)) return;
		setBusy(true);
		try {
			await post({ path: `/_pipeline/${encodeURIComponent(session)}/run`, body: { action: action.id, params } });
		} catch (e) {
			onError(e instanceof Error ? e.message : String(e));
		}
		setBusy(false);
	};
	const disabled = Boolean(action.blocked) || action.running || busy;
	return (
		<div className="space-y-1.5 rounded-md border p-2.5">
			<div className="flex items-start justify-between gap-2">
				<div className="min-w-0">
					<div className="font-medium">{action.label}</div>
					<div className="text-muted-foreground text-xs">
						{action.kind === "skill" ? "Headless Claude job (cost shown in Jobs)" : "Tool job"}
						{action.hint ? ` · ${action.hint}` : ""}
					</div>
				</div>
				<div className="flex shrink-0 gap-1">
					{action.kind === "skill" && (
						<Button size="sm" variant="ghost" title="Run it interactively in the chat panel instead" onClick={() => sendChat(`Run the ${action.label.toLowerCase()} step for this session.`)}>
							In chat
						</Button>
					)}
					<Button size="sm" disabled={disabled} onClick={run}>
						{action.running ? "Running…" : "Run"}
					</Button>
				</div>
			</div>
			{action.params.length > 0 && (
				<div className="flex flex-wrap gap-2">
					{action.params.map((p) => (
						<label key={p.name} className="flex items-center gap-1.5 text-xs">
							<span className="text-muted-foreground">{p.label}</span>
							{p.kind === "select" ? (
								<select className={`${inputClass} h-7 w-auto py-0`} value={params[p.name] ?? ""} onChange={(e) => setParams({ ...params, [p.name]: e.target.value })}>
									{(p.options ?? []).map((o) => (
										<option key={o} value={o}>
											{o}
										</option>
									))}
								</select>
							) : (
								<input className={`${inputClass} h-7 w-40 py-0`} value={params[p.name] ?? ""} onChange={(e) => setParams({ ...params, [p.name]: e.target.value })} />
							)}
						</label>
					))}
				</div>
			)}
			{action.warn && <div className="text-caution text-xs">{action.warn}</div>}
			{action.blocked && <div className="text-muted-foreground text-xs">Blocked: {action.blocked}</div>}
		</div>
	);
}
