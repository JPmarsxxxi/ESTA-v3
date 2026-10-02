"use client";

import { useCallback, useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { cn } from "@/utils/ui";
import { api, BACKEND, post } from "../api";
import { useWorkspace } from "../store";

type Pair = { ours: number; inspo: number };
type Section = {
	name: string;
	score: number | null;
	pass: boolean | null;
	note: string;
	ours?: Record<string, number>;
	inspo?: Record<string, number>;
	features?: Record<string, { ours_median: number; inspo_median: number }>;
	estimate?: boolean;
	rates?: Record<string, Pair>;
	median?: Pair;
	shape?: { ks: number };
};
type Report = {
	overall: number;
	pass: boolean;
	pass_marks: { overall: number; section: number };
	timing: string;
	sections: Record<string, Section>;
	notes: string[];
	locked: number[];
	history: { at: string; round: number | null; overall: number; note: string }[];
	adjust?: { rounds: { round: number; kept: boolean; changes: string[]; why?: string; gain?: number }[]; cost_usd: number };
};
type Reports = { plan: Report | null; final: Report | null; running: string[] };

const KEYS = ["a", "b", "c", "d", "e"];
const pct = (x: number) => `${Math.round(x * 100)}%`;

// The numbers behind a section, in words.
function measured({ k, s }: { k: string; s: Section | undefined }): string {
	if (!s || s.score == null) return s?.note ?? "";
	if (k === "a") {
		const ours = s.ours ?? {};
		const inspo = s.inspo ?? {};
		return Object.keys({ ...ours, ...inspo })
			.map((x) => `${x} ${pct(ours[x] ?? 0)} vs ${pct(inspo[x] ?? 0)}`)
			.join(" · ");
	}
	if (k === "b")
		return Object.entries(s.features ?? {})
			.slice(0, 3)
			.map(([f, v]) => `${f} ${v.ours_median} vs ${v.inspo_median}`)
			.join(" · ");
	if (k === "c") return s.estimate ? "estimate from desc and queries" : "from real frames";
	if (k === "d")
		return Object.entries(s.rates ?? {})
			.map(([r, v]) => `${r} ${v.ours} vs ${v.inspo}`)
			.join(" · ");
	if (k === "e" && s.median) return `median ${s.median.ours}s vs ${s.median.inspo}s` + (s.shape ? ` · shape KS ${s.shape.ks}` : "");
	return "";
}

function Cell({ s }: { s: Section | undefined }) {
	if (!s) return <td className="text-muted-foreground px-1 py-1 text-right">–</td>;
	if (s.score == null) return <td className="text-muted-foreground px-1 py-1 text-right">n/a</td>;
	return <td className={cn("px-1 py-1 text-right tabular-nums", s.pass ? "text-constructive" : "text-destructive")}>{Math.round(s.score)}</td>;
}

export function MatchPanel() {
	const { session, lastFile } = useWorkspace();
	const [data, setData] = useState<Reports | null>(null);
	const [status, setStatus] = useState("");

	const load = useCallback(() => {
		api<Reports>(`/_match/${encodeURIComponent(session)}`)
			.then(setData)
			.catch((e) => setStatus(e instanceof Error ? e.message : "failed to load"));
	}, [session]);
	useEffect(load, [load]);
	useEffect(() => {
		if (lastFile?.session === session && /^match_(plan|final)\.json$/.test(lastFile.path)) load();
	}, [lastFile, session, load]);

	const rescore = async (stage: "plan" | "final") => {
		try {
			await post({ path: `/_match/${encodeURIComponent(session)}/rescore`, body: { stage } });
			setStatus(`re-scoring ${stage}…`);
		} catch (e) {
			setStatus(e instanceof Error ? e.message : "failed");
		}
	};

	const plan = data?.plan ?? null;
	const final = data?.final ?? null;
	const any = plan ?? final;
	const rounds = [...(plan?.adjust?.rounds ?? []).map((r) => ({ ...r, stage: "plan" })), ...(final?.adjust?.rounds ?? []).map((r) => ({ ...r, stage: "final" }))];
	const notes = [...new Set([...(plan?.notes ?? []), ...(final?.notes ?? [])])];

	return (
		<div className="flex size-full min-h-0 flex-col overflow-auto p-2 text-sm">
			<div className="mb-2 flex items-center justify-between gap-2">
				<span className="text-muted-foreground text-xs">
					{any ? `pass: overall ≥ ${any.pass_marks.overall}, each section ≥ ${any.pass_marks.section}` : "Not scored yet. Run “Match the inspo” in the Stage panel."}
				</span>
				<div className="flex shrink-0 gap-1">
					<Button size="sm" variant="outline" disabled={!any} onClick={() => window.open(`${BACKEND}/_match/${encodeURIComponent(session)}/review`, "_blank")}>
						Open side-by-side
					</Button>
					<Button size="sm" variant="outline" disabled={!plan} onClick={() => rescore("plan")}>
						Re-score plan
					</Button>
					<Button size="sm" variant="outline" disabled={!final} onClick={() => rescore("final")}>
						Re-score final
					</Button>
				</div>
			</div>
			{(status || data?.running.length) && <p className="text-muted-foreground mb-2 text-xs">{data?.running.length ? `running: ${data.running.join(", ")}` : status}</p>}
			{any && (
				<table className="w-full text-xs">
					<thead className="text-muted-foreground">
						<tr>
							<th className="py-1 pr-2 text-left font-normal">section</th>
							<th className="px-1 py-1 text-right font-normal">Plan</th>
							<th className="px-1 py-1 text-right font-normal">Final</th>
							<th className="py-1 pl-2 text-left font-normal">measured (ours vs inspo)</th>
						</tr>
					</thead>
					<tbody>
						{KEYS.map((k) => {
							const s = final?.sections[k] ?? plan?.sections[k];
							return (
								<tr key={k} className="border-t align-top">
									<td className="py-1 pr-2 whitespace-nowrap">
										{k}. {s?.name}
									</td>
									<Cell s={plan?.sections[k]} />
									<Cell s={final?.sections[k]} />
									<td className="text-muted-foreground py-1 pl-2">{measured({ k, s })}</td>
								</tr>
							);
						})}
						<tr className="border-t font-medium">
							<td className="py-1 pr-2">Overall</td>
							<td className={cn("px-1 py-1 text-right tabular-nums", plan && (plan.pass ? "text-constructive" : "text-destructive"))}>{plan ? Math.round(plan.overall) : "–"}</td>
							<td className={cn("px-1 py-1 text-right tabular-nums", final && (final.pass ? "text-constructive" : "text-destructive"))}>{final ? Math.round(final.overall) : "–"}</td>
							<td className="text-muted-foreground py-1 pl-2 font-normal">
								{plan?.timing === "estimated" ? "plan timing is a 150 wpm estimate" : ""}
								{(final ?? plan)?.locked.length ? ` · ${(final ?? plan)?.locked.length} locked shots are left alone` : ""}
							</td>
						</tr>
					</tbody>
				</table>
			)}
			{notes.length > 0 && (
				<ul className="text-caution mt-2 list-disc pl-4 text-xs">
					{notes.map((n) => (
						<li key={n}>{n}</li>
					))}
				</ul>
			)}
			{rounds.length > 0 && (
				<div className="mt-3">
					<div className="text-muted-foreground mb-1 text-xs">Adjust history</div>
					{rounds.map((r) => (
						<details key={`${r.stage}-${r.round}`} className="border-t py-1 text-xs">
							<summary className="cursor-pointer">
								{r.stage} round {r.round}: {r.kept ? `kept (+${r.gain ?? 0})` : r.why || "stopped"} · {r.changes.length} changes
							</summary>
							<ul className="text-muted-foreground mt-1 list-disc pl-4">
								{r.changes.slice(0, 40).map((c) => (
									<li key={c}>{c}</li>
								))}
							</ul>
						</details>
					))}
				</div>
			)}
		</div>
	);
}
