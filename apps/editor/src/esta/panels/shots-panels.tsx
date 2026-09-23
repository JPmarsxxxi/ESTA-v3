"use client";

import { useEffect, useRef, useState } from "react";
import { cn } from "@/utils/ui";
import { api } from "../api";
import { mediaUrl } from "../doc";
import { useWorkspace } from "../store";

// Plan-derived shot timeline and a preview of the selected shot. Both follow the
// workspace's shared shot selection, so clicking here selects in the planner
// and picker and vice versa.

type PlanShot = { shot_number: number; start?: number; end?: number; audio?: string; visual?: { type?: string; desc?: string }; overlay?: unknown };
type Picked = { shot_number: number; picked: { url: string; ok: boolean; source: string } | null; desc: string; type: string };

const TYPE_CLASS: Record<string, string> = {
	REAL_FOOTAGE: "bg-sky-500/25 border-sky-500/60",
	REAL_IMAGE: "bg-emerald-500/25 border-emerald-500/60",
	MOTION_GRAPHICS: "bg-violet-500/25 border-violet-500/60",
	AI_VIDEO: "bg-amber-500/25 border-amber-500/60",
};

function usePlanShots() {
	const { session, lastFile } = useWorkspace();
	const [shots, setShots] = useState<PlanShot[] | null>(null);
	const version = lastFile?.path === "plan.json" ? lastFile.mtimeMs : 0;
	useEffect(() => {
		api<{ shots: PlanShot[] }>(`/_plan/api/plan?session=${encodeURIComponent(session)}`).then(
			(d) => setShots(d.shots),
			() => setShots([]),
		);
	}, [session, version]);
	return shots;
}

export function TimelinePanel() {
	const { selectedShot, selectShot } = useWorkspace();
	const shots = usePlanShots();
	const [pxPerSec, setPxPerSec] = useState(40);
	const refs = useRef(new Map<number, HTMLButtonElement>());

	useEffect(() => {
		if (selectedShot != null) refs.current.get(selectedShot)?.scrollIntoView({ block: "nearest", inline: "center", behavior: "smooth" });
	}, [selectedShot]);

	if (!shots) return <p className="text-muted-foreground p-3 text-sm">Loading…</p>;
	if (!shots.length) return <p className="text-muted-foreground p-3 text-sm">No plan.json yet.</p>;
	const total = Math.max(...shots.map((s) => s.end ?? 0), 1);

	return (
		<div className="flex size-full min-h-0 flex-col text-xs">
			<div className="flex shrink-0 items-center gap-2 border-b px-2 py-1">
				<span className="text-muted-foreground">
					{shots.length} shots · {total.toFixed(1)}s
				</span>
				<label className="text-muted-foreground ml-auto flex items-center gap-1">
					zoom
					<input type="range" min={8} max={160} value={pxPerSec} onChange={(e) => setPxPerSec(Number(e.target.value))} />
				</label>
			</div>
			<div className="min-h-0 flex-1 overflow-x-auto overflow-y-hidden">
				<div className="relative h-full" style={{ width: total * pxPerSec + 16 }}>
					{Array.from({ length: Math.ceil(total / 5) + 1 }, (_, i) => (
						<span key={i} className="text-muted-foreground absolute top-0 border-l pl-0.5 text-[9px]" style={{ left: i * 5 * pxPerSec }}>
							{i * 5}s
						</span>
					))}
					{shots.map((s) => {
						const start = s.start ?? 0;
						const width = Math.max(((s.end ?? start) - start) * pxPerSec, 3);
						const type = s.visual?.type ?? "";
						return (
							<button
								key={s.shot_number}
								ref={(el) => {
									if (el) refs.current.set(s.shot_number, el);
									else refs.current.delete(s.shot_number);
								}}
								type="button"
								title={`${s.shot_number}: ${s.audio ?? ""}`}
								onClick={() => selectShot(s.shot_number)}
								className={cn(
									"absolute top-4 bottom-2 overflow-hidden rounded-sm border px-1 text-left",
									TYPE_CLASS[type] ?? "bg-muted border-border",
									s.shot_number === selectedShot && "ring-primary ring-2",
								)}
								style={{ left: start * pxPerSec, width }}
							>
								<span className="block truncate font-medium">{s.shot_number}</span>
								{width > 60 && <span className="text-muted-foreground block truncate text-[10px]">{s.audio}</span>}
								{Boolean(s.overlay) && <span className="absolute right-0.5 bottom-0.5 rounded bg-violet-500 px-0.5 text-[8px] text-white">OVL</span>}
							</button>
						);
					})}
				</div>
			</div>
		</div>
	);
}

export function PreviewPanel() {
	const { session, selectedShot, lastFile } = useWorkspace();
	const [picked, setPicked] = useState<Picked[] | null>(null);
	const version = lastFile?.path === "assets_progress.jsonl" || lastFile?.path === "plan.json" ? lastFile.mtimeMs : 0;
	useEffect(() => {
		api<{ shots: Picked[] }>(`/_picker/api/shots?session=${encodeURIComponent(session)}`).then(
			(d) => setPicked(d.shots),
			() => setPicked([]),
		);
	}, [session, version]);

	const shot = picked?.find((s) => s.shot_number === selectedShot);
	if (!picked) return <p className="text-muted-foreground p-3 text-sm">Loading…</p>;
	if (!shot) return <p className="text-muted-foreground p-3 text-sm">Select a shot.</p>;
	const url = shot.picked?.ok ? mediaUrl(shot.picked.url) : "";
	const isImage = /\.(jpe?g|png|gif|webp)$/i.test(url);

	return (
		<div className="flex size-full min-h-0 flex-col text-sm">
			<div className="flex min-h-0 flex-1 items-center justify-center bg-black">
				{!url ? (
					<p className="max-w-xs p-4 text-center text-xs text-neutral-400">
						Shot {shot.shot_number} has no media yet.
						<br />
						{shot.desc}
					</p>
				) : isImage ? (
					// eslint-disable-next-line @next/next/no-img-element
					<img src={url} alt={shot.desc} className="max-h-full max-w-full object-contain" />
				) : (
					<video key={url} src={url} controls className="max-h-full max-w-full">
						<track kind="captions" />
					</video>
				)}
			</div>
			<div className="text-muted-foreground shrink-0 truncate border-t px-2 py-1 text-xs">
				shot {shot.shot_number} · {shot.type}
				{shot.picked?.ok ? ` · ${shot.picked.source}` : ""}
			</div>
		</div>
	);
}
