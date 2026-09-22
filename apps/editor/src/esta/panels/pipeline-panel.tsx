"use client";

import { cn } from "@/utils/ui";
import { useWorkspace } from "../store";

const STATE_CLASS: Record<string, string> = {
	done: "text-constructive",
	ready: "text-foreground",
	blocked: "text-muted-foreground",
	skipped: "text-muted-foreground line-through",
};

// Every step of pipeline.json with the same done/ready/blocked verdict conductor.py gives.
export function PipelinePanel() {
	const { pipeline } = useWorkspace();
	if (!pipeline) return null;
	const nextToken = pipeline.conductorNext.next ?? pipeline.conductorNext.blocked;
	return (
		<div className="p-2 text-sm">
			<p className="text-muted-foreground mb-2 text-xs">
				{pipeline.hasPipeline ? `pipeline.json · ${pipeline.template}` : "No pipeline.json yet: canonical standard-vo order."}
			</p>
			<table className="w-full text-xs">
				<thead className="text-muted-foreground text-left">
					<tr>
						<th className="py-1 pr-2 font-normal">#</th>
						<th className="py-1 pr-2 font-normal">step</th>
						<th className="py-1 pr-2 font-normal">state</th>
						<th className="py-1 font-normal">gate</th>
					</tr>
				</thead>
				<tbody>
					{pipeline.steps.map((s) => (
						<tr key={s.token} className={cn("border-t align-top", s.token === nextToken && "bg-accent")}>
							<td className="py-1 pr-2 tabular-nums">{s.order}</td>
							<td className="py-1 pr-2 font-mono">
								{s.token}
								{s.parallel ? <span className="text-muted-foreground"> (parallel)</span> : null}
							</td>
							<td className={cn("py-1 pr-2", STATE_CLASS[s.state])}>{s.state}</td>
							<td className="text-muted-foreground py-1">
								{s.overridden && <span className="text-caution">overridden · </span>}
								{s.missing.length > 0 && <span>needs {s.missing.join(", ")} </span>}
								{s.pendingApprovals.length > 0 && <span>approve {s.pendingApprovals.join(", ")}</span>}
							</td>
						</tr>
					))}
				</tbody>
			</table>
		</div>
	);
}
