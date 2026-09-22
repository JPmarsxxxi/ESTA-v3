"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/ui";
import { apiText, post, type Job } from "../api";
import { useWorkspace } from "../store";

const STATUS_CLASS: Record<Job["status"], string> = {
	running: "text-primary",
	done: "text-constructive",
	failed: "text-destructive",
	cancelled: "text-muted-foreground",
	interrupted: "text-caution",
};

function duration(job: Job) {
	const s = Math.round(((job.endedAt ?? Date.now()) - job.startedAt) / 1000);
	return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`;
}

export function JobsPanel() {
	const { jobs, logs, appendLog, stage } = useWorkspace();
	const [selected, setSelected] = useState<string | null>(null);
	const [onlyStage, setOnlyStage] = useState(false);
	const logRef = useRef<HTMLPreElement>(null);
	const shown = onlyStage ? jobs.filter((j) => j.stage === stage) : jobs;
	const job = jobs.find((j) => j.id === selected) ?? shown[0] ?? null;

	// The full log is fetched once; live lines then arrive over the shared event stream.
	useEffect(() => {
		if (!job || job.id in logs) return;
		apiText(`/_jobs/${job.id}/log`)
			.then((text) => appendLog({ id: job.id, text, replace: true }))
			.catch(() => {});
	}, [job, logs, appendLog]);

	const log = job ? logs[job.id] : undefined;
	useEffect(() => {
		const el = logRef.current;
		if (el && el.scrollHeight - el.scrollTop - el.clientHeight < 80) el.scrollTop = el.scrollHeight;
	}, [log]);

	if (!jobs.length) return <p className="text-muted-foreground p-3 text-sm">No jobs yet. Stage actions run here in the background.</p>;

	return (
		<div className="flex size-full min-h-0 flex-col text-sm">
			<div className="flex max-h-[45%] shrink-0 flex-col overflow-auto border-b">
				<label className="text-muted-foreground flex items-center gap-1.5 px-2 py-1 text-xs">
					<input type="checkbox" checked={onlyStage} onChange={(e) => setOnlyStage(e.target.checked)} />
					this stage only
				</label>
				{shown.map((j) => (
					<button
						key={j.id}
						type="button"
						onClick={() => setSelected(j.id)}
						className={cn("flex items-center gap-2 px-2 py-1.5 text-left", job?.id === j.id ? "bg-accent" : "hover:bg-accent/60")}
					>
						<span className={cn("w-20 shrink-0 text-xs", STATUS_CLASS[j.status])}>{j.status}</span>
						<span className="min-w-0 flex-1 truncate">{j.label}</span>
						{j.progress && (
							<span className="text-muted-foreground shrink-0 text-xs">
								{j.progress.total ? `${Math.round((j.progress.done / j.progress.total) * 100)}%` : j.progress.label}
							</span>
						)}
						{j.cost != null && <span className="text-muted-foreground shrink-0 text-xs">${j.cost.toFixed(3)}</span>}
						<span className="text-muted-foreground w-14 shrink-0 text-right text-xs tabular-nums">{duration(j)}</span>
					</button>
				))}
			</div>
			{job && (
				<div className="flex min-h-0 flex-1 flex-col">
					<div className="flex shrink-0 items-center justify-between gap-2 px-2 py-1.5">
						<div className="min-w-0">
							<div className="truncate font-medium">{job.label}</div>
							<div className="text-muted-foreground truncate text-xs">
								{job.stage} · {new Date(job.startedAt).toLocaleTimeString()}
								{job.detached ? " · detached (output lost on restart)" : ""}
								{job.error ? ` · ${job.error}` : ""}
							</div>
						</div>
						<div className="flex shrink-0 gap-1">
							{job.status === "running" ? (
								<Button size="sm" variant="destructive-foreground" onClick={() => post({ path: `/_jobs/${job.id}/cancel` })}>
									Cancel
								</Button>
							) : (
								<Button
									size="sm"
									variant="outline"
									onClick={async () => {
										const { job: next } = await post<{ job: Job }>({ path: `/_jobs/${job.id}/retry` });
										setSelected(next.id);
									}}
								>
									Retry
								</Button>
							)}
						</div>
					</div>
					{job.progress && job.progress.total > 0 && (
						<div className="mx-2 mb-1.5 h-1 shrink-0 rounded bg-accent">
							<div className="bg-primary h-1 rounded" style={{ width: `${Math.min(100, (job.progress.done / job.progress.total) * 100)}%` }} />
						</div>
					)}
					<pre ref={logRef} className="bg-accent/40 min-h-0 flex-1 overflow-auto px-2 py-1.5 font-mono text-[11px] leading-snug whitespace-pre-wrap">
						{log ?? "Loading log…"}
					</pre>
				</div>
			)}
		</div>
	);
}
